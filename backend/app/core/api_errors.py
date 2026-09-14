"""Small, privacy-safe HTTP error contract shared by every API route."""

from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException


REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$")
_UNSAFE_EXTERNAL_TEXT = re.compile(
    r"traceback|stack\s*trace|sqlalchemy|integrityerror|database error|"
    r"gemini|generatecontent|v1beta|openai|googlegenerativeai|yarngpt|"
    r"paystack|resend|termii|firebase|agora|cloudinary|"
    r"exception\b|socketerror|httperror|api[_ -]?key|bearer\s+",
    re.IGNORECASE,
)


class ApiError(HTTPException):
    """Explicit, externally safe domain failure."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.code = code
        self.safe_message = message
        self.details = details


def request_id_for(request: Request) -> str:
    existing = getattr(request.state, "request_id", None)
    if isinstance(existing, str) and _SAFE_REQUEST_ID.fullmatch(existing):
        return existing
    supplied = request.headers.get(REQUEST_ID_HEADER, "").strip()
    request_id = supplied if _SAFE_REQUEST_ID.fullmatch(supplied) else str(uuid.uuid4())
    request.state.request_id = request_id
    return request_id


def error_body(
    *,
    code: str,
    message: str,
    request_id: str | None = None,
    details: Any | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if request_id:
        error["request_id"] = request_id
    if details is not None:
        error["details"] = details
    return {"error": error}


def error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    request_id: str | None = None,
    details: Any | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    response_headers = dict(headers or {})
    if request_id:
        response_headers[REQUEST_ID_HEADER] = request_id
    return JSONResponse(
        status_code=status_code,
        content=error_body(
            code=code,
            message=message,
            request_id=request_id,
            details=details,
        ),
        headers=response_headers,
    )


def _default_code(status_code: int) -> str:
    return {
        400: "invalid_request",
        401: "unauthenticated",
        403: "forbidden",
        404: "not_found",
        409: "request_conflict",
        410: "not_found",
        413: "file_too_large",
        422: "validation_error",
        429: "rate_limited",
        502: "service_unavailable",
        503: "service_unavailable",
        504: "service_unavailable",
    }.get(status_code, "internal_error" if status_code >= 500 else "request_failed")


def _default_message(status_code: int) -> str:
    if status_code == 401:
        return "We could not authorize this request. Please try again."
    if status_code == 403:
        return "You do not have permission to perform this action."
    if status_code == 404:
        return "The requested item was not found."
    if status_code == 409:
        return "This request conflicts with the current state. Please refresh and try again."
    if status_code == 413:
        return "This file is too large. Please choose a smaller file."
    if status_code == 422:
        return "Please check your input and try again."
    if status_code == 429:
        return "Too many requests. Please wait and try again."
    if status_code in {502, 503, 504}:
        return "MDQ+ is temporarily unavailable. Please try again shortly."
    if status_code >= 500:
        return "We couldn't complete that request. Please try again."
    return "We couldn't complete that request. Please try again."


def _safe_legacy_message(status_code: int, detail: Any) -> str:
    # Existing deliberate 4xx product messages remain available while routes
    # move to explicit ApiError codes. Server/provider text is never trusted.
    if status_code < 500 and isinstance(detail, str):
        candidate = detail.strip()
        if candidate and len(candidate) <= 500 and not _UNSAFE_EXTERNAL_TEXT.search(candidate):
            return candidate
    return _default_message(status_code)


def install_error_handlers(app: FastAPI, logger) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        fields = []
        for issue in exc.errors():
            location = [str(part) for part in issue.get("loc", ()) if part != "body"]
            fields.append(
                {
                    "field": ".".join(location),
                    "message": str(issue.get("msg", "Invalid value"))[:200],
                    "type": str(issue.get("type", "validation_error"))[:100],
                }
            )
        request_id = request_id_for(request)
        return error_response(
            status_code=422,
            code="validation_error",
            message="Please check your input and try again.",
            request_id=request_id,
            details={"fields": fields},
        )

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
        request_id = request_id_for(request)
        retry_after = getattr(exc, "retry_after", None)
        headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
        return error_response(
            status_code=429,
            code="rate_limited",
            message="Too many requests. Please wait and try again.",
            request_id=request_id,
            headers=headers,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        request_id = request_id_for(request)
        if isinstance(exc, ApiError):
            code = exc.code
            message = exc.safe_message
            details = exc.details
        else:
            code = _default_code(exc.status_code)
            message = _safe_legacy_message(exc.status_code, exc.detail)
            details = None
        return error_response(
            status_code=exc.status_code,
            code=code,
            message=message,
            request_id=request_id,
            details=details,
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception):
        request_id = request_id_for(request)
        logger.error(
            "[UNHANDLED] request_id=%s method=%s path=%s failure_category=%s",
            request_id,
            request.method,
            request.url.path,
            type(exc).__name__,
            exc_info=True,
        )
        return error_response(
            status_code=500,
            code="internal_error",
            message="We couldn't complete that request. Please try again.",
            request_id=request_id,
        )
