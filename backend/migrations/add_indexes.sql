-- =============================================================
-- Migration: Add database indexes for scaling
-- Date: 2026-03-23
-- Description: Creates indexes on foreign keys, lookup fields,
--              and timestamp columns to eliminate sequential scans.
-- Usage: Run this against the production PostgreSQL database via
--        psql, Render SQL console, or your preferred DB tool.
-- =============================================================

-- ── Users ──────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS ix_users_role        ON users (role);
CREATE INDEX IF NOT EXISTS ix_users_is_verified ON users (is_verified);
CREATE INDEX IF NOT EXISTS ix_users_is_active   ON users (is_active);

-- ── Doctors ────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS ix_doctors_user_id     ON doctors (user_id);
CREATE INDEX IF NOT EXISTS ix_doctors_status      ON doctors (status);
CREATE INDEX IF NOT EXISTS ix_doctors_is_verified ON doctors (is_verified);

-- ── Doctor Slots ───────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS ix_doctor_slots_doctor_id ON doctor_slots (doctor_id);

-- ── Appointments ───────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS ix_appointments_patient_id ON appointments (patient_id);
CREATE INDEX IF NOT EXISTS ix_appointments_doctor_id  ON appointments (doctor_id);
CREATE INDEX IF NOT EXISTS ix_appointments_status     ON appointments (status);
CREATE INDEX IF NOT EXISTS ix_appointments_start_time ON appointments (start_time);

-- ── Messages ───────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS ix_messages_appointment_id ON messages (appointment_id);
CREATE INDEX IF NOT EXISTS ix_messages_sender_id      ON messages (sender_id);
CREATE INDEX IF NOT EXISTS ix_messages_created_at     ON messages (created_at);

-- ── Reviews ────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS ix_reviews_doctor_id  ON reviews (doctor_id);
CREATE INDEX IF NOT EXISTS ix_reviews_patient_id ON reviews (patient_id);
CREATE INDEX IF NOT EXISTS ix_reviews_created_at ON reviews (created_at);

-- ── Lab Results ────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS ix_lab_results_user_id    ON lab_results (user_id);
CREATE INDEX IF NOT EXISTS ix_lab_results_created_at ON lab_results (created_at);

-- ── Audit Logs ─────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS ix_audit_logs_admin_id   ON audit_logs (admin_id);
CREATE INDEX IF NOT EXISTS ix_audit_logs_timestamp  ON audit_logs (timestamp);

-- ── Health Tips ────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS ix_health_tips_created_at ON health_tips (created_at);
