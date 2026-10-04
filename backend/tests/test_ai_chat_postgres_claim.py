"""Distributed chat claims against an isolated local PostgreSQL schema."""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models.doctor  # noqa: F401 - resolves Vault ORM relationships
from app.api.v1.chat import ChatRequest, _chat_fingerprint, _get_chat_receipt, _run_chat_operation
from app.services.ai_interaction import InteractionMode, InteractionResponse, MessageResult, ResultKind
from app.models.ai_chat_receipt import AIChatRequestReceipt
from app.services.ai_chat_operation import (
    acquire_chat_operation, chat_operation_status, finish_chat_operation,
    require_chat_operation_owner, start_chat_operation,
)
from app.services.ai_request_guard import ai_request_digest
from tests.test_ai_chat_quality import _user


@pytest.fixture
def pg_sessions():
    url = os.getenv("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set TEST_POSTGRES_URL to a disposable local PostgreSQL instance")
    admin = create_engine(url)
    if admin.url.host not in {"localhost", "127.0.0.1", "::1"}:
        admin.dispose()
        pytest.skip("Distributed claim tests may only use local PostgreSQL")
    schema = f"ai_claim_test_{uuid.uuid4().hex}"
    with admin.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    engines = []

    def session():
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
        engines.append(engine)
        return sessionmaker(bind=engine)()

    setup = session()
    try:
        setup.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, monthly_chat_count INTEGER NOT NULL DEFAULT 0)"))
        setup.execute(text("INSERT INTO users (id) VALUES (7)"))
        setup.commit()
        claim_migration = Path(__file__).resolve().parents[1] / "migrations" / "add_ai_chat_claims.sql"
        with setup.bind.begin() as connection:
            connection.exec_driver_sql(claim_migration.read_text(encoding="utf-8"))
        AIChatRequestReceipt.__table__.create(bind=setup.bind)
    finally:
        setup.close()
    try:
        yield session
    finally:
        for engine in engines:
            engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


def test_separate_connections_claim_only_once_and_conflict_on_changed_payload(pg_sessions):
    barrier = Barrier(2)

    def attempt():
        db = pg_sessions()
        try:
            barrier.wait(timeout=5)
            return acquire_chat_operation(db, 7, "request-123", "hash-a").disposition
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(outcomes) == ["active", "started"]
    db = pg_sessions()
    try:
        with pytest.raises(HTTPException) as mismatch:
            acquire_chat_operation(db, 7, "request-123", "hash-b")
        assert mismatch.value.status_code == 409
        db.rollback()
        with pytest.raises(HTTPException) as busy:
            acquire_chat_operation(db, 7, "request-456", "hash-c")
        assert busy.value.code == "ai_operation_active"
    finally:
        db.close()


def test_expired_claim_cannot_be_stolen_while_original_worker_holds_lock(pg_sessions):
    first = pg_sessions()
    second = pg_sessions()
    updater = pg_sessions()
    try:
        operation = acquire_chat_operation(first, 7, "request-123", "hash-a")
        assert start_chat_operation(first, operation)
        updater.execute(text("UPDATE ai_chat_claims SET lease_expires_at = now() - interval '1 second'"))
        updater.commit()

        assert acquire_chat_operation(second, 7, "request-123", "hash-a").disposition == "active"
        assert chat_operation_status(second, 7, "request-123") == {"status": "processing"}
        with pytest.raises(HTTPException) as busy:
            acquire_chat_operation(second, 7, "request-456", "hash-c")
        assert busy.value.code == "ai_operation_active"

        first.close()  # Worker death rolls back the transaction-scoped lock.
        assert chat_operation_status(second, 7, "request-123")["status"] == "failed"
        replacement = acquire_chat_operation(second, 7, "request-123", "hash-a")
        assert replacement.disposition == "started"
        assert replacement.owner != operation.owner
        assert start_chat_operation(second, replacement)
        finish_chat_operation(second, replacement, succeeded=False)
        assert acquire_chat_operation(second, 7, "request-123", "hash-a").disposition == "started"
    finally:
        first.close()
        second.close()
        updater.close()


def test_takeover_before_original_worker_starts_fences_old_owner(pg_sessions):
    first = pg_sessions()
    second = pg_sessions()
    try:
        original = acquire_chat_operation(first, 7, "request-123", "hash-a")
        first.execute(text("UPDATE ai_chat_claims SET lease_expires_at = now() - interval '1 second'"))
        first.commit()
        replacement = acquire_chat_operation(second, 7, "request-123", "hash-a")
        assert replacement.disposition == "started"
        assert not start_chat_operation(first, original)
        with pytest.raises(HTTPException) as superseded:
            require_chat_operation_owner(first, original)
        assert superseded.value.code == "operation_superseded"
        first.rollback()
        assert start_chat_operation(second, replacement)
        finish_chat_operation(second, replacement, succeeded=False)
    finally:
        first.close()
        second.close()


def test_receipt_and_quota_commit_once_then_replay_without_generation(pg_sessions, monkeypatch):
    db = pg_sessions()
    replay_db = pg_sessions()
    try:
        payload = ChatRequest(message="What does HbA1c mean?")
        fingerprint = _chat_fingerprint(payload)
        calls = []

        async def generate(request, chat_request, session, current_user, lease, *,
                           document_bytes=None, operation=None):
            calls.append(operation.owner)
            session.execute(text("UPDATE users SET monthly_chat_count = monthly_chat_count + 1 WHERE id = 7"))
            session.add(AIChatRequestReceipt(
                patient_id=7,
                request_digest=ai_request_digest(operation.request_id),
                request_fingerprint=fingerprint,
                response_json=InteractionResponse(request_id="request-123", interaction_id="interaction-123",
                                                  mode=InteractionMode.CONVERSATION, result_kind=ResultKind.MESSAGE,
                                                  result=MessageResult(text="Saved answer")).model_dump(),
                created_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc).replace(year=2099),
            ))
            require_chat_operation_owner(session, operation)
            session.commit()
            return InteractionResponse(request_id="request-123", interaction_id="interaction-123",
                                       mode=InteractionMode.CONVERSATION, result_kind=ResultKind.MESSAGE,
                                       result=MessageResult(text="Saved answer"))

        monkeypatch.setattr("app.api.v1.chat._analyze_chat_request", generate)
        import asyncio

        first = asyncio.run(_run_chat_operation(None, payload, db, _user(), "request-123"))
        assert first.result.text == "Saved answer"

        async def unexpected(*_args, **_kwargs):
            raise AssertionError("provider must not run for a committed receipt")

        monkeypatch.setattr("app.api.v1.chat._analyze_chat_request", unexpected)
        result = asyncio.run(_run_chat_operation(None, payload, replay_db, _user(), "request-123"))
        assert result.result.text == "Saved answer"
        assert len(calls) == 1
        with pytest.raises(HTTPException) as mismatch:
            asyncio.run(_run_chat_operation(
                None, ChatRequest(message="A different question"),
                replay_db, _user(), "request-123",
            ))
        assert mismatch.value.code == "request_conflict"
        assert replay_db.execute(text("SELECT monthly_chat_count FROM users WHERE id = 7")).scalar_one() == 1
        assert _get_chat_receipt(replay_db, 7, "request-123") is not None
    finally:
        db.close()
        replay_db.close()
