-- Wave 4. Apply after the Wave 1-3 migrations, before enabling knowledge retrieval.
-- Supabase reports pgvector 0.8.0 available on 2026-09-26; it is not yet installed.
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;

CREATE TABLE IF NOT EXISTS clinical_sources (
    source_id UUID PRIMARY KEY,
    canonical_title TEXT NOT NULL,
    issuing_organization TEXT NOT NULL,
    jurisdiction VARCHAR(32) NOT NULL,
    source_type VARCHAR(32) NOT NULL CHECK (source_type IN (
        'GUIDELINE', 'PUBLIC_HEALTH', 'CLINICAL_REFERENCE')),
    canonical_url TEXT CHECK (canonical_url IS NULL OR canonical_url ~ '^https://[^[:space:]]+$'),
    trust_tier SMALLINT NOT NULL CHECK (trust_tier BETWEEN 1 AND 3),
    category VARCHAR(16) NOT NULL DEFAULT 'CURATED' CHECK (category = 'CURATED'),
    approval_status VARCHAR(16) NOT NULL CHECK (approval_status IN ('PENDING', 'APPROVED')),
    license_status VARCHAR(16) NOT NULL CHECK (license_status IN ('PENDING', 'APPROVED')),
    license_note TEXT NOT NULL,
    approved_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT clinical_source_approval_complete CHECK (
        approval_status <> 'APPROVED' OR
        (license_status = 'APPROVED' AND approved_by IS NOT NULL AND length(btrim(approved_by)) > 0)
    )
);

CREATE TABLE IF NOT EXISTS clinical_index_builds (
    build_id UUID PRIMARY KEY,
    embedding_key VARCHAR(160) NOT NULL,
    embedding_dimension INTEGER NOT NULL CHECK (embedding_dimension BETWEEN 1 AND 16000),
    extraction_version VARCHAR(32) NOT NULL,
    retrieval_policy_version VARCHAR(32) NOT NULL,
    status VARCHAR(16) NOT NULL CHECK (status IN ('BUILDING', 'COMPLETE', 'FAILED')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS clinical_document_versions (
    version_id UUID PRIMARY KEY,
    source_id UUID NOT NULL REFERENCES clinical_sources(source_id),
    edition_label TEXT NOT NULL,
    publication_date DATE,
    effective_date DATE,
    retrieved_at TIMESTAMPTZ NOT NULL,
    checksum CHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL CHECK (status IN ('DRAFT', 'ACTIVE', 'SUPERSEDED', 'RETIRED', 'WITHDRAWN')),
    original_reference TEXT NOT NULL,
    extraction_version VARCHAR(32) NOT NULL,
    index_build_id UUID REFERENCES clinical_index_builds(build_id),
    chunk_count INTEGER NOT NULL DEFAULT 0 CHECK (chunk_count >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    activated_at TIMESTAMPTZ,
    UNIQUE (source_id, edition_label),
    CONSTRAINT clinical_version_checksum_format CHECK (checksum ~ '^[a-f0-9]{64}$')
);
CREATE INDEX IF NOT EXISTS ix_clinical_versions_active
    ON clinical_document_versions (source_id, effective_date DESC)
    WHERE status = 'ACTIVE';
CREATE UNIQUE INDEX IF NOT EXISTS uq_clinical_source_active_version
    ON clinical_document_versions (source_id) WHERE status = 'ACTIVE';

CREATE TABLE IF NOT EXISTS clinical_evidence_chunks (
    chunk_id UUID PRIMARY KEY,
    document_version_id UUID NOT NULL REFERENCES clinical_document_versions(version_id),
    section_title TEXT,
    page_start INTEGER CHECK (page_start IS NULL OR page_start > 0),
    page_end INTEGER CHECK (page_end IS NULL OR page_end >= page_start),
    anchor TEXT,
    conflict_group TEXT,
    conflict_stance TEXT,
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    text TEXT NOT NULL,
    lexical_search_data TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED,
    embedding extensions.vector NOT NULL,
    checksum CHAR(64) NOT NULL CHECK (checksum ~ '^[a-f0-9]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_version_id, chunk_index),
    CONSTRAINT clinical_conflict_pair CHECK (
        (conflict_group IS NULL AND conflict_stance IS NULL) OR
        (conflict_group IS NOT NULL AND conflict_stance IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS ix_clinical_chunks_lexical
    ON clinical_evidence_chunks USING GIN (lexical_search_data);
CREATE INDEX IF NOT EXISTS ix_clinical_chunks_version
    ON clinical_evidence_chunks (document_version_id);

-- Published content cannot change; status transitions retain the audit trail.
CREATE OR REPLACE FUNCTION clinical_prevent_published_version_edit()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status <> 'DRAFT' AND NEW.status NOT IN ('SUPERSEDED', 'RETIRED', 'WITHDRAWN') THEN
        RAISE EXCEPTION 'published clinical version cannot be reactivated';
    END IF;
    IF OLD.status IN ('SUPERSEDED', 'RETIRED', 'WITHDRAWN') AND NEW.status IS DISTINCT FROM OLD.status THEN
        RAISE EXCEPTION 'terminal clinical version status is immutable';
    END IF;
    IF OLD.status <> 'DRAFT' AND (
        NEW.source_id IS DISTINCT FROM OLD.source_id OR
        NEW.edition_label IS DISTINCT FROM OLD.edition_label OR
        NEW.publication_date IS DISTINCT FROM OLD.publication_date OR
        NEW.effective_date IS DISTINCT FROM OLD.effective_date OR
        NEW.retrieved_at IS DISTINCT FROM OLD.retrieved_at OR
        NEW.checksum IS DISTINCT FROM OLD.checksum OR
        NEW.original_reference IS DISTINCT FROM OLD.original_reference OR
        NEW.extraction_version IS DISTINCT FROM OLD.extraction_version OR
        NEW.index_build_id IS DISTINCT FROM OLD.index_build_id OR
        NEW.chunk_count IS DISTINCT FROM OLD.chunk_count
    ) THEN
        RAISE EXCEPTION 'published clinical document versions are immutable';
    END IF;
    IF NEW.index_build_id IS DISTINCT FROM OLD.index_build_id AND EXISTS (
        SELECT 1 FROM clinical_evidence_chunks WHERE document_version_id = OLD.version_id
    ) THEN
        RAISE EXCEPTION 'index build cannot change after chunks are stored';
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS clinical_version_immutable ON clinical_document_versions;
CREATE TRIGGER clinical_version_immutable BEFORE UPDATE ON clinical_document_versions
    FOR EACH ROW EXECUTE FUNCTION clinical_prevent_published_version_edit();

CREATE OR REPLACE FUNCTION clinical_prevent_index_build_dimension_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.embedding_key IS DISTINCT FROM OLD.embedding_key OR
        NEW.embedding_dimension IS DISTINCT FROM OLD.embedding_dimension) AND EXISTS (
        SELECT 1 FROM clinical_document_versions WHERE index_build_id = OLD.build_id
    ) THEN
        RAISE EXCEPTION 'referenced clinical index build embedding contract is immutable';
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS clinical_index_build_contract_immutable ON clinical_index_builds;
CREATE TRIGGER clinical_index_build_contract_immutable BEFORE UPDATE ON clinical_index_builds
    FOR EACH ROW EXECUTE FUNCTION clinical_prevent_index_build_dimension_change();

CREATE OR REPLACE FUNCTION clinical_prevent_published_chunk_edit()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent_status TEXT;
DECLARE expected_dimension INTEGER;
BEGIN
    SELECT status INTO parent_status FROM clinical_document_versions
    WHERE version_id = CASE WHEN TG_OP = 'DELETE' THEN OLD.document_version_id
                            ELSE NEW.document_version_id END;
    IF parent_status <> 'DRAFT' THEN
        RAISE EXCEPTION 'published clinical evidence chunks are immutable';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    SELECT b.embedding_dimension INTO expected_dimension
    FROM clinical_document_versions v
    JOIN clinical_index_builds b ON b.build_id = v.index_build_id
    WHERE v.version_id = NEW.document_version_id;
    IF expected_dimension IS NULL OR
       extensions.vector_dims(NEW.embedding) <> expected_dimension THEN
        RAISE EXCEPTION 'clinical chunk embedding dimension differs from index build';
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS clinical_chunk_immutable ON clinical_evidence_chunks;
CREATE TRIGGER clinical_chunk_immutable BEFORE INSERT OR UPDATE OR DELETE ON clinical_evidence_chunks
    FOR EACH ROW EXECUTE FUNCTION clinical_prevent_published_chunk_edit();

CREATE OR REPLACE FUNCTION clinical_prevent_published_source_identity_edit()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM clinical_document_versions
               WHERE source_id = OLD.source_id AND status <> 'DRAFT') AND (
        NEW.canonical_title IS DISTINCT FROM OLD.canonical_title OR
        NEW.issuing_organization IS DISTINCT FROM OLD.issuing_organization OR
        NEW.jurisdiction IS DISTINCT FROM OLD.jurisdiction OR
        NEW.canonical_url IS DISTINCT FROM OLD.canonical_url OR
        NEW.trust_tier IS DISTINCT FROM OLD.trust_tier
    ) THEN
        RAISE EXCEPTION 'published clinical source identity is immutable';
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS clinical_source_identity_immutable ON clinical_sources;
CREATE TRIGGER clinical_source_identity_immutable BEFORE UPDATE ON clinical_sources
    FOR EACH ROW EXECUTE FUNCTION clinical_prevent_published_source_identity_edit();

-- These are server-owned tables, never a Supabase client data surface.
ALTER TABLE clinical_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE clinical_index_builds ENABLE ROW LEVEL SECURITY;
ALTER TABLE clinical_document_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE clinical_evidence_chunks ENABLE ROW LEVEL SECURITY;
