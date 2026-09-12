import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1 import chat
from app.services import ai_service
from app.services.ai_request_guard import AIRequestLease


def _provider_response(text: str, finish_reason: str, output_tokens: int = 20):
    return SimpleNamespace(
        text=text,
        candidates=[SimpleNamespace(finish_reason=finish_reason)],
        usage_metadata=SimpleNamespace(candidates_token_count=output_tokens),
    )


class _FakeChat:
    def __init__(self, model):
        self.model = model

    async def send_message_async(self, prompt, generation_config):
        self.model.prompts.append(prompt)
        self.model.configs.append(generation_config)
        return self.model.responses.pop(0)


class _FakeModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []
        self.configs = []
        self.histories = []

    def start_chat(self, history):
        self.histories.append(history)
        return _FakeChat(self)

    async def count_tokens_async(self, _contents):
        return SimpleNamespace(total_tokens=100)


def _install_standard_model(monkeypatch, responses):
    model = _FakeModel(responses)
    monkeypatch.setattr(ai_service, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(ai_service, "standard_model", model)
    return model


def _run_medical_response(**kwargs):
    return asyncio.run(ai_service.get_medical_response("I have a mild headache", **kwargs))


def test_first_message_quality_prompt_and_output_limit_are_plan_independent(monkeypatch):
    model = _install_standard_model(
        monkeypatch,
        [_provider_response("Complete answer", "STOP") for _ in range(3)],
    )

    results = [
        _run_medical_response(plan_category=plan)
        for plan in ("free", "premium", "family")
    ]

    assert [result.text for result in results] == ["Complete answer"] * 3
    assert model.prompts[0] == model.prompts[1] == model.prompts[2]
    assert all(
        config["max_output_tokens"] == ai_service.MAX_STANDARD_OUTPUT_TOKENS == 500
        for config in model.configs
    )
    assert "Be concise, direct, and reassuring where appropriate, but complete" in ai_service.SYSTEM_INSTRUCTION
    assert "do not omit important next steps merely to remain short" in ai_service.SYSTEM_INSTRUCTION


def test_normal_completion_returns_without_repair(monkeypatch):
    model = _install_standard_model(
        monkeypatch,
        [_provider_response("A complete answer", "STOP")],
    )

    result = _run_medical_response()

    assert result.text == "A complete answer"
    assert len(model.prompts) == 1


def test_max_tokens_runs_one_full_repair_and_never_returns_the_fragment(monkeypatch):
    model = _install_standard_model(
        monkeypatch,
        [
            _provider_response("cut-off fragment", "MAX_TOKENS", 500),
            _provider_response("Complete repaired answer", "STOP", 120),
        ],
    )

    result = _run_medical_response()

    assert result.text == "Complete repaired answer"
    assert "cut-off fragment" not in result.text
    assert len(model.prompts) == 2
    assert all(config["max_output_tokens"] == 500 for config in model.configs)
    assert "Regenerate the entire answer from the beginning" in model.prompts[1][-1]


@pytest.mark.parametrize("second_reason", ["MAX_TOKENS", "SAFETY"])
def test_failed_max_token_repair_returns_no_fragment(monkeypatch, second_reason):
    model = _install_standard_model(
        monkeypatch,
        [
            _provider_response("first fragment", "MAX_TOKENS", 500),
            _provider_response("second fragment", second_reason, 200),
        ],
    )

    with pytest.raises(ai_service.AIResponseCompletionError):
        _run_medical_response()

    assert len(model.prompts) == 2


@pytest.mark.parametrize("reason", ["SAFETY", "RECITATION", "OTHER", "BLOCKLIST"])
def test_abnormal_completion_is_not_presented_as_an_answer(monkeypatch, reason):
    model = _install_standard_model(
        monkeypatch,
        [_provider_response("provider fragment", reason)],
    )

    with pytest.raises(ai_service.AIResponseCompletionError):
        _run_medical_response()

    assert len(model.prompts) == 1


def test_memory_parser_extracts_complete_hidden_block():
    visible, memory = ai_service.extract_memory_update(
        "Visible complete answer.\n<memory_update>Headache for three days.</memory_update>"
    )
    assert visible == "Visible complete answer."
    assert memory == "Headache for three days."
    assert "memory_update" not in visible


@pytest.mark.parametrize(
    "malformed",
    [
        "Visible answer. <memory_update>hidden without close",
        "Visible answer. </memory_update>",
    ],
)
def test_malformed_memory_markup_fails_instead_of_silently_clipping(malformed):
    with pytest.raises(ai_service.AIMalformedMemoryError):
        ai_service.extract_memory_update(malformed)


class _UsageDb:
    def __init__(self, summary=None):
        self.summary = summary
        self.commits = 0

    def add(self, _value):
        return None

    def commit(self):
        self.commits += 1

    def query(self, _model):
        summary = self.summary

        class _Query:
            def filter(self, *_criteria):
                return self

            def first(self):
                return summary

        return _Query()


def _user(plan="free"):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return SimpleNamespace(
        id=7,
        plan=plan,
        subscription_expiry=None,
        ai_consent_granted_at=datetime.now(timezone.utc),
        ai_consent_withdrawn_at=None,
        chat_blocked_until=None,
        burst_start_time=now,
        burst_chat_count=0,
        monthly_chat_count=0,
        monthly_chat_image_count=0,
        last_chat_month_reset=date.today(),
        monthly_lab_count=0,
        last_lab_reset=date.today(),
        rolling_chat_count=0,
        rolling_chat_image_count=0,
        rolling_chat_window_start=now,
        dob=None,
        chronic_conditions=None,
    )


def _history(message_count=12):
    return [
        {
            "role": "user" if index % 2 == 0 else "model",
            "parts": [f"message-{index}"],
        }
        for index in range(message_count)
    ]


def _run_route(monkeypatch, *, user, request=None, db=None, provider=None):
    captured = []

    async def _response(*_args, **kwargs):
        captured.append(kwargs)
        if provider is not None:
            return await provider(*_args, **kwargs)
        return ai_service.MedicalAIResponse("Safe complete response")

    monkeypatch.setattr(ai_service, "get_medical_response", _response)
    db = db or _UsageDb()
    lease = AIRequestLease(user.id, "owner", "request")
    result = asyncio.run(
        chat._analyze_chat_request(
            request=SimpleNamespace(),
            chat_request=request or chat.ChatRequest(message="follow up"),
            db=db,
            current_user=user,
            request_lease=lease,
        )
    )
    return result, captured, db, lease


def test_free_context_is_bounded_and_rolling_memory_is_ignored(monkeypatch):
    request = chat.ChatRequest(
        message="Three days",
        history=_history(),
        conversation_memory="paid memory",
        memory_source="older paid turns",
        update_memory=True,
    )

    _, captured, _, _ = _run_route(monkeypatch, user=_user("free"), request=request)
    kwargs = captured[0]

    assert [item["parts"][0] for item in kwargs["history"]] == [
        "message-8",
        "message-9",
        "message-10",
        "message-11",
    ]
    assert kwargs["conversation_memory"] is None
    assert kwargs["memory_source"] is None
    assert kwargs["update_memory"] is False


@pytest.mark.parametrize("plan", ["premium", "family"])
def test_paid_context_retains_ten_messages_and_rolling_memory(monkeypatch, plan):
    request = chat.ChatRequest(
        message="Three days",
        history=_history(),
        conversation_memory="paid memory",
        memory_source="older paid turns",
        update_memory=True,
    )

    _, captured, _, _ = _run_route(monkeypatch, user=_user(plan), request=request)
    kwargs = captured[0]

    assert len(kwargs["history"]) == 10
    assert kwargs["history"][0]["parts"] == ["message-2"]
    assert kwargs["conversation_memory"] == "paid memory"
    assert kwargs["memory_source"] == "older paid turns"
    assert kwargs["update_memory"] is True


def test_free_direct_continuation_is_rejected_before_summary_lookup_or_ai(monkeypatch):
    called = False

    async def _response(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(ai_service, "get_medical_response", _response)
    request = chat.ChatRequest(
        message="Continue",
        source_summary_id=uuid4(),
        source_summary_updated_at=datetime.now(timezone.utc),
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            chat._analyze_chat_request(
                request=SimpleNamespace(),
                chat_request=request,
                db=_UsageDb(),
                current_user=_user("free"),
                request_lease=AIRequestLease(7, "owner", "request"),
            )
        )

    assert exc.value.status_code == 403
    assert called is False


@pytest.mark.parametrize("plan", ["premium", "family"])
def test_paid_direct_continuation_receives_owned_saved_context(monkeypatch, plan):
    summary = SimpleNamespace(
        id=uuid4(),
        patient_id=7,
        summary_text="Saved historical context",
        updated_at=datetime.now(timezone.utc),
    )
    request = chat.ChatRequest(
        message="Continue",
        source_summary_id=summary.id,
        source_summary_updated_at=summary.updated_at,
    )

    _, captured, _, _ = _run_route(
        monkeypatch,
        user=_user(plan),
        request=request,
        db=_UsageDb(summary),
    )

    assert captured[0]["historical_saved_context"] == "Saved historical context"


def test_successful_repair_consumes_one_logical_use(monkeypatch):
    model = _install_standard_model(
        monkeypatch,
        [
            _provider_response("fragment", "MAX_TOKENS", 500),
            _provider_response("Complete repair", "STOP", 100),
        ],
    )
    user = _user("free")
    db = _UsageDb()
    lease = AIRequestLease(user.id, "owner", "request")

    result = asyncio.run(
        chat._analyze_chat_request(
            request=SimpleNamespace(),
            chat_request=chat.ChatRequest(message="I have a mild headache"),
            db=db,
            current_user=user,
            request_lease=lease,
        )
    )

    assert result.response == "Complete repair"
    assert len(model.prompts) == 2
    assert user.monthly_chat_count == 1
    assert user.burst_chat_count == 1
    assert db.commits == 1


def test_failed_repair_consumes_no_successful_use(monkeypatch):
    model = _install_standard_model(
        monkeypatch,
        [
            _provider_response("fragment", "MAX_TOKENS", 500),
            _provider_response("still partial", "MAX_TOKENS", 500),
        ],
    )
    user = _user("free")
    db = _UsageDb()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            chat._analyze_chat_request(
                request=SimpleNamespace(),
                chat_request=chat.ChatRequest(message="I have a mild headache"),
                db=db,
                current_user=user,
                request_lease=AIRequestLease(user.id, "owner", "request"),
            )
        )

    assert exc.value.status_code == 503
    assert len(model.prompts) == 2
    assert user.monthly_chat_count == 0
    assert user.burst_chat_count == 0
    assert db.commits == 0
