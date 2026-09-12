-- Durable, idempotent support submissions. Apply before deploying the backend
-- code that writes to support_messages. This migration does not send email.

BEGIN;

CREATE TABLE IF NOT EXISTS support_messages (
    id UUID PRIMARY KEY,
    request_id UUID NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject TEXT NOT NULL,
    message TEXT NOT NULL,
    email_status VARCHAR(32) NOT NULL DEFAULT 'pending',
    provider_message_id VARCHAR(255),
    failure_category VARCHAR(32),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at TIMESTAMPTZ,
    CONSTRAINT uq_support_messages_request_id UNIQUE (request_id),
    CONSTRAINT ck_support_messages_email_status
        CHECK (email_status IN ('pending', 'sending', 'sent', 'failed')),
    CONSTRAINT ck_support_messages_failure_category
        CHECK (
            failure_category IS NULL OR failure_category IN (
                'configuration',
                'rate_limited',
                'provider_rejected',
                'provider_timeout',
                'provider_unavailable',
                'unknown'
            )
        )
);

CREATE INDEX IF NOT EXISTS ix_support_messages_user_id
    ON support_messages(user_id);

CREATE INDEX IF NOT EXISTS ix_support_messages_email_status
    ON support_messages(email_status);

COMMIT;
