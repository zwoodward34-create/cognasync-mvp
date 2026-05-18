-- Migration: add missing care_team_members columns
-- Safe to run on existing tables — all statements use IF NOT EXISTS / no-op defaults.

ALTER TABLE care_team_members
  ADD COLUMN IF NOT EXISTS data_permissions JSONB,
  ADD COLUMN IF NOT EXISTS requested_by     TEXT DEFAULT 'provider',
  ADD COLUMN IF NOT EXISTS request_message  TEXT,
  ADD COLUMN IF NOT EXISTS approved_at      TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS revoked_at       TIMESTAMPTZ;

-- Backfill: give all existing rows full access so nothing breaks for legacy relationships.
UPDATE care_team_members
SET data_permissions = '{"journals_raw":true,"journals_themes":true,"mood_stress_sleep":true,"medication_data":true,"system_scores":true,"advanced_data":true,"cross_provider_flags":true}'::jsonb
WHERE data_permissions IS NULL;

-- Set a non-null default for future inserts.
ALTER TABLE care_team_members
  ALTER COLUMN data_permissions SET DEFAULT
    '{"journals_raw":true,"journals_themes":true,"mood_stress_sleep":true,"medication_data":true,"system_scores":true,"advanced_data":true,"cross_provider_flags":true}'::jsonb;
