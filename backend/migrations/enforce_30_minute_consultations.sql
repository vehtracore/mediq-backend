-- Normalize all doctor-priced consultations to one 30-minute duration.

UPDATE doctors
SET consultation_duration_minutes = 30,
    consultation_fee = GREATEST(
        COALESCE(consultation_fee, hourly_rate, 0),
        4000
    );

UPDATE doctors
SET hourly_rate = consultation_fee
WHERE hourly_rate IS DISTINCT FROM consultation_fee;

ALTER TABLE doctors
ALTER COLUMN consultation_fee SET DEFAULT 4000,
ALTER COLUMN consultation_duration_minutes SET DEFAULT 30;

ALTER TABLE doctors
DROP CONSTRAINT IF EXISTS ck_doctors_consultation_duration;

ALTER TABLE doctors
DROP CONSTRAINT IF EXISTS ck_doctors_consultation_duration_30;

ALTER TABLE doctors
DROP CONSTRAINT IF EXISTS ck_doctors_consultation_minimum_fee;

ALTER TABLE doctors
DROP CONSTRAINT IF EXISTS ck_doctors_consultation_minimum_fee_30;

ALTER TABLE doctors
ADD CONSTRAINT ck_doctors_consultation_duration
CHECK (consultation_duration_minutes = 30);

ALTER TABLE doctors
ADD CONSTRAINT ck_doctors_consultation_minimum_fee
CHECK (consultation_fee >= 4000);
