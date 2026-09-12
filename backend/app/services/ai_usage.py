from datetime import date, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.user import User


PAID_MONTHLY_HEAVY_AI_LIMIT = 10
FREE_MONTHLY_MESSAGE_LIMIT = 12
PREMIUM_MONTHLY_MESSAGE_LIMIT = 300
FAMILY_MONTHLY_MESSAGE_LIMIT = 250
PAID_POST_CAP_DAILY_LIMIT = 5
AI_BURST_WINDOW_MINUTES = 15
AI_BURST_MESSAGE_LIMIT = 15
AI_COLD_CAP_MINUTES = 15
PAID_AI_PLANS = {"premium", "family"}


def _needs_month_reset(last_reset: date | None, today: date) -> bool:
    return (
        last_reset is None
        or last_reset.year < today.year
        or (
            last_reset.year == today.year
            and last_reset.month < today.month
        )
    )


def reset_monthly_ai_usage(user: User, today: date) -> None:
    """Reset monthly text, chat-image, and lab counters on their shared month."""
    if _needs_month_reset(user.last_chat_month_reset, today):
        user.monthly_chat_count = 0
        user.monthly_chat_image_count = 0
        user.last_chat_month_reset = today
        user.rolling_chat_count = 0
        user.rolling_chat_image_count = 0
        user.rolling_chat_window_start = None

    if _needs_month_reset(user.last_lab_reset, today):
        user.monthly_lab_count = 0
        user.last_lab_reset = today


def monthly_heavy_ai_usage(user: User) -> int:
    return (
        (user.monthly_chat_image_count or 0)
        + (user.monthly_lab_count or 0)
    )


def _paid_message_limit(plan: str) -> int:
    return (
        FAMILY_MONTHLY_MESSAGE_LIMIT
        if plan == "family"
        else PREMIUM_MONTHLY_MESSAGE_LIMIT
    )


def enforce_ai_text_usage_available(
    user: User,
    now: datetime,
    db: Session,
) -> None:
    """Apply the existing text-AI burst/monthly gates to a summary save."""
    reset_monthly_ai_usage(user, now.date())

    if user.chat_blocked_until is not None:
        if now < user.chat_blocked_until:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="AI usage is temporarily limited. Please try again later.",
            )
        user.chat_blocked_until = None

    if (
        user.burst_start_time is None
        or (now - user.burst_start_time)
        > timedelta(minutes=AI_BURST_WINDOW_MINUTES)
    ):
        user.burst_chat_count = 0
        user.burst_start_time = now

    if (user.burst_chat_count or 0) >= AI_BURST_MESSAGE_LIMIT:
        user.chat_blocked_until = now + timedelta(minutes=AI_COLD_CAP_MINUTES)
        db.add(user)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="AI usage is temporarily limited. Please try again later.",
        )

    if user.plan in PAID_AI_PLANS:
        if (
            user.rolling_chat_window_start is None
            or (now - user.rolling_chat_window_start) >= timedelta(hours=24)
        ):
            user.rolling_chat_count = 0
            user.rolling_chat_image_count = 0
            user.rolling_chat_window_start = now

        if (
            (user.monthly_chat_count or 0) >= _paid_message_limit(user.plan)
            and (user.rolling_chat_count or 0) >= PAID_POST_CAP_DAILY_LIMIT
        ):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Your AI usage limit has been reached. Please try again later.",
            )
        return

    if (user.monthly_chat_count or 0) >= FREE_MONTHLY_MESSAGE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Your AI usage limit has been reached. Please try again later.",
        )


def record_successful_ai_text_usage(user: User) -> None:
    """Meter one successful save operation as one existing text-AI use."""
    user.burst_chat_count = (user.burst_chat_count or 0) + 1
    monthly_before = user.monthly_chat_count or 0
    user.monthly_chat_count = monthly_before + 1
    if (
        user.plan in PAID_AI_PLANS
        and monthly_before >= _paid_message_limit(user.plan)
    ):
        user.rolling_chat_count = (user.rolling_chat_count or 0) + 1
