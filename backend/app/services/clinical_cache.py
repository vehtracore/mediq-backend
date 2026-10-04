"""Bounded process-local cache for public, versioned clinical evidence only."""

from collections import OrderedDict
from hashlib import sha256
import json
from threading import Lock
from time import monotonic
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


_entries: OrderedDict[str, tuple[float, Any]] = OrderedDict()
_lock = Lock()


def library_revision(db: Session) -> tuple[int, bool]:
    with db.begin_nested():
        row = db.execute(text("""
            SELECT revision,
              current_setting('mdq.clinical_library_mutated', true) = 'true' AS mutated
            FROM clinical_library_state WHERE singleton = TRUE
        """)).one()
    return int(row.revision), bool(row.mutated)


def cache_key(*, normalized_query: str, jurisdiction: str, population: tuple[str, ...],
              minimum_trust: int, min_effective_date: str | None, revision: int,
              embedding_key: str, limits: tuple[int, ...],
              policy_version: str = 'hybrid-1') -> str:
    # Hash even the de-identified terms so cache inspection cannot expose queries.
    payload = (normalized_query, jurisdiction.upper(), population, minimum_trust,
               min_effective_date, revision, embedding_key, limits, policy_version)
    return sha256(json.dumps(payload, separators=(',', ':')).encode()).hexdigest()


def get(key: str) -> Any | None:
    with _lock:
        entry = _entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= monotonic():
            del _entries[key]
            return None
        _entries.move_to_end(key)
        return value


def put(key: str, value: Any, *, ttl_seconds: int, max_entries: int) -> None:
    with _lock:
        _entries[key] = (monotonic() + ttl_seconds, value)
        _entries.move_to_end(key)
        while len(_entries) > max_entries:
            _entries.popitem(last=False)


def clear() -> None:
    with _lock:
        _entries.clear()
