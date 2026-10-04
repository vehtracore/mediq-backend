"""De-identified launch retrieval and staging footprint readout."""

import argparse
import asyncio
import csv
import json
import time
from dataclasses import replace
from pathlib import Path

from sqlalchemy import text

from app.core.database import SessionLocal
from app.services import clinical_cache
from app.services.clinical_embedding import get_embedding_provider
from app.services.clinical_knowledge import (KnowledgeConfig, POLICY_VERSION, query_from_text,
                                             retrieve_evidence, validate_evidence_references)

CASES = Path(__file__).resolve().parents[3] / 'docs' / 'clinical_launch_retrieval_eval.csv'


async def run(web: bool, selected: set[str] | None = None,
              question: str | None = None, repeat: bool = False,
              official_url: str | None = None, generate: bool = False):
    class ExactOfficialResult:
        async def search(self, _terms, _domains, _jurisdiction):
            return [official_url]

    with CASES.open(newline='', encoding='utf-8') as stream:
        cases = [case for case in csv.DictReader(stream)
                 if selected is None or case['case_id'] in selected]
    if question is not None:
        cases = [{'case_id': 'custom_synthetic', 'synthetic_question': question}]
    results = []
    with SessionLocal() as db:
        for case in cases:
            query = query_from_text(case['synthetic_question'], purpose='LAUNCH_EVAL')
            start = time.monotonic()
            bundle = await retrieve_evidence(db, query, config=KnowledgeConfig(
                enabled=True, web_enabled=web, cache_enabled=True),
                web_provider=ExactOfficialResult() if official_url else None)
            result = {
                'case_id': case['case_id'], 'concepts': query.normalized_text(),
                'synthetic_question': case['synthetic_question'],
                'status': bundle.status.value, 'failure': bundle.failure_category,
                'web_checked': bundle.web_checked,
                'latency_ms': int((time.monotonic() - start) * 1000),
                'sources': [{'title': item.title, 'url': item.canonical_url,
                             'jurisdiction': item.jurisdiction, 'origin': item.origin,
                             'methods': item.retrieval_methods, 'freshness': item.freshness_state,
                             'evidence_id': item.evidence_id,
                             'publication_date': item.publication_date,
                             'excerpt': item.excerpt[:180]} for item in bundle.items],
            }
            if generate:
                from app.services.ai_safety import evaluate_safety
                from app.services.ai_orchestrator import InteractionInput, run_interaction
                from app.services.ai_service import get_medical_response
                from app.services.ai_answer_scope import number_evidence
                safety = evaluate_safety(case['synthetic_question'])
                result['urgent_flags'] = safety.flags
                result['supplied_evidence_ids'] = []
                result['cited_evidence_ids'] = []
                try:
                    if safety.urgent_override:
                        response = await run_interaction(InteractionInput(
                            request_id='synthetic-launch-' + case['case_id'],
                            interaction_id=None, message=case['synthetic_question'],
                            language='English', history=[], user_context={}, db=db))
                        result['generation_path'] = response.mode.value
                        result['generated_answer'] = response.result.model_dump(mode='json')
                    else:
                        bundle = replace(bundle, items=bundle.items[:3])
                        result['generation_path'] = 'CONVERSATION_SERVICE'
                        result['supplied_evidence_ids'] = sorted(bundle.ids)
                        result['supplied_evidence_context'] = json.loads(bundle.model_context())
                        result['numbered_evidence_context'] = number_evidence(bundle.model_context()).context
                        response = await get_medical_response(
                            case['synthetic_question'], history=[], user_context={},
                            target_language='English',
                            evidence_context=bundle.model_context() if bundle.items or
                            bundle.failure_category == 'current_official_evidence_unavailable' else None)
                        cited = validate_evidence_references(list(response.evidence_ids), bundle)
                        result['cited_evidence_ids'] = [entry.evidence_id for entry in cited]
                        result['generated_answer'] = response.text
                        result['answer_scope'] = response.answer_scope.model_dump(exclude_none=True)
                        result['returned_citations'] = [entry.public_metadata() for entry in cited]
                except Exception as exc:
                    result['generation_error'] = type(exc).__name__
            if repeat:
                again = time.monotonic()
                cached = await retrieve_evidence(db, query, config=KnowledgeConfig(
                    enabled=True, web_enabled=web, cache_enabled=True),
                    web_provider=ExactOfficialResult() if official_url else None)
                result['repeat_latency_ms'] = int((time.monotonic() - again) * 1000)
                result['repeat_same_ids'] = cached.ids == bundle.ids
            results.append(result)
    return results


async def cache_smoke(question: str):
    clinical_cache.clear()
    query = query_from_text(question, purpose='CACHE_EVAL')
    config = KnowledgeConfig(enabled=True, cache_enabled=True)
    provider = get_embedding_provider()
    with SessionLocal() as db:
        revision_before, mutated_before = clinical_cache.library_revision(db)
        normalized = query.normalized_text()
        if {'foamy', 'urine'} <= set(normalized.split()):
            normalized += ' proteinuria kidney'
        token = clinical_cache.cache_key(
            normalized_query=normalized, jurisdiction=query.jurisdiction,
            population=query.population, minimum_trust=query.minimum_trust_tier,
            min_effective_date=None, revision=revision_before, embedding_key=provider.key,
            policy_version=POLICY_VERSION,
            limits=(config.vector_candidates, config.lexical_candidates, config.final_items,
                    config.max_excerpt_chars, config.min_sufficient_items))
        first_miss = clinical_cache.get(token) is None
        started = time.monotonic()
        first = await retrieve_evidence(db, query, config=config, embedding_provider=provider)
        first_ms = round((time.monotonic() - started) * 1000, 2)
        second_hit = clinical_cache.get(token) is first
        started = time.monotonic()
        second = await retrieve_evidence(db, query, config=config, embedding_provider=provider)
        second_ms = round((time.monotonic() - started) * 1000, 2)
        revision_after, mutated_after = clinical_cache.library_revision(db)
        valid_ids = db.execute(text("""
          SELECT count(*) FROM clinical_evidence_chunks c
          JOIN clinical_document_versions v ON v.version_id = c.document_version_id
          JOIN clinical_sources s ON s.source_id = v.source_id
          WHERE c.chunk_id::text = ANY(:ids) AND v.status = 'ACTIVE'
            AND s.approval_status = 'APPROVED' AND s.license_status = 'APPROVED'
        """), {'ids': sorted(second.ids)}).scalar()
    return {
        'concepts': query.normalized_text(), 'first_cache_miss': first_miss,
        'second_cache_hit': second_hit and first is second, 'first_latency_ms': first_ms,
        'second_latency_ms': second_ms, 'revision_before': revision_before,
        'revision_after': revision_after, 'mutated_before': mutated_before,
        'mutated_after': mutated_after, 'same_evidence_ids': first.ids == second.ids,
        'evidence_ids': sorted(first.ids), 'cache_value_type': type(second).__name__,
        'all_cached_ids_active_approved': valid_ids == len(second.ids),
        'cache_key_hex_length': len(token),
    }


def footprint():
    with SessionLocal() as db:
        overview = dict(db.execute(text("""
          SELECT (SELECT count(*) FROM clinical_sources) AS sources,
            (SELECT count(*) FROM clinical_document_versions) AS versions,
            (SELECT count(*) FROM clinical_document_versions WHERE status = 'ACTIVE') AS active_versions,
            (SELECT count(*) FROM clinical_evidence_chunks) AS chunks,
            (SELECT count(*) FROM clinical_index_builds) AS index_builds,
            (SELECT min(embedding_dimension) FROM clinical_index_builds) AS min_dimension,
            (SELECT max(embedding_dimension) FROM clinical_index_builds) AS max_dimension,
            (SELECT count(*) FROM clinical_evidence_chunks c JOIN clinical_document_versions v
              ON v.version_id = c.document_version_id WHERE v.status = 'ACTIVE') AS active_chunks,
            (SELECT coalesce(sum(octet_length(text)), 0) FROM clinical_evidence_chunks) AS chunk_text_bytes,
            (SELECT coalesce(sum(pg_column_size(embedding)), 0) FROM clinical_evidence_chunks) AS vector_bytes,
            (SELECT pg_total_relation_size('clinical_sources') +
                    pg_total_relation_size('clinical_document_versions') +
                    pg_total_relation_size('clinical_evidence_chunks') +
                    pg_total_relation_size('clinical_index_builds')) AS library_bytes
        """)).mappings().one())
        overview['active_topics'] = db.execute(text("""
          SELECT count(DISTINCT s.source_id) FROM clinical_sources s
          JOIN clinical_document_versions v ON v.source_id = s.source_id
          WHERE v.status = 'ACTIVE' AND s.approval_status = 'APPROVED'
        """)).scalar()
        overview['active_chunk_text_bytes'] = db.execute(text("""
          SELECT coalesce(sum(octet_length(c.text)), 0)
          FROM clinical_evidence_chunks c JOIN clinical_document_versions v
            ON v.version_id = c.document_version_id WHERE v.status = 'ACTIVE'
        """)).scalar()
        overview['relations'] = [dict(row) for row in db.execute(text("""
          SELECT relname, pg_relation_size(oid) AS heap_bytes,
                 pg_indexes_size(oid) AS index_bytes,
                 pg_total_relation_size(oid) AS total_bytes
          FROM pg_class WHERE relname IN ('clinical_sources',
            'clinical_document_versions', 'clinical_evidence_chunks',
            'clinical_index_builds', 'clinical_library_state') ORDER BY relname
        """)).mappings()]
        overview['complete_library_bytes'] = sum(row['total_bytes'] for row in overview['relations'])
        overview['average_active_chunks_per_topic'] = overview['active_chunks'] / overview['active_topics']
        overview['embedding_builds'] = [dict(row) for row in db.execute(text("""
          SELECT embedding_key, embedding_dimension, status, count(*) AS builds
          FROM clinical_index_builds GROUP BY embedding_key, embedding_dimension, status
        """)).mappings()]
        overview['indexes'] = [dict(row) for row in db.execute(text("""
          SELECT tablename, indexname FROM pg_indexes
          WHERE tablename LIKE 'clinical_%' ORDER BY tablename, indexname
        """)).mappings()]
        overview['vector_version'] = db.execute(text(
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
        )).scalar()
        return overview


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--web', action='store_true')
    parser.add_argument('--case', action='append')
    parser.add_argument('--question', help='Synthetic de-identified question only')
    parser.add_argument('--repeat', action='store_true')
    parser.add_argument('--cache-smoke', help='Synthetic de-identified query only')
    parser.add_argument('--footprint-only', action='store_true')
    parser.add_argument('--official-url', help='Exact official URL to validate through retrieval')
    parser.add_argument('--official-diagnostic', help='Read-only direct fetch of an official URL')
    parser.add_argument('--generate', action='store_true',
                        help='Use real generation on synthetic cases; no patient account/quota')
    args = parser.parse_args()
    result = {'footprint': footprint()}
    if args.official_diagnostic:
        import httpx
        from app.services.clinical_web import _fetch_official, trusted_url

        async def diagnostic():
            async with httpx.AsyncClient() as client:
                document, fallback = await _fetch_official(
                    args.official_diagnostic, 'diabetes safety', client=client)
            return {'trusted_host': trusted_url(args.official_diagnostic) is not None,
                    'fetched': document is not None, 'fallback_eligible': fallback,
                    'publication_date': str(document.publication_date) if document else None,
                    'title': document.title if document else None}

        result['official_diagnostic'] = asyncio.run(diagnostic())
    if args.cache_smoke:
        result['cache'] = asyncio.run(cache_smoke(args.cache_smoke))
    if not args.footprint_only and not args.cache_smoke and not args.official_diagnostic:
        result['cases'] = asyncio.run(run(args.web, set(args.case) if args.case else None,
                                          args.question, args.repeat, args.official_url,
                                          args.generate))
    print(json.dumps(result, default=str))
