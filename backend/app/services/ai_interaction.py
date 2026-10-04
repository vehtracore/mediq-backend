"""Patient-visible interaction contract, independent of the reasoning provider."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class InteractionMode(StrEnum):
    CONVERSATION = "CONVERSATION"
    ASSESSMENT = "ASSESSMENT"
    URGENT = "URGENT"


class ResultKind(StrEnum):
    MESSAGE = "MESSAGE"
    ASSESSMENT_QUESTION = "ASSESSMENT_QUESTION"
    ASSESSMENT_RESULT = "ASSESSMENT_RESULT"
    URGENT = "URGENT"


class MessageResult(BaseModel):
    kind: Literal["MESSAGE"] = "MESSAGE"
    text: str
    evidence_ids: list[str] = Field(default_factory=list)


class EvidenceCitation(BaseModel):
    evidence_id: str
    chunk_id: str
    source_id: str
    document_version_id: str
    title: str
    issuing_organization: str
    jurisdiction: str
    edition: str
    publication_date: str | None = None
    effective_date: str | None = None
    section: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    anchor: str | None = None
    canonical_url: str | None = None

    @field_validator("canonical_url")
    @classmethod
    def canonical_https(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or
                parsed.password or parsed.fragment or any(ch.isspace() for ch in value)):
            raise ValueError("source URL must be canonical HTTPS")
        return value


class AssessmentQuestionResult(BaseModel):
    kind: Literal["ASSESSMENT_QUESTION"] = "ASSESSMENT_QUESTION"
    question: str
    can_cancel: bool = True


class AssessmentExplanation(BaseModel):
    text: str = Field(min_length=3, max_length=350)
    fact_ids: list[str] = Field(min_length=1)


class AssessmentResult(BaseModel):
    kind: Literal["ASSESSMENT_RESULT"] = "ASSESSMENT_RESULT"
    what_you_told: list[str] = Field(min_length=1)
    possible_explanations: list[AssessmentExplanation]
    why_considered: list[str]
    important_negatives: list[str] = Field(default_factory=list)
    next_steps: list[str]
    urgent_help_if: list[str]
    limitations: str
    evidence_ids: list[str] = Field(default_factory=list)


class UrgentResult(BaseModel):
    kind: Literal["URGENT"] = "URGENT"
    action: str
    reason: str
    emergency_number: str = "112"


InteractionResult = Annotated[
    MessageResult | AssessmentQuestionResult | AssessmentResult | UrgentResult,
    Field(discriminator="kind"),
]


class InteractionResponse(BaseModel):
    request_id: str
    interaction_id: str
    assessment_id: str | None = None
    state_version: int | None = None
    operation_status: Literal["SUCCEEDED"] = "SUCCEEDED"
    mode: InteractionMode
    result_kind: ResultKind
    result: InteractionResult
    evidence_items: list[EvidenceCitation] = Field(default_factory=list)
    grounding_status: Literal["UNGROUNDED", "PARTIALLY_GROUNDED", "GROUNDED"] = "UNGROUNDED"
    usage_notice: str | None = None
    memory_summary: str | None = None
    safe_error: str | None = None

    @model_validator(mode="after")
    def matching_result(self):
        allowed = {
            InteractionMode.CONVERSATION: {ResultKind.MESSAGE},
            InteractionMode.ASSESSMENT: {ResultKind.ASSESSMENT_QUESTION, ResultKind.ASSESSMENT_RESULT},
            InteractionMode.URGENT: {ResultKind.URGENT},
        }[self.mode]
        if self.result_kind not in allowed or self.result.kind != self.result_kind.value:
            raise ValueError("Interaction mode and result kind do not match")
        references = getattr(self.result, "evidence_ids", [])
        identifiers = [item.evidence_id for item in self.evidence_items]
        if len(identifiers) != len(set(identifiers)) or set(references) != set(identifiers):
            raise ValueError("Evidence references and metadata do not match")
        if bool(references) == (self.grounding_status == "UNGROUNDED"):
            raise ValueError("Grounding status does not match referenced evidence")
        return self
