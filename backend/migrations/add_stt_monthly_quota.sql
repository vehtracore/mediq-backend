-- Separate UTC calendar-month allowance for successful voice transcription.
-- This migration is deployment-only and must not be executed from application
-- startup. Existing users lazily begin a fresh month on their next STT attempt.

ALTER TABLE users
ADD COLUMN IF NOT EXISTS monthly_stt_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE users
ADD COLUMN IF NOT EXISTS last_stt_month_reset DATE NULL;

CREATE TABLE IF NOT EXISTS stt_usage_reservations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    request_digest VARCHAR(64) NOT NULL,
    month_start DATE NOT NULL,
    status VARCHAR(16) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    finalized_at TIMESTAMP WITHOUT TIME ZONE NULL,
    CONSTRAINT uq_stt_usage_reservation_user_request
        UNIQUE (user_id, request_digest),
    CONSTRAINT ck_stt_usage_reservation_status
        CHECK (status IN ('reserved', 'consumed', 'released'))
);

CREATE INDEX IF NOT EXISTS ix_stt_usage_reservations_user_id
ON stt_usage_reservations (user_id);

CREATE INDEX IF NOT EXISTS ix_stt_usage_reservations_status
ON stt_usage_reservations (status);

CREATE INDEX IF NOT EXISTS ix_stt_usage_reservations_expires_at
ON stt_usage_reservations (expires_at);
