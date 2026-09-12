from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NotificationDeviceToken(Base):
    __tablename__ = "notification_device_tokens"
    __table_args__ = (
        UniqueConstraint("installation_id", name="uq_notification_device_installation"),
        UniqueConstraint("token", name="uq_notification_device_token"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    installation_id = Column(String(36), nullable=False)
    token = Column(String, nullable=False)
    platform = Column(String(20), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )
    last_seen_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
