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
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from sqlalchemy.orm import Session

from app.api import deps
from app.core.database import get_db
from app.models.appointment import (
    APPOINTMENT_TYPE_GENERAL_QUEUE,
    APPOINTMENT_TYPE_SPECIALIST_SCHEDULED,
    APPOINTMENT_TYPE_VIP_REQUEST,
    Appointment,
    resolve_appointment_type,
)
from app.models.failed_webhook import FailedWebhook
from app.models.user import User
from app.models.doctor import Doctor
from app.models.consultation_payout import ConsultationPayout
from app.services.consultation_pricing import naira_to_kobo
from app.services.email_service import send_transactional_email
from app.services.paystack_service import paystack_service  # noqa: F401 (used in future endpoints)
from app.core.notifications import dispatch_push

logger = logging.getLogger(__name__)


def _push_user(
    user: User | None,
    *,
    title: str,
    body: str,
    data: dict | None,
    event_label: str,
):
    if not user:
        return
    dispatch_push(
        token=user.fcm_token,
        title=title,
        body=body,
        data=data,
        event_label=event_label,
    )


def _display_name(user: User | None) -> str:
    if not user:
        return "A patient"
    return f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email or "A patient"

# ── Paystack credentials ───────────────────────────────────────────────────────
PAYSTACK_SECRET_KEY: str = os.environ.get("PAYSTACK_SECRET_KEY", "")
if not PAYSTACK_SECRET_KEY:
    logger.warning(
        "[PAYMENTS] ⚠️  PAYSTACK_SECRET_KEY is not set. "
        "The /webhook endpoint will reject every incoming request."
    )

PAYSTACK_VERIFY_URL = "https://api.paystack.co/transaction/verify"
PAYSTACK_INITIALIZE_URL = "https://api.paystack.co/transaction/initialize"
INDIVIDUAL_SUBSCRIPTION_AMOUNT_KOBO = 350_000
FAMILY_SUBSCRIPTION_AMOUNT_KOBO = 1_000_000

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
async def initialize_transaction(
    payload: PaymentInitializeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
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
    if not current_user.email:
        raise HTTPException(
            status_code=400,
            detail="Your account does not have a valid payment email.",
        )

    body: dict = {
        "email": current_user.email,
        "amount": payload.amount,
        "reference": payload.reference,
    }

    transaction_type, ref_appointment_id, ref_user_id = _parse_reference(
        payload.reference
    )
    expected_subscription_amounts = {
        "subscription": INDIVIDUAL_SUBSCRIPTION_AMOUNT_KOBO,
        "family_subscription": FAMILY_SUBSCRIPTION_AMOUNT_KOBO,
    }
    expected_amount = expected_subscription_amounts.get(transaction_type)
    if expected_amount is not None and payload.amount != expected_amount:
        raise HTTPException(
            status_code=400,
            detail="Subscription amount does not match the configured plan price.",
        )
    if (
        expected_amount is not None
        and ref_user_id != str(current_user.id)
    ):
        raise HTTPException(
            status_code=403,
            detail="This payment reference does not belong to your account.",
        )

    try:
        appointment = _validate_consultation_payment(
            transaction_type=transaction_type,
            ref_appointment_id=ref_appointment_id,
            ref_user_id=ref_user_id,
            reference=payload.reference,
            amount_kobo=payload.amount,
            db=db,
            current_user=current_user,
            require_payable=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if appointment is not None and appointment.doctor_id is not None:
        doctor = appointment.doctor
        if doctor is None or not doctor.paystack_subaccount_code:
            raise HTTPException(
                status_code=409,
                detail=(
                    "This doctor's payout setup is incomplete. "
                    "Please choose another doctor or try again later."
                ),
            )
        body["subaccount"] = doctor.paystack_subaccount_code
        body["transaction_charge"] = naira_to_kobo(
            appointment.commission or 0.0
        )

    metadata: dict = {
        "reference": payload.reference,
        "transaction_type": transaction_type,
    }
    if ref_user_id:
        metadata["user_id"] = ref_user_id
    if ref_appointment_id:
        metadata["appointment_id"] = ref_appointment_id
    body["metadata"] = metadata

    # Conditionally attach the Plan Code for recurring subscriptions.
    if payload.plan:
        body["plan"] = payload.plan

    logger.info(
        "[PAYMENTS] Initializing transaction | reference='%s' | email='%s' "
        "| amount=%d kobo | plan=%s",
        payload.reference,
        current_user.email,
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
    elif "vip_request" in reference:           # VIP propose-and-pay flow
        transaction_type = "vip_request"
    elif "family_subscription" in reference:   # must precede plain "sub" check
        transaction_type = "family_subscription"
    elif "sub" in reference:
        transaction_type = "subscription"

    return transaction_type, ref_appointment_id, ref_user_id


CONSULTATION_TRANSACTION_TYPES = {
    "gp_consult",
    "specialist_consult",
    "vip_request",
}

EXPECTED_TRANSACTION_TYPE_BY_APPOINTMENT_TYPE = {
    APPOINTMENT_TYPE_GENERAL_QUEUE: "gp_consult",
    APPOINTMENT_TYPE_SPECIALIST_SCHEDULED: "specialist_consult",
    APPOINTMENT_TYPE_VIP_REQUEST: "vip_request",
}


def _validate_consultation_payment(
    *,
    transaction_type: str,
    ref_appointment_id: str | None,
    ref_user_id: str | None,
    reference: str,
    amount_kobo: int,
    db: Session,
    current_user: User | None = None,
    require_payable: bool = False,
) -> Appointment | None:
    """Bind a consultation payment to its owner, amount, type and state."""
    if transaction_type not in CONSULTATION_TRANSACTION_TYPES:
        return None
    if not ref_appointment_id or not ref_user_id:
        raise ValueError("Consultation payment reference is missing required IDs.")

    appointment = (
        db.query(Appointment)
        .filter(Appointment.id == int(ref_appointment_id))
        .first()
    )
    if appointment is None:
        raise ValueError("Consultation appointment was not found.")
    if appointment.paystack_reference != reference:
        raise ValueError("Payment reference does not match the appointment.")
    if appointment.patient_id != int(ref_user_id):
        raise ValueError("Payment reference patient does not match the appointment.")
    if current_user is not None and appointment.patient_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You cannot pay for another patient's appointment.",
        )

    expected_transaction_type = EXPECTED_TRANSACTION_TYPE_BY_APPOINTMENT_TYPE.get(
        resolve_appointment_type(appointment)
    )
    if expected_transaction_type != transaction_type:
        raise ValueError("Payment reference type does not match the appointment.")

    expected_amount_kobo = naira_to_kobo(appointment.amount or 0.0)
    if amount_kobo != expected_amount_kobo:
        raise ValueError("Payment amount does not match the appointment amount.")

    if require_payable:
        if appointment.payment_status != "unpaid":
            raise HTTPException(
                status_code=409,
                detail="This appointment has already been paid.",
            )
        payable_statuses = {
            "gp_consult": {"pending"},
            "specialist_consult": {"pending"},
            "vip_request": {"awaiting_payment"},
        }
        if appointment.status not in payable_statuses[transaction_type]:
            raise HTTPException(
                status_code=409,
                detail="This appointment is not currently payable.",
            )

    return appointment


def _persist_subscription_identifiers(user: User, paystack_data: dict | None) -> bool:
    """
    Persist Paystack subscription identifiers when they are present on a
    transaction or webhook payload. Paystack may return `subscription` as a
    nested object or as a plain subscription code depending on the event.
    """
    if not paystack_data:
        return False

    subscription_obj = paystack_data.get("subscription") or {}
    subscription_code: str | None = None
    email_token: str | None = None

    if isinstance(subscription_obj, dict):
        subscription_code = (
            subscription_obj.get("subscription_code")
            or subscription_obj.get("code")
        )
        email_token = subscription_obj.get("email_token")
    elif isinstance(subscription_obj, str):
        subscription_code = subscription_obj

    subscription_code = (
        subscription_code
        or paystack_data.get("subscription_code")
    )
    email_token = email_token or paystack_data.get("email_token")

    changed = False
    if subscription_code and user.paystack_subscription_code != subscription_code:
        user.paystack_subscription_code = subscription_code
        changed = True
    if email_token and user.paystack_email_token != email_token:
        user.paystack_email_token = email_token
        changed = True

    return changed


def _parse_paystack_datetime(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _payment_timestamp(paystack_data: dict | None) -> datetime | None:
    if not paystack_data:
        return None

    for key in ("paid_at", "paidAt", "transaction_date", "created_at"):
        parsed = _parse_paystack_datetime(paystack_data.get(key))
        if parsed:
            return parsed
    return None


def _next_subscription_expiry(
    current_expiry: datetime | None,
    payment_time: datetime | None = None,
) -> datetime:
    """
    Extend access from the current paid-through date when still active, or from
    now when the previous entitlement has already expired. When a Paystack
    payment timestamp is available, use it as an idempotent anchor so processing
    the same reference via webhook and manual verify does not add two months.
    """
    now = datetime.utcnow()
    if current_expiry and current_expiry.tzinfo:
        current_expiry = current_expiry.astimezone(timezone.utc).replace(
            tzinfo=None
        )

    if payment_time is not None:
        candidate = payment_time + timedelta(days=30)
        if current_expiry and current_expiry > candidate:
            return current_expiry
        return candidate

    if current_expiry is None:
        return now + timedelta(days=30)

    comparison_now = (
        datetime.now(current_expiry.tzinfo)
        if current_expiry.tzinfo
        else now
    )
    base = current_expiry if current_expiry > comparison_now else comparison_now
    return base + timedelta(days=30)


def _is_subscription_entitlement_expired(expiry: datetime | None) -> bool:
    if expiry is None:
        return True

    if expiry.tzinfo:
        expiry = expiry.astimezone(timezone.utc).replace(tzinfo=None)
    now = datetime.utcnow()
    return expiry <= now


def _apply_db_update(
    transaction_type: str,
    ref_appointment_id: str | None,
    ref_user_id: str | None,
    reference: str,
    db: Session,
    background_tasks: BackgroundTasks | None = None,
    paystack_data: dict | None = None,
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
        expiry = _next_subscription_expiry(
            user.subscription_expiry,
            _payment_timestamp(paystack_data),
        )
        user.plan = "family" if transaction_type == "family_subscription" else "premium"
        user.subscription_expiry = expiry
        user.auto_renew = True
        identifiers_saved = _persist_subscription_identifiers(user, paystack_data)
        db.commit()
        db.refresh(user)

        logger.info(
            "[PAYMENTS] ✅ Subscription upgraded — user_id=%s (%s) | type=%s | expiry=%s",
            user.id,
            user.email,
            transaction_type,
            user.subscription_expiry,
        )
        if identifiers_saved:
            logger.info(
                "[PAYMENTS] ✅ Stored Paystack subscription identifiers for user_id=%s",
                user.id,
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

        plan_label = "MDQ+ Family Plan" if transaction_type == "family_subscription" else "MDQ+ Premium"

        # ── Queue confirmation email ───────────────────────────────────────────
        if background_tasks and user.email:
            expiry_str = user.subscription_expiry.strftime('%d %B %Y')
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

        expiry_str = user.subscription_expiry.strftime("%d %b %Y") if user.subscription_expiry else "N/A"
        _push_user(
            user,
            title="Subscription Activated",
            body=f"Your {plan_label} subscription is active until {expiry_str}.",
            data={"type": "subscription_successful", "plan": str(user.plan)},
            event_label="PAYMENTS/SUBSCRIPTION_SUCCESS",
        )

        return {
            "action": "subscription_upgraded",
            "plan": transaction_type,
            "user_id": user.id,
            "expiry": str(user.subscription_expiry),
            "dependents_upgraded": upgraded_dependents,
        }

    # ── Flow B: Appointment payment confirmation ───────────────────────────────
    # Covers: gp_consult, specialist_consult, and vip_request (propose-and-pay).
    elif transaction_type in ("gp_consult", "specialist_consult", "vip_request"):
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

        was_schedule_confirmed = (
            appt.doctor_id is not None
            and appt.payment_status == "paid"
            and appt.status == "confirmed"
        )

        appt.payment_status = "paid"

        # Dual-pipeline confirmation:
        # ┌─ doctor_id IS set: direct booking OR VIP (propose-and-pay) → confirm immediately.
        #    This covers both 'pending' (specialist direct) and 'awaiting_payment' (VIP after
        #    doctor proposed a time), so no status guard is needed here.
        # └─ doctor_id IS NULL: General Queue → stays 'pending' for manual doctor claiming.
        if appt.doctor_id is not None:
            appt.status = "confirmed"
        else:
            appt.status = "pending"

        db.commit()
        db.refresh(appt)

        logger.info(
            "[PAYMENTS] ✅ Appointment confirmed — appt_id=%s | type=%s | patient_id=%s",
            appt.id,
            transaction_type,
            appt.patient_id,
        )

        patient: User | None = (
            db.query(User).filter(User.id == appt.patient_id).first()
            if appt.patient_id
            else None
        )

        # ── Queue appointment confirmation email ───────────────────────────
        # Look up the patient's email from the User table using patient_id.
        if background_tasks and patient:
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

        if appt.doctor_id is not None and not was_schedule_confirmed:
            _push_user(
                patient,
                title="Appointment Confirmed",
                body="Your consultation payment is confirmed and your appointment is booked.",
                data={"type": "schedule_confirmed", "appointment_id": str(appt.id)},
                event_label="PAYMENTS/APPOINTMENT_CONFIRMED_PATIENT",
            )

            doctor: Doctor | None = db.query(Doctor).filter(Doctor.id == appt.doctor_id).first()
            doctor_user: User | None = (
                db.query(User).filter(User.id == doctor.user_id).first()
                if doctor
                else None
            )
            _push_user(
                doctor_user,
                title="Appointment Booked",
                body=f"{_display_name(patient)} booked a consultation.",
                data={"type": "appointment_booked", "appointment_id": str(appt.id)},
                event_label="PAYMENTS/APPOINTMENT_BOOKED_DOCTOR",
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


def _handle_charge_success(data: dict, db: Session) -> dict:
    """
    Handle charge.success events that carry a user_id in data.metadata.
    Upgrades or renews the user's subscription, extends the paid-through date,
    and resets burst_chat_count so the user gets a clean AI-chat allowance
    immediately.

    Raises ValueError when metadata is absent or the user is not found.
    """
    metadata: dict = data.get("metadata") or {}
    user_id_raw = metadata.get("user_id")

    if not user_id_raw:
        raise ValueError(
            "charge.success: metadata.user_id is absent — cannot upgrade subscription."
        )

    user: User | None = db.query(User).filter(User.id == int(user_id_raw)).first()
    if not user:
        raise ValueError(f"charge.success: user id={user_id_raw} not found.")

    transaction_type = str(metadata.get("transaction_type") or "")
    is_family_subscription = transaction_type == "family_subscription"
    expiry = _next_subscription_expiry(
        user.subscription_expiry,
        _payment_timestamp(data),
    )

    user.plan = "family" if is_family_subscription else "premium"
    user.subscription_expiry = expiry
    user.auto_renew = True
    user.burst_chat_count = 0

    # ── Capture subscription codes if Paystack includes them ───────────────────
    # charge.success events may embed `subscription` as either an object or a
    # plain code string, so use the shared tolerant parser.
    identifiers_saved = _persist_subscription_identifiers(user, data)
    if identifiers_saved:
        logger.info(
            "[WEBHOOK] charge.success — captured subscription identifiers for user_id=%s",
            user.id,
        )

    upgraded_dependents: list[int] = []
    if is_family_subscription:
        dependents: list[User] = (
            db.query(User)
            .filter(User.primary_account_id == user.id)
            .all()
        )
        for dep in dependents:
            dep.plan = "family"
            dep.subscription_expiry = expiry
        upgraded_dependents = [dep.id for dep in dependents]

    db.commit()
    db.refresh(user)

    logger.info(
        "[WEBHOOK] charge.success — upgraded user_id=%s to %s | expiry=%s | dependents=%s",
        user.id,
        user.plan,
        user.subscription_expiry,
        upgraded_dependents,
    )

    # ── FCM: notify the user their subscription is now active ──────────────
    try:
        expiry_str = user.subscription_expiry.strftime("%d %b %Y") if user.subscription_expiry else "N/A"
        dispatch_push(
            token=user.fcm_token,
            title="🎉 MDQ+ Subscription Activated!",
            body=f"Your subscription is active until {expiry_str}. Enjoy unlimited access!",
            data={"type": "subscription_successful", "plan": str(user.plan)},
            event_label="PAYMENTS/CHARGE_SUCCESS",
        )
    except Exception as notif_exc:
        logger.error(
            "[WEBHOOK] charge.success FCM push failed — user_id=%s: %s",
            user.id,
            notif_exc,
            exc_info=True,
        )

    return {
        "action": "subscription_upgraded_via_charge",
        "user_id": user.id,
        "plan": user.plan,
        "expiry": str(user.subscription_expiry),
        "dependents_upgraded": upgraded_dependents,
    }


def _handle_subscription_disable(data: dict, db: Session) -> dict:
    """
    Handle subscription.disable (and subscription.not_renew) events from Paystack.

    Paystack owns the failed-renewal retry schedule. When Paystack emits this
    event, MDQ+ turns off local auto-renew immediately. Access is still governed
    by subscription_expiry, so a user who cancelled early keeps paid access
    until their paid-through date, while an already-expired entitlement is
    downgraded immediately.

    Raises ValueError when required fields are missing or the user is not found.
    """
    subscription_code: str | None = data.get("subscription_code") or data.get("code")

    # Resolve user_id from customer.metadata (same path as subscription.create)
    customer: dict = data.get("customer") or {}
    customer_meta: dict = customer.get("metadata") or {}
    user_id_raw = customer_meta.get("user_id")

    # Fallback: some payloads embed user_id directly in data.metadata
    if not user_id_raw:
        top_meta: dict = data.get("metadata") or {}
        user_id_raw = top_meta.get("user_id")

    user: User | None = None
    if user_id_raw:
        user = db.query(User).filter(User.id == int(user_id_raw)).first()
    elif subscription_code:
        user = (
            db.query(User)
            .filter(User.paystack_subscription_code == subscription_code)
            .first()
        )

    if not user_id_raw and not subscription_code:
        raise ValueError(
            "subscription.disable: user_id/subscription_code not found in payload — "
            "cannot downgrade subscription."
        )

    if not user:
        raise ValueError(
            "subscription.disable: matching user not found for "
            f"user_id={user_id_raw!r}, subscription_code={subscription_code!r}."
        )

    previous_plan = user.plan
    user.auto_renew = False

    downgraded = _is_subscription_entitlement_expired(user.subscription_expiry)
    dependent_count = 0
    if downgraded:
        user.plan = "free"
        user.subscription_expiry = None
        dependent_count = (
            db.query(User)
            .filter(User.primary_account_id == user.id)
            .update(
                {
                    User.plan: "free",
                    User.subscription_expiry: None,
                    User.auto_renew: False,
                },
                synchronize_session=False,
            )
        )

    db.commit()
    db.refresh(user)

    logger.info(
        "[WEBHOOK] subscription.disable — user_id=%s auto_renew disabled; "
        "downgraded=%s; previous_plan=%s; dependents_downgraded=%s.",
        user.id,
        downgraded,
        previous_plan,
        dependent_count,
    )

    return {
        "action": "subscription_disabled",
        "user_id": user.id,
        "plan": user.plan,
        "downgraded": downgraded,
        "dependents_downgraded": dependent_count,
    }


def _handle_subscription_create(data: dict, db: Session) -> dict:
    """
    Handle subscription.create events from Paystack.

    This is the primary source for ``subscription_code`` and ``email_token``.
    Paystack fires this event immediately after a recurring subscription is
    activated (either via a plan-based charge.success or an explicit creation).

    Payload path: data.subscription_code, data.email_token, data.customer.metadata.user_id

    Raises ValueError when required fields are missing or the user is not found.
    """
    subscription_code: str | None = data.get("subscription_code")
    email_token: str | None = data.get("email_token")

    if not subscription_code:
        raise ValueError(
            "subscription.create: data.subscription_code is absent."
        )

    # Resolve user_id — Paystack stores it in the customer's metadata
    customer: dict = data.get("customer") or {}
    customer_meta: dict = customer.get("metadata") or {}
    top_meta: dict = data.get("metadata") or {}
    user_id_raw = customer_meta.get("user_id")

    if not user_id_raw:
        raise ValueError(
            "subscription.create: customer.metadata.user_id is absent — "
            "cannot persist subscription codes."
        )

    user: User | None = db.query(User).filter(User.id == int(user_id_raw)).first()
    if not user:
        raise ValueError(
            f"subscription.create: user id={user_id_raw} not found."
        )

    user.paystack_subscription_code = subscription_code
    if email_token:
        user.paystack_email_token = email_token
    user.auto_renew = True

    # Also ensure the plan is upgraded in case charge.success was missed
    if user.plan not in ("premium", "family"):
        transaction_type = str(
            customer_meta.get("transaction_type")
            or top_meta.get("transaction_type")
            or ""
        )
        is_family_subscription = transaction_type == "family_subscription"
        expiry = _next_subscription_expiry(user.subscription_expiry)

        user.plan = "family" if is_family_subscription else "premium"
        user.subscription_expiry = expiry
        if is_family_subscription:
            dependents: list[User] = (
                db.query(User)
                .filter(User.primary_account_id == user.id)
                .all()
            )
            for dep in dependents:
                dep.plan = "family"
                dep.subscription_expiry = expiry

    db.commit()
    db.refresh(user)

    logger.info(
        "[WEBHOOK] subscription.create — persisted sub_code='%s' for user_id=%s",
        subscription_code,
        user.id,
    )
    return {
        "action": "subscription_codes_persisted",
        "user_id": user.id,
        "subscription_code": subscription_code,
    }


def _handle_transfer_success(data: dict, db: Session) -> dict:
    """
    Handle transfer.success events to credit a doctor's earnings.

    Paystack sends the amount in kobo; we divide by 100 before storing.
    doctor_id is read from data.recipient.metadata.doctor_id first, then
    falls back to data.metadata.doctor_id.

    Raises ValueError when required fields are missing or the doctor is not found.
    """
    reference = str(data.get("reference") or "")
    ledger = (
        db.query(ConsultationPayout)
        .filter(ConsultationPayout.reference == reference)
        .with_for_update()
        .first()
        if reference
        else None
    )
    if ledger is not None:
        if ledger.status == "paid":
            return {
                "action": "payout_already_confirmed",
                "payout_id": ledger.id,
                "appointment_id": ledger.appointment_id,
            }
        if ledger.status == "reversed":
            return {
                "action": "payout_already_reversed",
                "payout_id": ledger.id,
                "appointment_id": ledger.appointment_id,
            }

        amount_kobo = int(data.get("amount") or 0)
        expected_amount_kobo = naira_to_kobo(float(ledger.amount))
        if amount_kobo != expected_amount_kobo:
            raise ValueError(
                "transfer.success amount does not match the payout ledger."
            )

        doctor = (
            db.query(Doctor)
            .filter(Doctor.id == ledger.doctor_id)
            .first()
        )
        if doctor is None:
            raise ValueError(
                f"transfer.success: doctor id={ledger.doctor_id} not found."
            )

        ledger.status = "paid"
        ledger.transfer_code = (
            data.get("transfer_code") or ledger.transfer_code
        )
        ledger.last_error = None
        ledger.paid_at = datetime.utcnow()
        current_earnings = Decimal(
            str(getattr(doctor, "total_earnings", None) or 0)
        )
        doctor.total_earnings = current_earnings + Decimal(str(ledger.amount))
        db.commit()
        db.refresh(ledger)
        db.refresh(doctor)

        doctor_user = (
            db.query(User).filter(User.id == doctor.user_id).first()
            if doctor.user_id
            else None
        )
        _push_user(
            doctor_user,
            title="Payout Sent",
            body=f"Your payout of ₦{float(ledger.amount):,.2f} has been processed.",
            data={
                "type": "payout_sent",
                "doctor_id": str(doctor.id),
                "appointment_id": str(ledger.appointment_id),
            },
            event_label="PAYMENTS/PAYOUT_SENT",
        )
        return {
            "action": "consultation_payout_confirmed",
            "payout_id": ledger.id,
            "appointment_id": ledger.appointment_id,
            "doctor_id": doctor.id,
            "amount_credited": float(ledger.amount),
        }

    # Legacy transfer events without a consultation payout reference.
    recipient: dict = data.get("recipient") or {}
    recipient_meta: dict = recipient.get("metadata") or {}
    top_meta: dict = data.get("metadata") or {}

    doctor_id_raw = recipient_meta.get("doctor_id") or top_meta.get("doctor_id")
    if not doctor_id_raw:
        raise ValueError(
            "transfer.success: doctor_id not found in data.recipient.metadata "
            "or data.metadata."
        )

    amount_kobo: int = int(data.get("amount") or 0)
    amount_naira: float = amount_kobo / 100.0

    doctor: Doctor | None = (
        db.query(Doctor).filter(Doctor.id == int(doctor_id_raw)).first()
    )
    if not doctor:
        raise ValueError(f"transfer.success: doctor id={doctor_id_raw} not found.")

    current_earnings: float = float(getattr(doctor, "total_earnings", None) or 0.0)
    doctor.total_earnings = current_earnings + amount_naira  # type: ignore[attr-defined]
    db.commit()
    db.refresh(doctor)

    logger.info(
        "[WEBHOOK] transfer.success — credited doctor_id=%s | amount=%.2f NGN "
        "| new total_earnings=%.2f",
        doctor.id,
        amount_naira,
        doctor.total_earnings,
    )

    doctor_user: User | None = (
        db.query(User).filter(User.id == doctor.user_id).first()
        if doctor.user_id
        else None
    )
    _push_user(
        doctor_user,
        title="Payout Sent",
        body=f"Your payout of ₦{amount_naira:,.2f} has been processed.",
        data={"type": "payout_sent", "doctor_id": str(doctor.id)},
        event_label="PAYMENTS/PAYOUT_SENT",
    )

    return {
        "action": "doctor_earnings_credited",
        "doctor_id": doctor.id,
        "amount_credited": amount_naira,
        "total_earnings": doctor.total_earnings,
    }


def _handle_transfer_status(
    data: dict,
    db: Session,
    *,
    status_value: str,
) -> dict:
    """Update a consultation payout for pending, failed or reversed transfers."""
    reference = str(data.get("reference") or "")
    if not reference:
        return {"action": "ignored_transfer_status_without_reference"}

    payout = (
        db.query(ConsultationPayout)
        .filter(ConsultationPayout.reference == reference)
        .with_for_update()
        .first()
    )
    if payout is None:
        return {"action": "ignored_non_consultation_transfer"}

    if status_value == "pending" and payout.status != "paid":
        payout.status = "processing"
    elif status_value == "failed" and payout.status != "paid":
        payout.status = "failed"
        payout.last_error = str(
            data.get("reason")
            or data.get("failures")
            or "Paystack transfer failed."
        )[:1000]
    elif status_value == "reversed":
        was_paid = payout.status == "paid"
        payout.status = "reversed"
        payout.last_error = "Paystack reversed the transfer."
        if was_paid:
            doctor = (
                db.query(Doctor)
                .filter(Doctor.id == payout.doctor_id)
                .first()
            )
            if doctor is not None:
                current = Decimal(
                    str(getattr(doctor, "total_earnings", None) or 0)
                )
                doctor.total_earnings = max(
                    Decimal("0.00"),
                    current - Decimal(str(payout.amount)),
                )

    payout.transfer_code = data.get("transfer_code") or payout.transfer_code
    db.commit()
    return {
        "action": f"consultation_payout_{status_value}",
        "payout_id": payout.id,
        "appointment_id": payout.appointment_id,
    }


def _handle_refund_status(
    data: dict,
    db: Session,
    *,
    status_value: str,
) -> dict:
    """Apply a Paystack refund webhook to its consultation appointment."""
    transaction = data.get("transaction")
    transaction_reference = str(
        data.get("transaction_reference")
        or (
            transaction.get("reference")
            if isinstance(transaction, dict)
            else ""
        )
        or ""
    )
    if not transaction_reference:
        raise ValueError("Refund webhook has no transaction reference.")

    appointment = (
        db.query(Appointment)
        .filter(Appointment.paystack_reference == transaction_reference)
        .with_for_update()
        .first()
    )
    if appointment is None:
        raise ValueError("Refund appointment was not found.")
    if appointment.refund_status is None:
        raise ValueError("Appointment has no approved refund workflow.")

    normalized_status = status_value.replace("-", "_")
    appointment.refund_status = normalized_status
    appointment.refund_reference = str(
        data.get("refund_reference")
        or appointment.refund_reference
        or ""
    ) or None
    appointment.refund_id = str(
        data.get("id") or appointment.refund_id or ""
    ) or None
    if data.get("amount") is not None:
        appointment.refund_amount = int(data["amount"]) / 100

    if normalized_status == "processed":
        appointment.refund_processed_at = datetime.utcnow()
        appointment.refund_last_error = None
        appointment.payment_status = "refunded"
    elif normalized_status == "failed":
        appointment.refund_last_error = str(
            data.get("reason") or "Paystack refund failed."
        )[:1000]
    elif normalized_status == "needs_attention":
        appointment.refund_last_error = (
            "Paystack requires customer bank details to complete this refund."
        )
    else:
        appointment.refund_last_error = None

    db.commit()
    return {
        "action": f"consultation_refund_{normalized_status}",
        "appointment_id": appointment.id,
    }


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
    reference: str = (
        data.get("reference")
        or data.get("transaction_reference")
        or ""
    )
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

    # -- 7. Event-level dispatch then reference-based routing -----------------
    #
    # charge.success  -> subscription upgrade via metadata.user_id
    # transfer.success -> doctor earnings credit via metadata/recipient.metadata
    # everything else -> existing reference-based router (_apply_db_update)
    #
    # All three paths share the same DLQ fallback below.
    # -------------------------------------------------------------------------
    try:
        if (
            raw_event == "charge.success"
            and transaction_type in {"subscription", "family_subscription"}
        ):
            result = _handle_charge_success(data=data, db=db)
        elif (
            raw_event == "charge.success"
            and transaction_type in CONSULTATION_TRANSACTION_TYPES
        ):
            _validate_consultation_payment(
                transaction_type=transaction_type,
                ref_appointment_id=ref_appointment_id,
                ref_user_id=ref_user_id,
                reference=reference,
                amount_kobo=int(data.get("amount") or 0),
                db=db,
            )
            result = _apply_db_update(
                transaction_type=transaction_type,
                ref_appointment_id=ref_appointment_id,
                ref_user_id=ref_user_id,
                reference=reference,
                db=db,
                background_tasks=background_tasks,
                paystack_data=data,
            )
        elif raw_event == "subscription.create":
            result = _handle_subscription_create(data=data, db=db)
        elif raw_event == "transfer.success":
            result = _handle_transfer_success(data=data, db=db)
        elif raw_event == "transfer.pending":
            result = _handle_transfer_status(
                data=data,
                db=db,
                status_value="pending",
            )
        elif raw_event == "transfer.failed":
            result = _handle_transfer_status(
                data=data,
                db=db,
                status_value="failed",
            )
        elif raw_event == "transfer.reversed":
            result = _handle_transfer_status(
                data=data,
                db=db,
                status_value="reversed",
            )
        elif raw_event in {
            "refund.pending",
            "refund.processing",
            "refund.needs-attention",
            "refund.failed",
            "refund.processed",
        }:
            result = _handle_refund_status(
                data=data,
                db=db,
                status_value=raw_event.removeprefix("refund."),
            )
        elif raw_event in ("subscription.disable", "subscription.not_renew"):
            result = _handle_subscription_disable(data=data, db=db)
        else:
            result = _apply_db_update(
                transaction_type=transaction_type,
                ref_appointment_id=ref_appointment_id,
                ref_user_id=ref_user_id,
                reference=reference,
                db=db,
                background_tasks=background_tasks,
                paystack_data=data,
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
    current_user: User = Depends(deps.get_current_user),
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
    if (
        transaction_type in {"subscription", "family_subscription"}
        and ref_user_id != str(current_user.id)
    ):
        raise HTTPException(
            status_code=403,
            detail="This payment reference does not belong to your account.",
        )
    try:
        _validate_consultation_payment(
            transaction_type=transaction_type,
            ref_appointment_id=ref_appointment_id,
            ref_user_id=ref_user_id,
            reference=reference,
            amount_kobo=int(tx_data.get("amount") or 0),
            db=db,
            current_user=current_user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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
            paystack_data=tx_data,
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
