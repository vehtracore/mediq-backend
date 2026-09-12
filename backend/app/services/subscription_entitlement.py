"""Shared paid-subscription entitlement checks."""

from datetime import datetime, timezone
from typing import Any


PAID_PLANS = frozenset({"premium", "family"})


def has_active_paid_entitlement(user: Any, *, now: datetime | None = None) -> bool:
    """Return whether a user currently has Premium or Family access."""
    plan = (getattr(user, "plan", None) or "free").strip().lower()
    if plan not in PAID_PLANS:
        return False

    expiry = getattr(user, "subscription_expiry", None)
    if expiry is None:
        return True

    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    reference_time = now or datetime.now(timezone.utc)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)
    return expiry >= reference_time
