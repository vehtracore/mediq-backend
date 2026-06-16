import os
import logging
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from openai import AsyncOpenAI
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import deps
from app.core.database import get_db
from app.models.user import User

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
_MONTHLY_AUDIO_CHAR_LIMIT = 18000
_ROLLING_AUDIO_CHAR_LIMIT = 3600

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
    if monthly_total > _MONTHLY_AUDIO_CHAR_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Monthly audio character limit reached.",
        )

    rolling_total = (user.rolling_audio_count or 0) + char_count
    if rolling_total > _ROLLING_AUDIO_CHAR_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rolling 24-hour audio character limit reached.",
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
async def speak(
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

    _reset_audio_windows(current_user, now)
    _enforce_audio_quota(current_user, char_count)

    try:
        if provider == "yarngpt":
            audio_bytes = await _synthesise_yarngpt(text, voice)
        else:
            audio_bytes = await _synthesise_openai(text)

        logger.info(
            "[Voice] TTS synthesised — user_id=%s provider=%s voice=%s chars=%d bytes=%d",
            current_user.id,
            provider,
            voice,
            char_count,
            len(audio_bytes),
        )

        current_user.monthly_audio_count = (current_user.monthly_audio_count or 0) + char_count
        current_user.rolling_audio_count = (current_user.rolling_audio_count or 0) + char_count
        db.add(current_user)
        db.commit()

        return Response(content=audio_bytes, media_type="audio/mpeg")

    except HTTPException:
        raise
    except Exception as exc:
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
