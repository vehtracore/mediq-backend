from fastapi import APIRouter, HTTPException, status, Depends, Request
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from pydantic import BaseModel
from typing import Optional

from app.services import ai_service
from app.core.database import get_db
from app.models.user import User
from app.api import deps
from app.core.limiter import limiter

router = APIRouter()

# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    image_url: Optional[str] = None
    history: Optional[list] = None
    language: Optional[str] = "English"


class ChatResponse(BaseModel):
    response: str


# ---------------------------------------------------------------------------
# Quota constants
# ---------------------------------------------------------------------------

# ── Free tier (monthly bucket) ───────────────────────────────────────────────
_FREE_MONTHLY_MSG_LIMIT: int   = 12   # total messages per calendar month
_FREE_MONTHLY_IMAGE_LIMIT: int =  2   # image-bearing messages per calendar month

# ── Premium / Family tier (rolling 24-hour bucket) ──────────────────────────
_PAID_DAILY_MSG_LIMIT: int     = 20   # total messages per rolling 24 h
_PAID_DAILY_IMAGE_LIMIT: int   =  5   # image-bearing messages per rolling 24 h

# ── Global cold-cap (anti-spam, all plans) ───────────────────────────────────
_BURST_WINDOW_MINUTES: int  = 15   # sliding window length
_BURST_MSG_THRESHOLD: int   = 10   # messages in the window that trigger a block
_COLD_CAP_MINUTES: int      = 30   # block duration once threshold is crossed

_PAID_PLANS = {"premium", "family"}

# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/analyze", response_model=ChatResponse)
@limiter.limit("10/minute")
async def analyze_symptoms(
    request: Request,
    chat_request: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """
    AI Symptom Checker / Chat endpoint.

    Enforces a three-layer, plan-aware quota system before forwarding the
    request to the Gemini AI service:

    Layer 0 — Global Cold-Cap (anti-spam)
        Any user who sends ≥ 10 messages within a 15-minute window is
        blocked for 30 minutes, regardless of plan.

    Layer 1 — Plan gate (paid content)
        (Currently no feature is gated here; images are allowed on all plans.)

    Layer 2 — Tier-specific quota
        Free     → 12 messages / calendar month  |  2 image messages / month
        Premium  → 20 messages / rolling 24 h    |  5 image messages / 24 h
        Family   → same as Premium

    Layer 3 — AI call & counter commit
        Counters are only incremented after a successful Gemini response so
        that network/API failures do not penalise the user's allowance.
    """

    now = datetime.utcnow()
    has_image: bool = bool(chat_request.image_url and chat_request.image_url.strip())

    # Guard: at least one of text or image must be present
    if not chat_request.message.strip() and not has_image:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message or Image is required",
        )

    # =========================================================================
    # LAYER 0 — Global Cold-Cap (anti-spam, all plans)
    # =========================================================================
    # Mechanism: sliding 15-minute window tracked via burst_start_time +
    # burst_chat_count.  If the window has expired, it is reset.  If the
    # request count inside the window reaches the threshold, a 30-minute hard
    # block is stamped on chat_blocked_until and the request is rejected.
    # =========================================================================

    # ── 0a. Check whether the user is currently in a hard block ─────────────
    if current_user.chat_blocked_until is not None:
        if now < current_user.chat_blocked_until:
            minutes_remaining = int(
                (current_user.chat_blocked_until - now).total_seconds() / 60
            ) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    "For clinical safety and accuracy, please allow a short pause "
                    "between messages. You can resume chatting shortly."
                ),
            )
        else:
            # Block has expired — clear it so it doesn't trigger next time
            current_user.chat_blocked_until = None

    # ── 0b. Manage the 15-minute burst window ────────────────────────────────
    burst_window_start = current_user.burst_start_time
    if burst_window_start is None or (now - burst_window_start) > timedelta(minutes=_BURST_WINDOW_MINUTES):
        # Start a fresh window
        current_user.burst_chat_count = 0
        current_user.burst_start_time = now

    # ── 0c. Threshold check BEFORE incrementing ──────────────────────────────
    # We check at >= threshold so the (threshold)th message is still allowed;
    # the (threshold+1)th message triggers the block.
    if (current_user.burst_chat_count or 0) >= _BURST_MSG_THRESHOLD:
        current_user.chat_blocked_until = now + timedelta(minutes=_COLD_CAP_MINUTES)
        db.add(current_user)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "For clinical safety and accuracy, please allow a short pause "
                "between messages. You can resume chatting shortly."
            ),
        )

    # =========================================================================
    # LAYER 2 — Tier-specific quota
    # =========================================================================

    if current_user.plan in _PAID_PLANS:
        # ── Premium / Family: rolling 24-hour bucket ─────────────────────────
        window_start = current_user.rolling_chat_window_start

        # Reset the 24 h window if it has expired or never been set
        if window_start is None or (now - window_start) >= timedelta(hours=24):
            current_user.rolling_chat_count       = 0
            current_user.rolling_chat_image_count = 0
            current_user.rolling_chat_window_start = now

        # Check total message cap
        if (current_user.rolling_chat_count or 0) >= _PAID_DAILY_MSG_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"You've reached your {_PAID_DAILY_MSG_LIMIT}-message limit for "
                    "the rolling 24-hour window. Please try again later today or "
                    "wait for your window to reset."
                ),
            )

        # Check image sub-bucket
        if has_image and (current_user.rolling_chat_image_count or 0) >= _PAID_DAILY_IMAGE_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"You've used your {_PAID_DAILY_IMAGE_LIMIT} image analyses "
                    "allowed in the current 24-hour window. You can still send "
                    "text messages, or wait for your window to reset."
                ),
            )

    else:
        # ── Free tier: calendar-month bucket ─────────────────────────────────
        today = now.date()
        last_reset = current_user.last_chat_month_reset

        # Reset if the month has rolled over (lazy inline reset — no cron needed)
        needs_reset = (
            last_reset is None
            or last_reset.year < today.year
            or (last_reset.year == today.year and last_reset.month < today.month)
        )
        if needs_reset:
            current_user.monthly_chat_count       = 0
            current_user.monthly_chat_image_count = 0
            current_user.last_chat_month_reset    = today

        # Check total monthly message cap
        if (current_user.monthly_chat_count or 0) >= _FREE_MONTHLY_MSG_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"You've reached your {_FREE_MONTHLY_MSG_LIMIT}-message monthly "
                    "limit on the Free plan. Upgrade to Premium for up to "
                    f"{_PAID_DAILY_MSG_LIMIT} messages every 24 hours."
                ),
            )

        # Check image sub-bucket
        if has_image and (current_user.monthly_chat_image_count or 0) >= _FREE_MONTHLY_IMAGE_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"You've used your {_FREE_MONTHLY_IMAGE_LIMIT} image analyses "
                    "allowed per month on the Free plan. You can still send text "
                    "messages, or upgrade to Premium for more."
                ),
            )

    # =========================================================================
    # LAYER 3 — Call Gemini and commit counters on success
    # =========================================================================

    user_age = "Unknown"
    if current_user.dob:
        user_age = (now.date() - current_user.dob).days // 365

    user_context = {
        "age": f"{user_age} years old",
        "conditions": current_user.chronic_conditions or "None",
    }

    target_language = chat_request.language or "English"

    ai_response = await ai_service.get_medical_response(
        chat_request.message,
        history=chat_request.history,
        image_url=chat_request.image_url,
        user_context=user_context,
        target_language=target_language,
    )

    # ── Increment all relevant counters (only reached on Gemini success) ─────
    current_user.burst_chat_count = (current_user.burst_chat_count or 0) + 1

    if current_user.plan in _PAID_PLANS:
        current_user.rolling_chat_count = (current_user.rolling_chat_count or 0) + 1
        if has_image:
            current_user.rolling_chat_image_count = (current_user.rolling_chat_image_count or 0) + 1
    else:
        current_user.monthly_chat_count = (current_user.monthly_chat_count or 0) + 1
        if has_image:
            current_user.monthly_chat_image_count = (current_user.monthly_chat_image_count or 0) + 1

    db.add(current_user)
    db.commit()

    return ChatResponse(response=ai_response)