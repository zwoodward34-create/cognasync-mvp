-- Migration: flag visibility list + flag responses table
-- Apply via Supabase SQL Editor or `supabase db push`

-- 1. Add visible_to_providers to care_flags
--    NULL means all active care team members can see the flag (existing behaviour).
--    A JSON array of provider_id UUIDs restricts visibility to those providers only.
ALTER TABLE care_flags
  ADD COLUMN IF NOT EXISTS visible_to_providers JSONB DEFAULT NULL;

-- 2. Create care_flag_responses table
CREATE TABLE IF NOT EXISTS care_flag_responses (
    id                 UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    flag_id            UUID        NOT NULL REFERENCES care_flags(id) ON DELETE CASCADE,
    patient_id         UUID        NOT NULL,
    author_provider_id UUID        NOT NULL,
    body               TEXT        NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_response_length CHECK (char_length(body) BETWEEN 5 AND 500)
);

CREATE INDEX IF NOT EXISTS idx_flag_responses_flag_id    ON care_flag_responses(flag_id);
CREATE INDEX IF NOT EXISTS idx_flag_responses_patient_id ON care_flag_responses(patient_id);

GRANT ALL ON TABLE care_flag_responses TO anon, authenticated, service_role;
