-- Wave 5. Apply once after add_clinical_knowledge.sql. No corpus is activated.
ALTER TABLE clinical_sources
    ADD COLUMN freshness_class VARCHAR(16) NOT NULL DEFAULT 'STANDARD'
        CHECK (freshness_class IN ('STABLE', 'STANDARD', 'SENSITIVE')),
    ADD COLUMN review_interval_days INTEGER NOT NULL DEFAULT 365
        CHECK (review_interval_days BETWEEN 1 AND 3650),
    ADD COLUMN update_check_frequency_hours INTEGER NOT NULL DEFAULT 720
        CHECK (update_check_frequency_hours BETWEEN 1 AND 8760),
    ADD COLUMN update_status VARCHAR(24) NOT NULL DEFAULT 'UNCHECKED'
        CHECK (update_status IN ('UNCHECKED', 'BASELINED', 'CURRENT',
                                'UPDATE_AVAILABLE', 'CHECK_FAILED')),
    ADD COLUMN last_checked_at TIMESTAMPTZ,
    ADD COLUMN last_seen_etag TEXT,
    ADD COLUMN last_seen_modified TEXT,
    ADD COLUMN last_seen_sha256 CHAR(64),
    ADD COLUMN update_signal_url TEXT,
    ADD COLUMN update_signal_reason VARCHAR(40);

CREATE INDEX ix_clinical_sources_update_due
    ON clinical_sources (last_checked_at, source_id)
    WHERE approval_status = 'APPROVED' AND canonical_url IS NOT NULL;

CREATE TABLE clinical_library_state (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    revision BIGINT NOT NULL DEFAULT 1 CHECK (revision > 0),
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO clinical_library_state (singleton) VALUES (TRUE);
ALTER TABLE clinical_library_state ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION clinical_bump_library_revision()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE clinical_library_state
    SET revision = revision + 1, changed_at = clock_timestamp()
    WHERE singleton = TRUE;
    PERFORM set_config('mdq.clinical_library_mutated', 'true', true);
    RETURN NULL;
END $$;

CREATE TRIGGER clinical_source_revision
    AFTER INSERT OR UPDATE OR DELETE ON clinical_sources
    FOR EACH STATEMENT EXECUTE FUNCTION clinical_bump_library_revision();
CREATE TRIGGER clinical_version_revision
    AFTER INSERT OR UPDATE OR DELETE ON clinical_document_versions
    FOR EACH STATEMENT EXECUTE FUNCTION clinical_bump_library_revision();
CREATE TRIGGER clinical_chunk_revision
    AFTER INSERT OR UPDATE OR DELETE ON clinical_evidence_chunks
    FOR EACH STATEMENT EXECUTE FUNCTION clinical_bump_library_revision();
CREATE TRIGGER clinical_index_revision
    AFTER INSERT OR UPDATE OR DELETE ON clinical_index_builds
    FOR EACH STATEMENT EXECUTE FUNCTION clinical_bump_library_revision();
