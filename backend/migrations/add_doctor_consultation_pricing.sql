-- Doctor-set flat consultation pricing for specialist and VIP appointments.
-- Existing hourly_rate values are retained where they satisfy the new floor.

ALTER TABLE doctors
ADD COLUMN IF NOT EXISTS consultation_fee DOUBLE PRECISION;

ALTER TABLE doctors
ADD COLUMN IF NOT EXISTS consultation_duration_minutes INTEGER;

UPDATE doctors
SET consultation_duration_minutes = COALESCE(
    consultation_duration_minutes,
    20
);

UPDATE doctors
SET consultation_fee = CASE consultation_duration_minutes
    WHEN 20 THEN GREATEST(COALESCE(consultation_fee, hourly_rate, 0), 4000)
    WHEN 30 THEN GREATEST(COALESCE(consultation_fee, hourly_rate, 0), 5000)
    WHEN 45 THEN GREATEST(COALESCE(consultation_fee, hourly_rate, 0), 7000)
    WHEN 60 THEN GREATEST(COALESCE(consultation_fee, hourly_rate, 0), 9000)
    ELSE 4000
END;

UPDATE doctors
SET hourly_rate = consultation_fee;

ALTER TABLE doctors
ALTER COLUMN consultation_fee SET DEFAULT 4000,
ALTER COLUMN consultation_fee SET NOT NULL,
ALTER COLUMN consultation_duration_minutes SET DEFAULT 20,
ALTER COLUMN consultation_duration_minutes SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_doctors_consultation_duration'
    ) THEN
        ALTER TABLE doctors
        ADD CONSTRAINT ck_doctors_consultation_duration
        CHECK (consultation_duration_minutes IN (20, 30, 45, 60));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_doctors_consultation_minimum_fee'
    ) THEN
        ALTER TABLE doctors
        ADD CONSTRAINT ck_doctors_consultation_minimum_fee
        CHECK (
            (consultation_duration_minutes = 20 AND consultation_fee >= 4000)
            OR (consultation_duration_minutes = 30 AND consultation_fee >= 5000)
            OR (consultation_duration_minutes = 45 AND consultation_fee >= 7000)
            OR (consultation_duration_minutes = 60 AND consultation_fee >= 9000)
        );
    END IF;
END
$$;
