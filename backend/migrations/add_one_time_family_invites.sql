BEGIN;

ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS family_invite_nonce VARCHAR(64),
    ADD COLUMN IF NOT EXISTS family_invite_expires_at TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS uq_users_family_invite_nonce
    ON public.users(family_invite_nonce)
    WHERE family_invite_nonce IS NOT NULL;

COMMIT;

-- No dependency beyond public.users. Deploy this migration before the backend version that
-- generates or redeems one-time family invitation nonces.
