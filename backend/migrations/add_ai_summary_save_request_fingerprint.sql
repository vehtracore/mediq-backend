BEGIN;

ALTER TABLE ai_chat_summaries
ADD COLUMN IF NOT EXISTS save_request_fingerprint VARCHAR(64) NULL;

CREATE TABLE IF NOT EXISTS ai_summary_save_idempotency (
    id SERIAL PRIMARY KEY,
    patient_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    request_key_digest VARCHAR(64) NOT NULL,
    request_fingerprint VARCHAR(64) NOT NULL,
    summary_id UUID NOT NULL REFERENCES ai_chat_summaries(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_ai_summary_save_idempotency_patient_key
        UNIQUE (patient_id, request_key_digest)
);

CREATE INDEX IF NOT EXISTS ix_ai_summary_save_idempotency_patient_id
ON ai_summary_save_idempotency (patient_id);

CREATE INDEX IF NOT EXISTS ix_ai_summary_save_idempotency_summary_id
ON ai_summary_save_idempotency (summary_id);

COMMIT;
