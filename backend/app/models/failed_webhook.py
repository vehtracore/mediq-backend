"""
FailedWebhook model — Dead Letter Queue (DLQ)
=============================================
When a webhook event passes HMAC verification but its database update
subsequently fails (e.g. record not found, constraint violation), a minimal
sanitised event summary is persisted here for operational diagnosis.

An ops engineer can inspect these rows and correlate them with provider
redelivery or a fresh, independently verified transaction lookup.
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

    # Legacy column name retained for schema compatibility. New writes contain
    # only safe identifiers, never the full webhook payload.
    payload = Column(Text, nullable=False)

    # Bounded operational error classification, not an exception or payload.
    error_message = Column(Text, nullable=False)

    # Auto-stamped on insert; never updated.
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
