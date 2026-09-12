BEGIN;

CREATE TABLE IF NOT EXISTS notification_device_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    installation_id VARCHAR(36) NOT NULL,
    token VARCHAR NOT NULL,
    platform VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_notification_device_installation UNIQUE (installation_id),
    CONSTRAINT uq_notification_device_token UNIQUE (token)
);

CREATE INDEX IF NOT EXISTS ix_notification_device_tokens_user_id
    ON notification_device_tokens(user_id);

CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR NOT NULL,
    body VARCHAR NOT NULL,
    type VARCHAR,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE notifications
    ADD COLUMN IF NOT EXISTS navigation_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS event_key VARCHAR(255);

CREATE UNIQUE INDEX IF NOT EXISTS uq_notifications_event_key
    ON notifications(event_key)
    WHERE event_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_notifications_user_read_created
    ON notifications(user_id, is_read, created_at DESC);

COMMIT;

-- users.fcm_token is intentionally retained for compatibility in this release.
-- It is no longer an active delivery source and can be removed after deployment
-- verification confirms all supported clients use notification_device_tokens.
