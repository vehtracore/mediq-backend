"""One durable in-flight chat claim per patient."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from app.core.database import Base


class AIChatClaim(Base):
    __tablename__ = "ai_chat_claims"

    patient_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    request_digest = Column(String(64), nullable=False)
    request_fingerprint = Column(String(64), nullable=False)
    owner = Column(String(36), nullable=False)
    lease_expires_at = Column(DateTime(timezone=True), nullable=False)
