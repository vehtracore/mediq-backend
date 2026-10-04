"""Staging-only MedlinePlus operator CLI: python -m app.tools.medlineplus_corpus_cli."""

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path

from sqlalchemy import text

from app.core.database import SessionLocal
from app.services.clinical_embedding import get_embedding_provider
from app.services.medlineplus_corpus import (fetch_latest_feed, ingest_topic,
                                             mark_updates, plan, selected_topics)

MANIFEST = Path(__file__).resolve().parents[3] / 'docs' / 'medlineplus_launch_topics.csv'


def parser():
    root = argparse.ArgumentParser(description='Staging-only NLM summary corpus')
    root.add_argument('command', choices=('plan', 'check-updates', 'import', 'stage-updates'))
    root.add_argument('--manifest', type=Path, default=MANIFEST)
    root.add_argument('--archive', type=Path, help='Previously verified official dated ZIP')
    root.add_argument('--confirm-staging', action='store_true')
    return root


async def run(args):
    from app.services.medlineplus_feed import parse_feed

    feed = parse_feed(args.archive.read_bytes()) if args.archive else await fetch_latest_feed()
    topics = selected_topics(feed, args.manifest)
    with SessionLocal() as db:
        identity = db.execute(text("""SELECT current_database(), current_user,
          current_schema(), current_setting('server_version'),
          EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')""")).one()
        if not identity[4]:
            raise RuntimeError('target has no pgvector extension')
        summary = {'database': identity[0], 'role': identity[1], 'schema': identity[2],
                   'postgres_version': identity[3], 'pgvector_installed': identity[4],
                   'feed_date': feed.generated_at.date().isoformat(),
                   'feed_sha256': feed.checksum, 'selected': len(topics)}
        if args.command == 'plan':
            actions = plan(db, topics)
            summary['actions'] = dict(Counter(action.action for action in actions))
            return summary
        if not args.confirm_staging:
            raise RuntimeError('write commands require --confirm-staging and owner-verified target')
        if args.command == 'check-updates':
            actions = mark_updates(db, topics)
            db.commit()
            summary['actions'] = dict(Counter(action.action for action in actions))
            return summary
    provider = get_embedding_provider()
    results = Counter()
    failures = []
    for topic in topics:
        try:
            with SessionLocal() as db, db.begin():
                result = await ingest_topic(db, topic, provider,
                                            activate=args.command == 'import')
                if args.command == 'stage-updates' and result.action == 'DRAFT':
                    db.execute(text("""UPDATE clinical_sources
                      SET update_status = 'UPDATE_AVAILABLE',
                          update_signal_reason = 'NLM_DRAFT_AWAITING_REVIEW'
                      WHERE source_id = :id"""), {'id': result.source_id})
            results[result.action] += 1
        except Exception as exc:
            failures.append({'topic_id': topic.topic_id, 'category': type(exc).__name__})
    summary['actions'] = dict(results)
    summary['failures'] = failures
    return summary


if __name__ == '__main__':
    print(json.dumps(asyncio.run(run(parser().parse_args())), default=str))
