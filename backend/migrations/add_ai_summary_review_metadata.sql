-- Migration: add server-controlled provenance and review metadata to saved
-- AI Health Vault summaries.
--
-- Existing summaries are backfilled as AI-generated and not reviewed. No
-- doctor review is inferred from historical data.

ALTER TABLE ai_chat_summaries
ADD COLUMN IF NOT EXISTS source VARCHAR NOT NULL DEFAULT 'ai_generated';

ALTER TABLE ai_chat_summaries
ADD COLUMN IF NOT EXISTS doctor_review_status VARCHAR NOT NULL DEFAULT 'not_reviewed';

ALTER TABLE ai_chat_summaries
ADD COLUMN IF NOT EXISTS reviewed_by_doctor_id INTEGER NULL;

ALTER TABLE ai_chat_summaries
ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_ai_chat_summaries_reviewed_by_doctor'
    ) THEN
        ALTER TABLE ai_chat_summaries
        ADD CONSTRAINT fk_ai_chat_summaries_reviewed_by_doctor
        FOREIGN KEY (reviewed_by_doctor_id)
        REFERENCES doctors(id)
        ON DELETE SET NULL;
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS ix_ai_chat_summaries_reviewed_by_doctor_id
ON ai_chat_summaries (reviewed_by_doctor_id);
