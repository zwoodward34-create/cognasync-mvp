-- ============================================================
-- CognaSync — Checkins table migration
-- Run this in Supabase > SQL Editor
-- ============================================================
-- Adds the columns that the API has always accepted but never
-- persisted.  All are nullable so existing rows are unaffected.
-- ============================================================

ALTER TABLE checkins
  ADD COLUMN IF NOT EXISTS mood_score        INTEGER,
  ADD COLUMN IF NOT EXISTS stress_score      INTEGER,
  ADD COLUMN IF NOT EXISTS sleep_hours       NUMERIC(4,1),
  ADD COLUMN IF NOT EXISTS checkin_type      TEXT    DEFAULT 'on_demand',
  ADD COLUMN IF NOT EXISTS time_of_day       TEXT,
  ADD COLUMN IF NOT EXISTS medications       JSONB   DEFAULT '[]',
  ADD COLUMN IF NOT EXISTS extended_data     JSONB   DEFAULT '{}';

-- Back-fill: copy existing stability_score into mood_score for
-- any rows that pre-date this migration so trend queries still
-- work on historical data.
UPDATE checkins
   SET mood_score = stability_score
 WHERE mood_score IS NULL
   AND stability_score IS NOT NULL;

-- Optional index — speeds up baseline and trend queries that
-- filter by user + date range.
CREATE INDEX IF NOT EXISTS idx_checkins_user_date
    ON checkins (user_id, checkin_date DESC);
