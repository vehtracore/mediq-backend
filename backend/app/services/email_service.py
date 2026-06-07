"""
Email Service — Resend
======================
Asynchronous transactional email sender for the MDQ+ platform,
powered by the Resend API (https://resend.com).

Configuration (environment variable):
    RESEND_API_KEY   — Resend API key (starts with "re_…")
    EMAIL_FROM       — Sender address verified in your Resend dashboard
                       (default: "MDQ+ Health <noreply@mdqplus.app>")

If RESEND_API_KEY is absent, the function logs a warning and returns
immediately so the calling code is never blocked or crashed.

The synchronous resend.Emails.send() call is offloaded to a thread
pool via asyncio.to_thread so the FastAPI event loop is never blocked.
"""

import asyncio
import logging
import os

import resend

logger = logging.getLogger(__name__)

# ── Resend configuration ──────────────────────────────────────────────────────
_RESEND_API_KEY: str = os.environ.get("RESEND_API_KEY", "")
_EMAIL_FROM: str = os.environ.get("EMAIL_FROM", "MDQ+ Health <noreply@mdqplus.app>")

if _RESEND_API_KEY:
    resend.api_key = _RESEND_API_KEY
else:
    logger.warning(
        "[EMAIL] ⚠️  RESEND_API_KEY is not set — "
        "all transactional emails will be silently skipped."
    )


def _resend_send(to_email: str, subject: str, html_body: str) -> None:
    """
    Synchronous Resend API call — runs inside a worker thread.

    Raises on any API / network error so the async caller can log it.
    """
    params: resend.Emails.SendParams = {
        "from": _EMAIL_FROM,
        "to": [to_email],
        "subject": subject,
        "html": html_body,
    }
    resend.Emails.send(params)


async def send_transactional_email(
    to_email: str,
    subject: str,
    html_body: str,
) -> None:
    """
    Queue an email via Resend on a worker thread so the event loop is
    never blocked.

    Safe to call from FastAPI BackgroundTasks — any exception is caught
    and logged; the error will never propagate to the HTTP response.

    Args:
        to_email:  Recipient address (e.g. "patient@example.com").
        subject:   Email subject line.
        html_body: HTML content of the email body.
    """
    if not _RESEND_API_KEY:
        logger.warning(
            "[EMAIL] ⚠️  Skipping email — RESEND_API_KEY not configured "
            "(to='%s' | subject='%s').",
            to_email,
            subject,
        )
        return

    try:
        await asyncio.to_thread(_resend_send, to_email, subject, html_body)
        logger.info(
            "[EMAIL] ✅ Email sent via Resend — to='%s' | subject='%s'",
            to_email,
            subject,
        )
    except Exception as exc:
        # Never crash the server over a failed notification.
        logger.error(
            "[EMAIL] ❌ Resend delivery failed — to='%s' | subject='%s' | error='%s'",
            to_email,
            subject,
            exc,
            exc_info=True,
        )
