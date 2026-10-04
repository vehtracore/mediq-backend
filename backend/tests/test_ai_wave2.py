"""Wave 2 interaction routing, safety, typing and continuation contracts."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import app.models.doctor  # noqa: F401 - resolves existing Vault ORM relationships
from app.api.v1.chat import _get_owned_lab_context
from app.models.lab_result import LabResult
from app.services import ai_orchestrator, ai_router, ai_service
from app.services.ai_interaction import (
    InteractionMode, InteractionResponse, MessageResult, ResultKind,
)
from app.services.ai_provider import (
    AIGenerationRequest, AIGenerationResult, AIErrorCategory, AIProviderError, AIMedia,
)
from app.services.ai_router import RouterInput, route_interaction
from app.services.ai_safety import evaluate_safety
from tests.ai_provider_fakes import install_model
from tests.test_ai_chat_quality import _FakeModel, _provider_response


class RouterProvider:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return AIGenerationResult(json.dumps(self.payload), "normal",
                                  structured_data=self.payload)


def _decision(mode, *, question=None, ambiguous=False):
    return {"mode": mode, "confidence": .91, "reason_codes": ["test"],
            "presenting_concern": None, "safety_signals": [],
            "ambiguous": ambiguous, "question": question}


def _router_input(message, **kwargs):
    return RouterInput(message=message, language="English", history=(),
                       attachment=kwargs.get("attachment"),
                       attachment_status="PRESENT_UNPROCESSED" if kwargs.get("attachment") else "NONE",
                       lab_context=kwargs.get("lab_context"), patient_context={},
                       safety=evaluate_safety(message),
                       continuing_assessment=kwargs.get("continuing", False))


@pytest.mark.parametrize("message,mode", [
    ("What does protein in urine mean?", "CONVERSATION"),
    ("Can dehydration cause dark urine?", "CONVERSATION"),
    ("My urine has been foamy for three months.", "ASSESSMENT"),
    ("I've had headaches for a week.", "ASSESSMENT"),
    ("My urine looks weird.", "ASSESSMENT"),
])
def test_router_returns_typed_mode_and_neutral_request(monkeypatch, message, mode):
    provider = RouterProvider(_decision(mode, question="What changed first?"))
    monkeypatch.setattr(ai_router, "get_clinical_ai_provider", lambda: provider)
    result = asyncio.run(route_interaction(_router_input(message)))
    assert result.mode == mode
    request = provider.requests[0]
    assert request.purpose == "router" and request.structured
    assert request.history == ()
    assert "'role': 'user'" not in str(request)


def test_deterministic_urgent_skips_provider_and_cannot_be_downgraded(monkeypatch):
    monkeypatch.setattr(ai_router, "get_clinical_ai_provider",
                        lambda: pytest.fail("urgent override must skip provider"))
    value = _router_input("I have severe chest pain and I can't breathe properly")
    assert value.safety.urgent_override
    result = asyncio.run(route_interaction(value))
    assert result.mode == InteractionMode.URGENT
    assert not evaluate_safety("What does severe chest pain mean?").urgent_override
    assert evaluate_safety("What do I do? I have severe chest pain and can't breathe.").urgent_override


def test_typed_response_rejects_mode_result_mismatch():
    with pytest.raises(ValueError):
        InteractionResponse(request_id="request-123", interaction_id="interaction-123",
                            mode=InteractionMode.URGENT, result_kind=ResultKind.MESSAGE,
                            result=MessageResult(text="Incorrect type"))


@pytest.mark.parametrize("error", [
    AIProviderError(AIErrorCategory.TIMEOUT, retryable=True),
    AIProviderError(AIErrorCategory.QUOTA_EXHAUSTED, retryable=True),
])
def test_router_failures_have_safe_text_fallbacks(monkeypatch, error):
    monkeypatch.setattr(ai_router, "get_clinical_ai_provider", lambda: RouterProvider(error=error))
    assert asyncio.run(route_interaction(_router_input("My urine is foamy"))).mode == InteractionMode.ASSESSMENT
    assert asyncio.run(route_interaction(_router_input("What does protein mean?"))).mode == InteractionMode.CONVERSATION
    assert asyncio.run(route_interaction(_router_input("Urine?"))).ambiguous


def test_malformed_structured_output_falls_back_without_leaking(monkeypatch):
    provider = RouterProvider({"mode": "UNSUPPORTED", "confidence": 2})
    monkeypatch.setattr(ai_router, "get_clinical_ai_provider", lambda: provider)
    result = asyncio.run(route_interaction(_router_input("I've had headaches")))
    assert result.mode == InteractionMode.ASSESSMENT
    assert result.confidence == 0
    assert "UNSUPPORTED" not in str(result)


def test_adapter_normalizes_invalid_native_json(monkeypatch):
    model = _FakeModel([_provider_response("not json", "STOP", scope=False)])
    adapter = install_model(monkeypatch, ai_router, "router", model)
    with pytest.raises(AIProviderError) as error:
        asyncio.run(adapter.generate(AIGenerationRequest(
            purpose="router", parts=("Route this",), output_tokens=200,
            structured=True,
        )))
    assert error.value.category == AIErrorCategory.INVALID_STRUCTURED_OUTPUT


def test_multimodal_router_processes_media_and_does_not_fallback_after_failure(monkeypatch):
    provider = RouterProvider(_decision("CONVERSATION"))
    monkeypatch.setattr(ai_router, "get_clinical_ai_provider", lambda: provider)
    value = _router_input("Can you explain this result?",
                          attachment=AIMedia("pdf_bytes", b"%PDF-test"))
    assert asyncio.run(route_interaction(value)).mode == InteractionMode.CONVERSATION
    assert any(isinstance(part, AIMedia) for part in provider.requests[0].parts)
    provider.error = AIProviderError(AIErrorCategory.MEDIA_PROCESSING_FAILED)
    with pytest.raises(AIProviderError) as error:
        asyncio.run(route_interaction(value))
    assert error.value.category == AIErrorCategory.MEDIA_PROCESSING_FAILED


def test_multimodal_personal_symptom_can_enter_assessment(monkeypatch):
    provider = RouterProvider(_decision("ASSESSMENT", question="Is the rash spreading?"))
    monkeypatch.setattr(ai_router, "get_clinical_ai_provider", lambda: provider)
    value = _router_input("Can you look at this rash I've had for several days?",
                          attachment=AIMedia("image_url", "https://example.invalid/image"))
    assert asyncio.run(route_interaction(value)).mode == InteractionMode.ASSESSMENT
    assert provider.requests[0].parts[-1].kind == "image_url"


def test_lab_context_is_router_data_not_a_flutter_instruction(monkeypatch):
    provider = RouterProvider(_decision("CONVERSATION"))
    monkeypatch.setattr(ai_router, "get_clinical_ai_provider", lambda: provider)
    asyncio.run(route_interaction(_router_input(
        "Explain this urinalysis result", lab_context='{"protein":"Trace"}')))
    assert "protein" in provider.requests[0].parts[1]
    assert "SYSTEM NOTIFICATION" not in str(provider.requests[0].parts)


def _interaction_input(message, **kwargs):
    return ai_orchestrator.InteractionInput(
        request_id="request-123", interaction_id=kwargs.get("interaction_id"),
        message=message, language="English", history=kwargs.get("history", []),
        user_context={}, image_url=kwargs.get("image_url"),
        lab_context=kwargs.get("lab_context"))


def test_conversation_is_direct_and_typed(monkeypatch):
    provider = RouterProvider(_decision("CONVERSATION"))
    monkeypatch.setattr(ai_router, "get_clinical_ai_provider", lambda: provider)
    async def answer(*_args, **_kwargs):
        return ai_service.MedicalAIResponse("Protein is a substance measured in urine tests.")
    monkeypatch.setattr(ai_service, "get_medical_response", answer)
    response = asyncio.run(ai_orchestrator.run_interaction(
        _interaction_input("What does protein in urine mean?")))
    assert response.mode == InteractionMode.CONVERSATION
    assert response.result_kind == ResultKind.MESSAGE
    assert response.result.text.startswith("Protein")
    assert "router" not in response.model_dump_json()


def test_assessment_entry_one_question_and_continuation(monkeypatch):
    provider = RouterProvider(_decision("ASSESSMENT", question="When did you first notice it?"))
    monkeypatch.setattr(ai_router, "get_clinical_ai_provider", lambda: provider)
    calls = []
    async def stored_assessment(_db, **kwargs):
        calls.append(kwargs)
        return InteractionResponse(
            request_id=kwargs["request_id"], interaction_id="assessment-id",
            assessment_id="assessment-id", state_version=len(calls),
            mode=InteractionMode.ASSESSMENT,
            result_kind=ResultKind.ASSESSMENT_QUESTION,
            result={"kind": "ASSESSMENT_QUESTION", "question":
                    "When did this start?" if len(calls) == 1 else "Has it changed?"},
        )
    monkeypatch.setattr(ai_orchestrator, "advance_assessment", stored_assessment)
    first = asyncio.run(ai_orchestrator.run_interaction(
        ai_orchestrator.InteractionInput(
            request_id="request-123", interaction_id=None,
            message="My urine is foamy every morning", language="English",
            history=[], user_context={}, db=object(), patient_id=7)))
    assert first.result_kind == ResultKind.ASSESSMENT_QUESTION
    assert first.result.question.count("?") == 1
    assert "start an assessment" not in first.result.question.lower()
    provider.payload = _decision("CONVERSATION")
    second = asyncio.run(ai_orchestrator.run_interaction(
        ai_orchestrator.InteractionInput(
            request_id="request-124", interaction_id=first.interaction_id,
            message="For three months", language="English", history=[],
            user_context={}, db=object(), patient_id=7, expected_state_version=1)))
    assert second.interaction_id == first.interaction_id
    assert second.result_kind == ResultKind.ASSESSMENT_QUESTION
    assert second.result.question != first.result.question
    assert len(provider.requests) == 1
    assert calls[1]["expected_version"] == 1


def test_urgent_action_first_without_provider(monkeypatch):
    monkeypatch.setattr(ai_router, "get_clinical_ai_provider",
                        lambda: pytest.fail("no provider call for urgent"))
    response = asyncio.run(ai_orchestrator.run_interaction(_interaction_input(
        "I have severe chest pain and I can't breathe properly")))
    assert response.mode == InteractionMode.URGENT
    assert response.result_kind == ResultKind.URGENT
    assert response.result.action.startswith("Call 112 now")
    assert len(response.result.reason) < 100


def test_model_emergency_signal_cannot_be_downgraded_by_mode(monkeypatch):
    payload = _decision("CONVERSATION")
    payload["safety_signals"] = ["immediate_emergency"]
    provider = RouterProvider(payload)
    monkeypatch.setattr(ai_router, "get_clinical_ai_provider", lambda: provider)
    response = asyncio.run(ai_orchestrator.run_interaction(
        _interaction_input("My chest is hurting and I feel faint")))
    assert response.result_kind == ResultKind.URGENT


def test_wave2_evaluation_cases_have_explicit_expected_and_forbidden_behavior():
    path = Path(__file__).parent / "fixtures" / "ai_wave2_scenarios.json"
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    assert len(cases) >= 8
    assert len({case["id"] for case in cases}) == len(cases)
    assert all(case["current_observed_behavior"] and case["desired_mode"]
               and case["forbidden_mode"] and case["safety_expectation"]
               and isinstance(case["question_expected"], bool)
               for case in cases)


def test_lab_context_requires_record_owner():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO users (id) VALUES (7), (8)"))
    LabResult.__table__.create(bind=engine)
    with Session(engine) as db:
        db.add(LabResult(user_id=7, raw_data={"status": "SUCCESS",
                                          "readings": {"protein": {"value": "Trace"}}}))
        db.commit()
        record_id = db.query(LabResult.id).scalar()
        assert _get_owned_lab_context(db, record_id, 7)["readings"]["protein"]["value"] == "Trace"
        with pytest.raises(HTTPException) as denied:
            _get_owned_lab_context(db, record_id, 8)
        assert denied.value.status_code == 404
        invalid_record = LabResult(user_id=7, raw_data=None)
        db.add(invalid_record)
        db.commit()
        with pytest.raises(HTTPException) as invalid:
            _get_owned_lab_context(db, invalid_record.id, 7)
        assert invalid.value.status_code == 422
    engine.dispose()
