BEGIN;

ALTER TABLE ai_chat_summaries
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;

UPDATE ai_chat_summaries
SET updated_at = created_at
WHERE updated_at IS NULL;

ALTER TABLE ai_chat_summaries
ALTER COLUMN updated_at SET DEFAULT NOW();

ALTER TABLE ai_chat_summaries
ALTER COLUMN updated_at SET NOT NULL;

COMMIT;
