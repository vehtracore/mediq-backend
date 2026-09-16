import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1.notifications import (
    get_notifications,
    get_unread_count,
    mark_all_notifications_read,
    mark_notification_read,
)
from app.api.v1 import appointments, family, payments
from app.core.database import Base
from app.core.notification_transport import PushDeliveryResult
from app.models.appointment import Appointment, DoctorSlot
from app.models.doctor import Doctor
from app.models.notification import Notification
from app.models.notification_device_token import NotificationDeviceToken
from app.models.review import Review
from app.schemas.appointment import AppointmentProposeRequest, ReferralRequest
from app.models.user import User
from app.services.notification_device_service import (
    claim_device_token,
    unregister_device_token,
)
from app.services.notification_service import (
    NotificationType,
    notify_user,
    room_ready_event_key,
)


class ReliableNotificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handle, cls.database_path = tempfile.mkstemp(suffix='.sqlite3')
        os.close(handle)
        cls.engine = create_engine(
            f'sqlite:///{cls.database_path}',
            connect_args={'check_same_thread': False},
        )
        cls.tables = [
            User.__table__,
            Doctor.__table__,
            DoctorSlot.__table__,
            Appointment.__table__,
            Review.__table__,
            NotificationDeviceToken.__table__,
            Notification.__table__,
        ]
        Base.metadata.create_all(cls.engine, tables=cls.tables)
        cls.Session = sessionmaker(bind=cls.engine, expire_on_commit=False)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        try:
            os.remove(cls.database_path)
        except PermissionError:
            pass

    def setUp(self):
        self.db = self.Session()
        for table in reversed(self.tables):
            self.db.execute(table.delete())
        self.db.add_all([
            User(id=1, email='a@example.test', role='patient', settings_notifications=True),
            User(id=2, email='b@example.test', role='patient', settings_notifications=True),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _claim(self, user_id, installation_id, token):
        return claim_device_token(
            self.db,
            user_id=user_id,
            installation_id=installation_id,
            token=token,
            platform='android',
        )

    @patch('app.api.v1.appointments.require_vip_requested_doctor')
    @patch('app.services.notification_service.notification_transport.send_multicast_notification')
    def test_vip_proposal_notifies_patient_after_status_commit(self, _send, _doctor_gate):
        appointment = Appointment(
            id=42,
            patient_id=1,
            doctor_id=7,
            appointment_type='vip_request',
            status='pending',
            payment_status='unpaid',
            start_time=None,
        )
        self.db.add(appointment)
        self.db.commit()

        appointments.propose_appointment_time(
            42,
            AppointmentProposeRequest(
                proposed_time=datetime.now(timezone.utc) + timedelta(days=1)
            ),
            db=self.db,
            current_user=self.db.get(User, 2),
        )

        self.assertEqual(self.db.get(Appointment, 42).status, 'awaiting_payment')
        event = self.db.query(Notification).one()
        self.assertEqual(event.user_id, 1)
        self.assertEqual(event.type, NotificationType.CONSULTATION_TIME_PROPOSED)
        self.assertEqual(event.navigation_data, {'appointment_id': '42'})

    def test_same_token_reassigned_between_accounts_has_one_owner(self):
        self._claim(1, '11111111-1111-4111-8111-111111111111', 'shared-token')
        self._claim(2, '22222222-2222-4222-8222-222222222222', 'shared-token')
        rows = self.db.query(NotificationDeviceToken).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].user_id, 2)

    def test_same_user_supports_two_installations_and_refresh_updates(self):
        first_id = '11111111-1111-4111-8111-111111111111'
        second_id = '22222222-2222-4222-8222-222222222222'
        self._claim(1, first_id, 'token-1')
        self._claim(1, second_id, 'token-2')
        self._claim(1, first_id, 'token-1-refreshed')
        rows = self.db.query(NotificationDeviceToken).order_by(
            NotificationDeviceToken.installation_id
        ).all()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].token, 'token-1-refreshed')

    def test_logout_unregisters_only_authenticated_installation(self):
        first_id = '11111111-1111-4111-8111-111111111111'
        second_id = '22222222-2222-4222-8222-222222222222'
        self._claim(1, first_id, 'token-1')
        self._claim(2, second_id, 'token-2')
        self.assertTrue(unregister_device_token(
            self.db, user_id=1, installation_id=first_id
        ))
        remaining = self.db.query(NotificationDeviceToken).one()
        self.assertEqual(remaining.user_id, 2)

    @patch('app.services.notification_service.notification_transport.send_multicast_notification')
    def test_preference_off_keeps_durable_record_and_skips_push(self, send):
        user = self.db.query(User).filter(User.id == 1).one()
        user.settings_notifications = False
        self.db.commit()
        self._claim(1, '11111111-1111-4111-8111-111111111111', 'token-1')
        notify_user(
            self.db,
            user_id=1,
            notification_type=NotificationType.CONSULTATION_CONFIRMED,
            navigation_data={'appointment_id': 8},
            event_key='appointment:8:confirmed:1',
        )
        self.assertEqual(self.db.query(Notification).count(), 1)
        send.assert_not_called()

    @patch('app.services.notification_service.notification_transport.send_multicast_notification')
    def test_dispatches_all_devices_and_removes_only_permanent_failures(self, send):
        self._claim(1, '11111111-1111-4111-8111-111111111111', 'token-1')
        self._claim(1, '22222222-2222-4222-8222-222222222222', 'token-2')
        send.return_value = PushDeliveryResult(
            successful_count=1,
            permanent_failure_tokens=('token-1',),
            transient_failure_count=0,
        )
        notify_user(
            self.db,
            user_id=1,
            notification_type=NotificationType.PAYOUT_SENT,
            event_key='payout:1:sent:1',
        )
        self.assertCountEqual(send.call_args.kwargs['tokens'], ['token-1', 'token-2'])
        rows = self.db.query(NotificationDeviceToken).all()
        self.assertEqual([row.token for row in rows], ['token-2'])

    @patch('app.services.notification_service.notification_transport.send_multicast_notification')
    def test_transient_failure_retains_token(self, send):
        self._claim(1, '11111111-1111-4111-8111-111111111111', 'token-1')
        send.return_value = PushDeliveryResult(transient_failure_count=1)
        notify_user(
            self.db,
            user_id=1,
            notification_type=NotificationType.SUBSCRIPTION_PAYMENT_FAILED,
            event_key='invoice:failed:1',
        )
        self.assertEqual(self.db.query(NotificationDeviceToken).count(), 1)

    @patch('app.services.notification_service.notification_transport.send_multicast_notification')
    def test_dedupe_and_push_failure_do_not_rollback_business_state(self, send):
        self._claim(1, '11111111-1111-4111-8111-111111111111', 'token-1')
        user = self.db.query(User).filter(User.id == 1).one()
        user.plan = 'premium'
        self.db.commit()
        send.side_effect = RuntimeError('provider unavailable')
        for _ in range(2):
            notify_user(
                self.db,
                user_id=1,
                notification_type=NotificationType.SUBSCRIPTION_ACTIVATED,
                event_key='subscription:event-1:activated:1',
            )
        self.assertEqual(self.db.query(Notification).count(), 1)
        self.assertEqual(self.db.query(User).filter(User.id == 1).one().plan, 'premium')

    def test_center_is_newest_first_readable_and_account_isolated(self):
        now = datetime.now(timezone.utc)
        self.db.add_all([
            Notification(
                user_id=1, title='Old', body='Old', type='test',
                navigation_data={}, created_at=now - timedelta(minutes=1),
            ),
            Notification(
                user_id=1, title='New', body='New', type='test',
                navigation_data={}, created_at=now,
            ),
            Notification(
                user_id=2, title='Other', body='Other', type='test',
                navigation_data={}, created_at=now,
            ),
        ])
        self.db.commit()
        user_a = self.db.query(User).filter(User.id == 1).one()
        rows = get_notifications(db=self.db, current_user=user_a, limit=None, offset=0)
        self.assertEqual([row.title for row in rows], ['New', 'Old'])
        self.assertEqual(get_unread_count(db=self.db, current_user=user_a).unread_count, 2)
        mark_notification_read(rows[0].id, db=self.db, current_user=user_a)
        self.assertEqual(get_unread_count(db=self.db, current_user=user_a).unread_count, 1)
        result = mark_all_notifications_read(db=self.db, current_user=user_a)
        self.assertEqual(result.updated_count, 1)
        other = self.db.query(Notification).filter(Notification.user_id == 2).one()
        self.assertFalse(other.is_read)

    @patch('app.api.v1.family._decode_invite_token', return_value=(1, 'invite-nonce'))
    def test_family_join_creates_durable_events_for_both_accounts(self, _decode):
        primary = self.db.query(User).filter(User.id == 1).one()
        member = self.db.query(User).filter(User.id == 2).one()
        primary.plan = 'family'
        primary.family_invite_nonce = 'invite-nonce'
        primary.family_invite_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        self.db.commit()
        family.join_family(
            body=family.JoinRequest(invite_code='fixture'),
            current_user=member,
            db=self.db,
        )
        self.assertCountEqual(
            [row.type for row in self.db.query(Notification).all()],
            ['family_member_joined', 'family_joined'],
        )

    def test_referral_transition_creates_safe_durable_event(self):
        patient = self.db.query(User).filter(User.id == 1).one()
        doctor_user = self.db.query(User).filter(User.id == 2).one()
        doctor_user.role = 'doctor'
        doctor = Doctor(
            id=1,
            user_id=doctor_user.id,
            full_name='Fixture Doctor',
            specialty='General',
            license_number='FIXTURE-1',
            status='active',
            is_verified=True,
        )
        appointment = Appointment(
            id=10,
            patient_id=patient.id,
            doctor_id=doctor.id,
            status='confirmed',
            payment_status='paid',
            amount=4000,
        )
        self.db.add_all([doctor, appointment])
        self.db.commit()
        appointments.refer_patient_to_hospital(
            appt_id=appointment.id,
            referral=ReferralRequest(
                hospital_name='Fixture Hospital',
                note='Sensitive fixture detail',
            ),
            db=self.db,
            current_user=doctor_user,
        )
        record = self.db.query(Notification).one()
        self.assertEqual(record.type, 'referral_created')
        self.assertNotIn('Sensitive fixture detail', record.body)
        self.assertEqual(record.navigation_data, {'appointment_id': '10'})

    def test_existing_accept_event_creates_one_durable_notification(self):
        doctor_user = self.db.query(User).filter(User.id == 2).one()
        doctor_user.role = 'doctor'
        doctor = Doctor(
            id=2,
            user_id=doctor_user.id,
            full_name='Fixture Doctor',
            specialty='General',
            license_number='FIXTURE-2',
            status='active',
            is_verified=True,
        )
        appointment = Appointment(
            id=11,
            patient_id=1,
            doctor_id=doctor.id,
            status='pending',
            payment_status='paid',
            amount=4000,
        )
        self.db.add_all([doctor, appointment])
        self.db.commit()
        appointments.accept_appointment(
            appt_id=appointment.id,
            db=self.db,
            current_user=doctor_user,
        )
        record = self.db.query(Notification).one()
        self.assertEqual(record.type, 'consultation_confirmed')
        self.assertEqual(record.user_id, 1)

    def test_room_ready_window_is_database_deduplicated(self):
        event_key = room_ready_event_key(appointment_id=12, user_id=1)
        for _ in range(2):
            notify_user(
                self.db,
                user_id=1,
                notification_type=NotificationType.CONSULTATION_ROOM_READY,
                navigation_data={'appointment_id': 12},
                event_key=event_key,
            )
        self.assertEqual(self.db.query(Notification).count(), 1)

    def test_consultation_copy_excludes_names_and_clinical_details(self):
        user = self.db.query(User).filter(User.id == 1).one()
        user.first_name = 'SensitiveName'
        self.db.commit()
        notify_user(
            self.db,
            user_id=1,
            notification_type=NotificationType.CONSULTATION_REQUEST,
            navigation_data={'appointment_id': 13},
            event_key='appointment:13:request:1',
        )
        record = self.db.query(Notification).one()
        rendered = f'{record.title} {record.body}'.lower()
        self.assertNotIn('sensitivename', rendered)
        self.assertNotIn('diagnosis', rendered)
        self.assertNotIn('medication', rendered)

    def test_payout_result_still_creates_durable_notification(self):
        payments._emit_payment_notification(
            self.db,
            result={
                'action': 'consultation_payout_confirmed',
                'user_id': 2,
                'appointment_id': 14,
            },
            provider_event_key='test:transfer.success:fixture',
        )
        record = self.db.query(Notification).one()
        self.assertEqual(record.type, 'payout_sent')
        self.assertNotIn('amount', record.body.lower())


if __name__ == '__main__':
    unittest.main()
