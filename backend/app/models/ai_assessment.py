"""Temporary, patient-owned assessment state. Not Health Vault data."""

from sqlalchemy import (Boolean, Column, DateTime, ForeignKey, Integer, JSON,
                        String, Text, UniqueConstraint, Index)
from sqlalchemy.orm import relationship

from app.core.database import Base


class AIAssessment(Base):
    __tablename__ = "ai_assessments"
    __table_args__ = (
        Index("ix_ai_assessments_patient_activity", "patient_id", "last_activity_at"),
    )

    id = Column(String(36), primary_key=True)
    patient_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(16), nullable=False)
    presenting_concern = Column(Text, nullable=False)
    language = Column(String(64), nullable=False)
    schema_version = Column(Integer, nullable=False, default=1)
    state_version = Column(Integer, nullable=False, default=1)
    readiness = Column(Boolean, nullable=False, default=False)
    readiness_reasons = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    last_activity_at = Column(DateTime(timezone=True), nullable=False)
    abandoned_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    originating_request_id = Column(String(128), nullable=False)
    latest_operation_id = Column(String(128))
    source_summary_id = Column(String(36))
    result_json = Column(JSON)
    last_response_json = Column(JSON)
    usage_committed = Column(Boolean, nullable=False, default=False)

    facts = relationship("AIAssessmentFact", cascade="all, delete-orphan", order_by="AIAssessmentFact.created_at")
    questions = relationship("AIAssessmentQuestion", cascade="all, delete-orphan", order_by="AIAssessmentQuestion.asked_at")


class AIAssessmentFact(Base):
    __tablename__ = "ai_assessment_facts"

    id = Column(String(36), primary_key=True)
    assessment_id = Column(String(36), ForeignKey("ai_assessments.id", ondelete="CASCADE"), nullable=False, index=True)
    concept = Column(String(64), nullable=False)
    value = Column(Text, nullable=False)
    status = Column(String(16), nullable=False)
    provenance = Column(String(24), nullable=False)
    source_turn_id = Column(String(128))
    attachment_id = Column(String(128))
    confidence = Column(Integer)
    created_at = Column(DateTime(timezone=True), nullable=False)
    supersedes_fact_id = Column(String(36), ForeignKey("ai_assessment_facts.id"))


class AIAssessmentQuestion(Base):
    __tablename__ = "ai_assessment_questions"
    __table_args__ = (
        UniqueConstraint("assessment_id", "semantic_key", name="uq_ai_assessment_question_key"),
    )

    id = Column(String(36), primary_key=True)
    assessment_id = Column(String(36), ForeignKey("ai_assessments.id", ondelete="CASCADE"), nullable=False, index=True)
    concept = Column(String(64), nullable=False)
    semantic_key = Column(String(100), nullable=False)
    text = Column(Text, nullable=False)
    asked_at = Column(DateTime(timezone=True), nullable=False)
    answered_at = Column(DateTime(timezone=True))
    answer_turn_id = Column(String(128))
    answer_status = Column(String(16))
    answer_text = Column(Text)
