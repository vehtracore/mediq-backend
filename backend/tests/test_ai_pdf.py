import asyncio
import io
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image
from google.generativeai.types.content_types import to_content
from pypdf import PdfWriter

from app.api.v1 import chat
from app.services import ai_service
from app.services.ai_request_guard import AIRequestLease
from app.services.ai_pdf import (
    MAX_AI_PDF_BYTES,
    read_validated_ai_pdf,
    validate_ai_pdf_bytes,
)


def _pdf_bytes(*, pages: int = 1, password: str | None = None) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=100, height=100)
    if password:
        writer.encrypt(password)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_valid_pdf_is_accepted() -> None:
    assert validate_ai_pdf_bytes(_pdf_bytes()) == 1


def test_installed_gemini_sdk_accepts_inline_pdf_blob() -> None:
    content = to_content(
        {
            "role": "user",
            "parts": [
                "Explain this document",
                {"mime_type": "application/pdf", "data": _pdf_bytes()},
            ],
        }
    )
    assert content.parts[1].inline_data.mime_type == "application/pdf"


def test_non_pdf_masquerading_as_pdf_is_rejected() -> None:
    with pytest.raises(HTTPException) as exc:
        validate_ai_pdf_bytes(b"not a PDF")
    assert exc.value.status_code == 400


def test_oversized_pdf_is_rejected_before_parsing() -> None:
    upload = UploadFile(
        file=io.BytesIO(b"%PDF-1.7\n" + b"0" * MAX_AI_PDF_BYTES),
        filename="large.pdf",
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(read_validated_ai_pdf(upload))
    assert exc.value.status_code == 413


def test_pdf_with_too_many_pages_is_rejected() -> None:
    with pytest.raises(HTTPException) as exc:
        validate_ai_pdf_bytes(_pdf_bytes(pages=11))
    assert exc.value.status_code == 400


def test_encrypted_pdf_is_rejected() -> None:
    with pytest.raises(HTTPException) as exc:
        validate_ai_pdf_bytes(_pdf_bytes(password="secret"))
    assert exc.value.status_code == 400


def test_malformed_pdf_fails_with_safe_error() -> None:
    with pytest.raises(HTTPException) as exc:
        validate_ai_pdf_bytes(b"%PDF-1.7\nthis is truncated")
    assert exc.value.status_code == 400
    assert exc.value.detail == "This PDF could not be processed."


def test_pdf_validation_does_not_create_temporary_files(tmp_path) -> None:
    assert validate_ai_pdf_bytes(_pdf_bytes()) == 1
    assert list(tmp_path.iterdir()) == []


class _FakeChat:
    def __init__(self, *, error: Exception | None = None):
        self.error = error
        self.calls = []

    async def send_message_async(self, prompt, generation_config):
        self.calls.append(prompt)
        if self.error:
            raise self.error
        return SimpleNamespace(
            text="[MODE: SIMPLE] Safe response",
            candidates=[SimpleNamespace(finish_reason="STOP")],
            usage_metadata=SimpleNamespace(candidates_token_count=12),
        )


class _FakeModel:
    def __init__(self, chat: _FakeChat):
        self.chat = chat

    def start_chat(self, history):
        return self.chat

    async def count_tokens_async(self, contents):
        return SimpleNamespace(total_tokens=100)


def test_pdf_provider_failure_does_not_retry_without_document(monkeypatch) -> None:
    chat = _FakeChat(error=ValueError("provider rejected document"))
    monkeypatch.setattr(ai_service, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(ai_service, "heavy_model", _FakeModel(chat))

    with pytest.raises(RuntimeError, match="Gemini request failed"):
        asyncio.run(
            ai_service.get_medical_response(
                "Explain my results",
                document_bytes=_pdf_bytes(),
            )
        )

    assert len(chat.calls) == 1
    assert any(
        isinstance(part, dict) and part.get("mime_type") == "application/pdf"
        for part in chat.calls[0]
    )


def test_saved_historical_context_is_not_rolling_memory_truncated(monkeypatch) -> None:
    chat = _FakeChat()
    monkeypatch.setattr(ai_service, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(ai_service, "standard_model", _FakeModel(chat))
    historical = "H" * (ai_service.MAX_MEMORY_CHARS + 800)

    result = asyncio.run(
        ai_service.get_medical_response(
            "What changed?",
            historical_saved_context=historical,
        )
    )

    assert result.text == "Safe response"
    assert historical in chat.calls[0][0]


def test_existing_image_prompt_path_remains_operational(monkeypatch) -> None:
    image_bytes = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(image_bytes, format="PNG")

    class _Response:
        content = image_bytes.getvalue()

        def raise_for_status(self):
            return None

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get(self, *_args, **_kwargs):
            return _Response()

    import httpx

    chat = _FakeChat()
    monkeypatch.setattr(ai_service, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(ai_service, "heavy_model", _FakeModel(chat))
    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    result = asyncio.run(
        ai_service.get_medical_response(
            "What is shown?",
            image_url="https://temporary.invalid/image.png",
        )
    )

    assert result.text == "Safe response"
    assert any(isinstance(part, Image.Image) for part in chat.calls[0])


class _UsageDb:
    def __init__(self):
        self.commits = 0

    def add(self, _value):
        return None

    def commit(self):
        self.commits += 1


def _chat_user():
    from datetime import date, datetime, timezone

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return SimpleNamespace(
        id=7,
        plan="free",
        ai_consent_granted_at=now,
        ai_consent_withdrawn_at=None,
        chat_blocked_until=None,
        burst_start_time=now,
        burst_chat_count=0,
        monthly_chat_count=0,
        monthly_chat_image_count=0,
        last_chat_month_reset=date.today(),
        monthly_lab_count=0,
        last_lab_reset=date.today(),
        rolling_chat_count=0,
        rolling_chat_image_count=0,
        rolling_chat_window_start=now,
        dob=None,
        chronic_conditions=None,
    )


def test_successful_pdf_chat_uses_existing_image_named_attachment_counter(
    monkeypatch,
) -> None:
    calls = []

    async def _response(*_args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text="Safe response", memory_update=None)

    monkeypatch.setattr(ai_service, "get_medical_response", _response)
    user = _chat_user()
    db = _UsageDb()
    lease = AIRequestLease(user.id, "owner", "request")

    result = asyncio.run(
        chat._analyze_chat_request(
            request=SimpleNamespace(),
            chat_request=chat.ChatRequest(message="Explain this report"),
            db=db,
            current_user=user,
            request_lease=lease,
            document_bytes=_pdf_bytes(),
        )
    )

    assert result.response == "Safe response"
    assert calls[0]["document_bytes"].startswith(b"%PDF-")
    assert user.monthly_chat_count == 1
    assert user.monthly_chat_image_count == 1
    assert user.monthly_lab_count == 0
    assert lease.completed is True
    assert db.commits == 1
