"""Per-user concurrency and duplicate protection for AI processing."""

import hashlib
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Optional

from fastapi import HTTPException, status
from app.core.api_errors import ApiError

try:
    import redis
    from app.core.cache import get_redis_client
except ImportError:
    redis = None
    get_redis_client: Optional[Callable] = None

logger = logging.getLogger(__name__)

_LOCK_TTL_SECONDS = 180
_COMPLETED_TTL_SECONDS = 600
AI_SAVE_RESULT_TTL_SECONDS = 24 * 60 * 60
AI_SAVE_RATE_LIMIT = 3
AI_SAVE_RATE_WINDOW_SECONDS = 60

_LOCAL_GUARD = threading.Lock()
_LOCAL_INFLIGHT: dict[int, tuple[str, float]] = {}
_LOCAL_COMPLETED: dict[tuple[int, str], float] = {}
_LOCAL_SAVE_RESULTS: dict[tuple[int, str], tuple[str, str, float]] = {}
_LOCAL_SAVE_RATE: dict[int, list[float]] = {}

_COMPARE_AND_DELETE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""


@dataclass
class AIRequestLease:
    user_id: int
    owner: str
    request_digest: Optional[str]
    redis_active: bool = False
    completed: bool = False


def _lock_key(user_id: int) -> str:
    return f"mdq:ai:inflight:{user_id}"


def _request_key(user_id: int, request_digest: str) -> str:
    return f"mdq:ai:request:{user_id}:{request_digest}"


def _save_result_key(user_id: int, request_digest: str) -> str:
    return f"mdq:ai:save-result:{user_id}:{request_digest}"


def _save_rate_key(user_id: int) -> str:
    return f"mdq:ai:save-rate:{user_id}"


def ai_request_digest(request_id: str) -> str:
    return hashlib.sha256(request_id.encode("utf-8")).hexdigest()


def _idempotency_mismatch() -> HTTPException:
    return ApiError(
        status.HTTP_409_CONFLICT,
        "request_conflict",
        "This idempotency key was already used for a different summary save.",
    )


def _encode_save_result(summary_id: str, request_fingerprint: str) -> str:
    return json.dumps(
        {
            "summary_id": summary_id,
            "request_fingerprint": request_fingerprint,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _decode_save_result(value: object) -> tuple[str, str] | None:
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    summary_id = parsed.get("summary_id")
    request_fingerprint = parsed.get("request_fingerprint")
    if not isinstance(summary_id, str) or not isinstance(request_fingerprint, str):
        return None
    return summary_id, request_fingerprint


def _prune_local_save_state(now: float) -> None:
    """Remove expired fallback entries while the caller holds _LOCAL_GUARD."""
    expired_results = [
        key
        for key, (_, _, expires_at) in _LOCAL_SAVE_RESULTS.items()
        if expires_at <= now
    ]
    for key in expired_results:
        _LOCAL_SAVE_RESULTS.pop(key, None)

    cutoff = now - AI_SAVE_RATE_WINDOW_SECONDS
    for rate_user_id, attempts in list(_LOCAL_SAVE_RATE.items()):
        active_attempts = [attempt for attempt in attempts if attempt > cutoff]
        if active_attempts:
            _LOCAL_SAVE_RATE[rate_user_id] = active_attempts
        else:
            _LOCAL_SAVE_RATE.pop(rate_user_id, None)


def _enforce_local_ai_save_rate_limit(user_id: int) -> None:
    now = time.monotonic()
    cutoff = now - AI_SAVE_RATE_WINDOW_SECONDS
    with _LOCAL_GUARD:
        _prune_local_save_state(now)
        attempts = [
            attempted_at
            for attempted_at in _LOCAL_SAVE_RATE.get(user_id, [])
            if attempted_at > cutoff
        ]
        if len(attempts) >= AI_SAVE_RATE_LIMIT:
            _LOCAL_SAVE_RATE[user_id] = attempts
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many summary save attempts. Please try again shortly.",
            )
        attempts.append(now)
        _LOCAL_SAVE_RATE[user_id] = attempts


def enforce_ai_save_rate_limit(user_id: int) -> None:
    """Limit non-replayed summary saves by authenticated user ID."""
    if get_redis_client is not None:
        try:
            client = get_redis_client()
            key = _save_rate_key(user_id)
            attempts = int(client.incr(key))
            if attempts == 1:
                client.expire(key, AI_SAVE_RATE_WINDOW_SECONDS)
            if attempts > AI_SAVE_RATE_LIMIT:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=(
                        "Too many summary save attempts. "
                        "Please try again shortly."
                    ),
                )
            return
        except HTTPException:
            raise
        except (
            (redis.RedisError, ValueError)
            if redis is not None
            else (ValueError,)
        ):
            logger.warning(
                "[AI REQUEST GUARD] Save rate-limit cache unavailable for "
                "user_id=%s",
                user_id,
            )

    _enforce_local_ai_save_rate_limit(user_id)


def get_ai_save_result(
    user_id: int,
    request_id: str,
    request_fingerprint: str,
) -> Optional[str]:
    """Return a completed save's summary UUID without caching medical data."""
    request_digest = ai_request_digest(request_id)
    now = time.monotonic()
    with _LOCAL_GUARD:
        _prune_local_save_state(now)
        cached = _LOCAL_SAVE_RESULTS.get((user_id, request_digest))
        if cached and cached[2] > now:
            if cached[1] != request_fingerprint:
                raise _idempotency_mismatch()
            return cached[0]
        if cached:
            _LOCAL_SAVE_RESULTS.pop((user_id, request_digest), None)

    if get_redis_client is None:
        return None
    try:
        result = get_redis_client().get(_save_result_key(user_id, request_digest))
        if result:
            decoded = _decode_save_result(result)
            if decoded is None:
                return None
            summary_id, stored_fingerprint = decoded
            if stored_fingerprint != request_fingerprint:
                raise _idempotency_mismatch()
            with _LOCAL_GUARD:
                _LOCAL_SAVE_RESULTS[(user_id, request_digest)] = (
                    summary_id,
                    stored_fingerprint,
                    now + AI_SAVE_RESULT_TTL_SECONDS,
                )
            return summary_id
    except (
        (redis.RedisError, ValueError)
        if redis is not None
        else (ValueError,)
    ):
        logger.warning(
            "[AI REQUEST GUARD] Save-result lookup unavailable for user_id=%s",
            user_id,
        )
    return None


def store_ai_save_result(
    user_id: int,
    request_id: str,
    summary_id: str,
    request_fingerprint: str,
) -> None:
    """Cache only the resulting UUID for a bounded replay-safe retry window."""
    request_digest = ai_request_digest(request_id)
    now = time.monotonic()
    with _LOCAL_GUARD:
        _prune_local_save_state(now)
        _LOCAL_SAVE_RESULTS[(user_id, request_digest)] = (
            summary_id,
            request_fingerprint,
            now + AI_SAVE_RESULT_TTL_SECONDS,
        )

    if get_redis_client is None:
        return
    try:
        get_redis_client().set(
            _save_result_key(user_id, request_digest),
            _encode_save_result(summary_id, request_fingerprint),
            ex=AI_SAVE_RESULT_TTL_SECONDS,
        )
    except (
        (redis.RedisError, ValueError)
        if redis is not None
        else (ValueError,)
    ):
        logger.warning(
            "[AI REQUEST GUARD] Save-result cache unavailable for user_id=%s",
            user_id,
        )


def _release_local(lease: AIRequestLease) -> None:
    now = time.monotonic()
    with _LOCAL_GUARD:
        current = _LOCAL_INFLIGHT.get(lease.user_id)
        if current and current[0] == lease.owner:
            _LOCAL_INFLIGHT.pop(lease.user_id, None)

        if lease.completed and lease.request_digest:
            _LOCAL_COMPLETED[(lease.user_id, lease.request_digest)] = (
                now + _COMPLETED_TTL_SECONDS
            )


def _release_redis_key_if_owned(key: str, owner: str) -> None:
    if get_redis_client is None:
        return
    get_redis_client().eval(
        _COMPARE_AND_DELETE_SCRIPT,
        1,
        key,
        owner,
    )


def release_ai_request_lease(lease: AIRequestLease) -> None:
    if lease.redis_active and get_redis_client is not None:
        try:
            if lease.request_digest:
                request_key = _request_key(
                    lease.user_id,
                    lease.request_digest,
                )
                if lease.completed:
                    get_redis_client().set(
                        request_key,
                        "completed",
                        ex=_COMPLETED_TTL_SECONDS,
                    )
                else:
                    _release_redis_key_if_owned(request_key, lease.owner)

            _release_redis_key_if_owned(
                _lock_key(lease.user_id),
                lease.owner,
            )
        except (
            (redis.RedisError, ValueError)
            if redis is not None
            else (ValueError,)
        ):
            logger.exception(
                "[AI REQUEST GUARD] Redis release failed for user_id=%s",
                lease.user_id,
            )
    _release_local(lease)


def acquire_ai_request_lease(
    user_id: int,
    request_id: Optional[str],
) -> AIRequestLease:
    owner = str(uuid.uuid4())
    request_digest = (
        ai_request_digest(request_id)
        if request_id
        else None
    )
    now = time.monotonic()

    with _LOCAL_GUARD:
        expired_completed = [
            key
            for key, expires_at in _LOCAL_COMPLETED.items()
            if expires_at <= now
        ]
        for key in expired_completed:
            _LOCAL_COMPLETED.pop(key, None)

        if request_digest and (user_id, request_digest) in _LOCAL_COMPLETED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This AI request was already submitted.",
            )

        inflight = _LOCAL_INFLIGHT.get(user_id)
        if inflight and inflight[1] > now:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "An AI request is already being processed. "
                    "Please wait for it to finish."
                ),
            )

        _LOCAL_INFLIGHT[user_id] = (
            owner,
            now + _LOCK_TTL_SECONDS,
        )

    lease = AIRequestLease(
        user_id=user_id,
        owner=owner,
        request_digest=request_digest,
    )

    if get_redis_client is None:
        logger.warning(
            "[AI REQUEST GUARD] Redis package unavailable; using local guard "
            "for user_id=%s",
            user_id,
        )
        return lease

    try:
        client = get_redis_client()
        if request_digest and client.exists(
            _request_key(user_id, request_digest)
        ):
            _release_local(lease)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This AI request was already submitted.",
            )

        acquired = client.set(
            _lock_key(user_id),
            owner,
            nx=True,
            ex=_LOCK_TTL_SECONDS,
        )
        if not acquired:
            _release_local(lease)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "An AI request is already being processed. "
                    "Please wait for it to finish."
                ),
            )

        lease.redis_active = True
        if request_digest:
            request_acquired = client.set(
                _request_key(user_id, request_digest),
                owner,
                nx=True,
                ex=_LOCK_TTL_SECONDS,
            )
            if not request_acquired:
                release_ai_request_lease(lease)
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This AI request was already submitted.",
                )
    except HTTPException:
        raise
    except (
        (redis.RedisError, ValueError)
        if redis is not None
        else (ValueError,)
    ):
        logger.warning(
            "[AI REQUEST GUARD] Redis unavailable; using local guard "
            "for user_id=%s",
            user_id,
            exc_info=True,
        )

    return lease
