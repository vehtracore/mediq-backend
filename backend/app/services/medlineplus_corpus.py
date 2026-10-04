"""Operator-managed MedlinePlus summaries; no patient ingestion path uses this."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.clinical_embedding import EmbeddingProvider
from app.services.clinical_ingestion import (SourceRegistration, activate_version,
                                             extract_document, ingest_version, register_source)
from app.services.medlineplus_feed import FEED_URL, Feed, Topic, parse_feed

ORGANIZATION = 'U.S. National Library of Medicine / MedlinePlus'
APPROVAL = 'MDQ+ owner staging-only corpus directive 2026-09-27'
LICENSE_NOTE = ('NLM-produced MedlinePlus health-topic summary; public domain. '
                'Source: MedlinePlus, National Library of Medicine. '
                'No third-party linked content or endorsement.')
MAX_INDEX_BYTES = 200_000
_ARCHIVE = re.compile(r'/xml/mplus_topics_compressed_(\d{4}-\d{2}-\d{2})\.zip\Z')


class _ArchiveLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag != 'a':
            return
        href = dict(attrs).get('href', '')
        url = urljoin(FEED_URL, href)
        parsed = urlsplit(url)
        match = _ARCHIVE.fullmatch(parsed.path)
        if (match and parsed.scheme == 'https' and parsed.hostname == 'medlineplus.gov'
                and not parsed.query and not parsed.fragment):
            self.paths.append((match.group(1), url))


async def fetch_latest_feed(client: httpx.AsyncClient | None = None) -> Feed:
    """Read only the official HTTPS index and its same-host dated ZIP."""
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=30.0, follow_redirects=False)
    try:
        response = await client.get(FEED_URL)
        response.raise_for_status()
        if len(response.content) > MAX_INDEX_BYTES:
            raise ValueError('MedlinePlus index exceeds size limit')
        parser = _ArchiveLinks()
        parser.feed(response.text)
        if not parser.paths:
            raise ValueError('no official MedlinePlus dated XML archive found')
        _, url = max(parser.paths)
        archive = await client.get(url)
        archive.raise_for_status()
        feed = parse_feed(archive.content)
        if feed.generated_at.date().isoformat() not in url:
            raise ValueError('feed and index dates disagree')
        return feed
    finally:
        if own_client:
            await client.aclose()


def selected_topics(feed: Feed, manifest: Path) -> list[Topic]:
    with manifest.open(newline='', encoding='utf-8') as stream:
        rows = list(csv.DictReader(stream))
    if not 100 <= len(rows) <= 200:
        raise ValueError('unexpected launch manifest size')
    seen = set()
    selected = []
    for row in rows:
        topic_id = row['topic_id']
        topic = feed.topics.get(topic_id)
        if (topic_id in seen or topic is None or topic.title != row['title'] or
                not row['coverage_category'].strip() or not row['selection_reason'].strip()):
            raise ValueError(f'invalid manifest topic {topic_id}')
        seen.add(topic_id)
        selected.append(topic)
    return selected


def _existing(db: Session, url: str):
    return db.execute(text("""
        SELECT s.source_id::text AS source_id, s.issuing_organization,
          v.version_id::text AS version_id, v.checksum, v.status
        FROM clinical_sources s
        LEFT JOIN clinical_document_versions v ON v.source_id = s.source_id
          AND v.status = 'ACTIVE'
        WHERE s.canonical_url = :url
    """), {'url': url}).mappings().first()


@dataclass(frozen=True)
class TopicAction:
    topic_id: str
    action: str
    source_id: str | None = None
    version_id: str | None = None


def plan(db: Session, topics: list[Topic]) -> list[TopicAction]:
    result = []
    for topic in topics:
        row = _existing(db, topic.url)
        if row and row['issuing_organization'] != ORGANIZATION:
            raise ValueError(f'canonical URL belongs to another source: {topic.topic_id}')
        action = ('NEW' if row is None else 'UNCHANGED' if row['checksum'] == topic.checksum
                  else 'CHANGED')
        result.append(TopicAction(topic.topic_id, action,
                                  row['source_id'] if row else None,
                                  row['version_id'] if row else None))
    return result


async def ingest_topic(db: Session, topic: Topic, provider: EmbeddingProvider,
                       *, activate: bool) -> TopicAction:
    row = _existing(db, topic.url)
    if row and row['issuing_organization'] != ORGANIZATION:
        raise ValueError('canonical URL belongs to another source')
    if row and row['checksum'] == topic.checksum:
        return TopicAction(topic.topic_id, 'UNCHANGED', row['source_id'], row['version_id'])
    data = topic.document()
    chunks = extract_document(data, f'medlineplus-{topic.topic_id}.md')
    if not chunks or len(chunks) > 40 or any(len(c.text) < 20 for c in chunks):
        raise ValueError('unexpected extraction shape')
    if row:
        source_id = row['source_id']
    else:
        source_id = register_source(db, SourceRegistration(
            title=topic.title, organization=ORGANIZATION, jurisdiction='GLOBAL',
            source_type='CLINICAL_REFERENCE', canonical_url=topic.url, trust_tier=2,
            license_note=f'{LICENSE_NOTE} Topic ID: {topic.topic_id}',
            approved_by=APPROVAL, freshness_class='STANDARD',
            review_interval_days=365, update_check_frequency_hours=24))
    edition = f'NLM-{topic.checksum[:16]}'
    version_id = await ingest_version(
        db, source_id=source_id, edition=edition, publication_date=None,
        effective_date=None, data=data, filename=f'medlineplus-{topic.topic_id}.md',
        embedding_provider=provider)
    if activate:
        activate_version(db, version_id)
        db.execute(text("""UPDATE clinical_sources SET update_status = 'CURRENT',
          last_checked_at = now(), last_seen_sha256 = :checksum,
          update_signal_reason = NULL WHERE source_id = :id"""),
                   {'checksum': topic.checksum, 'id': source_id})
    return TopicAction(topic.topic_id, 'ACTIVATED' if activate else 'DRAFT',
                       source_id, version_id)


def mark_updates(db: Session, topics: list[Topic]) -> list[TopicAction]:
    actions = plan(db, topics)
    for action, topic in zip(actions, topics, strict=True):
        if action.source_id is None:
            continue
        db.execute(text("""UPDATE clinical_sources SET last_checked_at = now(),
          update_status = :status, update_signal_reason = :reason,
          last_seen_sha256 = :digest WHERE source_id = :id"""), {
            'id': action.source_id,
            'status': 'UPDATE_AVAILABLE' if action.action == 'CHANGED' else 'CURRENT',
            'reason': 'NLM_TOPIC_CHECKSUM_CHANGED' if action.action == 'CHANGED' else None,
            'digest': topic.checksum})
    return actions


async def run_due_medlineplus_check() -> dict:
    """Daily checksum comparison; changed text is not auto-activated."""
    from app.core.database import SessionLocal

    with SessionLocal() as db, db.begin():
        due = db.execute(text("""SELECT EXISTS (
          SELECT 1 FROM clinical_sources s JOIN clinical_document_versions v
            ON v.source_id = s.source_id AND v.status = 'ACTIVE'
          WHERE s.issuing_organization = :organization
            AND (s.last_checked_at IS NULL OR s.last_checked_at <= now() - interval '24 hours')
        )"""), {'organization': ORGANIZATION}).scalar()
        if not due:
            return {'status': 'not_due', 'changed': 0}
        locked = db.execute(text('SELECT pg_try_advisory_xact_lock(:key)'),
                            {'key': 0x4D44514D504C5553}).scalar()
        if not locked:
            return {'status': 'already_running', 'changed': 0}
        feed = await fetch_latest_feed()
        manifest = Path(__file__).resolve().parents[3] / 'docs' / 'medlineplus_launch_topics.csv'
        actions = mark_updates(db, selected_topics(feed, manifest))
        return {'status': 'completed',
                'changed': sum(a.action == 'CHANGED' for a in actions)}
