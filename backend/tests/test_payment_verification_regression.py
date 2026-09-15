import asyncio
import inspect

import pytest
from fastapi import BackgroundTasks, HTTPException
from starlette.requests import Request

from app.api.v1 import payments


class _ProviderResponse:
    status_code = 429
    headers = {"Retry-After": "73"}

    @staticmethod
    def json():
        return {"status": False}


class _ProviderClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def get(self, *_args, **_kwargs):
        return _ProviderResponse()


def test_provider_429_preserves_bounded_retry_after(monkeypatch) -> None:
    monkeypatch.setattr(payments, "PAYSTACK_SECRET_KEY", "sk_test_placeholder")
    monkeypatch.setattr(
        payments,
        "_validate_reference_owner_before_paystack",
        lambda **_: ("gp_consult", 11, 7),
    )
    monkeypatch.setattr(
        payments.httpx,
        "AsyncClient",
        lambda **_: _ProviderClient(),
    )
    endpoint = inspect.unwrap(payments.verify_transaction)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/payments/verify/reference",
            "headers": [],
        }
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            endpoint(
                reference="reference",
                request=request,
                background_tasks=BackgroundTasks(),
                db=object(),
                current_user=object(),
            )
        )

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers == {"Retry-After": "73"}
    assert "rate limited" in exc_info.value.detail.lower()
