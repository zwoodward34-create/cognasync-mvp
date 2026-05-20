-- Add share_with_provider column to journal_entries and backfill existing rows.
-- Run in Supabase > SQL Editor.

ALTER TABLE journal_entries
  ADD COLUMN IF NOT EXISTS share_with_provider BOOLEAN NOT NULL DEFAULT TRUE;

-- Backfill any rows created before this column existed.
UPDATE journal_entries
SET share_with_provider = TRUE
WHERE share_with_provider IS NULL;
