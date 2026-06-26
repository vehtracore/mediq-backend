import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.appointment import Appointment
from app.models.vault import ConsultationRecord
from app.services.consultation_payout_service import ensure_consultation_payout

logger = logging.getLogger(__name__)


def complete_consultation(db: Session, appointment: Appointment) -> None:
    """Mark a started consultation complete and sync vault/payout side effects.

    This helper is used by both the doctor action and the nightly cleanup so
    auto-completed consultations do not bypass vault record creation.
    It does not commit; callers own transaction boundaries.
    """
    appointment.status = "completed"

    referrals = (
        f"Referred to: {appointment.referred_hospital}\nNote: {appointment.referral_note}"
        if appointment.referred_hospital
        else None
    )

    existing = (
        db.query(ConsultationRecord)
        .filter(ConsultationRecord.appointment_id == appointment.id)
        .first()
    )
    if existing is None:
        db.add(
            ConsultationRecord(
                appointment_id=appointment.id,
                patient_id=appointment.patient_id,
                doctor_id=appointment.doctor_id,
                clinical_notes=appointment.notes,
                prescriptions=appointment.prescription,
                referrals=referrals,
                created_at=datetime.now(timezone.utc),
            )
        )
        logger.info(
            "[Vault] ConsultationRecord created ? appt_id=%s patient_id=%s doctor_id=%s prescription=%s referral=%s",
            appointment.id,
            appointment.patient_id,
            appointment.doctor_id,
            bool(appointment.prescription),
            bool(referrals),
        )
    else:
        existing.clinical_notes = appointment.notes
        if appointment.prescription:
            existing.prescriptions = appointment.prescription
        if referrals:
            existing.referrals = referrals
        logger.info(
            "[Vault] ConsultationRecord updated ? appt_id=%s prescription=%s referral=%s",
            appointment.id,
            bool(appointment.prescription),
            bool(referrals),
        )

    ensure_consultation_payout(db, appointment)
