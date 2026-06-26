-- Adds account-level failed attempt tracking for AI urinalysis scanner abuse control.

ALTER TABLE users
ADD COLUMN IF NOT EXISTS lab_failed_attempt_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE users
ADD COLUMN IF NOT EXISTS lab_failed_attempt_started_at TIMESTAMPTZ NULL;

ALTER TABLE users
ADD COLUMN IF NOT EXISTS lab_last_failed_attempt_at TIMESTAMPTZ NULL;

ALTER TABLE users
ADD COLUMN IF NOT EXISTS lab_cooldown_until TIMESTAMPTZ NULL;
