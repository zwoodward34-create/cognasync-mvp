-- Provider Appointments table
-- Run this in the Supabase SQL Editor

CREATE TABLE IF NOT EXISTS provider_appointments (
  id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  provider_id             UUID NOT NULL,
  patient_id              UUID NOT NULL,
  status                  TEXT NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'completed', 'cancelled')),
  period_days             INTEGER NOT NULL DEFAULT 30,
  started_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at            TIMESTAMPTZ,
  guided_qa               JSONB NOT NULL DEFAULT '[]',
  notes                   TEXT NOT NULL DEFAULT '',
  care_plan_changes       TEXT NOT NULL DEFAULT '',
  actions                 JSONB NOT NULL DEFAULT '[]',
  next_appointment_date   DATE,
  next_appointment_notes  TEXT NOT NULL DEFAULT '',
  created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_prov_appts_provider ON provider_appointments(provider_id);
CREATE INDEX IF NOT EXISTS idx_prov_appts_patient  ON provider_appointments(patient_id);
CREATE INDEX IF NOT EXISTS idx_prov_appts_started  ON provider_appointments(started_at DESC);

-- Grant access to all roles (required in addition to RLS)
GRANT ALL ON TABLE provider_appointments TO anon, authenticated, service_role;
