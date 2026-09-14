BEGIN;

ALTER TABLE public.emergency_sms_requests
    ADD COLUMN IF NOT EXISTS request_fingerprint VARCHAR(64);

COMMIT;

-- Deploy after add_emergency_sms_request_idempotency.sql and before the
-- backend version that enforces same-key/same-payload emergency replays.
