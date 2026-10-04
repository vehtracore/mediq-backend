"""Assessment optimistic versioning on separate PostgreSQL connections."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from time import sleep

from fastapi import HTTPException
from sqlalchemy import text

from app.models.ai_assessment import AIAssessment
from app.services import ai_assessment
from tests.test_ai_chat_postgres_claim import pg_sessions


def test_concurrent_assessment_mutation_only_one_version_wins(pg_sessions):
    setup = pg_sessions()
    try:
        migration = Path(__file__).resolve().parents[1] / "migrations" / "add_ai_assessments.sql"
        with setup.bind.begin() as connection:
            connection.exec_driver_sql(migration.read_text(encoding="utf-8"))
        now = ai_assessment.utcnow()
        setup.add(AIAssessment(
            id="00000000-0000-4000-8000-000000000001", patient_id=7,
            status="ACTIVE", presenting_concern="Synthetic concern", language="English",
            schema_version=1, state_version=1, readiness=False,
            readiness_reasons=[], created_at=now, updated_at=now,
            last_activity_at=now, expires_at=now + ai_assessment.RETENTION,
            originating_request_id="initial-operation", usage_committed=False,
        ))
        setup.commit()
    finally:
        setup.close()

    gate = Barrier(2)

    def attempt(number):
        db = pg_sessions()
        try:
            gate.wait(timeout=5)
            session = ai_assessment.owned_session(
                db, 7, "00000000-0000-4000-8000-000000000001", lock=True)
            ai_assessment._require_mutable(session, 1, ai_assessment.utcnow())
            if number == 0:
                sleep(.2)
            ai_assessment._touch(session, f"operation-{number}", ai_assessment.utcnow())
            db.commit()
            return "won"
        except HTTPException as error:
            db.rollback()
            return error.code
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, range(2)))
    assert sorted(outcomes) == ["stale_version", "won"]
    verify = pg_sessions()
    try:
        assert verify.execute(text("SELECT state_version FROM ai_assessments")).scalar_one() == 2
    finally:
        verify.close()
