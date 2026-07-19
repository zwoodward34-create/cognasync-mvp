-- Scheduling & attendance signals, phase 1 (spec §26.6, decision 2026-07-12).
--
-- Append-only log of calendar scheduling events. The calendar UI edits
-- provider_appointments rows in place and deletes cancelled ones, so
-- reschedules and cancellations previously left no trace. This table
-- preserves them. 'missed'/'kept' outcomes are NOT logged — they are
-- computed at read time by compute_attendance_signals() (a scheduled date
-- in the past with no recorded session is an observation, not an event).
--
-- Reminder (repo convention): CHECK constraint lists every allowed value
-- up front, and GRANTs are required alongside RLS for the service role.
-- Run in dev (mvekchhbyvyhbdilulfx) first, then prod.

CREATE TABLE IF NOT EXISTS scheduling_events (
  id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id              uuid NOT NULL,
  provider_id             uuid NOT NULL,
  calendar_appointment_id uuid,
  event_type              text NOT NULL
                          CHECK (event_type IN ('scheduled', 'rescheduled', 'cancelled')),
  from_date               date,          -- rescheduled: old date; cancelled: the date dropped
  to_date                 date,          -- scheduled/rescheduled: the (new) date
  created_at              timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_scheduling_events_patient
  ON scheduling_events (patient_id, created_at);

ALTER TABLE scheduling_events ENABLE ROW LEVEL SECURITY;
GRANT ALL ON TABLE scheduling_events TO anon, authenticated, service_role;
