"""
Termii Notification Service
============================
Async wrapper around the Termii messaging API.

Provides two methods:
  • send_sms()   — POST /api/sms/send
  • send_voice() — POST /api/sms/voice/call

Both methods use httpx.AsyncClient so they never block the event loop.
API credentials are pulled exclusively from environment variables so
secrets are never hard-coded.
"""

import os
import logging
import httpx

logger = logging.getLogger("uvicorn.error")

# ─── Termii API base URL ───────────────────────────────────────────────────────
TERMII_BASE_URL = "https://api.ng.termii.com"


class TermiiService:
    """Async client for the Termii messaging platform."""

    def __init__(self) -> None:
        self.api_key: str = os.getenv("TERMII_API_KEY", "")
        self.sender_id: str = os.getenv("TERMII_SENDER_ID", "MDQplus")

        if not self.api_key:
            logger.warning(
                "[TERMII] ⚠️  TERMII_API_KEY is not set. "
                "SMS/Voice alerts will fail until the key is configured."
            )

    # ─── Public: Send SMS ──────────────────────────────────────────────────────

    async def send_sms(self, to: str, message: str) -> bool:
        """
        Send a plain-text SMS via Termii.

        Args:
            to:      Recipient phone number in international format (e.g. '+2348012345678').
            message: The SMS body text.

        Returns:
            True  if Termii accepted the request (2xx response).
            False on any network or API error (error is logged, not re-raised).
        """
        endpoint = f"{TERMII_BASE_URL}/api/sms/send"
        payload = {
            "to": to,
            "from": self.sender_id,
            "sms": message,
            "type": "plain",
            "channel": "generic",  # Falls back through DND routes automatically
            "api_key": self.api_key,
        }

        logger.info(f"[TERMII] 📤 Sending SMS to {to}")

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(endpoint, json=payload)
                response.raise_for_status()
                logger.info(
                    f"[TERMII] ✅ SMS delivered | status={response.status_code} "
                    f"| body={response.text[:200]}"
                )
                return True

        except httpx.HTTPStatusError as exc:
            logger.error(
                f"[TERMII] ❌ SMS HTTP error | status={exc.response.status_code} "
                f"| body={exc.response.text[:300]}"
            )
        except httpx.RequestError as exc:
            # Network-level failure (DNS, timeout, connection refused, etc.)
            logger.error(
                f"[TERMII] ❌ SMS network error | type={type(exc).__name__} | detail={exc}"
            )
        except Exception as exc:
            logger.error(f"[TERMII] ❌ SMS unexpected error | {type(exc).__name__}: {exc}")

        return False

    # ─── Public: Trigger Voice Call ────────────────────────────────────────────

    async def send_voice_call(self, to: str, message: str) -> bool:
        """
        Trigger a text-to-speech voice call via Termii.

        Args:
            to:      Recipient phone number in international format.
            message: The text that will be read aloud to the recipient.

        Returns:
            True  if Termii accepted the request (2xx response).
            False on any network or API error (error is logged, not re-raised).
        """
        endpoint = f"{TERMII_BASE_URL}/api/sms/voice/call"
        payload = {
            "api_key": self.api_key,
            "phone_number": to,
            "code": message,  # Termii voice/call uses 'code' as the TTS body
        }

        logger.info(f"[TERMII] 📞 Initiating voice call to {to}")

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(endpoint, json=payload)
                response.raise_for_status()
                logger.info(
                    f"[TERMII] ✅ Voice call initiated | status={response.status_code} "
                    f"| body={response.text[:200]}"
                )
                return True

        except httpx.HTTPStatusError as exc:
            logger.error(
                f"[TERMII] ❌ Voice call HTTP error | status={exc.response.status_code} "
                f"| body={exc.response.text[:300]}"
            )
        except httpx.RequestError as exc:
            logger.error(
                f"[TERMII] ❌ Voice call network error | type={type(exc).__name__} | detail={exc}"
            )
        except Exception as exc:
            logger.error(
                f"[TERMII] ❌ Voice call unexpected error | {type(exc).__name__}: {exc}"
            )

        return False


# ─── Module-level singleton ────────────────────────────────────────────────────
# Import this instance wherever you need to send alerts:
#   from app.services.termii_service import termii_service
termii_service = TermiiService()
