"""Curated PostgreSQL hybrid retrieval with explicit fail-open grounding state."""

from __future__ import annotations

import json
import asyncio
import hashlib
import logging
import os
import re
import time
from dataclasses import dataclass, replace
from datetime import date, timedelta
from enum import StrEnum
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.clinical_embedding import (
    EmbeddingProvider, EmbeddingUnavailable, get_embedding_provider, validate_vectors,
)
from app.services import clinical_cache
from app.services.clinical_freshness import FreshnessState, classify, topic_sensitive

logger = logging.getLogger(__name__)
POLICY_VERSION = "hybrid-2"
WEB_SEARCH_TIMEOUT_SECONDS = 30
_MEDICAL_TERMS = {
    "urine", "foamy", "proteinuria", "kidney", "headache", "migraine",
    "fever", "cough", "breathing", "asthma", "rash", "skin", "abdominal",
    "pain", "pregnancy", "pregnant", "pediatric", "child", "infant",
    "medication", "medicine", "metformin", "amoxicillin", "paracetamol",
    "hypertension", "diabetes", "urinalysis", "swelling", "bleeding",
    "malaria", "infection", "antibiotic", "dosage", "treatment",
    "effects", "blood", "pressure", "heart", "chest", "nausea",
    "guideline", "guidelines", "evaluation", "symptoms", "allergy",
    "drug", "recall", "warning", "withdrawn", "contraindication",
    "approval", "outbreak", "vaccination", "vaccine", "safety",
    "current", "latest", "recent",
    "breath", "breathless", "shortness", "antibiotics", "cold",
    "vomiting", "diarrhea", "diarrhoea", "dehydration", "urinary",
    "urinate", "suicide", "crisis", "harm", "interaction", "interact",
    "confused", "shaky", "stroke", "migraine", "emergency",
    "hypoglycemia", "sugar",
    "hay", "stone", "stones", "high", "low", "nutrition",
    "pandemic", "preparedness", "prevention", "response", "commitment",
}
_CLINICAL_MARKERS = _MEDICAL_TERMS | {"guideline", "treatment", "dose", "side", "effect", "test"}


class EvidenceStatus(StrEnum):
    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"
    NONE = "NONE"
    CONFLICTING = "CONFLICTING"
    STALE = "STALE"


class GroundingStatus(StrEnum):
    UNGROUNDED = "UNGROUNDED"
    PARTIALLY_GROUNDED = "PARTIALLY_GROUNDED"
    GROUNDED = "GROUNDED"


@dataclass(frozen=True)
class KnowledgeConfig:
    enabled: bool = False
    vector_candidates: int = 12
    lexical_candidates: int = 12
    final_items: int = 5
    min_sufficient_items: int = 2
    max_excerpt_chars: int = 900
    cache_enabled: bool = False
    cache_ttl_seconds: int = 900
    cache_max_entries: int = 256
    web_enabled: bool = False

    @classmethod
    def from_env(cls) -> "KnowledgeConfig":
        def bounded(name: str, default: int, low: int, high: int) -> int:
            try:
                value = int(os.getenv(name, str(default)))
            except ValueError:
                return default
            return value if low <= value <= high else default
        return cls(
            enabled=os.getenv("CLINICAL_KNOWLEDGE_ENABLED", "false").lower() == "true",
            vector_candidates=bounded("CLINICAL_VECTOR_CANDIDATES", 12, 1, 50),
            lexical_candidates=bounded("CLINICAL_LEXICAL_CANDIDATES", 12, 1, 50),
            final_items=bounded("CLINICAL_EVIDENCE_ITEMS", 5, 1, 8),
            min_sufficient_items=bounded("CLINICAL_MIN_SUFFICIENT_ITEMS", 2, 1, 5),
            max_excerpt_chars=bounded("CLINICAL_EVIDENCE_EXCERPT_CHARS", 900, 200, 1600),
            cache_enabled=os.getenv("CLINICAL_CACHE_ENABLED", "true").lower() == "true",
            cache_ttl_seconds=bounded("CLINICAL_CACHE_TTL_SECONDS", 900, 60, 1800),
            cache_max_entries=bounded("CLINICAL_CACHE_MAX_ENTRIES", 256, 16, 1024),
            web_enabled=os.getenv("CLINICAL_WEB_ENABLED", "false").lower() == "true",
        )


@dataclass(frozen=True)
class ClinicalEvidenceQuery:
    concepts: tuple[str, ...]
    purpose: str
    jurisdiction: str = "NG"
    population: tuple[str, ...] = ()
    min_effective_date: date | None = None
    minimum_trust_tier: int = 1

    def normalized_text(self) -> str:
        # Query construction is allowlist-based; no raw account/chat fields reach embeddings.
        words = [word.lower() for part in (*self.concepts, *self.population)
                 for word in re.findall(r"[a-zA-Z]{3,32}", part)]
        accepted = [word for word in words if word in _MEDICAL_TERMS]
        return " ".join(dict.fromkeys(accepted))[:240]


def query_from_text(message: str, *, purpose: str, jurisdiction: str = "NG") -> ClinicalEvidenceQuery:
    lowered = message.lower()
    words = [word for word in re.findall(r"[a-zA-Z]{3,32}", lowered)
             if word in _MEDICAL_TERMS]
    if re.search(r"\b(short of breath|shortness of breath|breathless)\b", lowered):
        words = [word for word in words if word != "breath"]
        words.append("breathing")
    if re.search(r"\b(harm myself|kill myself|end my life|self.harm)\b", lowered):
        words = [word for word in words if word not in {"harm", "self"}]
        words.extend(("suicide", "crisis"))
    if "diabetes" in words and {"shaky", "confused"} <= set(words):
        words.append("hypoglycemia")
    if "rash" in words and {"medicine", "medication", "drug"} & set(words):
        words.extend(("drug", "safety"))
    return ClinicalEvidenceQuery(tuple(dict.fromkeys(words)),
                                 purpose=purpose, jurisdiction=jurisdiction)


def query_from_assessment(concepts: Iterable[str], concern: str) -> ClinicalEvidenceQuery:
    category = query_from_text(concern, purpose="ASSESSMENT_RESULT")
    normalized = tuple(dict.fromkeys((*category.concepts, *(str(c).lower() for c in concepts))))
    return ClinicalEvidenceQuery(normalized, purpose="ASSESSMENT_RESULT")


def should_retrieve(message: str, *, lab: bool = False, media: bool = False) -> bool:
    if lab or media:
        return True
    words = set(re.findall(r"[a-zA-Z]{3,32}", message.lower()))
    return bool(words & _CLINICAL_MARKERS)


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    chunk_id: str
    source_id: str
    document_version_id: str
    title: str
    issuing_organization: str
    jurisdiction: str
    edition: str
    publication_date: str | None
    effective_date: str | None
    section: str | None
    page_start: int | None
    page_end: int | None
    anchor: str | None
    canonical_url: str | None
    trust_tier: int
    indexed_at: str
    excerpt: str
    retrieval_methods: tuple[str, ...] = ()
    conflict_group: str | None = None
    conflict_stance: str | None = None
    freshness_state: str = "CURRENT"
    origin: str = "CURATED"

    def public_metadata(self) -> dict:
        return {key: getattr(self, key) for key in (
            "evidence_id", "chunk_id", "source_id", "document_version_id", "title",
            "issuing_organization", "jurisdiction", "edition", "publication_date",
            "effective_date", "section", "page_start", "page_end", "anchor",
            "canonical_url",
        )}


@dataclass(frozen=True)
class EvidenceBundle:
    status: EvidenceStatus
    items: tuple[EvidenceItem, ...] = ()
    conflict: bool = False
    eligible_version_ids: tuple[str, ...] = ()
    index_build_ids: tuple[str, ...] = ()
    embedding_key: str | None = None
    embedding_dimension: int | None = None
    policy_version: str = POLICY_VERSION
    failure_category: str | None = None
    web_checked: bool = False

    @property
    def ids(self) -> set[str]:
        return {item.evidence_id for item in self.items}

    def model_context(self) -> str:
        return json.dumps({
            "status": self.status.value,
            "conflict": self.conflict,
            "web_checked": self.web_checked,
            "failure_category": self.failure_category,
            "items": [{"evidence_id": item.evidence_id, "text": item.excerpt,
                       "title": item.title, "section": item.section,
                       "jurisdiction": item.jurisdiction,
                       "edition": item.edition, "publication_date": item.publication_date,
                       "freshness": item.freshness_state, "origin": item.origin}
                      for item in self.items],
        }, ensure_ascii=False)


def _canonical_url(value: str | None) -> str | None:
    if not value:
        return None
    from urllib.parse import urlsplit, urlunsplit
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or
            parsed.password or parsed.fragment or any(ch.isspace() for ch in value)):
        return None
    return urlunsplit(("https", parsed.netloc.lower(), parsed.path or "/", parsed.query, ""))


_CANDIDATE_SQL = """
SELECT c.chunk_id::text AS chunk_id, c.document_version_id::text AS version_id,
       c.section_title, c.page_start, c.page_end, c.anchor, c.text AS excerpt,
       c.conflict_group, c.conflict_stance,
       c.checksum, c.created_at AS indexed_at, s.source_id::text AS source_id,
       s.canonical_title AS title, s.issuing_organization, s.jurisdiction,
       s.canonical_url, s.trust_tier, s.source_type, s.freshness_class,
       s.review_interval_days, s.update_status, v.edition_label AS edition,
       v.publication_date, v.effective_date, v.index_build_id::text AS build_id,
       {score} AS rank_score
FROM clinical_evidence_chunks c
JOIN clinical_document_versions v ON v.version_id = c.document_version_id
JOIN clinical_sources s ON s.source_id = v.source_id
JOIN clinical_index_builds b ON b.build_id = v.index_build_id
WHERE v.status = 'ACTIVE' AND s.approval_status = 'APPROVED'
  AND s.license_status = 'APPROVED' AND s.category = 'CURATED'
  AND NOT (s.issuing_organization = 'U.S. National Library of Medicine / MedlinePlus'
           AND c.text LIKE 'MedlinePlus topic ID:%')
  AND s.trust_tier >= :minimum_trust
  AND s.jurisdiction IN (:jurisdiction, 'GLOBAL')
  AND (CAST(:min_effective_date AS date) IS NULL OR v.effective_date >= CAST(:min_effective_date AS date))
  AND b.status = 'COMPLETE' AND b.embedding_key = :embedding_key
  AND b.embedding_dimension = :embedding_dimension
  AND {match}
ORDER BY rank_score {direction}
LIMIT :candidate_limit
"""

_STALE_SQL = """
SELECT EXISTS (
  SELECT 1 FROM clinical_evidence_chunks c
  JOIN clinical_document_versions v ON v.version_id = c.document_version_id
  JOIN clinical_sources s ON s.source_id = v.source_id
  WHERE s.approval_status = 'APPROVED' AND s.license_status = 'APPROVED'
    AND s.category = 'CURATED' AND s.jurisdiction IN (:jurisdiction, 'GLOBAL')
    AND c.lexical_search_data @@ websearch_to_tsquery('simple', :query_text)
    AND (v.status <> 'ACTIVE' OR
         (CAST(:min_effective_date AS date) IS NOT NULL AND
          v.effective_date < CAST(:min_effective_date AS date)))
  LIMIT 1
)
"""

_ELIGIBLE_SQL = """
SELECT v.version_id::text AS version_id
FROM clinical_document_versions v
JOIN clinical_sources s ON s.source_id = v.source_id
JOIN clinical_index_builds b ON b.build_id = v.index_build_id
WHERE v.status = 'ACTIVE' AND s.approval_status = 'APPROVED'
  AND s.license_status = 'APPROVED' AND s.category = 'CURATED'
  AND s.trust_tier >= :minimum_trust
  AND s.jurisdiction IN (:jurisdiction, 'GLOBAL')
  AND (CAST(:min_effective_date AS date) IS NULL OR
       v.effective_date >= CAST(:min_effective_date AS date))
  AND b.status = 'COMPLETE' AND b.embedding_key = :embedding_key
  AND b.embedding_dimension = :embedding_dimension
"""


def _ranked_merge(vector_rows: list[dict], lexical_rows: list[dict], limit: int,
                  max_excerpt_chars: int, jurisdiction: str = "NG",
                  sensitive: bool = False) -> tuple[EvidenceItem, ...]:
    ranked: dict[str, tuple[dict, float, set[str]]] = {}
    for method, rows in (("vector", vector_rows), ("lexical", lexical_rows)):
        for position, row in enumerate(rows, 1):
            key = row["chunk_id"]
            score = 1.0 / (60 + position)
            if key in ranked:
                prior, total, methods = ranked[key]
                ranked[key] = (prior, total + score, methods | {method})
            else:
                ranked[key] = (row, score, {method})
    selected = []
    seen_checksum = set()
    per_source: dict[str, int] = {}
    # Candidates are already bounded by retrieval. Applicable local guidance,
    # then trust tier, precedes rank fusion; score is never clinical confidence.
    ordered = sorted(ranked.values(), key=lambda entry: (
        entry[0]["jurisdiction"] != jurisdiction,
        -entry[0]["trust_tier"], -entry[1], entry[0]["chunk_id"]))
    for row, _rank, methods in ordered:
        digest = row["checksum"]
        if digest in seen_checksum or per_source.get(row["source_id"], 0) >= 2:
            continue
        url = _canonical_url(row["canonical_url"])
        freshness = classify(
            version_status="ACTIVE", source_type=row.get("source_type", "GUIDELINE"),
            freshness_class=row.get("freshness_class", "STANDARD"),
            review_interval_days=row.get("review_interval_days", 365),
            update_status=row.get("update_status", "CURRENT"),
            effective_date=row.get("effective_date"),
            publication_date=row.get("publication_date"), sensitive=sensitive,
            issuing_organization=row.get("issuing_organization", ""),
        )
        item = EvidenceItem(
            evidence_id=row["chunk_id"], chunk_id=row["chunk_id"],
            source_id=row["source_id"], document_version_id=row["version_id"],
            title=row["title"], issuing_organization=row["issuing_organization"],
            jurisdiction=row["jurisdiction"], edition=row["edition"],
            publication_date=str(row["publication_date"]) if row["publication_date"] else None,
            effective_date=str(row["effective_date"]) if row["effective_date"] else None,
            section=row["section_title"], page_start=row["page_start"],
            page_end=row["page_end"], anchor=row["anchor"], canonical_url=url,
            trust_tier=row["trust_tier"], indexed_at=str(row["indexed_at"]),
            excerpt=row["excerpt"][:max_excerpt_chars],
            retrieval_methods=tuple(sorted(methods)),
            conflict_group=row.get("conflict_group"),
            conflict_stance=row.get("conflict_stance"),
            freshness_state=freshness.value,
        )
        selected.append(item)
        seen_checksum.add(digest)
        per_source[row["source_id"]] = per_source.get(row["source_id"], 0) + 1
        if len(selected) >= limit:
            break
    return tuple(selected)


def _conflicting(items: tuple[EvidenceItem, ...]) -> bool:
    groups: dict[str, set[str]] = {}
    for item in items:
        if item.conflict_group and item.conflict_stance:
            groups.setdefault(item.conflict_group, set()).add(item.conflict_stance)
    return any(len(stances) > 1 for stances in groups.values())


def _medlineplus_relevant(item: EvidenceItem, concepts: set[str]) -> bool:
    if item.issuing_organization != 'U.S. National Library of Medicine / MedlinePlus':
        return True
    title = set(re.findall(r'[a-z]+', item.title.lower()))
    if 'hay' in title and 'hay' not in concepts:
        return False
    if 'pregnancy' in title and not concepts & {'pregnant', 'pregnancy'}:
        return False
    if 'stones' in title and not concepts & {'stone', 'stones'}:
        return False
    if 'hay' in concepts:
        return {'hay', 'fever'} <= title
    if concepts & {'stone', 'stones'}:
        return 'stones' in title
    if {'foamy', 'urine'} <= concepts:
        return item.title in {'Kidney Tests', 'Urine and Urination'}
    if 'interact' in concepts or 'interaction' in concepts:
        return any(word.startswith('interact') for word in title)
    if 'suicide' in concepts or 'crisis' in concepts:
        return bool(title & {'suicide', 'self', 'harm'})
    if concepts & {'pregnant', 'pregnancy'} and concepts & {'headache', 'swelling'}:
        return 'pregnancy' in title and bool(title & {'pressure', 'health'})
    if 'hypoglycemia' in concepts:
        return 'hypoglycemia' in title
    if 'asthma' in concepts:
        return 'asthma' in title
    if 'migraine' in concepts:
        return 'migraine' in title
    if 'breathing' in concepts:
        return 'breathing' in title
    if 'chest' in concepts:
        return 'chest' in title
    if 'headache' in concepts:
        return 'headache' in title
    if 'fever' in concepts and 'child' not in concepts and 'urinate' not in concepts:
        return 'fever' in title and 'hay' not in title
    if {'child', 'fever'} <= concepts:
        return 'fever' in title
    if 'rash' in concepts and concepts & {'medicine', 'medication', 'drug'}:
        return bool(title & {'rash', 'rashes', 'reactions'})
    if {'blood', 'pressure'} <= concepts or 'hypertension' in concepts:
        if 'low' in concepts:
            return 'pressure' in title and 'low' in title
        return 'pressure' in title and (
            not concepts & {'high', 'hypertension'} or 'low' not in title)
    if 'diabetes' not in concepts and title & {'diabetic', 'diabetes'}:
        return False
    aliases = {'foamy': 'urine', 'urinate': 'urinary', 'diarrhoea': 'diarrhea',
               'antibiotics': 'antibiotics', 'rash': 'rashes', 'child': 'children',
               'pregnant': 'pregnancy'}
    matching = {aliases.get(word, word) for word in concepts}
    return bool(title & matching)


def _without_verified_web(curated: EvidenceBundle, normalized: str,
                          *, checked: bool) -> EvidenceBundle:
    volatile = {'recall', 'withdrawn', 'approval', 'outbreak',
                'current', 'latest', 'recent'}
    if set(normalized.split()) & volatile:
        return replace(curated, status=EvidenceStatus.NONE, items=(),
                       web_checked=checked,
                       failure_category='current_official_evidence_unavailable')
    if topic_sensitive(normalized) and curated.items:
        return replace(curated, status=EvidenceStatus.INSUFFICIENT,
                       web_checked=checked)
    return replace(curated, web_checked=checked)


async def _retrieve_curated(
    db: Session, query: ClinicalEvidenceQuery, *,
    config: KnowledgeConfig | None = None,
    embedding_provider: EmbeddingProvider | None = None,
) -> EvidenceBundle:
    config = config or KnowledgeConfig.from_env()
    if not config.enabled:
        return EvidenceBundle(EvidenceStatus.NONE, failure_category="disabled")
    normalized = query.normalized_text()
    if not normalized:
        return EvidenceBundle(EvidenceStatus.NONE, failure_category="no_deidentified_concepts")
    if {"foamy", "urine"} <= set(normalized.split()):
        normalized += " proteinuria kidney"
    started = time.monotonic()
    try:
        provider = embedding_provider or get_embedding_provider()
        cache_token = None
        if config.cache_enabled:
            try:
                revision, mutated = clinical_cache.library_revision(db)
                if not mutated:
                    cache_token = clinical_cache.cache_key(
                        normalized_query=normalized, jurisdiction=query.jurisdiction,
                        population=query.population, minimum_trust=query.minimum_trust_tier,
                        min_effective_date=str(query.min_effective_date) if query.min_effective_date else None,
                        revision=revision, embedding_key=provider.key,
                        policy_version=POLICY_VERSION,
                        limits=(config.vector_candidates, config.lexical_candidates,
                                config.final_items, config.max_excerpt_chars,
                                config.min_sufficient_items),
                    )
                    cached = clinical_cache.get(cache_token)
                    if cached is not None:
                        logger.info("[KNOWLEDGE] purpose=%s cache=hit final=%d",
                                    query.purpose, len(cached.items))
                        return cached
                logger.info("[KNOWLEDGE] purpose=%s cache=miss", query.purpose)
            except Exception as exc:
                cache_token = None
                logger.warning("[KNOWLEDGE] purpose=%s cache=bypass reason=%s",
                               query.purpose, type(exc).__name__)
        vector = (await provider.embed([normalized], task="RETRIEVAL_QUERY"))[0]
        dimension = validate_vectors([vector], 1)
        params = {
            "minimum_trust": max(1, min(3, query.minimum_trust_tier)),
            "jurisdiction": query.jurisdiction,
            "min_effective_date": query.min_effective_date,
            "embedding_key": provider.key,
            "embedding_dimension": dimension,
        }
        vector_sql = _CANDIDATE_SQL.format(
            score="c.embedding OPERATOR(extensions.<=>) CAST(:vector AS extensions.vector)",
            match="TRUE", direction="ASC",
        )
        lexical_sql = _CANDIDATE_SQL.format(
            score="ts_rank_cd(c.lexical_search_data, websearch_to_tsquery('simple', :query_text))",
            match="c.lexical_search_data @@ websearch_to_tsquery('simple', :query_text)",
            direction="DESC",
        )
        # A retrieval failure must never abort or roll back the request's outer
        # claim/assessment transaction. The nested transaction is a SAVEPOINT.
        db_started = time.monotonic()
        with db.begin_nested():
            eligible_versions = tuple(row["version_id"] for row in db.execute(
                text(_ELIGIBLE_SQL), params).mappings())
            vector_rows = [dict(row) for row in db.execute(text(vector_sql), {
                **params, "vector": "[" + ",".join(str(float(v)) for v in vector) + "]",
                "candidate_limit": config.vector_candidates,
            }).mappings()]
            lexical_rows = [dict(row) for row in db.execute(text(lexical_sql), {
                **params, "query_text": normalized,
                "candidate_limit": config.lexical_candidates,
            }).mappings()]
            stale_only = False
            if not vector_rows and not lexical_rows:
                stale_only = bool(db.execute(text(_STALE_SQL), {
                    "jurisdiction": query.jurisdiction, "query_text": normalized,
                    "min_effective_date": query.min_effective_date,
                }).scalar())
        db_latency_ms = int((time.monotonic() - db_started) * 1000)
        sensitive = topic_sensitive(normalized)
        candidates = _ranked_merge(vector_rows, lexical_rows,
                                   config.vector_candidates + config.lexical_candidates,
                                   config.max_excerpt_chars, query.jurisdiction, sensitive)
        concepts = set(normalized.split())
        items = tuple(item for item in candidates if _medlineplus_relevant(item, concepts))[
            :config.final_items]
        stale_items = bool(items) and all(item.freshness_state == FreshnessState.STALE for item in items)
        if sensitive:
            items = tuple(item for item in items if item.freshness_state != FreshnessState.STALE)
        if not items:
            status = EvidenceStatus.STALE if stale_only or stale_items else EvidenceStatus.NONE
        elif stale_items:
            status = EvidenceStatus.STALE
        elif _conflicting(items):
            status = EvidenceStatus.CONFLICTING
        elif (len(items) < config.min_sufficient_items or
              (len({item.source_id for item in items}) == 1 and
               len({item.section for item in items}) == 1)):
            status = EvidenceStatus.INSUFFICIENT
        else:
            status = EvidenceStatus.SUFFICIENT
        logger.info("[KNOWLEDGE] purpose=%s status=%s vector=%d lexical=%d final=%d "
                    "eligible_versions=%s selected_sources=%s build_ids=%s policy=%s "
                    "db_latency_ms=%d latency_ms=%d",
                    query.purpose, status.value, len(vector_rows), len(lexical_rows),
                    len(items), eligible_versions,
                    tuple(dict.fromkeys(item.source_id for item in items)),
                    tuple(dict.fromkeys(row["build_id"] for row in [*vector_rows, *lexical_rows]
                    if row["build_id"])), POLICY_VERSION, db_latency_ms,
                    int((time.monotonic() - started) * 1000))
        bundle = EvidenceBundle(
            status, items, conflict=status == EvidenceStatus.CONFLICTING,
            eligible_version_ids=eligible_versions,
            index_build_ids=tuple(dict.fromkeys(row["build_id"] for row in
                                                    [*vector_rows, *lexical_rows] if row["build_id"])),
            embedding_key=provider.key, embedding_dimension=dimension,
        )
        if cache_token is not None:
            try:
                clinical_cache.put(cache_token, bundle, ttl_seconds=config.cache_ttl_seconds,
                                   max_entries=config.cache_max_entries)
            except Exception as exc:
                logger.warning("[KNOWLEDGE] purpose=%s cache=store_failed reason=%s",
                               query.purpose, type(exc).__name__)
        return bundle
    except Exception as exc:
        logger.warning("[KNOWLEDGE] purpose=%s status=NONE failure_category=%s",
                       query.purpose, type(exc).__name__)
        return EvidenceBundle(EvidenceStatus.NONE, failure_category=type(exc).__name__)


async def retrieve_evidence(
    db: Session, query: ClinicalEvidenceQuery, *,
    config: KnowledgeConfig | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    web_provider: object | None = None,
    web_client: object | None = None,
) -> EvidenceBundle:
    config = config or KnowledgeConfig.from_env()
    if not config.enabled and not config.web_enabled:
        return EvidenceBundle(EvidenceStatus.NONE, failure_category="disabled")
    normalized = query.normalized_text()
    if not normalized:
        return EvidenceBundle(EvidenceStatus.NONE, failure_category="no_deidentified_concepts")
    curated = (await _retrieve_curated(db, query, config=config,
                                      embedding_provider=embedding_provider)
               if config.enabled else EvidenceBundle(EvidenceStatus.NONE,
                                                     failure_category="curated_disabled"))
    if (not topic_sensitive(normalized) and curated.items and
            any(item.issuing_organization == 'U.S. National Library of Medicine / MedlinePlus'
                for item in curated.items)):
        return curated
    if not config.web_enabled or not (topic_sensitive(normalized) or curated.status in {
            EvidenceStatus.NONE, EvidenceStatus.INSUFFICIENT, EvidenceStatus.STALE}):
        return curated
    from app.services.clinical_web import search_official

    try:
        documents = await asyncio.wait_for(
            search_official(normalized, query.jurisdiction,
                            provider=web_provider, client=web_client),
            timeout=WEB_SEARCH_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.warning("[KNOWLEDGE] purpose=%s web=failed reason=%s",
                       query.purpose, type(exc).__name__)
        return _without_verified_web(curated, normalized, checked=False)
    if not documents:
        logger.info("[KNOWLEDGE] purpose=%s web=no_valid_results", query.purpose)
        return _without_verified_web(curated, normalized, checked=True)

    web_items = []
    current_sensitive = topic_sensitive(normalized)
    for document in documents:
        if current_sensitive and (document.publication_date is None or
                                  not date.today() - timedelta(days=90) <=
                                  document.publication_date <= date.today()):
            logger.info("[KNOWLEDGE] purpose=%s web=rejected_unverified_freshness",
                        query.purpose)
            continue
        digest = hashlib.sha256((document.url + document.digest).encode()).hexdigest()
        source_digest = hashlib.sha256(document.url.encode()).hexdigest()[:24]
        web_items.append(EvidenceItem(
            evidence_id="web:" + digest, chunk_id="web:" + digest,
            source_id="official:" + source_digest,
            document_version_id="web-version:" + document.digest[:24],
            title=document.title, issuing_organization=document.organization,
            jurisdiction=document.jurisdiction, edition="", publication_date=(
                document.publication_date.isoformat() if document.publication_date else None),
            effective_date=None, section=None, page_start=None, page_end=None,
            anchor=None, canonical_url=document.url, trust_tier=2,
            indexed_at=date.today().isoformat(), excerpt=document.excerpt,
            retrieval_methods=("official_web",), origin="OFFICIAL_WEB",
            freshness_state=("AGING" if document.publication_date is None else "CURRENT"),
        ))
    if not web_items:
        return _without_verified_web(curated, normalized, checked=True)
    web_items.sort(key=lambda item: item.jurisdiction != query.jurisdiction)
    retained = []
    for old in curated.items:
        if old.freshness_state == FreshnessState.STALE:
            continue
        replacement = next((newer for newer in web_items if
            newer.issuing_organization == old.issuing_organization and
            newer.publication_date and old.publication_date and
            newer.publication_date > old.publication_date
        ), None)
        if replacement is None:
            retained.append(old)
        else:
            logger.info("[KNOWLEDGE] purpose=%s newer_official_replacement source_id=%s",
                        query.purpose, old.source_id)
            try:
                with db.begin_nested():
                    db.execute(text("""
                        UPDATE clinical_sources SET update_status = 'UPDATE_AVAILABLE',
                          update_signal_url = :url,
                          update_signal_reason = 'NEWER_OFFICIAL_RESULT'
                        WHERE source_id = CAST(:source_id AS uuid)
                          AND update_status <> 'UPDATE_AVAILABLE'
                    """), {"url": replacement.canonical_url, "source_id": old.source_id})
            except Exception as exc:
                logger.warning("[KNOWLEDGE] review_signal=failed reason=%s",
                               type(exc).__name__)
    ordered = ([*web_items, *retained] if topic_sensitive(normalized)
               else [*retained, *web_items])
    items = tuple(ordered[:config.final_items])
    status = (EvidenceStatus.SUFFICIENT if len(items) >= config.min_sufficient_items and
              len({item.source_id for item in items}) >= 2 else EvidenceStatus.INSUFFICIENT)
    logger.info("[KNOWLEDGE] purpose=%s web=accepted candidates=%d final=%d",
                query.purpose, len(web_items), len(items))
    return replace(curated, status=status, items=items, web_checked=True,
                   failure_category=None)


def validate_evidence_references(ids: list[str], bundle: EvidenceBundle,
                                 *, claimed_urls: list[str] | None = None) -> tuple[EvidenceItem, ...]:
    if not isinstance(ids, list) or any(not isinstance(value, str) for value in ids):
        raise ValueError("invalid evidence references")
    if len(ids) != len(set(ids)) or any(value not in bundle.ids for value in ids):
        raise ValueError("unknown evidence reference")
    if claimed_urls:
        raise ValueError("provider-supplied URLs are forbidden")
    return tuple(item for item in bundle.items if item.evidence_id in ids)
