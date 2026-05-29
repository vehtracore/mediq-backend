import os
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.api import deps
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# OpenAI async client
# Initialised once at module load; the API key is read from the environment
# (set OPENAI_API_KEY in your .env / Render environment variables).
# ---------------------------------------------------------------------------
_OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
client = AsyncOpenAI(api_key=_OPENAI_API_KEY)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class VoiceRequest(BaseModel):
    """Request body for the TTS endpoint."""
    text: str


# ---------------------------------------------------------------------------
# POST /voice/speak
# ---------------------------------------------------------------------------

@router.post(
    "/speak",
    summary="Convert text to speech using OpenAI TTS",
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
    current_user: User = Depends(deps.get_current_user),
) -> Response:
    """
    Accepts a text string and returns an MP3 audio stream synthesised
    by OpenAI's ``tts-1`` model using the empathetic ``alloy`` voice.

    The endpoint is stateless — nothing is persisted to the database.

    Security: requires a valid Bearer token (authenticated patients only).
    """
    if not _OPENAI_API_KEY:
        logger.error(
            "[Voice] OPENAI_API_KEY is not set. "
            "Add it to your .env / Render environment variables."
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Voice service is not configured.",
        )

    if not payload.text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="text must not be empty.",
        )

    try:
        response = await client.audio.speech.create(
            model="tts-1",
            voice="alloy",
            input=payload.text,
            response_format="mp3",
        )

        audio_bytes = response.read()

        logger.info(
            "[Voice] TTS synthesised — user_id=%s bytes=%d",
            current_user.id,
            len(audio_bytes),
        )

        return Response(content=audio_bytes, media_type="audio/mpeg")

    except Exception as exc:
        logger.error("[Voice] OpenAI TTS error — user_id=%s error=%s", current_user.id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"TTS service error: {exc}",
        )
