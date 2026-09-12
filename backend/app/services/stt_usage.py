"""Short-transaction monthly accounting for usable STT transcripts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import case, func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.stt_usage_reservation import STTUsageReservation
from app.models.user import User
from app.services.subscription_entitlement import has_active_paid_entitlement


FREE_MONTHLY_STT_LIMIT = 4
PREMIUM_MONTHLY_STT_LIMIT = 40
FAMILY_MONTHLY_STT_LIMIT = 30
STT_RESERVATION_TTL = timedelta(minutes=5)

STT_RESERVED = "reserved"
STT_CONSUMED = "consumed"
STT_RELEASED = "released"


@dataclass(frozen=True)
class STTAllowanceReservation:
    user_id: int
    request_digest: str
    plan: str
    used: int
    limit: int
    month_start: date


@dataclass(frozen=True)
class STTAllowanceFinalization:
    status: str
    changed: bool


def _calendar_month_start(value: datetime) -> date:
    return date(value.year, value.month, 1)


def _effective_stt_plan(user: User, now: datetime) -> str:
    plan = (user.plan or "free").strip().lower()
    if plan in {"premium", "family"} and has_active_paid_entitlement(
        user,
        now=now,
    ):
        return plan
    return "free"


def _monthly_stt_limit(plan: str) -> int:
    if plan == "premium":
        return PREMIUM_MONTHLY_STT_LIMIT
    if plan == "family":
        return FAMILY_MONTHLY_STT_LIMIT
    return FREE_MONTHLY_STT_LIMIT


def _decrement_month_count(
    db: Session,
    *,
    user_id: int,
    month_start: date,
) -> None:
    """Atomically decrement the matching month without ever going negative."""
    db.execute(
        update(User)
        .where(User.id == user_id)
        .where(User.last_stt_month_reset == month_start)
        .values(
            monthly_stt_count=case(
                (
                    func.coalesce(User.monthly_stt_count, 0) > 0,
                    func.coalesce(User.monthly_stt_count, 0) - 1,
                ),
                else_=0,
            )
        )
        .execution_options(synchronize_session=False)
    )


def _recover_stale_reservations(
    db: Session,
    *,
    user_id: int,
    now: datetime,
) -> int:
    """Release expired reservations in the caller's short transaction."""
    stale = (
        db.query(STTUsageReservation)
        .filter(STTUsageReservation.user_id == user_id)
        .filter(STTUsageReservation.status == STT_RESERVED)
        .filter(STTUsageReservation.expires_at <= now)
        .all()
    )
    recovered = 0
    for reservation in stale:
        changed = db.execute(
            update(STTUsageReservation)
            .where(STTUsageReservation.id == reservation.id)
            .where(STTUsageReservation.status == STT_RESERVED)
            .values(status=STT_RELEASED, finalized_at=now)
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            continue
        _decrement_month_count(
            db,
            user_id=user_id,
            month_start=reservation.month_start,
        )
        recovered += 1
    return recovered


def reserve_stt_allowance(
    db: Session,
    *,
    user_id: int,
    request_digest: str,
    now: datetime,
) -> STTAllowanceReservation:
    """Reserve one monthly slot and commit before any provider network call."""
    if len(request_digest) != 64:
        raise ValueError("STT request digest must be a SHA-256 hex digest")

    month_start = _calendar_month_start(now)
    try:
        _recover_stale_reservations(db, user_id=user_id, now=now)

        # Lazy reset is a bounded atomic update. A stale reservation from an old
        # month is later marked released but cannot decrement the new month.
        db.execute(
            update(User)
            .where(User.id == user_id)
            .where(
                or_(
                    User.last_stt_month_reset.is_(None),
                    User.last_stt_month_reset != month_start,
                )
            )
            .values(monthly_stt_count=0, last_stt_month_reset=month_start)
            .execution_options(synchronize_session=False)
        )

        quota_user = db.query(User).filter(User.id == user_id).first()
        if quota_user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials.",
            )

        duplicate = (
            db.query(STTUsageReservation.id)
            .filter(STTUsageReservation.user_id == user_id)
            .filter(STTUsageReservation.request_digest == request_digest)
            .first()
        )
        if duplicate is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This transcription request was already submitted.",
            )

        plan = _effective_stt_plan(quota_user, now)
        limit = _monthly_stt_limit(plan)
        incremented = db.execute(
            update(User)
            .where(User.id == user_id)
            .where(User.last_stt_month_reset == month_start)
            .where(func.coalesce(User.monthly_stt_count, 0) < limit)
            .values(
                monthly_stt_count=func.coalesce(User.monthly_stt_count, 0) + 1
            )
            .execution_options(synchronize_session=False)
        )
        if incremented.rowcount != 1:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    "You've used this month's voice input. "
                    "You can still type your message."
                ),
            )

        ledger = STTUsageReservation(
            user_id=user_id,
            request_digest=request_digest,
            month_start=month_start,
            status=STT_RESERVED,
            created_at=now,
            expires_at=now + STT_RESERVATION_TTL,
        )
        db.add(ledger)
        db.flush()
        used = (
            db.query(User.monthly_stt_count)
            .filter(User.id == user_id)
            .scalar()
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This transcription request was already submitted.",
        ) from None
    except Exception:
        db.rollback()
        raise

    return STTAllowanceReservation(
        user_id=user_id,
        request_digest=request_digest,
        plan=plan,
        used=int(used or 0),
        limit=limit,
        month_start=month_start,
    )


def finalize_stt_allowance(
    db: Session,
    reservation: STTAllowanceReservation,
    *,
    usable_transcript: bool,
    now: datetime,
) -> STTAllowanceFinalization:
    """Retain or refund a reservation exactly once in a new transaction."""
    target_status = STT_CONSUMED if usable_transcript else STT_RELEASED
    try:
        changed = db.execute(
            update(STTUsageReservation)
            .where(STTUsageReservation.user_id == reservation.user_id)
            .where(
                STTUsageReservation.request_digest == reservation.request_digest
            )
            .where(STTUsageReservation.status == STT_RESERVED)
            .values(status=target_status, finalized_at=now)
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount == 1:
            if not usable_transcript:
                _decrement_month_count(
                    db,
                    user_id=reservation.user_id,
                    month_start=reservation.month_start,
                )
            db.commit()
            return STTAllowanceFinalization(status=target_status, changed=True)

        existing_status = (
            db.query(STTUsageReservation.status)
            .filter(STTUsageReservation.user_id == reservation.user_id)
            .filter(
                STTUsageReservation.request_digest == reservation.request_digest
            )
            .scalar()
        )
        db.rollback()
        if existing_status not in {STT_CONSUMED, STT_RELEASED}:
            raise RuntimeError("STT allowance reservation is missing")
        return STTAllowanceFinalization(
            status=existing_status,
            changed=False,
        )
    except Exception:
        db.rollback()
        raise
