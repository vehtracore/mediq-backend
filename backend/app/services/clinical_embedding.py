"""Embedding capability is separate from clinical reasoning."""

from __future__ import annotations

import asyncio
import math
import os
from dataclasses import dataclass
from typing import Protocol


class EmbeddingUnavailable(RuntimeError):
    pass


class EmbeddingProvider(Protocol):
    key: str

    async def embed(self, texts: list[str], *, task: str) -> list[list[float]]: ...


def validate_vectors(vectors: list[list[float]], count: int) -> int:
    if len(vectors) != count or not vectors:
        raise EmbeddingUnavailable("embedding count mismatch")
    dimension = len(vectors[0])
    if dimension < 1 or dimension > 16000:
        raise EmbeddingUnavailable("unsupported embedding dimension")
    if any(len(vector) != dimension or any(
        not isinstance(value, (float, int)) or not math.isfinite(value)
        for value in vector
    ) for vector in vectors):
        raise EmbeddingUnavailable("invalid embedding values")
    return dimension


@dataclass(frozen=True)
class GeminiEmbeddingAdapter:
    model: str
    output_dimension: int | None

    @property
    def key(self) -> str:
        return f"gemini:{self.model}:{self.output_dimension or 'native'}"

    async def embed(self, texts: list[str], *, task: str) -> list[list[float]]:
        if task not in {"RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"} or not texts:
            raise EmbeddingUnavailable("invalid embedding request")
        import google.generativeai as genai

        if not os.getenv("GEMINI_API_KEY"):
            raise EmbeddingUnavailable("embedding credentials unavailable")
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])
        options = {"output_dimensionality": self.output_dimension} if self.output_dimension else {}
        try:
            response = await asyncio.to_thread(
                genai.embed_content, model=self.model, content=texts,
                task_type=task, **options,
            )
            raw = response["embedding"]
            vectors = [raw] if raw and isinstance(raw[0], (float, int)) else raw
            dimension = validate_vectors(vectors, len(texts))
            if self.output_dimension is not None and dimension != self.output_dimension:
                raise EmbeddingUnavailable("embedding dimension differs from configuration")
            return [[float(value) for value in vector] for vector in vectors]
        except EmbeddingUnavailable:
            raise
        except Exception as exc:
            raise EmbeddingUnavailable("embedding provider unavailable") from exc


def get_embedding_provider() -> EmbeddingProvider:
    provider = os.getenv("CLINICAL_EMBEDDING_PROVIDER", "gemini").strip().lower()
    model = os.getenv("CLINICAL_EMBEDDING_MODEL", "").strip()
    if provider != "gemini" or not model:
        raise EmbeddingUnavailable("embedding provider/model must be configured")
    raw_dimension = os.getenv("CLINICAL_EMBEDDING_DIMENSION", "").strip()
    if raw_dimension:
        try:
            dimension = int(raw_dimension)
        except ValueError as exc:
            raise EmbeddingUnavailable("invalid embedding dimension") from exc
        if not 1 <= dimension <= 16000:
            raise EmbeddingUnavailable("invalid embedding dimension")
    else:
        dimension = None
    return GeminiEmbeddingAdapter(model, dimension)
