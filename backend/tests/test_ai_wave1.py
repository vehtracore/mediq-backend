"""Wave 1 contracts: one reasoning adapter, recoverable operations, honest media."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from google.api_core.exceptions import ResourceExhausted

import app.models.doctor  # noqa: F401 - resolves Vault ORM relationships
from app.api.v1 import chat
from app.services import ai_chat_operation, ai_provider, ai_service, ai_summary_service
from app.services import ai_orchestrator
from app.services.ai_interaction import InteractionMode, InteractionResponse, MessageResult, ResultKind
from app.services.ai_router import RouterDecision
from app.services.ai_provider import AIErrorCategory, AIProviderError
from app.services.ai_request_guard import AIRequestLease
from app.services.gemini_adapter import GeminiAdapter, _map_error
from app.models.ai_chat_receipt import AIChatRequestReceipt
from tests.test_ai_chat_quality import _UsageDb, _user


@pytest.fixture(autouse=True)
def legacy_generation_focus(monkeypatch):
    async def conversation(_value):
        return RouterDecision(mode=InteractionMode.CONVERSATION, confidence=1,
                              reason_codes=["test_conversation"])

    monkeypatch.setattr(ai_orchestrator, "route_interaction", conversation)

@pytest.fixture
def stub_chat_operation(monkeypatch):
    finished = []
    monkeypatch.setattr(chat, "acquire_chat_operation", lambda db, uid, rid, fp:
                        ai_chat_operation.ChatOperation(uid, rid, "owner", fp, "started"))
    monkeypatch.setattr(chat, "start_chat_operation", lambda db, operation: True)
    monkeypatch.setattr(chat, "finish_chat_operation", lambda db, operation, *, succeeded:
                        finished.append(succeeded))
    return finished


def test_gemini_native_errors_are_normalized():
    error = _map_error(ResourceExhausted("quota exhausted"))
    assert error.category == AIErrorCategory.QUOTA_EXHAUSTED
    assert error.retryable
    assert _map_error(TimeoutError()).category == AIErrorCategory.TIMEOUT


def test_only_configured_reasoning_provider_is_accepted(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "unsupported")
    with pytest.raises(AIProviderError) as error:
        ai_provider.get_clinical_ai_provider()
    assert error.value.category == AIErrorCategory.AUTH_CONFIGURATION_ERROR


def test_vault_summary_preserves_provider_quota_category(monkeypatch):
    class QuotaProvider:
        async def count_input(self, request):
            assert request.purpose == "summary"
            return 10

        async def generate(self, request):
            assert request.purpose == "summary"
            raise AIProviderError(AIErrorCategory.QUOTA_EXHAUSTED, retryable=True)

    monkeypatch.setattr(ai_summary_service, "get_clinical_ai_provider", lambda: QuotaProvider())
    with pytest.raises(ai_summary_service.AISummaryGenerationError) as error:
        asyncio.run(ai_summary_service.generate_ai_vault_summary([
            ai_summary_service.SummaryTurn("user", "I have a headache"),
        ]))
    assert error.value.category == AIErrorCategory.QUOTA_EXHAUSTED


def test_gemini_history_conversion_is_adapter_only():
    from app.services.ai_provider import AIGenerationRequest, AIHistoryTurn

    history = GeminiAdapter._history(AIGenerationRequest(
        "standard", ("hello",), 500,
        (AIHistoryTurn("patient", "question"), AIHistoryTurn("mdq_plus", "answer")),
    ))
    assert [turn["role"] for turn in history] == ["user", "model"]


def test_failed_image_fetch_never_commits_attachment_usage(monkeypatch):
    async def fail_image(*_args, **_kwargs):
        raise AIProviderError(AIErrorCategory.MEDIA_PROCESSING_FAILED, retryable=True)

    monkeypatch.setattr(ai_service, "get_medical_response", fail_image)
    monkeypatch.setattr(chat, "generate_sensitive_access", lambda *_args, **_kwargs: SimpleNamespace(url="https://temporary.invalid/image"))
    monkeypatch.setattr(chat, "_delete_temp_image", lambda *_args, **_kwargs: True)
    user = _user()
    db = _UsageDb()
    with pytest.raises(HTTPException) as error:
        asyncio.run(chat._analyze_chat_request(
            SimpleNamespace(),
            chat.ChatRequest(message="What is shown?", image_public_id="mediq_ai_temp/7/img", image_format="png"),
            db, user, AIRequestLease(7, "owner", "digest"),
        ))
    assert error.value.status_code == 422
    assert user.monthly_chat_count == 0
    assert user.monthly_chat_image_count == 0
    assert db.commits == 0


def test_successful_chat_receipt_commits_with_usage(monkeypatch):
    async def answer(*_args, **_kwargs):
        return ai_service.MedicalAIResponse("Complete answer")

    class RecordingDb(_UsageDb):
        def __init__(self):
            super().__init__()
            self.added = []

        def add(self, value):
            self.added.append(value)

    monkeypatch.setattr(ai_service, "get_medical_response", answer)
    monkeypatch.setattr(chat, "require_chat_operation_owner", lambda *_args: None)
    user = _user()
    db = RecordingDb()
    operation = ai_chat_operation.ChatOperation(7, "request-123", "owner", "hash-a", "started")
    result = asyncio.run(chat._analyze_chat_request(
        SimpleNamespace(), chat.ChatRequest(message="What does HbA1c mean?"),
        db, user, AIRequestLease(7, "owner", "digest"), operation=operation,
    ))
    receipts = [item for item in db.added if isinstance(item, AIChatRequestReceipt)]
    assert result.result.text == "Complete answer"
    assert db.commits == 1
    assert user.monthly_chat_count == 1
    assert len(receipts) == 1
    assert receipts[0].response_json["result"]["text"] == result.result.text


def test_evaluation_baseline_distinguishes_observation_from_requirement():
    path = Path(__file__).parent / "fixtures" / "ai_wave1_scenarios.json"
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    assert len(cases) >= 11
    assert len({case["id"] for case in cases}) == len(cases)
    assert all(case["current_observed_behavior"] and case["desired_requirement"] for case in cases)


def test_committed_receipt_replays_without_provider_or_quota_work(monkeypatch):
    payload = chat.ChatRequest(message="What does HbA1c mean?")
    fingerprint = chat._chat_fingerprint(payload)
    receipt = SimpleNamespace(
        request_fingerprint=fingerprint,
        response_json=InteractionResponse(request_id="request-123", interaction_id="interaction-123",
                                          mode=InteractionMode.CONVERSATION, result_kind=ResultKind.MESSAGE,
                                          result=MessageResult(text="Saved answer")).model_dump(),
    )
    monkeypatch.setattr(chat, "_get_chat_receipt", lambda *_args: receipt)

    async def unexpected(*_args, **_kwargs):
        raise AssertionError("provider must not run for a committed receipt")

    monkeypatch.setattr(chat, "_analyze_chat_request", unexpected)
    result = asyncio.run(chat._run_chat_operation(
        SimpleNamespace(), payload, SimpleNamespace(), _user(), "request-123",
    ))
    assert result.result.text == "Saved answer"


def test_provider_failure_releases_chat_operation(monkeypatch, stub_chat_operation):
    monkeypatch.setattr(chat, "_get_chat_receipt", lambda *_args: None)

    async def failed(*_args, **_kwargs):
        raise AIProviderError(AIErrorCategory.QUOTA_EXHAUSTED)

    monkeypatch.setattr(chat, "_analyze_chat_request", failed)
    with pytest.raises(AIProviderError):
        asyncio.run(chat._run_chat_operation(
            SimpleNamespace(), chat.ChatRequest(message="hello"),
            SimpleNamespace(), _user(), "request-123",
        ))
    assert stub_chat_operation == [False]


def test_terminal_timeout_releases_chat_operation(monkeypatch, stub_chat_operation):
    monkeypatch.setattr(chat, "_get_chat_receipt", lambda *_args: None)

    async def unfinished(*_args, **_kwargs):
        await asyncio.sleep(30)

    async def expire(coroutine, *, timeout):
        coroutine.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr(chat, "_analyze_chat_request", unfinished)
    monkeypatch.setattr(chat.asyncio, "wait_for", expire)
    with pytest.raises(HTTPException) as error:
        asyncio.run(chat._run_chat_operation(
            SimpleNamespace(), chat.ChatRequest(message="hello"),
            SimpleNamespace(), _user(), "request-123",
        ))
    assert error.value.status_code == 504
    assert stub_chat_operation == [False]
