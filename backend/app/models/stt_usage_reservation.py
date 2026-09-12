"""Durable idempotency and refund ledger for monthly STT usage."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)

from app.core.database import Base


class STTUsageReservation(Base):
    __tablename__ = "stt_usage_reservations"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "request_digest",
            name="uq_stt_usage_reservation_user_request",
        ),
        CheckConstraint(
            "status IN ('reserved', 'consumed', 'released')",
            name="ck_stt_usage_reservation_status",
        ),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    request_digest = Column(String(64), nullable=False)
    month_start = Column(Date, nullable=False)
    status = Column(String(16), nullable=False, default="reserved", index=True)
    created_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    finalized_at = Column(DateTime, nullable=True)
