-- ============================================================
-- CognaSync — Summaries table migration
-- Run in Supabase > SQL Editor (safe to re-run)
-- ============================================================
-- Adds summary_text, date_range_start, date_range_end columns
-- so past summaries display correctly and can be deleted.
-- ============================================================

ALTER TABLE summaries
  ADD COLUMN IF NOT EXISTS summary_text     TEXT,
  ADD COLUMN IF NOT EXISTS date_range_start TEXT,
  ADD COLUMN IF NOT EXISTS date_range_end   TEXT;

-- Back-fill existing rows: copy content → summary_text, derive
-- date range from summary_date (assumes 14-day default window).
UPDATE summaries
   SET summary_text     = content,
       date_range_end   = summary_date,
       date_range_start = (summary_date::date - INTERVAL '14 days')::TEXT
 WHERE summary_text IS NULL
   AND content IS NOT NULL;
