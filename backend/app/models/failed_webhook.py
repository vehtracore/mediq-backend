"""
FailedWebhook model — Dead Letter Queue (DLQ)
=============================================
When a webhook event passes HMAC verification but its database update
subsequently fails (e.g. record not found, constraint violation), the
raw payload is persisted here so the event is never silently dropped.

An ops engineer or automated retry job can inspect / replay these rows.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, Text
from sqlalchemy.sql import func

from app.core.database import Base


class FailedWebhook(Base):
    __tablename__ = "failed_webhooks"

    id = Column(Integer, primary_key=True, index=True)

    # The Paystack transaction reference extracted from the payload.
    reference = Column(Text, nullable=False, index=True)

    # The raw Paystack event string, e.g. "charge.success".
    event_type = Column(Text, nullable=False)

    # Full JSON payload stored as text (JSONB on Postgres via cast in patch).
    payload = Column(Text, nullable=False)

    # The Python exception message that caused the failure.
    error_message = Column(Text, nullable=False)

    # Auto-stamped on insert; never updated.
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
