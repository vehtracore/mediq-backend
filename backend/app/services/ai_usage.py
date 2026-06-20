from datetime import date

from app.models.user import User


PAID_MONTHLY_HEAVY_AI_LIMIT = 10


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
