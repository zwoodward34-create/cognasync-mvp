-- Adds SMS opt-in consent tracking to patient_profiles.
-- Apply via the Supabase SQL Editor (this repo has no migration runner).
-- Safe to run more than once: uses IF NOT EXISTS and a default for existing rows.

ALTER TABLE patient_profiles
    ADD COLUMN IF NOT EXISTS sms_consent boolean NOT NULL DEFAULT false;

ALTER TABLE patient_profiles
    ADD COLUMN IF NOT EXISTS sms_consent_at timestamptz;

-- Column privileges are inherited from the existing table-level grants on
-- patient_profiles (anon, authenticated, service_role), so no new GRANT is needed.
