"""
Firebase Cloud Messaging (FCM) push notification utility.

Initialises the Firebase Admin SDK from a service-account JSON whose
path is read from the FIREBASE_CREDENTIALS environment variable.
Exposes a single helper `send_push_notification` used by the rest of
the backend to deliver push messages to individual devices.
"""

import os
import logging

import firebase_admin
from firebase_admin import credentials, messaging

logger = logging.getLogger("uvicorn.error")

# ---------------------------------------------------------------------------
# Firebase Admin SDK initialisation
# ---------------------------------------------------------------------------
_FIREBASE_APP = None

_cred_path = os.getenv("FIREBASE_CREDENTIALS")

if _cred_path:
    try:
        _cred = credentials.Certificate(_cred_path)
        _FIREBASE_APP = firebase_admin.initialize_app(_cred)
        logger.info(f"[FCM] Firebase Admin SDK initialised (creds: {_cred_path})")
    except Exception as exc:
        logger.error(f"[FCM] Failed to initialise Firebase Admin SDK: {exc}")
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
