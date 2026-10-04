"""Internal-only curated source administration: python -m app.tools.clinical_knowledge_cli."""

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from sqlalchemy import text

from app.core.database import SessionLocal
from app.services.clinical_embedding import get_embedding_provider
from app.services.clinical_ingestion import (
    SourceRegistration, activate_version, close_version, ingest_version,
    register_source,
)
from app.services.clinical_knowledge import (
    ClinicalEvidenceQuery, KnowledgeConfig, retrieve_evidence,
)
from app.services.clinical_source_updates import check_active_sources, sources_needing_review


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Private MDQ+ curated clinical library operator tool")
    commands = root.add_subparsers(dest="command", required=True)
    register = commands.add_parser("register")
    for name in ("title", "organization", "jurisdiction", "source-type",
                 "license-note", "approved-by"):
        register.add_argument("--" + name, required=True)
    register.add_argument("--canonical-url")
    register.add_argument("--trust-tier", type=int, required=True)
    register.add_argument("--freshness-class", choices=("STABLE", "STANDARD", "SENSITIVE"),
                          required=True)
    register.add_argument("--review-interval-days", type=int, required=True)
    register.add_argument("--update-check-frequency-hours", type=int, required=True)
    for action in ("ingest", "reindex"):
        ingest = commands.add_parser(action)
        ingest.add_argument("--source-id", required=True)
        ingest.add_argument("--edition", required=True,
                            help="New edition label for reindex; published versions are immutable")
        ingest.add_argument("--file", type=Path, required=True)
        ingest.add_argument("--publication-date", type=date.fromisoformat)
        ingest.add_argument("--effective-date", type=date.fromisoformat)
        ingest.add_argument("--conflict-group")
        ingest.add_argument("--conflict-stance")
        ingest.add_argument("--approved-curated-material", action="store_true", required=True)
    for action in ("activate", "retire", "withdraw"):
        command = commands.add_parser(action)
        command.add_argument("--version-id", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--source-id")
    smoke = commands.add_parser("smoke")
    smoke.add_argument("--concepts", required=True,
                       help="De-identified clinical concepts only, never raw patient text")
    smoke.add_argument("--jurisdiction", default="NG")
    checker = commands.add_parser("check-updates")
    checker.add_argument("--limit", type=int, default=50)
    checker.add_argument("--all", action="store_true", help="Include sources not yet due")
    review = commands.add_parser("updates-report")
    review.add_argument("--limit", type=int, default=100)
    return root


async def run(args: argparse.Namespace) -> dict:
    with SessionLocal() as db:
        try:
            if args.command == "register":
                result = {"source_id": register_source(db, SourceRegistration(
                    args.title, args.organization, args.jurisdiction, args.source_type,
                    args.canonical_url, args.trust_tier, args.license_note,
                    args.approved_by, args.freshness_class,
                    args.review_interval_days, args.update_check_frequency_hours))}
            elif args.command in {"ingest", "reindex"}:
                provider = get_embedding_provider()
                result = {"version_id": await ingest_version(
                    db, source_id=args.source_id, edition=args.edition,
                    publication_date=args.publication_date,
                    effective_date=args.effective_date, data=args.file.read_bytes(),
                    filename=args.file.name, embedding_provider=provider,
                    conflict_group=args.conflict_group,
                    conflict_stance=args.conflict_stance)}
            elif args.command == "activate":
                activate_version(db, args.version_id)
                result = {"version_id": args.version_id, "status": "ACTIVE"}
            elif args.command in {"retire", "withdraw"}:
                status = args.command.upper() + ("D" if args.command == "retire" else "N")
                close_version(db, args.version_id, status)
                result = {"version_id": args.version_id, "status": status}
            elif args.command == "inspect":
                rows = db.execute(text("""
                    SELECT s.source_id::text, s.canonical_title, s.issuing_organization,
                      s.jurisdiction, s.approval_status, s.license_status,
                      v.version_id::text, v.edition_label, v.status, v.chunk_count,
                      v.checksum, b.embedding_key, b.embedding_dimension,
                      s.freshness_class, s.review_interval_days,
                      s.update_check_frequency_hours, s.update_status,
                      s.last_checked_at, s.update_signal_reason
                    FROM clinical_sources s
                    LEFT JOIN clinical_document_versions v ON v.source_id = s.source_id
                    LEFT JOIN clinical_index_builds b ON b.build_id = v.index_build_id
                    WHERE CAST(:source_id AS uuid) IS NULL OR s.source_id = CAST(:source_id AS uuid)
                    ORDER BY s.created_at DESC, v.created_at DESC LIMIT 100
                """), {"source_id": args.source_id}).mappings()
                result = {"sources": [dict(row) for row in rows]}
            elif args.command == "check-updates":
                checks = await check_active_sources(db, limit=args.limit,
                                                    due_only=not args.all)
                result = {"checked": len(checks),
                          "results": [asdict(check) for check in checks]}
            elif args.command == "updates-report":
                result = {"sources_needing_review": sources_needing_review(db,
                                                                             limit=args.limit)}
            else:
                query = ClinicalEvidenceQuery(tuple(args.concepts.split()),
                                              purpose="OPERATOR_SMOKE",
                                              jurisdiction=args.jurisdiction)
                bundle = await retrieve_evidence(db, query,
                                                  config=KnowledgeConfig(enabled=True))
                result = {"status": bundle.status.value,
                          "sources": [item.public_metadata() for item in bundle.items],
                          "failure_category": bundle.failure_category}
            if args.command not in {"inspect", "smoke", "updates-report"}:
                db.commit()
            return result
        except Exception:
            db.rollback()
            raise


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run(parser().parse_args())), default=str))
