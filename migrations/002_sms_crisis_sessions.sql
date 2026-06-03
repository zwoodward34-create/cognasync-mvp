-- Migration 002: SMS crisis events + check-in session tracking
-- Run in Supabase SQL Editor before deploying sms_engine / app.py changes.

-- ── sms_checkin_sessions ─────────────────────────────────────────────────────
-- Tracks which SMS prompt is currently pending for each patient so the inbound
-- router knows how to interpret an unstructured reply (numbers vs Y/N vs CRISIS).

CREATE TABLE IF NOT EXISTS sms_checkin_sessions (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id             UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    session_type           TEXT NOT NULL
                               CHECK (session_type IN ('checkin_pending','med_pending','help_pending')),
    sent_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at            TIMESTAMPTZ,
    -- When HELP interrupts an active session, the prior type is stored here
    -- so routing can resume after the CRISIS/SYSTEM branch resolves.
    suspended_session_type TEXT
                               CHECK (suspended_session_type IN ('checkin_pending','med_pending'))
);

CREATE INDEX IF NOT EXISTS idx_sms_sessions_patient
    ON sms_checkin_sessions(patient_id, resolved_at);

GRANT ALL ON TABLE sms_checkin_sessions TO anon, authenticated, service_role;


-- ── sms_crisis_events ────────────────────────────────────────────────────────
-- One row per crisis signal received via SMS, regardless of source.
-- Intentionally stores no patient text — only metadata.

CREATE TABLE IF NOT EXISTS sms_crisis_events (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id           UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    -- 'keyword'     = free-text crisis keyword matched in any inbound message
    -- 'help_branch' = patient replied CRISIS to the CRISIS/SYSTEM branch prompt
    source               TEXT NOT NULL
                             CHECK (source IN ('keyword','help_branch')),
    triggered_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    provider_notified_at TIMESTAMPTZ,   -- set when provider SMS is confirmed sent
    provider_sms_sid     TEXT           -- Twilio message SID for the provider alert
);

CREATE INDEX IF NOT EXISTS idx_sms_crisis_patient
    ON sms_crisis_events(patient_id, triggered_at DESC);

GRANT ALL ON TABLE sms_crisis_events TO anon, authenticated, service_role;
