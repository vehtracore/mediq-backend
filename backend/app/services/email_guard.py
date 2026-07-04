import logging
import os
import re
import threading
from datetime import date, datetime, timezone

try:
    from email_validator import EmailNotValidError, validate_email
except Exception:  # pragma: no cover - defensive fallback if dependency changes
    EmailNotValidError = ValueError
    validate_email = None


logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}
_EMAIL_FALLBACK_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_COUNTER_LOCK = threading.Lock()
_COUNTER_DATE: date | None = None
_COUNTER_COUNT = 0
_RECIPIENT_LAST_SENT_AT: dict[str, datetime] = {}


def env_bool(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in _TRUTHY


def email_delivery_enabled() -> bool:
    return env_bool("EMAIL_DELIVERY_ENABLED", default=False)


def email_test_endpoint_enabled() -> bool:
    return env_bool("EMAIL_TEST_ENDPOINT_ENABLED", default=False)


def get_resend_api_key() -> str:
    return os.getenv("RESEND_API_KEY", "").strip()


def get_from_email(default: str = "MDQ+ <noreply@mdqplus.com>") -> str:
    return os.getenv("RESEND_FROM_EMAIL") or os.getenv("EMAIL_FROM") or default


def mask_email(email: str | None) -> str:
    if not email or "@" not in email:
        return "(invalid)"
    local, domain = email.split("@", 1)
    masked_local = local[:1] + "***" if len(local) <= 2 else local[:2] + "***"
    return f"{masked_local}@{domain}"


def normalize_email_address(email: str) -> str | None:
    candidate = (email or "").strip()
    if not candidate:
        return None
    if validate_email is not None:
        try:
            return validate_email(candidate, check_deliverability=False).normalized
        except EmailNotValidError:
            return None
    return candidate.lower() if _EMAIL_FALLBACK_RE.match(candidate) else None


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default)).strip()
    try:
        return max(int(raw_value), 0)
    except ValueError:
        logger.warning("[EMAIL GUARD] Invalid %s=%r; using %s.", name, raw_value, default)
        return default


def _daily_send_limit() -> int:
    return _env_int("EMAIL_DAILY_SEND_LIMIT", 80)


def _recipient_cooldown_seconds() -> int:
    return _env_int("EMAIL_RECIPIENT_COOLDOWN_SECONDS", 300)


def _reserve_email_slot(*, to_email: str, subject: str, purpose: str) -> bool:
    daily_limit = _daily_send_limit()
    cooldown_seconds = _recipient_cooldown_seconds()
    now = datetime.now(timezone.utc)
    today = now.date()
    recipient_key = to_email.lower()

    global _COUNTER_DATE, _COUNTER_COUNT

    with _COUNTER_LOCK:
        if _COUNTER_DATE != today:
            _COUNTER_DATE = today
            _COUNTER_COUNT = 0
            _RECIPIENT_LAST_SENT_AT.clear()

        if cooldown_seconds > 0:
            last_sent_at = _RECIPIENT_LAST_SENT_AT.get(recipient_key)
            if last_sent_at is not None:
                elapsed = (now - last_sent_at).total_seconds()
                if elapsed < cooldown_seconds:
                    logger.warning(
                        "[EMAIL GUARD] Recipient cooldown blocked send to=%s subject=%r purpose=%s elapsed=%.1fs cooldown=%ss",
                        mask_email(to_email),
                        subject,
                        purpose,
                        elapsed,
                        cooldown_seconds,
                    )
                    return False

        if daily_limit > 0 and _COUNTER_COUNT >= daily_limit:
            logger.error(
                "[EMAIL GUARD] Daily email cap reached; blocked send to=%s subject=%r purpose=%s count=%s limit=%s",
                mask_email(to_email),
                subject,
                purpose,
                _COUNTER_COUNT,
                daily_limit,
            )
            return False

        _COUNTER_COUNT += 1
        _RECIPIENT_LAST_SENT_AT[recipient_key] = now
        logger.info(
            "[EMAIL GUARD] Reserved email send slot count=%s/%s to=%s purpose=%s",
            _COUNTER_COUNT,
            daily_limit if daily_limit > 0 else "unlimited",
            mask_email(to_email),
            purpose,
        )
        return True


def reserve_email_send(to_email: str, subject: str, *, purpose: str) -> str | None:
    normalized = normalize_email_address(to_email)
    if normalized is None:
        logger.warning(
            "[EMAIL GUARD] Blocked invalid recipient to=%r subject=%r purpose=%s",
            to_email,
            subject,
            purpose,
        )
        return None

    if not email_delivery_enabled():
        logger.warning(
            "[EMAIL GUARD] EMAIL_DELIVERY_ENABLED is false; skipped send to=%s subject=%r purpose=%s",
            mask_email(normalized),
            subject,
            purpose,
        )
        return None

    if not get_resend_api_key():
        logger.error(
            "[EMAIL GUARD] RESEND_API_KEY is not configured; skipped send to=%s subject=%r purpose=%s",
            mask_email(normalized),
            subject,
            purpose,
        )
        return None

    if not _reserve_email_slot(to_email=normalized, subject=subject, purpose=purpose):
        return None

    return normalized
