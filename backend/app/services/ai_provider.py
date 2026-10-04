"""Provider-neutral execution contract for MDQ+ reasoning."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from dotenv import load_dotenv

load_dotenv()


class AIErrorCategory(StrEnum):
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXHAUSTED = "quota_exhausted"
    AUTH_CONFIGURATION_ERROR = "auth_configuration_error"
    SAFETY_BLOCKED = "safety_blocked"
    INPUT_TOO_LARGE = "input_too_large"
    UNSUPPORTED_MEDIA = "unsupported_media"
    MEDIA_PROCESSING_FAILED = "media_processing_failed"
    INCOMPLETE_GENERATION = "incomplete_generation"
    INVALID_STRUCTURED_OUTPUT = "invalid_structured_output"
    TRANSIENT_PROVIDER_FAILURE = "transient_provider_failure"
    PERMANENT_PROVIDER_FAILURE = "permanent_provider_failure"


class AIProviderError(RuntimeError):
    def __init__(self, category: AIErrorCategory, *, retryable: bool = False):
        super().__init__(category.value)
        self.category = category
        self.retryable = retryable


@dataclass(frozen=True)
class AIHistoryTurn:
    role: str  # patient | mdq_plus
    text: str


@dataclass(frozen=True)
class AIMedia:
    kind: str  # image_url | image_bytes | pdf_bytes
    value: str | bytes


@dataclass(frozen=True)
class AIGenerationRequest:
    purpose: str  # standard | heavy | summary | lab
    parts: tuple[str | AIMedia, ...]
    output_tokens: int
    history: tuple[AIHistoryTurn, ...] = ()
    structured: bool = False
    input_token_limit: int | None = None


@dataclass(frozen=True)
class AIGenerationResult:
    text: str
    completion: str  # normal | max_tokens | safety | missing | abnormal
    input_tokens: int | None = None
    output_tokens: int | None = None
    structured_data: dict | None = None


class ClinicalAIProvider(Protocol):
    name: str

    async def generate(self, request: AIGenerationRequest) -> AIGenerationResult: ...

    async def count_input(self, request: AIGenerationRequest) -> int: ...

    def validate_capabilities(self) -> None: ...


_provider: ClinicalAIProvider | None = None


def get_clinical_ai_provider() -> ClinicalAIProvider:
    global _provider
    selected = os.getenv("AI_PROVIDER", "gemini").strip().lower()
    if selected != "gemini":
        raise AIProviderError(AIErrorCategory.AUTH_CONFIGURATION_ERROR)
    if _provider is None or _provider.name != selected:
        from app.services.gemini_adapter import GeminiAdapter

        _provider = GeminiAdapter()
        _provider.validate_capabilities()
    return _provider
