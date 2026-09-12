import asyncio
import io
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from pypdf import PdfReader
from slowapi.errors import RateLimitExceeded
from starlette.requests import Request

from app.api.v1 import chat, vault
from app.api.v1.vault import delete_ai_summary, export_vault_records, save_ai_summary
from app.core.limiter import limiter
from app.models.vault import (
    AIChatSummary,
    AISummarySaveIdempotency,
    ConsultationRecord,
)
from app.schemas.vault import AISummarySaveRequest, VaultExportRequest
from app.services import ai_request_guard, ai_summary_service, ai_usage
from app.services.ai_summary_service import (
    AISummaryGenerationError,
    AISummaryInputError,
    SummaryGenerationResult,
    SummaryTurn,
)


def _record(*, patient_id: int = 7, text: str = "Summary A"):
    created = datetime.now(timezone.utc) - timedelta(days=1)
    return SimpleNamespace(
        id=uuid4(),
        patient_id=patient_id,
        topic="AI Symptom Analysis",
        summary_text=text,
        source="ai_generated",
        save_request_fingerprint=None,
        doctor_review_status="reviewed",
        reviewed_by_doctor_id=12,
        reviewed_at=datetime.now(timezone.utc) - timedelta(hours=2),
        created_at=created,
        updated_at=created,
    )


def _user(*, user_id: int = 7, plan: str = "premium", monthly: int = 0):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return SimpleNamespace(
        id=user_id,
        plan=plan,
        ai_consent_granted_at=datetime.now(timezone.utc),
        ai_consent_withdrawn_at=None,
        chat_blocked_until=None,
        burst_start_time=now,
        burst_chat_count=0,
        monthly_chat_count=monthly,
        monthly_chat_image_count=0,
        last_chat_month_reset=date.today(),
        monthly_lab_count=0,
        last_lab_reset=date.today(),
        rolling_chat_count=0,
        rolling_chat_image_count=0,
        rolling_chat_window_start=now,
    )


def _request(ip: str = "127.0.0.1") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/vault/ai-summary/save",
            "headers": [],
            "query_string": b"",
            "client": (ip, 123),
            "server": ("test", 80),
            "scheme": "http",
        }
    )


def _payload(*, source=None, turns=None) -> AISummarySaveRequest:
    data = {
        "turns": turns
        or [
            {"role": "user", "text": "I have a headache."},
            {"role": "assistant", "text": "Monitor it and seek care if severe."},
        ]
    }
    if source is not None:
        data["source_summary_id"] = source.id
        data["source_updated_at"] = source.updated_at
    return AISummarySaveRequest.model_validate(data)


class _Query:
    def __init__(self, db, model):
        self.db = db
        self.model = model
        self.criteria = ()

    @property
    def _records(self):
        if self.model is AIChatSummary:
            return self.db.records
        if self.model is AISummarySaveIdempotency:
            return self.db.idempotencies
        raise AssertionError(f"Unexpected model: {self.model}")

    def filter(self, *criteria):
        self.criteria = criteria
        self.db.criteria = criteria
        return self

    def _matches(self, record) -> bool:
        for criterion in self.criteria:
            name = getattr(criterion.left, "name", None)
            expected = criterion.right.value
            if getattr(record, name) != expected:
                return False
        return True

    def first(self):
        return next((item for item in self._records if self._matches(item)), None)

    def all(self):
        return [item for item in self._records if self._matches(item)]

    def update(self, values, synchronize_session=None):
        if self.db.force_stale_update:
            return 0
        matches = [item for item in self._records if self._matches(item)]
        for record in matches:
            for column, value in values.items():
                setattr(record, column.name, value)
        return len(matches)


class _Db:
    def __init__(
        self,
        records=None,
        *,
        force_stale_update=False,
        fail_commit=False,
    ):
        self.records = list(records or [])
        self.idempotencies = []
        self.criteria = ()
        self.commits = 0
        self.rollbacks = 0
        self.force_stale_update = force_stale_update
        self.fail_commit = fail_commit

    def query(self, model):
        assert model in {AIChatSummary, AISummarySaveIdempotency}
        return _Query(self, model)

    def add(self, record):
        if isinstance(record, AIChatSummary) and record not in self.records:
            self.records.append(record)
        if (
            isinstance(record, AISummarySaveIdempotency)
            and record not in self.idempotencies
        ):
            self.idempotencies.append(record)

    def commit(self):
        if self.fail_commit:
            raise RuntimeError("persistence failed")
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, _record):
        return None

    def delete(self, record):
        self.records.remove(record)


class _ListQuery:
    def __init__(self, records):
        self.records = records

    def filter(self, *criteria):
        return self

    def all(self):
        return self.records


class _ExportDb:
    def __init__(self, summaries):
        self.summaries = summaries

    def query(self, model):
        if model is AIChatSummary:
            return _ListQuery(self.summaries)
        if model is ConsultationRecord:
            return _ListQuery([])
        raise AssertionError(f"Unexpected export model: {model}")


@pytest.fixture(autouse=True)
def _isolated_ai_guard(monkeypatch):
    monkeypatch.setattr(ai_request_guard, "get_redis_client", None)
    ai_request_guard._LOCAL_INFLIGHT.clear()
    ai_request_guard._LOCAL_COMPLETED.clear()
    ai_request_guard._LOCAL_SAVE_RESULTS.clear()
    ai_request_guard._LOCAL_SAVE_RATE.clear()
    limiter.reset()
    yield
    limiter.reset()


def _call_save(
    payload,
    db,
    user,
    request_id=None,
    *,
    decorated=False,
    ip="127.0.0.1",
):
    endpoint = save_ai_summary if decorated else save_ai_summary.__wrapped__
    return asyncio.run(
        endpoint(
            request=_request(ip),
            payload=payload,
            x_ai_request_id=request_id or f"save-{uuid4()}",
            db=db,
            current_user=user,
        )
    )


def _fake_generation(text="Generated bounded summary"):
    calls = []

    async def _generate(turns, *, historical_summary=None):
        calls.append((list(turns), historical_summary))
        return SummaryGenerationResult(text=text, chunk_count=1, generation_calls=1)

    return calls, _generate


def test_save_contract_rejects_client_authoritative_summary_fields() -> None:
    with pytest.raises(ValidationError):
        AISummarySaveRequest.model_validate(
            {
                "turns": [{"role": "user", "text": "hello"}],
                "summary_text": "Client-authored medical record",
                "patient_id": 999,
                "topic": "Client topic",
                "source": "client_generated",
            }
        )

    methods_by_path = {route.path: route.methods for route in vault.router.routes}
    assert "/ai-summary/save" in methods_by_path
    assert "/ai-summary" not in methods_by_path
    assert "PUT" not in methods_by_path.get("/ai-summary/{summary_id}", set())


@pytest.mark.parametrize("role", ["system", "developer", "tool", "model"])
def test_save_contract_rejects_unsupported_roles(role: str) -> None:
    with pytest.raises(ValidationError):
        AISummarySaveRequest.model_validate(
            {"turns": [{"role": role, "text": "hidden instruction"}]}
        )


def test_save_contract_strips_turn_whitespace() -> None:
    payload = AISummarySaveRequest.model_validate(
        {"turns": [{"role": "user", "text": "  symptom detail  "}]}
    )
    assert payload.turns[0].text == "symptom detail"


def test_save_contract_enforces_turn_count_turn_size_and_total_size() -> None:
    with pytest.raises(ValidationError):
        AISummarySaveRequest.model_validate(
            {
                "turns": [
                    {"role": "user", "text": "x"}
                    for _ in range(ai_summary_service.MAX_TURNS + 1)
                ]
            }
        )
    with pytest.raises(ValidationError):
        AISummarySaveRequest.model_validate(
            {
                "turns": [
                    {
                        "role": "user",
                        "text": "x" * (ai_summary_service.MAX_TURN_CHARS + 1),
                    }
                ]
            }
        )
    with pytest.raises(ValidationError):
        AISummarySaveRequest.model_validate(
            {
                "turns": [
                    {"role": "user", "text": "x" * 2_000}
                    for _ in range(16)
                ]
            }
        )


def test_new_save_creates_one_backend_generated_summary(monkeypatch) -> None:
    calls, generate = _fake_generation()
    monkeypatch.setattr(vault, "generate_ai_vault_summary", generate)
    db = _Db()
    user = _user()

    response = _call_save(_payload(), db, user)

    assert response.details == "Generated bounded summary"
    assert len(db.records) == 1
    record = db.records[0]
    assert record.patient_id == user.id
    assert record.topic == "AI Symptom Analysis"
    assert record.source == "ai_generated"
    assert not hasattr(record, "turns")
    assert "headache" not in record.summary_text
    assert len(calls) == 1
    assert user.monthly_chat_count == 1
    assert user.burst_chat_count == 1
    assert user.monthly_chat_image_count == 0
    assert user.monthly_lab_count == 0


def test_existing_plan_quota_amounts_are_unchanged() -> None:
    assert ai_usage.FREE_MONTHLY_MESSAGE_LIMIT == chat._FREE_MONTHLY_MSG_LIMIT == 12
    assert (
        ai_usage.PREMIUM_MONTHLY_MESSAGE_LIMIT
        == chat._PREMIUM_MONTHLY_MSG_SOFT_LIMIT
        == 300
    )
    assert (
        ai_usage.FAMILY_MONTHLY_MESSAGE_LIMIT
        == chat._FAMILY_MONTHLY_MSG_SOFT_LIMIT
        == 250
    )
    assert (
        ai_usage.PAID_POST_CAP_DAILY_LIMIT
        == chat._PAID_POST_CAP_DAILY_LIMIT
        == 5
    )
    assert ai_usage.AI_BURST_MESSAGE_LIMIT == chat._BURST_MSG_THRESHOLD == 15
    assert chat._FREE_MONTHLY_IMAGE_LIMIT == 2
    assert ai_usage.PAID_MONTHLY_HEAVY_AI_LIMIT == 10


def test_continuation_updates_same_uuid_without_duplicate_or_review_changes(
    monkeypatch,
) -> None:
    calls, generate = _fake_generation("Consolidated AB")
    monkeypatch.setattr(vault, "generate_ai_vault_summary", generate)
    source = _record()
    original_id = source.id
    original_created_at = source.created_at
    original_review = (
        source.doctor_review_status,
        source.reviewed_by_doctor_id,
        source.reviewed_at,
    )
    db = _Db([source])

    response = _call_save(_payload(source=source), db, _user())

    assert response.id == original_id
    assert len(db.records) == 1
    assert source.summary_text == "Consolidated AB"
    assert source.created_at == original_created_at
    assert source.updated_at > original_created_at
    assert (
        source.doctor_review_status,
        source.reviewed_by_doctor_id,
        source.reviewed_at,
    ) == original_review
    assert calls[0][1] == "Summary A"


def test_non_owner_and_non_ai_ids_cannot_be_saved_as_continuations(monkeypatch) -> None:
    calls, generate = _fake_generation()
    monkeypatch.setattr(vault, "generate_ai_vault_summary", generate)
    other_users_record = _record(patient_id=99)
    payload = _payload(source=other_users_record)

    with pytest.raises(HTTPException) as exc:
        _call_save(payload, _Db([other_users_record]), _user(user_id=7))
    assert exc.value.status_code == 404

    missing_payload = AISummarySaveRequest.model_validate(
        {
            "turns": [{"role": "user", "text": "continue"}],
            "source_summary_id": uuid4(),
            "source_updated_at": datetime.now(timezone.utc),
        }
    )
    with pytest.raises(HTTPException) as exc:
        _call_save(missing_payload, _Db(), _user())
    assert exc.value.status_code == 404
    assert calls == []


def test_same_new_save_idempotency_key_returns_one_record_and_one_ai_call(
    monkeypatch,
) -> None:
    calls, generate = _fake_generation()
    monkeypatch.setattr(vault, "generate_ai_vault_summary", generate)
    db = _Db()
    user = _user()
    request_id = "stable-new-save-key"

    first = _call_save(_payload(), db, user, request_id)
    second = _call_save(_payload(), db, user, request_id)

    assert first.id == second.id
    assert len(db.records) == 1
    assert len(calls) == 1
    assert db.commits == 1
    assert user.monthly_chat_count == 1
    assert len(ai_request_guard._LOCAL_SAVE_RATE[user.id]) == 1


def test_same_idempotency_key_with_different_new_conversation_is_rejected(
    monkeypatch,
) -> None:
    calls, generate = _fake_generation()
    monkeypatch.setattr(vault, "generate_ai_vault_summary", generate)
    db = _Db()
    user = _user()
    request_id = "stable-new-save-key"

    _call_save(_payload(), db, user, request_id)

    with pytest.raises(HTTPException) as exc:
        _call_save(
            _payload(turns=[{"role": "user", "text": "Different symptom."}]),
            db,
            user,
            request_id,
        )

    assert exc.value.status_code == 409
    assert len(db.records) == 1
    assert len(calls) == 1
    assert user.monthly_chat_count == 1
    assert len(ai_request_guard._LOCAL_SAVE_RATE[user.id]) == 1


def test_completed_new_save_survives_replay_cache_loss_without_duplicate_or_usage(
    monkeypatch,
) -> None:
    calls, generate = _fake_generation()
    monkeypatch.setattr(vault, "generate_ai_vault_summary", generate)
    db = _Db()
    user = _user()
    request_id = "cache-loss-new-save-key"
    payload = _payload()

    first = _call_save(payload, db, user, request_id)
    ai_request_guard._LOCAL_SAVE_RESULTS.clear()

    second = _call_save(payload, db, user, request_id)

    assert first.id == second.id
    assert len(db.records) == 1
    assert len(calls) == 1
    assert db.commits == 1
    assert user.monthly_chat_count == 1
    assert user.burst_chat_count == 1
    assert len(ai_request_guard._LOCAL_SAVE_RATE[user.id]) == 1


def test_cache_loss_retry_with_different_new_conversation_is_rejected(
    monkeypatch,
) -> None:
    calls, generate = _fake_generation()
    monkeypatch.setattr(vault, "generate_ai_vault_summary", generate)
    db = _Db()
    user = _user()
    request_id = "cache-loss-mismatch-key"

    _call_save(_payload(), db, user, request_id)
    ai_request_guard._LOCAL_SAVE_RESULTS.clear()

    with pytest.raises(HTTPException) as exc:
        _call_save(
            _payload(turns=[{"role": "user", "text": "Different symptom."}]),
            db,
            user,
            request_id,
        )

    assert exc.value.status_code == 409
    assert len(db.records) == 1
    assert len(calls) == 1
    assert user.monthly_chat_count == 1


def test_same_continuation_retry_does_not_regenerate_or_overwrite(monkeypatch) -> None:
    calls, generate = _fake_generation("Consolidated AB")
    monkeypatch.setattr(vault, "generate_ai_vault_summary", generate)
    source = _record()
    payload = _payload(source=source)
    db = _Db([source])
    user = _user()
    request_id = "stable-continuation-key"

    first = _call_save(payload, db, user, request_id)
    first_updated_at = source.updated_at
    second = _call_save(payload, db, user, request_id)

    assert first.id == second.id == source.id
    assert len(calls) == 1
    assert db.commits == 1
    assert source.updated_at == first_updated_at
    assert user.monthly_chat_count == 1


def test_same_idempotency_key_with_different_continuation_source_is_rejected(
    monkeypatch,
) -> None:
    calls, generate = _fake_generation("Consolidated AB")
    monkeypatch.setattr(vault, "generate_ai_vault_summary", generate)
    source_a = _record(text="Summary A")
    source_b = _record(text="Summary B")
    db = _Db([source_a, source_b])
    user = _user()
    request_id = "continuation-source-mismatch-key"

    _call_save(_payload(source=source_a), db, user, request_id)
    ai_request_guard._LOCAL_SAVE_RESULTS.clear()
    ai_request_guard._LOCAL_COMPLETED.clear()

    with pytest.raises(HTTPException) as exc:
        _call_save(_payload(source=source_b), db, user, request_id)

    assert exc.value.status_code == 409
    assert source_b.summary_text == "Summary B"
    assert len(calls) == 1
    assert user.monthly_chat_count == 1


def test_same_idempotency_key_with_different_continuation_version_is_rejected(
    monkeypatch,
) -> None:
    calls, generate = _fake_generation("Consolidated AB")
    monkeypatch.setattr(vault, "generate_ai_vault_summary", generate)
    source = _record()
    db = _Db([source])
    user = _user()
    request_id = "continuation-version-mismatch-key"
    payload = _payload(source=source)

    _call_save(payload, db, user, request_id)
    ai_request_guard._LOCAL_SAVE_RESULTS.clear()
    ai_request_guard._LOCAL_COMPLETED.clear()
    mismatched_payload = AISummarySaveRequest.model_validate(
        {
            "turns": [turn.model_dump() for turn in payload.turns],
            "source_summary_id": source.id,
            "source_updated_at": payload.source_updated_at + timedelta(seconds=5),
        }
    )

    with pytest.raises(HTTPException) as exc:
        _call_save(mismatched_payload, db, user, request_id)

    assert exc.value.status_code == 409
    assert len(calls) == 1
    assert user.monthly_chat_count == 1


def test_stale_version_rejected_before_generation(monkeypatch) -> None:
    calls, generate = _fake_generation()
    monkeypatch.setattr(vault, "generate_ai_vault_summary", generate)
    source = _record()
    payload = _payload(source=source)
    source.updated_at = source.updated_at + timedelta(minutes=1)

    with pytest.raises(HTTPException) as exc:
        _call_save(payload, _Db([source]), _user())

    assert exc.value.status_code == 409
    assert source.summary_text == "Summary A"
    assert calls == []


def test_stale_version_rejected_before_generation_consumes_no_usage(monkeypatch) -> None:
    calls, generate = _fake_generation()
    monkeypatch.setattr(vault, "generate_ai_vault_summary", generate)
    source = _record()
    payload = _payload(source=source)
    source.updated_at = source.updated_at + timedelta(minutes=1)
    user = _user()

    with pytest.raises(HTTPException) as exc:
        _call_save(payload, _Db([source]), user)

    assert exc.value.status_code == 409
    assert calls == []
    assert user.monthly_chat_count == 0
    assert user.burst_chat_count == 0


def test_atomic_race_does_not_overwrite_newer_summary(monkeypatch) -> None:
    calls, generate = _fake_generation("Stale generated text")
    monkeypatch.setattr(vault, "generate_ai_vault_summary", generate)
    source = _record(text="Newer summary")
    original_updated_at = source.updated_at
    db = _Db([source], force_stale_update=True)

    with pytest.raises(HTTPException) as exc:
        _call_save(_payload(source=source), db, _user())

    assert exc.value.status_code == 409
    assert source.summary_text == "Newer summary"
    assert source.updated_at == original_updated_at
    assert db.commits == 0
    assert db.rollbacks == 1
    assert len(calls) == 1


def test_atomic_race_stale_409_consumes_no_usage(monkeypatch) -> None:
    calls, generate = _fake_generation("Stale generated text")
    monkeypatch.setattr(vault, "generate_ai_vault_summary", generate)
    source = _record(text="Newer summary")
    db = _Db([source], force_stale_update=True)
    user = _user()

    with pytest.raises(HTTPException) as exc:
        _call_save(_payload(source=source), db, user)

    assert exc.value.status_code == 409
    assert len(calls) == 1
    assert user.monthly_chat_count == 0
    assert user.burst_chat_count == 0


def test_unusable_summary_does_not_create_or_overwrite(monkeypatch) -> None:
    async def fail_generation(*_args, **_kwargs):
        raise AISummaryGenerationError("unusable")

    monkeypatch.setattr(vault, "generate_ai_vault_summary", fail_generation)
    db = _Db()
    user = _user()
    with pytest.raises(HTTPException) as exc:
        _call_save(_payload(), db, user)
    assert exc.value.status_code == 503
    assert db.records == []
    assert db.commits == 0
    assert user.monthly_chat_count == 0
    assert user.burst_chat_count == 0


def test_failed_consolidation_leaves_existing_summary_unchanged(monkeypatch) -> None:
    async def fail_generation(*_args, **_kwargs):
        raise AISummaryGenerationError("provider failure")

    monkeypatch.setattr(vault, "generate_ai_vault_summary", fail_generation)
    source = _record()
    db = _Db([source])
    with pytest.raises(HTTPException) as exc:
        _call_save(_payload(source=source), db, _user())
    assert exc.value.status_code == 503
    assert source.summary_text == "Summary A"
    assert db.commits == 0


def test_persistence_failure_consumes_no_final_usage(monkeypatch) -> None:
    calls, generate = _fake_generation()
    monkeypatch.setattr(vault, "generate_ai_vault_summary", generate)
    db = _Db(fail_commit=True)
    user = _user()

    with pytest.raises(HTTPException) as exc:
        _call_save(_payload(), db, user)

    assert exc.value.status_code == 503
    assert len(calls) == 1
    assert db.rollbacks == 1
    assert user.monthly_chat_count == 0
    assert user.burst_chat_count == 0


def test_successful_persisted_new_save_consumes_exactly_one(monkeypatch) -> None:
    calls, generate = _fake_generation()
    monkeypatch.setattr(vault, "generate_ai_vault_summary", generate)
    db = _Db()
    user = _user()

    _call_save(_payload(), db, user)

    assert len(calls) == 1
    assert len(db.records) == 1
    assert user.monthly_chat_count == 1
    assert user.burst_chat_count == 1


def test_successful_persisted_continuation_consumes_exactly_one(monkeypatch) -> None:
    calls, generate = _fake_generation("Consolidated AB")
    monkeypatch.setattr(vault, "generate_ai_vault_summary", generate)
    source = _record()
    db = _Db([source])
    user = _user()

    _call_save(_payload(source=source), db, user)

    assert len(calls) == 1
    assert user.monthly_chat_count == 1
    assert user.burst_chat_count == 1


def test_free_save_is_rejected_before_generation_or_usage(monkeypatch) -> None:
    calls, generate = _fake_generation()
    monkeypatch.setattr(vault, "generate_ai_vault_summary", generate)
    user = _user(plan="free", monthly=0)
    db = _Db()
    with pytest.raises(HTTPException) as exc:
        _call_save(_payload(), db, user)
    assert exc.value.status_code == 403
    assert calls == []
    assert db.records == []
    assert db.commits == 0
    assert user.monthly_chat_count == 0
    assert user.burst_chat_count == 0


@pytest.mark.parametrize("plan", ["premium", "family"])
def test_paid_plans_can_save_ai_summaries(monkeypatch, plan) -> None:
    calls, generate = _fake_generation()
    monkeypatch.setattr(vault, "generate_ai_vault_summary", generate)
    user = _user(plan=plan)

    response = _call_save(_payload(), _Db(), user)

    assert response.details == "Generated bounded summary"
    assert len(calls) == 1
    assert user.monthly_chat_count == 1


def test_save_requires_active_ai_consent(monkeypatch) -> None:
    calls, generate = _fake_generation()
    monkeypatch.setattr(vault, "generate_ai_vault_summary", generate)
    user = _user()
    user.ai_consent_granted_at = None
    with pytest.raises(HTTPException) as exc:
        _call_save(_payload(), _Db(), user)
    assert exc.value.status_code == 403
    assert calls == []


def test_save_endpoint_rate_limit_applies_per_authenticated_user(monkeypatch) -> None:
    calls, generate = _fake_generation()
    monkeypatch.setattr(vault, "generate_ai_vault_summary", generate)
    user = _user(plan="premium")
    db = _Db()
    for index in range(3):
        _call_save(
            _payload(),
            db,
            user,
            f"rate-limit-key-{index}",
            ip=f"198.51.100.{index + 10}",
        )
    with pytest.raises(HTTPException) as exc:
        _call_save(
            _payload(),
            db,
            user,
            "rate-limit-key-4",
            ip="203.0.113.50",
        )
    assert exc.value.status_code == 429
    assert len(calls) == 3


def test_save_endpoint_ip_rate_limit_remains_enabled(monkeypatch) -> None:
    calls, generate = _fake_generation()
    monkeypatch.setattr(vault, "generate_ai_vault_summary", generate)
    for index in range(3):
        _call_save(
            _payload(),
            _Db(),
            _user(user_id=100 + index, plan="premium"),
            f"ip-rate-limit-key-{index}",
            decorated=True,
            ip="198.51.100.10",
        )
    with pytest.raises(RateLimitExceeded):
        _call_save(
            _payload(),
            _Db(),
            _user(user_id=200, plan="premium"),
            "ip-rate-limit-key-4",
            decorated=True,
            ip="198.51.100.10",
        )
    assert len(calls) == 3


class _FakeChat:
    def __init__(self, model):
        self.model = model

    async def send_message_async(self, prompt, generation_config):
        text = prompt[0]
        self.model.generated_prompts.append(text)
        if self.model.response_text is not None:
            response_text = self.model.response_text
        elif "conversation_segment" in text:
            response_text = "Segment facts preserved"
        else:
            response_text = "Final bounded continuity summary"
        return SimpleNamespace(
            text=response_text,
            candidates=[SimpleNamespace(finish_reason="STOP")],
        )


class _FakeModel:
    def __init__(self, *, token_divisor=4, response_text=None):
        self.token_divisor = token_divisor
        self.response_text = response_text
        self.generated_prompts = []

    async def count_tokens_async(self, contents):
        text = str(contents[0])
        return SimpleNamespace(total_tokens=max(1, len(text) // self.token_divisor))

    def start_chat(self, history):
        return _FakeChat(self)


def test_single_pass_summary_sends_every_turn_once(monkeypatch) -> None:
    model = _FakeModel(token_divisor=20)
    monkeypatch.setattr(ai_summary_service.ai_service, "GEMINI_API_KEY", "test")
    monkeypatch.setattr(ai_summary_service.ai_service, "heavy_model", model)
    turns = [
        SummaryTurn("user", "EARLY fact"),
        SummaryTurn("assistant", "MIDDLE advice"),
        SummaryTurn("user", "LATEST update"),
    ]

    result = asyncio.run(ai_summary_service.generate_ai_vault_summary(turns))

    assert result.generation_calls == 1
    assert len(model.generated_prompts) == 1
    assert "EARLY fact" in model.generated_prompts[0]
    assert "MIDDLE advice" in model.generated_prompts[0]
    assert "LATEST update" in model.generated_prompts[0]


def test_multi_chunk_summary_includes_every_turn_and_middle_fact(monkeypatch) -> None:
    model = _FakeModel(token_divisor=4)
    monkeypatch.setattr(ai_summary_service.ai_service, "GEMINI_API_KEY", "test")
    monkeypatch.setattr(ai_summary_service.ai_service, "heavy_model", model)
    turns = [
        SummaryTurn(
            "user" if index % 2 == 0 else "assistant",
            f"TURN_{index}_FACT " + ("detail " * 120),
        )
        for index in range(14)
    ]

    result = asyncio.run(ai_summary_service.generate_ai_vault_summary(turns))

    chunk_prompts = [
        prompt for prompt in model.generated_prompts if "conversation_segment" in prompt
    ]
    combined_chunks = "\n".join(chunk_prompts)
    assert result.chunk_count > 1
    assert result.generation_calls <= ai_summary_service.MAX_GENERATION_CALLS
    assert result.provider_calls <= ai_summary_service.MAX_GEMINI_CALLS
    for index in range(14):
        assert f"TURN_{index}_FACT" in combined_chunks
    assert "TURN_7_FACT" in combined_chunks
    assert "Compacted to bounded per-turn excerpts" not in combined_chunks


def test_excessive_chunk_count_is_rejected(monkeypatch) -> None:
    model = _FakeModel(token_divisor=1)
    monkeypatch.setattr(ai_summary_service.ai_service, "GEMINI_API_KEY", "test")
    monkeypatch.setattr(ai_summary_service.ai_service, "heavy_model", model)
    turns = [SummaryTurn("user", "x" * 1_900) for _ in range(5)]

    with pytest.raises(AISummaryInputError, match="too many chunks"):
        asyncio.run(ai_summary_service.generate_ai_vault_summary(turns))
    assert model.generated_prompts == []


def test_final_summary_output_is_bounded_without_chopping(monkeypatch) -> None:
    model = _FakeModel(
        token_divisor=20,
        response_text="x" * (ai_summary_service.MAX_FINAL_SUMMARY_CHARS + 1),
    )
    monkeypatch.setattr(ai_summary_service.ai_service, "GEMINI_API_KEY", "test")
    monkeypatch.setattr(ai_summary_service.ai_service, "heavy_model", model)

    with pytest.raises(AISummaryGenerationError, match="unusable"):
        asyncio.run(
            ai_summary_service.generate_ai_vault_summary(
                [SummaryTurn("user", "headache")]
            )
        )


def test_empty_model_output_is_rejected(monkeypatch) -> None:
    model = _FakeModel(token_divisor=20, response_text="")
    monkeypatch.setattr(ai_summary_service.ai_service, "GEMINI_API_KEY", "test")
    monkeypatch.setattr(ai_summary_service.ai_service, "heavy_model", model)

    with pytest.raises(AISummaryGenerationError, match="unusable"):
        asyncio.run(
            ai_summary_service.generate_ai_vault_summary(
                [SummaryTurn("user", "headache")]
            )
        )


def test_intermediate_chunk_summaries_are_not_persisted(monkeypatch) -> None:
    model = _FakeModel(token_divisor=4)
    monkeypatch.setattr(ai_summary_service.ai_service, "GEMINI_API_KEY", "test")
    monkeypatch.setattr(ai_summary_service.ai_service, "heavy_model", model)
    turns = [
        {
            "role": "user" if index % 2 == 0 else "assistant",
            "text": f"TURN_{index}_FACT " + ("detail " * 120),
        }
        for index in range(14)
    ]
    db = _Db()

    response = _call_save(_payload(turns=turns), db, _user())

    assert response.details == "Final bounded continuity summary"
    assert len(db.records) == 1
    assert db.records[0].summary_text == "Final bounded continuity summary"
    assert "Segment facts preserved" not in db.records[0].summary_text
    assert not hasattr(db.records[0], "turns")


def test_loading_continuation_without_save_does_not_mutate_source() -> None:
    source = _record()
    db = _Db([source])
    loaded = vault._owned_summary(db, source.id, source.patient_id)
    assert loaded is source
    assert source.summary_text == "Summary A"
    assert db.commits == 0


def test_ai_summary_export_labels_creation_and_latest_update_separately() -> None:
    record = _record(text="Exported summary")
    record.created_at = datetime(2025, 1, 2, 3, 4, tzinfo=timezone.utc)
    record.updated_at = datetime(2026, 2, 3, 4, 5, tzinfo=timezone.utc)
    response = export_vault_records(
        request=_request(),
        payload=VaultExportRequest(record_ids=[record.id]),
        db=_ExportDb([record]),
        current_user=SimpleNamespace(id=record.patient_id, plan="free"),
    )

    async def _read_stream() -> bytes:
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        return b"".join(chunks)

    pdf_text = "\n".join(
        page.extract_text() or ""
        for page in PdfReader(io.BytesIO(asyncio.run(_read_stream()))).pages
    )
    assert "Created: 02 Jan 2025, 03:04 UTC" in pdf_text
    assert "Last updated: 03 Feb 2026, 04:05 UTC" in pdf_text


def test_downgraded_free_user_can_still_view_and_delete_owned_summary() -> None:
    record = _record(text="Previously saved summary")
    user = SimpleNamespace(id=record.patient_id, plan="free")
    view_db = _Db([record])

    loaded = vault._owned_summary(view_db, record.id, user.id)

    assert loaded is record
    assert vault._summary_response(loaded).details == "Previously saved summary"

    delete_db = _Db([record])
    response = delete_ai_summary(record.id, db=delete_db, current_user=user)

    assert response["detail"] == "Summary deleted successfully."
    assert delete_db.records == []
    assert delete_db.commits == 1
