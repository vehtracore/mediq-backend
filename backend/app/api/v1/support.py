"""
Support Router
==============
Handles in-app customer support messaging.

POST /contact is authenticated and forwards a support message from the current
user to the MDQ+ admin inbox via Resend. Delivery is centrally guarded so this
route cannot burn email quota if abused.
"""

import logging
import os
from html import escape

import resend
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.core.database import get_db
from app.core.limiter import limiter
from app.models.user import User
from app.services.email_guard import (
    get_from_email,
    get_resend_api_key,
    mask_email,
    reserve_email_send,
)

logger = logging.getLogger(__name__)

router = APIRouter()

FROM_ADDRESS: str = "MDQ+ Support <support@mdqplus.com>"
ADMIN_EMAIL: str = os.getenv("ADMIN_EMAIL", "admin@mdqplus.com")


class SupportMessageRequest(BaseModel):
    """Body for POST /api/v1/support/contact."""

    subject: str = Field(..., min_length=1, max_length=120)
    message: str = Field(..., min_length=1, max_length=5000)


@router.post("/contact", status_code=200)
@limiter.limit("10/hour")
async def send_support_message(
    request: Request,
    payload: SupportMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """
    Accept a support message from the authenticated user and forward it to admin.

    The endpoint still returns 200 when email delivery is disabled/capped so the
    client can show a stable support confirmation while ops sees guard logs.
    """
    user_name = f"{current_user.first_name or ''} {current_user.last_name or ''}".strip() or "Unknown"
    user_id = current_user.id
    user_email = current_user.email or "unknown"

    clean_subject = " ".join(payload.subject.split())
    email_subject = f"MDQ+ Support: {clean_subject} (From: {user_email})"

    safe_user_name = escape(user_name)
    safe_user_email = escape(user_email)
    safe_subject = escape(clean_subject)
    safe_message = escape(payload.message.strip())

    html_body = f"""
    <div style="font-family:sans-serif;max-width:600px;margin:auto;padding:24px;border:1px solid #e0e0e0;border-radius:8px;">
      <h2 style="color:#4A90E2;margin-top:0;">MDQ+ Support Request</h2>

      <table style="border-collapse:collapse;width:100%;margin-bottom:24px;">
        <tr style="background:#f5f5f5;">
          <td style="padding:10px 14px;font-weight:bold;width:140px;">User Name</td>
          <td style="padding:10px 14px;">{safe_user_name}</td>
        </tr>
        <tr>
          <td style="padding:10px 14px;font-weight:bold;">Email</td>
          <td style="padding:10px 14px;">{safe_user_email}</td>
        </tr>
        <tr style="background:#f5f5f5;">
          <td style="padding:10px 14px;font-weight:bold;">Account ID</td>
          <td style="padding:10px 14px;">#{user_id}</td>
        </tr>
        <tr>
          <td style="padding:10px 14px;font-weight:bold;">Subject</td>
          <td style="padding:10px 14px;">{safe_subject}</td>
        </tr>
      </table>

      <h3 style="color:#333;margin-bottom:8px;">Message</h3>
      <div style="background:#fafafa;border-left:4px solid #4A90E2;padding:16px;border-radius:4px;white-space:pre-wrap;">{safe_message}</div>

      <p style="color:#aaa;font-size:12px;margin-top:24px;">
        This message was submitted via the MDQ+ in-app support form.
      </p>
    </div>
    """

    logger.info(
        "[SUPPORT] Support request accepted | user_id=%s | subject='%s'",
        user_id,
        clean_subject,
    )

    recipient = reserve_email_send(ADMIN_EMAIL, email_subject, purpose="support_contact")
    if recipient is None:
        return {
            "status": "success",
            "detail": "Your message has been received. Our support team will get back to you shortly.",
        }

    try:
        resend.api_key = get_resend_api_key()
        resend.Emails.send({
            "from": get_from_email(FROM_ADDRESS),
            "to": [recipient],
            "subject": email_subject,
            "html": html_body,
        })
        logger.info(
            "[SUPPORT] Support email sent | user_id=%s | to='%s'",
            user_id,
            mask_email(recipient),
        )
    except Exception as exc:
        logger.error(
            "[SUPPORT] Failed to send support email | user_id=%s | error=%s",
            user_id,
            exc,
            exc_info=True,
        )

    return {
        "status": "success",
        "detail": "Your message has been received. Our support team will get back to you shortly.",
    }
