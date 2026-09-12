import asyncio
from datetime import datetime, timedelta, timezone
import inspect
import logging
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import deps
from app.api.v1 import support
from app.models.review import Review  # noqa: F401 - registers ORM relationship
from app.core import scheduler
from app.core.database import Base, get_db
from app.core.limiter import limiter
from app.models.support_message import SupportMessage
from app.models.user import User
from app.services import email_guard, email_service


class SupportSubmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name, "support.sqlite3").as_posix()
        self.engine = create_engine(
            f"sqlite:///{database_path}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(
            self.engine,
            tables=[User.__table__, SupportMessage.__table__],
        )
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.Session() as db:
            db.add_all(
                [
                    User(
                        id=1,
                        email="patient@example.com",
                        first_name="Ada",
                        last_name="Okafor",
                        role="patient",
                    ),
                    User(
                        id=2,
                        email="other@example.com",
                        first_name="Other",
                        last_name="User",
                        role="patient",
                    ),
                ]
            )
            db.commit()

        self.env = patch.dict(
            os.environ,
            {
                "EMAIL_DELIVERY_ENABLED": "true",
                "RESEND_API_KEY": "test-only-key",
                "SUPPORT_EMAIL_TO": "mdqplus.info@gmail.com",
                "RESEND_FROM_EMAIL": "MDQ+ Support <support@mdqplus.com>",
                "EMAIL_DAILY_SEND_LIMIT": "0",
                "EMAIL_RECIPIENT_COOLDOWN_SECONDS": "300",
            },
        )
        self.env.start()
        self._reset_email_guard()

    def tearDown(self):
        self.env.stop()
        self._reset_email_guard()
        self.engine.dispose()
        self.temp_dir.cleanup()

    @staticmethod
    def _reset_email_guard():
        email_guard._COUNTER_DATE = None
        email_guard._COUNTER_COUNT = 0
        email_guard._RECIPIENT_LAST_SENT_AT.clear()

    def _payload(self, request_id=None, subject="Billing <urgent>", message="Help & advise"):
        return support.SupportMessageRequest(
            request_id=request_id or uuid4(),
            subject=subject,
            message=message,
        )

    def _invoke(self, payload, *, user_id=1):
        with self.Session() as db:
            user = db.get(User, user_id)
            return asyncio.run(
                inspect.unwrap(support.send_support_message)(
                    request=SimpleNamespace(),
                    payload=payload,
                    db=db,
                    current_user=user,
                )
            )

    def _row(self, request_id):
        with self.Session() as db:
            return (
                db.query(SupportMessage)
                .filter(SupportMessage.request_id == request_id)
                .one()
            )

    def test_validation_trims_and_rejects_whitespace_only_content(self):
        with self.assertRaises(ValidationError):
            self._payload(subject="   ")
        with self.assertRaises(ValidationError):
            self._payload(message="\n\t ")

        payload = self._payload(subject="  Account issue  ", message="  Please help  ")
        self.assertEqual(payload.subject, "Account issue")
        self.assertEqual(payload.message, "Please help")

        with self.assertRaises(ValidationError):
            support.SupportMessageRequest(
                request_id=uuid4(),
                subject="Help",
                message="Please assist",
                user_id=999,
                sender_email="attacker@example.com",
            )

    def test_provider_acceptance_is_durable_private_and_uses_authenticated_identity(self):
        payload = self._payload()
        captured = {}

        def accept(params):
            with self.Session() as db:
                row = (
                    db.query(SupportMessage)
                    .filter(SupportMessage.request_id == payload.request_id)
                    .one()
                )
                self.assertEqual(row.email_status, "sending")
                self.assertEqual(row.attempt_count, 1)
            captured["params"] = params
            return {"id": "resend-message-1"}

        with self.assertLogs(level=logging.INFO) as logs:
            with patch("app.services.support_email_service.resend.Emails.send", side_effect=accept):
                result = self._invoke(payload)

        self.assertEqual(result.status, "sent")
        self.assertEqual(result.request_id, payload.request_id)
        row = self._row(payload.request_id)
        self.assertEqual(row.email_status, "sent")
        self.assertEqual(row.provider_message_id, "resend-message-1")
        self.assertIsNotNone(row.sent_at)

        params = captured["params"]
        self.assertEqual(params["to"], ["mdqplus.info@gmail.com"])
        self.assertEqual(params["from"], "MDQ+ Support <support@mdqplus.com>")
        self.assertEqual(params["reply_to"], "patient@example.com")
        self.assertNotEqual(params["from"], "patient@example.com")
        self.assertNotIn(payload.subject, params["subject"])
        self.assertIn("Billing &lt;urgent&gt;", params["html"])
        self.assertIn("Help &amp; advise", params["html"])
        self.assertIn("Ada Okafor", params["html"])

        output = "\n".join(logs.output)
        self.assertNotIn(payload.subject, output)
        self.assertNotIn(payload.message, output)

    def _assert_configuration_failure(self, *, remove=(), updates=None):
        payload = self._payload()
        old_values = {name: os.environ.get(name) for name in remove}
        try:
            for name in remove:
                os.environ.pop(name, None)
            with patch.dict(os.environ, updates or {}):
                with patch("app.services.support_email_service.resend.Emails.send") as send:
                    with self.assertRaises(HTTPException) as caught:
                        self._invoke(payload)
            self.assertEqual(caught.exception.status_code, 503)
            send.assert_not_called()
            row = self._row(payload.request_id)
            self.assertEqual(row.email_status, "failed")
            self.assertEqual(row.failure_category, "configuration")
            self.assertEqual(row.attempt_count, 1)
        finally:
            for name, value in old_values.items():
                if value is not None:
                    os.environ[name] = value

    def test_disabled_or_missing_configuration_never_returns_success(self):
        self._assert_configuration_failure(
            updates={"EMAIL_DELIVERY_ENABLED": "false"}
        )
        self._assert_configuration_failure(remove=("RESEND_API_KEY",))
        self._assert_configuration_failure(remove=("SUPPORT_EMAIL_TO",))
        self._assert_configuration_failure(remove=("RESEND_FROM_EMAIL", "EMAIL_FROM"))

    def test_admin_email_is_not_a_support_recipient_fallback(self):
        with patch.dict(os.environ, {"ADMIN_EMAIL": "admin@mdqplus.com"}):
            self._assert_configuration_failure(remove=("SUPPORT_EMAIL_TO",))

    def test_provider_exception_and_timeout_are_failed_and_retained(self):
        cases = [
            (RuntimeError("provider down"), 502, "unknown"),
            (TimeoutError("provider timeout"), 504, "provider_timeout"),
        ]
        for error, status_code, category in cases:
            with self.subTest(category=category):
                payload = self._payload()
                with patch(
                    "app.services.support_email_service.resend.Emails.send",
                    side_effect=error,
                ):
                    with self.assertRaises(HTTPException) as caught:
                        self._invoke(payload)
                self.assertEqual(caught.exception.status_code, status_code)
                row = self._row(payload.request_id)
                self.assertEqual(row.email_status, "failed")
                self.assertEqual(row.failure_category, category)
                self.assertIsNone(row.provider_message_id)

    def test_retry_reuses_row_and_already_sent_does_not_resend(self):
        payload = self._payload()
        responses = [TimeoutError("timeout"), {"id": "resend-after-retry"}]
        def send(_params):
            result = responses.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        with patch("app.services.support_email_service.resend.Emails.send", side_effect=send) as mocked:
            with self.assertRaises(HTTPException):
                self._invoke(payload)
            result = self._invoke(payload)
            replay = self._invoke(payload)

        self.assertEqual(result.status, "sent")
        self.assertEqual(replay.status, "sent")
        self.assertEqual(mocked.call_count, 2)
        with self.Session() as db:
            self.assertEqual(db.query(SupportMessage).count(), 1)
        self.assertEqual(self._row(payload.request_id).attempt_count, 2)

    def test_live_attempt_is_not_duplicated_and_stale_claim_can_recover(self):
        payload = self._payload()
        with self.Session() as db:
            db.add(
                SupportMessage(
                    request_id=payload.request_id,
                    user_id=1,
                    subject=payload.subject,
                    message=payload.message,
                    email_status="sending",
                    attempt_count=1,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            db.commit()

        with patch("app.services.support_email_service.resend.Emails.send") as send:
            with self.assertRaises(HTTPException) as caught:
                self._invoke(payload)
        self.assertEqual(caught.exception.status_code, 409)
        send.assert_not_called()

        with self.Session() as db:
            row = (
                db.query(SupportMessage)
                .filter(SupportMessage.request_id == payload.request_id)
                .one()
            )
            row.updated_at = datetime.now(timezone.utc) - timedelta(minutes=3)
            db.commit()

        with patch(
            "app.services.support_email_service.resend.Emails.send",
            return_value={"id": "recovered"},
        ) as send:
            result = self._invoke(payload)
        self.assertEqual(result.status, "sent")
        send.assert_called_once()
        self.assertEqual(self._row(payload.request_id).attempt_count, 2)

    def test_request_id_cannot_cross_users_or_change_content(self):
        payload = self._payload()
        with patch(
            "app.services.support_email_service.resend.Emails.send",
            return_value={"id": "accepted"},
        ):
            self._invoke(payload, user_id=1)

        with self.assertRaises(HTTPException) as cross_user:
            self._invoke(payload, user_id=2)
        self.assertEqual(cross_user.exception.status_code, 409)

        changed = self._payload(
            request_id=payload.request_id,
            subject="Different",
            message=payload.message,
        )
        with self.assertRaises(HTTPException) as changed_content:
            self._invoke(changed, user_id=1)
        self.assertEqual(changed_content.exception.status_code, 409)

    def test_shared_support_recipient_cooldown_is_bypassed_narrowly(self):
        with patch.dict(
            os.environ,
            {
                "EMAIL_RECIPIENT_COOLDOWN_SECONDS": "9999",
                "EMAIL_DAILY_SEND_LIMIT": "0",
            },
        ):
            with patch(
                "app.services.support_email_service.resend.Emails.send",
                side_effect=[{"id": "one"}, {"id": "two"}],
            ) as send:
                self._invoke(self._payload(), user_id=1)
                self._invoke(self._payload(), user_id=2)
        self.assertEqual(send.call_count, 2)

        self._reset_email_guard()
        first = email_guard.reserve_email_send(
            "ordinary@example.com", "Transactional", purpose="auth"
        )
        second = email_guard.reserve_email_send(
            "ordinary@example.com", "Transactional", purpose="auth"
        )
        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_existing_transactional_email_service_keeps_generic_guard(self):
        with patch.object(email_service, "_resend_send") as send:
            asyncio.run(
                email_service.send_transactional_email(
                    "billing@example.com",
                    "Payment receipt",
                    "<p>Receipt</p>",
                )
            )
            asyncio.run(
                email_service.send_transactional_email(
                    "billing@example.com",
                    "Payment receipt",
                    "<p>Receipt</p>",
                )
            )

        send.assert_called_once()
        self.assertEqual(send.call_args.args[0], "billing@example.com")

    def test_global_cap_failure_is_explicit_and_retains_row(self):
        with patch.dict(os.environ, {"EMAIL_DAILY_SEND_LIMIT": "1"}):
            with patch(
                "app.services.support_email_service.resend.Emails.send",
                return_value={"id": "first"},
            ) as send:
                self._invoke(self._payload())
                second_payload = self._payload()
                with self.assertRaises(HTTPException) as caught:
                    self._invoke(second_payload, user_id=2)
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(self._row(second_payload.request_id).email_status, "failed")
        self.assertEqual(
            self._row(second_payload.request_id).failure_category,
            "rate_limited",
        )

    def test_route_rate_limit_is_explicit(self):
        limiter.reset()
        app = FastAPI()
        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        app.include_router(support.router, prefix="/api/v1/support")

        def override_db():
            with self.Session() as db:
                yield db

        def override_user():
            with self.Session() as db:
                yield db.get(User, 1)

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[deps.get_current_user] = override_user

        with patch(
            "app.services.support_email_service.resend.Emails.send",
            side_effect=lambda *_args, **_kwargs: {"id": str(uuid4())},
        ):
            client = TestClient(app)
            statuses = [
                client.post(
                    "/api/v1/support/contact",
                    json={
                        "request_id": str(uuid4()),
                        "subject": "Help",
                        "message": "Please assist",
                    },
                ).status_code
                for _ in range(11)
            ]
        self.assertEqual(statuses[:10], [200] * 10)
        self.assertEqual(statuses[10], 429)
        limiter.reset()

    def test_retention_cleanup_deletes_only_rows_older_than_30_days(self):
        now = datetime.now(timezone.utc)
        with self.Session() as db:
            db.add_all(
                [
                    SupportMessage(
                        request_id=uuid4(),
                        user_id=1,
                        subject="Old",
                        message="Old content",
                        created_at=now - timedelta(days=31),
                        updated_at=now - timedelta(days=31),
                    ),
                    SupportMessage(
                        request_id=uuid4(),
                        user_id=1,
                        subject="Recent",
                        message="Recent content",
                        created_at=now - timedelta(days=29),
                        updated_at=now - timedelta(days=29),
                    ),
                ]
            )
            db.commit()

        with patch.object(scheduler, "SessionLocal", self.Session):
            asyncio.run(scheduler.cleanup_old_support_messages())

        with self.Session() as db:
            rows = db.query(SupportMessage).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].subject, "Recent")

    def test_migration_has_global_request_id_uniqueness(self):
        migration = Path(
            __file__
        ).parents[1] / "migrations" / "add_reliable_support_messages.sql"
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("UNIQUE (request_id)", sql)
        self.assertNotIn("admin@mdqplus.com", sql)


if __name__ == "__main__":
    unittest.main()
