"""
Payments Router
================
Owns all Paystack-facing HTTP surface area for the MDQ+ platform.

Exposes:
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

router = APIRouter()


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
    # ── Flow A: Subscription upgrade ──────────────────────────────────────────
    if transaction_type == "subscription":
        if not ref_user_id:
            raise ValueError(
                f"subscription: reference missing user_id segment (ref='{reference}')"
            )

        user: User | None = db.query(User).filter(User.id == int(ref_user_id)).first()
        if not user:
            raise ValueError(
                f"subscription: user id={ref_user_id} not found"
            )

        user.plan = "premium"
        user.subscription_expiry = datetime.utcnow() + timedelta(days=30)
        db.commit()
        db.refresh(user)

        logger.info(
            "[PAYMENTS] ✅ Subscription upgraded — user_id=%s (%s) | expiry=%s",
            user.id,
            user.email,
            user.subscription_expiry,
        )

        # ── Queue subscription confirmation email ──────────────────────────
        if background_tasks and user.email:
            body = (
                f"Hi {user.first_name or 'there'},\n\n"
                "Your MDQ+ Premium subscription is now active! 🎉\n\n"
                f"Your plan has been upgraded and will remain active until "
                f"{user.subscription_expiry.strftime('%d %B %Y')}.\n\n"
                "Enjoy unlimited AI chats, priority doctor access, and all "
                "premium features.\n\n"
                "— The MDQ+ Team"
            )
            background_tasks.add_task(
                send_transactional_email,
                to_email=user.email,
                subject="MDQ+ Premium Activated 🎉",
                body=body,
            )

        return {
            "action": "subscription_upgraded",
            "user_id": user.id,
            "expiry": str(user.subscription_expiry),
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
                body = (
                    f"Hi {patient.first_name or 'there'},\n\n"
                    f"Your {type_label} payment has been confirmed! ✅\n\n"
                    "Your doctor will be in touch shortly. You can join "
                    "your appointment via the MDQ+ app at the scheduled "
                    "time.\n\n"
                    "Appointment reference: "
                    f"{reference}\n"
                    f"Appointment ID: #{appt.id}\n\n"
                    "If you have any questions, reply to this email or "
                    "contact support in the app.\n\n"
                    "— The MDQ+ Team"
                )
                background_tasks.add_task(
                    send_transactional_email,
                    to_email=patient.email,
                    subject="MDQ+ Appointment Confirmed ✅",
                    body=body,
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
