-- Migration: add frequency column to medications table
-- Apply via Supabase SQL Editor

ALTER TABLE medications
  ADD COLUMN IF NOT EXISTS frequency TEXT DEFAULT NULL;

-- Valid values: once_daily, twice_daily, three_times_daily,
--               every_morning, at_bedtime, as_needed,
--               every_other_day, weekly
