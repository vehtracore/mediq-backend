from io import BytesIO
from types import SimpleNamespace
import unittest

from fastapi import HTTPException
from PIL import Image, ImageDraw

from app.services.lab_image_quality import assess_lab_image_quality
from app.services.lab_scan_guard import (
    enforce_lab_scan_guard,
    record_lab_scan_failure,
    record_lab_scan_success,
)


class DummyDb:
    def __init__(self):
        self.commits = 0

    def add(self, _obj):
        pass

    def commit(self):
        self.commits += 1


def _user(**overrides):
    data = {
        "monthly_lab_count": 0,
        "monthly_chat_image_count": 0,
        "lab_failed_attempt_count": 0,
        "lab_failed_attempt_started_at": None,
        "lab_last_failed_attempt_at": None,
        "lab_cooldown_until": None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _jpeg_bytes(image):
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


class LabImageQualityTests(unittest.TestCase):
    def test_dark_image_is_rejected_before_gemini(self):
        image = Image.new("RGB", (500, 500), (5, 5, 5))
        result = assess_lab_image_quality(_jpeg_bytes(image))

        self.assertFalse(result.passed)
        self.assertEqual(result.lighting_score, "Poor")
        self.assertIn("too dark", result.reason)

    def test_clear_strip_like_image_passes_local_preflight(self):
        image = Image.new("RGB", (700, 900), (220, 220, 220))
        draw = ImageDraw.Draw(image)
        draw.rectangle((280, 80, 420, 820), fill=(245, 245, 245), outline=(40, 40, 40))
        colors = [
            (245, 225, 120),
            (220, 130, 160),
            (120, 180, 110),
            (170, 120, 220),
            (210, 180, 80),
        ]
        for index, color in enumerate(colors):
            y = 130 + (index * 120)
            draw.rectangle((300, y, 400, y + 70), fill=color, outline=(60, 60, 60))

        result = assess_lab_image_quality(_jpeg_bytes(image))

        self.assertTrue(result.passed)
        self.assertIn(result.lighting_score, {"Good", "Acceptable"})


class LabScanGuardTests(unittest.TestCase):
    def test_fourth_consecutive_failure_deducts_one_quota_unit(self):
        db = DummyDb()
        user = _user()

        actions = [record_lab_scan_failure(db, user) for _ in range(4)]

        self.assertFalse(actions[0].quota_deducted)
        self.assertFalse(actions[1].quota_deducted)
        self.assertFalse(actions[2].quota_deducted)
        self.assertTrue(actions[3].quota_deducted)
        self.assertEqual(user.monthly_lab_count, 1)
        self.assertEqual(user.lab_failed_attempt_count, 4)

    def test_after_four_failures_next_attempt_is_cooled_down(self):
        db = DummyDb()
        user = _user(lab_failed_attempt_count=4)

        with self.assertRaises(HTTPException) as ctx:
            enforce_lab_scan_guard(db, user)

        self.assertEqual(ctx.exception.status_code, 429)
        self.assertIsNotNone(user.lab_cooldown_until)

    def test_success_resets_failure_streak(self):
        user = _user(lab_failed_attempt_count=3, monthly_lab_count=2)

        record_lab_scan_success(user)

        self.assertEqual(user.lab_failed_attempt_count, 0)
        self.assertIsNone(user.lab_failed_attempt_started_at)
        self.assertIsNone(user.lab_last_failed_attempt_at)
        self.assertIsNone(user.lab_cooldown_until)
        self.assertEqual(user.monthly_lab_count, 2)


if __name__ == "__main__":
    unittest.main()
