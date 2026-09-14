import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.core.api_errors import ApiError, install_error_handlers
from app.services.paystack_service import PaystackService


class _Payload(BaseModel):
    name: str = Field(min_length=2)


def _client() -> TestClient:
    app = FastAPI()
    install_error_handlers(app, app.logger if hasattr(app, "logger") else __import__("logging").getLogger(__name__))

    @app.get("/unexpected")
    def unexpected():
        raise RuntimeError(
            "sqlalchemy IntegrityError; gemini-1.5-flash v1beta generateContent"
        )

    @app.get("/unauthenticated")
    def unauthenticated():
        raise HTTPException(status_code=401, detail="Token was rejected")

    @app.get("/forbidden")
    def forbidden():
        raise HTTPException(status_code=403, detail="This action is not allowed.")

    @app.post("/validate")
    def validate(payload: _Payload):
        return payload

    @app.get("/conflict")
    def conflict():
        raise ApiError(409, "stale_version", "Refresh this saved conversation.")

    @app.get("/limited")
    def limited():
        raise ApiError(
            429,
            "quota_exceeded",
            "Your current allowance has been reached.",
            headers={"Retry-After": "30"},
        )

    @app.get("/provider")
    def provider():
        raise HTTPException(
            status_code=503,
            detail="OpenAI API error: provider-request-id=secret",
        )

    return TestClient(app, raise_server_exceptions=False)


def _error(response):
    return response.json()["error"]


def test_unexpected_exception_is_safe_and_correlated():
    response = _client().get(
        "/unexpected",
        headers={"X-Request-ID": "safe-request-123"},
    )

    assert response.status_code == 500
    assert response.headers["x-request-id"] == "safe-request-123"
    assert _error(response)["code"] == "internal_error"
    assert _error(response)["request_id"] == "safe-request-123"
    serialized = response.text.lower()
    for forbidden in ("sqlalchemy", "integrityerror", "gemini", "v1beta", "generatecontent"):
        assert forbidden not in serialized


def test_invalid_correlation_id_is_replaced():
    response = _client().get(
        "/unexpected",
        headers={"X-Request-ID": "patient@example.com"},
    )
    request_id = _error(response)["request_id"]
    assert request_id != "patient@example.com"
    assert response.headers["x-request-id"] == request_id


def test_401_and_403_keep_their_http_semantics():
    client = _client()
    unauthenticated = client.get("/unauthenticated")
    forbidden = client.get("/forbidden")

    assert unauthenticated.status_code == 401
    assert _error(unauthenticated)["code"] == "unauthenticated"
    assert forbidden.status_code == 403
    assert _error(forbidden)["code"] == "forbidden"


def test_validation_keeps_safe_field_details():
    response = _client().post("/validate", json={"name": ""})

    assert response.status_code == 422
    assert _error(response)["code"] == "validation_error"
    assert _error(response)["details"]["fields"][0]["field"] == "name"


def test_conflict_and_rate_limit_keep_stable_codes_and_retry_after():
    client = _client()
    conflict = client.get("/conflict")
    limited = client.get("/limited")

    assert conflict.status_code == 409
    assert _error(conflict)["code"] == "stale_version"
    assert limited.status_code == 429
    assert _error(limited)["code"] == "quota_exceeded"
    assert limited.headers["retry-after"] == "30"


def test_provider_failure_is_translated_without_provider_text():
    response = _client().get("/provider")

    assert response.status_code == 503
    assert _error(response)["code"] == "service_unavailable"
    assert "openai" not in response.text.lower()
    assert "provider-request-id" not in response.text.lower()


def test_active_ai_models_are_central_and_do_not_use_retired_scanner_identifier():
    source_path = Path(__file__).resolve().parents[1] / "app" / "services" / "ai_service.py"
    source = source_path.read_text(encoding="utf-8")

    assert "STANDARD_MODEL_NAME = os.getenv" in source
    assert "HEAVY_MODEL_NAME = os.getenv" in source
    assert "gemini-1.5-flash" not in source
    assert "vision_model = heavy_model" in source


def test_payment_provider_message_is_not_promoted_to_api_detail(monkeypatch):
    raw_provider_message = "Gateway debug reference secret-provider-123"

    class _Response:
        is_success = False
        status_code = 400

        @staticmethod
        def json():
            return {"status": False, "message": raw_provider_message}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, *_args, **_kwargs):
            return _Response()

    monkeypatch.setattr(
        "app.services.paystack_service.httpx.AsyncClient",
        lambda **_kwargs: _Client(),
    )

    service = PaystackService()
    try:
        asyncio.run(service.resolve_account("058", "0123456789"))
    except ApiError as exc:
        assert exc.status_code == 400
        assert exc.code == "invalid_payout_details"
        assert raw_provider_message not in exc.detail
        assert "paystack" not in exc.detail.lower()
    else:
        raise AssertionError("Expected provider rejection to be translated")
