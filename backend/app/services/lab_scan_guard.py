from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.ai_usage import monthly_heavy_ai_usage, PAID_MONTHLY_HEAVY_AI_LIMIT


LAB_FAILED_ATTEMPT_LIMIT = 3
LAB_FAILED_SESSION_MINUTES = 30
LAB_COOLDOWN_HOURS = 24


@dataclass(frozen=True)
class LabScanFailureAction:
    failed_attempt_count: int
    attempts_remaining: int
    quota_deducted: bool


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _reset_failed_streak(user: User) -> None:
    user.lab_failed_attempt_count = 0
    user.lab_failed_attempt_started_at = None
    user.lab_last_failed_attempt_at = None


def _reset_expired_failed_streak(user: User, now: datetime) -> bool:
    last_failed_at = _aware_utc(user.lab_last_failed_attempt_at)
    if last_failed_at is None:
        return False

    if now - last_failed_at <= timedelta(minutes=LAB_FAILED_SESSION_MINUTES):
        return False

    _reset_failed_streak(user)
    return True


def enforce_lab_scan_guard(db: Session, user: User) -> None:
    now = _utcnow()
    changed = False

    cooldown_until = _aware_utc(user.lab_cooldown_until)
    if cooldown_until is not None and cooldown_until <= now:
        user.lab_cooldown_until = None
        changed = True
    elif cooldown_until is not None:
        remaining_minutes = max(1, int((cooldown_until - now).total_seconds() // 60))
        raise HTTPException(
            status_code=429,
            detail=(
                "Scanner is temporarily locked after repeated unreadable scans. "
                f"Please try again in about {remaining_minutes} minutes."
            ),
        )

    changed = _reset_expired_failed_streak(user, now) or changed

    if (user.lab_failed_attempt_count or 0) > LAB_FAILED_ATTEMPT_LIMIT:
        user.lab_cooldown_until = now + timedelta(hours=LAB_COOLDOWN_HOURS)
        db.add(user)
        db.commit()
        raise HTTPException(
            status_code=429,
            detail=(
                "Scanner is temporarily locked after repeated unreadable scans. "
                "Please try again tomorrow."
            ),
        )

    if changed:
        db.add(user)
        db.commit()


def record_lab_scan_success(user: User) -> None:
    _reset_failed_streak(user)
    user.lab_cooldown_until = None


def record_lab_scan_failure(db: Session, user: User) -> LabScanFailureAction:
    now = _utcnow()
    _reset_expired_failed_streak(user, now)

    current_count = user.lab_failed_attempt_count or 0
    if current_count == 0:
        user.lab_failed_attempt_started_at = now

    failed_attempt_count = current_count + 1
    user.lab_failed_attempt_count = failed_attempt_count
    user.lab_last_failed_attempt_at = now

    quota_deducted = False
    if failed_attempt_count == LAB_FAILED_ATTEMPT_LIMIT + 1:
        if monthly_heavy_ai_usage(user) < PAID_MONTHLY_HEAVY_AI_LIMIT:
            user.monthly_lab_count = (user.monthly_lab_count or 0) + 1
            quota_deducted = True

    db.add(user)
    db.commit()

    return LabScanFailureAction(
        failed_attempt_count=failed_attempt_count,
        attempts_remaining=max(0, LAB_FAILED_ATTEMPT_LIMIT - failed_attempt_count),
        quota_deducted=quota_deducted,
    )


def add_scan_failure_guidance(
    reason: str | None,
    action: LabScanFailureAction,
) -> str:
    base_reason = reason or "The image could not be read clearly."

    if action.quota_deducted:
        return (
            f"{base_reason} This was your 4th consecutive failed scan, so 1 "
            "AI photo/lab unit has been deducted from your monthly allowance."
        )

    if action.attempts_remaining == 0:
        return (
            f"{base_reason} Your next consecutive failed scan will use 1 AI "
            "photo/lab unit from your monthly allowance."
        )

    return (
        f"{base_reason} You have {action.attempts_remaining} failed scan "
        "attempt(s) left before a penalty applies."
    )
