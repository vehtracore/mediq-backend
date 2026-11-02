"""Contract tests: optional Vehtr routing never changes payment acceptance."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app.services.vehtr_router_bindings import (
    RouterSettings, router_settings, stored_payment_bindings, publish_router_bindings,
)

CONFIG = RouterSettings("https://router.vehtr.example", "mdq-plus", "token-" + "a" * 40)


class RouterBindingConfigTests(unittest.TestCase):
    def test_missing_configuration_disables_registrations(self):
        self.assertIsNone(router_settings({}))
        self.assertEqual(router_settings({
            "VEHTR_PAYSTACK_ROUTER_URL": CONFIG.base_url,
            "VEHTR_PAYSTACK_ROUTER_PRODUCT_ID": CONFIG.product_id,
            "VEHTR_PAYSTACK_ROUTER_PRODUCT_TOKEN": CONFIG.token,
        }), CONFIG)

    def test_only_https_registered_destinations(self):
        for invalid in ("http://router.example.org", "https://localhost", "https://127.0.0.1",
                        "https://router.example.org:443", "https://router.example.org/path"):
            self.assertIsNone(router_settings({
                "VEHTR_PAYSTACK_ROUTER_URL": invalid,
                "VEHTR_PAYSTACK_ROUTER_PRODUCT_ID": CONFIG.product_id,
                "VEHTR_PAYSTACK_ROUTER_PRODUCT_TOKEN": CONFIG.token,
            }))

    def test_environment_scoped_subscription_and_invoice_only(self):
        user = SimpleNamespace(
            paystack_environment="test",
            paystack_subscription_code="SUB_abc",
            paystack_latest_invoice_code="INV_abc",
            paystack_customer_code="CUS_shared",
        )
        self.assertEqual(stored_payment_bindings(user, "test"), [
            ("subscription", "SUB_abc"), ("invoice", "INV_abc"),
        ])
        self.assertEqual(stored_payment_bindings(user, "live"), [])


class RouterBindingNetworkTests(unittest.IsolatedAsyncioTestCase):
    async def test_registration_is_scoped_and_not_leaking_customer_data(self):
        requests = []
        def respond(request):
            requests.append(request)
            return httpx.Response(200)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            self.assertEqual(await publish_router_bindings(
                "test", [("subscription", "SUB_abc"), ("invoice", "INV_abc")],
                client=client, settings=CONFIG), (2, 0))
        self.assertEqual(len(requests), 2)
        for request in requests:
            self.assertEqual(request.url.path, "/v1/bindings")
            self.assertEqual(request.headers["authorization"], "Bearer " + CONFIG.token)
            self.assertNotIn(b"CUS_", request.content)

    async def test_duplicate_registration_deduplicates(self):
        calls = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: (calls.append(request), httpx.Response(200))[1]
        )) as client:
            self.assertEqual(await publish_router_bindings(
                "test", [("subscription", "SUB_abc"), ("subscription", "SUB_abc")],
                client=client, settings=CONFIG), (1, 0))
        self.assertEqual(len(calls), 1)

    async def test_conflict_does_not_reassign_or_leak_tokens(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(409)
        )) as client:
            with self.assertLogs("app.services.vehtr_router_bindings", "WARNING") as logs:
                result = await publish_router_bindings(
                    "test", [("subscription", "SUB_conflict")],
                    client=client, settings=CONFIG)
        self.assertEqual(result, (0, 1))
        self.assertNotIn(CONFIG.token, "".join(logs.output))
        self.assertNotIn("SUB_conflict", "".join(logs.output))

    async def test_transient_failure_recovers(self):
        seen = []
        def responder(request):
            seen.append(request)
            return httpx.Response(503 if len(seen) < 3 else 200)
        async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as client:
            self.assertEqual(await publish_router_bindings(
                "test", [("invoice", "INV_retry")],
                client=client, settings=CONFIG), (1, 0))
        self.assertEqual(len(seen), 3)
