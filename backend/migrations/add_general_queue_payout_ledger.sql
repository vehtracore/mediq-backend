-- Idempotent general-queue payout ledger and Paystack recipient storage.

ALTER TABLE doctors
ADD COLUMN IF NOT EXISTS paystack_recipient_code VARCHAR NULL;

CREATE TABLE IF NOT EXISTS consultation_payouts (
    id SERIAL PRIMARY KEY,
    appointment_id INTEGER NOT NULL UNIQUE REFERENCES appointments(id),
    doctor_id INTEGER NOT NULL REFERENCES doctors(id),
    amount NUMERIC(14,2) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'awaiting_admin',
    reference VARCHAR(64) NOT NULL UNIQUE,
    recipient_code VARCHAR NULL,
    transfer_code VARCHAR NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error VARCHAR NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    paid_at TIMESTAMP NULL,
    approved_by_admin_id INTEGER NULL REFERENCES users(id),
    approved_at TIMESTAMP NULL,
    rejected_by_admin_id INTEGER NULL REFERENCES users(id),
    rejected_at TIMESTAMP NULL,
    rejection_reason VARCHAR NULL
);

ALTER TABLE consultation_payouts
ADD COLUMN IF NOT EXISTS approved_by_admin_id INTEGER NULL REFERENCES users(id);

ALTER TABLE consultation_payouts
ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP NULL;

ALTER TABLE consultation_payouts
ADD COLUMN IF NOT EXISTS rejected_by_admin_id INTEGER NULL REFERENCES users(id);

ALTER TABLE consultation_payouts
ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMP NULL;

ALTER TABLE consultation_payouts
ADD COLUMN IF NOT EXISTS rejection_reason VARCHAR NULL;

ALTER TABLE consultation_payouts
ALTER COLUMN status SET DEFAULT 'awaiting_admin';

UPDATE consultation_payouts
SET status = 'awaiting_admin'
WHERE status = 'pending'
   OR (status = 'blocked' AND approved_at IS NULL);

CREATE INDEX IF NOT EXISTS ix_consultation_payouts_status
ON consultation_payouts (status);

CREATE INDEX IF NOT EXISTS ix_consultation_payouts_doctor_id
ON consultation_payouts (doctor_id);

CREATE INDEX IF NOT EXISTS ix_consultation_payouts_transfer_code
ON consultation_payouts (transfer_code);

CREATE INDEX IF NOT EXISTS ix_consultation_payouts_approved_by_admin_id
ON consultation_payouts (approved_by_admin_id);

CREATE INDEX IF NOT EXISTS ix_consultation_payouts_rejected_by_admin_id
ON consultation_payouts (rejected_by_admin_id);
