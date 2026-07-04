"""
Email Service - Resend
======================
Asynchronous transactional email sender for the MDQ+ platform.

All outbound delivery is gated by app.services.email_guard so one exposed
endpoint cannot silently burn the Resend quota.
"""

import asyncio
import logging

import resend

from app.services.email_guard import (
    get_from_email,
    get_resend_api_key,
    mask_email,
    reserve_email_send,
)

logger = logging.getLogger(__name__)


def _resend_send(
    to_email: str,
    subject: str,
    html_body: str,
    *,
    api_key: str,
    from_email: str,
) -> None:
    """Synchronous Resend API call; runs inside a worker thread."""
    resend.api_key = api_key
    params: resend.Emails.SendParams = {
        "from": from_email,
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
    Queue an email via Resend on a worker thread so the event loop is not blocked.

    Safe to call from FastAPI BackgroundTasks. Guard failures and Resend errors
    are logged and never propagate to the HTTP response.
    """
    recipient = reserve_email_send(
        to_email,
        subject,
        purpose="transactional",
    )
    if recipient is None:
        return

    api_key = get_resend_api_key()
    from_email = get_from_email("MDQ+ Health <noreply@mdqplus.app>")

    try:
        await asyncio.to_thread(
            _resend_send,
            recipient,
            subject,
            html_body,
            api_key=api_key,
            from_email=from_email,
        )
        logger.info(
            "[EMAIL] Email sent via Resend - to='%s' | subject='%s'",
            mask_email(recipient),
            subject,
        )
    except Exception as exc:
        logger.error(
            "[EMAIL] Resend delivery failed - to='%s' | subject='%s' | error='%s'",
            mask_email(recipient),
            subject,
            exc,
            exc_info=True,
        )
