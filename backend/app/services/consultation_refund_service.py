import logging
from datetime import datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.appointment import Appointment
from app.services.consultation_pricing import naira_to_kobo
from app.services.paystack_service import paystack_service

logger = logging.getLogger("uvicorn.error")

REFUND_ELIGIBLE_APPOINTMENT_STATUSES = frozenset(
    {"doctor_no_show", "both_no_show", "queue_expired", "queue_patient_unavailable"}
)
REFUND_STATUS_AWAITING_ADMIN = "awaiting_admin"
REFUND_STATUS_APPROVED = "approved"
TRANSFERABLE_REFUND_STATUSES = frozenset({REFUND_STATUS_APPROVED})


def eligible_consultation_refund_amount(
    appointment: Appointment,
) -> Decimal | None:
    """Return the full paid amount when a consultation refund is eligible."""
    patient_complaint_or_dispute = (
        appointment.status == "completed"
        and appointment.refund_status == REFUND_STATUS_AWAITING_ADMIN
    )
    if (
        appointment.status not in REFUND_ELIGIBLE_APPOINTMENT_STATUSES
        and not patient_complaint_or_dispute
    ):
        return None
    if appointment.payment_status != "paid":
        return None
    if not appointment.paystack_reference:
        return None
    amount = Decimal(str(appointment.amount or 0)).quantize(Decimal("0.01"))
    return amount if amount > 0 else None


def validate_admin_refund_approval(appointment: Appointment) -> bool:
    """Validate refund approval; return False for an idempotent repeat."""
    if appointment.refund_status in {
        "approved",
        "processing",
        "pending",
        "processed",
        "needs_attention",
    }:
        return False
    if appointment.refund_status != REFUND_STATUS_AWAITING_ADMIN:
        raise HTTPException(
            status_code=409,
            detail="This refund is no longer awaiting approval.",
        )
    if eligible_consultation_refund_amount(appointment) is None:
        raise HTTPException(
            status_code=409,
            detail="Appointment no longer qualifies for a refund.",
        )
    return True


async def process_approved_consultation_refunds() -> None:
    """Initiate only no-show refunds explicitly approved by an admin."""
    db = SessionLocal()
    try:
        appointment_ids = [
            row[0]
            for row in (
                db.query(Appointment.id)
                .filter(
                    Appointment.refund_status.in_(
                        TRANSFERABLE_REFUND_STATUSES
                    )
                )
                .order_by(Appointment.id)
                .limit(20)
                .all()
            )
        ]
        for appointment_id in appointment_ids:
            claimed = (
                db.query(Appointment)
                .filter(
                    Appointment.id == appointment_id,
                    Appointment.refund_status.in_(
                        TRANSFERABLE_REFUND_STATUSES
                    ),
                )
                .update(
                    {
                        Appointment.refund_status: "processing",
                        Appointment.refund_last_error: None,
                    },
                    synchronize_session=False,
                )
            )
            db.commit()
            if claimed != 1:
                continue

            appointment = db.get(Appointment, appointment_id)
            if appointment is None:
                continue
            amount = eligible_consultation_refund_amount(appointment)
            if amount is None:
                appointment.refund_status = "failed"
                appointment.refund_last_error = (
                    "Appointment is no longer eligible for refund."
                )
                db.commit()
                continue

            try:
                refund = await paystack_service.create_refund(
                    transaction_reference=appointment.paystack_reference,
                    amount_kobo=naira_to_kobo(float(amount)),
                    customer_note=(
                        "Refund for consultation that could not proceed."
                    ),
                    merchant_note=(
                        f"MDQ+ no-show refund for appointment "
                        f"{appointment.id}"
                    ),
                )
                appointment.refund_id = str(refund.get("id") or "") or None
                appointment.refund_reference = str(
                    refund.get("refund_reference")
                    or f"mdq-refund-{appointment.id}"
                )
                appointment.refund_amount = float(amount)
                paystack_status = str(refund.get("status") or "pending")
                appointment.refund_status = paystack_status.replace("-", "_")
                if appointment.refund_status == "processed":
                    appointment.refund_processed_at = datetime.utcnow()
                    appointment.payment_status = "refunded"
                db.commit()
            except HTTPException as exc:
                db.rollback()
                appointment = db.get(Appointment, appointment_id)
                if appointment is None:
                    continue
                appointment.refund_status = (
                    "verification_required"
                    if exc.status_code >= 500
                    else "failed"
                )
                appointment.refund_last_error = str(exc.detail)[:1000]
                db.commit()
            except Exception as exc:
                db.rollback()
                appointment = db.get(Appointment, appointment_id)
                if appointment is None:
                    continue
                appointment.refund_status = "verification_required"
                appointment.refund_last_error = str(exc)[:1000]
                db.commit()
                logger.exception(
                    "[REFUND] Unexpected refund processing error appointment=%s",
                    appointment_id,
                )
    finally:
        db.close()
