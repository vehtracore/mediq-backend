"""Short-lived, transactional result receipt for chat idempotency."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint

from app.core.database import Base


class AIChatRequestReceipt(Base):
    __tablename__ = "ai_chat_request_receipts"
    __table_args__ = (
        UniqueConstraint("patient_id", "request_digest", name="uq_ai_chat_receipt_patient_request"),
    )

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    request_digest = Column(String(64), nullable=False)
    request_fingerprint = Column(String(64), nullable=False)
    response_json = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
