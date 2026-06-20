import logging
from datetime import datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.appointment import (
    APPOINTMENT_TYPE_GENERAL_QUEUE,
    Appointment,
    resolve_appointment_type,
)
from app.models.consultation_payout import ConsultationPayout
from app.models.doctor import Doctor
from app.services.consultation_pricing import naira_to_kobo
from app.services.paystack_service import paystack_service

logger = logging.getLogger("uvicorn.error")

ELIGIBLE_PAYOUT_STATUSES = {"completed", "patient_no_show"}
PAYOUT_STATUS_AWAITING_ADMIN = "awaiting_admin"
PAYOUT_STATUS_APPROVED = "approved"
TRANSFERABLE_PAYOUT_STATUSES = frozenset({PAYOUT_STATUS_APPROVED})
APPROVAL_IDEMPOTENT_STATUSES = frozenset(
    {"approved", "processing", "otp_required", "paid"}
)


def eligible_general_queue_payout_amount(
    appointment: Appointment,
) -> Decimal | None:
    """Return the owed doctor amount only when a payout may be created."""
    if resolve_appointment_type(appointment) != APPOINTMENT_TYPE_GENERAL_QUEUE:
        return None
    if appointment.status not in ELIGIBLE_PAYOUT_STATUSES:
        return None
    if appointment.payment_status != "paid" or appointment.doctor_id is None:
        return None

    amount = Decimal(str(appointment.payout or 0)).quantize(Decimal("0.01"))
    return amount if amount > 0 else None


def validate_admin_payout_decision(
    payout: ConsultationPayout,
    *,
    action: str,
    appointment: Appointment | None = None,
    doctor: Doctor | None = None,
) -> bool:
    """Validate an admin decision; return False for an idempotent repeat."""
    if action == "approve":
        if payout.status in APPROVAL_IDEMPOTENT_STATUSES:
            return False
        if payout.status != PAYOUT_STATUS_AWAITING_ADMIN:
            raise HTTPException(
                status_code=409,
                detail="This payout is no longer awaiting approval.",
            )

        eligible_amount = (
            eligible_general_queue_payout_amount(appointment)
            if appointment is not None
            else None
        )
        if (
            appointment is None
            or eligible_amount is None
            or appointment.doctor_id != payout.doctor_id
            or eligible_amount != Decimal(str(payout.amount))
        ):
            raise HTTPException(
                status_code=409,
                detail="Payout no longer matches an eligible consultation.",
            )
        if doctor is None or not doctor.bank_code or not doctor.account_number:
            raise HTTPException(
                status_code=409,
                detail="Doctor payout settings are incomplete.",
            )
        return True

    if action == "reject":
        if payout.status == "rejected":
            return False
        if payout.status != PAYOUT_STATUS_AWAITING_ADMIN:
            raise HTTPException(
                status_code=409,
                detail="Only payouts awaiting approval may be rejected.",
            )
        return True

    raise ValueError(f"Unsupported payout decision: {action}")


def ensure_general_queue_payout(
    db: Session,
    appointment: Appointment,
) -> ConsultationPayout | None:
    """Create one payout obligation for an eligible general-queue appointment."""
    amount = eligible_general_queue_payout_amount(appointment)
    if amount is None:
        return None

    existing = (
        db.query(ConsultationPayout)
        .filter(ConsultationPayout.appointment_id == appointment.id)
        .first()
    )
    if existing is not None:
        return existing

    try:
        with db.begin_nested():
            payout = ConsultationPayout(
                appointment_id=appointment.id,
                doctor_id=appointment.doctor_id,
                amount=amount,
                status=PAYOUT_STATUS_AWAITING_ADMIN,
                reference=f"mdq-gp-payout-{appointment.id}",
            )
            db.add(payout)
            db.flush()
            return payout
    except IntegrityError:
        return (
            db.query(ConsultationPayout)
            .filter(ConsultationPayout.appointment_id == appointment.id)
            .first()
        )


def enqueue_missing_general_queue_payouts(db: Session) -> int:
    """Backfill payout obligations for eligible appointments safely."""
    appointments = (
        db.query(Appointment)
        .filter(
            Appointment.appointment_type == APPOINTMENT_TYPE_GENERAL_QUEUE,
            Appointment.status.in_(ELIGIBLE_PAYOUT_STATUSES),
            Appointment.payment_status == "paid",
            Appointment.doctor_id.is_not(None),
        )
        .all()
    )
    created = 0
    for appointment in appointments:
        before = (
            db.query(ConsultationPayout.id)
            .filter(ConsultationPayout.appointment_id == appointment.id)
            .first()
        )
        ensure_general_queue_payout(db, appointment)
        if before is None:
            created += 1
    db.commit()
    return created


async def process_approved_general_queue_payouts() -> None:
    """Initiate only general-queue payouts explicitly approved by an admin."""
    db = SessionLocal()
    try:
        enqueue_missing_general_queue_payouts(db)
        payout_ids = [
            row[0]
            for row in (
                db.query(ConsultationPayout.id)
                .filter(
                    ConsultationPayout.status.in_(TRANSFERABLE_PAYOUT_STATUSES)
                )
                .order_by(ConsultationPayout.id)
                .limit(20)
                .all()
            )
        ]

        for payout_id in payout_ids:
            claimed = (
                db.query(ConsultationPayout)
                .filter(
                    ConsultationPayout.id == payout_id,
                    ConsultationPayout.status.in_(
                        TRANSFERABLE_PAYOUT_STATUSES
                    ),
                )
                .update(
                    {
                        ConsultationPayout.status: "processing",
                        ConsultationPayout.attempts:
                            ConsultationPayout.attempts + 1,
                        ConsultationPayout.last_error: None,
                    },
                    synchronize_session=False,
                )
            )
            db.commit()
            if claimed != 1:
                continue

            payout = db.get(ConsultationPayout, payout_id)
            doctor = (
                db.query(Doctor)
                .filter(Doctor.id == payout.doctor_id)
                .first()
                if payout
                else None
            )
            if payout is None:
                continue
            if doctor is None:
                payout.status = "failed"
                payout.last_error = "Assigned doctor profile no longer exists."
                db.commit()
                continue

            try:
                if not doctor.bank_code or not doctor.account_number:
                    payout.status = "blocked"
                    payout.last_error = "Doctor payout bank details are incomplete."
                    db.commit()
                    continue

                recipient_code = doctor.paystack_recipient_code
                if not recipient_code:
                    recipient_code = await paystack_service.create_transfer_recipient(
                        doctor_id=doctor.id,
                        name=doctor.full_name,
                        bank_code=doctor.bank_code,
                        account_number=doctor.account_number,
                    )
                    doctor.paystack_recipient_code = recipient_code
                    db.commit()

                transfer = await paystack_service.initiate_transfer(
                    amount_kobo=naira_to_kobo(float(payout.amount)),
                    recipient_code=recipient_code,
                    reference=payout.reference,
                    reason=f"MDQ+ general consultation #{payout.appointment_id}",
                )
                payout.recipient_code = recipient_code
                payout.transfer_code = transfer.get("transfer_code")
                transfer_status = str(transfer.get("status") or "processing")
                payout.status = (
                    "otp_required"
                    if transfer_status == "otp"
                    else "processing"
                )
                payout.last_error = (
                    "Paystack transfer OTP is enabled; automatic payout cannot finish."
                    if payout.status == "otp_required"
                    else None
                )
                db.commit()
            except HTTPException as exc:
                db.rollback()
                payout = db.get(ConsultationPayout, payout_id)
                if payout is None:
                    continue
                payout.status = (
                    PAYOUT_STATUS_APPROVED
                    if exc.status_code >= 500
                    else "failed"
                )
                payout.last_error = str(exc.detail)[:1000]
                db.commit()
            except Exception as exc:
                db.rollback()
                payout = db.get(ConsultationPayout, payout_id)
                if payout is None:
                    continue
                payout.status = PAYOUT_STATUS_APPROVED
                payout.last_error = str(exc)[:1000]
                db.commit()
                logger.exception(
                    "[PAYOUT] Unexpected payout processing error id=%s",
                    payout_id,
                )
    finally:
        db.close()
