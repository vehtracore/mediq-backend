"""Gemini-specific transport, payloads, completion and failure mapping."""

from __future__ import annotations

import asyncio
import io
import logging
import os
import json

import google.generativeai as genai
import httpx
from PIL import Image

from app.services.ai_provider import (
    AIErrorCategory,
    AIGenerationRequest,
    AIGenerationResult,
    AIMedia,
    AIProviderError,
)

logger = logging.getLogger(__name__)


def _completion(reason: object) -> str:
    if reason is None:
        return "missing"
    try:
        numeric = int(reason)
    except (TypeError, ValueError):
        numeric = None
    if numeric == 1:
        return "normal"
    if numeric == 2:
        return "max_tokens"
    name = (getattr(reason, "name", None) or str(reason)).rsplit(".", 1)[-1].upper()
    if name in {"STOP", "FINISH_REASON_STOP"}:
        return "normal"
    if name in {"MAX_TOKENS", "FINISH_REASON_MAX_TOKENS"}:
        return "max_tokens"
    if name in {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "IMAGE_SAFETY"}:
        return "safety"
    return "abnormal"


def _map_error(exc: Exception) -> AIProviderError:
    if isinstance(exc, AIProviderError):
        return exc
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException)):
        return AIProviderError(AIErrorCategory.TIMEOUT, retryable=True)
    # google.api_core exceptions have a stable code; avoid exposing their text.
    from google.api_core import exceptions as google_errors

    if isinstance(exc, google_errors.ResourceExhausted):
        return AIProviderError(AIErrorCategory.QUOTA_EXHAUSTED, retryable=True)
    if isinstance(exc, google_errors.TooManyRequests):
        return AIProviderError(AIErrorCategory.RATE_LIMITED, retryable=True)
    if isinstance(exc, (google_errors.Unauthenticated, google_errors.PermissionDenied)):
        return AIProviderError(AIErrorCategory.AUTH_CONFIGURATION_ERROR)
    if isinstance(exc, (google_errors.DeadlineExceeded, google_errors.ServiceUnavailable)):
        return AIProviderError(AIErrorCategory.TRANSIENT_PROVIDER_FAILURE, retryable=True)
    if isinstance(exc, google_errors.InvalidArgument):
        return AIProviderError(AIErrorCategory.PERMANENT_PROVIDER_FAILURE)
    return AIProviderError(AIErrorCategory.TRANSIENT_PROVIDER_FAILURE, retryable=True)


class GeminiAdapter:
    name = "gemini"

    def __init__(self) -> None:
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.model_names = {
            "standard": os.getenv("GEMINI_STANDARD_MODEL", "gemini-3.1-flash-lite"),
            "heavy": os.getenv("GEMINI_HEAVY_MODEL", "gemini-3.5-flash"),
        }
        self.model_names["summary"] = self.model_names["heavy"]
        self.model_names["lab"] = self.model_names["heavy"]
        self.model_names["router"] = self.model_names["heavy"]
        self.model_names["assessment"] = self.model_names["heavy"]
        self.model_names["assessment_result"] = self.model_names["heavy"]
        if self.api_key:
            genai.configure(api_key=self.api_key)
        self.models = {
            purpose: genai.GenerativeModel(name)
            for purpose, name in self.model_names.items()
        }

    def validate_capabilities(self) -> None:
        if not all(self.model_names.values()) or not all(self.models.values()):
            raise AIProviderError(AIErrorCategory.AUTH_CONFIGURATION_ERROR)

    def _model(self, purpose: str):
        if not self.api_key or purpose not in self.models:
            raise AIProviderError(AIErrorCategory.AUTH_CONFIGURATION_ERROR)
        return self.models[purpose]

    @staticmethod
    def _history(request: AIGenerationRequest) -> list[dict]:
        return [
            {"role": "user" if turn.role == "patient" else "model", "parts": [turn.text]}
            for turn in request.history
        ]

    @staticmethod
    async def _parts(request: AIGenerationRequest) -> list:
        parts = []
        for part in request.parts:
            if isinstance(part, str):
                parts.append(part)
            elif part.kind == "image_url":
                try:
                    async with httpx.AsyncClient() as client:
                        response = await client.get(str(part.value), timeout=15.0)
                        response.raise_for_status()
                    image = Image.open(io.BytesIO(response.content))
                    image.load()
                    parts.append(image)
                except Exception as exc:
                    raise AIProviderError(AIErrorCategory.MEDIA_PROCESSING_FAILED, retryable=True) from exc
            elif part.kind == "image_bytes":
                try:
                    image = Image.open(io.BytesIO(part.value))
                    image.load()
                    parts.append(image)
                except Exception as exc:
                    raise AIProviderError(AIErrorCategory.MEDIA_PROCESSING_FAILED) from exc
            elif part.kind == "pdf_bytes":
                parts.append({"mime_type": "application/pdf", "data": part.value})
            else:
                raise AIProviderError(AIErrorCategory.UNSUPPORTED_MEDIA)
        return parts

    async def count_input(self, request: AIGenerationRequest) -> int:
        model = self._model(request.purpose)
        try:
            parts = await self._parts(request)
            count = await asyncio.wait_for(
                model.count_tokens_async([
                    *self._history(request), {"role": "user", "parts": parts}
                ]), timeout=75,
            )
            return int(count.total_tokens)
        except Exception as exc:
            raise _map_error(exc) from exc

    async def generate(self, request: AIGenerationRequest) -> AIGenerationResult:
        model = self._model(request.purpose)
        try:
            parts = await self._parts(request)
            input_tokens = await asyncio.wait_for(
                model.count_tokens_async([
                    *self._history(request), {"role": "user", "parts": parts}
                ]), timeout=75,
            )
            count = int(input_tokens.total_tokens)
            if request.input_token_limit is not None and count > request.input_token_limit:
                raise AIProviderError(AIErrorCategory.INPUT_TOO_LARGE)
            config = {"max_output_tokens": request.output_tokens}
            if request.structured:
                config["response_mime_type"] = "application/json"
            if request.purpose == "lab":
                response = await asyncio.wait_for(
                    model.generate_content_async(parts, generation_config=config), timeout=120,
                )
            else:
                session = model.start_chat(history=self._history(request))
                response = await asyncio.wait_for(
                    session.send_message_async(parts, generation_config=config), timeout=120,
                )
            candidates = getattr(response, "candidates", None)
            completion = _completion(getattr(candidates[0], "finish_reason", None)) if candidates else (
                "safety" if getattr(response, "prompt_feedback", None) else "missing"
            )
            try:
                text = (getattr(response, "text", None) or "").strip()
            except (ValueError, AttributeError):
                text = ""
            usage = getattr(response, "usage_metadata", None)
            output_tokens = getattr(usage, "candidates_token_count", None)
            logger.info(
                "AI provider=%s model=%s purpose=%s completion=%s input_tokens=%s output_tokens=%s",
                self.name, self.model_names[request.purpose], request.purpose,
                completion, count, output_tokens,
            )
            structured_data = None
            if request.structured and completion == "normal":
                try:
                    structured_data = json.loads(text)
                    if not isinstance(structured_data, dict):
                        raise ValueError("Structured output must be an object")
                except (ValueError, TypeError) as exc:
                    raise AIProviderError(AIErrorCategory.INVALID_STRUCTURED_OUTPUT) from exc
            return AIGenerationResult(text, completion, count, output_tokens, structured_data)
        except Exception as exc:
            error = _map_error(exc)
            logger.warning("AI provider=%s purpose=%s error=%s", self.name, request.purpose, error.category.value)
            raise error from exc
