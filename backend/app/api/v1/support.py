"""
Support Router
==============
Handles in-app customer support messaging.

Endpoints
---------
POST /contact — Authenticated endpoint that forwards a support message from
                the current user to the MDQ+ admin inbox via Resend.

Design notes
------------
• The Resend SDK is already installed (resend>=2.4.0 in requirements.txt).
• RESEND_API_KEY and ADMIN_EMAIL are read from environment variables.
• The sender address MUST belong to a domain verified in the Resend dashboard
  (currently mdqplus.com). Update FROM_ADDRESS if the verified domain changes.
• The endpoint always returns 200 to the client even when the email fails so
  that a transient Resend error does not surface a 500 to users — the failure
  is logged for ops visibility.
"""

import logging
import os

import resend
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import deps
from app.core.database import get_db
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Resend configuration ───────────────────────────────────────────────────────
FROM_ADDRESS: str = "MDQ+ Support <support@mdqplus.com>"
ADMIN_EMAIL: str = os.getenv("ADMIN_EMAIL", "admin@mdqplus.com")


# ── Request schema ─────────────────────────────────────────────────────────────

class SupportMessageRequest(BaseModel):
    """
    Body for POST /api/v1/support/contact.

    Fields
    ------
    subject : Short description of the issue (shown in email subject line).
    message : Full text of the user's support message.
    """

    subject: str
    message: str


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.post("/contact", status_code=200)
async def send_support_message(
    payload: SupportMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """
    POST /api/v1/support/contact

    Accepts a support message from the authenticated user and forwards it to
    the MDQ+ admin inbox via Resend.

    The email includes the user's name, email address, and account ID so the
    support team can look up the account immediately without needing to ask.

    Returns 200 regardless of the Resend outcome — failures are logged.
    """
    # Initialise Resend with the secret key on every call (cheap string assign)
    resend.api_key = os.getenv("RESEND_API_KEY", "")
    if not resend.api_key:
        logger.error(
            "[SUPPORT] RESEND_API_KEY is not set — email will not be delivered."
        )

    user_name: str = f"{current_user.first_name or ''} {current_user.last_name or ''}".strip() or "Unknown"
    user_id: int = current_user.id
    user_email: str = current_user.email or "unknown"

    email_subject: str = f"MDQ+ Support: {payload.subject} (From: {user_email})"

    html_body: str = f"""
    <div style="font-family:sans-serif;max-width:600px;margin:auto;padding:24px;border:1px solid #e0e0e0;border-radius:8px;">
      <h2 style="color:#4A90E2;margin-top:0;">MDQ+ Support Request</h2>

      <table style="border-collapse:collapse;width:100%;margin-bottom:24px;">
        <tr style="background:#f5f5f5;">
          <td style="padding:10px 14px;font-weight:bold;width:140px;">User Name</td>
          <td style="padding:10px 14px;">{user_name}</td>
        </tr>
        <tr>
          <td style="padding:10px 14px;font-weight:bold;">Email</td>
          <td style="padding:10px 14px;">{user_email}</td>
        </tr>
        <tr style="background:#f5f5f5;">
          <td style="padding:10px 14px;font-weight:bold;">Account ID</td>
          <td style="padding:10px 14px;">#{user_id}</td>
        </tr>
        <tr>
          <td style="padding:10px 14px;font-weight:bold;">Subject</td>
          <td style="padding:10px 14px;">{payload.subject}</td>
        </tr>
      </table>

      <h3 style="color:#333;margin-bottom:8px;">Message</h3>
      <div style="background:#fafafa;border-left:4px solid #4A90E2;padding:16px;border-radius:4px;white-space:pre-wrap;">{payload.message}</div>

      <p style="color:#aaa;font-size:12px;margin-top:24px;">
        This message was submitted via the MDQ+ in-app support form.
      </p>
    </div>
    """

    logger.info(
        "[SUPPORT] Sending support email | user_id=%s | subject='%s'",
        user_id,
        payload.subject,
    )

    try:
        resend.Emails.send({
            "from": FROM_ADDRESS,
            "to": [ADMIN_EMAIL],
            "subject": email_subject,
            "html": html_body,
        })
        logger.info(
            "[SUPPORT] ✅ Support email sent | user_id=%s | to='%s'",
            user_id,
            ADMIN_EMAIL,
        )
    except Exception as exc:
        # Never surface a Resend failure to the user as a 500 — log it for ops.
        logger.error(
            "[SUPPORT] ❌ Failed to send support email | user_id=%s | error=%s",
            user_id,
            exc,
        )

    return {
        "status": "success",
        "detail": "Your message has been received. Our support team will get back to you shortly.",
    }
