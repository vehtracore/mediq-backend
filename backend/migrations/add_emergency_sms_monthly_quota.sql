-- UTC calendar-month marker for the Emergency NOK SMS allowance.
-- Existing lifetime counters intentionally keep a NULL marker so the next
-- eligible server-side reservation starts a fresh monthly window.

ALTER TABLE users
ADD COLUMN IF NOT EXISTS emergency_sms_month_reset DATE NULL;
