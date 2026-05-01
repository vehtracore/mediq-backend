"""
Email Service
=============
Asynchronous transactional email sender for the MDQ+ platform.

Credentials are loaded from environment variables:
    SMTP_HOST        — SMTP server hostname  (default: smtp.gmail.com)
    SMTP_PORT        — SMTP server port       (default: 587, STARTTLS)
    SMTP_USER        — Login username / sender address
    SMTP_PASSWORD    — Login password / app-password

If any credential is missing, the function logs a warning and returns
immediately so the calling code is never blocked or crashed.

The synchronous smtplib call is offloaded to a thread pool via
``asyncio.to_thread`` so the FastAPI event loop is never blocked.
"""

import asyncio
import logging
import os
import smtplib
from email.message import EmailMessage

logger = logging.getLogger(__name__)

# ── SMTP configuration ────────────────────────────────────────────────────────
_SMTP_HOST: str = os.environ.get("SMTP_HOST", "smtp.gmail.com")
_SMTP_PORT: int = int(os.environ.get("SMTP_PORT", "587"))
_SMTP_USER: str = os.environ.get("SMTP_USER", "")
_SMTP_PASSWORD: str = os.environ.get("SMTP_PASSWORD", "")

# Display name shown in the From header
_FROM_NAME: str = "MDQ+ Health"


def _smtp_send(to_email: str, subject: str, body: str) -> None:
    """
    Synchronous SMTP send — runs inside a worker thread.

    Uses STARTTLS on port 587 (industry-standard secure relay).
    Raises on any SMTP / network error so the caller can log it.
    """
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{_FROM_NAME} <{_SMTP_USER}>"
    msg["To"] = to_email
    msg.set_content(body)

    with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=20) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(_SMTP_USER, _SMTP_PASSWORD)
        server.send_message(msg)


async def send_transactional_email(to_email: str, subject: str, body: str) -> None:
    """
    Queue an email on a worker thread so the event loop is never blocked.

    Safe to call from FastAPI BackgroundTasks — any exception is caught
    and logged; the error will never propagate to the HTTP response.

    Args:
        to_email: Recipient address (e.g. "patient@example.com").
        subject:  Email subject line.
        body:     Plain-text email body.
    """
    if not _SMTP_USER or not _SMTP_PASSWORD:
        logger.warning(
            "[EMAIL] ⚠️  SMTP_USER / SMTP_PASSWORD not configured — "
            "email to '%s' skipped.",
            to_email,
        )
        return

    try:
        # Offload the blocking smtplib call to a thread-pool worker.
        await asyncio.to_thread(_smtp_send, to_email, subject, body)
        logger.info("[EMAIL] ✅ Email sent — to='%s' | subject='%s'", to_email, subject)
    except Exception as exc:
        # Never crash the server over a failed notification.
        logger.error(
            "[EMAIL] ❌ Failed to send email — to='%s' | subject='%s' | error='%s'",
            to_email,
            subject,
            exc,
        )
