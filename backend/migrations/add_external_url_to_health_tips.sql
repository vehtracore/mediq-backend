-- Add external_url column to health_tips table for "Read More" links
ALTER TABLE health_tips ADD COLUMN IF NOT EXISTS external_url VARCHAR;
