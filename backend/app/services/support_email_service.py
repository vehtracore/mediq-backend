"""Truthful, privacy-safe Resend delivery for durable support submissions."""

import os
from dataclasses import dataclass
from datetime import datetime
from email.utils import parseaddr
from html import escape
from uuid import UUID

import resend
from resend.exceptions import ResendError

from app.services.email_guard import (
    email_delivery_enabled,
    get_from_email,
    get_resend_api_key,
    normalize_email_address,
    reserve_support_email_send,
)


@dataclass(frozen=True)
class SupportEmailReadiness:
    ready: bool
    issues: tuple[str, ...]

    def public_dict(self) -> dict[str, object]:
        return {
            "status": "ready" if self.ready else "unavailable",
            "issues": list(self.issues),
        }


class SupportEmailDeliveryError(Exception):
    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


def _configured_sender() -> str | None:
    configured = get_from_email(default="").strip()
    if not configured or "\r" in configured or "\n" in configured:
        return None
    _, mailbox = parseaddr(configured)
    if normalize_email_address(mailbox) is None:
        return None
    return configured


def support_email_readiness() -> SupportEmailReadiness:
    issues: list[str] = []
    if not email_delivery_enabled():
        issues.append("EMAIL_DELIVERY_ENABLED_FALSE")
    if not get_resend_api_key():
        issues.append("RESEND_API_KEY_MISSING")
    if normalize_email_address(os.getenv("SUPPORT_EMAIL_TO", "")) is None:
        issues.append("SUPPORT_EMAIL_TO_MISSING_OR_INVALID")
    if _configured_sender() is None:
        issues.append("RESEND_FROM_EMAIL_MISSING_OR_INVALID")
    return SupportEmailReadiness(ready=not issues, issues=tuple(issues))


def _failure_category(exc: Exception) -> str:
    text = f"{type(exc).__name__} {exc}".lower()
    if isinstance(exc, (TimeoutError, ConnectionError)) or "timeout" in text:
        return "provider_timeout"
    if isinstance(exc, ResendError):
        try:
            code = int(exc.code)
        except (TypeError, ValueError):
            code = 0
        if code == 429:
            return "rate_limited"
        if 400 <= code < 500:
            return "provider_rejected"
        if code >= 500:
            return "provider_unavailable"
    return "unknown"


def _email_html(
    *,
    request_id: UUID,
    user_name: str,
    user_email: str,
    user_role: str,
    subject: str,
    message: str,
    submitted_at: datetime,
) -> str:
    values = {
        "reference": escape(str(request_id)),
        "name": escape(user_name),
        "email": escape(user_email),
        "role": escape(user_role),
        "subject": escape(subject),
        "message": escape(message),
        "timestamp": escape(submitted_at.isoformat()),
    }
    return f"""
    <div style="font-family:sans-serif;max-width:600px;margin:auto;padding:24px;border:1px solid #e0e0e0;border-radius:8px;">
      <h2 style="color:#2563eb;margin-top:0;">MDQ+ Support Request</h2>
      <table style="border-collapse:collapse;width:100%;margin-bottom:24px;">
        <tr><td style="padding:8px;font-weight:bold;">Reference</td><td style="padding:8px;">{values['reference']}</td></tr>
        <tr><td style="padding:8px;font-weight:bold;">Name</td><td style="padding:8px;">{values['name']}</td></tr>
        <tr><td style="padding:8px;font-weight:bold;">Email</td><td style="padding:8px;">{values['email']}</td></tr>
        <tr><td style="padding:8px;font-weight:bold;">Role</td><td style="padding:8px;">{values['role']}</td></tr>
        <tr><td style="padding:8px;font-weight:bold;">Submitted</td><td style="padding:8px;">{values['timestamp']}</td></tr>
        <tr><td style="padding:8px;font-weight:bold;">Subject</td><td style="padding:8px;">{values['subject']}</td></tr>
      </table>
      <h3 style="margin-bottom:8px;">Message</h3>
      <div style="background:#fafafa;border-left:4px solid #2563eb;padding:16px;white-space:pre-wrap;">{values['message']}</div>
    </div>
    """


def send_support_email(
    *,
    request_id: UUID,
    user_name: str,
    user_email: str,
    user_role: str,
    subject: str,
    message: str,
    submitted_at: datetime,
) -> str:
    """Wait for Resend acceptance and return its message identifier."""
    readiness = support_email_readiness()
    if not readiness.ready:
        raise SupportEmailDeliveryError("configuration")

    reservation = reserve_support_email_send(os.getenv("SUPPORT_EMAIL_TO", ""))
    if reservation.recipient is None:
        raise SupportEmailDeliveryError(reservation.failure_category or "unknown")

    sender = _configured_sender()
    reply_to = normalize_email_address(user_email)
    if sender is None or reply_to is None:
        raise SupportEmailDeliveryError("configuration")

    reference = str(request_id)
    params = {
        "from": sender,
        "to": [reservation.recipient],
        "reply_to": reply_to,
        "subject": f"MDQ+ Support Request - {reference[:8].upper()}",
        "html": _email_html(
            request_id=request_id,
            user_name=user_name,
            user_email=reply_to,
            user_role=user_role,
            subject=subject,
            message=message,
            submitted_at=submitted_at,
        ),
    }

    try:
        resend.api_key = get_resend_api_key()
        response = resend.Emails.send(params)
    except Exception as exc:
        raise SupportEmailDeliveryError(_failure_category(exc)) from None

    provider_message_id = response.get("id") if isinstance(response, dict) else None
    if not provider_message_id:
        raise SupportEmailDeliveryError("provider_rejected")
    return str(provider_message_id)
