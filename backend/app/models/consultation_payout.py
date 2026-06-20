from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
)

from app.core.database import Base


class ConsultationPayout(Base):
    """Idempotent doctor payout obligation for a general-queue appointment."""

    __tablename__ = "consultation_payouts"

    id = Column(Integer, primary_key=True, index=True)
    appointment_id = Column(
        Integer,
        ForeignKey("appointments.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    doctor_id = Column(
        Integer,
        ForeignKey("doctors.id"),
        nullable=False,
        index=True,
    )
    amount = Column(Numeric(14, 2), nullable=False)
    status = Column(
        String(32),
        nullable=False,
        default="awaiting_admin",
        index=True,
    )
    reference = Column(String(64), nullable=False, unique=True, index=True)
    recipient_code = Column(String, nullable=True)
    transfer_code = Column(String, nullable=True, index=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    paid_at = Column(DateTime, nullable=True)
    approved_by_admin_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    approved_at = Column(DateTime, nullable=True)
    rejected_by_admin_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    rejected_at = Column(DateTime, nullable=True)
    rejection_reason = Column(String, nullable=True)
