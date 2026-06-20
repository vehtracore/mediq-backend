from types import SimpleNamespace
import unittest

from fastapi import HTTPException

from app.models.appointment import (
    APPOINTMENT_TYPE_GENERAL_QUEUE,
    APPOINTMENT_TYPE_SPECIALIST_SCHEDULED,
)
from app.models.consultation_payout import ConsultationPayout
from app.services.consultation_payout_service import (
    PAYOUT_STATUS_AWAITING_ADMIN,
    PAYOUT_STATUS_APPROVED,
    TRANSFERABLE_PAYOUT_STATUSES,
    eligible_general_queue_payout_amount,
    validate_admin_payout_decision,
)


def _appointment(**overrides):
    values = {
        "appointment_type": APPOINTMENT_TYPE_GENERAL_QUEUE,
        "slot_id": None,
        "paystack_reference": "gp_consult-42",
        "status": "completed",
        "payment_status": "paid",
        "doctor_id": 7,
        "payout": 2520.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _payout(**overrides):
    values = {
        "status": PAYOUT_STATUS_AWAITING_ADMIN,
        "doctor_id": 7,
        "amount": 2520,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _doctor(**overrides):
    values = {
        "bank_code": "058",
        "account_number": "0123456789",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class ConsultationPayoutTests(unittest.TestCase):
    def test_new_payouts_require_admin_approval(self):
        self.assertEqual(PAYOUT_STATUS_AWAITING_ADMIN, "awaiting_admin")
        self.assertEqual(
            ConsultationPayout.__table__.c.status.default.arg,
            "awaiting_admin",
        )
        self.assertEqual(
            TRANSFERABLE_PAYOUT_STATUSES,
            frozenset({"approved"}),
        )
        self.assertNotIn("awaiting_admin", TRANSFERABLE_PAYOUT_STATUSES)
        self.assertNotIn("rejected", TRANSFERABLE_PAYOUT_STATUSES)

    def test_completed_and_patient_no_show_general_queue_sessions_are_payable(self):
        self.assertEqual(
            eligible_general_queue_payout_amount(_appointment()),
            2520,
        )
        self.assertEqual(
            eligible_general_queue_payout_amount(
                _appointment(status="patient_no_show")
            ),
            2520,
        )

    def test_non_payable_outcomes_are_rejected(self):
        cases = (
            {"status": "pending"},
            {"status": "doctor_no_show"},
            {"status": "both_no_show"},
            {"payment_status": "unpaid"},
            {"doctor_id": None},
            {"payout": 0},
            {"appointment_type": APPOINTMENT_TYPE_SPECIALIST_SCHEDULED},
        )

        for overrides in cases:
            with self.subTest(overrides=overrides):
                self.assertIsNone(
                    eligible_general_queue_payout_amount(
                        _appointment(**overrides)
                    )
                )

    def test_admin_can_approve_only_matching_eligible_payout(self):
        self.assertTrue(
            validate_admin_payout_decision(
                _payout(),
                action="approve",
                appointment=_appointment(),
                doctor=_doctor(),
            )
        )

        invalid_cases = (
            {
                "payout": _payout(amount=2500),
                "appointment": _appointment(),
                "doctor": _doctor(),
            },
            {
                "payout": _payout(),
                "appointment": _appointment(status="doctor_no_show"),
                "doctor": _doctor(),
            },
            {
                "payout": _payout(),
                "appointment": _appointment(doctor_id=8),
                "doctor": _doctor(),
            },
            {
                "payout": _payout(),
                "appointment": _appointment(),
                "doctor": _doctor(account_number=None),
            },
        )
        for case in invalid_cases:
            with self.subTest(case=case):
                with self.assertRaises(HTTPException) as raised:
                    validate_admin_payout_decision(
                        case["payout"],
                        action="approve",
                        appointment=case["appointment"],
                        doctor=case["doctor"],
                    )
                self.assertEqual(raised.exception.status_code, 409)

    def test_approval_and_rejection_repeats_are_idempotent(self):
        self.assertFalse(
            validate_admin_payout_decision(
                _payout(status=PAYOUT_STATUS_APPROVED),
                action="approve",
            )
        )
        self.assertFalse(
            validate_admin_payout_decision(
                _payout(status="rejected"),
                action="reject",
            )
        )

    def test_unapproved_or_rejected_payout_cannot_change_decision(self):
        with self.assertRaises(HTTPException):
            validate_admin_payout_decision(
                _payout(status="rejected"),
                action="approve",
            )
        with self.assertRaises(HTTPException):
            validate_admin_payout_decision(
                _payout(status=PAYOUT_STATUS_APPROVED),
                action="reject",
            )


if __name__ == "__main__":
    unittest.main()
