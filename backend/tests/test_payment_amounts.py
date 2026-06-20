import unittest

from app.services.paystack_amounts import paystack_requested_amount_kobo


class PaystackAmountTests(unittest.TestCase):
    def test_requested_amount_excludes_customer_borne_fees(self):
        self.assertEqual(
            paystack_requested_amount_kobo(
                {
                    "amount": 416000,
                    "requested_amount": 400000,
                }
            ),
            400000,
        )

    def test_legacy_payload_falls_back_to_amount(self):
        self.assertEqual(
            paystack_requested_amount_kobo({"amount": 400000}),
            400000,
        )

    def test_invalid_payload_is_rejected_as_zero(self):
        self.assertEqual(
            paystack_requested_amount_kobo({"requested_amount": "invalid"}),
            0,
        )


if __name__ == "__main__":
    unittest.main()
