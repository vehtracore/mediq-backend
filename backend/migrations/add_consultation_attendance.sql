-- Durable attendance, session-start, no-show and refund-review state.

ALTER TABLE appointments
ADD COLUMN IF NOT EXISTS patient_joined_at TIMESTAMP NULL;

ALTER TABLE appointments
ADD COLUMN IF NOT EXISTS doctor_joined_at TIMESTAMP NULL;

ALTER TABLE appointments
ADD COLUMN IF NOT EXISTS consultation_started_at TIMESTAMP NULL;

ALTER TABLE appointments
ADD COLUMN IF NOT EXISTS no_show_marked_at TIMESTAMP NULL;

ALTER TABLE appointments
ADD COLUMN IF NOT EXISTS refund_status VARCHAR(32) NULL;

CREATE INDEX IF NOT EXISTS ix_appointments_consultation_started_at
ON appointments (consultation_started_at);
