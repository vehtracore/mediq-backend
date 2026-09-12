"""Per-user in-flight and hourly abuse guards for billable STT calls."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status

try:
    import redis

    from app.core.cache import get_redis_client
except ImportError:  # pragma: no cover - production installs redis
    redis = None
    get_redis_client = None


logger = logging.getLogger(__name__)

STT_RATE_LIMIT = 10
STT_RATE_WINDOW_SECONDS = 60 * 60
_STT_LOCK_TTL_SECONDS = 120
_STT_COMPLETED_TTL_SECONDS = 10 * 60

_LOCAL_LOCK = threading.Lock()
_LOCAL_INFLIGHT: dict[int, tuple[str, float]] = {}
_LOCAL_RATE: dict[int, list[float]] = {}
_LOCAL_COMPLETED: dict[tuple[int, str], float] = {}

_COMPARE_AND_DELETE = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""


@dataclass
class STTRequestLease:
    user_id: int
    owner: str
    request_digest: str | None
    redis_active: bool = False
    completed: bool = False


def stt_request_digest(request_identifier: str | None) -> str | None:
    if not request_identifier:
        return None
    return hashlib.sha256(request_identifier.encode("utf-8")).hexdigest()


def _lock_key(user_id: int) -> str:
    return f"mdq:stt:inflight:{user_id}"


def _request_key(user_id: int, digest: str) -> str:
    return f"mdq:stt:request:{user_id}:{digest}"


def _rate_key(user_id: int) -> str:
    return f"mdq:stt:rate:{user_id}"


def _prune(now: float) -> None:
    rate_cutoff = now - STT_RATE_WINDOW_SECONDS
    for user_id, attempts in list(_LOCAL_RATE.items()):
        active = [attempt for attempt in attempts if attempt > rate_cutoff]
        if active:
            _LOCAL_RATE[user_id] = active
        else:
            _LOCAL_RATE.pop(user_id, None)
    for key, expiry in list(_LOCAL_COMPLETED.items()):
        if expiry <= now:
            _LOCAL_COMPLETED.pop(key, None)


def acquire_stt_request_lease(
    user_id: int,
    request_identifier: str | None,
) -> STTRequestLease:
    now = time.monotonic()
    owner = str(uuid.uuid4())
    request_digest = stt_request_digest(request_identifier)
    with _LOCAL_LOCK:
        _prune(now)
        if request_digest and (user_id, request_digest) in _LOCAL_COMPLETED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This transcription request was already completed.",
            )
        inflight = _LOCAL_INFLIGHT.get(user_id)
        if inflight and inflight[1] > now:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A voice transcription is already being processed.",
            )
        _LOCAL_INFLIGHT[user_id] = (owner, now + _STT_LOCK_TTL_SECONDS)

    lease = STTRequestLease(user_id, owner, request_digest)
    if get_redis_client is None:
        return lease
    try:
        client = get_redis_client()
        if request_digest and client.exists(_request_key(user_id, request_digest)):
            release_stt_request_lease(lease)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This transcription request was already submitted.",
            )
        if not client.set(
            _lock_key(user_id), owner, nx=True, ex=_STT_LOCK_TTL_SECONDS
        ):
            release_stt_request_lease(lease)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A voice transcription is already being processed.",
            )
        lease.redis_active = True
        if request_digest and not client.set(
            _request_key(user_id, request_digest),
            owner,
            nx=True,
            ex=_STT_LOCK_TTL_SECONDS,
        ):
            release_stt_request_lease(lease)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This transcription request was already submitted.",
            )
    except HTTPException:
        raise
    except ((redis.RedisError, ValueError) if redis is not None else (ValueError,)):
        logger.warning("[STT] Redis unavailable; using local in-flight guard")
    return lease


def enforce_stt_user_rate_limit(user_id: int) -> None:
    if get_redis_client is not None:
        try:
            client = get_redis_client()
            attempts = int(client.incr(_rate_key(user_id)))
            if attempts == 1:
                client.expire(_rate_key(user_id), STT_RATE_WINDOW_SECONDS)
            if attempts > STT_RATE_LIMIT:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Voice transcription limit reached. Try again later.",
                )
            return
        except HTTPException:
            raise
        except ((redis.RedisError, ValueError) if redis is not None else (ValueError,)):
            logger.warning("[STT] Redis unavailable; using local rate guard")

    now = time.monotonic()
    with _LOCAL_LOCK:
        _prune(now)
        attempts = _LOCAL_RATE.setdefault(user_id, [])
        if len(attempts) >= STT_RATE_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Voice transcription limit reached. Try again later.",
            )
        attempts.append(now)


def release_stt_request_lease(lease: STTRequestLease) -> None:
    now = time.monotonic()
    with _LOCAL_LOCK:
        current = _LOCAL_INFLIGHT.get(lease.user_id)
        if current and current[0] == lease.owner:
            _LOCAL_INFLIGHT.pop(lease.user_id, None)
        if lease.completed and lease.request_digest:
            _LOCAL_COMPLETED[(lease.user_id, lease.request_digest)] = (
                now + _STT_COMPLETED_TTL_SECONDS
            )

    if not lease.redis_active or get_redis_client is None:
        return
    try:
        client = get_redis_client()
        client.eval(_COMPARE_AND_DELETE, 1, _lock_key(lease.user_id), lease.owner)
        if lease.request_digest:
            request_key = _request_key(lease.user_id, lease.request_digest)
            if lease.completed:
                client.set(request_key, "completed", ex=_STT_COMPLETED_TTL_SECONDS)
            else:
                client.eval(_COMPARE_AND_DELETE, 1, request_key, lease.owner)
    except ((redis.RedisError, ValueError) if redis is not None else (ValueError,)):
        logger.warning("[STT] Redis release failed for user_id=%s", lease.user_id)
