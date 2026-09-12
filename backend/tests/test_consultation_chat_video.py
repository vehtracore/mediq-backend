from datetime import datetime, timedelta
import inspect
from types import SimpleNamespace
import unittest
from unittest.mock import ANY, patch

from fastapi import HTTPException

from app.api.v1 import chat_socket, video


class _Query:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._result


class _MessageDb:
    def __init__(self, user):
        self.user = user
        self.added = []
        self.committed = False
        self.closed = False

    def query(self, model):
        return _Query(self.user)

    def add(self, message):
        self.added.append(message)

    def commit(self):
        self.committed = True

    def refresh(self, message):
        message.id = 81

    def rollback(self):
        pass

    def close(self):
        self.closed = True


class _VideoDb:
    def query(self, model):
        return _Query(None)


class _Message:
    def __init__(self, **values):
        self.__dict__.update(values)
        self.id = None


class ConsultationChatVideoTests(unittest.TestCase):
    def test_chat_message_is_authorized_then_persisted(self):
        current_user = SimpleNamespace(id=5)
        db = _MessageDb(current_user)

        with (
            patch.object(chat_socket, "WsSession", return_value=db),
            patch.object(chat_socket, "Message", _Message),
            patch.object(chat_socket, "require_consultation_access") as authorize,
        ):
            result = chat_socket.save_message_sync(7, 5, "hello")

        authorize.assert_called_once_with(
            db,
            7,
            current_user,
            allow_completed=False,
            allow_message_grace=True,
        )
        self.assertTrue(db.committed)
        self.assertTrue(db.closed)
        self.assertEqual(len(db.added), 1)
        self.assertEqual(result["id"], 81)
        self.assertEqual(result["content"], "hello")

    def test_chat_message_rejects_unauthorized_participant(self):
        current_user = SimpleNamespace(id=99)
        db = _MessageDb(current_user)

        with (
            patch.object(chat_socket, "WsSession", return_value=db),
            patch.object(
                chat_socket,
                "require_consultation_access",
                side_effect=HTTPException(status_code=403, detail="forbidden"),
            ),
        ):
            result = chat_socket.save_message_sync(7, 99, "no access")

        self.assertEqual(result, {"error": "consultation_unavailable"})
        self.assertFalse(db.committed)
        self.assertEqual(db.added, [])

    def _issue_video_token(self, *, appointment_id, current_user, appointment):
        endpoint = inspect.unwrap(video.get_agora_token)
        with (
            patch.object(video, "require_consultation_access", return_value=appointment) as authorize,
            patch.object(video.RtcTokenBuilder, "buildTokenWithUid", return_value="token") as build,
            patch.dict(
                video.os.environ,
                {"AGORA_APP_ID": "app-id", "AGORA_APP_CERTIFICATE": "certificate"},
            ),
        ):
            result = endpoint(
                request=SimpleNamespace(),
                appointment_id=appointment_id,
                current_user=current_user,
                db=_VideoDb(),
            )
        authorize.assert_called_once_with(
            ANY,
            appointment_id,
            current_user,
            allow_completed=False,
        )
        self.assertEqual(build.call_args.args[3], result["uid"])
        return result

    @staticmethod
    def _appointment(*, patient_id=5, doctor_user_id=9):
        return SimpleNamespace(
            patient_id=patient_id,
            doctor=SimpleNamespace(user_id=doctor_user_id),
            consultation_started_at=datetime.utcnow() - timedelta(minutes=2),
        )

    def test_patient_always_gets_uid_one_and_cannot_obtain_doctor_identity(self):
        appointment = self._appointment()
        patient = SimpleNamespace(id=5)

        first = self._issue_video_token(
            appointment_id=7,
            current_user=patient,
            appointment=appointment,
        )
        renewed = self._issue_video_token(
            appointment_id=7,
            current_user=patient,
            appointment=appointment,
        )

        self.assertEqual(first["uid"], 1)
        self.assertEqual(renewed["uid"], 1)

    def test_assigned_doctor_always_gets_uid_two_and_cannot_obtain_patient_identity(self):
        appointment = self._appointment()
        doctor = SimpleNamespace(id=9)

        first = self._issue_video_token(
            appointment_id=7,
            current_user=doctor,
            appointment=appointment,
        )
        renewed = self._issue_video_token(
            appointment_id=7,
            current_user=doctor,
            appointment=appointment,
        )

        self.assertEqual(first["uid"], 2)
        self.assertEqual(renewed["uid"], 2)

    def test_video_token_endpoint_accepts_no_client_uid_override(self):
        endpoint = inspect.unwrap(video.get_agora_token)
        self.assertNotIn("uid", inspect.signature(endpoint).parameters)
        with self.assertRaises(TypeError):
            endpoint(
                request=SimpleNamespace(),
                appointment_id=7,
                uid=2,
                current_user=SimpleNamespace(id=5),
                db=_VideoDb(),
            )

    def test_separate_appointments_reuse_uids_in_distinct_channels(self):
        patient = SimpleNamespace(id=5)
        appointment = self._appointment()

        first = self._issue_video_token(
            appointment_id=7,
            current_user=patient,
            appointment=appointment,
        )
        second = self._issue_video_token(
            appointment_id=8,
            current_user=patient,
            appointment=appointment,
        )

        self.assertEqual(first["uid"], second["uid"])
        self.assertEqual(first["uid"], 1)
        self.assertEqual(first["channel"], "appt_7")
        self.assertEqual(second["channel"], "appt_8")

    def test_video_token_rejects_unauthorized_participant(self):
        endpoint = inspect.unwrap(video.get_agora_token)
        forbidden = HTTPException(status_code=403, detail="forbidden")

        with patch.object(
            video,
            "require_consultation_access",
            side_effect=forbidden,
        ):
            with self.assertRaises(HTTPException) as raised:
                endpoint(
                    request=SimpleNamespace(),
                    appointment_id=7,
                    current_user=SimpleNamespace(id=99),
                    db=_VideoDb(),
                )

        self.assertEqual(raised.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
