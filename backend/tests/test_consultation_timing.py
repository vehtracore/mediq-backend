from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest

from app.models.appointment import (
    APPOINTMENT_TYPE_GENERAL_QUEUE,
    APPOINTMENT_TYPE_SPECIALIST_SCHEDULED,
    attendance_deadline_utc,
    consultation_room_is_unlocked,
    consultation_started_utc,
)
from app.services.consultation_pricing import (
    PAYSTACK_PLATFORM_PERCENTAGE_CHARGE,
    calculate_consultation_split,
    naira_to_kobo,
)


def _appointment(**overrides):
    values = {
        "appointment_type": APPOINTMENT_TYPE_GENERAL_QUEUE,
        "start_time": datetime(2026, 6, 20, 10, 0),
        "slot_id": None,
        "slot": None,
        "paystack_reference": None,
        "doctor_id": 1,
        "consultation_started_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class ConsultationTimingTests(unittest.TestCase):
    def test_general_queue_second_participant_has_five_minutes_to_join(self):
        appointment = _appointment()

        self.assertEqual(
            attendance_deadline_utc(appointment),
            datetime(2026, 6, 20, 10, 5, tzinfo=timezone.utc),
        )

    def test_scheduled_second_participant_has_fifteen_minutes_to_join(self):
        scheduled_start = datetime(2026, 6, 20, 10, 0)
        appointment = _appointment(
            appointment_type=APPOINTMENT_TYPE_SPECIALIST_SCHEDULED,
            slot_id=8,
            slot=SimpleNamespace(start_time=scheduled_start),
        )

        self.assertEqual(
            attendance_deadline_utc(appointment),
            datetime(2026, 6, 20, 10, 15, tzinfo=timezone.utc),
        )

    def test_scheduled_room_opens_ten_minutes_early_and_closes_at_deadline(self):
        scheduled_start = datetime(2026, 6, 20, 10, 0)
        appointment = _appointment(
            appointment_type=APPOINTMENT_TYPE_SPECIALIST_SCHEDULED,
            slot_id=8,
            slot=SimpleNamespace(start_time=scheduled_start),
        )

        self.assertFalse(
            consultation_room_is_unlocked(
                appointment,
                now=datetime(2026, 6, 20, 9, 49, tzinfo=timezone.utc),
            )
        )
        self.assertTrue(
            consultation_room_is_unlocked(
                appointment,
                now=datetime(2026, 6, 20, 9, 50, tzinfo=timezone.utc),
            )
        )
        self.assertFalse(
            consultation_room_is_unlocked(
                appointment,
                now=datetime(2026, 6, 20, 10, 15, tzinfo=timezone.utc),
            )
        )

    def test_consultation_split_uses_configured_platform_rate(self):
        commission, payout = calculate_consultation_split(4000)

        self.assertEqual(commission, 1480.0)
        self.assertEqual(payout, 2520.0)
        self.assertEqual(PAYSTACK_PLATFORM_PERCENTAGE_CHARGE, 37.0)

    def test_naira_to_kobo_rounds_currency_safely(self):
        self.assertEqual(naira_to_kobo(1480.0), 148000)
        self.assertEqual(naira_to_kobo(12.345), 1235)

    def test_recorded_session_start_is_independent_of_scheduled_time(self):
        actual_start = datetime(2026, 6, 20, 10, 7)
        appointment = _appointment(consultation_started_at=actual_start)

        self.assertEqual(
            consultation_started_utc(appointment),
            actual_start.replace(tzinfo=timezone.utc),
        )
        self.assertTrue(
            consultation_room_is_unlocked(
                appointment,
                now=actual_start.replace(tzinfo=timezone.utc)
                + timedelta(hours=1),
            )
        )


if __name__ == "__main__":
    unittest.main()
