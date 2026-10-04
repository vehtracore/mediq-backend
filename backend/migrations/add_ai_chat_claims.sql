-- Apply after add_ai_chat_request_receipts.sql and before deploying DB-backed claims.
CREATE TABLE IF NOT EXISTS ai_chat_claims (
    patient_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    request_digest VARCHAR(64) NOT NULL,
    request_fingerprint VARCHAR(64) NOT NULL,
    owner VARCHAR(36) NOT NULL,
    lease_expires_at TIMESTAMPTZ NOT NULL
);
