from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.models.appointment import (
    Appointment,
    consultation_room_is_unlocked,
)
from app.models.user import User


def require_consultation_access(
    db: Session,
    appointment_id: int,
    current_user: User,
    *,
    allow_completed: bool = False,
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
        allowed_statuses.add("completed")
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
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="The consultation room unlocks 10 minutes before the appointment.",
        )

    return appointment
