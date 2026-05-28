-- CognaSync — Twilio SMS Schema Migration
-- Run this in the Supabase SQL Editor (dashboard > SQL Editor > New query)
-- Safe to re-run: tables/indexes use IF NOT EXISTS; policies use DROP IF EXISTS before CREATE

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. sms_tokens
--    Pre-authenticated single-use tokens that identify a patient in Twilio flows.
--    Token is embedded in webhook calls and voice recording URLs.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sms_tokens (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    token       text UNIQUE NOT NULL,
    patient_id  uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    flow_type   text NOT NULL CHECK (flow_type IN ('medication', 'short', 'full', 'voice')),
    metadata    jsonb NOT NULL DEFAULT '{}',
    expires_at  timestamptz NOT NULL,
    used_at     timestamptz,                          -- NULL = unused
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS sms_tokens_token_idx       ON sms_tokens (token);
CREATE INDEX IF NOT EXISTS sms_tokens_patient_idx     ON sms_tokens (patient_id);
CREATE INDEX IF NOT EXISTS sms_tokens_expires_idx     ON sms_tokens (expires_at);

-- RLS: patients cannot query their own tokens; backend uses service role only
ALTER TABLE sms_tokens ENABLE ROW LEVEL SECURITY;

GRANT ALL ON TABLE sms_tokens TO service_role;
-- No grants to anon or authenticated — token table is backend-only

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. checkin_schedules
--    Per-patient SMS delivery schedule. One row per patient.
--    short_checkin_days uses ISO weekday integers: 0=Mon, 1=Tue, … 6=Sun
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS checkin_schedules (
    patient_id              uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    medication_dose_time    time,                     -- HH:MM in patient's local tz
    short_checkin_days      integer[] NOT NULL DEFAULT '{0,2}',  -- Mon, Wed
    voice_day_of_week       integer NOT NULL DEFAULT 3,          -- Thu
    full_checkin_offset_hrs integer NOT NULL DEFAULT 24,         -- hours before appt
    timezone                text NOT NULL DEFAULT 'America/New_York',
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE checkin_schedules ENABLE ROW LEVEL SECURITY;

-- Drop before recreating so this migration is safely re-runnable
DROP POLICY IF EXISTS "patients_own_schedule"    ON checkin_schedules;
DROP POLICY IF EXISTS "service_role_all_schedules" ON checkin_schedules;

-- Patients can read their own schedule; service role handles all writes
CREATE POLICY "patients_own_schedule"
    ON checkin_schedules FOR SELECT
    USING (patient_id = auth.uid());

CREATE POLICY "service_role_all_schedules"
    ON checkin_schedules FOR ALL
    USING (true);

GRANT ALL ON TABLE checkin_schedules TO service_role;
GRANT SELECT ON TABLE checkin_schedules TO authenticated;

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. checkins — add new columns
--    source       : where the check-in came from
--    check_in_type: granularity of the check-in
--    follow_up_note : free-text answer to the adaptive follow-up question
--    follow_up_type : which signal triggered the follow-up
--    flags         : JSONB for silent backend flags (tier1_watch, etc.)
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE checkins
    ADD COLUMN IF NOT EXISTS source        text DEFAULT 'web'
        CHECK (source IN ('sms', 'web', 'manual')),
    ADD COLUMN IF NOT EXISTS check_in_type text DEFAULT 'full'
        CHECK (check_in_type IN ('micro', 'short', 'full')),
    ADD COLUMN IF NOT EXISTS follow_up_note text,
    ADD COLUMN IF NOT EXISTS follow_up_type text
        CHECK (follow_up_type IN ('mood', 'stress', 'sleep', 'energy', NULL)),
    ADD COLUMN IF NOT EXISTS flags         jsonb NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS checkins_source_idx        ON checkins (source);
CREATE INDEX IF NOT EXISTS checkins_check_in_type_idx ON checkins (check_in_type);
CREATE INDEX IF NOT EXISTS checkins_flags_idx         ON checkins USING gin (flags);

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. Cleanup helper: purge expired unused tokens (run periodically or via cron)
-- ─────────────────────────────────────────────────────────────────────────────
-- To run manually:
-- DELETE FROM sms_tokens WHERE expires_at < now() AND used_at IS NULL;
