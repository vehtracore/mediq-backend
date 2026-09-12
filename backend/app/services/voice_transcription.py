"""Bounded, non-persistent validation and OpenAI transcription for voice input."""

from __future__ import annotations

import io
import logging
import math
import os
import wave
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import HTTPException, UploadFile, status
from mutagen.mp4 import MP4
from openai import AsyncOpenAI


logger = logging.getLogger(__name__)

MAX_STT_AUDIO_BYTES = 2 * 1024 * 1024
MAX_STT_AUDIO_SECONDS = 90.5
MIN_STT_AUDIO_SECONDS = 0.1
OPENAI_STT_MODEL = os.getenv("OPENAI_STT_MODEL", "gpt-transcribe")
_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

_M4A_CONTENT_TYPES = {"audio/mp4", "audio/m4a", "audio/x-m4a"}
_WAV_CONTENT_TYPES = {"audio/wav", "audio/x-wav", "audio/wave"}


@dataclass(frozen=True)
class VoiceInputCapability:
    enabled: bool
    provider: str | None = None
    provider_language: str | None = None
    prompt: str | None = None


VOICE_INPUT_CAPABILITIES = {
    "english": VoiceInputCapability(
        enabled=True,
        provider="openai",
        provider_language="en",
        prompt=(
            "Transcribe the spoken English faithfully. Preserve the speaker's "
            "actual words, numbers, medicine names, dosage and frequency. Do not "
            "summarize, rewrite grammar, infer medical meaning, or expand "
            "abbreviations based on assumptions."
        ),
    ),
    "pidgin": VoiceInputCapability(
        enabled=True,
        provider="openai",
        prompt=(
            "This audio fit contain Nigerian Pidgin, Nigerian English, "
            "code-switching, and English medication or medical terms. Write "
            "exactly wetin the speaker talk and preserve the spoken wording, "
            "negation, numbers, medicine names, dose, and frequency as heard. "
            "No translate am to Standard English, no polish the grammar, and no "
            "infer or correct medical meaning."
        ),
    ),
    "nigerian pidgin": VoiceInputCapability(
        enabled=True,
        provider="openai",
        prompt=(
            "This audio fit contain Nigerian Pidgin, Nigerian English, "
            "code-switching, and English medication or medical terms. Write "
            "exactly wetin the speaker talk and preserve the spoken wording, "
            "negation, numbers, medicine names, dose, and frequency as heard. "
            "No translate am to Standard English, no polish the grammar, and no "
            "infer or correct medical meaning."
        ),
    ),
    "yoruba": VoiceInputCapability(enabled=False),
    "hausa": VoiceInputCapability(enabled=False),
    "igbo": VoiceInputCapability(enabled=False),
}


@dataclass(frozen=True)
class ValidatedVoiceAudio:
    data: bytes
    filename: str
    content_type: str
    duration_seconds: float


def normalise_voice_input_language(language: str | None) -> str:
    return (language or "").strip().lower()


def require_voice_input_capability(language: str | None) -> tuple[str, VoiceInputCapability]:
    normalised = normalise_voice_input_language(language)
    capability = VOICE_INPUT_CAPABILITIES.get(normalised)
    if capability is None or not capability.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Voice input is not available for this language. "
                "You can still type your message."
            ),
        )
    return ("pidgin" if normalised == "nigerian pidgin" else normalised), capability


def _invalid_audio() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="This audio file could not be processed. Use an M4A or WAV recording.",
    )


def _wav_duration(data: bytes) -> float:
    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            if audio.getcomptype() != "NONE":
                raise _invalid_audio()
            frame_rate = audio.getframerate()
            frame_count = audio.getnframes()
            if frame_rate <= 0 or frame_count <= 0:
                raise _invalid_audio()
            return frame_count / frame_rate
    except HTTPException:
        raise
    except Exception:
        raise _invalid_audio()


def _m4a_duration(data: bytes) -> float:
    try:
        parsed = MP4(io.BytesIO(data))
        duration = float(parsed.info.length)
        if parsed.info.channels <= 0 or parsed.info.sample_rate <= 0:
            raise _invalid_audio()
        return duration
    except HTTPException:
        raise
    except Exception:
        raise _invalid_audio()


def validate_voice_audio_bytes(
    data: bytes,
    *,
    filename: str,
    content_type: str,
) -> ValidatedVoiceAudio:
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The voice recording is empty.",
        )
    if len(data) > MAX_STT_AUDIO_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Voice recording exceeds the 2 MB upload limit.",
        )

    safe_name = (filename or "").strip().lower()
    safe_type = (content_type or "").split(";", 1)[0].strip().lower()
    is_wav = data.startswith(b"RIFF") and data[8:12] == b"WAVE"
    is_m4a = len(data) >= 12 and data[4:8] == b"ftyp"

    if is_wav:
        if not safe_name.endswith(".wav") or safe_type not in _WAV_CONTENT_TYPES:
            raise _invalid_audio()
        duration = _wav_duration(data)
        provider_filename = "mdq_voice.wav"
        provider_content_type = "audio/wav"
    elif is_m4a:
        if not safe_name.endswith(".m4a") or safe_type not in _M4A_CONTENT_TYPES:
            raise _invalid_audio()
        duration = _m4a_duration(data)
        provider_filename = "mdq_voice.m4a"
        provider_content_type = "audio/mp4"
    else:
        raise _invalid_audio()

    if not math.isfinite(duration) or duration < MIN_STT_AUDIO_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The voice recording is empty or too short.",
        )
    if duration > MAX_STT_AUDIO_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Voice recordings must be 90 seconds or shorter.",
        )

    return ValidatedVoiceAudio(
        data=data,
        filename=provider_filename,
        content_type=provider_content_type,
        duration_seconds=duration,
    )


async def read_validated_voice_upload(file: UploadFile) -> ValidatedVoiceAudio:
    data = await file.read(MAX_STT_AUDIO_BYTES + 1)
    return validate_voice_audio_bytes(
        data,
        filename=file.filename or "",
        content_type=file.content_type or "",
    )


def _stt_client() -> AsyncOpenAI:
    if not _OPENAI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice transcription is not configured.",
        )
    # Provider retries are disabled: retrying a paid transcription requires an
    # explicit user action in Flutter.
    return AsyncOpenAI(
        api_key=_OPENAI_API_KEY,
        max_retries=0,
        timeout=75.0,
    )


async def transcribe_voice_audio(
    audio: ValidatedVoiceAudio,
    capability: VoiceInputCapability,
    *,
    before_submit: Callable[[], object] | None = None,
) -> str:
    openai_client = _stt_client()
    try:
        request = {
            "file": (audio.filename, audio.data, audio.content_type),
            "model": OPENAI_STT_MODEL,
            "prompt": capability.prompt,
            "response_format": "json",
        }
        if capability.provider_language is not None:
            request["language"] = capability.provider_language
        if before_submit is not None:
            before_submit()
        response = await openai_client.audio.transcriptions.create(**request)
    finally:
        await openai_client.close()
    transcript = response.text.strip()
    if not transcript:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No speech could be transcribed from this recording.",
        )
    return transcript
