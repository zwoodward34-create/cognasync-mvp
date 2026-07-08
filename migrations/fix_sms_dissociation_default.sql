-- Backfill: strip the bogus dissociation=0 default from legacy SMS check-ins.
--
-- Context: the SMS short check-in handler used to store dissociation=0 with
-- dissociation_source='sms_default'. Spec §12 says missing fields are absent,
-- not zero — the 0 inflated Stability Score by up to +2.5 and corrupted Mood
-- Distortion for every SMS check-in. The handler no longer writes these keys;
-- _compute_checkin_scores() now uses a 3-term fallback when dissociation is
-- absent (see CLAUDE.md §5). Scores are computed at read time, so removing the
-- stored keys is the only backfill needed — no score recomputation required.
--
-- Idempotent. Run in dev (mvekchhbyvyhbdilulfx) first, then prod.
-- Sanity check before/after:
--   SELECT count(*) FROM checkins
--   WHERE extended_data->>'dissociation_source' = 'sms_default';

UPDATE checkins
SET extended_data = (extended_data - 'dissociation') - 'dissociation_source'
WHERE extended_data->>'dissociation_source' = 'sms_default';
