"""Payload-free ledger for Emergency NOK SMS idempotency."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.sql import func

from app.core.database import Base


class EmergencySmsRequest(Base):
    __tablename__ = "emergency_sms_requests"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "request_id",
            name="uq_emergency_sms_requests_user_request",
        ),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    request_id = Column(String(128), nullable=False)
    request_fingerprint = Column(String(64), nullable=True)
    status = Column(String(32), nullable=False, default="reserved")
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
