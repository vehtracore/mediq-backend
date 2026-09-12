"""One-shot Firebase multicast transport and provider-error classification."""

from dataclasses import dataclass, field
import json
import logging
import os

try:
    import firebase_admin
    from firebase_admin import credentials, messaging
except ImportError:  # Static/test environments may intentionally omit Firebase.
    firebase_admin = None
    credentials = None
    messaging = None

logger = logging.getLogger("uvicorn.error")

CONSULTATIONS_CHANNEL_ID = "consultations"
GENERAL_CHANNEL_ID = "general"


@dataclass(frozen=True)
class PushDeliveryResult:
    successful_count: int = 0
    permanent_failure_tokens: tuple[str, ...] = field(default_factory=tuple)
    transient_failure_count: int = 0


def _initialise_firebase():
    if firebase_admin is None or credentials is None:
        logger.warning("[FCM] firebase-admin is unavailable; push is disabled.")
        return None

    credential_value = (os.getenv("FIREBASE_CREDENTIALS") or "").strip()
    if not credential_value:
        logger.warning("[FCM] FIREBASE_CREDENTIALS is unset; push is disabled.")
        return None

    try:
        try:
            return firebase_admin.get_app()
        except ValueError:
            pass
        if credential_value.startswith("{"):
            credential_data = json.loads(credential_value)
            private_key = credential_data.get("private_key")
            if isinstance(private_key, str):
                credential_data["private_key"] = private_key.replace("\\n", "\n")
            credential = credentials.Certificate(credential_data)
        else:
            credential = credentials.Certificate(credential_value)
        return firebase_admin.initialize_app(credential)
    except Exception as exc:
        logger.error("[FCM] Firebase Admin initialisation failed: %s", exc)
        return None


_FIREBASE_APP = _initialise_firebase()


def _is_permanent_token_error(exc: Exception) -> bool:
    code = str(getattr(exc, "code", "") or "").lower()
    message = str(exc).lower()
    if code in {
        "registration-token-not-registered",
        "unregistered",
        "sender-id-mismatch",
        "mismatched-credential",
    }:
        return True
    return code == "invalid-argument" and "registration token" in message


def send_multicast_notification(
    *,
    tokens: list[str],
    title: str,
    body: str,
    data: dict[str, str],
    channel_id: str = GENERAL_CHANNEL_ID,
) -> PushDeliveryResult:
    """Attempt one provider-supported multicast send for each token."""
    unique_tokens = list(dict.fromkeys(token for token in tokens if token))
    if not unique_tokens or _FIREBASE_APP is None or messaging is None:
        return PushDeliveryResult()

    success_count = 0
    transient_count = 0
    permanent_tokens: list[str] = []

    for start in range(0, len(unique_tokens), 500):
        batch_tokens = unique_tokens[start : start + 500]
        message = messaging.MulticastMessage(
            notification=messaging.Notification(title=title, body=body),
            data={key: str(value) for key, value in data.items()},
            android=messaging.AndroidConfig(
                priority=(
                    "high" if channel_id == CONSULTATIONS_CHANNEL_ID else "normal"
                ),
                notification=messaging.AndroidNotification(channel_id=channel_id),
            ),
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(sound="default")
                )
            ),
            tokens=batch_tokens,
        )

        try:
            response = messaging.send_each_for_multicast(message)
        except Exception as exc:
            transient_count += len(batch_tokens)
            logger.error(
                "[FCM] Multicast attempt failed before per-token results: %s",
                type(exc).__name__,
            )
            continue

        for token, send_response in zip(batch_tokens, response.responses):
            if send_response.success:
                success_count += 1
                continue
            error = send_response.exception or RuntimeError("Unknown FCM error")
            permanent = _is_permanent_token_error(error)
            if permanent:
                permanent_tokens.append(token)
            else:
                transient_count += 1
            logger.warning(
                "[FCM] Device delivery failed code=%s permanent=%s",
                getattr(error, "code", type(error).__name__),
                permanent,
            )

    return PushDeliveryResult(
        successful_count=success_count,
        permanent_failure_tokens=tuple(permanent_tokens),
        transient_failure_count=transient_count,
    )
