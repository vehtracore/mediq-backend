"""
Termii Notification Service
============================
Async wrapper around the Termii messaging API.

Provides one method:
  • send_sms() — POST /api/sms/send

The method uses httpx.AsyncClient so it never blocks the event loop.
API credentials are pulled exclusively from environment variables so
secrets are never hard-coded.

Phone Number Sanitization
--------------------------
Termii requires numbers in strict international format WITHOUT a leading
plus sign, e.g. 2348012345678.

The _sanitize_phone() helper handles all common input variants:
  •  +2348012345678  →  2348012345678  (strips leading +)
  •   2348012345678  →  2348012345678  (already correct, no change)
  •    08012345678   →  2348012345678  (leading 0 replaced with 234)
  •  080-1234-5678   →  2348012345678  (strips dashes/spaces first)

The default country code is 234 (Nigeria).  Extend _sanitize_phone()
when multi-country support is required.
"""

import os
import re
import logging
import httpx

logger = logging.getLogger("uvicorn.error")

# ─── Termii API base URL ───────────────────────────────────────────────────────
TERMII_BASE_URL = "https://api.ng.termii.com"

# Default country code applied when user enters a local number (e.g. 080...)
_DEFAULT_COUNTRY_CODE = "234"


def _sanitize_phone(raw: str) -> str:
    """
    Normalise a phone number to the format Termii expects: no + or leading 0,
    digits only, with country code prefix.

    Examples
    --------
    >>> _sanitize_phone("+2348012345678")
    '2348012345678'
    >>> _sanitize_phone("08012345678")
    '2348012345678'
    >>> _sanitize_phone("080 1234 5678")
    '2348012345678'
    >>> _sanitize_phone("2348012345678")
    '2348012345678'
    """
    # Strip all non-digit characters (spaces, dashes, parentheses, +)
    digits = re.sub(r"\D", "", raw)

    # Local format: leading 0 (e.g. 08012345678 → 2348012345678)
    if digits.startswith("0"):
        digits = _DEFAULT_COUNTRY_CODE + digits[1:]

    return digits


class TermiiService:
    """Async client for the Termii messaging platform."""

    def __init__(self) -> None:
        self.api_key: str = os.getenv("TERMII_API_KEY", "")
        self.sender_id: str = os.getenv("TERMII_SENDER_ID", "MDQplus")

        if not self.api_key:
            logger.warning(
                "[TERMII] ⚠️  TERMII_API_KEY is not set. "
                "SMS alerts will fail until the key is configured."
            )

    # ─── Public: Send SMS ──────────────────────────────────────────────────────

    async def send_sms(self, to: str, message: str) -> bool:
        """
        Send a plain-text SMS via Termii.

        The phone number is sanitized to Termii's required format before
        the API call is made, so callers may pass any common variant
        (e.g. '+234...', '080...', '234...').

        Args:
            to:      Recipient phone number (any common Nigerian format).
            message: The SMS body text.

        Returns:
            True  if Termii accepted the request (2xx response).
            False on any network or API error (error is logged, not re-raised).
        """
        # ── Sanitize ──────────────────────────────────────────────────────────
        sanitized = _sanitize_phone(to)
        logger.info(
            "[TERMII] 🔢 Phone sanitization | raw=%r → sanitized=%r",
            to,
            sanitized,
        )

        endpoint = f"{TERMII_BASE_URL}/api/sms/send"
        payload = {
            "to": sanitized,
            "from": self.sender_id,
            "sms": message,
            "type": "plain",
            "channel": "dnd",  # DND route bypasses telco Sender ID blocks via whitelisted numeric route
            "api_key": self.api_key,
        }

        logger.info(
            "[TERMII] 📤 Sending SMS | to=%s | sender_id=%s | message_length=%d",
            sanitized,
            self.sender_id,
            len(message),
        )

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(endpoint, json=payload)

                # ── Log full response regardless of status ─────────────────
                logger.info(
                    "[TERMII] 📥 Response received | status=%s | body=%s",
                    response.status_code,
                    response.text,
                )

                response.raise_for_status()

                logger.info(
                    "[TERMII] ✅ SMS accepted by Termii | status=%s",
                    response.status_code,
                )
                return True

        except httpx.HTTPStatusError as exc:
            logger.error(
                "[TERMII] ❌ SMS HTTP error | status=%s | body=%s",
                exc.response.status_code,
                exc.response.text,
            )
        except httpx.RequestError as exc:
            # Network-level failure (DNS, timeout, connection refused, etc.)
            logger.error(
                "[TERMII] ❌ SMS network error | type=%s | detail=%s",
                type(exc).__name__,
                exc,
            )
        except Exception as exc:
            logger.error(
                "[TERMII] ❌ SMS unexpected error | %s: %s",
                type(exc).__name__,
                exc,
            )

        return False


# ─── Module-level singleton ────────────────────────────────────────────────────
# Import this instance wherever you need to send alerts:
#   from app.services.termii_service import termii_service
termii_service = TermiiService()
