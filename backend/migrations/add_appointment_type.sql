-- Durable workflow discriminator for the three MDQ+ appointment flows.
--
-- Legacy backfill is deliberately conservative:
--   * slot-backed rows are specialist appointments;
--   * known backend-generated references identify their original flow;
--   * unassigned rows without slots are general queue requests;
--   * assigned rows without slots and without a known reference remain NULL,
--     because they could be either claimed general-queue or VIP appointments.

ALTER TABLE appointments
ADD COLUMN IF NOT EXISTS appointment_type VARCHAR(32);

UPDATE appointments
SET appointment_type = NULL
WHERE appointment_type IS NOT NULL
  AND appointment_type NOT IN (
      'general_queue',
      'specialist_scheduled',
      'vip_request'
  );

UPDATE appointments
SET appointment_type = CASE
    WHEN slot_id IS NOT NULL THEN 'specialist_scheduled'
    WHEN LOWER(COALESCE(paystack_reference, '')) LIKE '%gp_consult%'
        THEN 'general_queue'
    WHEN LOWER(COALESCE(paystack_reference, '')) LIKE '%vip_request%'
        THEN 'vip_request'
    WHEN LOWER(COALESCE(paystack_reference, '')) LIKE '%specialist%'
        THEN 'specialist_scheduled'
    WHEN doctor_id IS NULL AND slot_id IS NULL
        THEN 'general_queue'
    ELSE NULL
END
WHERE appointment_type IS NULL;

CREATE INDEX IF NOT EXISTS ix_appointments_appointment_type
ON appointments (appointment_type);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_appointments_appointment_type'
    ) THEN
        ALTER TABLE appointments
        ADD CONSTRAINT ck_appointments_appointment_type
        CHECK (
            appointment_type IS NULL
            OR appointment_type IN (
                'general_queue',
                'specialist_scheduled',
                'vip_request'
            )
        );
    END IF;
END
$$;

-- TODO: After ambiguous legacy rows are reviewed and all writers have been
-- deployed, make appointments.appointment_type NOT NULL.
