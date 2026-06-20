from types import SimpleNamespace
import unittest

from fastapi import HTTPException

from app.services.consultation_refund_service import (
    REFUND_STATUS_AWAITING_ADMIN,
    TRANSFERABLE_REFUND_STATUSES,
    eligible_consultation_refund_amount,
    validate_admin_refund_approval,
)


def _appointment(**overrides):
    values = {
        "status": "doctor_no_show",
        "payment_status": "paid",
        "paystack_reference": "MDQ-gp_consult-42-8-123456",
        "amount": 4000.0,
        "refund_status": REFUND_STATUS_AWAITING_ADMIN,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class ConsultationRefundTests(unittest.TestCase):
    def test_only_doctor_or_both_no_show_are_refundable(self):
        self.assertEqual(eligible_consultation_refund_amount(_appointment()), 4000)
        self.assertEqual(
            eligible_consultation_refund_amount(
                _appointment(status="both_no_show")
            ),
            4000,
        )

        for status in ("patient_no_show", "completed", "cancelled"):
            with self.subTest(status=status):
                self.assertIsNone(
                    eligible_consultation_refund_amount(
                        _appointment(status=status)
                    )
                )

    def test_refund_requires_paid_transaction_reference_and_amount(self):
        cases = (
            {"payment_status": "unpaid"},
            {"paystack_reference": None},
            {"amount": 0},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                self.assertIsNone(
                    eligible_consultation_refund_amount(
                        _appointment(**overrides)
                    )
                )

    def test_admin_approval_is_idempotent_after_initiation(self):
        self.assertTrue(validate_admin_refund_approval(_appointment()))
        for refund_status in (
            "approved",
            "processing",
            "pending",
            "processed",
            "needs_attention",
        ):
            with self.subTest(refund_status=refund_status):
                self.assertFalse(
                    validate_admin_refund_approval(
                        _appointment(refund_status=refund_status)
                    )
                )

    def test_rejected_or_ineligible_refund_cannot_be_approved(self):
        with self.assertRaises(HTTPException):
            validate_admin_refund_approval(
                _appointment(refund_status="rejected")
            )
        with self.assertRaises(HTTPException):
            validate_admin_refund_approval(
                _appointment(status="patient_no_show")
            )

    def test_worker_accepts_only_admin_approved_refunds(self):
        self.assertEqual(TRANSFERABLE_REFUND_STATUSES, frozenset({"approved"}))
        self.assertNotIn("awaiting_admin", TRANSFERABLE_REFUND_STATUSES)
        self.assertNotIn("rejected", TRANSFERABLE_REFUND_STATUSES)


if __name__ == "__main__":
    unittest.main()
