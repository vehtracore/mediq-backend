
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta, timezone
from app.core.database import Base
from app.models.user import User 

APPOINTMENT_TYPE_GENERAL_QUEUE = "general_queue"
APPOINTMENT_TYPE_SPECIALIST_SCHEDULED = "specialist_scheduled"
APPOINTMENT_TYPE_VIP_REQUEST = "vip_request"

VALID_APPOINTMENT_TYPES = frozenset(
    {
        APPOINTMENT_TYPE_GENERAL_QUEUE,
        APPOINTMENT_TYPE_SPECIALIST_SCHEDULED,
        APPOINTMENT_TYPE_VIP_REQUEST,
    }
)


class DoctorSlot(Base):
    __tablename__ = "doctor_slots"
    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), index=True)
    start_time = Column(DateTime, index=True)
    is_booked = Column(Boolean, default=False)
    doctor = relationship("Doctor", backref="slots")

class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint(
            "appointment_type IS NULL OR appointment_type IN "
            "('general_queue', 'specialist_scheduled', 'vip_request')",
            name="ck_appointments_appointment_type",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("users.id"), index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=True, index=True)
    slot_id = Column(Integer, ForeignKey("doctor_slots.id"), unique=True, nullable=True)
    # Nullable during the legacy backfill phase. All newly-created appointments
    # must set this explicitly; ambiguous historical rows remain NULL until
    # reviewed rather than being assigned the wrong workflow.
    appointment_type = Column(String(32), nullable=True, index=True)
    start_time = Column(DateTime, default=datetime.utcnow, nullable=True, index=True)
    status = Column(String, default="pending", index=True)
    payment_status = Column(String, default="unpaid")
    is_acknowledged = Column(Boolean, default=False)
    notes = Column(String, nullable=True)
    related_appointment_id = Column(Integer, nullable=True)
    amount = Column(Float, default=0.0)
    commission = Column(Float, default=0.0)
    payout = Column(Float, default=0.0)
    # Paystack reference embedded at checkout — used by the payment watchdog
    paystack_reference = Column(String, nullable=True, index=True)
    # --- Continuity of Care: Physical Referral ---
    referred_hospital = Column(String, nullable=True)   # e.g. "Lagos Island General Hospital A&E"
    referral_note = Column(String, nullable=True)        # Standardised referral string
    # --- Doctor Prescription ---
    prescription = Column(Text, nullable=True)           # Free-text prescription / medication plan

    patient = relationship("User")
    doctor = relationship("Doctor")
    slot = relationship("DoctorSlot", backref="appointment", uselist=False)
    # NEW: Link to review
    review = relationship("Review", back_populates="appointment", uselist=False)


def resolve_appointment_type(appointment: Appointment) -> str | None:
    """Return the durable type, with conservative legacy detection.

    A claimed general-queue appointment and a VIP request can both have a
    doctor_id and no slot_id, so that shape is deliberately left unresolved
    unless the stored type or Paystack reference identifies the workflow.
    """
    stored_type = getattr(appointment, "appointment_type", None)
    if stored_type in VALID_APPOINTMENT_TYPES:
        return stored_type

    if getattr(appointment, "slot_id", None) is not None:
        return APPOINTMENT_TYPE_SPECIALIST_SCHEDULED

    reference = (getattr(appointment, "paystack_reference", None) or "").lower()
    if "gp_consult" in reference:
        return APPOINTMENT_TYPE_GENERAL_QUEUE
    if "vip_request" in reference:
        return APPOINTMENT_TYPE_VIP_REQUEST
    if "specialist" in reference:
        return APPOINTMENT_TYPE_SPECIALIST_SCHEDULED

    if (
        getattr(appointment, "doctor_id", None) is None
        and getattr(appointment, "slot_id", None) is None
    ):
        return APPOINTMENT_TYPE_GENERAL_QUEUE

    return None


def as_utc(value: datetime | None) -> datetime | None:
    """Return a datetime as timezone-aware UTC.

    Appointment timestamps are stored as naive UTC in the current database
    schema. API and authorization code must restore the UTC timezone before
    comparing or serializing them.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def as_naive_utc(value: datetime) -> datetime:
    """Normalize an incoming datetime for the database's naive-UTC columns."""
    normalized = as_utc(value)
    assert normalized is not None
    return normalized.replace(tzinfo=None)


def appointment_start_utc(appointment: Appointment) -> datetime | None:
    """Resolve the consultation's effective scheduled start time."""
    appointment_type = resolve_appointment_type(appointment)
    if (
        appointment_type == APPOINTMENT_TYPE_SPECIALIST_SCHEDULED
        and getattr(appointment, "slot", None) is not None
    ):
        return as_utc(appointment.slot.start_time)
    return as_utc(getattr(appointment, "start_time", None))


def consultation_room_is_unlocked(
    appointment: Appointment,
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether the consultation room may open.

    General-queue consultations remain immediately available after a doctor
    claims them. Scheduled specialist and VIP consultations unlock ten minutes
    before their effective start time.
    """
    if resolve_appointment_type(appointment) == APPOINTMENT_TYPE_GENERAL_QUEUE:
        return True

    start = appointment_start_utc(appointment)
    if start is None:
        return False

    now_utc = as_utc(now) if now is not None else datetime.now(timezone.utc)
    assert now_utc is not None
    return now_utc >= start - timedelta(minutes=10)
