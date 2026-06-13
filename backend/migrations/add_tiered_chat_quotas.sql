-- Migration: Add tiered AI chat quota columns to users table
-- Corresponds to the three-layer token-bucket system in api/v1/chat.py

-- Free tier (monthly bucket)
ALTER TABLE users ADD COLUMN IF NOT EXISTS monthly_chat_count       INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS monthly_chat_image_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_chat_month_reset    DATE;

-- Premium / Family tier (rolling 24-hour bucket)
ALTER TABLE users ADD COLUMN IF NOT EXISTS rolling_chat_count        INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS rolling_chat_image_count  INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS rolling_chat_window_start TIMESTAMP;

-- Global cold-cap hard-block timestamp
ALTER TABLE users ADD COLUMN IF NOT EXISTS chat_blocked_until TIMESTAMP;

-- NOTE: burst_chat_count and burst_start_time already exist and are reused
--       for the 15-minute cold-cap window.  No action needed for those columns.

-- NOTE: daily_chat_count and last_chat_date are preserved (legacy columns).
--       They are no longer written to by the new chat logic but are kept for
--       backward compatibility until a future cleanup migration removes them.
