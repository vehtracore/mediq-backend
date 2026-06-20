from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.models.appointment import (
    Appointment,
    attendance_deadline_utc,
    consultation_started_utc,
    consultation_room_is_unlocked,
)
from app.models.user import User
from app.services.consultation_pricing import (
    DEFAULT_CONSULTATION_DURATION_MINUTES,
    CONSULTATION_MESSAGE_GRACE_MINUTES,
)

NO_SHOW_STATUSES = {
    "patient_no_show",
    "doctor_no_show",
    "both_no_show",
}


def require_consultation_access(
    db: Session,
    appointment_id: int,
    current_user: User,
    *,
    allow_completed: bool = False,
    allow_message_grace: bool = False,
) -> Appointment:
    """Authorize a patient or assigned doctor to enter a consultation room."""
    appointment = (
        db.query(Appointment)
        .options(
            joinedload(Appointment.doctor),
            joinedload(Appointment.slot),
        )
        .filter(Appointment.id == appointment_id)
        .first()
    )
    if appointment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found.",
        )

    is_patient = appointment.patient_id == current_user.id
    is_assigned_doctor = (
        appointment.doctor is not None
        and appointment.doctor.user_id == current_user.id
    )
    if not is_patient and not is_assigned_doctor:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this consultation.",
        )

    allowed_statuses = {"confirmed"}
    if allow_completed:
        allowed_statuses.update({"completed", *NO_SHOW_STATUSES})
    if appointment.status not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This consultation room is not active.",
        )

    if appointment.payment_status != "paid":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The consultation room is unavailable until payment is verified.",
        )

    if not consultation_room_is_unlocked(appointment):
        deadline = attendance_deadline_utc(appointment)
        if (
            appointment.consultation_started_at is None
            and deadline is not None
            and datetime.now(timezone.utc) >= deadline
        ):
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="The attendance window for this consultation has closed.",
            )
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="The consultation room unlocks 10 minutes before the appointment.",
        )

    start_time = consultation_started_utc(appointment)
    if start_time is None:
        return appointment

    allowed_minutes = DEFAULT_CONSULTATION_DURATION_MINUTES
    if allow_message_grace:
        allowed_minutes += CONSULTATION_MESSAGE_GRACE_MINUTES
    consultation_end = start_time + timedelta(minutes=allowed_minutes)
    if not allow_completed and datetime.now(timezone.utc) >= consultation_end:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This consultation has ended.",
        )

    return appointment


def record_consultation_attendance(
    db: Session,
    appointment_id: int,
    current_user: User,
) -> Appointment:
    """Record the first join and start the clock when the second party joins."""
    appointment = (
        db.query(Appointment)
        .filter(Appointment.id == appointment_id)
        .with_for_update()
        .first()
    )
    if appointment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found.",
        )
    if appointment.status != "confirmed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This consultation room is not active.",
        )

    now = datetime.utcnow()
    if appointment.patient_id == current_user.id:
        if appointment.patient_joined_at is None:
            appointment.patient_joined_at = now
    elif (
        appointment.doctor is not None
        and appointment.doctor.user_id == current_user.id
    ):
        if appointment.doctor_joined_at is None:
            appointment.doctor_joined_at = now
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to join this consultation.",
        )

    if (
        appointment.patient_joined_at is not None
        and appointment.doctor_joined_at is not None
        and appointment.consultation_started_at is None
    ):
        appointment.consultation_started_at = now

    db.commit()
    db.refresh(appointment)
    return appointment
