-- ============================================================
-- CognaSync — Intelligence Layer Data Model
-- Migration: pivot_001_intelligence_layer
--
-- Run in Supabase > SQL Editor AFTER deploying the pivot.
-- Existing v1 tables (checkins, journals, etc.) are untouched —
-- this migration only adds new tables. The v1 schema stays intact
-- so the v1 codebase can be restored to any prior tag without
-- data loss.
--
-- Apply grants after creating each table so the service role
-- (used by supabase_admin) can write, and RLS policies control
-- what the anon/authenticated keys can read.
-- ============================================================

-- ── 1. CLINICAL SESSIONS ────────────────────────────────────────
-- The primary input record. One row per therapy or psychiatry session.
-- Transcript arrives as raw text; structured extraction is stored
-- separately in session_features once the pipeline processes it.

CREATE TABLE IF NOT EXISTS clinical_sessions (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id          UUID        NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    provider_id         UUID        NOT NULL REFERENCES profiles(id),
    session_date        DATE        NOT NULL,
    session_type        TEXT        NOT NULL
                            CHECK (session_type IN ('psychiatry', 'therapy', 'intake', 'followup', 'group', 'other')),
    duration_minutes    INTEGER,
    transcript_raw      TEXT,           -- verbatim transcript text
    transcript_json     JSONB,          -- structured [{speaker, timestamp, text}, ...]
    transcript_source   TEXT            -- 'upload', 'assemblyai', 'deepgram', 'manual'
                            DEFAULT 'upload',
    processing_status   TEXT            -- 'pending', 'processing', 'complete', 'error'
                            DEFAULT 'pending',
    processing_error    TEXT,           -- error message if processing_status = 'error'
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_clinical_sessions_patient_date
    ON clinical_sessions (patient_id, session_date DESC);

CREATE INDEX IF NOT EXISTS idx_clinical_sessions_provider
    ON clinical_sessions (provider_id, session_date DESC);

GRANT ALL ON TABLE clinical_sessions TO anon, authenticated, service_role;


-- ── 2. SESSION FEATURES ─────────────────────────────────────────
-- Structured clinical features extracted from a session transcript
-- by the intelligence pipeline. One row per clinical_session once
-- processing completes.
--
-- Key design: extraction is factual (what was mentioned, what signals
-- were present). Clinical interpretation happens in the deterministic
-- scoring layer and in the Mode C generation — never here.

CREATE TABLE IF NOT EXISTS session_features (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id          UUID        NOT NULL UNIQUE REFERENCES clinical_sessions(id) ON DELETE CASCADE,
    patient_id          UUID        NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,

    -- Raw feature extraction (from transcript_engine.py)
    extracted           JSONB       NOT NULL DEFAULT '{}',
    -- Shape of extracted:
    -- {
    --   patient_mood_description: str | null,
    --   mood_estimate: 1-10 | null,       -- only if patient named a number
    --   energy_description: str | null,
    --   energy_estimate: 1-10 | null,
    --   sleep_hours_mentioned: float | null,
    --   sleep_quality_description: str | null,
    --   stress_description: str | null,
    --   themes: [str, ...],
    --   medications_mentioned: [{name, context, adherence_signal}],
    --   symptoms_mentioned: [str, ...],
    --   stressors: [str, ...],
    --   positive_signals: [str, ...],
    --   concerning_language: [str, ...],
    --   crisis_language_detected: bool,
    --   session_notes: str
    -- }

    -- Deterministic scores (from scoring engine, same formulas as v1)
    scores              JSONB       NOT NULL DEFAULT '{}',
    -- Shape of scores:
    -- {
    --   mood_estimate: float | null,
    --   sleep_disruption: float | null,
    --   nervous_system_load: float | null,
    --   crash_risk: float | null,
    --   stim_load: float | null,
    --   medication_adherence_signal: str | null
    -- }

    -- Safety flags (populated by crisis detection before extraction)
    crisis_detected     BOOLEAN     NOT NULL DEFAULT FALSE,
    safety_flags        JSONB       DEFAULT '{}',

    extraction_model    TEXT,           -- model version used for extraction
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_session_features_patient
    ON session_features (patient_id, created_at DESC);

GRANT ALL ON TABLE session_features TO anon, authenticated, service_role;


-- ── 3. VOICE MEMOS ──────────────────────────────────────────────
-- 90-second weekly patient recordings — the only required patient
-- action beyond initial consent. Captures affect, energy, and pacing
-- that text cannot.

CREATE TABLE IF NOT EXISTS voice_memos (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id          UUID        NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    recorded_at         DATE        NOT NULL,
    week_of             DATE,           -- start of the week this covers (Monday)
    audio_url           TEXT,           -- Supabase Storage path
    transcript          TEXT,           -- transcribed text (via AssemblyAI/Deepgram)
    acoustic_features   JSONB,          -- {speech_rate, vocal_energy, pause_rate,
                                        --  prosody_score, pitch_variability}
    processing_status   TEXT DEFAULT 'pending',
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (patient_id, week_of)        -- one memo per patient per week
);

CREATE INDEX IF NOT EXISTS idx_voice_memos_patient_week
    ON voice_memos (patient_id, week_of DESC);

GRANT ALL ON TABLE voice_memos TO anon, authenticated, service_role;


-- ── 4. WEARABLE SNAPSHOTS ───────────────────────────────────────
-- Aggregated daily biometric data from any wearable source.
-- One row per patient per date per source. Multiple sources for the
-- same patient/date are acceptable — the brief generation layer picks
-- the highest-confidence source or averages when they align.

CREATE TABLE IF NOT EXISTS wearable_snapshots (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id          UUID        NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    snapshot_date       DATE        NOT NULL,
    source              TEXT        NOT NULL    -- 'apple_health', 'google_health', 'whoop', 'oura', 'fitbit', 'garmin'
                            DEFAULT 'apple_health',
    sleep_hours         NUMERIC(4,1),
    sleep_stages        JSONB,          -- {light_min, deep_min, rem_min, awake_min}
    hrv_ms              NUMERIC(6,1),   -- heart rate variability, RMSSD
    resting_hr          INTEGER,
    active_minutes      INTEGER,
    steps               INTEGER,
    raw_data            JSONB,          -- full source payload for reprocessing
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (patient_id, snapshot_date, source)
);

CREATE INDEX IF NOT EXISTS idx_wearable_snapshots_patient_date
    ON wearable_snapshots (patient_id, snapshot_date DESC);

GRANT ALL ON TABLE wearable_snapshots TO anon, authenticated, service_role;


-- ── 5. MEDICATION RECORDS ───────────────────────────────────────
-- The patient's current medication list. Source can be FHIR, manual
-- entry by provider, or imported from v1 patient_profiles.current_medications.

CREATE TABLE IF NOT EXISTS medication_records (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id          UUID        NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    provider_id         UUID        REFERENCES profiles(id),   -- prescribing provider if known
    medication_name     TEXT        NOT NULL,
    dose_amount         NUMERIC(8,2),
    dose_unit           TEXT        DEFAULT 'mg',
    frequency           TEXT,           -- 'daily', 'twice_daily', 'as_needed', 'weekly'
    prescribed_date     DATE,
    discontinued_date   DATE,
    active              BOOLEAN     DEFAULT TRUE,
    source              TEXT        DEFAULT 'manual',   -- 'fhir', 'surescripts', 'manual', 'v1_import'
    fhir_resource_id    TEXT,          -- FHIR MedicationRequest ID for deduplication
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_medication_records_patient_active
    ON medication_records (patient_id, active, created_at DESC);

GRANT ALL ON TABLE medication_records TO anon, authenticated, service_role;


-- ── 6. PHARMACY FILLS ───────────────────────────────────────────
-- Fill records indicate when a patient actually picked up a prescription.
-- Gap analysis between days_supply and next fill date is the primary
-- adherence signal for the persistence-risk layer.

CREATE TABLE IF NOT EXISTS pharmacy_fills (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id          UUID        NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    medication_id       UUID        REFERENCES medication_records(id),
    medication_name     TEXT,           -- denormalized for cases where medication_id is null
    fill_date           DATE        NOT NULL,
    days_supply         INTEGER,
    quantity_dispensed  NUMERIC(8,2),
    pharmacy_name       TEXT,
    ndc                 TEXT,           -- National Drug Code
    source              TEXT        DEFAULT 'manual',   -- 'fhir', 'surescripts', 'manual'
    fhir_resource_id    TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (patient_id, medication_name, fill_date, source)
);

CREATE INDEX IF NOT EXISTS idx_pharmacy_fills_patient_med
    ON pharmacy_fills (patient_id, medication_name, fill_date DESC);

GRANT ALL ON TABLE pharmacy_fills TO anon, authenticated, service_role;


-- ── 7. PROVIDER BRIEFS ──────────────────────────────────────────
-- Generated Mode C provider briefs. Immutable once created —
-- each regeneration creates a new row. The provider always sees
-- the most recently generated brief for a given session/period.

CREATE TABLE IF NOT EXISTS provider_briefs (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id          UUID        NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    provider_id         UUID        NOT NULL REFERENCES profiles(id),
    brief_type          TEXT        NOT NULL    -- 'pre_visit', 'post_session', 'alert'
                            DEFAULT 'pre_visit',
    for_session_id      UUID        REFERENCES clinical_sessions(id),
    period_start        DATE,
    period_end          DATE,
    content             TEXT        NOT NULL,   -- the Mode C output text
    data_sources        JSONB,      -- {sessions: [id,...], wearable_days: int, voice_memos: int, ...}
    scores              JSONB,      -- aggregate scores used in this brief
    crisis_detected     BOOLEAN     NOT NULL DEFAULT FALSE,
    session_count       INTEGER     DEFAULT 0,
    model_version       TEXT,
    generated_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_provider_briefs_patient
    ON provider_briefs (patient_id, generated_at DESC);

CREATE INDEX IF NOT EXISTS idx_provider_briefs_provider
    ON provider_briefs (provider_id, generated_at DESC);

GRANT ALL ON TABLE provider_briefs TO anon, authenticated, service_role;


-- ── 8. PATIENT SESSION SUMMARIES ────────────────────────────────
-- Plain-language summaries generated for patients after a session.
-- Never contains clinical scores, thresholds, or provider flags.

CREATE TABLE IF NOT EXISTS patient_session_summaries (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id          UUID        NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    session_id          UUID        NOT NULL REFERENCES clinical_sessions(id) ON DELETE CASCADE,
    content             TEXT        NOT NULL,
    model_version       TEXT,
    generated_at        TIMESTAMPTZ DEFAULT NOW()
);

GRANT ALL ON TABLE patient_session_summaries TO anon, authenticated, service_role;


-- ── 9. PROVIDER BRIEF VIEWS ─────────────────────────────────────
-- Track when a provider viewed a brief (for analytics and audit).

CREATE TABLE IF NOT EXISTS provider_brief_views (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    brief_id            UUID        NOT NULL REFERENCES provider_briefs(id) ON DELETE CASCADE,
    provider_id         UUID        NOT NULL REFERENCES profiles(id),
    viewed_at           TIMESTAMPTZ DEFAULT NOW()
);

GRANT ALL ON TABLE provider_brief_views TO anon, authenticated, service_role;


-- ── 10. PATIENT CONSENTS ────────────────────────────────────────
-- Explicit, auditable consent records for each data source.
-- A patient must have an active consent record for a source before
-- that source's data can be ingested or used in brief generation.

CREATE TABLE IF NOT EXISTS patient_consents (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id          UUID        NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    data_source         TEXT        NOT NULL,   -- 'session_recording', 'apple_health',
                                                -- 'google_health', 'pharmacy_fhir', 'voice_memo'
    granted             BOOLEAN     NOT NULL DEFAULT FALSE,
    granted_at          TIMESTAMPTZ,
    revoked_at          TIMESTAMPTZ,
    consent_version     TEXT,                   -- version of consent language shown
    ip_address          TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (patient_id, data_source)
);

GRANT ALL ON TABLE patient_consents TO anon, authenticated, service_role;


-- ── INDEXES AND HELPERS ─────────────────────────────────────────

-- Composite index for period queries (most common brief generation pattern)
CREATE INDEX IF NOT EXISTS idx_session_features_patient_date
    ON session_features (patient_id, created_at DESC);

-- Partial index for pending sessions (processing queue)
CREATE INDEX IF NOT EXISTS idx_clinical_sessions_pending
    ON clinical_sessions (processing_status, created_at)
    WHERE processing_status = 'pending';

-- ── COMMENT ─────────────────────────────────────────────────────
COMMENT ON TABLE clinical_sessions IS
    'Primary input record for the intelligence layer. One row per therapy or psychiatry session. Raw transcript stored here; extracted features stored in session_features.';

COMMENT ON TABLE session_features IS
    'Structured clinical features extracted from a session transcript. Extraction is factual (what was observed/mentioned). Clinical interpretation happens in the scoring and generation layers.';

COMMENT ON TABLE provider_briefs IS
    'Generated Mode C provider briefs. Immutable. Each regeneration creates a new row. Crisis detection flag set at generation time — a flagged brief is never the only action taken.';

COMMENT ON TABLE patient_consents IS
    'Explicit, auditable consent records. No data source is used without a corresponding granted=true row here.';
