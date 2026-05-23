
from pydantic import BaseModel, ConfigDict
from typing import Optional, Any, Literal
from uuid import UUID
from datetime import datetime


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class AISummaryCreate(BaseModel):
    """Payload sent by the client to persist an AI chat summary."""
    topic: str
    summary_text: str


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
    prescriptions: Optional[Any] = None
    referrals: Optional[Any] = None

    model_config = ConfigDict(from_attributes=True)
