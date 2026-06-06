"""
Redis caching foundation.

Provides a thin wrapper around redis.Redis for get/set operations
with TTL support.  Connection URL is read from the UPSTASH_REDIS_REST_URL
environment variable, falling back to a local Redis instance.
"""

import logging
import os

import redis

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

REDIS_URL: str = os.getenv("UPSTASH_REDIS_REST_URL", "redis://localhost:6379")

_redis_client: redis.Redis | None = None


def get_redis_client() -> redis.Redis:
    """Return a lazily-initialised, module-level Redis client."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(
            REDIS_URL,
            decode_responses=True,  # Return strings instead of bytes
        )
        logger.info("[Cache] Redis client initialised — %s", REDIS_URL)
    return _redis_client


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def get_cache(key: str) -> str | None:
    """Retrieve a value from the cache.

    Returns ``None`` when the key does not exist **or** if Redis is
    unreachable (fail-open so the app degrades gracefully).
    """
    try:
        return get_redis_client().get(key)
    except redis.RedisError as exc:
        logger.warning("[Cache] GET failed for key '%s': %s", key, exc)
        return None


def set_cache(key: str, value: str, expire_in_seconds: int = 3600) -> bool:
    """Store a value in the cache with an optional TTL (default 1 hour).

    Returns ``True`` on success, ``False`` on failure (fail-open).
    """
    try:
        get_redis_client().set(key, value, ex=expire_in_seconds)
        return True
    except redis.RedisError as exc:
        logger.warning("[Cache] SET failed for key '%s': %s", key, exc)
        return False
