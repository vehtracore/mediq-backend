"""Operator-only curated document ingestion. No patient upload path imports this module."""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from uuid import uuid4

from pypdf import PdfReader
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.clinical_embedding import EmbeddingProvider, validate_vectors
from app.services.clinical_knowledge import POLICY_VERSION, _canonical_url

EXTRACTION_VERSION = "paragraph-1"
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
MAX_CHUNK_CHARS = 1400


@dataclass(frozen=True)
class SourceRegistration:
    title: str
    organization: str
    jurisdiction: str
    source_type: str
    canonical_url: str | None
    trust_tier: int
    license_note: str
    approved_by: str
    freshness_class: str = "STANDARD"
    review_interval_days: int = 365
    update_check_frequency_hours: int = 720


@dataclass(frozen=True)
class ExtractedChunk:
    text: str
    section: str | None
    page: int | None
    anchor: str


def register_source(db: Session, source: SourceRegistration) -> str:
    if not all((source.title.strip(), source.organization.strip(),
                source.jurisdiction.strip(), source.source_type.strip(),
                source.license_note.strip(), source.approved_by.strip())):
        raise ValueError("source approval and licensing metadata are required")
    if source.canonical_url and _canonical_url(source.canonical_url) != source.canonical_url:
        raise ValueError("canonical HTTPS source URL required")
    if source.trust_tier not in (1, 2, 3):
        raise ValueError("invalid trust tier")
    if source.source_type.upper() not in {"GUIDELINE", "PUBLIC_HEALTH", "CLINICAL_REFERENCE"}:
        raise ValueError("patient or unreviewed documents cannot be curated sources")
    if (source.freshness_class not in {"STABLE", "STANDARD", "SENSITIVE"} or
            not 1 <= source.review_interval_days <= 3650 or
            not 1 <= source.update_check_frequency_hours <= 8760):
        raise ValueError("invalid clinical source freshness policy")
    source_id = str(uuid4())
    db.execute(text("""
        INSERT INTO clinical_sources (source_id, canonical_title, issuing_organization,
          jurisdiction, source_type, canonical_url, trust_tier, category,
          approval_status, license_status, license_note, approved_by,
          freshness_class, review_interval_days, update_check_frequency_hours)
        VALUES (:id, :title, :organization, :jurisdiction, :type, :url, :tier,
          'CURATED', 'APPROVED', 'APPROVED', :license_note, :approved_by,
          :freshness_class, :review_interval_days, :update_check_frequency_hours)
    """), dict(id=source_id, title=source.title.strip(), organization=source.organization.strip(),
               jurisdiction=source.jurisdiction.strip().upper(), type=source.source_type.strip().upper(),
               url=source.canonical_url, tier=source.trust_tier,
               license_note=source.license_note.strip(), approved_by=source.approved_by.strip(),
               freshness_class=source.freshness_class,
               review_interval_days=source.review_interval_days,
               update_check_frequency_hours=source.update_check_frequency_hours))
    return source_id


def extract_document(data: bytes, filename: str) -> list[ExtractedChunk]:
    if not data or len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError("document size outside allowed range")
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise ValueError("invalid PDF signature")
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted or len(reader.pages) > 500:
            raise ValueError("encrypted or oversized PDF")
        pages = [(index + 1, page.extract_text() or "")
                 for index, page in enumerate(reader.pages)]
    elif suffix in (".txt", ".md"):
        pages = [(None, data.decode("utf-8", errors="strict"))]
    else:
        raise ValueError("only PDF, UTF-8 text, and Markdown are supported")
    chunks: list[ExtractedChunk] = []
    for page, raw in pages:
        section: str | None = None
        paragraphs = re.split(r"\n\s*\n", raw.replace("\r\n", "\n"))
        for paragraph in paragraphs:
            lines = [" ".join(line.split()) for line in paragraph.splitlines() if line.strip()]
            if not lines:
                continue
            first = lines[0]
            if (first.startswith("#") or
                    (len(first) < 100 and first.endswith(":") and len(lines) == 1)):
                section = first.lstrip("# ").rstrip(":")[:200]
                continue
            body = "\n".join(lines)
            while len(body) > MAX_CHUNK_CHARS:
                boundary = max(body.rfind(". ", 0, MAX_CHUNK_CHARS),
                               body.rfind("\n", 0, MAX_CHUNK_CHARS))
                if boundary < MAX_CHUNK_CHARS // 2:
                    boundary = MAX_CHUNK_CHARS
                piece, body = body[:boundary].strip(), body[boundary:].strip()
                if piece:
                    chunks.append(ExtractedChunk(piece, section, page,
                                                  f"p{page or 0}-c{len(chunks)}"))
            if body:
                chunks.append(ExtractedChunk(body, section, page,
                                              f"p{page or 0}-c{len(chunks)}"))
    if not chunks:
        raise ValueError("no extractable clinical text")
    return chunks


async def ingest_version(
    db: Session, *, source_id: str, edition: str, publication_date: date | None,
    effective_date: date | None, data: bytes, filename: str,
    embedding_provider: EmbeddingProvider, conflict_group: str | None = None,
    conflict_stance: str | None = None,
) -> str:
    if bool(conflict_group) != bool(conflict_stance):
        raise ValueError("conflict group and stance must be supplied together")
    if not edition.strip() or not Path(filename).name == filename:
        raise ValueError("edition and plain filename required")
    source = db.execute(text("""
        SELECT source_id FROM clinical_sources WHERE source_id = :id
          AND category = 'CURATED' AND approval_status = 'APPROVED'
          AND license_status = 'APPROVED'
    """), {"id": source_id}).first()
    if source is None:
        raise ValueError("source is not approved for curated ingestion")
    checksum = hashlib.sha256(data).hexdigest()
    existing = db.execute(text("""
        SELECT version_id::text, checksum FROM clinical_document_versions
        WHERE source_id = :source_id AND edition_label = :edition
    """), {"source_id": source_id, "edition": edition}).first()
    if existing:
        if existing.checksum != checksum:
            raise ValueError("edition changed: register a new edition label")
        return existing.version_id
    chunks = extract_document(data, filename)
    vectors = await embedding_provider.embed([chunk.text for chunk in chunks],
                                             task="RETRIEVAL_DOCUMENT")
    dimension = validate_vectors(vectors, len(chunks))
    version_id, build_id = str(uuid4()), str(uuid4())
    db.execute(text("""
        INSERT INTO clinical_index_builds (build_id, embedding_key, embedding_dimension,
          extraction_version, retrieval_policy_version, status)
        VALUES (:id, :key, :dimension, :extraction, :policy, 'BUILDING')
    """), dict(id=build_id, key=embedding_provider.key, dimension=dimension,
               extraction=EXTRACTION_VERSION, policy=POLICY_VERSION))
    db.execute(text("""
        INSERT INTO clinical_document_versions (version_id, source_id, edition_label,
          publication_date, effective_date, retrieved_at, checksum, status,
          original_reference, extraction_version, index_build_id, chunk_count)
        VALUES (:id, :source_id, :edition, :published, :effective, now(), :checksum,
          'DRAFT', :filename, :extraction, :build_id, :chunk_count)
    """), dict(id=version_id, source_id=source_id, edition=edition.strip(),
               published=publication_date, effective=effective_date, checksum=checksum,
               filename=filename, extraction=EXTRACTION_VERSION,
               build_id=build_id, chunk_count=len(chunks)))
    for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
        db.execute(text("""
            INSERT INTO clinical_evidence_chunks (chunk_id, document_version_id,
              section_title, page_start, page_end, anchor, conflict_group,
              conflict_stance, chunk_index, text, embedding, checksum)
            VALUES (:id, :version_id, :section, :page, :page, :anchor,
              :conflict_group, :conflict_stance, :index, :body,
              CAST(:vector AS extensions.vector), :checksum)
        """), dict(id=str(uuid4()), version_id=version_id, section=chunk.section,
                   page=chunk.page, anchor=chunk.anchor, conflict_group=conflict_group,
                   conflict_stance=conflict_stance, index=index, body=chunk.text,
                   vector="[" + ",".join(str(float(v)) for v in vector) + "]",
                   checksum=hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()))
    db.execute(text("""UPDATE clinical_index_builds SET status = 'COMPLETE',
      completed_at = now() WHERE build_id = :id"""), {"id": build_id})
    return version_id


def activate_version(db: Session, version_id: str) -> None:
    row = db.execute(text("""
        SELECT v.source_id, v.status, v.chunk_count, b.status AS build_status,
          (SELECT count(*) FROM clinical_evidence_chunks c WHERE c.document_version_id = v.version_id) AS actual_chunks
        FROM clinical_document_versions v JOIN clinical_index_builds b ON b.build_id = v.index_build_id
        JOIN clinical_sources s ON s.source_id = v.source_id
        WHERE v.version_id = :id AND s.category = 'CURATED'
          AND s.approval_status = 'APPROVED' AND s.license_status = 'APPROVED'
        FOR UPDATE OF v
    """), {"id": version_id}).first()
    if row is None or row.status != "DRAFT" or row.build_status != "COMPLETE" or row.chunk_count == 0 or row.chunk_count != row.actual_chunks:
        raise ValueError("only fully indexed draft versions may be activated")
    db.execute(text("SELECT source_id FROM clinical_sources WHERE source_id = :id FOR UPDATE"),
               {"id": row.source_id})
    db.execute(text("""UPDATE clinical_document_versions SET status = 'SUPERSEDED'
      WHERE source_id = :source_id AND status = 'ACTIVE'"""), {"source_id": row.source_id})
    db.execute(text("""UPDATE clinical_document_versions SET status = 'ACTIVE',
      activated_at = now() WHERE version_id = :id"""), {"id": version_id})


def close_version(db: Session, version_id: str, status: str) -> None:
    if status not in {"RETIRED", "WITHDRAWN"}:
        raise ValueError("invalid closure status")
    changed = db.execute(text("""UPDATE clinical_document_versions SET status = :status
      WHERE version_id = :id AND status = 'ACTIVE'"""),
                         {"id": version_id, "status": status}).rowcount
    if changed != 1:
        raise ValueError("only an active version can be closed")
