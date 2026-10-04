import logging
import os
import uuid
import json
import hashlib
import asyncio
from urllib.parse import parse_qs, urlparse

import cloudinary
import cloudinary.api
import cloudinary.uploader
from fastapi import (
    APIRouter,
    HTTPException,
    status,
    Depends,
    Request,
    File,
    Form,
    Header,
    UploadFile,
)
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel
from typing import Literal, Optional
from uuid import UUID

from app.services import ai_service
from app.services.ai_interaction import InteractionResponse
from app.services.ai_assessment import (
    assessment_snapshot, aware, cancel_assessment, owned_session, resumable_assessment,
)
from app.services.ai_orchestrator import InteractionInput, run_interaction
from app.services.ai_provider import AIErrorCategory, AIProviderError
from app.core.database import get_db
from app.core.api_errors import ApiError
from app.models.user import User
from app.models.vault import AIChatSummary
from app.models.ai_chat_receipt import AIChatRequestReceipt
from app.models.lab_result import LabResult
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
)
from app.services.ai_request_guard import ai_request_digest
from fastapi.responses import JSONResponse
from app.services.ai_chat_operation import (
    acquire_chat_operation, chat_operation_status, finish_chat_operation,
    require_chat_operation_owner, start_chat_operation,
)
from app.services.ai_pdf import read_validated_ai_pdf
from app.services.subscription_entitlement import has_active_paid_entitlement
from app.services.media_service import (
    SensitiveMediaAsset,
    delete_sensitive_media,
    generate_sensitive_access,
    read_validated_upload,
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
    interaction_id: Optional[UUID] = None
    expected_state_version: Optional[int] = None
    lab_result_id: Optional[int] = None
    image_url: Optional[str] = None
    image_public_id: Optional[str] = None
    image_format: Optional[Literal["jpg", "jpeg", "png", "webp"]] = None
    history: Optional[list] = None
    language: Optional[str] = "English"
    conversation_memory: Optional[str] = None
    memory_source: Optional[str] = None
    update_memory: bool = False
    source_summary_id: Optional[UUID] = None
    source_summary_updated_at: Optional[datetime] = None


class TemporaryImageResponse(BaseModel):
    url: str
    public_id: str
    format: Literal["jpg", "jpeg", "png", "webp"]
    expires_at: datetime


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

_TEMP_IMAGE_TTL = timedelta(hours=2)


class CancelAssessmentRequest(BaseModel):
    expected_state_version: int


def _chat_fingerprint(payload: ChatRequest, document_bytes: bytes | None = None) -> str:
    content = payload.model_dump(mode="json")
    if document_bytes is not None:
        content["document_sha256"] = hashlib.sha256(document_bytes).hexdigest()
    serialized = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


async def _run_chat_operation(
    request: Request, chat_request: ChatRequest, db: Session,
    current_user: User, request_id: str, document_bytes: bytes | None = None,
):
    fingerprint = _chat_fingerprint(chat_request, document_bytes)
    receipt = _get_chat_receipt(db, current_user.id, request_id)
    if receipt is not None:
        if receipt.request_fingerprint != fingerprint:
            raise ApiError(409, "request_conflict", "This request ID was used for different content.")
        return InteractionResponse(**receipt.response_json)
    operation = acquire_chat_operation(db, current_user.id, request_id, fingerprint)
    if operation.disposition == "replay":
        # A committed receipt is the only source of clinical response content.
        receipt = _get_chat_receipt(db, current_user.id, request_id)
        if receipt is not None:
            return InteractionResponse(**receipt.response_json)
        raise ApiError(503, "operation_unavailable", "The request status could not be confirmed. Please try again.")
    if operation.disposition == "active":
        return JSONResponse(status_code=202, content={"status": "processing", "request_id": request_id})
    if not start_chat_operation(db, operation):
        receipt = _get_chat_receipt(db, current_user.id, request_id)
        if receipt is not None:
            return InteractionResponse(**receipt.response_json)
        return JSONResponse(status_code=202, content={"status": "processing", "request_id": request_id})
    receipt = _get_chat_receipt(db, current_user.id, request_id)
    if receipt is not None:
        finish_chat_operation(db, operation, succeeded=False)
        return InteractionResponse(**receipt.response_json)
    lease = AIRequestLease(current_user.id, operation.owner, None)
    try:
        result = await asyncio.wait_for(
            _analyze_chat_request(
                request, chat_request, db, current_user, lease,
                document_bytes=document_bytes, operation=operation,
            ),
            timeout=270,
        )
    except asyncio.TimeoutError as exc:
        try:
            finish_chat_operation(db, operation, succeeded=False)
        except Exception:
            logger.exception("[AI CHAT] operation release failed request_id=%s", request_id)
        raise ApiError(504, "ai_operation_timeout", "This request took too long. Please try again.") from exc
    except BaseException as exc:
        try:
            finish_chat_operation(db, operation, succeeded=False)
        except Exception:
            logger.exception("[AI CHAT] operation release failed request_id=%s", request_id)
        raise
    try:
        finish_chat_operation(db, operation, succeeded=True)
    except Exception:
        logger.exception("[AI CHAT] result cache unavailable request_id=%s", request_id)
    return result


@router.get("/request-status/{request_id}")
def get_chat_request_status(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    receipt = _get_chat_receipt(db, current_user.id, request_id)
    if receipt is not None:
        return {"status": "succeeded", "response": receipt.response_json}
    return chat_operation_status(db, current_user.id, request_id)


def _get_chat_receipt(db: Session, user_id: int, request_id: str):
    return (
        db.query(AIChatRequestReceipt)
        .filter(
            AIChatRequestReceipt.patient_id == user_id,
            AIChatRequestReceipt.request_digest == ai_request_digest(request_id),
            AIChatRequestReceipt.expires_at > datetime.now(timezone.utc),
        )
        .first()
    )


def _get_owned_lab_context(db: Session, record_id: int, user_id: int) -> dict:
    record = db.query(LabResult).filter(
        LabResult.id == record_id,
        LabResult.user_id == user_id,
    ).first()
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="This lab result is no longer available.")
    if not isinstance(record.raw_data, dict) or record.raw_data.get("status") != "SUCCESS":
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, "lab_context_unavailable",
                       "This lab result could not be interpreted. Please choose another result.")
    return record.raw_data


def _paid_message_thresholds(plan: str) -> tuple[int, int]:
    if plan == "family":
        return _FAMILY_MONTHLY_MSG_SOFT_LIMIT, _FAMILY_MONTHLY_WARNING_AT
    return _PREMIUM_MONTHLY_MSG_SOFT_LIMIT, _PREMIUM_MONTHLY_WARNING_AT


def _get_owned_source_summary(
    db: Session,
    summary_id: UUID,
    user_id: int,
    expected_updated_at: datetime | None = None,
) -> AIChatSummary:
    summary = (
        db.query(AIChatSummary)
        .filter(
            AIChatSummary.id == summary_id,
            AIChatSummary.patient_id == user_id,
        )
        .first()
    )
    if summary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This saved conversation is no longer available.",
        )
    if expected_updated_at is not None:
        stored_updated_at = summary.updated_at
        if stored_updated_at.tzinfo is None:
            stored_updated_at = stored_updated_at.replace(tzinfo=timezone.utc)
        else:
            stored_updated_at = stored_updated_at.astimezone(timezone.utc)
        source_updated_at = expected_updated_at
        if source_updated_at.tzinfo is None:
            source_updated_at = source_updated_at.replace(tzinfo=timezone.utc)
        else:
            source_updated_at = source_updated_at.astimezone(timezone.utc)
        if stored_updated_at != source_updated_at:
            raise ApiError(
                status.HTTP_409_CONFLICT,
                "stale_version",
                (
                    "This saved conversation was updated elsewhere. Your current "
                    "chat is still available; refresh it before continuing."
                ),
            )
    return summary


def _require_owned_temp_image(public_id: str, user_id: int) -> None:
    if not public_id.startswith(f"mediq_ai_temp/{user_id}/"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Temporary image does not belong to this user.",
        )


def _delete_temp_image(public_id: str, user_id: int) -> bool:
    _require_owned_temp_image(public_id, user_id)
    for delivery_type in ("authenticated", "upload"):
        try:
            result = cloudinary.uploader.destroy(
                public_id,
                resource_type="image",
                type=delivery_type,
                invalidate=True,
            )
            if result.get("result") == "ok":
                return True
        except Exception as exc:
            logger.error(
                "[AI TEMP IMAGE] Cleanup failed user_id=%s failure_category=%s",
                user_id,
                type(exc).__name__,
            )
            return False
    return True


def cleanup_stale_temp_images() -> int:
    """Delete abandoned AI chat images older than the temporary retention TTL."""
    cutoff = datetime.now(timezone.utc) - _TEMP_IMAGE_TTL
    deleted_count = 0
    for delivery_type in ("authenticated", "upload"):
        next_cursor = None
        while True:
            options = {
                "resource_type": "image",
                "type": delivery_type,
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
                        type=delivery_type,
                        invalidate=True,
                    )
                    if deletion.get("result") in {"ok", "not found"}:
                        deleted_count += 1
                except Exception as exc:
                    logger.error(
                        "[AI TEMP IMAGE] Stale cleanup failed failure_category=%s",
                        type(exc).__name__,
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

    content = await read_validated_upload(
        file,
        allowed_types={"image/jpeg", "image/png", "image/webp"},
    )

    public_id = f"mediq_ai_temp/{current_user.id}/{uuid.uuid4()}"
    try:
        result = cloudinary.uploader.upload(
            content,
            public_id=public_id,
            resource_type="image",
            type="authenticated",
            overwrite=False,
        )
        asset = SensitiveMediaAsset(
            public_id=result["public_id"],
            resource_type="image",
            format=result["format"],
            delivery_type="authenticated",
        )
        access = generate_sensitive_access(asset, ttl_seconds=15 * 60)
    except Exception as exc:
        if "asset" in locals():
            delete_sensitive_media(asset)
        logger.error(
            "[AI TEMP IMAGE] Upload failed user_id=%s failure_category=%s",
            current_user.id,
            type(exc).__name__,
        )
        if isinstance(exc, HTTPException):
            raise
        raise ApiError(
            status.HTTP_502_BAD_GATEWAY,
            "media_upload_unavailable",
            "MDQ+ could not securely store this image. Please try again.",
        ) from exc

    return TemporaryImageResponse(
        url=access.url,
        public_id=asset.public_id,
        format=asset.format,
        expires_at=access.expires_at,
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

@router.get("/assessment/current")
def get_current_assessment(
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    require_active_ai_consent(current_user)
    session = resumable_assessment(db, current_user.id)
    return {"assessment": assessment_snapshot(session) if session else None}


@router.get("/assessment/{assessment_id}")
def get_assessment(
    assessment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    require_active_ai_consent(current_user)
    session = owned_session(db, current_user.id, str(assessment_id))
    if aware(session.expires_at) <= datetime.now(timezone.utc):
        raise ApiError(404, "assessment_not_found", "This assessment is no longer available.")
    return assessment_snapshot(session)


@router.post("/assessment/{assessment_id}/cancel")
def cancel_current_assessment(
    assessment_id: UUID,
    payload: CancelAssessmentRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
    x_ai_request_id: str = Header(alias="X-AI-Request-ID", min_length=8, max_length=128),
):
    require_active_ai_consent(current_user)
    return cancel_assessment(
        db, patient_id=current_user.id, assessment_id=str(assessment_id),
        expected_version=payload.expected_state_version, request_id=x_ai_request_id,
    )

@router.post("/analyze", response_model=InteractionResponse)
@limiter.limit("30/minute")
async def analyze_symptoms(
    request: Request,
    chat_request: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
    x_ai_request_id: str = Header(alias="X-AI-Request-ID", min_length=8, max_length=128),
):
    return await _run_chat_operation(
        request, chat_request, db, current_user, x_ai_request_id,
    )


async def _analyze_chat_request(
    request: Request,
    chat_request: ChatRequest,
    db: Session,
    current_user: User,
    request_lease: AIRequestLease,
    *,
    document_bytes: bytes | None = None,
    operation=None,
):
    """
    AI Symptom Checker / Chat endpoint.

    Enforces a three-layer, plan-aware quota system before forwarding the
    request to the configured AI provider:

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
        Counters are only incremented after a successful AI response so
        that network/API failures do not penalise the user's allowance.
    """

    require_active_ai_consent(current_user)

    now = datetime.utcnow()
    has_paid_entitlement = has_active_paid_entitlement(current_user)
    plan_category = (
        (current_user.plan or "free").strip().lower()
        if has_paid_entitlement
        else "free"
    )
    has_image = bool(chat_request.image_public_id)
    has_document = document_bytes is not None
    has_heavy_attachment = has_image or has_document
    trusted_image_url = None

    lab_context = None
    if chat_request.lab_result_id is not None:
        lab_context = _get_owned_lab_context(
            db, chat_request.lab_result_id, current_user.id)

    if has_image and has_document:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only one attachment can be analysed at a time.",
        )

    historical_saved_context = None
    if chat_request.source_summary_id is not None:
        if not has_paid_entitlement:
            logger.info(
                "[AI CHAT] plan=%s quota_outcome=not_evaluated "
                "entitlement_outcome=continuation_denied",
                plan_category,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Continue with AI is available on Premium and Family plans.",
            )
        if chat_request.source_summary_updated_at is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The saved conversation version is required.",
            )
        source_summary = _get_owned_source_summary(
            db,
            chat_request.source_summary_id,
            current_user.id,
            chat_request.source_summary_updated_at,
        )
        historical_saved_context = source_summary.summary_text

    if chat_request.image_url and not has_image:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Temporary image identifier is required.",
        )

    if has_image:
        _require_owned_temp_image(chat_request.image_public_id, current_user.id)
        image_format = chat_request.image_format
        if not image_format and chat_request.image_url:
            candidate = parse_qs(urlparse(chat_request.image_url).query).get(
                "format",
                [None],
            )[0]
            if candidate in {"jpg", "jpeg", "png", "webp"}:
                image_format = candidate
        if not image_format:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Temporary image format is required.",
            )
        trusted_image_url = generate_sensitive_access(
            SensitiveMediaAsset(
                public_id=chat_request.image_public_id,
                resource_type="image",
                format=image_format,
                delivery_type="authenticated",
            ),
            ttl_seconds=15 * 60,
        ).url

    # Guard: at least one of text or attachment must be present.
    if (not chat_request.message.strip() and not has_heavy_attachment
            and lab_context is None and chat_request.interaction_id is None):
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

    if has_paid_entitlement:
        monthly_soft_limit, monthly_warning_at = _paid_message_thresholds(
            plan_category
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
            has_heavy_attachment
            and monthly_heavy_ai_usage(current_user)
            >= PAID_MONTHLY_HEAVY_AI_LIMIT
        ):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    "You've used this month's 10 AI attachment and lab "
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

        # Check attachment sub-bucket (images and PDFs share the existing cap).
        if has_heavy_attachment and (current_user.monthly_chat_image_count or 0) >= _FREE_MONTHLY_IMAGE_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"You've used your {_FREE_MONTHLY_IMAGE_LIMIT} attachment analyses "
                    "allowed per month on the Free plan. You can still send text "
                    "messages, or upgrade to Premium for more."
                ),
            )

    # =========================================================================
    # LAYER 3 — Call the provider and commit counters on success
    # =========================================================================

    user_age = "Unknown"
    if current_user.dob:
        user_age = (now.date() - current_user.dob).days // 365

    user_context = {
        "age": f"{user_age} years old",
        "conditions": current_user.chronic_conditions or "None",
    }

    target_language = chat_request.language or "English"

    history_limit = ai_service.MAX_HISTORY_MESSAGES if has_paid_entitlement else 4
    entitled_history = ai_service.sanitise_recent_history(
        chat_request.history,
        max_messages=history_limit,
    )
    entitled_conversation_memory = (
        chat_request.conversation_memory if has_paid_entitlement else None
    )
    entitled_memory_source = (
        chat_request.memory_source if has_paid_entitlement else None
    )
    entitled_update_memory = (
        chat_request.update_memory if has_paid_entitlement else False
    )

    logger.info(
        "[AI CHAT] plan=%s quota_outcome=allowed",
        plan_category,
    )

    try:
        try:
            interaction = await run_interaction(InteractionInput(
                request_id=operation.request_id if operation is not None else str(uuid.uuid4()),
                interaction_id=str(chat_request.interaction_id) if chat_request.interaction_id else None,
                message=chat_request.message,
                language=target_language,
                history=entitled_history,
                image_url=trusted_image_url,
                user_context=user_context,
                conversation_memory=entitled_conversation_memory,
                memory_source=entitled_memory_source,
                update_memory=entitled_update_memory,
                historical_saved_context=historical_saved_context,
                document_bytes=document_bytes,
                lab_context=lab_context,
                plan_category=plan_category,
                db=db,
                patient_id=current_user.id,
                expected_state_version=chat_request.expected_state_version,
                attachment_id=(chat_request.image_public_id or
                               f"lab:{chat_request.lab_result_id}" if chat_request.lab_result_id else
                               "pdf:current-request" if document_bytes is not None else None),
                source_summary_id=str(chat_request.source_summary_id) if chat_request.source_summary_id else None,
            ))
        except ai_service.AIInputLimitError:
            logger.info(
                "[AI CHAT] plan=%s quota_outcome=not_consumed finish=input_limit",
                plan_category,
            )
            raise ApiError(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                "file_too_large",
                "This attachment is too large to analyze.",
            )
        except ai_service.AIResponseCompletionError as exc:
            logger.info(
                "[AI CHAT] plan=%s quota_outcome=not_consumed finish=%s",
                plan_category,
                exc.finish_category,
            )
            raise ApiError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "analysis_unavailable",
                "We couldn't analyze that right now. Please try again.",
            )
        except AIProviderError as exc:
            logger.info(
                "[AI CHAT] plan=%s quota_outcome=not_consumed error_category=%s",
                plan_category, exc.category.value,
            )
            if exc.category == AIErrorCategory.MEDIA_PROCESSING_FAILED:
                raise ApiError(
                    status.HTTP_422_UNPROCESSABLE_ENTITY, "media_processing_failed",
                    "This image could not be processed. Please try another image.",
                ) from exc
            if exc.category == AIErrorCategory.INPUT_TOO_LARGE:
                raise ApiError(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file_too_large",
                    "This attachment is too large to analyze.",
                ) from exc
            raise ApiError(
                status.HTTP_503_SERVICE_UNAVAILABLE, "analysis_unavailable",
                "We couldn't analyze that right now. Please try again.",
            ) from exc
        except ApiError:
            raise
        except Exception:
            logger.info(
                "[AI CHAT] plan=%s quota_outcome=not_consumed finish=abnormal",
                plan_category,
            )
            logger.exception(
                "[AI CHAT] Provider processing failed for user_id=%s",
                current_user.id,
            )
            raise ApiError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "analysis_unavailable",
                "We couldn't analyze that right now. Please try again.",
            )
    finally:
        if chat_request.image_public_id:
            _delete_temp_image(
                chat_request.image_public_id,
                current_user.id,
            )

    # ── Increment all relevant counters (only reached on AI success) ─────
    is_assessment = interaction.assessment_id is not None
    charge_usage = not is_assessment or interaction.result_kind.value in {"ASSESSMENT_RESULT", "URGENT"}
    if charge_usage:
        current_user.burst_chat_count = (current_user.burst_chat_count or 0) + 1

    usage_notice = None
    if not charge_usage:
        pass
    elif has_paid_entitlement:
        monthly_soft_limit, monthly_warning_at = _paid_message_thresholds(
            plan_category
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

        if has_heavy_attachment and not is_assessment:
            current_user.monthly_chat_image_count = (
                current_user.monthly_chat_image_count or 0
            ) + 1
    else:
        current_user.monthly_chat_count = (current_user.monthly_chat_count or 0) + 1
        if has_heavy_attachment and not is_assessment:
            current_user.monthly_chat_image_count = (current_user.monthly_chat_image_count or 0) + 1

    db.add(current_user)
    result = interaction.model_copy(update={"usage_notice": usage_notice})
    if operation is not None:
        require_chat_operation_owner(db, operation)
        committed_at = datetime.now(timezone.utc)
        db.add(AIChatRequestReceipt(
            patient_id=current_user.id,
            request_digest=ai_request_digest(operation.request_id),
            request_fingerprint=operation.fingerprint,
            response_json=result.model_dump(),
            created_at=committed_at,
            expires_at=committed_at + (timedelta(hours=72) if is_assessment else timedelta(minutes=10)),
        ))
    db.commit()
    request_lease.completed = True
    logger.info(
        "[AI CHAT] plan=%s quota_outcome=%s response_chars=%s",
        plan_category,
        "consumed" if charge_usage else "deferred",
        len(str(result.result.model_dump())),
    )

    return result


def _parse_document_history(raw_history: str) -> list:
    try:
        history = json.loads(raw_history)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid conversation context.",
        ) from None
    if not isinstance(history, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid conversation context.",
        )
    return history


@router.post("/analyze-document", response_model=InteractionResponse)
@limiter.limit("10/hour")
async def analyze_document(
    request: Request,
    file: UploadFile = File(...),
    message: str = Form(""),
    history: str = Form("[]"),
    language: str = Form("English"),
    interaction_id: Optional[UUID] = Form(None),
    expected_state_version: Optional[int] = Form(None),
    lab_result_id: Optional[int] = Form(None),
    conversation_memory: Optional[str] = Form(None),
    memory_source: Optional[str] = Form(None),
    update_memory: bool = Form(False),
    source_summary_id: Optional[UUID] = Form(None),
    source_summary_updated_at: Optional[datetime] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
    x_ai_request_id: str = Header(alias="X-AI-Request-ID", min_length=8, max_length=128),
):
    """Validate and analyse one temporary PDF without persisting its bytes."""
    require_active_ai_consent(current_user)
    document_bytes = await read_validated_ai_pdf(file)
    chat_request = ChatRequest(
        message=message.strip() or "Analyse and explain this PDF document.",
        history=_parse_document_history(history),
        language=language,
        interaction_id=interaction_id,
        expected_state_version=expected_state_version,
        lab_result_id=lab_result_id,
        conversation_memory=conversation_memory,
        memory_source=memory_source,
        update_memory=update_memory,
        source_summary_id=source_summary_id,
        source_summary_updated_at=source_summary_updated_at,
    )
    return await _run_chat_operation(
        request, chat_request, db, current_user, x_ai_request_id,
        document_bytes=document_bytes,
    )
