"""Per-user concurrency and duplicate protection for AI processing."""

import hashlib
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Optional

from fastapi import HTTPException, status

try:
    import redis
    from app.core.cache import get_redis_client
except ImportError:
    redis = None
    get_redis_client: Optional[Callable] = None

logger = logging.getLogger(__name__)

_LOCK_TTL_SECONDS = 180
_COMPLETED_TTL_SECONDS = 600

_LOCAL_GUARD = threading.Lock()
_LOCAL_INFLIGHT: dict[int, tuple[str, float]] = {}
_LOCAL_COMPLETED: dict[tuple[int, str], float] = {}

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
        hashlib.sha256(request_id.encode("utf-8")).hexdigest()
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
