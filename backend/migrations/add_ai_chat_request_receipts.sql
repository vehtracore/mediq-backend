-- Apply before deploying Wave 1 chat operation code.
CREATE TABLE IF NOT EXISTS ai_chat_request_receipts (
    id BIGSERIAL PRIMARY KEY,
    patient_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    request_digest VARCHAR(64) NOT NULL,
    request_fingerprint VARCHAR(64) NOT NULL,
    response_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_ai_chat_receipt_patient_request UNIQUE (patient_id, request_digest)
);
CREATE INDEX IF NOT EXISTS ix_ai_chat_request_receipts_patient_id
    ON ai_chat_request_receipts(patient_id);
CREATE INDEX IF NOT EXISTS ix_ai_chat_request_receipts_expires_at
    ON ai_chat_request_receipts(expires_at);
