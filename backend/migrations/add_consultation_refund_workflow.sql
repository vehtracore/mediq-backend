-- Admin-reviewed Paystack refunds for doctor/both no-show consultations.

ALTER TABLE appointments
ADD COLUMN IF NOT EXISTS refund_reference VARCHAR NULL;

ALTER TABLE appointments
ADD COLUMN IF NOT EXISTS refund_id VARCHAR NULL;

ALTER TABLE appointments
ADD COLUMN IF NOT EXISTS refund_amount DOUBLE PRECISION NULL;

ALTER TABLE appointments
ADD COLUMN IF NOT EXISTS refund_approved_by_admin_id INTEGER NULL
    REFERENCES users(id);

ALTER TABLE appointments
ADD COLUMN IF NOT EXISTS refund_approved_at TIMESTAMP NULL;

ALTER TABLE appointments
ADD COLUMN IF NOT EXISTS refund_rejected_by_admin_id INTEGER NULL
    REFERENCES users(id);

ALTER TABLE appointments
ADD COLUMN IF NOT EXISTS refund_rejected_at TIMESTAMP NULL;

ALTER TABLE appointments
ADD COLUMN IF NOT EXISTS refund_processed_at TIMESTAMP NULL;

ALTER TABLE appointments
ADD COLUMN IF NOT EXISTS refund_last_error VARCHAR NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ix_appointments_refund_reference
ON appointments (refund_reference)
WHERE refund_reference IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_appointments_refund_id
ON appointments (refund_id);

CREATE INDEX IF NOT EXISTS ix_appointments_refund_approved_admin
ON appointments (refund_approved_by_admin_id);

CREATE INDEX IF NOT EXISTS ix_appointments_refund_rejected_admin
ON appointments (refund_rejected_by_admin_id);

UPDATE appointments
SET refund_status = 'awaiting_admin'
WHERE refund_status = 'pending'
  AND refund_approved_at IS NULL;
