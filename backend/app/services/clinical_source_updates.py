"""Bounded operator checks for canonical official source changes."""

import hashlib
import logging
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.clinical_web import MAX_PAGE_BYTES, _PageParser, trusted_url

logger = logging.getLogger(__name__)
_CHECK_LOCK_KEY = 0x4D4451434C494E35


@dataclass(frozen=True)
class SourceCheck:
    source_id: str
    status: str
    reason: str | None


async def _fingerprint(url: str, client: httpx.AsyncClient) -> tuple[str, str | None, str | None, str | None]:
    if trusted_url(url) is None:
        return 'CHECK_FAILED', 'UNAPPROVED_HOST', None, None
    try:
        async with client.stream('GET', url, follow_redirects=False, timeout=12.0) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                target = urljoin(url, response.headers.get('location', ''))
                if trusted_url(target) is None:
                    return 'UPDATE_AVAILABLE', 'UNTRUSTED_REDIRECT', None, None
                return 'UPDATE_AVAILABLE', 'URL_CHANGED', target, None
            if response.status_code in {404, 410}:
                return 'UPDATE_AVAILABLE', 'SOURCE_UNAVAILABLE', None, None
            if response.status_code != 200:
                return 'CHECK_FAILED', 'HTTP_ERROR', None, None
            kind = response.headers.get('content-type', '').split(';')[0].lower()
            if kind not in {'text/html', 'application/pdf'}:
                return 'CHECK_FAILED', 'UNSUPPORTED_CONTENT', None, None
            if int(response.headers.get('content-length', '0')) > MAX_PAGE_BYTES:
                return 'CHECK_FAILED', 'CONTENT_TOO_LARGE', None, None
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > MAX_PAGE_BYTES:
                    return 'CHECK_FAILED', 'CONTENT_TOO_LARGE', None, None
            etag = response.headers.get('etag', '')[:240] or None
            modified = response.headers.get('last-modified', '')[:240] or None
        if kind == 'text/html':
            parser = _PageParser()
            parser.feed(content.decode('utf-8', errors='replace'))
            if parser.canonical:
                target = urljoin(url, parser.canonical)
                if target != url:
                    if trusted_url(target) is None:
                        return 'UPDATE_AVAILABLE', 'UNTRUSTED_CANONICAL', None, None
                    return 'UPDATE_AVAILABLE', 'URL_CHANGED', target, None
        return 'OK', etag, modified, hashlib.sha256(content).hexdigest()
    except (httpx.HTTPError, ValueError, OSError):
        return 'CHECK_FAILED', 'NETWORK_ERROR', None, None


async def check_active_sources(db: Session, *, limit: int = 50,
                               due_only: bool = True,
                               client: httpx.AsyncClient | None = None) -> list[SourceCheck]:
    if not 1 <= limit <= 100:
        raise ValueError('source check limit must be 1-100')
    rows = db.execute(text("""
        SELECT s.source_id::text, s.canonical_url, s.update_status,
          s.last_seen_etag, s.last_seen_modified, s.last_seen_sha256
        FROM clinical_sources s
        WHERE s.approval_status = 'APPROVED' AND s.canonical_url IS NOT NULL
          AND s.issuing_organization <> 'U.S. National Library of Medicine / MedlinePlus'
          AND EXISTS (SELECT 1 FROM clinical_document_versions v
                      WHERE v.source_id = s.source_id AND v.status = 'ACTIVE')
          AND (:due_only = FALSE OR s.last_checked_at IS NULL OR
               s.last_checked_at <= now() -
                 (s.update_check_frequency_hours * interval '1 hour'))
        ORDER BY s.last_checked_at NULLS FIRST, s.source_id LIMIT :limit
    """), {'limit': limit, 'due_only': due_only}).mappings().all()
    own_client = client is None
    client = client or httpx.AsyncClient()
    results = []
    try:
        for row in rows:
            result = await _fingerprint(row['canonical_url'], client)
            state, first, second, digest = result
            if state == 'OK':
                if row['last_seen_sha256'] is None:
                    status, reason = 'BASELINED', None
                elif (row['last_seen_sha256'] != digest or
                      (row['last_seen_etag'] and first and row['last_seen_etag'] != first) or
                      (row['last_seen_modified'] and second and row['last_seen_modified'] != second)):
                    status, reason = 'UPDATE_AVAILABLE', 'CONTENT_CHANGED'
                else:
                    status, reason = 'CURRENT', None
                if row['update_status'] == 'UPDATE_AVAILABLE':
                    status, reason = 'UPDATE_AVAILABLE', 'AWAITING_REVIEW'
                db.execute(text("""
                    UPDATE clinical_sources SET update_status = :status,
                      last_checked_at = now(), last_seen_etag = :etag,
                      last_seen_modified = :modified, last_seen_sha256 = :digest,
                      update_signal_reason = :reason
                    WHERE source_id = :source_id
                """), {'status': status, 'etag': first, 'modified': second,
                        'digest': digest, 'reason': reason, 'source_id': row['source_id']})
            else:
                status = state
                reason = first
                signal_url = second
                if row['update_status'] == 'UPDATE_AVAILABLE' and status == 'CHECK_FAILED':
                    status = 'UPDATE_AVAILABLE'
                db.execute(text("""
                    UPDATE clinical_sources SET update_status = :status,
                      last_checked_at = now(), update_signal_url = :signal_url,
                      update_signal_reason = :reason
                    WHERE source_id = :source_id
                """), {'status': status, 'signal_url': signal_url,
                        'reason': reason, 'source_id': row['source_id']})
            results.append(SourceCheck(row['source_id'], status, reason))
        return results
    finally:
        if own_client:
            await client.aclose()


def sources_needing_review(db: Session, *, limit: int = 100) -> list[dict]:
    if not 1 <= limit <= 100:
        raise ValueError('report limit must be 1-100')
    return [dict(row) for row in db.execute(text("""
        SELECT source_id::text, canonical_title, issuing_organization,
          canonical_url, freshness_class, update_status, update_signal_reason,
          update_signal_url, last_checked_at
        FROM clinical_sources
        WHERE update_status IN ('UPDATE_AVAILABLE', 'CHECK_FAILED')
        ORDER BY last_checked_at DESC NULLS LAST LIMIT :limit
    """), {'limit': limit}).mappings()]


async def run_due_source_checks(*, limit: int = 50) -> dict:
    """Run one due batch; a transaction lock prevents duplicate worker runs."""
    from app.core.database import SessionLocal

    with SessionLocal() as db, db.begin():
        acquired = db.execute(
            text('SELECT pg_try_advisory_xact_lock(:lock_key)'),
            {'lock_key': _CHECK_LOCK_KEY},
        ).scalar()
        if not acquired:
            return {'status': 'already_running', 'checked': 0,
                    'update_available': 0, 'check_failed': 0}
        checks = await check_active_sources(db, limit=limit)
        result = {'status': 'completed', 'checked': len(checks),
                  'update_available': sum(c.status == 'UPDATE_AVAILABLE' for c in checks),
                  'check_failed': sum(c.status == 'CHECK_FAILED' for c in checks)}
        logger.info('[KNOWLEDGE] source_update_check checked=%d update_available=%d '
                    'check_failed=%d', result['checked'], result['update_available'],
                    result['check_failed'])
        return result
