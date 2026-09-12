
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Optional, Any, Literal
from uuid import UUID
from datetime import datetime

from app.services.ai_summary_service import (
    MAX_CONVERSATION_CHARS,
    MAX_TURN_CHARS,
    MAX_TURNS,
)


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class AIConversationTurn(BaseModel):
    """One untrusted, ephemeral turn accepted by the summary-save endpoint."""

    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=MAX_TURN_CHARS)

    model_config = ConfigDict(extra="forbid")

    @field_validator("text")
    @classmethod
    def normalise_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Turn text cannot be empty.")
        return value


class AISummarySaveRequest(BaseModel):
    """Typed, non-authoritative input for backend-owned AI summary saving."""

    turns: list[AIConversationTurn] = Field(min_length=1, max_length=MAX_TURNS)
    source_summary_id: Optional[UUID] = None
    source_updated_at: Optional[datetime] = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_bounds_and_source(self):
        if sum(len(turn.text) for turn in self.turns) > MAX_CONVERSATION_CHARS:
            raise ValueError("Conversation exceeds the supported size.")
        if (self.source_summary_id is None) != (self.source_updated_at is None):
            raise ValueError("Continuation ID and source version must be supplied together.")
        return self


class VaultExportRequest(BaseModel):
    """Payload for the PDF export endpoint — a list of vault record UUIDs."""
    record_ids: list[UUID]


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class VaultHistoryResponse(BaseModel):
    """
    Unified response shape that represents either an AI chat summary or a
    clinical consultation record, allowing the frontend to render a single,
    chronologically sorted Health Vault timeline.

    Discriminator field: `type`
      • "ai_summary"   — created by the AI Health Assistant
      • "consultation" — created after a doctor consultation
    """
    id: UUID
    type: Literal["ai_summary", "consultation"]

    # ISO-8601 timestamp of the event (used for chronological sorting)
    date: datetime

    # Present on consultation records; None for AI summaries
    doctor_name: Optional[str] = None

    # Human-readable label: AI topic or appointment reason/notes
    topic_or_reason: str

    # Main textual body (summary_text or clinical_notes)
    details: Optional[str] = None

    # Structured clinical data — only populated for consultation records
    source: Optional[str] = None
    doctor_review_status: Optional[str] = None
    reviewed_by_doctor_id: Optional[int] = None
    reviewed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    prescriptions: Optional[Any] = None
    referrals: Optional[Any] = None

    model_config = ConfigDict(from_attributes=True)
