
import uuid
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base


class AIChatSummary(Base):
    """
    Persists a structured summary of an AI chat session for a patient.
    One row per topic/session; created by the POST /vault/ai-summary endpoint
    after the chat ends.
    """
    __tablename__ = "ai_chat_summaries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    patient_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    topic = Column(String, nullable=False)
    summary_text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)

    # Relationships
    patient = relationship("User", foreign_keys=[patient_id])


class ConsultationRecord(Base):
    """
    Clinical record generated after a completed doctor–patient appointment.
    Links back to the appointments table (appointment_id) and carries
    structured clinical data: notes, prescriptions (JSONB), and referrals (JSONB).
    """
    __tablename__ = "consultation_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    appointment_id = Column(Integer, unique=True, nullable=False, index=True)
    patient_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="SET NULL"), nullable=True, index=True)
    clinical_notes = Column(Text, nullable=True)
    prescriptions = Column(JSONB, nullable=True)   # e.g. [{"drug": "...", "dosage": "..."}]
    referrals = Column(JSONB, nullable=True)        # e.g. [{"hospital": "...", "reason": "..."}]
    created_at = Column(DateTime(timezone=True), nullable=False)

    # Relationships
    patient = relationship("User", foreign_keys=[patient_id])
    doctor = relationship("Doctor", foreign_keys=[doctor_id])
