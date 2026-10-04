"""Temporary assessment lifecycle, provenance and typed result tests."""

import asyncio
import json
from pathlib import Path
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models.user  # noqa: F401
from app.models.ai_assessment import AIAssessment, AIAssessmentFact, AIAssessmentQuestion
from app.services import ai_assessment
from app.services.ai_provider import AIGenerationResult
from app.services.ai_interaction import (
    AssessmentQuestionResult, AssessmentResult, InteractionMode,
    InteractionResponse, ResultKind, UrgentResult,
)
from app.api.v1 import chat
from app.services.ai_request_guard import AIRequestLease
from tests.test_ai_chat_quality import _UsageDb, _user
from tests.ai_provider_fakes import scope_payload


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO users (id) VALUES (7), (8)"))
    for table in (AIAssessment.__table__, AIAssessmentFact.__table__, AIAssessmentQuestion.__table__):
        table.create(bind=engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


class PlanProvider:
    def __init__(self, plans, finals=None):
        self.plans = list(plans)
        self.finals = list(finals or [])
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        if request.purpose == "assessment":
            value = self.plans.pop(0)
        else:
            value = self.finals.pop(0)
            if callable(value):
                value = value(json.loads(request.parts[1]))
        return AIGenerationResult(json.dumps(value), "normal", structured_data=value)


def plan(*, facts=None, needs=None, ready=False):
    return {"facts": facts or [], "needs": needs or [], "ready": ready,
            "readiness_reasons": ["sufficient_information"] if ready else []}


def need(concept, question, safety=0):
    return {"concept": concept, "question": question, "safety_impact": safety,
            "decision_change": "Duration changes whether to arrange persistent-symptom evaluation.",
            "next_step_impact": 2, "differential_impact": 1,
            "uncertainty_reduction": 2, "burden": 1}


def fact(concept, quote, *, status="ASSERTED", provenance="USER_STATED"):
    return {"concept": concept, "value": quote, "evidence_quote": quote,
            "status": status, "provenance": provenance}


def valid_final(state):
    return scope_payload("This cannot confirm a diagnosis without an examination.")


def advance(db, message, *, assessment_id=None, version=None, request_id="request-1"):
    return asyncio.run(ai_assessment.advance_assessment(
        db, patient_id=7, request_id=request_id, assessment_id=assessment_id,
        expected_version=version, message=message, language="English",
    ))


def test_question_then_result_is_durable_and_not_charged_per_question(db, monkeypatch):
    provider = PlanProvider([
        plan(needs=[need("duration", "When did this start?")]),
        plan(facts=[fact("duration", "Three months")], ready=True),
    ], finals=[valid_final])
    monkeypatch.setattr(ai_assessment, "get_clinical_ai_provider", lambda: provider)
    first = advance(db, "My urine looks foamy")
    assert first.result_kind.value == "ASSESSMENT_QUESTION"
    db.commit()
    session = ai_assessment.owned_session(db, 7, first.assessment_id)
    assert session.status == "ACTIVE" and not session.usage_committed
    assert len(session.questions) == 1 and session.questions[0].answered_at is None
    second = advance(db, "Three months", assessment_id=first.assessment_id,
                     version=first.state_version, request_id="request-2")
    db.commit()
    assert second.result_kind.value == "ASSESSMENT_RESULT"
    assert second.state_version == first.state_version + 1
    assert session.status == "COMPLETED" and session.usage_committed
    assert session.questions[0].answer_text == "Three months"
    assert all(item.provenance == "USER_STATED" for item in session.facts)
    assert second.result.evidence_ids == []
    assert all("provider" not in item.lower() for item in second.result.what_you_told)
    assert [request.purpose for request in provider.requests] == [
        "assessment", "assessment", "assessment_result"]


def test_stale_version_ownership_and_cancel(db, monkeypatch):
    monkeypatch.setattr(ai_assessment, "get_clinical_ai_provider",
                        lambda: PlanProvider([plan(needs=[need("duration", "When did this start?")])]))
    first = advance(db, "I have a headache")
    db.commit()
    with pytest.raises(HTTPException) as other:
        ai_assessment.owned_session(db, 8, first.assessment_id)
    assert other.value.status_code == 404
    with pytest.raises(HTTPException) as stale:
        advance(db, "Yesterday", assessment_id=first.assessment_id, version=0)
    assert stale.value.status_code == 409
    db.rollback()
    cancelled = ai_assessment.cancel_assessment(
        db, patient_id=7, assessment_id=first.assessment_id,
        expected_version=first.state_version, request_id="cancel-123")
    assert cancelled["status"] == "CANCELLED"
    assert ai_assessment.cancel_assessment(
        db, patient_id=7, assessment_id=first.assessment_id,
        expected_version=first.state_version, request_id="cancel-123") == cancelled
    with pytest.raises(HTTPException):
        advance(db, "Yesterday", assessment_id=first.assessment_id,
                version=cancelled["state_version"])


def test_provenance_denial_and_unknown_are_not_invented(db, monkeypatch):
    provider = PlanProvider([
        plan(facts=[fact("fever", "fever", status="DENIED"),
                    fact("swelling", "swelling", provenance="MODEL_INFERENCE")],
             needs=[need("fever", "Have you had a fever?", safety=3)]),
        plan(needs=[need("fever", "Have you had a fever?", safety=3),
                    need("duration", "When did this start?")]),
    ], finals=[valid_final])
    monkeypatch.setattr(ai_assessment, "get_clinical_ai_provider", lambda: provider)
    first = advance(db, "My urine looks foamy")
    db.commit()
    session = ai_assessment.owned_session(db, 7, first.assessment_id)
    assert not any(f.concept == "fever" for f in session.facts)
    assert any(f.provenance == "MODEL_INFERENCE" for f in session.facts)
    assert first.result.question == "Have you had a fever?"
    second = advance(db, "I don't know", assessment_id=first.assessment_id,
                     version=first.state_version, request_id="request-2")
    db.commit()
    assert second.result_kind.value == "ASSESSMENT_RESULT"
    assert len(session.questions) == 1
    assert any(f.concept == "fever" and f.status == "UNKNOWN" for f in session.facts)
    assert not any(f.concept == "fever" and f.status == "DENIED" for f in session.facts)


def test_question_selector_rejects_symptom_bundle(db, monkeypatch):
    provider = PlanProvider([plan(needs=[
        need("fever", "Do you have fever, pain, swelling, bleeding, nausea, or dizziness?", safety=3),
        need("duration", "When did this start?"),
    ])])
    monkeypatch.setattr(ai_assessment, "get_clinical_ai_provider", lambda: provider)
    response = advance(db, "I have a new symptom")
    assert response.result.question == "Have you had a fever?"


@pytest.mark.parametrize("answer", ["I don't know", "I can't remember", "I'm not sure"])
def test_common_unknown_answers_are_recognized(answer):
    assert ai_assessment.UNKNOWN_ANSWER.match(answer)


def test_invalid_final_repairs_once_and_failure_stays_ready(db, monkeypatch):
    bad = {"possible_explanations": [{"text": "Definitely cancer", "fact_ids": ["invented"]}],
           "next_steps": ["See a clinician"], "urgent_help_if": ["Severe symptoms"],
           "limitations": "No examination", "evidence_ids": ["fake-source"]}
    provider = PlanProvider([plan(facts=[fact("duration", "three months")], ready=True)],
                            finals=[bad, valid_final])
    monkeypatch.setattr(ai_assessment, "get_clinical_ai_provider", lambda: provider)
    result = advance(db, "Foamy urine for three months")
    db.commit()
    assert result.result_kind.value == "ASSESSMENT_RESULT"
    assert len(provider.requests) == 3

    failed = PlanProvider([plan(facts=[fact("duration", "three months")], ready=True)],
                          finals=[bad, bad])
    monkeypatch.setattr(ai_assessment, "get_clinical_ai_provider", lambda: failed)
    with pytest.raises(HTTPException) as error:
        advance(db, "Headache for three months", request_id="request-3")
    assert error.value.status_code == 503
    session = db.query(AIAssessment).filter_by(originating_request_id="request-3").one()
    assert session.status == "READY" and not session.usage_committed
    assert session.result_json is None


def test_urgent_interrupts_and_resume_expires(db, monkeypatch):
    monkeypatch.setattr(ai_assessment, "get_clinical_ai_provider",
                        lambda: PlanProvider([plan(needs=[need("duration", "When did this start?")])]))
    first = advance(db, "I have a headache")
    db.commit()
    assert ai_assessment.resumable_assessment(db, 7).id == first.assessment_id
    urgent = advance(db, "I have severe chest pain and I can't breathe properly",
                     assessment_id=first.assessment_id, version=first.state_version,
                     request_id="request-2")
    db.commit()
    assert urgent.result_kind.value == "URGENT"
    session = ai_assessment.owned_session(db, 7, first.assessment_id)
    assert session.status == "URGENT" and session.usage_committed
    with pytest.raises(HTTPException):
        advance(db, "Better now", assessment_id=first.assessment_id,
                version=urgent.state_version)
    db.rollback()

    session.last_activity_at = ai_assessment.utcnow() - timedelta(hours=73)
    session.expires_at = ai_assessment.utcnow() - timedelta(hours=1)
    db.commit()
    assert ai_assessment.resumable_assessment(db, 7) is None


def test_attachment_fact_needs_real_attachment(db, monkeypatch):
    proposed = plan(facts=[fact("skin_change", "red patch", provenance="ATTACHMENT_DERIVED")],
                    needs=[need("duration", "When did this start?")])
    provider = PlanProvider([proposed, proposed])
    monkeypatch.setattr(ai_assessment, "get_clinical_ai_provider", lambda: provider)
    plain = advance(db, "I have a rash")
    db.commit()
    assert not any(f.provenance == "ATTACHMENT_DERIVED" for f in
                   ai_assessment.owned_session(db, 7, plain.assessment_id).facts)
    attached = asyncio.run(ai_assessment.advance_assessment(
        db, patient_id=7, request_id="request-attachment", assessment_id=None,
        expected_version=None, message="I have a rash", language="English",
        attachment_id="image-owned-123"))
    db.commit()
    facts = ai_assessment.owned_session(db, 7, attached.assessment_id).facts
    assert any(f.provenance == "ATTACHMENT_DERIVED" and
               f.attachment_id == "image-owned-123" for f in facts)


@pytest.mark.parametrize("result_kind,expected_usage", [
    ("ASSESSMENT_QUESTION", 0),
    ("ASSESSMENT_RESULT", 1),
    ("URGENT", 1),
])
def test_assessment_accounting_is_one_text_unit(monkeypatch, result_kind, expected_usage):
    if result_kind == "ASSESSMENT_QUESTION":
        mode, kind, result = (InteractionMode.ASSESSMENT,
            ResultKind.ASSESSMENT_QUESTION, AssessmentQuestionResult(question="When did this start?"))
    elif result_kind == "ASSESSMENT_RESULT":
        mode, kind, result = (InteractionMode.ASSESSMENT,
            ResultKind.ASSESSMENT_RESULT, AssessmentResult(
                what_you_told=["A headache"],
                possible_explanations=[{"text": "Several possible causes", "fact_ids": ["f1"]}],
                why_considered=["A headache"], next_steps=["See a clinician"],
                urgent_help_if=["A sudden severe headache"],
                limitations="Not a diagnosis"))
    else:
        mode, kind, result = (InteractionMode.URGENT, ResultKind.URGENT,
            UrgentResult(action="Call 112 now", reason="Urgent symptoms"))

    async def response(_value):
        return InteractionResponse(
            request_id="request-123", interaction_id="assessment-id",
            assessment_id="assessment-id", state_version=2,
            mode=mode, result_kind=kind, result=result,
        )
    monkeypatch.setattr(chat, "run_interaction", response)
    user, usage_db = _user(), _UsageDb()
    asyncio.run(chat._analyze_chat_request(
        None, chat.ChatRequest(message="A headache"), usage_db, user,
        AIRequestLease(7, "owner", "digest")))
    assert user.monthly_chat_count == expected_usage
    assert user.burst_chat_count == expected_usage


def test_cleanup_removes_temp_payload_without_touching_vault(db, monkeypatch):
    monkeypatch.setattr(ai_assessment, "get_clinical_ai_provider",
                        lambda: PlanProvider([plan(needs=[need("duration", "When did this start?")])]))
    response = advance(db, "My skin has changed")
    db.commit()
    session = ai_assessment.owned_session(db, 7, response.assessment_id)
    session.last_activity_at = ai_assessment.utcnow() - timedelta(hours=25)
    session.expires_at = ai_assessment.utcnow() + timedelta(hours=47)
    db.commit()
    from app.core import database
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=db.bind))
    abandoned, expired = ai_assessment.cleanup_assessments()
    assert (abandoned, expired) == (1, 0)
    db.expire_all()
    assert ai_assessment.owned_session(db, 7, response.assessment_id).status == "ABANDONED"
    session = ai_assessment.owned_session(db, 7, response.assessment_id)
    session.expires_at = ai_assessment.utcnow() - timedelta(seconds=1)
    db.commit()
    abandoned, expired = ai_assessment.cleanup_assessments()
    assert expired == 1
    db.expire_all()
    with pytest.raises(HTTPException):
        ai_assessment.owned_session(db, 7, response.assessment_id)
    assert db.query(AIAssessmentFact).count() == 0
    assert db.query(AIAssessmentQuestion).count() == 0


def test_synthetic_evaluation_fixture_covers_adaptive_safety_and_provenance():
    fixture = json.loads((Path(__file__).parent / "fixtures" /
                          "ai_wave3_scenarios.json").read_text(encoding="utf-8"))
    assert fixture["synthetic_only"] is True
    assert len(fixture["cases"]) >= 12
    expected = {label for case in fixture["cases"] for label in case["expected"]}
    assert {"NO_REPEAT", "URGENT_OVERRIDE", "NO_FACT_MIXING",
            "ATTACHMENT_DERIVED_NOT_USER_STATED", "UNKNOWN_RECORDED",
            "READY_WITHOUT_FORCED_QUESTION_IF_SAFE"} <= expected
