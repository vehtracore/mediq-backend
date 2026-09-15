BEGIN;

-- Historical terminal rows are intentionally preserved. Deployment should
-- stop and review if an environment still contains multiple active rows for
-- one patient rather than choosing or deleting one automatically.
CREATE UNIQUE INDEX IF NOT EXISTS
    uq_appointments_one_active_general_queue_per_patient
ON appointments (patient_id)
WHERE appointment_type = 'general_queue'
  AND status IN ('pending', 'confirmed');

COMMIT;
