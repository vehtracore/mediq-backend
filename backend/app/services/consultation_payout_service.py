import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.appointment import (
    APPOINTMENT_TYPE_GENERAL_QUEUE,
    Appointment,
    consultation_started_utc,
    resolve_appointment_type,
)
from app.models.consultation_payout import ConsultationPayout
from app.models.doctor import Doctor
from app.services.consultation_pricing import (
    CONSULTATION_MESSAGE_GRACE_MINUTES,
    DEFAULT_CONSULTATION_DURATION_MINUTES,
    calculate_consultation_split,
    naira_to_kobo,
)
from app.services.paystack_service import paystack_service

logger = logging.getLogger("uvicorn.error")

PAYOUT_REVIEW_HOLD_HOURS = 24
ELIGIBLE_PAYOUT_STATUSES = {"completed", "patient_no_show"}
PAYOUT_STATUS_AWAITING_ADMIN = "awaiting_admin"
PAYOUT_STATUS_APPROVED = "approved"
TRANSFERABLE_PAYOUT_STATUSES = frozenset({PAYOUT_STATUS_APPROVED})
APPROVAL_IDEMPOTENT_STATUSES = frozenset(
    {"approved", "processing", "otp_required", "paid", "verification_required"}
)
PAYOUT_BLOCKING_REFUND_STATUSES = frozenset(
    {
        "awaiting_admin",
        "approved",
        "pending",
        "processing",
        "needs_attention",
        "needs-attention",
        "verification_required",
        "processed",
    }
)

PAYOUT_AMOUNT_SYNC_STATUSES = frozenset(
    {"awaiting_admin", "approved", "blocked", "failed", "verification_required"}
)


def consultation_payout_hold_until(appointment: Appointment) -> datetime | None:
    """Return when a consultation may enter admin payout review."""
    if appointment.status == "completed":
        started = consultation_started_utc(appointment)
        if started is None:
            return None
        close_time = started + timedelta(
            minutes=(
                DEFAULT_CONSULTATION_DURATION_MINUTES
                + CONSULTATION_MESSAGE_GRACE_MINUTES
            )
        )
        return close_time.replace(tzinfo=None) + timedelta(
            hours=PAYOUT_REVIEW_HOLD_HOURS
        )

    if appointment.status == "patient_no_show":
        marked_at = appointment.no_show_marked_at
        if marked_at is None:
            return None
        if marked_at.tzinfo is not None:
            marked_at = marked_at.astimezone(timezone.utc).replace(tzinfo=None)
        return marked_at + timedelta(hours=PAYOUT_REVIEW_HOLD_HOURS)

    return None


def payout_hold_has_elapsed(appointment: Appointment) -> bool:
    hold_until = consultation_payout_hold_until(appointment)
    if hold_until is None:
        return False
    return datetime.utcnow() >= hold_until


def appointment_has_blocking_refund_or_dispute(appointment: Appointment) -> bool:
    status = (getattr(appointment, "refund_status", None) or "").replace("-", "_")
    return status in {value.replace("-", "_") for value in PAYOUT_BLOCKING_REFUND_STATUSES}


def expected_consultation_payout_amount(appointment: Appointment) -> Decimal:
    """Return the current policy doctor payout from the patient-paid amount."""
    amount = Decimal(str(getattr(appointment, "amount", None) or 0)).quantize(
        Decimal("0.01")
    )
    if amount <= 0:
        return Decimal("0.00")
    _, payout = calculate_consultation_split(float(amount))
    return Decimal(str(payout)).quantize(Decimal("0.01"))


def sync_consultation_payout_amount(
    payout: ConsultationPayout,
    appointment: Appointment,
) -> Decimal | None:
    """Normalize unprocessed payout ledgers to the current split policy."""
    amount = eligible_consultation_payout_amount(
        appointment, require_hold_elapsed=False
    )
    if amount is None:
        return None
    existing_amount = Decimal(str(payout.amount or 0)).quantize(Decimal("0.01"))
    if payout.status in PAYOUT_AMOUNT_SYNC_STATUSES and existing_amount != amount:
        payout.amount = amount
        payout.last_error = None
    return amount


def eligible_consultation_payout_amount(
    appointment: Appointment,
    *,
    require_hold_elapsed: bool = True,
) -> Decimal | None:
    """Return owed doctor amount only when payout may enter admin review."""
    appointment_type = resolve_appointment_type(appointment)
    if appointment_type == APPOINTMENT_TYPE_GENERAL_QUEUE and appointment.status == "patient_no_show":
        return None
    if appointment.status not in ELIGIBLE_PAYOUT_STATUSES:
        return None
    if appointment.payment_status != "paid" or appointment.doctor_id is None:
        return None
    if appointment_has_blocking_refund_or_dispute(appointment):
        return None
    if require_hold_elapsed and not payout_hold_has_elapsed(appointment):
        return None

    amount = expected_consultation_payout_amount(appointment)
    return amount if amount > 0 else None


# Backward-compatible name used by existing admin code/tests.
def eligible_general_queue_payout_amount(
    appointment: Appointment,
) -> Decimal | None:
    if resolve_appointment_type(appointment) != APPOINTMENT_TYPE_GENERAL_QUEUE:
        return None
    return eligible_consultation_payout_amount(appointment)


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

        if appointment is not None:
            sync_consultation_payout_amount(payout, appointment)
        eligible_amount = (
            eligible_consultation_payout_amount(appointment)
            if appointment is not None
            else None
        )
        if appointment is not None and not payout_hold_has_elapsed(appointment):
            hold_until = consultation_payout_hold_until(appointment)
            raise HTTPException(
                status_code=409,
                detail=(
                    "This payout is still inside the 24-hour patient complaint "
                    f"hold. Earliest approval time: {hold_until}."
                ),
            )
        if appointment is not None and appointment_has_blocking_refund_or_dispute(appointment):
            raise HTTPException(
                status_code=409,
                detail="This payout is blocked by a pending refund or dispute review.",
            )
        if (
            appointment is None
            or eligible_amount is None
            or appointment.doctor_id != payout.doctor_id
            or eligible_amount != Decimal(str(payout.amount or 0)).quantize(Decimal("0.01"))
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


def ensure_consultation_payout(
    db: Session,
    appointment: Appointment,
) -> ConsultationPayout | None:
    """Create one admin-reviewed payout obligation for an eligible consultation."""
    amount = eligible_consultation_payout_amount(
        appointment, require_hold_elapsed=False
    )
    if amount is None:
        return None

    existing = (
        db.query(ConsultationPayout)
        .filter(ConsultationPayout.appointment_id == appointment.id)
        .first()
    )
    if existing is not None:
        sync_consultation_payout_amount(existing, appointment)
        return existing

    try:
        with db.begin_nested():
            payout = ConsultationPayout(
                appointment_id=appointment.id,
                doctor_id=appointment.doctor_id,
                amount=amount,
                status=PAYOUT_STATUS_AWAITING_ADMIN,
                reference=f"mdq-consult-payout-{appointment.id}",
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


# Backward-compatible name used by older scheduler/completion call sites.
def ensure_general_queue_payout(
    db: Session,
    appointment: Appointment,
) -> ConsultationPayout | None:
    return ensure_consultation_payout(db, appointment)


def enqueue_missing_consultation_payouts(db: Session) -> int:
    """Backfill payout obligations for all eligible consultations safely."""
    appointments = (
        db.query(Appointment)
        .filter(
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
        ensure_consultation_payout(db, appointment)
        if before is None:
            after = (
                db.query(ConsultationPayout.id)
                .filter(ConsultationPayout.appointment_id == appointment.id)
                .first()
            )
            if after is not None:
                created += 1
    db.commit()
    return created


# Backward-compatible name.
def enqueue_missing_general_queue_payouts(db: Session) -> int:
    return enqueue_missing_consultation_payouts(db)


async def process_approved_consultation_payouts() -> None:
    """Initiate only admin-approved consultation payouts after the hold window."""
    db = SessionLocal()
    try:
        enqueue_missing_consultation_payouts(db)
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
            payout = db.get(ConsultationPayout, payout_id)
            appointment = (
                db.query(Appointment)
                .filter(Appointment.id == payout.appointment_id)
                .first()
                if payout
                else None
            )
            if payout is None or appointment is None:
                continue
            if (
                eligible_consultation_payout_amount(appointment) is None
                or appointment.doctor_id != payout.doctor_id
            ):
                payout.status = "blocked"
                payout.last_error = (
                    "Payout blocked by hold window, refund/dispute review, "
                    "or changed appointment eligibility."
                )
                db.commit()
                continue

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
                    reason=f"MDQ+ consultation #{payout.appointment_id}",
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
                    "verification_required"
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
                payout.status = "verification_required"
                payout.last_error = str(exc)[:1000]
                db.commit()
                logger.exception(
                    "[PAYOUT] Unexpected payout processing error id=%s",
                    payout_id,
                )
    finally:
        db.close()


# Backward-compatible scheduler import.
async def process_approved_general_queue_payouts() -> None:
    await process_approved_consultation_payouts()
