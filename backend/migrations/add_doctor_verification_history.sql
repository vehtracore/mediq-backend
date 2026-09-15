-- MDQ+ doctor professional verification evidence history.
-- Apply only after: add_private_sensitive_media_identifiers.sql
-- This migration is additive and must be applied explicitly in staging.

CREATE TABLE IF NOT EXISTS doctor_verification_submissions (
    id UUID PRIMARY KEY,
    doctor_id INTEGER NOT NULL REFERENCES doctors(id) ON DELETE RESTRICT,
    submission_type VARCHAR(24) NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'pending',
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ NULL,
    reviewed_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE RESTRICT,
    rejection_reason VARCHAR(1000) NULL,
    supersedes_submission_id UUID NULL
        REFERENCES doctor_verification_submissions(id) ON DELETE RESTRICT,
    license_number_snapshot VARCHAR NOT NULL,
    specialty_snapshot VARCHAR NOT NULL,
    CONSTRAINT ck_doctor_verification_submission_type CHECK (
        submission_type IN ('initial', 'reapplication', 'reverification', 'legacy_import')
    ),
    CONSTRAINT ck_doctor_verification_submission_status CHECK (
        status IN ('pending', 'approved', 'rejected', 'historical_unknown')
    ),
    CONSTRAINT ck_doctor_verification_review_fields CHECK (
        (status = 'pending' AND reviewed_at IS NULL AND reviewed_by_user_id IS NULL
            AND rejection_reason IS NULL)
        OR (status = 'approved' AND reviewed_at IS NOT NULL
            AND reviewed_by_user_id IS NOT NULL AND rejection_reason IS NULL)
        OR (status = 'rejected' AND reviewed_at IS NOT NULL
            AND reviewed_by_user_id IS NOT NULL AND rejection_reason IS NOT NULL)
        OR (status = 'historical_unknown' AND reviewed_at IS NULL
            AND reviewed_by_user_id IS NULL AND rejection_reason IS NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_doctor_verification_one_pending
    ON doctor_verification_submissions (doctor_id)
    WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS ix_doctor_verification_doctor_submitted
    ON doctor_verification_submissions (doctor_id, submitted_at);
CREATE INDEX IF NOT EXISTS ix_doctor_verification_status
    ON doctor_verification_submissions (status);

CREATE TABLE IF NOT EXISTS doctor_verification_documents (
    id UUID PRIMARY KEY,
    submission_id UUID NOT NULL
        REFERENCES doctor_verification_submissions(id) ON DELETE RESTRICT,
    document_kind VARCHAR(32) NOT NULL,
    cloudinary_public_id VARCHAR NOT NULL,
    resource_type VARCHAR(16) NOT NULL,
    format VARCHAR(16) NOT NULL,
    delivery_type VARCHAR(16) NOT NULL DEFAULT 'authenticated',
    sha256_digest VARCHAR(64) NOT NULL,
    size_bytes BIGINT NOT NULL,
    mime_type VARCHAR(64) NOT NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_verification_document_kind_per_submission
        UNIQUE (submission_id, document_kind),
    CONSTRAINT ck_doctor_verification_document_kind CHECK (
        document_kind IN ('mdcn_license', 'indemnity_certificate')
    ),
    CONSTRAINT ck_doctor_verification_document_delivery CHECK (
        delivery_type = 'authenticated'
    ),
    CONSTRAINT ck_doctor_verification_document_digest CHECK (
        sha256_digest ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_doctor_verification_document_size CHECK (size_bytes > 0)
);

CREATE INDEX IF NOT EXISTS ix_doctor_verification_documents_submission
    ON doctor_verification_documents (submission_id);

ALTER TABLE doctors
    ADD COLUMN IF NOT EXISTS current_verification_submission_id UUID NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_doctors_current_verification_submission'
    ) THEN
        ALTER TABLE doctors
            ADD CONSTRAINT fk_doctors_current_verification_submission
            FOREIGN KEY (current_verification_submission_id)
            REFERENCES doctor_verification_submissions(id)
            ON DELETE RESTRICT;
    END IF;
END $$;

CREATE OR REPLACE FUNCTION mdq_prevent_verification_document_mutation()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'committed doctor verification documents are immutable';
END;
$$;

DROP TRIGGER IF EXISTS trg_verification_documents_immutable
    ON doctor_verification_documents;
CREATE TRIGGER trg_verification_documents_immutable
    BEFORE UPDATE OR DELETE ON doctor_verification_documents
    FOR EACH ROW EXECUTE FUNCTION mdq_prevent_verification_document_mutation();

CREATE OR REPLACE FUNCTION mdq_guard_verification_submission_update()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.doctor_id IS DISTINCT FROM NEW.doctor_id
        OR OLD.submission_type IS DISTINCT FROM NEW.submission_type
        OR OLD.submitted_at IS DISTINCT FROM NEW.submitted_at
        OR OLD.supersedes_submission_id IS DISTINCT FROM NEW.supersedes_submission_id
        OR OLD.license_number_snapshot IS DISTINCT FROM NEW.license_number_snapshot
        OR OLD.specialty_snapshot IS DISTINCT FROM NEW.specialty_snapshot THEN
        RAISE EXCEPTION 'committed verification submission evidence is immutable';
    END IF;
    IF OLD.status <> 'pending' OR NEW.status NOT IN ('approved', 'rejected') THEN
        RAISE EXCEPTION 'invalid verification submission status transition';
    END IF;
    IF (
        SELECT COUNT(DISTINCT document_kind)
        FROM doctor_verification_documents
        WHERE submission_id = OLD.id
          AND document_kind IN ('mdcn_license', 'indemnity_certificate')
    ) <> 2 THEN
        RAISE EXCEPTION 'verification submission is missing required evidence';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_verification_submission_guard
    ON doctor_verification_submissions;
CREATE TRIGGER trg_verification_submission_guard
    BEFORE UPDATE ON doctor_verification_submissions
    FOR EACH ROW EXECUTE FUNCTION mdq_guard_verification_submission_update();

CREATE UNIQUE INDEX IF NOT EXISTS uq_doctors_current_verification_submission
    ON doctors (current_verification_submission_id)
    WHERE current_verification_submission_id IS NOT NULL;

CREATE OR REPLACE FUNCTION mdq_guard_doctor_current_verification()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.current_verification_submission_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM doctor_verification_submissions submission
        WHERE submission.id = NEW.current_verification_submission_id
          AND submission.doctor_id = NEW.id
          AND submission.status = 'approved'
    ) THEN
        RAISE EXCEPTION 'current verification submission must be this doctor''s approved evidence';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_doctor_current_verification_guard ON doctors;
CREATE TRIGGER trg_doctor_current_verification_guard
    BEFORE INSERT OR UPDATE OF current_verification_submission_id ON doctors
    FOR EACH ROW EXECUTE FUNCTION mdq_guard_doctor_current_verification();

-- No legacy history is backfilled here. See the controlled transition plan.
