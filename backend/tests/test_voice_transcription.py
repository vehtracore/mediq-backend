import asyncio
import io
import threading
import wave
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Header, HTTPException, UploadFile
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import Headers

import app.models.appointment  # noqa: F401 - resolves ORM relationships
import app.models.consultation_payout  # noqa: F401 - resolves ORM relationships
import app.models.doctor  # noqa: F401 - resolves ORM relationships
import app.models.review  # noqa: F401 - resolves ORM relationships
from app.api.v1 import chat, voice
from app.api import deps
from app.core.database import Base, get_db
from app.core.limiter import limiter
from app.models.stt_usage_reservation import STTUsageReservation
from app.models.user import User
from app.services import ai_service, stt_request_guard
from app.services.ai_request_guard import AIRequestLease
from app.services.stt_request_guard import (
    acquire_stt_request_lease,
    enforce_stt_user_rate_limit,
    release_stt_request_lease,
    stt_request_digest,
)
from app.services.stt_usage import (
    FAMILY_MONTHLY_STT_LIMIT,
    FREE_MONTHLY_STT_LIMIT,
    PREMIUM_MONTHLY_STT_LIMIT,
    STT_CONSUMED,
    STT_RELEASED,
    STT_RESERVATION_TTL,
    STTAllowanceReservation,
    finalize_stt_allowance,
    reserve_stt_allowance,
)
from app.services.voice_transcription import (
    MAX_STT_AUDIO_BYTES,
    VOICE_INPUT_CAPABILITIES,
    ValidatedVoiceAudio,
    require_voice_input_capability,
    transcribe_voice_audio,
    validate_voice_audio_bytes,
)


def _wav_bytes(*, seconds: float = 1.0, sample_rate: int = 8_000) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(1)
        audio.setframerate(sample_rate)
        audio.writeframes(b"\x80" * int(seconds * sample_rate))
    return output.getvalue()


def _upload(data: bytes | None = None) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(data if data is not None else _wav_bytes()),
        filename="fixture.wav",
        headers=Headers({"content-type": "audio/wav"}),
    )


def _user(user_id: int = 701):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return SimpleNamespace(
        id=user_id,
        plan="free",
        subscription_expiry=None,
        ai_consent_granted_at=now,
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
        monthly_stt_count=0,
        last_stt_month_reset=date.today(),
        dob=None,
        chronic_conditions=None,
    )


class _Db:
    def __init__(self, user=None):
        self.user = user
        self.commits = 0
        self.rollbacks = 0

    def add(self, _value):
        return None

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def query(self, _model):
        user = self.user

        class _Query:
            def filter(self, *_criteria):
                return self

            def with_for_update(self):
                return self

            def first(self):
                return user

        return _Query()


@pytest.fixture
def stt_session_factory(tmp_path):
    database_path = (tmp_path / "stt-usage.sqlite3").as_posix()
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(
        engine,
        tables=[User.__table__, STTUsageReservation.__table__],
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


def _add_quota_user(
    db,
    *,
    user_id: int,
    plan: str = "free",
    monthly_stt_count: int = 0,
    month_start: date | None = None,
) -> User:
    user = User(
        id=user_id,
        email=f"stt-{user_id}@test.local",
        hashed_password="test",
        plan=plan,
        monthly_stt_count=monthly_stt_count,
        last_stt_month_reset=month_start or date(2026, 9, 1),
    )
    db.add(user)
    db.commit()
    return user


def _monthly_stt_count(db, user_id: int) -> int:
    db.expire_all()
    return db.query(User).filter(User.id == user_id).one().monthly_stt_count


@pytest.fixture(autouse=True)
def _reset_stt_guards(monkeypatch):
    monkeypatch.setattr(stt_request_guard, "get_redis_client", None)
    stt_request_guard._LOCAL_INFLIGHT.clear()
    stt_request_guard._LOCAL_RATE.clear()
    stt_request_guard._LOCAL_COMPLETED.clear()
    limiter.reset()
    yield
    limiter.reset()


def test_generated_wav_fixture_is_validated_without_persistence() -> None:
    validated = validate_voice_audio_bytes(
        _wav_bytes(seconds=1.25),
        filename="fixture.wav",
        content_type="audio/wav",
    )
    assert validated.filename == "mdq_voice.wav"
    assert validated.content_type == "audio/wav"
    assert validated.duration_seconds == pytest.approx(1.25, abs=0.01)


@pytest.mark.parametrize(
    ("data", "filename", "content_type", "status_code"),
    [
        (b"", "empty.wav", "audio/wav", 400),
        (b"not audio", "fake.wav", "audio/wav", 400),
        (_wav_bytes(), "fixture.wav", "audio/mpeg", 400),
        (b"0" * (MAX_STT_AUDIO_BYTES + 1), "large.wav", "audio/wav", 413),
    ],
    ids=["empty", "malformed", "unsupported-mime", "oversized"],
)
def test_invalid_empty_unsupported_and_oversized_audio_are_rejected(
    data, filename, content_type, status_code
) -> None:
    with pytest.raises(HTTPException) as exc:
        validate_voice_audio_bytes(
            data,
            filename=filename,
            content_type=content_type,
        )
    assert exc.value.status_code == status_code


def test_audio_over_90_seconds_is_rejected() -> None:
    with pytest.raises(HTTPException) as exc:
        validate_voice_audio_bytes(
            _wav_bytes(seconds=91),
            filename="long.wav",
            content_type="audio/wav",
        )
    assert exc.value.status_code == 400
    assert "90 seconds" in exc.value.detail


@pytest.mark.parametrize("language", ["yoruba", "hausa", "igbo", "unknown"])
def test_native_and_unknown_languages_are_rejected_before_provider(language) -> None:
    with pytest.raises(HTTPException) as exc:
        require_voice_input_capability(language)
    assert exc.value.status_code == 400
    assert "still type" in exc.value.detail


def test_english_and_pidgin_provider_hints_preserve_spoken_language(monkeypatch) -> None:
    calls = []

    class _Transcriptions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(text="No be malaria I talk")

    class _Client:
        audio = SimpleNamespace(transcriptions=_Transcriptions())

        async def close(self):
            return None

    fake_client = _Client()
    from app.services import voice_transcription

    monkeypatch.setattr(voice_transcription, "_stt_client", lambda: fake_client)
    audio = ValidatedVoiceAudio(
        data=_wav_bytes(),
        filename="mdq_voice.wav",
        content_type="audio/wav",
        duration_seconds=1,
    )

    english = asyncio.run(
        transcribe_voice_audio(audio, VOICE_INPUT_CAPABILITIES["english"])
    )
    pidgin = asyncio.run(
        transcribe_voice_audio(audio, VOICE_INPUT_CAPABILITIES["pidgin"])
    )

    assert english == "No be malaria I talk"
    assert pidgin == "No be malaria I talk"
    assert calls[0]["language"] == "en"
    assert "Do not summarize" in calls[0]["prompt"]
    assert "language" not in calls[1]
    assert VOICE_INPUT_CAPABILITIES["pidgin"].provider_language is None
    assert "Nigerian Pidgin" in calls[1]["prompt"]
    assert "No translate" in calls[1]["prompt"]
    assert "no polish" in calls[1]["prompt"]
    assert "negation" in calls[1]["prompt"]
    assert "medicine names" in calls[1]["prompt"]
    assert "dose" in calls[1]["prompt"]
    assert len(calls) == 2


def test_unsupported_language_never_reads_audio_or_calls_provider(monkeypatch) -> None:
    reads = []
    provider_calls = []
    user = _user()

    async def _read(_file):
        reads.append(True)

    async def _provider(*_args, **_kwargs):
        provider_calls.append(True)

    monkeypatch.setattr(voice, "read_validated_voice_upload", _read)
    monkeypatch.setattr(voice, "transcribe_voice_audio", _provider)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            voice._transcribe_uploaded_voice(
                file=_upload(),
                language="yoruba",
                request_identifier="request-native-1",
                db=_Db(),
                current_user=user,
            )
        )
    assert exc.value.status_code == 400
    assert reads == []
    assert provider_calls == []
    assert user.monthly_stt_count == 0


@pytest.mark.parametrize(
    ("data", "expected_status"),
    [
        (b"not audio", 400),
        (b"0" * (MAX_STT_AUDIO_BYTES + 1), 413),
        (_wav_bytes(seconds=91), 400),
    ],
    ids=["malformed", "oversized", "over-duration"],
)
def test_invalid_audio_never_calls_provider(
    monkeypatch, data, expected_status
) -> None:
    provider_calls = []
    user = _user(707)

    async def _provider(*_args, **_kwargs):
        provider_calls.append(True)

    monkeypatch.setattr(voice, "transcribe_voice_audio", _provider)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            voice._transcribe_uploaded_voice(
                file=_upload(data),
                language="english",
                request_identifier="request-invalid-1",
                db=_Db(),
                current_user=user,
            )
        )
    assert exc.value.status_code == expected_status
    assert provider_calls == []
    assert user.monthly_stt_count == 0


def test_active_consent_and_chat_eligibility_are_required_before_stt(monkeypatch) -> None:
    provider_calls = []

    async def _provider(*_args, **_kwargs):
        provider_calls.append(True)
        return "unused"

    monkeypatch.setattr(voice, "transcribe_voice_audio", _provider)
    no_consent = _user(702)
    no_consent.ai_consent_granted_at = None
    with pytest.raises(HTTPException) as consent_exc:
        asyncio.run(
            voice._transcribe_uploaded_voice(
                file=_upload(),
                language="english",
                request_identifier="request-consent-1",
                db=_Db(),
                current_user=no_consent,
            )
        )
    assert consent_exc.value.status_code == 403

    no_entitlement = _user(703)
    no_entitlement.monthly_chat_count = 12
    with pytest.raises(HTTPException) as entitlement_exc:
        asyncio.run(
            voice._transcribe_uploaded_voice(
                file=_upload(),
                language="english",
                request_identifier="request-entitlement-1",
                db=_Db(),
                current_user=no_entitlement,
            )
        )
    assert entitlement_exc.value.status_code == 429
    assert provider_calls == []
    assert no_consent.monthly_stt_count == 0
    assert no_entitlement.monthly_stt_count == 0


def _digest(request_id: str) -> str:
    digest = stt_request_digest(request_id)
    assert digest is not None
    return digest


def _reserve(db, user_id: int, request_id: str, now: datetime):
    return reserve_stt_allowance(
        db,
        user_id=user_id,
        request_digest=_digest(request_id),
        now=now,
    )


def _consume(db, reservation, now: datetime):
    return finalize_stt_allowance(
        db,
        reservation,
        usable_transcript=True,
        now=now,
    )


def test_stt_success_does_not_increment_normal_ai_message_quota(
    monkeypatch, stt_session_factory
) -> None:
    async def _provider(_audio, _capability, *, before_submit):
        before_submit()
        return "faithful transcript"

    monkeypatch.setattr(voice, "transcribe_voice_audio", _provider)
    current_user = _user(704)
    before = (current_user.monthly_chat_count, current_user.burst_chat_count)
    with stt_session_factory() as db:
        _add_quota_user(db, user_id=current_user.id)
        result = asyncio.run(
            voice._transcribe_uploaded_voice(
                file=_upload(),
                language="english",
                request_identifier="request-success-1",
                db=db,
                current_user=current_user,
            )
        )
        assert _monthly_stt_count(db, current_user.id) == 1

    assert result.transcript == "faithful transcript"
    assert (current_user.monthly_chat_count, current_user.burst_chat_count) == before


def test_free_fourth_stt_succeeds_and_fifth_is_blocked(stt_session_factory) -> None:
    now = datetime(2026, 9, 6, 12, 0)
    with stt_session_factory() as db:
        user = _add_quota_user(db, user_id=720)
        for expected_used in range(1, FREE_MONTHLY_STT_LIMIT + 1):
            reservation = _reserve(db, user.id, f"free-{expected_used}", now)
            assert reservation.used == expected_used
            assert _consume(db, reservation, now).status == STT_CONSUMED

        with pytest.raises(HTTPException) as exc:
            _reserve(db, user.id, "free-fifth", now)
        assert exc.value.status_code == 429
        assert "still type" in exc.value.detail
        assert _monthly_stt_count(db, user.id) == 4


@pytest.mark.parametrize(("plan", "limit"), [("premium", 40), ("family", 30)])
def test_paid_plan_final_stt_succeeds_and_next_is_blocked(
    stt_session_factory, plan, limit
) -> None:
    assert {
        "premium": PREMIUM_MONTHLY_STT_LIMIT,
        "family": FAMILY_MONTHLY_STT_LIMIT,
    }[plan] == limit
    now = datetime(2026, 9, 6, 12, 0)
    with stt_session_factory() as db:
        user = _add_quota_user(
            db,
            user_id=721 if plan == "premium" else 722,
            plan=plan,
            monthly_stt_count=limit - 1,
        )
        reservation = _reserve(db, user.id, f"{plan}-final", now)
        assert reservation.used == limit
        _consume(db, reservation, now)
        with pytest.raises(HTTPException) as exc:
            _reserve(db, user.id, f"{plan}-blocked", now)
        assert exc.value.status_code == 429
        assert _monthly_stt_count(db, user.id) == limit


def test_family_stt_allowance_is_per_member(stt_session_factory) -> None:
    now = datetime(2026, 9, 6, 12, 0)
    with stt_session_factory() as db:
        members = [
            _add_quota_user(
                db,
                user_id=user_id,
                plan="family",
                monthly_stt_count=FAMILY_MONTHLY_STT_LIMIT - 1,
            )
            for user_id in (723, 724)
        ]
        for member in members:
            reservation = _reserve(db, member.id, f"member-{member.id}", now)
            _consume(db, reservation, now)
        assert [_monthly_stt_count(db, member.id) for member in members] == [
            FAMILY_MONTHLY_STT_LIMIT,
            FAMILY_MONTHLY_STT_LIMIT,
        ]


def test_stt_allowance_resets_lazily_on_calendar_month_change(
    stt_session_factory,
) -> None:
    with stt_session_factory() as db:
        user = _add_quota_user(
            db,
            user_id=725,
            monthly_stt_count=FREE_MONTHLY_STT_LIMIT,
            month_start=date(2026, 8, 1),
        )
        reservation = _reserve(
            db,
            user.id,
            "september-first",
            datetime(2026, 9, 1, 0, 0),
        )
        _consume(db, reservation, datetime(2026, 9, 1, 0, 0))
        db.expire_all()
        refreshed = db.query(User).filter(User.id == user.id).one()
        assert refreshed.monthly_stt_count == 1
        assert refreshed.last_stt_month_reset == date(2026, 9, 1)


def test_no_database_transaction_is_held_during_openai_call(
    monkeypatch, stt_session_factory
) -> None:
    observed_transactions = []
    with stt_session_factory() as db:
        current_user = _user(726)
        _add_quota_user(db, user_id=current_user.id)

        class _Transcriptions:
            async def create(self, **_kwargs):
                observed_transactions.append(db.in_transaction())
                return SimpleNamespace(text="usable transcript")

        class _Client:
            audio = SimpleNamespace(transcriptions=_Transcriptions())

            async def close(self):
                return None

        from app.services import voice_transcription

        monkeypatch.setattr(voice_transcription, "_stt_client", _Client)
        result = asyncio.run(
            voice._transcribe_uploaded_voice(
                file=_upload(),
                language="english",
                request_identifier="request-no-open-transaction",
                db=db,
                current_user=current_user,
            )
        )

    assert result.transcript == "usable transcript"
    assert observed_transactions == [False]


def test_concurrent_final_slot_requests_cannot_exceed_quota(
    stt_session_factory,
) -> None:
    now = datetime(2026, 9, 6, 12, 0)
    with stt_session_factory() as setup_db:
        user = _add_quota_user(
            setup_db,
            user_id=727,
            monthly_stt_count=FREE_MONTHLY_STT_LIMIT - 1,
        )
        user_id = user.id

    barrier = threading.Barrier(2)
    outcomes = []
    reservations = []

    def _attempt(index: int) -> None:
        with stt_session_factory() as db:
            barrier.wait()
            try:
                reservation = _reserve(db, user_id, f"concurrent-{index}", now)
                reservations.append(reservation)
                outcomes.append("reserved")
            except HTTPException as exc:
                outcomes.append(f"blocked-{exc.status_code}")

    threads = [threading.Thread(target=_attempt, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["blocked-429", "reserved"]
    with stt_session_factory() as db:
        assert _monthly_stt_count(db, user_id) == 4
        finalize_stt_allowance(
            db,
            reservations[0],
            usable_transcript=False,
            now=now,
        )


def test_failed_provider_call_refunds_exactly_once(
    monkeypatch, stt_session_factory
) -> None:
    with stt_session_factory() as db:
        current_user = _user(728)
        _add_quota_user(db, user_id=current_user.id)

        class _Transcriptions:
            async def create(self, **_kwargs):
                raise TimeoutError("provider timeout")

        class _Client:
            audio = SimpleNamespace(transcriptions=_Transcriptions())

            async def close(self):
                return None

        from app.services import voice_transcription

        monkeypatch.setattr(voice_transcription, "_stt_client", _Client)
        request_id = "request-provider-refund"
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                voice._transcribe_uploaded_voice(
                    file=_upload(),
                    language="english",
                    request_identifier=request_id,
                    db=db,
                    current_user=current_user,
                )
            )
        assert exc.value.status_code == 502
        ledger = db.query(STTUsageReservation).one()
        assert ledger.status == STT_RELEASED
        assert _monthly_stt_count(db, current_user.id) == 0

        reservation = STTAllowanceReservation(
            user_id=current_user.id,
            request_digest=_digest(request_id),
            plan="free",
            used=1,
            limit=4,
            month_start=date(2026, 9, 1),
        )
        second = finalize_stt_allowance(
            db,
            reservation,
            usable_transcript=False,
            now=datetime(2026, 9, 6, 12, 1),
        )
        assert second.changed is False
        assert _monthly_stt_count(db, current_user.id) == 0


def test_empty_provider_transcript_refunds_exactly_once(
    monkeypatch, stt_session_factory
) -> None:
    with stt_session_factory() as db:
        current_user = _user(729)
        _add_quota_user(db, user_id=current_user.id)

        class _Transcriptions:
            async def create(self, **_kwargs):
                return SimpleNamespace(text="   ")

        class _Client:
            audio = SimpleNamespace(transcriptions=_Transcriptions())

            async def close(self):
                return None

        from app.services import voice_transcription

        monkeypatch.setattr(voice_transcription, "_stt_client", _Client)
        request_id = "request-empty-refund"
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                voice._transcribe_uploaded_voice(
                    file=_upload(),
                    language="english",
                    request_identifier=request_id,
                    db=db,
                    current_user=current_user,
                )
            )
        assert exc.value.status_code == 422
        ledger = db.query(STTUsageReservation).one()
        assert ledger.status == STT_RELEASED
        assert _monthly_stt_count(db, current_user.id) == 0

        reservation = STTAllowanceReservation(
            user_id=current_user.id,
            request_digest=_digest(request_id),
            plan="free",
            used=1,
            limit=4,
            month_start=date(2026, 9, 1),
        )
        assert finalize_stt_allowance(
            db,
            reservation,
            usable_transcript=False,
            now=datetime(2026, 9, 6, 12, 1),
        ).changed is False
        assert _monthly_stt_count(db, current_user.id) == 0


def test_duplicate_request_id_cannot_consume_twice(stt_session_factory) -> None:
    now = datetime(2026, 9, 6, 12, 0)
    with stt_session_factory() as db:
        user = _add_quota_user(db, user_id=730)
        first = _reserve(db, user.id, "same-request-id", now)
        with pytest.raises(HTTPException) as exc:
            _reserve(db, user.id, "same-request-id", now)
        assert exc.value.status_code == 409
        assert _monthly_stt_count(db, user.id) == 1
        assert db.query(STTUsageReservation).count() == 1
        _consume(db, first, now)


def test_refund_cannot_push_monthly_count_below_zero(stt_session_factory) -> None:
    now = datetime(2026, 9, 6, 12, 0)
    request_id = "defensive-zero-refund"
    with stt_session_factory() as db:
        user = _add_quota_user(db, user_id=731, monthly_stt_count=0)
        db.add(
            STTUsageReservation(
                user_id=user.id,
                request_digest=_digest(request_id),
                month_start=date(2026, 9, 1),
                status="reserved",
                created_at=now,
                expires_at=now + STT_RESERVATION_TTL,
            )
        )
        db.commit()
        reservation = STTAllowanceReservation(
            user_id=user.id,
            request_digest=_digest(request_id),
            plan="free",
            used=0,
            limit=4,
            month_start=date(2026, 9, 1),
        )
        first = finalize_stt_allowance(
            db,
            reservation,
            usable_transcript=False,
            now=now,
        )
        second = finalize_stt_allowance(
            db,
            reservation,
            usable_transcript=False,
            now=now,
        )
        assert first.changed is True
        assert second.changed is False
        assert _monthly_stt_count(db, user.id) == 0


def test_stale_process_interruption_is_recovered_deterministically(
    stt_session_factory,
) -> None:
    started = datetime(2026, 9, 6, 12, 0)
    recovered_at = started + STT_RESERVATION_TTL + timedelta(seconds=1)
    with stt_session_factory() as db:
        user = _add_quota_user(db, user_id=732)
        abandoned = _reserve(db, user.id, "abandoned-process", started)
        assert abandoned.used == 1
        replacement = _reserve(db, user.id, "replacement-request", recovered_at)
        assert replacement.used == 1
        ledgers = {
            row.request_digest: row.status
            for row in db.query(STTUsageReservation).all()
        }
        assert ledgers[_digest("abandoned-process")] == STT_RELEASED
        assert ledgers[_digest("replacement-request")] == "reserved"
        assert _monthly_stt_count(db, user.id) == 1
        finalize_stt_allowance(
            db,
            replacement,
            usable_transcript=False,
            now=recovered_at,
        )


def test_transcription_then_normal_send_use_separate_counters(
    monkeypatch, stt_session_factory
) -> None:
    async def _stt_provider(_audio, _capability, *, before_submit):
        before_submit()
        return "I get headache"

    async def _chat_provider(*_args, **_kwargs):
        return ai_service.MedicalAIResponse("Safe response")

    monkeypatch.setattr(voice, "transcribe_voice_audio", _stt_provider)
    monkeypatch.setattr(ai_service, "get_medical_response", _chat_provider)
    current_user = _user(733)
    with stt_session_factory() as db:
        _add_quota_user(db, user_id=current_user.id)
        asyncio.run(
            voice._transcribe_uploaded_voice(
                file=_upload(),
                language="english",
                request_identifier="request-before-normal-send",
                db=db,
                current_user=current_user,
            )
        )
        assert _monthly_stt_count(db, current_user.id) == 1
    assert current_user.monthly_chat_count == 0

    asyncio.run(
        chat._analyze_chat_request(
            request=SimpleNamespace(),
            chat_request=chat.ChatRequest(message="I get headache"),
            db=_Db(),
            current_user=current_user,
            request_lease=AIRequestLease(current_user.id, "owner", "chat-request"),
        )
    )
    assert current_user.monthly_chat_count == 1
    assert current_user.burst_chat_count == 1


def test_one_transcription_in_flight_per_user() -> None:
    first = acquire_stt_request_lease(705, "request-inflight-1")
    try:
        with pytest.raises(HTTPException) as exc:
            acquire_stt_request_lease(705, "request-inflight-2")
        assert exc.value.status_code == 409
    finally:
        release_stt_request_lease(first)


def test_per_user_transcription_rate_limit_is_ten_per_hour() -> None:
    for _ in range(10):
        enforce_stt_user_rate_limit(706)
    with pytest.raises(HTTPException) as exc:
        enforce_stt_user_rate_limit(706)
    assert exc.value.status_code == 429


def test_provider_failure_is_not_retried_automatically(monkeypatch) -> None:
    calls = []

    class _Transcriptions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            raise TimeoutError("timeout")

    class _Client:
        audio = SimpleNamespace(transcriptions=_Transcriptions())

        async def close(self):
            return None

    fake_client = _Client()
    from app.services import voice_transcription

    monkeypatch.setattr(voice_transcription, "_stt_client", lambda: fake_client)
    audio = ValidatedVoiceAudio(
        data=_wav_bytes(),
        filename="mdq_voice.wav",
        content_type="audio/wav",
        duration_seconds=1,
    )

    with pytest.raises(TimeoutError):
        asyncio.run(
            transcribe_voice_audio(audio, VOICE_INPUT_CAPABILITIES["english"])
        )
    assert len(calls) == 1


@pytest.mark.parametrize("provider_fails", [False, True])
def test_route_closes_spooled_upload_on_success_and_failure(
    monkeypatch, provider_fails, stt_session_factory
) -> None:
    async def _provider(_audio, _capability, *, before_submit):
        before_submit()
        if provider_fails:
            raise RuntimeError("provider unavailable")
        return "transcript"

    monkeypatch.setattr(voice, "transcribe_voice_audio", _provider)
    upload = _upload()
    call = voice.transcribe.__wrapped__
    user = _user(708 if provider_fails else 709)
    with stt_session_factory() as db:
        _add_quota_user(db, user_id=user.id)
        if provider_fails:
            with pytest.raises(HTTPException) as exc:
                asyncio.run(
                    call(
                        request=SimpleNamespace(),
                        file=upload,
                        language="english",
                        request_identifier="request-close-failure",
                        db=db,
                        current_user=user,
                    )
                )
            assert exc.value.status_code == 502
        else:
            result = asyncio.run(
                call(
                    request=SimpleNamespace(),
                    file=upload,
                    language="english",
                    request_identifier="request-close-success",
                    db=db,
                    current_user=user,
                )
            )
            assert result.transcript == "transcript"
        assert upload.file.closed
        assert _monthly_stt_count(db, user.id) == (0 if provider_fails else 1)


def test_transcribe_route_requires_authentication() -> None:
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(voice.router, prefix="/voice")

    with TestClient(app) as client:
        response = client.post(
            "/voice/transcribe",
            data={
                "language": "english",
                "request_identifier": "request-unauthenticated",
            },
            files={"file": ("fixture.wav", _wav_bytes(), "audio/wav")},
        )
    assert response.status_code == 401


def test_transcribe_route_has_secondary_per_ip_rate_limit(
    monkeypatch, stt_session_factory
) -> None:
    async def _provider(_audio, _capability, *, before_submit):
        before_submit()
        return "transcript"

    monkeypatch.setattr(voice, "transcribe_voice_audio", _provider)
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(voice.router, prefix="/voice")

    def _current_user(x_test_user: int = Header(...)):
        return _user(x_test_user)

    def _db(x_test_user: int = Header(...)):
        with stt_session_factory() as db:
            yield db

    with stt_session_factory() as db:
        for index in range(11):
            _add_quota_user(db, user_id=800 + index)

    app.dependency_overrides[deps.get_current_user] = _current_user
    app.dependency_overrides[get_db] = _db

    with TestClient(app) as client:
        responses = [
            client.post(
                "/voice/transcribe",
                headers={"X-Test-User": str(800 + index)},
                data={
                    "language": "english",
                    "request_identifier": f"request-ip-limit-{index}",
                },
                files={"file": ("fixture.wav", _wav_bytes(), "audio/wav")},
            )
            for index in range(11)
        ]

    assert [response.status_code for response in responses[:10]] == [200] * 10
    assert responses[10].status_code == 429


def test_existing_tts_routing_map_is_unchanged() -> None:
    assert voice._YARNGPT_VOICES == {
        "igbo": "Chinenye",
        "hausa": "Zainab",
        "yoruba": "Remi",
        "pidgin": "Osagie",
        "nigerian pidgin": "Osagie",
    }
    assert "english" not in voice._YARNGPT_VOICES
