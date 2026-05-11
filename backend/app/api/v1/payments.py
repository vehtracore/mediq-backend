"""
Payments Router
================
Owns all Paystack-facing HTTP surface area for the MDQ+ platform.

Exposes:
  POST /api/v1/payments/initialize     — Server-side Paystack transaction init.
                                         Accepts (email, amount_kobo, reference)
                                         and returns an authorization_url so the
                                         Secret Key never touches the client.
  POST /api/v1/payments/webhook        — HMAC-verified Paystack webhook with
                                         reference-based routing and a Dead
                                         Letter Queue (DLQ) fallback.
  GET  /api/v1/payments/verify/{ref}   — Manual transaction verification for
                                         when the app loses connection before
                                         the webhook fires.

Security model
--------------
Paystack signs every outbound webhook payload with the account's secret key
using HMAC-SHA512. We recompute that digest from the raw request body (before
any JSON decoding) and compare with a timing-safe equality check. Any request
that fails this check is rejected with HTTP 400 before it touches the database.

Reference format
----------------
New format embedded by the Flutter client:
    MDQ-{transaction_type}-{appointment_id}-{user_id}-{epoch_ms}
    e.g.  MDQ-gp_consult-123-456-1777195558454

Old underscore-delimited references are handled gracefully (no IDs extracted).
"""

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.failed_webhook import FailedWebhook
from app.models.user import User
from app.services.email_service import send_transactional_email

logger = logging.getLogger(__name__)

# ── Paystack credentials ───────────────────────────────────────────────────────
PAYSTACK_SECRET_KEY: str = os.environ.get("PAYSTACK_SECRET_KEY", "")
if not PAYSTACK_SECRET_KEY:
    logger.warning(
        "[PAYMENTS] ⚠️  PAYSTACK_SECRET_KEY is not set. "
        "The /webhook endpoint will reject every incoming request."
    )

PAYSTACK_VERIFY_URL = "https://api.paystack.co/transaction/verify"
PAYSTACK_INITIALIZE_URL = "https://api.paystack.co/transaction/initialize"

router = APIRouter()


# ─── Schemas ──────────────────────────────────────────────────────────────────

class PaymentInitializeRequest(BaseModel):
    """
    Request body for POST /api/v1/payments/initialize.

    Fields
    ------
    email      : The customer's email address forwarded to Paystack.
    amount     : Transaction amount in **Kobo** (Naira × 100). Must be > 0.
                 Required by Paystack even when a plan code is supplied.
    reference  : The pre-generated MDQ reference string. The backend stores this
                 on the Appointment row before calling /initialize so the watchdog
                 and webhook can locate the record immediately upon receipt.
    plan       : Optional Paystack Plan Code (e.g. ``PLN_xxxx``) for recurring
                 subscriptions. When present, Paystack will create a subscription
                 against this plan instead of a one-time charge. Omit entirely
                 (or pass null) for one-time consultation payments.
    """

    email: EmailStr
    amount: int = Field(..., gt=0, description="Amount in Kobo (Naira × 100)")
    reference: str = Field(..., min_length=8, description="MDQ-prefixed transaction reference")
    plan: Optional[str] = Field(
        default=None,
        description="Paystack Plan Code for recurring subscriptions (e.g. PLN_xxxx). "
                    "Omit for one-time payments.",
    )


# ─── Initialize Endpoint ──────────────────────────────────────────────────────

@router.post("/initialize", status_code=200)
async def initialize_transaction(payload: PaymentInitializeRequest):
    """
    POST /api/v1/payments/initialize

    Exchanges the client-supplied (email, amount, reference) for a Paystack
    ``authorization_url`` and ``access_code``.  The Secret Key is used here on
    the server and is never forwarded to the Flutter client.

    Flow
    ----
    1. Flutter builds the MDQ reference and calls this endpoint.
    2. This endpoint calls Paystack /transaction/initialize with the Secret Key.
    3. Paystack returns an authorization_url + access_code.
    4. We return those two values to the Flutter app.
    5. Flutter opens the authorization_url in a WebView (flutter_paystack_plus
       can accept a checkout URL directly, no Secret Key required).
    6. After the user pays, Paystack fires a webhook to /webhook which confirms
       the DB record using the same reference.

    Error responses
    ---------------
    503  Payment service unavailable — PAYSTACK_SECRET_KEY not configured.
    502  Bad Gateway              — Could not reach Paystack.
    400  Bad Request              — Paystack rejected the initialization request.
    """

    if not PAYSTACK_SECRET_KEY:
        raise HTTPException(
            status_code=503,
            detail="Payment service unavailable — secret key not configured.",
        )

    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }
    # Base payload — amount is always required by Paystack even for plan-based
    # recurring charges, so we never omit it regardless of whether plan is set.
    body: dict = {
        "email": payload.email,
        "amount": payload.amount,
        "reference": payload.reference,
    }
    # Conditionally attach the Plan Code for recurring subscriptions.
    if payload.plan:
        body["plan"] = payload.plan

    logger.info(
        "[PAYMENTS] Initializing transaction | reference='%s' | email='%s' "
        "| amount=%d kobo | plan=%s",
        payload.reference,
        payload.email,
        payload.amount,
        payload.plan or "(one-time)",
    )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                PAYSTACK_INITIALIZE_URL,
                headers=headers,
                json=body,
            )
    except httpx.RequestError as exc:
        logger.error("[PAYMENTS] HTTP error reaching Paystack /initialize: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="Could not reach Paystack. Please try again.",
        )

    resp_data: dict = resp.json()

    if not resp.is_success or not resp_data.get("status"):
        error_msg: str = resp_data.get("message", "Unknown error from Paystack")
        logger.error(
            "[PAYMENTS] ❌ Paystack initialization failed | HTTP %s | message='%s' | reference='%s'",
            resp.status_code,
            error_msg,
            payload.reference,
        )
        raise HTTPException(
            status_code=400,
            detail=f"Paystack error: {error_msg}",
        )

    tx: dict = resp_data.get("data", {})
    authorization_url: str = tx.get("authorization_url", "")
    access_code: str = tx.get("access_code", "")

    logger.info(
        "[PAYMENTS] ✅ Transaction initialized | reference='%s' | access_code='%s'",
        payload.reference,
        access_code,
    )

    return {
        "authorization_url": authorization_url,
        "access_code": access_code,
        "reference": payload.reference,
    }


# ─── Shared helpers ───────────────────────────────────────────────────────────

def _parse_reference(reference: str) -> tuple[str, str | None, str | None]:
    """
    Parse an MDQ reference string and return:
        (transaction_type, appointment_id_str, user_id_str)

    New dash-delimited format:
        MDQ-{type}-{appointment_id}-{user_id}-{timestamp}
    Old underscore format (no embedded IDs):
        MDQ_{type}_{timestamp}

    Returns empty strings / None for fields that cannot be extracted.
    """
    ref_parts = reference.split("-")
    # Expect at least 5 segments: MDQ | type | appt_id | user_id | timestamp
    ref_appointment_id: str | None = ref_parts[2] if len(ref_parts) >= 5 else None
    ref_user_id: str | None = ref_parts[3] if len(ref_parts) >= 5 else None

    transaction_type = ""
    if "gp_consult" in reference:
        transaction_type = "gp_consult"
    elif "specialist" in reference:
        transaction_type = "specialist_consult"
    elif "family_subscription" in reference:   # must precede plain "sub" check
        transaction_type = "family_subscription"
    elif "sub" in reference:
        transaction_type = "subscription"

    return transaction_type, ref_appointment_id, ref_user_id


def _apply_db_update(
    transaction_type: str,
    ref_appointment_id: str | None,
    ref_user_id: str | None,
    reference: str,
    db: Session,
    background_tasks: BackgroundTasks | None = None,
) -> dict:
    """
    Execute the database update for a confirmed Paystack transaction.

    Returns a dict describing what was done (used for both the webhook
    response and the verify endpoint response).

    Raises ValueError with a descriptive message if the required IDs are
    missing or the target record is not found — callers must handle this.
    """
    # ── Flow A: Individual subscription upgrade ───────────────────────────────
    # ── Flow A2: Family Plan upgrade (payer + all dependents) ─────────────────
    if transaction_type in ("subscription", "family_subscription"):
        if not ref_user_id:
            raise ValueError(
                f"{transaction_type}: reference missing user_id segment (ref='{reference}')"
            )

        user: User | None = db.query(User).filter(User.id == int(ref_user_id)).first()
        if not user:
            raise ValueError(
                f"{transaction_type}: user id={ref_user_id} not found"
            )

        # ── Upgrade the primary payer ──────────────────────────────────────────
        expiry = datetime.utcnow() + timedelta(days=30)
        user.plan = "family" if transaction_type == "family_subscription" else "premium"
        user.subscription_expiry = expiry
        db.commit()
        db.refresh(user)

        logger.info(
            "[PAYMENTS] ✅ Subscription upgraded — user_id=%s (%s) | type=%s | expiry=%s",
            user.id,
            user.email,
            transaction_type,
            user.subscription_expiry,
        )

        # ── Flow A2 only: Bulk-upgrade all linked dependents ───────────────────
        upgraded_dependents: list[int] = []
        if transaction_type == "family_subscription":
            dependents: list[User] = (
                db.query(User)
                .filter(User.primary_account_id == user.id)
                .all()
            )
            for dep in dependents:
                dep.plan = "family"
                dep.subscription_expiry = expiry

            if dependents:
                db.commit()
                upgraded_dependents = [d.id for d in dependents]
                logger.info(
                    "[PAYMENTS] ✅ Family Plan — upgraded %d dependent(s) | ids=%s | expiry=%s",
                    len(dependents),
                    upgraded_dependents,
                    expiry,
                )
            else:
                logger.info(
                    "[PAYMENTS] ℹ️  Family Plan — primary user_id=%s has no linked dependents.",
                    user.id,
                )

        # ── Queue confirmation email ───────────────────────────────────────────
        if background_tasks and user.email:
            expiry_str = user.subscription_expiry.strftime('%d %B %Y')
            plan_label = "MDQ+ Family Plan" if transaction_type == "family_subscription" else "MDQ+ Premium"
            family_note = (
                f"<p>This plan also covers <strong>{len(upgraded_dependents)} linked member(s)</strong> "
                f"on your family account.</p>"
                if transaction_type == "family_subscription"
                else ""
            )
            html_body = f"""
            <div style="font-family:sans-serif;max-width:520px;margin:auto;">
              <h2 style="color:#4A90E2;">{plan_label} Activated 🎉</h2>
              <p>Hi {user.first_name or 'there'},</p>
              <p>Your <strong>{plan_label}</strong> subscription is now active!</p>
              <p>Your plan has been upgraded and will remain active until
              <strong>{expiry_str}</strong>.</p>
              {family_note}
              <p>You now have access to:</p>
              <ul>
                <li>Unlimited AI health chats</li>
                <li>Priority doctor access</li>
                <li>Urinalysis AI &amp; advanced analytics</li>
                <li>Consultation summaries</li>
              </ul>
              <p style="color:#888;font-size:13px;">— The MDQ+ Team</p>
            </div>
            """
            background_tasks.add_task(
                send_transactional_email,
                to_email=user.email,
                subject=f"{plan_label} Activated 🎉",
                html_body=html_body,
            )

        return {
            "action": "subscription_upgraded",
            "plan": transaction_type,
            "user_id": user.id,
            "expiry": str(user.subscription_expiry),
            "dependents_upgraded": upgraded_dependents,
        }

    # ── Flow B: Appointment payment confirmation ───────────────────────────────
    elif transaction_type in ("gp_consult", "specialist_consult"):
        from app.models.appointment import Appointment  # local import → no circular dep

        if not ref_appointment_id:
            raise ValueError(
                f"{transaction_type}: reference missing appointment_id segment "
                f"(ref='{reference}')"
            )

        appt: Appointment | None = (
            db.query(Appointment)
            .filter(Appointment.id == int(ref_appointment_id))
            .first()
        )
        if not appt:
            raise ValueError(
                f"{transaction_type}: appointment id={ref_appointment_id} not found"
            )

        appt.payment_status = "paid"
        appt.status = "confirmed"
        db.commit()
        db.refresh(appt)

        logger.info(
            "[PAYMENTS] ✅ Appointment confirmed — appt_id=%s | type=%s | patient_id=%s",
            appt.id,
            transaction_type,
            appt.patient_id,
        )

        # ── Queue appointment confirmation email ───────────────────────────
        # Look up the patient's email from the User table using patient_id.
        if background_tasks and appt.patient_id:
            patient: User | None = (
                db.query(User).filter(User.id == appt.patient_id).first()
            )
            if patient and patient.email:
                type_label = (
                    "GP Consultation"
                    if transaction_type == "gp_consult"
                    else "Specialist Consultation"
                )
                html_body = f"""
                <div style="font-family:sans-serif;max-width:520px;margin:auto;">
                  <h2 style="color:#4A90E2;">Appointment Confirmed ✅</h2>
                  <p>Hi {patient.first_name or 'there'},</p>
                  <p>Your <strong>{type_label}</strong> payment has been
                  confirmed and your appointment is now booked.</p>
                  <table style="border-collapse:collapse;width:100%;margin:16px 0;">
                    <tr style="background:#f5f5f5;">
                      <td style="padding:8px 12px;font-weight:bold;">Appointment ID</td>
                      <td style="padding:8px 12px;">#{appt.id}</td>
                    </tr>
                    <tr>
                      <td style="padding:8px 12px;font-weight:bold;">Reference</td>
                      <td style="padding:8px 12px;font-size:12px;color:#555;">{reference}</td>
                    </tr>
                    <tr style="background:#f5f5f5;">
                      <td style="padding:8px 12px;font-weight:bold;">Type</td>
                      <td style="padding:8px 12px;">{type_label}</td>
                    </tr>
                  </table>
                  <p>Your doctor will be in touch shortly. Open the
                  <strong>MDQ+ app</strong> to join your session at the
                  scheduled time.</p>
                  <p>Questions? Reply to this email or contact support in
                  the app.</p>
                  <p style="color:#888;font-size:13px;">— The MDQ+ Team</p>
                </div>
                """
                background_tasks.add_task(
                    send_transactional_email,
                    to_email=patient.email,
                    subject="MDQ+ Appointment Confirmed ✅",
                    html_body=html_body,
                )

        return {
            "action": "appointment_confirmed",
            "appointment_id": appt.id,
            "transaction_type": transaction_type,
        }

    # ── Unrecognised type ──────────────────────────────────────────────────────
    else:
        logger.warning(
            "[PAYMENTS] Unrecognised transactionType='%s' — no action taken.",
            transaction_type,
        )
        return {"action": "ignored", "reason": f"unrecognised type '{transaction_type}'"}


def _write_dlq(
    reference: str,
    event_type: str,
    payload: dict,
    error_message: str,
    db: Session,
) -> None:
    """Persist a failed event to the failed_webhooks Dead Letter Queue."""
    try:
        dlq_entry = FailedWebhook(
            reference=reference,
            event_type=event_type,
            payload=json.dumps(payload),
            error_message=error_message,
        )
        db.add(dlq_entry)
        db.commit()
        logger.error(
            "[PAYMENTS] ⚠️  Event routed to DLQ — reference='%s' | error='%s'",
            reference,
            error_message,
        )
    except Exception as dlq_exc:
        # DLQ write itself failed — last-resort log, don't raise
        logger.critical(
            "[PAYMENTS] 🚨 DLQ write FAILED — reference='%s' | dlq_error='%s'",
            reference,
            dlq_exc,
        )


# ─── Webhook ──────────────────────────────────────────────────────────────────

@router.post("/webhook", status_code=200)
async def paystack_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    POST /api/v1/payments/webhook

    1. Verifies the HMAC-SHA512 signature from Paystack.
    2. Parses the reference string to extract transaction type + DB IDs.
    3. Updates the database (subscription or appointment).
    4. On any DB failure, writes to the failed_webhooks DLQ instead of
       raising — so Paystack receives 200 and stops retrying a
       structurally unprocessable event.

    Always returns HTTP 200 so Paystack never enters a retry loop for
    events we deliberately ignore or route to the DLQ.
    """

    # ── 1. Read raw body BEFORE any parsing ───────────────────────────────────
    body: bytes = await request.body()

    # ── 2. Extract Paystack signature header ──────────────────────────────────
    signature: str = request.headers.get("x-paystack-signature", "")
    if not signature:
        logger.warning("[WEBHOOK] Request missing x-paystack-signature header — rejected.")
        raise HTTPException(status_code=400, detail="Missing signature header")

    # ── 3. Recompute HMAC-SHA512 digest ───────────────────────────────────────
    expected_hash: str = hmac.new(
        PAYSTACK_SECRET_KEY.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha512,
    ).hexdigest()

    # ── 4. Timing-attack-safe comparison ─────────────────────────────────────
    if not hmac.compare_digest(expected_hash, signature):
        logger.warning("[WEBHOOK] Signature mismatch — request rejected.")
        raise HTTPException(status_code=400, detail="Invalid signature")

    # ── 5. Parse payload ──────────────────────────────────────────────────────
    try:
        payload: dict = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Malformed JSON payload")

    data: dict = payload.get("data") or {}
    reference: str = data.get("reference", "")
    raw_event: str = payload.get("event", "unknown")

    # ── 6. Parse reference string ─────────────────────────────────────────────
    transaction_type, ref_appointment_id, ref_user_id = _parse_reference(reference)

    logger.info(
        "[WEBHOOK] Received event='%s' | reference='%s' | transactionType='%s' "
        "| appointment_id='%s' | user_id='%s'",
        raw_event,
        reference,
        transaction_type,
        ref_appointment_id,
        ref_user_id,
    )

    # ── 7. Database update — wrapped in DLQ fallback ──────────────────────────
    try:
        result = _apply_db_update(
            transaction_type=transaction_type,
            ref_appointment_id=ref_appointment_id,
            ref_user_id=ref_user_id,
            reference=reference,
            db=db,
            background_tasks=background_tasks,
        )
    except Exception as exc:
        db.rollback()  # ensure the session is clean before the DLQ write
        _write_dlq(
            reference=reference,
            event_type=raw_event,
            payload=payload,
            error_message=str(exc),
            db=db,
        )
        return {
            "status": "success",
            "detail": "event routed to DLQ — see failed_webhooks table",
        }

    return {"status": "success", **result}


# ─── Manual Verification Endpoint ────────────────────────────────────────────

@router.get("/verify/{reference}")
async def verify_transaction(
    reference: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    GET /api/v1/payments/verify/{reference}

    Called by the Flutter app when it suspects a successful payment was
    not reflected in the UI (e.g. the app was backgrounded before the
    webhook fired).

    Flow:
      1. Queries Paystack's /transaction/verify/{reference} endpoint.
      2. If Paystack reports status == "success", runs the exact same
         reference-parsing + DB-update logic as the webhook.
      3. Returns the final status so the app can refresh its UI.
    """

    if not PAYSTACK_SECRET_KEY:
        raise HTTPException(
            status_code=503,
            detail="Payment verification is unavailable — secret key not configured.",
        )

    # ── 1. Query Paystack ─────────────────────────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{PAYSTACK_VERIFY_URL}/{reference}",
                headers={"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"},
            )
        paystack_data: dict = resp.json()
    except httpx.RequestError as exc:
        logger.error("[VERIFY] HTTP error reaching Paystack: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="Could not reach Paystack verification endpoint.",
        )

    # ── 2. Inspect Paystack's verdict ─────────────────────────────────────────
    if not paystack_data.get("status"):
        logger.warning(
            "[VERIFY] Paystack returned an error for reference='%s': %s",
            reference,
            paystack_data.get("message"),
        )
        raise HTTPException(
            status_code=402,
            detail=paystack_data.get("message", "Transaction not found on Paystack."),
        )

    tx_data: dict = paystack_data.get("data") or {}
    paystack_status: str = tx_data.get("status", "")

    if paystack_status != "success":
        logger.info(
            "[VERIFY] Transaction reference='%s' is NOT successful (status='%s').",
            reference,
            paystack_status,
        )
        return {
            "verified": False,
            "paystack_status": paystack_status,
            "detail": "Transaction is not yet successful.",
        }

    # ── 3. Parse reference and update database ────────────────────────────────
    transaction_type, ref_appointment_id, ref_user_id = _parse_reference(reference)

    logger.info(
        "[VERIFY] ✅ Paystack confirmed success — reference='%s' | type='%s' "
        "| appointment_id='%s' | user_id='%s'",
        reference,
        transaction_type,
        ref_appointment_id,
        ref_user_id,
    )

    try:
        result = _apply_db_update(
            transaction_type=transaction_type,
            ref_appointment_id=ref_appointment_id,
            ref_user_id=ref_user_id,
            reference=reference,
            db=db,
            background_tasks=background_tasks,
        )
    except Exception as exc:
        db.rollback()
        logger.error(
            "[VERIFY] DB update failed for reference='%s': %s", reference, exc
        )
        raise HTTPException(
            status_code=500,
            detail=f"Payment verified by Paystack, but DB update failed: {exc}",
        )

    return {
        "verified": True,
        "paystack_status": paystack_status,
        **result,
    }
