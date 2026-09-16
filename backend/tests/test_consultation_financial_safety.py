import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1 import admin, appointments
from app.core.database import Base
from app.models.appointment import Appointment, DoctorSlot
from app.models.audit import AuditLog
from app.models.consultation_payout import ConsultationPayout
from app.models.doctor import Doctor
from app.models.review import Review  # noqa: F401 - register ORM relationship
from app.models.support_message import SupportMessage
from app.models.user import User
from app.services import consultation_payout_service, consultation_refund_service
from app.services import email_guard
from app.services.support_email_service import SupportEmailDeliveryError


TABLES = [
    User.__table__,
    Doctor.__table__,
    DoctorSlot.__table__,
    Appointment.__table__,
    ConsultationPayout.__table__,
    SupportMessage.__table__,
    AuditLog.__table__,
]


class FinancialSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        path = Path(self.temp_dir.name, "financial_safety.sqlite3").as_posix()
        self.engine = create_engine(
            f"sqlite:///{path}", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(self.engine, tables=TABLES)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.Session() as db:
            self._seed(db)

    def tearDown(self):
        self.engine.dispose()
        self.temp_dir.cleanup()

    @staticmethod
    def _seed(db, *, started_at=None):
        db.add_all(
            [
                User(id=1, email="admin@example.com", role="admin"),
                User(
                    id=2,
                    email="patient@example.com",
                    first_name="Ada",
                    last_name="Okafor",
                    role="patient",
                ),
                User(id=3, email="doctor@example.com", role="doctor"),
            ]
        )
        db.flush()
        db.add(
            Doctor(
                id=7,
                user_id=3,
                full_name="Dr Test",
                bank_code="058",
                account_number="0123456789",
                paystack_recipient_code="RCP_TEST",
            )
        )
        db.flush()
        db.add(
            Appointment(
                id=42,
                patient_id=2,
                doctor_id=7,
                appointment_type="general_queue",
                status="completed",
                payment_status="paid",
                consultation_started_at=started_at or datetime.utcnow() - timedelta(days=2),
                amount=4000,
                payout=2520,
                paystack_reference="MDQ-gp_consult-42-2-test",
                notes="PRIVATE CLINICAL NOTE",
            )
        )
        db.flush()
        db.add(
            ConsultationPayout(
                id=99,
                appointment_id=42,
                doctor_id=7,
                amount=2520,
                status="awaiting_admin",
                reference="mdq-consult-payout-42",
            )
        )
        db.commit()

    def _complain(self, reason="Doctor did not provide the consultation."):
        with self.Session() as db:
            return appointments.raise_appointment_complaint(
                42,
                appointments.AppointmentComplaintRequest(reason=reason),
                db=db,
                current_user=db.get(User, 2),
            )

    def test_dispute_commits_record_and_one_authenticated_support_email(self):
        with self.Session() as db:
            db.get(Appointment, 42).consultation_started_at = datetime.utcnow() - timedelta(hours=1)
            db.commit()
        with patch.object(
            appointments.support_email_service,
            "send_support_email",
            return_value="resend-42",
        ) as send:
            result = self._complain()
            self.assertEqual(result["refund_status"], "awaiting_admin")
            with self.assertRaises(HTTPException) as duplicate:
                self._complain()
            self.assertEqual(duplicate.exception.status_code, 409)
            send.assert_called_once()

        with self.Session() as db:
            appointment = db.get(Appointment, 42)
            email = db.query(SupportMessage).one()
            self.assertEqual(appointment.refund_status, "awaiting_admin")
            self.assertEqual(email.email_status, "sent")
            self.assertEqual(email.provider_message_id, "resend-42")
            self.assertEqual(email.user_id, 2)
            self.assertIn("#42", email.subject)
            self.assertIn("MDQ-gp_consult-42-2-test", email.message)
            self.assertIn("Doctor did not provide", email.message)
            self.assertNotIn("PRIVATE CLINICAL NOTE", email.message)
            kwargs = send.call_args.kwargs
            self.assertEqual(kwargs["user_name"], "Ada Okafor")
            self.assertEqual(kwargs["user_email"], "patient@example.com")
            self.assertEqual(kwargs["recipient_email"], "mdqplus.info@gmail.com")
            self.assertNotIn("PRIVATE CLINICAL NOTE", kwargs["message"])

    def test_email_failure_does_not_release_refund_hold_or_dispute(self):
        with self.Session() as db:
            db.get(Appointment, 42).consultation_started_at = datetime.utcnow() - timedelta(hours=1)
            db.commit()
        with patch.object(
            appointments.support_email_service,
            "send_support_email",
            side_effect=SupportEmailDeliveryError("provider_timeout"),
        ) as send:
            self._complain()
            send.assert_called_once()
        with self.Session() as db:
            appointment = db.get(Appointment, 42)
            email = db.query(SupportMessage).one()
            self.assertEqual(appointment.refund_status, "awaiting_admin")
            self.assertEqual(email.email_status, "failed")
            self.assertEqual(email.failure_category, "provider_timeout")
            self.assertIsNone(
                consultation_payout_service.eligible_consultation_payout_amount(
                    appointment, require_hold_elapsed=False
                )
            )

    def test_dispute_email_reuses_support_provider_with_fixed_recipient(self):
        with self.Session() as db:
            db.get(Appointment, 42).consultation_started_at = datetime.utcnow() - timedelta(hours=1)
            db.commit()
        email_guard._COUNTER_DATE = None
        email_guard._COUNTER_COUNT = 0
        email_guard._RECIPIENT_LAST_SENT_AT.clear()
        with patch.dict(
            os.environ,
            {
                "EMAIL_DELIVERY_ENABLED": "true",
                "RESEND_API_KEY": "test-only-key",
                "RESEND_FROM_EMAIL": "MDQ+ Support <support@mdqplus.com>",
                "SUPPORT_EMAIL_TO": "different-inbox@example.com",
                "EMAIL_DAILY_SEND_LIMIT": "0",
            },
        ), patch.object(
            appointments.support_email_service.resend.Emails,
            "send",
            return_value={"id": "resend-42"},
        ) as send:
            self._complain()
            send.assert_called_once()
            params = send.call_args.args[0]
            self.assertEqual(params["to"], ["mdqplus.info@gmail.com"])
            self.assertEqual(params["reply_to"], "patient@example.com")
            self.assertIn("Consultation Refund / Dispute", params["subject"])
            self.assertIn("Ada Okafor", params["html"])
            self.assertIn("patient@example.com", params["html"])
            self.assertIn("MDQ-gp_consult-42-2-test", params["html"])
            self.assertNotIn("PRIVATE CLINICAL NOTE", params["html"])
        email_guard._COUNTER_DATE = None
        email_guard._COUNTER_COUNT = 0
        email_guard._RECIPIENT_LAST_SENT_AT.clear()

    def test_email_record_failure_does_not_rollback_dispute(self):
        with self.Session() as db:
            db.get(Appointment, 42).consultation_started_at = datetime.utcnow() - timedelta(hours=1)
            db.commit()
        with patch.object(appointments, "SupportMessage", side_effect=RuntimeError("unavailable")):
            result = self._complain()
        self.assertEqual(result["refund_status"], "awaiting_admin")
        with self.Session() as db:
            self.assertEqual(db.get(Appointment, 42).refund_status, "awaiting_admin")
            self.assertEqual(db.query(SupportMessage).count(), 0)

    def test_payout_approved_first_blocks_complaint_and_refund_approval(self):
        with self.Session() as db:
            admin.approve_consultation_payout(99, db=db, admin=db.get(User, 1))
        with self.Session() as db:
            db.get(Appointment, 42).consultation_started_at = datetime.utcnow() - timedelta(hours=1)
            db.commit()
        with self.assertRaises(HTTPException) as complaint:
            self._complain()
        self.assertEqual(complaint.exception.status_code, 409)
        with self.Session() as db:
            db.get(Appointment, 42).refund_status = "awaiting_admin"
            db.commit()
        with self.Session() as db:
            with self.assertRaises(HTTPException) as refund:
                admin.approve_consultation_refund(42, db=db, admin=db.get(User, 1))
            self.assertEqual(refund.exception.status_code, 409)
        with self.Session() as db:
            self.assertEqual(db.get(ConsultationPayout, 99).status, "approved")
            self.assertEqual(db.get(Appointment, 42).refund_status, "awaiting_admin")

    def test_refund_approved_first_blocks_payout_approval(self):
        with self.Session() as db:
            db.get(Appointment, 42).refund_status = "awaiting_admin"
            db.commit()
        with self.Session() as db:
            admin.approve_consultation_refund(42, db=db, admin=db.get(User, 1))
        with self.Session() as db:
            with self.assertRaises(HTTPException) as payout:
                admin.approve_consultation_payout(99, db=db, admin=db.get(User, 1))
            self.assertEqual(payout.exception.status_code, 409)
        with self.Session() as db:
            self.assertEqual(db.get(Appointment, 42).refund_status, "approved")
            self.assertEqual(db.get(ConsultationPayout, 99).status, "awaiting_admin")

    def test_legacy_conflicting_approvals_never_call_paystack(self):
        with self.Session() as db:
            db.get(Appointment, 42).refund_status = "approved"
            db.get(ConsultationPayout, 99).status = "approved"
            db.commit()
        with patch.object(consultation_refund_service, "SessionLocal", self.Session), patch.object(
            consultation_refund_service.paystack_service, "create_refund"
        ) as refund_call:
            asyncio.run(consultation_refund_service.process_approved_consultation_refunds())
            refund_call.assert_not_called()
        with patch.object(consultation_payout_service, "SessionLocal", self.Session), patch.object(
            consultation_payout_service, "enqueue_missing_consultation_payouts"
        ), patch.object(
            consultation_payout_service.paystack_service, "initiate_transfer"
        ) as payout_call:
            asyncio.run(consultation_payout_service.process_approved_consultation_payouts())
            payout_call.assert_not_called()
        with self.Session() as db:
            self.assertEqual(db.get(Appointment, 42).refund_status, "needs_attention")
            self.assertEqual(db.get(ConsultationPayout, 99).status, "blocked")


@unittest.skipUnless(
    os.getenv("TEST_FINANCIAL_POSTGRES_URL"),
    "A disposable PostgreSQL database is required for row-lock concurrency",
)
class PostgresFinancialConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(os.environ["TEST_FINANCIAL_POSTGRES_URL"])
        Base.metadata.create_all(self.engine, tables=TABLES)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.Session() as db:
            FinancialSafetyTests._seed(db)

    def tearDown(self):
        Base.metadata.drop_all(self.engine, tables=list(reversed(TABLES)))
        self.engine.dispose()

    def test_concurrent_admin_approvals_choose_one_direction(self):
        with self.Session() as db:
            db.get(Appointment, 42).refund_status = "awaiting_admin"
            db.commit()
        barrier = threading.Barrier(2)

        def approve_payout():
            with self.Session() as db:
                barrier.wait()
                try:
                    admin.approve_consultation_payout(99, db=db, admin=db.get(User, 1))
                    return "payout"
                except HTTPException as exc:
                    return exc.status_code

        def approve_refund():
            with self.Session() as db:
                barrier.wait()
                try:
                    admin.approve_consultation_refund(42, db=db, admin=db.get(User, 1))
                    return "refund"
                except HTTPException as exc:
                    return exc.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = [pool.submit(approve_payout), pool.submit(approve_refund)]
            outcomes = [future.result(timeout=15) for future in outcomes]
        self.assertEqual(sorted(outcomes, key=str), [409, "refund"])
        with self.Session() as db:
            self.assertEqual(db.get(Appointment, 42).refund_status, "approved")
            self.assertEqual(db.get(ConsultationPayout, 99).status, "awaiting_admin")

    def test_payout_approval_racing_dispute_submission_never_commits_both(self):
        # The hold/window boundary is modeled with both decisions eligible so
        # this exercises the shared row lock rather than the clock condition.
        barrier = threading.Barrier(2)

        def approve_payout():
            with self.Session() as db:
                barrier.wait()
                try:
                    admin.approve_consultation_payout(99, db=db, admin=db.get(User, 1))
                    return "payout"
                except HTTPException as exc:
                    return exc.status_code

        def submit_dispute():
            with self.Session() as db:
                barrier.wait()
                try:
                    appointments.raise_appointment_complaint(
                        42,
                        appointments.AppointmentComplaintRequest(reason="No consultation"),
                        db=db,
                        current_user=db.get(User, 2),
                    )
                    return "dispute"
                except HTTPException as exc:
                    return exc.status_code

        with patch.object(
            appointments.support_email_service, "send_support_email", return_value="test-email"
        ), patch.object(
            appointments, "consultation_payout_hold_until", return_value=datetime.utcnow() + timedelta(hours=1)
        ), patch.object(
            consultation_payout_service, "payout_hold_has_elapsed", return_value=True
        ), ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = [pool.submit(approve_payout), pool.submit(submit_dispute)]
            outcomes = [future.result(timeout=15) for future in outcomes]
        self.assertEqual(len([outcome for outcome in outcomes if isinstance(outcome, str)]), 1)
        self.assertIn(409, outcomes)
        with self.Session() as db:
            payout = db.get(ConsultationPayout, 99)
            appointment = db.get(Appointment, 42)
            self.assertFalse(
                payout.status == "approved" and appointment.refund_status == "awaiting_admin"
            )
            if appointment.refund_status == "awaiting_admin":
                admin.approve_consultation_refund(42, db=db, admin=db.get(User, 1))

        payout_provider = AsyncMock(return_value={"status": "success", "transfer_code": "TRF_TEST"})
        refund_provider = AsyncMock(
            return_value={"id": "RF_TEST", "refund_reference": "RF_42", "status": "processed"}
        )
        with patch.object(consultation_payout_service, "SessionLocal", self.Session), patch.object(
            consultation_payout_service, "enqueue_missing_consultation_payouts"
        ), patch.object(
            consultation_payout_service.paystack_service,
            "initiate_transfer",
            payout_provider,
        ), patch.object(
            consultation_refund_service, "SessionLocal", self.Session
        ), patch.object(
            consultation_refund_service.paystack_service,
            "create_refund",
            refund_provider,
        ):
            asyncio.run(consultation_payout_service.process_approved_consultation_payouts())
            asyncio.run(consultation_refund_service.process_approved_consultation_refunds())
        self.assertEqual(
            payout_provider.await_count + refund_provider.await_count, 1
        )
        if "payout" in outcomes:
            refund_provider.assert_not_awaited()
        else:
            payout_provider.assert_not_awaited()
