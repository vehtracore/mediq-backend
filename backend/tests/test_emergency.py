import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import inspect
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1 import emergency
from app.core.database import Base
from app.models.emergency_sms_request import EmergencySmsRequest
from app.models.user import User
from app.services.subscription_entitlement import has_active_paid_entitlement


class EmergencyTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = self.temp_dir.name.replace('\\', '/') + '/emergency.sqlite3'
        self.engine = create_engine(
            f'sqlite:///{database_path}',
            connect_args={'check_same_thread': False, 'timeout': 10},
        )
        Base.metadata.create_all(
            self.engine,
            tables=[User.__table__, EmergencySmsRequest.__table__],
        )
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        emergency._LOCAL_SERVICES_CACHE.clear()

    def tearDown(self):
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _add_user(
        self,
        *,
        plan='premium',
        expiry=None,
        phone='+2348012345678',
        enabled=True,
        sms_count=0,
        month_reset=None,
        last_trigger=None,
    ):
        with self.Session() as db:
            user = User(
                email=f'user-{plan}-{id(self)}-{datetime.now().timestamp()}@test.local',
                first_name='Test',
                last_name='Patient',
                plan=plan,
                subscription_expiry=expiry,
                kin_phone=phone,
                emergency_sms_enabled=enabled,
                emergency_sms_count=sms_count,
                emergency_sms_month_reset=month_reset,
                last_emergency_trigger=last_trigger,
            )
            db.add(user)
            db.commit()
            return user.id

    def _reserve(self, user_id, request_id, now):
        with self.Session() as db:
            return emergency._reserve_emergency_sms(
                db,
                user_id=user_id,
                request_id=request_id,
                now=now,
            )

    def _dispatch(self, user_id, request_id, reservation, *, accepted):
        sender = AsyncMock(return_value=accepted)
        with patch.object(emergency.termii_service, 'send_sms', sender):
            asyncio.run(
                emergency._dispatch_sms(
                    '+2348012345678',
                    'test message',
                    user_id=user_id,
                    request_id=request_id,
                    reserved_at=reservation.reserved_at,
                    month_start=reservation.month_start,
                    session_factory=self.Session,
                )
            )
        return sender

    def _trigger(self, user_id, request_id='activation-123456'):
        with self.Session() as db:
            user = db.get(User, user_id)
            tasks = BackgroundTasks()
            result = asyncio.run(
                inspect.unwrap(emergency.trigger_emergency)(
                    request=SimpleNamespace(),
                    payload=emergency.EmergencyTriggerRequest(
                        latitude=6.5244,
                        longitude=3.3792,
                        request_id=request_id,
                    ),
                    background_tasks=tasks,
                    db=db,
                    current_user=user,
                )
            )
            return result, tasks

    def test_paid_entitlement_includes_active_premium_and_family_only(self):
        now = datetime.now(timezone.utc)
        self.assertFalse(has_active_paid_entitlement(SimpleNamespace(plan='free', subscription_expiry=None), now=now))
        self.assertTrue(has_active_paid_entitlement(SimpleNamespace(plan='premium', subscription_expiry=now + timedelta(days=1)), now=now))
        self.assertTrue(has_active_paid_entitlement(SimpleNamespace(plan='family', subscription_expiry=None), now=now))
        self.assertFalse(has_active_paid_entitlement(SimpleNamespace(plan='premium', subscription_expiry=now - timedelta(seconds=1)), now=now))

    def test_backend_guards_and_paid_plan_outcomes(self):
        free_id = self._add_user(plan='free')
        expired_id = self._add_user(
            plan='premium',
            expiry=datetime.now(timezone.utc) - timedelta(days=1),
        )
        premium_id = self._add_user(plan='premium')
        family_id = self._add_user(plan='family')

        for ineligible_id in (free_id, expired_id):
            result, tasks = self._trigger(ineligible_id)
            self.assertFalse(result['nok_alert_queued'])
            self.assertEqual(len(tasks.tasks), 0)

        for eligible_id in (premium_id, family_id):
            result, tasks = self._trigger(eligible_id)
            self.assertTrue(result['nok_alert_queued'])
            self.assertEqual(len(tasks.tasks), 1)

        for user_id in (
            self._add_user(phone=None),
            self._add_user(enabled=False),
        ):
            with self.assertRaises(HTTPException):
                self._trigger(user_id)

    def test_replay_reserves_once_and_does_not_consume_more_quota(self):
        user_id = self._add_user()
        now = datetime.now(timezone.utc)

        first = self._reserve(user_id, 'same-activation-1234', now)
        self._dispatch(
            user_id,
            'same-activation-1234',
            first,
            accepted=True,
        )
        replay = self._reserve(user_id, 'same-activation-1234', now)

        self.assertEqual(first.outcome, 'queued')
        self.assertEqual(replay.outcome, 'duplicate')
        with self.Session() as db:
            self.assertEqual(db.get(User, user_id).emergency_sms_count, 1)
            self.assertEqual(db.query(EmergencySmsRequest).count(), 1)
            self.assertEqual(db.query(EmergencySmsRequest).one().status, 'accepted')

    def test_concurrent_duplicate_requests_queue_at_most_once(self):
        user_id = self._add_user()
        now = datetime.now(timezone.utc)
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(
                pool.map(
                    lambda _: self._reserve(user_id, 'concurrent-activation', now),
                    range(2),
                )
            )

        self.assertEqual(sorted(item.outcome for item in outcomes), ['duplicate', 'queued'])
        with self.Session() as db:
            self.assertEqual(db.get(User, user_id).emergency_sms_count, 1)

    def test_concurrent_distinct_requests_make_atomic_cooldown_decision(self):
        user_id = self._add_user()
        now = datetime.now(timezone.utc)
        request_ids = ('activation-one-123', 'activation-two-123')
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(
                pool.map(lambda value: self._reserve(user_id, value, now), request_ids)
            )

        self.assertEqual(sorted(item.outcome for item in outcomes), ['cooldown', 'queued'])
        with self.Session() as db:
            self.assertEqual(db.get(User, user_id).emergency_sms_count, 1)
            self.assertEqual(db.query(EmergencySmsRequest).count(), 1)

    def test_sixth_request_in_same_month_is_blocked(self):
        now = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
        user_id = self._add_user(
            sms_count=emergency._SMS_QUOTA,
            month_reset=date(2026, 9, 1),
            last_trigger=now - timedelta(minutes=10),
        )

        outcome = self._reserve(
            user_id,
            'quota-activation-123',
            now,
        )

        self.assertEqual(outcome.outcome, 'quota')
        with self.Session() as db:
            self.assertEqual(db.get(User, user_id).emergency_sms_count, emergency._SMS_QUOTA)
            self.assertEqual(db.query(EmergencySmsRequest).count(), 0)

    def test_first_five_provider_accepted_requests_are_monthly_uses(self):
        user_id = self._add_user()
        month_start = datetime(2026, 9, 1, tzinfo=timezone.utc)

        for index in range(emergency._SMS_QUOTA):
            request_id = f'monthly-accepted-{index:02d}'
            reservation = self._reserve(
                user_id,
                request_id,
                month_start + timedelta(minutes=index * 6),
            )
            self.assertEqual(reservation.outcome, 'queued')
            sender = self._dispatch(
                user_id,
                request_id,
                reservation,
                accepted=True,
            )
            self.assertEqual(sender.await_count, 1)

        sixth = self._reserve(
            user_id,
            'monthly-sixth-request',
            month_start + timedelta(minutes=emergency._SMS_QUOTA * 6),
        )
        self.assertEqual(sixth.outcome, 'quota')
        with self.Session() as db:
            user = db.get(User, user_id)
            self.assertEqual(user.emergency_sms_count, 5)
            self.assertEqual(user.emergency_sms_month_reset, date(2026, 9, 1))
            self.assertEqual(
                db.query(EmergencySmsRequest)
                .filter(EmergencySmsRequest.status == 'accepted')
                .count(),
                5,
            )

    def test_october_request_resets_september_quota_and_prior_cooldown(self):
        user_id = self._add_user(
            sms_count=5,
            month_reset=date(2026, 9, 1),
            last_trigger=datetime(2026, 9, 30, 23, 59, tzinfo=timezone.utc),
        )

        reservation = self._reserve(
            user_id,
            'october-activation-01',
            datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(reservation.outcome, 'queued')
        self.assertEqual(reservation.sms_count, 1)
        self.assertEqual(reservation.month_start, date(2026, 10, 1))
        with self.Session() as db:
            user = db.get(User, user_id)
            self.assertEqual(user.emergency_sms_count, 1)
            self.assertEqual(user.emergency_sms_month_reset, date(2026, 10, 1))

    def test_active_premium_and_family_both_receive_monthly_reset(self):
        october = datetime(2026, 10, 1, tzinfo=timezone.utc)
        for plan in ('premium', 'family'):
            user_id = self._add_user(
                plan=plan,
                sms_count=5,
                month_reset=date(2026, 9, 1),
                last_trigger=datetime(2026, 9, 30, 23, 59, tzinfo=timezone.utc),
            )
            with self.Session() as db:
                self.assertTrue(has_active_paid_entitlement(db.get(User, user_id), now=october))

            reservation = self._reserve(
                user_id,
                f'{plan}-october-01',
                october,
            )
            self.assertEqual(reservation.outcome, 'queued')
            self.assertEqual(reservation.sms_count, 1)

    def test_provider_acceptance_consumes_exactly_one_monthly_unit(self):
        user_id = self._add_user()
        request_id = 'provider-accepted-01'
        reservation = self._reserve(
            user_id,
            request_id,
            datetime(2026, 9, 10, tzinfo=timezone.utc),
        )

        self._dispatch(user_id, request_id, reservation, accepted=True)

        with self.Session() as db:
            user = db.get(User, user_id)
            ledger = db.query(EmergencySmsRequest).one()
            self.assertEqual(user.emergency_sms_count, 1)
            self.assertIsNotNone(user.last_emergency_trigger)
            self.assertEqual(ledger.status, 'accepted')

    def test_provider_failure_releases_quota_and_its_cooldown_but_replay_stays_failed(self):
        user_id = self._add_user()
        now = datetime(2026, 9, 10, tzinfo=timezone.utc)
        request_id = 'provider-failed-0001'
        reservation = self._reserve(user_id, request_id, now)

        self._dispatch(user_id, request_id, reservation, accepted=False)

        with self.Session() as db:
            user = db.get(User, user_id)
            ledger = db.query(EmergencySmsRequest).one()
            self.assertEqual(user.emergency_sms_count, 0)
            self.assertIsNone(user.last_emergency_trigger)
            self.assertEqual(ledger.status, 'failed')

        replay = self._reserve(user_id, request_id, now)
        next_activation = self._reserve(user_id, 'provider-next-00001', now)
        self.assertEqual(replay.outcome, 'duplicate')
        self.assertEqual(replay.request_status, 'failed')
        self.assertEqual(next_activation.outcome, 'queued')

    def test_concurrent_requests_cannot_claim_a_sixth_monthly_slot(self):
        now = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
        user_id = self._add_user(
            sms_count=4,
            month_reset=date(2026, 9, 1),
            last_trigger=now - timedelta(minutes=10),
        )

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(
                pool.map(
                    lambda request_id: self._reserve(user_id, request_id, now),
                    ('final-slot-request-a', 'final-slot-request-b'),
                )
            )

        self.assertEqual(sorted(item.outcome for item in outcomes), ['queued', 'quota'])
        with self.Session() as db:
            self.assertEqual(db.get(User, user_id).emergency_sms_count, 5)
            self.assertEqual(db.query(EmergencySmsRequest).count(), 1)

    def test_monthly_reset_is_not_client_controlled(self):
        payload = emergency.EmergencyTriggerRequest.model_validate(
            {
                'request_id': 'server-month-only-01',
                'emergency_sms_month_reset': '2035-01-01',
            }
        )

        self.assertNotIn('emergency_sms_month_reset', payload.model_dump())

    def test_phone_less_places_are_excluded_and_category_is_returned(self):
        async def handler(request):
            return httpx.Response(
                200,
                json={
                    'places': [
                        {'displayName': {'text': 'Call Hospital'}, 'nationalPhoneNumber': '01 234 5678'},
                        {'displayName': {'text': 'No Phone Hospital'}},
                    ]
                },
                request=request,
            )

        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await emergency._fetch_places_category(
                    client,
                    category='hospital',
                    lat=1.0,
                    lon=2.0,
                    api_key='test-key',
                )

        result = asyncio.run(run())
        self.assertTrue(result.succeeded)
        self.assertEqual(result.raw_count, 2)
        self.assertEqual(result.missing_phone_count, 1)
        self.assertEqual(len(result.services), 1)
        self.assertEqual(result.services[0].category, 'hospital')

    def test_hospital_and_police_searches_start_concurrently(self):
        async def run():
            started = []
            both_started = asyncio.Event()

            async def fake_fetch(_client, *, category, **_kwargs):
                started.append(category)
                if len(started) == 2:
                    both_started.set()
                await asyncio.wait_for(both_started.wait(), timeout=0.25)
                return emergency._CategorySearchResult(category, True, [], 0, 0)

            with patch.object(emergency, '_fetch_places_category', side_effect=fake_fetch):
                results = await emergency._search_places(lat=1.0, lon=2.0, api_key='test')
            return started, results

        started, results = asyncio.run(run())
        self.assertCountEqual(started, ['hospital', 'police'])
        self.assertEqual(len(results), 2)

    def test_partial_zero_failure_and_success_cache_semantics(self):
        hospital = emergency.LocalServiceResult(
            name='Hospital A', phone_number='1122', category='hospital'
        )
        route = inspect.unwrap(emergency.get_local_services)
        user = SimpleNamespace(id=42)

        async def call(results):
            with patch.dict('os.environ', {'Maps_API_KEY': 'test-key'}), patch.object(
                emergency, '_search_places', AsyncMock(return_value=results)
            ) as search:
                response = await route(
                    request=SimpleNamespace(), lat=1.2345, lon=2.3456, current_user=user
                )
                return response, search

        partial, _ = asyncio.run(
            call([
                emergency._CategorySearchResult('hospital', True, [hospital], 1, 0),
                emergency._CategorySearchResult('police', False, [], 0, 0),
            ])
        )
        self.assertEqual(partial.status, 'success')
        self.assertEqual(partial.services, [hospital])
        self.assertIn(
            emergency._local_services_cache_key(1.2345, 2.3456),
            emergency._LOCAL_SERVICES_CACHE,
        )

        # A new coordinate avoids the successful cache entry above.
        async def uncached_call(results, lat):
            with patch.dict('os.environ', {'Maps_API_KEY': 'test-key'}), patch.object(
                emergency, '_search_places', AsyncMock(return_value=results)
            ):
                return await route(
                    request=SimpleNamespace(), lat=lat, lon=2.3456, current_user=user
                )

        empty_results = [
            emergency._CategorySearchResult('hospital', True, [], 2, 2),
            emergency._CategorySearchResult('police', True, [], 1, 1),
        ]
        empty = asyncio.run(uncached_call(empty_results, 1.3345))
        self.assertEqual(empty.status, 'empty')
        self.assertNotIn(emergency._local_services_cache_key(1.3345, 2.3456), emergency._LOCAL_SERVICES_CACHE)

        police = emergency.LocalServiceResult(
            name='Police A', phone_number='199', category='police'
        )
        police_only = asyncio.run(
            uncached_call(
                [
                    emergency._CategorySearchResult('hospital', False, [], 0, 0),
                    emergency._CategorySearchResult('police', True, [police], 1, 0),
                ],
                1.3845,
            )
        )
        self.assertEqual(police_only.status, 'success')
        self.assertEqual(police_only.services, [police])

        both = asyncio.run(
            uncached_call(
                [
                    emergency._CategorySearchResult('hospital', True, [hospital], 1, 0),
                    emergency._CategorySearchResult('police', True, [police], 1, 0),
                ],
                1.4045,
            )
        )
        self.assertEqual(both.status, 'success')
        self.assertEqual(both.services, [hospital, police])

        failed_results = [
            emergency._CategorySearchResult('hospital', False, [], 0, 0),
            emergency._CategorySearchResult('police', False, [], 0, 0),
        ]
        unavailable = asyncio.run(uncached_call(failed_results, 1.4345))
        self.assertEqual(unavailable.status, 'unavailable')
        self.assertNotIn(emergency._local_services_cache_key(1.4345, 2.3456), emergency._LOCAL_SERVICES_CACHE)


if __name__ == '__main__':
    unittest.main()
