import logging
import os
import uuid

import cloudinary
import cloudinary.api
import cloudinary.utils
import cloudinary.uploader
from fastapi import (
    APIRouter,
    HTTPException,
    status,
    Depends,
    Request,
    File,
    Header,
    UploadFile,
)
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel
from typing import Optional

from app.services import ai_service
from app.core.database import get_db
from app.models.user import User
from app.api import deps
from app.api.v1.ai_consent import require_active_ai_consent
from app.core.limiter import limiter
from app.services.ai_usage import (
    PAID_MONTHLY_HEAVY_AI_LIMIT,
    monthly_heavy_ai_usage,
    reset_monthly_ai_usage,
)
from app.services.ai_request_guard import (
    AIRequestLease,
    acquire_ai_request_lease,
    release_ai_request_lease,
)

router = APIRouter()
logger = logging.getLogger(__name__)

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True,
)

# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    image_url: Optional[str] = None
    image_public_id: Optional[str] = None
    history: Optional[list] = None
    language: Optional[str] = "English"
    conversation_memory: Optional[str] = None
    memory_source: Optional[str] = None
    update_memory: bool = False


class ChatResponse(BaseModel):
    response: str
    usage_notice: Optional[str] = None
    memory_summary: Optional[str] = None


class TemporaryImageResponse(BaseModel):
    url: str
    public_id: str


# ---------------------------------------------------------------------------
# Quota constants
# ---------------------------------------------------------------------------

# ── Free tier (monthly bucket) ───────────────────────────────────────────────
_FREE_MONTHLY_MSG_LIMIT: int   = 12   # total messages per calendar month
_FREE_MONTHLY_IMAGE_LIMIT: int =  2   # image-bearing messages per calendar month

# Premium / Family per-account fair-use thresholds
_PREMIUM_MONTHLY_MSG_SOFT_LIMIT: int = 300
_PREMIUM_MONTHLY_WARNING_AT: int = 250
_FAMILY_MONTHLY_MSG_SOFT_LIMIT: int = 250
_FAMILY_MONTHLY_WARNING_AT: int = 200
_PAID_POST_CAP_DAILY_LIMIT: int = 5

# ── Global cold-cap (anti-spam, all plans) ───────────────────────────────────
_BURST_WINDOW_MINUTES: int  = 15   # sliding window length
_BURST_MSG_THRESHOLD: int = 15
_COLD_CAP_MINUTES: int = 15

_PAID_PLANS = {"premium", "family"}
_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/jpg"}
_MAX_TEMP_IMAGE_BYTES = 5 * 1024 * 1024
_TEMP_IMAGE_TTL = timedelta(hours=2)


def require_ai_request_slot(
    x_ai_request_id: Optional[str] = Header(
        default=None,
        alias="X-AI-Request-ID",
        min_length=8,
        max_length=128,
    ),
    current_user: User = Depends(deps.get_current_user),
):
    """Allow only one AI analyze request per user and reject request retries."""
    lease = acquire_ai_request_lease(
        current_user.id,
        x_ai_request_id,
    )
    try:
        yield lease
    finally:
        release_ai_request_lease(lease)


def _paid_message_thresholds(plan: str) -> tuple[int, int]:
    if plan == "family":
        return _FAMILY_MONTHLY_MSG_SOFT_LIMIT, _FAMILY_MONTHLY_WARNING_AT
    return _PREMIUM_MONTHLY_MSG_SOFT_LIMIT, _PREMIUM_MONTHLY_WARNING_AT


def _require_owned_temp_image(public_id: str, user_id: int) -> None:
    if not public_id.startswith(f"mediq_ai_temp/{user_id}/"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Temporary image does not belong to this user.",
        )


def _delete_temp_image(public_id: str, user_id: int) -> bool:
    _require_owned_temp_image(public_id, user_id)
    try:
        result = cloudinary.uploader.destroy(
            public_id,
            resource_type="image",
            invalidate=True,
        )
        return result.get("result") in {"ok", "not found"}
    except Exception:
        logger.exception(
            "[AI TEMP IMAGE] Cleanup failed for user_id=%s public_id=%s",
            user_id,
            public_id,
        )
        return False


def cleanup_stale_temp_images() -> int:
    """Delete abandoned AI chat images older than the temporary retention TTL."""
    cutoff = datetime.now(timezone.utc) - _TEMP_IMAGE_TTL
    deleted_count = 0
    next_cursor = None

    while True:
        options = {
            "resource_type": "image",
            "type": "upload",
            "prefix": "mediq_ai_temp/",
            "max_results": 500,
        }
        if next_cursor:
            options["next_cursor"] = next_cursor

        result = cloudinary.api.resources(**options)
        for resource in result.get("resources", []):
            created_at = resource.get("created_at")
            public_id = resource.get("public_id")
            if not created_at or not public_id:
                continue

            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if created > cutoff:
                continue

            try:
                deletion = cloudinary.uploader.destroy(
                    public_id,
                    resource_type="image",
                    invalidate=True,
                )
                if deletion.get("result") in {"ok", "not found"}:
                    deleted_count += 1
            except Exception:
                logger.exception(
                    "[AI TEMP IMAGE] Failed deleting stale public_id=%s",
                    public_id,
                )

        next_cursor = result.get("next_cursor")
        if not next_cursor:
            break

    if deleted_count:
        logger.info(
            "[AI TEMP IMAGE] Removed %d image(s) older than %s hours.",
            deleted_count,
            int(_TEMP_IMAGE_TTL.total_seconds() // 3600),
        )
    return deleted_count

# ---------------------------------------------------------------------------
# Temporary image endpoints
# ---------------------------------------------------------------------------

@router.post("/image", response_model=TemporaryImageResponse)
@limiter.limit("10/hour")
async def upload_temporary_chat_image(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(deps.get_current_user),
):
    require_active_ai_consent(current_user)

    filename = (file.filename or "").lower()
    has_allowed_extension = filename.endswith((".jpg", ".jpeg", ".png", ".webp"))
    if file.content_type not in _ALLOWED_IMAGE_TYPES and not has_allowed_extension:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid image type. Use JPEG, PNG, or WebP.",
        )

    content = await file.read(_MAX_TEMP_IMAGE_BYTES + 1)
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded image is empty.",
        )
    if len(content) > _MAX_TEMP_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Image exceeds the 5MB upload limit.",
        )

    public_id = f"mediq_ai_temp/{current_user.id}/{uuid.uuid4()}"
    try:
        result = cloudinary.uploader.upload(
            content,
            public_id=public_id,
            resource_type="image",
            overwrite=False,
        )
    except Exception:
        logger.exception(
            "[AI TEMP IMAGE] Upload failed for user_id=%s",
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Temporary image upload failed.",
        )

    return TemporaryImageResponse(
        url=result["secure_url"],
        public_id=result["public_id"],
    )


@router.delete("/image")
def delete_temporary_chat_image(
    public_id: str,
    current_user: User = Depends(deps.get_current_user),
):
    if not _delete_temp_image(public_id, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Temporary image cleanup failed.",
        )
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Chat endpoint
# ---------------------------------------------------------------------------

@router.post("/analyze", response_model=ChatResponse)
@limiter.limit("30/minute")
async def analyze_symptoms(
    request: Request,
    chat_request: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
    request_lease: AIRequestLease = Depends(require_ai_request_slot),
):
    """
    AI Symptom Checker / Chat endpoint.

    Enforces a three-layer, plan-aware quota system before forwarding the
    request to the Gemini AI service:

    Layer 0 — Global Cold-Cap (anti-spam)
        Any user who sends 15 messages within a 15-minute window is
        paused for 15 minutes, regardless of plan.

    Layer 1 — Plan gate (paid content)
        (Currently no feature is gated here; images are allowed on all plans.)

    Layer 2 — Tier-specific quota
        Free     → 12 messages / calendar month  |  2 image messages / month
        Premium → 300 standard messages per calendar month.
        Family  → 250 standard messages per member per calendar month.
        After the applicable threshold, five priority messages remain per
        rolling 24 hours.

    Layer 3 — AI call & counter commit
        Counters are only incremented after a successful Gemini response so
        that network/API failures do not penalise the user's allowance.
    """

    require_active_ai_consent(current_user)

    now = datetime.utcnow()
    has_image = bool(chat_request.image_public_id)
    trusted_image_url = None

    if chat_request.image_url and not has_image:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Temporary image identifier is required.",
        )

    if has_image:
        _require_owned_temp_image(chat_request.image_public_id, current_user.id)
        trusted_image_url = cloudinary.utils.cloudinary_url(
            chat_request.image_public_id,
            secure=True,
            resource_type="image",
        )[0]

    # Guard: at least one of text or image must be present
    if not chat_request.message.strip() and not has_image:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message or Image is required",
        )

    today = now.date()
    reset_monthly_ai_usage(current_user, today)

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
        monthly_soft_limit, monthly_warning_at = _paid_message_thresholds(
            current_user.plan
        )
        # Premium / Family fair use and post-cap rolling allowance.
        window_start = current_user.rolling_chat_window_start

        # Reset the 24 h window if it has expired or never been set
        if window_start is None or (now - window_start) >= timedelta(hours=24):
            current_user.rolling_chat_count       = 0
            current_user.rolling_chat_image_count = 0
            current_user.rolling_chat_window_start = now

        # Check total message cap
        fair_use_active = (
            (current_user.monthly_chat_count or 0)
            >= monthly_soft_limit
        )
        if (
            fair_use_active
            and (current_user.rolling_chat_count or 0)
            >= _PAID_POST_CAP_DAILY_LIMIT
        ):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    "Your account has reached this month's fair-use threshold. "
                    "Your five priority messages for the current 24-hour period "
                    "have been used. More become available when the period resets."
                ),
            )

        if (
            has_image
            and monthly_heavy_ai_usage(current_user)
            >= PAID_MONTHLY_HEAVY_AI_LIMIT
        ):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    "You've used this month's 10 AI photo and lab "
                    "interpretations. Text AI support remains available."
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
                    "limit on the Free plan. Upgrade to Premium for unlimited "
                    "everyday AI support, subject to fair use."
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

    try:
        try:
            ai_result = await ai_service.get_medical_response(
                chat_request.message,
                history=chat_request.history,
                image_url=trusted_image_url,
                user_context=user_context,
                target_language=target_language,
                conversation_memory=chat_request.conversation_memory,
                memory_source=chat_request.memory_source,
                update_memory=chat_request.update_memory,
            )
        except ai_service.AIInputLimitError as exc:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=str(exc),
            )
        except Exception:
            logger.exception(
                "[AI CHAT] Gemini processing failed for user_id=%s",
                current_user.id,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI service is temporarily unavailable. Please try again.",
            )
    finally:
        if chat_request.image_public_id:
            _delete_temp_image(
                chat_request.image_public_id,
                current_user.id,
            )

    # ── Increment all relevant counters (only reached on Gemini success) ─────
    current_user.burst_chat_count = (current_user.burst_chat_count or 0) + 1

    usage_notice = None
    if current_user.plan in _PAID_PLANS:
        monthly_soft_limit, monthly_warning_at = _paid_message_thresholds(
            current_user.plan
        )
        monthly_before_increment = current_user.monthly_chat_count or 0
        current_user.monthly_chat_count = monthly_before_increment + 1

        if monthly_before_increment >= monthly_soft_limit:
            current_user.rolling_chat_count = (
                current_user.rolling_chat_count or 0
            ) + 1

        if current_user.monthly_chat_count == monthly_warning_at:
            usage_notice = (
                "You've been using MDQ+ AI frequently this month. "
                "Your plan remains available, and fair-use controls apply "
                "only to exceptional usage."
            )
        elif current_user.monthly_chat_count == monthly_soft_limit:
            usage_notice = (
                "You've reached this month's standard fair-use threshold. "
                "Five priority messages per 24 hours remain available until "
                "your monthly allowance resets."
            )

        if has_image:
            current_user.monthly_chat_image_count = (
                current_user.monthly_chat_image_count or 0
            ) + 1
    else:
        current_user.monthly_chat_count = (current_user.monthly_chat_count or 0) + 1
        if has_image:
            current_user.monthly_chat_image_count = (current_user.monthly_chat_image_count or 0) + 1

    db.add(current_user)
    db.commit()
    request_lease.completed = True

    return ChatResponse(
        response=ai_result.text,
        usage_notice=usage_notice,
        memory_summary=ai_result.memory_update,
    )
