-- Migration: add versioned, one-time AI consent fields to users.
--
-- Existing users remain unconsented until they explicitly accept the AI
-- disclosure. Granting consent records the accepted version and timestamp.
-- Withdrawal is recorded separately and blocks later AI processing until the
-- user grants consent again.

ALTER TABLE users
ADD COLUMN IF NOT EXISTS ai_consent_granted_at TIMESTAMPTZ;

ALTER TABLE users
ADD COLUMN IF NOT EXISTS ai_consent_version VARCHAR;

ALTER TABLE users
ADD COLUMN IF NOT EXISTS ai_consent_withdrawn_at TIMESTAMPTZ;
