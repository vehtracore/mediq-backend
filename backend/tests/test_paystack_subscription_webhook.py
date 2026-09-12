import asyncio
import hashlib
import hmac
import json
import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.api.v1 import payments
from app.core.database import Base
from app.models.appointment import (
    APPOINTMENT_TYPE_GENERAL_QUEUE,
    Appointment,
    DoctorSlot,
)
from app.models.consultation_payout import ConsultationPayout
from app.models.doctor import Doctor
from app.models.failed_webhook import FailedWebhook
from app.models.payment_event import PaymentEvent
from app.models.notification import Notification
from app.models.notification_device_token import NotificationDeviceToken
from app.models.review import Review  # noqa: F401 - resolves ORM relationship
from app.models.user import User


class PaystackSubscriptionWebhookTests(unittest.TestCase):
    secret = 'fixture-webhook-secret'

    @classmethod
    def setUpClass(cls):
        handle, cls.database_path = tempfile.mkstemp(suffix='.sqlite3')
        os.close(handle)
        cls.engine = create_engine(
            f'sqlite:///{cls.database_path}',
            connect_args={'check_same_thread': False, 'timeout': 10},
        )
        cls.tables = [
            User.__table__,
            Doctor.__table__,
            DoctorSlot.__table__,
            Appointment.__table__,
            Review.__table__,
            ConsultationPayout.__table__,
            FailedWebhook.__table__,
            PaymentEvent.__table__,
            NotificationDeviceToken.__table__,
            Notification.__table__,
        ]
        Base.metadata.create_all(cls.engine, tables=cls.tables)
        cls.Session = sessionmaker(
            bind=cls.engine,
            autoflush=False,
            expire_on_commit=False,
        )

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
        self.db.commit()
        self.original_secret = payments.PAYSTACK_SECRET_KEY
        self.original_environment = os.environ.get('PAYSTACK_ENVIRONMENT')
        payments.PAYSTACK_SECRET_KEY = self.secret
        os.environ['PAYSTACK_ENVIRONMENT'] = 'test'
        self.user = self._add_paid_user()

    def tearDown(self):
        self.db.close()
        payments.PAYSTACK_SECRET_KEY = self.original_secret
        if self.original_environment is None:
            os.environ.pop('PAYSTACK_ENVIRONMENT', None)
        else:
            os.environ['PAYSTACK_ENVIRONMENT'] = self.original_environment

    def _add_paid_user(self, *, user_id=1, environment='test'):
        user = User(
            id=user_id,
            email=f'patient{user_id}@example.test',
            first_name='Test',
            last_name='Patient',
            role='patient',
            is_active=True,
            is_banned=False,
            plan='premium',
            subscription_expiry=datetime(2026, 7, 31),
            auto_renew=True,
            paystack_subscription_code=f'SUB_fixture_{user_id}',
            paystack_customer_code=f'CUS_fixture_{user_id}',
            paystack_plan_code=payments.PAYSTACK_INDIVIDUAL_PLAN_CODE,
            paystack_environment=environment,
            paystack_subscription_status='active',
        )
        self.db.add(user)
        self.db.commit()
        return user

    def _invoice_payload(self, **overrides):
        data = {
            'domain': 'test',
            'invoice_code': 'INV_renewal_001',
            'amount': payments.INDIVIDUAL_SUBSCRIPTION_AMOUNT_KOBO,
            'period_start': '2026-07-13T00:00:00Z',
            'period_end': '2026-08-12T23:59:59Z',
            'status': 'success',
            'paid': True,
            'paid_at': '2026-07-13T08:00:00Z',
            'subscription': {
                'status': 'active',
                'subscription_code': self.user.paystack_subscription_code,
                'next_payment_date': '2026-08-13T08:00:00Z',
                'plan': {
                    'plan_code': payments.PAYSTACK_INDIVIDUAL_PLAN_CODE,
                },
            },
            'customer': {
                'email': self.user.email,
                'customer_code': self.user.paystack_customer_code,
            },
            'transaction': {
                'reference': 'renewal-reference-001',
                'status': 'success',
                'amount': payments.INDIVIDUAL_SUBSCRIPTION_AMOUNT_KOBO,
                'currency': 'NGN',
                'domain': 'test',
            },
        }
        for key, value in overrides.items():
            if key.startswith('transaction_'):
                data['transaction'][key.removeprefix('transaction_')] = value
            elif key.startswith('subscription_'):
                data['subscription'][key.removeprefix('subscription_')] = value
            elif key.startswith('customer_'):
                data['customer'][key.removeprefix('customer_')] = value
            else:
                data[key] = value
        return {'event': 'invoice.update', 'data': data}

    def _recurring_charge_payload(self):
        invoice = self._invoice_payload()['data']
        return {
            'event': 'charge.success',
            'data': {
                'domain': 'test',
                'status': 'success',
                'reference': invoice['transaction']['reference'],
                'amount': invoice['amount'],
                'currency': 'NGN',
                'metadata': '',
                'subscription': invoice['subscription'],
                'customer': invoice['customer'],
                'paid_at': invoice['paid_at'],
            },
        }

    def _initial_charge_payload(self, user: User):
        reference = f'MDQ-subscription-0-{user.id}-1783929600000'
        return {
            'event': 'charge.success',
            'data': {
                'domain': 'test',
                'status': 'success',
                'reference': reference,
                'amount': payments.INDIVIDUAL_SUBSCRIPTION_AMOUNT_KOBO,
                'currency': 'NGN',
                'paid_at': '2026-07-13T08:00:00Z',
                'metadata': {
                    'transaction_type': 'subscription',
                    'user_id': str(user.id),
                },
                'plan': {
                    'plan_code': payments.PAYSTACK_INDIVIDUAL_PLAN_CODE,
                },
                'subscription': {
                    'status': 'active',
                    'subscription_code': f'SUB_initial_{user.id}',
                    'next_payment_date': '2026-08-13T08:00:00Z',
                },
                'customer': {
                    'email': user.email,
                    'customer_code': f'CUS_initial_{user.id}',
                },
            },
        }

    def _request(self, body: bytes, signature):
        headers = [(b'content-length', str(len(body)).encode())]
        if signature is not None:
            headers.append((b'x-paystack-signature', signature.encode()))
        delivered = False

        async def receive():
            nonlocal delivered
            if delivered:
                return {'type': 'http.disconnect'}
            delivered = True
            return {
                'type': 'http.request',
                'body': body,
                'more_body': False,
            }

        return Request(
            {
                'type': 'http',
                'method': 'POST',
                'path': '/api/v1/payments/webhook',
                'headers': headers,
            },
            receive,
        )

    def _send(self, payload=None, *, raw=None, sign=True, db=None):
        body = raw if raw is not None else json.dumps(
            payload,
            separators=(',', ':'),
        ).encode()
        signature = None
        if sign:
            signature = hmac.new(
                self.secret.encode(),
                body,
                hashlib.sha512,
            ).hexdigest()
        request = self._request(body, signature)
        return asyncio.run(
            payments.paystack_webhook(
                request,
                BackgroundTasks(),
                db or self.db,
            )
        )

    def _refresh_user(self, user_id=1):
        self.db.expire_all()
        return self.db.query(User).filter(User.id == user_id).one()

    def test_valid_signed_recurring_charge_is_recognised_without_metadata(self):
        original_expiry = self.user.subscription_expiry
        result = self._send(self._recurring_charge_payload())
        self.assertEqual(result['action'], 'recurring_charge_observed')
        self.assertEqual(self._refresh_user().subscription_expiry, original_expiry)

    def test_valid_signed_invoice_update_applies_renewal(self):
        result = self._send(self._invoice_payload())
        user = self._refresh_user()
        self.assertEqual(result['action'], 'subscription_payment_applied')
        self.assertEqual(user.subscription_expiry, datetime(2026, 8, 13, 8))
        self.assertEqual(
            user.paystack_last_payment_reference,
            'renewal-reference-001',
        )
        self.assertEqual(user.paystack_latest_invoice_code, 'INV_renewal_001')
        self.assertEqual(
            self.db.query(Notification).one().type,
            'subscription_activated',
        )

    def test_automatic_renewal_does_not_require_transaction_type(self):
        payload = self._invoice_payload()
        payload['data']['metadata'] = {}
        result = self._send(payload)
        self.assertEqual(result['action'], 'subscription_payment_applied')
        self.assertEqual(self._refresh_user().plan, 'premium')

    def test_duplicate_invoice_delivery_extends_once(self):
        first = self._send(self._invoice_payload())
        first_expiry = self._refresh_user().subscription_expiry
        second = self._send(self._invoice_payload())
        self.assertEqual(first['action'], 'subscription_payment_applied')
        self.assertEqual(second['action'], 'duplicate_event_ignored')
        self.assertEqual(self._refresh_user().subscription_expiry, first_expiry)
        self.assertEqual(self.db.query(PaymentEvent).count(), 1)

    def test_charge_then_invoice_extends_once(self):
        self._send(self._recurring_charge_payload())
        self._send(self._invoice_payload())
        expiry = self._refresh_user().subscription_expiry
        self._send(self._recurring_charge_payload())
        self.assertEqual(self._refresh_user().subscription_expiry, expiry)
        self.assertEqual(expiry, datetime(2026, 8, 13, 8))

    def test_invoice_then_charge_out_of_order_does_not_extend_twice(self):
        self._send(self._invoice_payload())
        expiry = self._refresh_user().subscription_expiry
        result = self._send(self._recurring_charge_payload())
        self.assertEqual(result['action'], 'recurring_charge_observed')
        self.assertEqual(self._refresh_user().subscription_expiry, expiry)

    def test_initial_subscription_payment_still_works(self):
        user = User(
            id=2,
            email='new-subscriber@example.test',
            first_name='New',
            last_name='Subscriber',
            role='patient',
            is_active=True,
            is_banned=False,
            plan='free',
            auto_renew=False,
        )
        self.db.add(user)
        self.db.commit()
        result = self._send(self._initial_charge_payload(user))
        refreshed = self._refresh_user(2)
        self.assertEqual(result['action'], 'subscription_payment_applied')
        self.assertEqual(refreshed.plan, 'premium')
        self.assertEqual(
            refreshed.paystack_subscription_code,
            'SUB_initial_2',
        )

    def test_consultation_charge_still_confirms_appointment(self):
        reference = 'MDQ-gp_consult-10-1-1783929600000'
        appointment = Appointment(
            id=10,
            patient_id=self.user.id,
            doctor_id=None,
            appointment_type=APPOINTMENT_TYPE_GENERAL_QUEUE,
            status='pending',
            payment_status='unpaid',
            amount=4000,
            paystack_reference=reference,
        )
        self.db.add(appointment)
        self.db.commit()
        payload = {
            'event': 'charge.success',
            'data': {
                'domain': 'test',
                'status': 'success',
                'reference': reference,
                'amount': 400000,
                'currency': 'NGN',
                'paid_at': '2026-07-13T08:00:00Z',
                'customer': {
                    'email': self.user.email,
                    'customer_code': self.user.paystack_customer_code,
                },
            },
        }
        result = self._send(payload)
        self.db.expire_all()
        stored = self.db.query(Appointment).filter(Appointment.id == 10).one()
        self.assertEqual(result['action'], 'appointment_confirmed')
        self.assertEqual(stored.payment_status, 'paid')
        self.assertEqual(
            self.db.query(Notification).one().type,
            'consultation_payment_confirmed',
        )

    def test_missing_signature_is_rejected_before_database_write(self):
        with self.assertRaises(HTTPException) as raised:
            self._send(self._invoice_payload(), sign=False)
        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(self.db.query(PaymentEvent).count(), 0)

    def test_invalid_signature_is_rejected_before_database_write(self):
        body = json.dumps(self._invoice_payload()).encode()
        request = self._request(body, 'invalid')
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                payments.paystack_webhook(
                    request,
                    BackgroundTasks(),
                    self.db,
                )
            )
        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(self.db.query(PaymentEvent).count(), 0)

    def test_signed_malformed_json_is_rejected(self):
        with self.assertRaises(HTTPException) as raised:
            self._send(raw=b'{not-json')
        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(self.db.query(PaymentEvent).count(), 0)

    def test_unknown_event_is_safely_acknowledged(self):
        result = self._send(
            {
                'event': 'customeridentification.success',
                'data': {'reference': 'safe-reference'},
            }
        )
        self.assertEqual(result['action'], 'unknown_event_ignored')
        self.assertEqual(self.db.query(PaymentEvent).count(), 0)

    def test_renewal_for_unknown_subscription_is_not_acknowledged_as_success(self):
        payload = self._invoice_payload(
            subscription_subscription_code='SUB_unknown',
            customer_customer_code='CUS_unknown',
            customer_email='unknown@example.test',
        )
        with self.assertRaises(HTTPException) as raised:
            self._send(payload)
        self.assertEqual(raised.exception.status_code, 500)
        event = self.db.query(PaymentEvent).one()
        self.assertEqual(event.processing_status, 'failed')
        self.assertEqual(event.error_code, 'subscription_not_found')

    def test_amount_mismatch_does_not_extend_subscription(self):
        original_expiry = self.user.subscription_expiry
        with self.assertRaises(HTTPException):
            self._send(self._invoice_payload(amount=1))
        self.assertEqual(self._refresh_user().subscription_expiry, original_expiry)
        self.assertEqual(
            self.db.query(PaymentEvent).one().error_code,
            'amount_mismatch',
        )

    def test_currency_mismatch_does_not_extend_subscription(self):
        original_expiry = self.user.subscription_expiry
        with self.assertRaises(HTTPException):
            self._send(self._invoice_payload(transaction_currency='USD'))
        self.assertEqual(self._refresh_user().subscription_expiry, original_expiry)
        self.assertEqual(
            self.db.query(PaymentEvent).one().error_code,
            'currency_mismatch',
        )

    def test_plan_mismatch_does_not_extend_subscription(self):
        original_expiry = self.user.subscription_expiry
        with self.assertRaises(HTTPException):
            self._send(
                self._invoice_payload(
                    subscription_plan={'plan_code': 'PLN_wrong'},
                )
            )
        self.assertEqual(self._refresh_user().subscription_expiry, original_expiry)
        self.assertEqual(
            self.db.query(PaymentEvent).one().error_code,
            'plan_mismatch',
        )

    def test_failed_renewal_preserves_paid_access(self):
        original_expiry = self.user.subscription_expiry
        payload = self._invoice_payload(
            status='failed',
            paid=False,
            transaction_status='failed',
        )
        payload['event'] = 'invoice.payment_failed'
        result = self._send(payload)
        user = self._refresh_user()
        self.assertEqual(result['action'], 'subscription_payment_failed')
        self.assertEqual(user.subscription_expiry, original_expiry)
        self.assertEqual(user.plan, 'premium')
        self.assertEqual(user.paystack_subscription_status, 'attention')
        self.assertEqual(
            self.db.query(Notification).one().type,
            'subscription_payment_failed',
        )

    def test_subscription_disable_preserves_unexpired_access(self):
        future_expiry = datetime.utcnow() + timedelta(days=30)
        self.user.subscription_expiry = future_expiry
        self.db.commit()
        payload = {
            'event': 'subscription.disable',
            'data': {
                'domain': 'test',
                'status': 'cancelled',
                'subscription_code': self.user.paystack_subscription_code,
                'customer': {
                    'email': self.user.email,
                    'customer_code': self.user.paystack_customer_code,
                },
            },
        }
        result = self._send(payload)
        user = self._refresh_user()
        self.assertEqual(result['action'], 'subscription_lifecycle_updated')
        self.assertFalse(user.auto_renew)
        self.assertEqual(user.plan, 'premium')
        self.assertEqual(user.subscription_expiry, future_expiry)
        self.assertEqual(
            self.db.query(Notification).one().type,
            'subscription_cancelled',
        )

    def test_subscription_not_renew_is_idempotent(self):
        payload = {
            'event': 'subscription.not_renew',
            'data': {
                'domain': 'test',
                'status': 'non-renewing',
                'subscription_code': self.user.paystack_subscription_code,
                'customer': {
                    'email': self.user.email,
                    'customer_code': self.user.paystack_customer_code,
                },
            },
        }
        self._send(payload)
        second = self._send(payload)
        self.assertEqual(second['action'], 'duplicate_event_ignored')
        self.assertEqual(
            self._refresh_user().paystack_subscription_status,
            'non-renewing',
        )
        self.assertEqual(self.db.query(Notification).count(), 1)

    def test_subscription_create_binds_identifiers_without_granting_access(self):
        user = User(
            id=3,
            email='created-subscription@example.test',
            first_name='Created',
            last_name='Subscription',
            role='patient',
            is_active=True,
            is_banned=False,
            plan='free',
            auto_renew=False,
        )
        self.db.add(user)
        self.db.commit()
        payload = {
            'event': 'subscription.create',
            'data': {
                'domain': 'test',
                'status': 'active',
                'subscription_code': 'SUB_created_3',
                'plan': {
                    'plan_code': payments.PAYSTACK_INDIVIDUAL_PLAN_CODE,
                },
                'customer': {
                    'email': user.email,
                    'customer_code': 'CUS_created_3',
                    'metadata': {'user_id': '3'},
                },
                'next_payment_date': '2026-08-13T08:00:00Z',
            },
        }
        result = self._send(payload)
        stored = self._refresh_user(3)
        self.assertEqual(result['action'], 'subscription_identifiers_persisted')
        self.assertEqual(stored.paystack_subscription_code, 'SUB_created_3')
        self.assertEqual(stored.paystack_customer_code, 'CUS_created_3')
        self.assertEqual(stored.plan, 'free')
        self.assertIsNone(stored.subscription_expiry)

    def test_database_failure_rolls_back_entitlement_mutation(self):
        original_expiry = self.user.subscription_expiry
        with patch.object(
            payments,
            '_mark_payment_event_processed',
            side_effect=RuntimeError('injected failure'),
        ):
            with self.assertRaises(HTTPException):
                self._send(self._invoice_payload())
        self.assertEqual(self._refresh_user().subscription_expiry, original_expiry)
        self.assertEqual(
            self.db.query(PaymentEvent).one().processing_status,
            'failed',
        )
        stored = self.db.query(FailedWebhook).one()
        self.assertNotIn('authorization', stored.payload)
        self.assertNotIn(self.user.email, stored.payload)

    def _manual_subscription_data(self, reference):
        data = self._recurring_charge_payload()['data']
        data['reference'] = reference
        data['metadata'] = {
            'transaction_type': 'subscription',
            'user_id': str(self.user.id),
        }
        return data

    def test_manual_verification_after_webhook_is_idempotent(self):
        reference = 'MDQ-subscription-0-1-1783929600001'
        data = self._manual_subscription_data(reference)
        self._send({'event': 'charge.success', 'data': data})
        expiry = self._refresh_user().subscription_expiry
        result = payments._process_manual_verified_transaction(
            transaction_type='subscription',
            ref_appointment_id='0',
            ref_user_id='1',
            reference=reference,
            tx_data=data,
            db=self.db,
            background_tasks=BackgroundTasks(),
            current_user=self.user,
        )
        self.assertEqual(result['action'], 'payment_already_processed')
        self.assertEqual(self._refresh_user().subscription_expiry, expiry)

    def test_webhook_after_manual_verification_is_idempotent(self):
        reference = 'MDQ-subscription-0-1-1783929600002'
        data = self._manual_subscription_data(reference)
        payments._process_manual_verified_transaction(
            transaction_type='subscription',
            ref_appointment_id='0',
            ref_user_id='1',
            reference=reference,
            tx_data=data,
            db=self.db,
            background_tasks=BackgroundTasks(),
            current_user=self.user,
        )
        expiry = self._refresh_user().subscription_expiry
        result = self._send({'event': 'charge.success', 'data': data})
        self.assertEqual(result['action'], 'duplicate_event_ignored')
        self.assertEqual(self._refresh_user().subscription_expiry, expiry)

    def test_manual_verification_rejects_another_users_reference(self):
        with self.assertRaises(HTTPException) as raised:
            payments._validate_reference_owner_before_paystack(
                reference='MDQ-subscription-0-2-1783929600003',
                db=self.db,
                current_user=self.user,
            )
        self.assertEqual(raised.exception.status_code, 403)

    def test_test_event_cannot_update_live_subscription(self):
        self.user.paystack_environment = 'live'
        self.db.commit()
        original_expiry = self.user.subscription_expiry
        with self.assertRaises(HTTPException):
            self._send(self._invoice_payload())
        self.assertEqual(self._refresh_user().subscription_expiry, original_expiry)

    def test_customer_mismatch_does_not_update_subscription(self):
        original_expiry = self.user.subscription_expiry
        with self.assertRaises(HTTPException):
            self._send(
                self._invoice_payload(
                    customer_customer_code='CUS_different',
                )
            )
        self.assertEqual(self._refresh_user().subscription_expiry, original_expiry)
        self.assertEqual(
            self.db.query(PaymentEvent).one().error_code,
            'customer_code_mismatch',
        )

    def test_missing_server_secret_fails_closed(self):
        payments.PAYSTACK_SECRET_KEY = ''
        with self.assertRaises(HTTPException) as raised:
            self._send(self._invoice_payload())
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(self.db.query(PaymentEvent).count(), 0)

    def _initialize_handler(self):
        handler = payments.initialize_transaction
        while hasattr(handler, '__wrapped__'):
            handler = handler.__wrapped__
        return handler

    def test_initialization_rejects_client_plan_substitution(self):
        request = self._request(b'', None)
        payload = payments.PaymentInitializeRequest(
            email='attacker@example.com',
            amount=payments.INDIVIDUAL_SUBSCRIPTION_AMOUNT_KOBO,
            reference='MDQ-subscription-0-1-1783929600004',
            plan='PLN_cheaper_plan',
        )
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                self._initialize_handler()(
                    request,
                    payload,
                    self.db,
                    self.user,
                )
            )
        self.assertEqual(raised.exception.status_code, 400)

    def test_initialization_uses_authenticated_email_and_server_plan(self):
        captured = {}

        class FakeResponse:
            is_success = True
            status_code = 200

            def json(self):
                return {
                    'status': True,
                    'data': {
                        'authorization_url': 'https://checkout.example.test',
                        'access_code': 'fixture-access-code',
                    },
                }

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, *, headers, json):
                captured['url'] = url
                captured['body'] = json
                return FakeResponse()

        request = self._request(b'', None)
        payload = payments.PaymentInitializeRequest(
            email='attacker@example.com',
            amount=payments.INDIVIDUAL_SUBSCRIPTION_AMOUNT_KOBO,
            reference='MDQ-subscription-0-1-1783929600005',
            plan=None,
        )
        with patch.object(
            payments.httpx,
            'AsyncClient',
            return_value=FakeClient(),
        ):
            result = asyncio.run(
                self._initialize_handler()(
                    request,
                    payload,
                    self.db,
                    self.user,
                )
            )
        self.assertEqual(result['reference'], payload.reference)
        self.assertEqual(captured['body']['email'], self.user.email)
        self.assertEqual(
            captured['body']['plan'],
            payments.PAYSTACK_INDIVIDUAL_PLAN_CODE,
        )
        self.assertEqual(captured['body']['currency'], 'NGN')

    def test_concurrent_duplicate_processing_extends_once(self):
        payload = self._invoice_payload()
        barrier = threading.Barrier(2)
        results = []
        errors = []
        result_lock = threading.Lock()

        def worker():
            session = self.Session()
            try:
                barrier.wait(timeout=5)
                result = self._send(payload, db=session)
                with result_lock:
                    results.append(result['action'])
            except Exception as exc:
                with result_lock:
                    errors.append(exc)
            finally:
                session.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)

        self.assertFalse(errors)
        self.assertCountEqual(
            results,
            ['subscription_payment_applied', 'duplicate_event_ignored'],
        )
        self.assertEqual(
            self._refresh_user().subscription_expiry,
            datetime(2026, 8, 13, 8),
        )


if __name__ == '__main__':
    unittest.main()
