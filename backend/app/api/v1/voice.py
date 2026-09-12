import os
import logging
import time
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import Response
from openai import AsyncOpenAI
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.ai_consent import require_active_ai_consent
from app.core.database import get_db
from app.core.limiter import limiter
from app.models.user import User
from app.services.ai_usage import enforce_ai_text_usage_available
from app.services.stt_request_guard import (
    acquire_stt_request_lease,
    enforce_stt_user_rate_limit,
    release_stt_request_lease,
)
from app.services.stt_usage import (
    STT_CONSUMED,
    STTAllowanceReservation,
    finalize_stt_allowance,
    reserve_stt_allowance,
)
from app.services.voice_transcription import (
    OPENAI_STT_MODEL,
    read_validated_voice_upload,
    require_voice_input_capability,
    transcribe_voice_audio,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# OpenAI async client
# Initialised once at module load; the API key is read from the environment
# (set OPENAI_API_KEY in your .env / Render environment variables).
# ---------------------------------------------------------------------------
_OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
_YARNGPT_API_KEY: str = os.getenv("YARNGPT_API_KEY", "")
_YARNGPT_TTS_URL: str = os.getenv("YARNGPT_TTS_URL", "https://yarngpt.ai/api/v1/tts")

client = AsyncOpenAI(api_key=_OPENAI_API_KEY)

_MAX_TTS_CHARS = 2000
_FREE_MONTHLY_AUDIO_CHAR_LIMIT = 3600
_PAID_MONTHLY_AUDIO_CHAR_LIMIT = 18000
_PAID_ROLLING_AUDIO_CHAR_LIMIT = 3600
_PAID_PLANS = {"premium", "family"}

_YARNGPT_VOICES = {
    "igbo": "Chinenye",
    "hausa": "Zainab",
    "yoruba": "Remi",
    "pidgin": "Osagie",
    "nigerian pidgin": "Osagie",
}


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class VoiceRequest(BaseModel):
    """Request body for the TTS endpoint."""
    text: str
    language: str = "english"


class VoiceTranscriptionResponse(BaseModel):
    transcript: str
    language: str
    status: str = "ready"


def _normalise_language(language: str | None) -> str:
    value = (language or "english").strip().lower()
    return value or "english"


def _to_naive_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _reset_audio_windows(user: User, now: datetime) -> None:
    last_month_reset = _to_naive_utc(user.last_audio_month_reset)
    needs_month_reset = (
        last_month_reset is None
        or last_month_reset.year < now.year
        or (
            last_month_reset.year == now.year
            and last_month_reset.month < now.month
        )
    )
    if needs_month_reset:
        user.monthly_audio_count = 0
        user.last_audio_month_reset = now

    rolling_window_start = _to_naive_utc(user.rolling_audio_window_start)
    if rolling_window_start is None or (now - rolling_window_start) >= timedelta(hours=24):
        user.rolling_audio_count = 0
        user.rolling_audio_window_start = now


def _enforce_audio_quota(user: User, char_count: int) -> None:
    monthly_total = (user.monthly_audio_count or 0) + char_count

    if user.plan not in _PAID_PLANS:
        if monthly_total > _FREE_MONTHLY_AUDIO_CHAR_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    "You've reached your monthly Free audio limit. "
                    "Upgrade to Premium for more voice playback."
                ),
            )
        return

    if monthly_total > _PAID_MONTHLY_AUDIO_CHAR_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Monthly audio character limit reached.",
        )

    rolling_total = (user.rolling_audio_count or 0) + char_count
    if rolling_total > _PAID_ROLLING_AUDIO_CHAR_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rolling 24-hour audio character limit reached.",
        )



def _reserve_audio_quota(
    db: Session,
    user_id: int,
    char_count: int,
    now: datetime,
) -> bool:
    quota_user = (
        db.query(User)
        .filter(User.id == user_id)
        .with_for_update()
        .first()
    )
    if quota_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials.",
        )

    _reset_audio_windows(quota_user, now)
    _enforce_audio_quota(quota_user, char_count)

    quota_user.monthly_audio_count = (quota_user.monthly_audio_count or 0) + char_count
    counted_rolling = quota_user.plan in _PAID_PLANS
    if counted_rolling:
        quota_user.rolling_audio_count = (quota_user.rolling_audio_count or 0) + char_count

    db.add(quota_user)
    db.commit()
    return counted_rolling


def _refund_audio_quota(
    db: Session,
    user_id: int,
    char_count: int,
    counted_rolling: bool,
) -> None:
    try:
        quota_user = (
            db.query(User)
            .filter(User.id == user_id)
            .with_for_update()
            .first()
        )
        if quota_user is None:
            return

        quota_user.monthly_audio_count = max(
            (quota_user.monthly_audio_count or 0) - char_count,
            0,
        )
        if counted_rolling:
            quota_user.rolling_audio_count = max(
                (quota_user.rolling_audio_count or 0) - char_count,
                0,
            )
        db.add(quota_user)
        db.commit()
    except Exception as refund_exc:
        db.rollback()
        logger.warning(
            "[Voice] Failed to refund audio quota reservation for user_id=%s: %s",
            user_id,
            refund_exc,
        )


async def _synthesise_openai(text: str) -> bytes:
    if not _OPENAI_API_KEY:
        logger.error(
            "[Voice] OPENAI_API_KEY is not set. "
            "Add it to your .env / Render environment variables."
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Voice service is not configured.",
        )

    response = await client.audio.speech.create(
        model="tts-1",
        voice="alloy",
        input=text,
        response_format="mp3",
    )
    return response.read()


async def _synthesise_yarngpt(text: str, voice: str) -> bytes:
    if not _YARNGPT_API_KEY:
        logger.error(
            "[Voice] YARNGPT_API_KEY is not set. "
            "Add it to your .env / Render environment variables."
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Voice service is not configured.",
        )

    async with httpx.AsyncClient(timeout=60.0) as http_client:
        response = await http_client.post(
            _YARNGPT_TTS_URL,
            headers={"Authorization": f"Bearer {_YARNGPT_API_KEY}"},
            json={
                "text": text,
                "voice": voice,
                "response_format": "mp3",
            },
        )

    if response.status_code != 200:
        logger.error(
            "[Voice] YarnGPT TTS error — status=%s body=%s",
            response.status_code,
            response.text[:500],
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="TTS service error.",
        )

    return response.content


def _release_failed_stt_reservation(
    db: Session,
    reservation: STTAllowanceReservation,
) -> None:
    """Best-effort immediate refund; stale recovery covers process interruption."""
    try:
        finalize_stt_allowance(
            db,
            reservation,
            usable_transcript=False,
            now=datetime.now(timezone.utc).replace(tzinfo=None),
        )
    except Exception as exc:
        logger.error(
            "[STT] allowance refund deferred user_id=%s failure_category=%s",
            reservation.user_id,
            type(exc).__name__,
        )


async def _transcribe_uploaded_voice(
    *,
    file: UploadFile,
    language: str,
    request_identifier: str | None,
    db: Session,
    current_user: User,
) -> VoiceTranscriptionResponse:
    normalised_language, capability = require_voice_input_capability(language)
    require_active_ai_consent(current_user)
    user_id = current_user.id

    # This applies the existing AI availability rules without incrementing the
    # normal AI message counters. The eventual reviewed Send remains the one
    # billable chat usage event inside the existing chat endpoint.
    eligibility_now = datetime.now(timezone.utc).replace(tzinfo=None)
    enforce_ai_text_usage_available(current_user, eligibility_now, db)
    audio = await read_validated_voice_upload(file)

    if request_identifier is None or not (8 <= len(request_identifier) <= 128):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid transcription request identifier.",
        )

    lease = acquire_stt_request_lease(user_id, request_identifier)
    if lease.request_digest is None:
        release_stt_request_lease(lease)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid transcription request identifier.",
        )
    allowance_reservation: STTAllowanceReservation | None = None
    started_at = time.monotonic()
    try:
        enforce_stt_user_rate_limit(user_id)

        def _acquire_monthly_allowance() -> None:
            nonlocal allowance_reservation
            allowance_reservation = reserve_stt_allowance(
                db,
                user_id=user_id,
                request_digest=lease.request_digest,
                now=eligibility_now,
            )

        transcript = await transcribe_voice_audio(
            audio,
            capability,
            before_submit=_acquire_monthly_allowance,
        )
        if allowance_reservation is None:
            raise RuntimeError("STT allowance boundary was not reached")
        finalization = finalize_stt_allowance(
            db,
            allowance_reservation,
            usable_transcript=True,
            now=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        if finalization.status != STT_CONSUMED:
            raise RuntimeError("STT allowance reservation was not consumed")
        allowance = allowance_reservation
        allowance_reservation = None
        lease.completed = True
        logger.info(
            "[STT] completed user_id=%s language=%s provider=openai model=%s "
            "duration_seconds=%.2f bytes=%d latency_ms=%d transcript_chars=%d "
            "allowance_used=%d allowance_limit=%d",
            user_id,
            normalised_language,
            OPENAI_STT_MODEL,
            audio.duration_seconds,
            len(audio.data),
            int((time.monotonic() - started_at) * 1000),
            len(transcript),
            allowance.used,
            allowance.limit,
        )
        return VoiceTranscriptionResponse(
            transcript=transcript,
            language=normalised_language,
        )
    except HTTPException:
        if allowance_reservation is not None:
            _release_failed_stt_reservation(db, allowance_reservation)
        raise
    except Exception as exc:
        if allowance_reservation is not None:
            _release_failed_stt_reservation(db, allowance_reservation)
        logger.error(
            "[STT] provider failure user_id=%s language=%s model=%s "
            "duration_seconds=%.2f bytes=%d failure_category=%s",
            user_id,
            normalised_language,
            OPENAI_STT_MODEL,
            audio.duration_seconds,
            len(audio.data),
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Voice transcription is temporarily unavailable.",
        )
    finally:
        release_stt_request_lease(lease)


@router.post(
    "/transcribe",
    response_model=VoiceTranscriptionResponse,
    summary="Transcribe a temporary English or Nigerian Pidgin recording",
)
@limiter.limit("10/hour")
async def transcribe(
    request: Request,
    file: UploadFile = File(...),
    language: str = Form(...),
    request_identifier: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> VoiceTranscriptionResponse:
    try:
        return await _transcribe_uploaded_voice(
            file=file,
            language=language,
            request_identifier=request_identifier,
            db=db,
            current_user=current_user,
        )
    finally:
        # UploadFile is backed by a bounded spooled temporary resource. It is
        # always closed and is never copied to application or cloud storage.
        await file.close()


# ---------------------------------------------------------------------------
# POST /voice/speak
# ---------------------------------------------------------------------------

@router.post(
    "/speak",
    summary="Convert text to speech using OpenAI or YarnGPT TTS",
    response_class=Response,
    responses={
        200: {
            "content": {"audio/mpeg": {}},
            "description": "Raw MP3 audio stream",
        }
    },
)
@limiter.limit("20/hour")
@limiter.limit("5/minute")
async def speak(
    request: Request,
    payload: VoiceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Response:
    """
    Accepts a text string and returns an MP3 audio stream. English speech is
    synthesised by OpenAI; Nigerian local languages are routed to YarnGPT.

    Security: requires a valid Bearer token (authenticated patients only).
    """
    text = payload.text[:_MAX_TTS_CHARS].strip()
    if not text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="text must not be empty.",
        )

    now = datetime.utcnow()
    char_count = len(text)
    language = _normalise_language(payload.language)
    provider = "openai"
    voice = "alloy"

    if language in _YARNGPT_VOICES:
        provider = "yarngpt"
        voice = _YARNGPT_VOICES[language]
    elif language != "english":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported voice language.",
        )

    counted_rolling = _reserve_audio_quota(
        db,
        current_user.id,
        char_count,
        now,
    )

    try:
        if provider == "yarngpt":
            audio_bytes = await _synthesise_yarngpt(text, voice)
        else:
            audio_bytes = await _synthesise_openai(text)

        logger.info(
            "[Voice] TTS synthesised - user_id=%s provider=%s voice=%s chars=%d bytes=%d",
            current_user.id,
            provider,
            voice,
            char_count,
            len(audio_bytes),
        )

        return Response(content=audio_bytes, media_type="audio/mpeg")

    except HTTPException:
        _refund_audio_quota(db, current_user.id, char_count, counted_rolling)
        raise
    except Exception as exc:
        _refund_audio_quota(db, current_user.id, char_count, counted_rolling)
        logger.error(
            "[Voice] TTS error — user_id=%s provider=%s error=%s",
            current_user.id,
            provider,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="TTS service error.",
        )
