-- Backfill: normalize the orphaned SMS sleep-latency key.
--
-- Context: the SMS rotating sleep question stored answers under
-- 'sleep_latency_min', but the Sleep Disruption score reads
-- 'sleep_latency_minutes' — so those answers never reached scoring.
-- The writer now uses the canonical key and scoring accepts both; this
-- backfill copies legacy values onto the canonical key so historical
-- SMS answers count in trend windows (scores compute at read time).
--
-- Idempotent (skips rows that already have the canonical key).
-- Run in dev (mvekchhbyvyhbdilulfx) first, then prod.
-- Sanity check:
--   SELECT count(*) FROM checkins
--   WHERE extended_data ? 'sleep_latency_min'
--     AND NOT extended_data ? 'sleep_latency_minutes';

UPDATE checkins
SET extended_data = (extended_data - 'sleep_latency_min')
                    || jsonb_build_object('sleep_latency_minutes',
                                          extended_data->'sleep_latency_min')
WHERE extended_data ? 'sleep_latency_min'
  AND NOT extended_data ? 'sleep_latency_minutes';

-- Drop the legacy key from any rows that somehow carry both.
UPDATE checkins
SET extended_data = extended_data - 'sleep_latency_min'
WHERE extended_data ? 'sleep_latency_min';
