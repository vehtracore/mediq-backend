"""Durable customer-support submission and delivery state."""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.sql import func

from app.core.database import Base


class SupportMessage(Base):
    __tablename__ = "support_messages"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(
        Uuid(as_uuid=True),
        nullable=False,
        unique=True,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject = Column(Text, nullable=False)
    message = Column(Text, nullable=False)
    email_status = Column(String(32), nullable=False, default="pending", index=True)
    provider_message_id = Column(String(255), nullable=True)
    failure_category = Column(String(32), nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    sent_at = Column(DateTime(timezone=True), nullable=True)
