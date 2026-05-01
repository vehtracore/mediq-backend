"""
Payments Router
================
Owns all Paystack-facing HTTP surface area for the MDQ+ platform.

Currently exposes:
  POST /api/v1/payments/webhook  — Paystack webhook receiver with HMAC SHA512
                                   signature verification and metadata-driven
                                   event routing.

Security model
--------------
Paystack signs every outbound webhook payload with the account's secret key
using HMAC-SHA512. We recompute that digest from the raw request body (before
any JSON decoding) and compare with a timing-safe equality check. Any request
that fails this check is rejected with HTTP 400 before it touches the database.
"""

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User

logger = logging.getLogger(__name__)

# ── Paystack credentials ───────────────────────────────────────────────────────
PAYSTACK_SECRET_KEY: str = os.environ.get("PAYSTACK_SECRET_KEY", "")
if not PAYSTACK_SECRET_KEY:
    logger.warning(
        "[PAYMENTS] ⚠️  PAYSTACK_SECRET_KEY is not set. "
        "The /webhook endpoint will reject every incoming request."
    )

router = APIRouter()


# ─── Webhook ──────────────────────────────────────────────────────────────────

@router.post("/webhook", status_code=200)
async def paystack_webhook(request: Request, db: Session = Depends(get_db)):
    """
    POST /api/v1/payments/webhook

    Receives Paystack event notifications and routes them by
    ``metadata.transactionType``:

    =========== ============================================================
    Type        Action
    =========== ============================================================
    subscription  Upgrade ``User.plan`` → "premium" for 30 days.
    gp_consult    Mark ``Appointment.payment_status`` = "paid" and
                  ``status`` = "confirmed".
    specialist_consult  Same as gp_consult.
    *(other)*   Log a warning, return 200 so Paystack stops retrying.
    =========== ============================================================

    Always returns ``{"status": "success"}`` on 2xx so Paystack never
    puts the endpoint into a retry loop for events we deliberately ignore.
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

    # ── Parse IDs embedded in the reference string ────────────────────────────
    # New format: MDQ-{type}-{appointment_id}-{user_id}-{timestamp}
    # e.g.  MDQ-gp_consult-123-456-1777195558454
    # Old format (underscore-delimited, no IDs) is handled gracefully below.
    ref_parts = reference.split("-")
    # ref_parts[0] = 'MDQ'
    # ref_parts[1] = type segment  (may contain underscores, e.g. 'gp_consult')
    # ref_parts[2] = appointment_id
    # ref_parts[3] = user_id
    # ref_parts[4] = timestamp
    ref_appointment_id: str | None = ref_parts[2] if len(ref_parts) >= 5 else None
    ref_user_id: str | None = ref_parts[3] if len(ref_parts) >= 5 else None

    # Determine transaction type from the reference string
    transaction_type = ""
    if "gp_consult" in reference:
        transaction_type = "gp_consult"
    elif "specialist" in reference:
        transaction_type = "specialist_consult"
    elif "sub" in reference:
        transaction_type = "subscription"

    logger.info(
        "[WEBHOOK] Received event='%s' | reference='%s' | transactionType='%s' "
        "| appointment_id='%s' | user_id='%s'",
        raw_event,
        reference,
        transaction_type,
        ref_appointment_id,
        ref_user_id,
    )

    # ── Flow A: Subscription upgrade ──────────────────────────────────────────
    if transaction_type == "subscription":
        user_id = ref_user_id
        if not user_id:
            logger.error("[WEBHOOK] subscription: reference missing user_id segment (ref='%s').", reference)
            return {"status": "success", "detail": "missing user_id in reference"}

        user: User | None = db.query(User).filter(User.id == int(user_id)).first()
        if not user:
            logger.error("[WEBHOOK] subscription: user id=%s not found.", user_id)
            return {"status": "success", "detail": "user not found"}

        user.plan = "premium"
        user.subscription_expiry = datetime.utcnow() + timedelta(days=30)
        db.commit()
        db.refresh(user)

        logger.info(
            "[WEBHOOK] ✅ Subscription upgraded — user_id=%s (%s) | expiry=%s",
            user.id,
            user.email,
            user.subscription_expiry,
        )

    # ── Flow B: Appointment payment confirmation ───────────────────────────────
    elif transaction_type in ("gp_consult", "specialist_consult"):
        from app.models.appointment import Appointment  # local import → no circular dep

        appointment_id = ref_appointment_id
        if not appointment_id:
            logger.error(
                "[WEBHOOK] %s: reference missing appointment_id segment (ref='%s').",
                transaction_type,
                reference,
            )
            return {"status": "success", "detail": "missing appointment_id in reference"}

        appt: Appointment | None = (
            db.query(Appointment).filter(Appointment.id == int(appointment_id)).first()
        )
        if not appt:
            logger.error(
                "[WEBHOOK] %s: appointment id=%s not found.",
                transaction_type,
                appointment_id,
            )
            return {"status": "success", "detail": "appointment not found"}

        appt.payment_status = "paid"
        appt.status = "confirmed"
        db.commit()
        db.refresh(appt)

        logger.info(
            "[WEBHOOK] ✅ Appointment confirmed — appt_id=%s | type=%s | patient_id=%s",
            appt.id,
            transaction_type,
            appt.patient_id,
        )

    # ── Graceful fallback: unrecognised transactionType ───────────────────────
    else:
        logger.warning(
            "[WEBHOOK] Unrecognised transactionType='%s' — no action taken.",
            transaction_type,
        )

    return {"status": "success"}
