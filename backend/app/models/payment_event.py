'''Minimal, payload-free ledger for payment webhook idempotency.'''

from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.core.database import Base


class PaymentEvent(Base):
    __tablename__ = 'payment_events'
    __table_args__ = (
        UniqueConstraint(
            'provider',
            'provider_event_key',
            name='uq_payment_events_provider_event_key',
        ),
        UniqueConstraint(
            'provider',
            'payment_key',
            name='uq_payment_events_provider_payment_key',
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String(32), nullable=False)
    event_type = Column(String(80), nullable=False)
    provider_event_key = Column(String(255), nullable=False)
    payment_key = Column(String(255), nullable=True)
    transaction_reference = Column(String(255), nullable=True, index=True)
    subscription_code = Column(String(255), nullable=True, index=True)
    invoice_code = Column(String(255), nullable=True, index=True)
    user_id = Column(Integer, nullable=True, index=True)
    processing_status = Column(String(32), nullable=False, default='processing')
    error_code = Column(String(80), nullable=True)
    received_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    processed_at = Column(DateTime(timezone=True), nullable=True)
    # Short non-sensitive note only. Never store a webhook body here.
    processing_note = Column(Text, nullable=True)
