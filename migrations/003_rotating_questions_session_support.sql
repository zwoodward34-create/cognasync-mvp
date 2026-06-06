-- Migration 003: rotating_pending session type + metadata column
-- Already applied to production 2026-06-06 via Supabase MCP.

ALTER TABLE sms_checkin_sessions
    DROP CONSTRAINT sms_checkin_sessions_session_type_check;

ALTER TABLE sms_checkin_sessions
    ADD CONSTRAINT sms_checkin_sessions_session_type_check
    CHECK (session_type = ANY (ARRAY[
        'checkin_pending'::text,
        'med_pending'::text,
        'help_pending'::text,
        'rotating_pending'::text
    ]));

ALTER TABLE sms_checkin_sessions
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}';
