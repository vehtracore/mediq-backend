"""
Firebase Cloud Messaging (FCM) push notification utility.

Initialises the Firebase Admin SDK from a service-account JSON.
The FIREBASE_CREDENTIALS env var can be either:
  - A raw JSON string (e.g. on Render / cloud hosts)
  - A file path to a service-account JSON file (local dev)
Exposes a single helper `send_push_notification` used by the rest of
the backend to deliver push messages to individual devices.
"""

import os
import json
import logging

import firebase_admin
from firebase_admin import credentials, messaging

logger = logging.getLogger("uvicorn.error")

# ---------------------------------------------------------------------------
# Firebase Admin SDK initialisation
# ---------------------------------------------------------------------------
_FIREBASE_APP = None

_cred_raw = os.getenv("FIREBASE_CREDENTIALS")

if _cred_raw:
    _cred_value = _cred_raw.strip()
    looks_like_json = _cred_value.startswith("{")

    if looks_like_json:
        try:
            cred_dict = json.loads(_cred_value)
            if not isinstance(cred_dict, dict):
                raise ValueError("FIREBASE_CREDENTIALS JSON must be an object.")

            private_key = cred_dict.get("private_key")
            if isinstance(private_key, str):
                cred_dict["private_key"] = private_key.replace("\\n", "\n")

            _cred = credentials.Certificate(cred_dict)
            _FIREBASE_APP = firebase_admin.initialize_app(_cred)
            logger.info("[FCM] Firebase Admin SDK initialised (from JSON env var)")
        except json.JSONDecodeError as exc:
            logger.error(
                "[FCM] Invalid FCM JSON format in FIREBASE_CREDENTIALS: %s",
                exc,
            )
        except Exception as exc:
            logger.error(
                "[FCM] Failed to initialise Firebase Admin SDK from JSON env var: %s",
                exc,
            )
    else:
        # Local development can still point FIREBASE_CREDENTIALS to a JSON file.
        try:
            _cred = credentials.Certificate(_cred_value)
            _FIREBASE_APP = firebase_admin.initialize_app(_cred)
            logger.info("[FCM] Firebase Admin SDK initialised (from file path)")
        except Exception as exc:
            logger.error(
                "[FCM] Failed to initialise Firebase Admin SDK from file path: %s",
                exc,
            )
else:
    logger.warning(
        "[FCM] FIREBASE_CREDENTIALS env var not set — push notifications disabled."
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def send_push_notification(
    token: str,
    title: str,
    body: str,
    data: dict | None = None,
) -> str | None:
    """
    Send a push notification to a single device.

    Args:
        token: FCM device registration token.
        title: Notification title shown on the device.
        body:  Notification body text.
        data:  Optional dict of string key/value pairs sent as data payload.

    Returns:
        The FCM message ID on success, or ``None`` on failure.
    """
    if _FIREBASE_APP is None:
        logger.warning("[FCM] Cannot send — Firebase Admin SDK not initialised.")
        return None

    message = messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        data=data or {},
        token=token,
    )

    try:
        msg_id = messaging.send(message)
        logger.info(f"[FCM] Push sent successfully (id={msg_id})")
        return msg_id
    except Exception as exc:
        logger.error(f"[FCM] Push send failed: {exc}")
        return None


def dispatch_push(
    token: str | None,
    title: str,
    body: str,
    data: dict | None = None,
    *,
    event_label: str = "FCM",
) -> str | None:
    """
    Sentry-aware fire-and-forget wrapper for ``send_push_notification``.

    Differences from the raw helper:
    • Silently skips (returns None) when *token* is falsy — avoids crashing
      when a user has not granted notification permission.
    • Wraps the entire dispatch in a try/except so FCM failures are forwarded
      to Sentry as ``logger.error`` events (which the LoggingIntegration in
      main.py converts into Sentry issues) without propagating the exception
      to the calling request handler.

    Args:
        token:       FCM device registration token (may be None / empty string).
        title:       Notification title.
        body:        Notification body text.
        data:        Optional string key/value pairs sent as data payload.
        event_label: Short label prefixed to log messages for tracing.

    Returns:
        The FCM message ID on success, or ``None`` on any failure / skip.
    """
    if not token:
        logger.debug("[%s] dispatch_push skipped — no FCM token.", event_label)
        return None

    try:
        return send_push_notification(token=token, title=title, body=body, data=data)
    except Exception as exc:
        # logger.error is captured by Sentry's LoggingIntegration as an issue.
        logger.error(
            "[%s] FCM dispatch_push failed: %s",
            event_label,
            exc,
            exc_info=True,
        )
        return None
