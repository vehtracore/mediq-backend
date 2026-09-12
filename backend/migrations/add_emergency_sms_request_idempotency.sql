-- Payload-free Emergency NOK SMS idempotency ledger.
-- It stores no phone number, coordinates, address, or SMS body.

CREATE TABLE IF NOT EXISTS emergency_sms_requests (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    request_id VARCHAR(128) NOT NULL,
    status     VARCHAR(32) NOT NULL DEFAULT 'reserved',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_emergency_sms_requests_user_request
        UNIQUE (user_id, request_id)
);

CREATE INDEX IF NOT EXISTS ix_emergency_sms_requests_user_id
ON emergency_sms_requests (user_id);
