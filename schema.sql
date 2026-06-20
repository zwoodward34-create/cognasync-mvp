-- CognaSync public schema — generated from prod (qsnxrfefwwybiutkynzk) on 2026-06-20.
-- Best-effort introspection dump for dev/local environments. The canonical method
-- is `pg_dump --schema-only` (see docs/local-dev.md). Re-generate if the app errors
-- on a missing object at first boot.

-- ============================================================
-- ord 0: EXTENSIONS
-- ============================================================

CREATE EXTENSION IF NOT EXISTS pg_stat_statements WITH SCHEMA extensions;

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA extensions;

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;

CREATE EXTENSION IF NOT EXISTS supabase_vault WITH SCHEMA vault;

CREATE TABLE IF NOT EXISTS public.care_flag_responses (id uuid NOT NULL DEFAULT gen_random_uuid(), flag_id uuid NOT NULL, patient_id uuid NOT NULL, author_provider_id uuid NOT NULL, body text NOT NULL, created_at timestamp with time zone NOT NULL DEFAULT now());

CREATE TABLE IF NOT EXISTS public.care_flags (id uuid NOT NULL DEFAULT gen_random_uuid(), patient_id uuid NOT NULL, author_provider_id uuid NOT NULL, flag_type text NOT NULL, body text NOT NULL, visibility text NOT NULL DEFAULT 'care_team'::text, created_at timestamp with time zone NOT NULL DEFAULT now(), resolved_at timestamp with time zone, resolved_by uuid, visible_to_providers jsonb);

CREATE TABLE IF NOT EXISTS public.care_team_members (id uuid NOT NULL DEFAULT gen_random_uuid(), patient_id uuid NOT NULL, provider_id uuid NOT NULL, role text NOT NULL DEFAULT 'psychiatrist'::text, status text NOT NULL DEFAULT 'pending'::text, data_permissions jsonb NOT NULL DEFAULT jsonb_build_object('journals_raw', true, 'journals_themes', true, 'mood_stress_sleep', true, 'medication_data', true, 'system_scores', true, 'advanced_data', true, 'cross_provider_flags', true), requested_by text NOT NULL DEFAULT 'provider'::text, request_message text, requested_at timestamp with time zone NOT NULL DEFAULT now(), approved_at timestamp with time zone, revoked_at timestamp with time zone);

CREATE TABLE IF NOT EXISTS public.checkin_schedules (patient_id uuid NOT NULL, medication_dose_time time without time zone, short_checkin_days integer[] NOT NULL DEFAULT '{0,2}'::integer[], voice_day_of_week integer NOT NULL DEFAULT 3, full_checkin_offset_hrs integer NOT NULL DEFAULT 24, timezone text NOT NULL DEFAULT 'America/New_York'::text, created_at timestamp with time zone NOT NULL DEFAULT now(), updated_at timestamp with time zone NOT NULL DEFAULT now(), voice_days integer[] NOT NULL DEFAULT '{}'::integer[]);

CREATE TABLE IF NOT EXISTS public.checkin_tokens (id uuid NOT NULL DEFAULT gen_random_uuid(), token text NOT NULL DEFAULT substr(md5(((random())::text || (clock_timestamp())::text)), 1, 40), patient_id uuid NOT NULL, appointment_id uuid, provider_id uuid, voice_prompt text, token_type text NOT NULL DEFAULT 'checkin'::text, expires_at timestamp with time zone NOT NULL, used_at timestamp with time zone, created_at timestamp with time zone NOT NULL DEFAULT now());

CREATE TABLE IF NOT EXISTS public.checkins (id uuid NOT NULL DEFAULT gen_random_uuid(), user_id uuid NOT NULL, checkin_date date NOT NULL, stability_score integer, dopamine_efficiency integer, nervous_system_load integer, sleep_disruption integer, crash_risk integer, notes text, created_at timestamp without time zone DEFAULT now(), updated_at timestamp without time zone DEFAULT now(), mood_score integer, stress_score integer, sleep_hours numeric(4,1), checkin_type text DEFAULT 'on_demand'::text, time_of_day text, medications jsonb DEFAULT '[]'::jsonb, extended_data jsonb DEFAULT '{}'::jsonb, ai_insights text, source text DEFAULT 'web'::text, check_in_type text DEFAULT 'full'::text, follow_up_note text, follow_up_type text, flags jsonb NOT NULL DEFAULT '{}'::jsonb);

CREATE TABLE IF NOT EXISTS public.clinical_sessions (id uuid NOT NULL DEFAULT gen_random_uuid(), patient_id uuid NOT NULL, provider_id uuid NOT NULL, session_date date NOT NULL, session_type text NOT NULL, duration_minutes integer, transcript_raw text, transcript_json jsonb, transcript_source text DEFAULT 'upload'::text, processing_status text DEFAULT 'pending'::text, processing_error text, created_at timestamp with time zone DEFAULT now(), updated_at timestamp with time zone DEFAULT now(), voice_recording_role text);

CREATE TABLE IF NOT EXISTS public.daily_sms_sends (id uuid NOT NULL DEFAULT gen_random_uuid(), patient_id uuid NOT NULL, send_type text NOT NULL, send_date date NOT NULL, created_at timestamp with time zone NOT NULL DEFAULT now());

CREATE TABLE IF NOT EXISTS public.journal_entries (id uuid NOT NULL DEFAULT gen_random_uuid(), user_id uuid NOT NULL, entry_date date NOT NULL, content text, is_crisis boolean DEFAULT false, created_at timestamp without time zone DEFAULT now(), share_with_provider boolean NOT NULL DEFAULT false, ai_analysis text, entry_type character varying(32));

CREATE TABLE IF NOT EXISTS public.medication_events (id uuid NOT NULL DEFAULT gen_random_uuid(), user_id uuid NOT NULL, medication_id uuid NOT NULL, event_date date NOT NULL, scheduled_time time without time zone, actual_time timestamp without time zone, dose double precision, status text DEFAULT 'TAKEN'::text, taken_with_food boolean, meal_note text, custom_note text, created_at timestamp without time zone DEFAULT now());

CREATE TABLE IF NOT EXISTS public.medication_records (id uuid NOT NULL DEFAULT gen_random_uuid(), patient_id uuid NOT NULL, provider_id uuid, medication_name text NOT NULL, dose_amount numeric(8,2), dose_unit text DEFAULT 'mg'::text, frequency text, prescribed_date date, discontinued_date date, active boolean DEFAULT true, source text DEFAULT 'manual'::text, fhir_resource_id text, notes text, created_at timestamp with time zone DEFAULT now(), updated_at timestamp with time zone DEFAULT now());

CREATE TABLE IF NOT EXISTS public.medication_reference (id uuid NOT NULL DEFAULT gen_random_uuid(), name text NOT NULL, category text NOT NULL, common_dose double precision, dose_unit text DEFAULT 'mg'::text, typical_onset_hours integer, typical_duration_hours integer, common_side_effects text[], notes text, created_at timestamp without time zone DEFAULT now(), purpose text, conditions_treated text, dosage_range text, discontinuation_notes text, common_doses_list jsonb);

CREATE TABLE IF NOT EXISTS public.medication_sms_logs (id uuid NOT NULL DEFAULT gen_random_uuid(), patient_id uuid NOT NULL, medication_name text NOT NULL, scheduled_time time without time zone NOT NULL, sent_at timestamp with time zone NOT NULL DEFAULT now(), replied_at timestamp with time zone, taken boolean, raw_reply text, phone_number text);

CREATE TABLE IF NOT EXISTS public.medications (id uuid NOT NULL DEFAULT gen_random_uuid(), user_id uuid NOT NULL, name text NOT NULL, category text, standard_dose double precision, dose_unit text DEFAULT 'mg'::text, scheduled_times text[] DEFAULT ARRAY[]::text[], is_as_needed boolean DEFAULT false, date_started date, date_discontinued date, is_active boolean DEFAULT true, notes text, created_at timestamp without time zone DEFAULT now(), updated_at timestamp without time zone DEFAULT now(), frequency text);

CREATE TABLE IF NOT EXISTS public.patient_consents (id uuid NOT NULL DEFAULT gen_random_uuid(), patient_id uuid NOT NULL, data_source text NOT NULL, granted boolean NOT NULL DEFAULT false, granted_at timestamp with time zone, revoked_at timestamp with time zone, consent_version text, ip_address text, created_at timestamp with time zone DEFAULT now());

CREATE TABLE IF NOT EXISTS public.patient_invites (id uuid NOT NULL DEFAULT gen_random_uuid(), token text NOT NULL DEFAULT encode(gen_random_bytes(32), 'hex'::text), provider_id uuid NOT NULL, patient_email text NOT NULL, role text NOT NULL DEFAULT 'psychiatrist'::text, message text, status text NOT NULL DEFAULT 'pending'::text, created_at timestamp with time zone NOT NULL DEFAULT now(), expires_at timestamp with time zone NOT NULL DEFAULT (now() + '7 days'::interval));

CREATE TABLE IF NOT EXISTS public.patient_profiles (id uuid NOT NULL DEFAULT gen_random_uuid(), user_id uuid NOT NULL, provider_id uuid, medications text, created_at timestamp without time zone DEFAULT now(), current_medications jsonb DEFAULT '[]'::jsonb, crisis_resolved_at timestamp with time zone, checkin_reminders_enabled boolean NOT NULL DEFAULT true, last_reminder_sent_at timestamp with time zone, adherence_alert boolean NOT NULL DEFAULT false, phone_number text, sms_consent boolean NOT NULL DEFAULT false, sms_consent_at timestamp with time zone);

CREATE TABLE IF NOT EXISTS public.patient_session_summaries (id uuid NOT NULL DEFAULT gen_random_uuid(), patient_id uuid NOT NULL, session_id uuid NOT NULL, content text NOT NULL, model_version text, generated_at timestamp with time zone DEFAULT now());

CREATE TABLE IF NOT EXISTS public.pharmacy_fills (id uuid NOT NULL DEFAULT gen_random_uuid(), patient_id uuid NOT NULL, medication_id uuid, medication_name text, fill_date date NOT NULL, days_supply integer, quantity_dispensed numeric(8,2), pharmacy_name text, ndc text, source text DEFAULT 'manual'::text, fhir_resource_id text, created_at timestamp with time zone DEFAULT now());

CREATE TABLE IF NOT EXISTS public.proactive_insights (id uuid NOT NULL DEFAULT gen_random_uuid(), patient_id uuid NOT NULL, pattern_type text NOT NULL, insight_text text NOT NULL, supporting_data jsonb, created_at timestamp with time zone NOT NULL DEFAULT now(), seen_at timestamp with time zone, dismissed_at timestamp with time zone);

CREATE TABLE IF NOT EXISTS public.profiles (id uuid NOT NULL, email text NOT NULL, full_name text, role text DEFAULT 'patient'::text, created_at timestamp without time zone DEFAULT now(), updated_at timestamp without time zone DEFAULT now(), email_verify_token text, status text DEFAULT 'pending_email'::text, provider_type text DEFAULT 'psychiatrist'::text, phone_number text);

CREATE TABLE IF NOT EXISTS public.provider_appointments (id uuid NOT NULL DEFAULT gen_random_uuid(), provider_id uuid NOT NULL, patient_id uuid NOT NULL, status text NOT NULL DEFAULT 'active'::text, period_days integer NOT NULL DEFAULT 30, started_at timestamp with time zone NOT NULL DEFAULT now(), completed_at timestamp with time zone, guided_qa jsonb NOT NULL DEFAULT '[]'::jsonb, notes text NOT NULL DEFAULT ''::text, care_plan_changes text NOT NULL DEFAULT ''::text, actions jsonb NOT NULL DEFAULT '[]'::jsonb, next_appointment_date date, next_appointment_notes text NOT NULL DEFAULT ''::text, created_at timestamp with time zone NOT NULL DEFAULT now(), updated_at timestamp with time zone NOT NULL DEFAULT now(), next_appointment_time text, appointment_type text);

CREATE TABLE IF NOT EXISTS public.provider_brief_views (id uuid NOT NULL DEFAULT gen_random_uuid(), brief_id uuid NOT NULL, provider_id uuid NOT NULL, viewed_at timestamp with time zone DEFAULT now());

CREATE TABLE IF NOT EXISTS public.provider_briefs (id uuid NOT NULL DEFAULT gen_random_uuid(), patient_id uuid NOT NULL, provider_id uuid NOT NULL, brief_type text NOT NULL DEFAULT 'pre_visit'::text, for_session_id uuid, period_start date, period_end date, content text NOT NULL, data_sources jsonb, scores jsonb, crisis_detected boolean NOT NULL DEFAULT false, session_count integer DEFAULT 0, model_version text, generated_at timestamp with time zone DEFAULT now());

CREATE TABLE IF NOT EXISTS public.provider_focus_configs (id uuid NOT NULL DEFAULT gen_random_uuid(), provider_id uuid NOT NULL, patient_id uuid NOT NULL, focus_domains jsonb NOT NULL DEFAULT '[]'::jsonb, notes text, set_by_role text, created_at timestamp with time zone NOT NULL DEFAULT now(), expires_at timestamp with time zone NOT NULL);

CREATE TABLE IF NOT EXISTS public.session_features (id uuid NOT NULL DEFAULT gen_random_uuid(), session_id uuid NOT NULL, patient_id uuid NOT NULL, extracted jsonb NOT NULL DEFAULT '{}'::jsonb, scores jsonb NOT NULL DEFAULT '{}'::jsonb, crisis_detected boolean NOT NULL DEFAULT false, safety_flags jsonb DEFAULT '{}'::jsonb, extraction_model text, created_at timestamp with time zone DEFAULT now());

CREATE TABLE IF NOT EXISTS public.side_effects (id uuid NOT NULL DEFAULT gen_random_uuid(), user_id uuid NOT NULL, medication_id uuid, symptom text NOT NULL, severity integer, onset_date date, onset_time timestamp without time zone, notes text, created_at timestamp without time zone DEFAULT now());

CREATE TABLE IF NOT EXISTS public.sms_checkin_sessions (id uuid NOT NULL DEFAULT gen_random_uuid(), patient_id uuid NOT NULL, session_type text NOT NULL, sent_at timestamp with time zone NOT NULL DEFAULT now(), resolved_at timestamp with time zone, suspended_session_type text, metadata jsonb NOT NULL DEFAULT '{}'::jsonb);

CREATE TABLE IF NOT EXISTS public.sms_crisis_events (id uuid NOT NULL DEFAULT gen_random_uuid(), patient_id uuid NOT NULL, source text NOT NULL, triggered_at timestamp with time zone NOT NULL DEFAULT now(), provider_notified_at timestamp with time zone, provider_sms_sid text);

CREATE TABLE IF NOT EXISTS public.sms_tokens (id uuid NOT NULL DEFAULT gen_random_uuid(), token text NOT NULL, patient_id uuid NOT NULL, flow_type text NOT NULL, metadata jsonb NOT NULL DEFAULT '{}'::jsonb, expires_at timestamp with time zone NOT NULL, used_at timestamp with time zone, created_at timestamp with time zone NOT NULL DEFAULT now());

CREATE TABLE IF NOT EXISTS public.summaries (id uuid NOT NULL DEFAULT gen_random_uuid(), user_id uuid NOT NULL, summary_date date NOT NULL, content text, created_at timestamp without time zone DEFAULT now());

CREATE TABLE IF NOT EXISTS public.user_hypotheses (id uuid NOT NULL DEFAULT gen_random_uuid(), user_id uuid NOT NULL, hypothesis text, tested_at timestamp without time zone DEFAULT now(), result text, created_at timestamp without time zone DEFAULT now());

CREATE TABLE IF NOT EXISTS public.voice_baselines (id uuid NOT NULL DEFAULT gen_random_uuid(), patient_id uuid NOT NULL, status text NOT NULL DEFAULT 'establishing'::text, anchor_session_id uuid, anchor_recorded_at timestamp with time zone, anchor_stability_score numeric, anchor_state_verified boolean NOT NULL DEFAULT false, training_recordings_count integer NOT NULL DEFAULT 0, training_span_days integer, last_baseline_at timestamp with time zone, articulation_rate_mean numeric, articulation_rate_sd numeric, f0_cv_mean numeric, f0_cv_sd numeric, pause_ratio_mean numeric, pause_ratio_sd numeric, f0_mean_hz_mean numeric, f0_mean_hz_sd numeric, rms_mean_mean numeric, rms_mean_sd numeric, rms_cv_mean numeric, rms_cv_sd numeric, hnr_db_mean numeric, hnr_db_sd numeric, jitter_local_mean numeric, jitter_local_sd numeric, shimmer_local_mean numeric, shimmer_local_sd numeric, stale_reason text, stale_flagged_at timestamp with time zone, stale_medication_event_id uuid, created_at timestamp with time zone NOT NULL DEFAULT now(), updated_at timestamp with time zone NOT NULL DEFAULT now());

CREATE TABLE IF NOT EXISTS public.voice_memos (id uuid NOT NULL DEFAULT gen_random_uuid(), patient_id uuid NOT NULL, recorded_at date NOT NULL, week_of date, audio_url text, transcript text, acoustic_features jsonb, processing_status text DEFAULT 'pending'::text, created_at timestamp with time zone DEFAULT now());

CREATE TABLE IF NOT EXISTS public.voice_notes (id uuid NOT NULL DEFAULT gen_random_uuid(), patient_id uuid NOT NULL, appointment_id uuid, provider_id uuid, token_id uuid, guiding_question text, audio_url text, transcript text, processing_status text NOT NULL DEFAULT 'pending'::text, processing_error text, created_at timestamp with time zone NOT NULL DEFAULT now(), clinical_session_id uuid);

CREATE TABLE IF NOT EXISTS public.wearable_snapshots (id uuid NOT NULL DEFAULT gen_random_uuid(), patient_id uuid NOT NULL, snapshot_date date NOT NULL, source text NOT NULL DEFAULT 'apple_health'::text, sleep_hours numeric(4,1), sleep_stages jsonb, hrv_ms numeric(6,1), resting_hr integer, active_minutes integer, steps integer, raw_data jsonb, created_at timestamp with time zone DEFAULT now());

CREATE TABLE IF NOT EXISTS public.appointments (id uuid NOT NULL DEFAULT gen_random_uuid(), patient_id uuid NOT NULL, provider_id uuid NOT NULL, scheduled_at timestamp with time zone NOT NULL, checkin_triggered boolean NOT NULL DEFAULT false, notes text, created_at timestamp with time zone NOT NULL DEFAULT now(), updated_at timestamp with time zone NOT NULL DEFAULT now());

CREATE OR REPLACE FUNCTION public.rls_auto_enable()
 RETURNS event_trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog'
AS $function$
DECLARE
  cmd record;
BEGIN
  FOR cmd IN
    SELECT *
    FROM pg_event_trigger_ddl_commands()
    WHERE command_tag IN ('CREATE TABLE', 'CREATE TABLE AS', 'SELECT INTO')
      AND object_type IN ('table','partitioned table')
  LOOP
     IF cmd.schema_name IS NOT NULL AND cmd.schema_name IN ('public') AND cmd.schema_name NOT IN ('pg_catalog','information_schema') AND cmd.schema_name NOT LIKE 'pg_toast%' AND cmd.schema_name NOT LIKE 'pg_temp%' THEN
      BEGIN
        EXECUTE format('alter table if exists %s enable row level security', cmd.object_identity);
        RAISE LOG 'rls_auto_enable: enabled RLS on %', cmd.object_identity;
      EXCEPTION
        WHEN OTHERS THEN
          RAISE LOG 'rls_auto_enable: failed to enable RLS on %', cmd.object_identity;
      END;
     ELSE
        RAISE LOG 'rls_auto_enable: skip % (either system schema or not in enforced list: %.)', cmd.object_identity, cmd.schema_name;
     END IF;
  END LOOP;
END;
$function$
;

CREATE OR REPLACE FUNCTION public.update_voice_baselines_updated_at()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$function$
;

CREATE OR REPLACE FUNCTION public.can_access_patient(p_patient uuid)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
  select
    auth.uid() = p_patient
    or exists (
      select 1
      from public.care_team_members ctm
      where ctm.patient_id  = p_patient
        and ctm.provider_id = auth.uid()
        and ctm.status      = 'active'
        and ctm.revoked_at is null
    );
$function$
;

ALTER TABLE public.care_flag_responses ADD CONSTRAINT care_flag_responses_pkey PRIMARY KEY (id);

ALTER TABLE public.care_flags ADD CONSTRAINT care_flags_pkey PRIMARY KEY (id);

ALTER TABLE public.care_team_members ADD CONSTRAINT care_team_members_pkey PRIMARY KEY (id);

ALTER TABLE public.checkin_schedules ADD CONSTRAINT checkin_schedules_pkey PRIMARY KEY (patient_id);

ALTER TABLE public.checkin_tokens ADD CONSTRAINT checkin_tokens_pkey PRIMARY KEY (id);

ALTER TABLE public.checkins ADD CONSTRAINT checkins_pkey PRIMARY KEY (id);

ALTER TABLE public.clinical_sessions ADD CONSTRAINT clinical_sessions_pkey PRIMARY KEY (id);

ALTER TABLE public.daily_sms_sends ADD CONSTRAINT daily_sms_sends_pkey PRIMARY KEY (id);

ALTER TABLE public.journal_entries ADD CONSTRAINT journal_entries_pkey PRIMARY KEY (id);

ALTER TABLE public.medication_events ADD CONSTRAINT medication_events_pkey PRIMARY KEY (id);

ALTER TABLE public.medication_records ADD CONSTRAINT medication_records_pkey PRIMARY KEY (id);

ALTER TABLE public.medication_reference ADD CONSTRAINT medication_reference_pkey PRIMARY KEY (id);

ALTER TABLE public.medication_sms_logs ADD CONSTRAINT medication_sms_logs_pkey PRIMARY KEY (id);

ALTER TABLE public.medications ADD CONSTRAINT medications_pkey PRIMARY KEY (id);

ALTER TABLE public.patient_consents ADD CONSTRAINT patient_consents_pkey PRIMARY KEY (id);

ALTER TABLE public.patient_invites ADD CONSTRAINT patient_invites_pkey PRIMARY KEY (id);

ALTER TABLE public.patient_profiles ADD CONSTRAINT patient_profiles_pkey PRIMARY KEY (id);

ALTER TABLE public.patient_session_summaries ADD CONSTRAINT patient_session_summaries_pkey PRIMARY KEY (id);

ALTER TABLE public.pharmacy_fills ADD CONSTRAINT pharmacy_fills_pkey PRIMARY KEY (id);

ALTER TABLE public.proactive_insights ADD CONSTRAINT proactive_insights_pkey PRIMARY KEY (id);

ALTER TABLE public.profiles ADD CONSTRAINT profiles_pkey PRIMARY KEY (id);

ALTER TABLE public.provider_appointments ADD CONSTRAINT provider_appointments_pkey PRIMARY KEY (id);

ALTER TABLE public.provider_brief_views ADD CONSTRAINT provider_brief_views_pkey PRIMARY KEY (id);

ALTER TABLE public.provider_briefs ADD CONSTRAINT provider_briefs_pkey PRIMARY KEY (id);

ALTER TABLE public.provider_focus_configs ADD CONSTRAINT provider_focus_configs_pkey PRIMARY KEY (id);

ALTER TABLE public.session_features ADD CONSTRAINT session_features_pkey PRIMARY KEY (id);

ALTER TABLE public.side_effects ADD CONSTRAINT side_effects_pkey PRIMARY KEY (id);

ALTER TABLE public.sms_checkin_sessions ADD CONSTRAINT sms_checkin_sessions_pkey PRIMARY KEY (id);

ALTER TABLE public.sms_crisis_events ADD CONSTRAINT sms_crisis_events_pkey PRIMARY KEY (id);

ALTER TABLE public.sms_tokens ADD CONSTRAINT sms_tokens_pkey PRIMARY KEY (id);

ALTER TABLE public.summaries ADD CONSTRAINT summaries_pkey PRIMARY KEY (id);

ALTER TABLE public.user_hypotheses ADD CONSTRAINT user_hypotheses_pkey PRIMARY KEY (id);

ALTER TABLE public.voice_baselines ADD CONSTRAINT voice_baselines_pkey PRIMARY KEY (id);

ALTER TABLE public.voice_memos ADD CONSTRAINT voice_memos_pkey PRIMARY KEY (id);

ALTER TABLE public.voice_notes ADD CONSTRAINT voice_notes_pkey PRIMARY KEY (id);

ALTER TABLE public.wearable_snapshots ADD CONSTRAINT wearable_snapshots_pkey PRIMARY KEY (id);

ALTER TABLE public.care_team_members ADD CONSTRAINT care_team_members_patient_id_provider_id_key UNIQUE (patient_id, provider_id);

ALTER TABLE public.checkin_tokens ADD CONSTRAINT checkin_tokens_token_key UNIQUE (token);

ALTER TABLE public.daily_sms_sends ADD CONSTRAINT daily_sms_sends_patient_id_send_type_send_date_key UNIQUE (patient_id, send_type, send_date);

ALTER TABLE public.medication_reference ADD CONSTRAINT medication_reference_name_key UNIQUE (name);

ALTER TABLE public.patient_consents ADD CONSTRAINT patient_consents_patient_id_data_source_key UNIQUE (patient_id, data_source);

ALTER TABLE public.patient_invites ADD CONSTRAINT patient_invites_token_key UNIQUE (token);

ALTER TABLE public.patient_profiles ADD CONSTRAINT patient_profiles_user_id_unique UNIQUE (user_id);

ALTER TABLE public.pharmacy_fills ADD CONSTRAINT pharmacy_fills_patient_id_medication_name_fill_date_source_key UNIQUE (patient_id, medication_name, fill_date, source);

ALTER TABLE public.profiles ADD CONSTRAINT profiles_email_key UNIQUE (email);

ALTER TABLE public.provider_focus_configs ADD CONSTRAINT provider_focus_configs_provider_id_patient_id_key UNIQUE (provider_id, patient_id);

ALTER TABLE public.session_features ADD CONSTRAINT session_features_session_id_key UNIQUE (session_id);

ALTER TABLE public.sms_tokens ADD CONSTRAINT sms_tokens_token_key UNIQUE (token);

ALTER TABLE public.voice_memos ADD CONSTRAINT voice_memos_patient_id_week_of_key UNIQUE (patient_id, week_of);

ALTER TABLE public.wearable_snapshots ADD CONSTRAINT wearable_snapshots_patient_id_snapshot_date_source_key UNIQUE (patient_id, snapshot_date, source);

ALTER TABLE public.care_flag_responses ADD CONSTRAINT chk_response_length CHECK (((char_length(body) >= 5) AND (char_length(body) <= 500)));

ALTER TABLE public.care_flags ADD CONSTRAINT care_flags_body_check CHECK (((char_length(body) >= 10) AND (char_length(body) <= 1000)));

ALTER TABLE public.care_flags ADD CONSTRAINT care_flags_flag_type_check CHECK ((flag_type = ANY (ARRAY['observation'::text, 'concern'::text, 'progress'::text, 'coordination_needed'::text])));

ALTER TABLE public.care_flags ADD CONSTRAINT care_flags_visibility_check CHECK ((visibility = 'care_team'::text));

ALTER TABLE public.care_team_members ADD CONSTRAINT care_team_members_requested_by_check CHECK ((requested_by = ANY (ARRAY['patient'::text, 'provider'::text])));

ALTER TABLE public.care_team_members ADD CONSTRAINT care_team_members_role_check CHECK ((role = ANY (ARRAY['psychiatrist'::text, 'therapist'::text, 'counselor'::text, 'coach'::text, 'sleep_specialist'::text, 'other'::text])));

ALTER TABLE public.care_team_members ADD CONSTRAINT care_team_members_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'active'::text, 'revoked'::text])));

ALTER TABLE public.checkins ADD CONSTRAINT checkins_check_in_type_check CHECK ((check_in_type = ANY (ARRAY['micro'::text, 'short'::text, 'full'::text])));

ALTER TABLE public.checkins ADD CONSTRAINT checkins_follow_up_type_check CHECK ((follow_up_type = ANY (ARRAY['mood'::text, 'stress'::text, 'sleep'::text, 'energy'::text, NULL::text])));

ALTER TABLE public.checkins ADD CONSTRAINT checkins_source_check CHECK ((source = ANY (ARRAY['sms'::text, 'web'::text, 'manual'::text])));

ALTER TABLE public.clinical_sessions ADD CONSTRAINT clinical_sessions_session_type_check CHECK ((session_type = ANY (ARRAY['psychiatry'::text, 'therapy'::text, 'intake'::text, 'followup'::text, 'group'::text, 'other'::text, 'voice_note'::text])));

ALTER TABLE public.clinical_sessions ADD CONSTRAINT clinical_sessions_voice_recording_role_check CHECK ((voice_recording_role = ANY (ARRAY['clinical_session'::text, 'voice_memo_anchor'::text, 'voice_memo_baseline'::text, 'voice_memo_standard'::text, 'voice_memo_excluded'::text])));

ALTER TABLE public.daily_sms_sends ADD CONSTRAINT daily_sms_sends_send_type_check CHECK ((send_type = ANY (ARRAY['medication'::text, 'checkin'::text, 'voice'::text])));

ALTER TABLE public.medication_events ADD CONSTRAINT medication_events_status_check CHECK ((status = ANY (ARRAY['TAKEN'::text, 'SKIPPED'::text, 'MISSED'::text])));

ALTER TABLE public.medications ADD CONSTRAINT medications_category_check CHECK ((category = ANY (ARRAY['STIMULANT'::text, 'ANTIDEPRESSANT'::text, 'MOOD_STABILIZER'::text, 'ANTIPSYCHOTIC'::text, 'ANXIOLYTIC'::text, 'SLEEP'::text, 'OTHER'::text])));

ALTER TABLE public.profiles ADD CONSTRAINT profiles_provider_type_check CHECK ((provider_type = ANY (ARRAY['psychiatrist'::text, 'therapist'::text, 'counselor'::text, 'coach'::text, 'sleep_specialist'::text, 'other'::text])));

ALTER TABLE public.profiles ADD CONSTRAINT profiles_role_check CHECK ((role = ANY (ARRAY['patient'::text, 'provider'::text])));

ALTER TABLE public.provider_appointments ADD CONSTRAINT provider_appointments_status_check CHECK ((status = ANY (ARRAY['active'::text, 'completed'::text, 'cancelled'::text])));

ALTER TABLE public.side_effects ADD CONSTRAINT side_effects_severity_check CHECK (((severity >= 1) AND (severity <= 5)));

ALTER TABLE public.sms_checkin_sessions ADD CONSTRAINT sms_checkin_sessions_session_type_check CHECK ((session_type = ANY (ARRAY['checkin_pending'::text, 'med_pending'::text, 'help_pending'::text, 'rotating_pending'::text])));

ALTER TABLE public.sms_checkin_sessions ADD CONSTRAINT sms_checkin_sessions_suspended_session_type_check CHECK ((suspended_session_type = ANY (ARRAY['checkin_pending'::text, 'med_pending'::text])));

ALTER TABLE public.sms_crisis_events ADD CONSTRAINT sms_crisis_events_source_check CHECK ((source = ANY (ARRAY['keyword'::text, 'help_branch'::text, 'checkin'::text, 'voice'::text])));

ALTER TABLE public.sms_tokens ADD CONSTRAINT sms_tokens_flow_type_check CHECK ((flow_type = ANY (ARRAY['medication'::text, 'short'::text, 'full'::text, 'voice'::text, 'briefing'::text])));

ALTER TABLE public.voice_baselines ADD CONSTRAINT voice_baselines_stale_reason_check CHECK ((stale_reason = ANY (ARRAY['medication_change'::text, 'time_elapsed'::text, 'manual_reset'::text])));

ALTER TABLE public.voice_baselines ADD CONSTRAINT voice_baselines_status_check CHECK ((status = ANY (ARRAY['establishing'::text, 'established'::text, 'stale'::text])));

ALTER TABLE public.appointments ADD CONSTRAINT appointments_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES auth.users(id) ON DELETE CASCADE;

ALTER TABLE public.appointments ADD CONSTRAINT appointments_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES auth.users(id) ON DELETE CASCADE;

ALTER TABLE public.care_flag_responses ADD CONSTRAINT care_flag_responses_flag_id_fkey FOREIGN KEY (flag_id) REFERENCES care_flags(id) ON DELETE CASCADE;

ALTER TABLE public.care_flags ADD CONSTRAINT care_flags_author_provider_id_fkey FOREIGN KEY (author_provider_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.care_flags ADD CONSTRAINT care_flags_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.care_flags ADD CONSTRAINT care_flags_resolved_by_fkey FOREIGN KEY (resolved_by) REFERENCES profiles(id) ON DELETE SET NULL;

ALTER TABLE public.care_team_members ADD CONSTRAINT care_team_members_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.care_team_members ADD CONSTRAINT care_team_members_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.checkin_schedules ADD CONSTRAINT checkin_schedules_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES auth.users(id) ON DELETE CASCADE;

ALTER TABLE public.checkin_tokens ADD CONSTRAINT checkin_tokens_appointment_id_fkey FOREIGN KEY (appointment_id) REFERENCES provider_appointments(id) ON DELETE SET NULL;

ALTER TABLE public.checkin_tokens ADD CONSTRAINT checkin_tokens_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.checkin_tokens ADD CONSTRAINT checkin_tokens_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES profiles(id) ON DELETE SET NULL;

ALTER TABLE public.checkins ADD CONSTRAINT checkins_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.clinical_sessions ADD CONSTRAINT clinical_sessions_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.clinical_sessions ADD CONSTRAINT clinical_sessions_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES profiles(id);

ALTER TABLE public.journal_entries ADD CONSTRAINT journal_entries_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.medication_events ADD CONSTRAINT medication_events_medication_id_fkey FOREIGN KEY (medication_id) REFERENCES medications(id) ON DELETE CASCADE;

ALTER TABLE public.medication_events ADD CONSTRAINT medication_events_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.medication_records ADD CONSTRAINT medication_records_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.medication_records ADD CONSTRAINT medication_records_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES profiles(id);

ALTER TABLE public.medication_sms_logs ADD CONSTRAINT medication_sms_logs_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.medications ADD CONSTRAINT medications_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.patient_consents ADD CONSTRAINT patient_consents_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.patient_invites ADD CONSTRAINT patient_invites_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.patient_profiles ADD CONSTRAINT patient_profiles_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES profiles(id) ON DELETE SET NULL;

ALTER TABLE public.patient_profiles ADD CONSTRAINT patient_profiles_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.patient_session_summaries ADD CONSTRAINT patient_session_summaries_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.patient_session_summaries ADD CONSTRAINT patient_session_summaries_session_id_fkey FOREIGN KEY (session_id) REFERENCES clinical_sessions(id) ON DELETE CASCADE;

ALTER TABLE public.pharmacy_fills ADD CONSTRAINT pharmacy_fills_medication_id_fkey FOREIGN KEY (medication_id) REFERENCES medication_records(id);

ALTER TABLE public.pharmacy_fills ADD CONSTRAINT pharmacy_fills_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.proactive_insights ADD CONSTRAINT proactive_insights_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.profiles ADD CONSTRAINT profiles_id_fkey FOREIGN KEY (id) REFERENCES auth.users(id) ON DELETE CASCADE;

ALTER TABLE public.provider_brief_views ADD CONSTRAINT provider_brief_views_brief_id_fkey FOREIGN KEY (brief_id) REFERENCES provider_briefs(id) ON DELETE CASCADE;

ALTER TABLE public.provider_brief_views ADD CONSTRAINT provider_brief_views_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES profiles(id);

ALTER TABLE public.provider_briefs ADD CONSTRAINT provider_briefs_for_session_id_fkey FOREIGN KEY (for_session_id) REFERENCES clinical_sessions(id);

ALTER TABLE public.provider_briefs ADD CONSTRAINT provider_briefs_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.provider_briefs ADD CONSTRAINT provider_briefs_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES profiles(id);

ALTER TABLE public.provider_focus_configs ADD CONSTRAINT provider_focus_configs_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.provider_focus_configs ADD CONSTRAINT provider_focus_configs_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.session_features ADD CONSTRAINT session_features_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.session_features ADD CONSTRAINT session_features_session_id_fkey FOREIGN KEY (session_id) REFERENCES clinical_sessions(id) ON DELETE CASCADE;

ALTER TABLE public.side_effects ADD CONSTRAINT side_effects_medication_id_fkey FOREIGN KEY (medication_id) REFERENCES medications(id) ON DELETE SET NULL;

ALTER TABLE public.side_effects ADD CONSTRAINT side_effects_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.sms_checkin_sessions ADD CONSTRAINT sms_checkin_sessions_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.sms_crisis_events ADD CONSTRAINT sms_crisis_events_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.sms_tokens ADD CONSTRAINT sms_tokens_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES auth.users(id) ON DELETE CASCADE;

ALTER TABLE public.summaries ADD CONSTRAINT summaries_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.user_hypotheses ADD CONSTRAINT user_hypotheses_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.voice_baselines ADD CONSTRAINT voice_baselines_anchor_session_id_fkey FOREIGN KEY (anchor_session_id) REFERENCES clinical_sessions(id) ON DELETE SET NULL;

ALTER TABLE public.voice_baselines ADD CONSTRAINT voice_baselines_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES patient_profiles(id) ON DELETE CASCADE;

ALTER TABLE public.voice_memos ADD CONSTRAINT voice_memos_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.voice_notes ADD CONSTRAINT voice_notes_appointment_id_fkey FOREIGN KEY (appointment_id) REFERENCES provider_appointments(id) ON DELETE SET NULL;

ALTER TABLE public.voice_notes ADD CONSTRAINT voice_notes_clinical_session_id_fkey FOREIGN KEY (clinical_session_id) REFERENCES clinical_sessions(id);

ALTER TABLE public.voice_notes ADD CONSTRAINT voice_notes_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.voice_notes ADD CONSTRAINT voice_notes_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES profiles(id) ON DELETE SET NULL;

ALTER TABLE public.voice_notes ADD CONSTRAINT voice_notes_token_id_fkey FOREIGN KEY (token_id) REFERENCES checkin_tokens(id) ON DELETE SET NULL;

ALTER TABLE public.wearable_snapshots ADD CONSTRAINT wearable_snapshots_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE public.appointments ADD CONSTRAINT appointments_pkey PRIMARY KEY (id);

CREATE INDEX appointments_provider_idx ON public.appointments USING btree (provider_id);

CREATE INDEX appointments_scheduled_idx ON public.appointments USING btree (scheduled_at);

CREATE INDEX appointments_triggered_idx ON public.appointments USING btree (checkin_triggered);

CREATE INDEX idx_flag_responses_flag_id ON public.care_flag_responses USING btree (flag_id);

CREATE INDEX idx_flag_responses_patient_id ON public.care_flag_responses USING btree (patient_id);

CREATE INDEX idx_care_flags_author ON public.care_flags USING btree (author_provider_id, patient_id);

CREATE INDEX idx_care_flags_patient ON public.care_flags USING btree (patient_id, resolved_at);

CREATE INDEX idx_care_team_patient_id ON public.care_team_members USING btree (patient_id);

CREATE INDEX idx_care_team_provider_id ON public.care_team_members USING btree (provider_id);

CREATE INDEX idx_care_team_status ON public.care_team_members USING btree (status);

CREATE INDEX checkin_tokens_patient_idx ON public.checkin_tokens USING btree (patient_id);

CREATE INDEX checkin_tokens_token_idx ON public.checkin_tokens USING btree (token);

CREATE INDEX idx_checkin_tokens_patient ON public.checkin_tokens USING btree (patient_id);

CREATE INDEX idx_checkin_tokens_token ON public.checkin_tokens USING btree (token);

CREATE INDEX checkins_check_in_type_idx ON public.checkins USING btree (check_in_type);

CREATE INDEX checkins_flags_idx ON public.checkins USING gin (flags);

CREATE INDEX checkins_source_idx ON public.checkins USING btree (source);

CREATE INDEX idx_checkins_user_date ON public.checkins USING btree (user_id, checkin_date DESC);

CREATE INDEX idx_clinical_sessions_patient_date ON public.clinical_sessions USING btree (patient_id, session_date DESC);

CREATE INDEX idx_clinical_sessions_pending ON public.clinical_sessions USING btree (processing_status, created_at) WHERE (processing_status = 'pending'::text);

CREATE INDEX idx_clinical_sessions_provider ON public.clinical_sessions USING btree (provider_id, session_date DESC);

CREATE INDEX idx_medication_records_patient_active ON public.medication_records USING btree (patient_id, active, created_at DESC);

CREATE INDEX idx_med_sms_patient ON public.medication_sms_logs USING btree (patient_id);

CREATE INDEX medication_sms_logs_patient_idx ON public.medication_sms_logs USING btree (patient_id);

CREATE INDEX patient_invites_email_status ON public.patient_invites USING btree (patient_email, status);

CREATE INDEX patient_invites_provider ON public.patient_invites USING btree (provider_id);

CREATE INDEX patient_invites_token ON public.patient_invites USING btree (token);

CREATE INDEX idx_pharmacy_fills_patient_med ON public.pharmacy_fills USING btree (patient_id, medication_name, fill_date DESC);

CREATE INDEX idx_proactive_insights_patient ON public.proactive_insights USING btree (patient_id);

CREATE INDEX idx_proactive_insights_recent ON public.proactive_insights USING btree (patient_id, created_at DESC);

CREATE INDEX idx_prov_appts_patient ON public.provider_appointments USING btree (patient_id);

CREATE INDEX idx_prov_appts_provider ON public.provider_appointments USING btree (provider_id);

CREATE INDEX idx_prov_appts_started ON public.provider_appointments USING btree (started_at DESC);

CREATE INDEX idx_provider_briefs_patient ON public.provider_briefs USING btree (patient_id, generated_at DESC);

CREATE INDEX idx_provider_briefs_provider ON public.provider_briefs USING btree (provider_id, generated_at DESC);

CREATE INDEX idx_session_features_patient ON public.session_features USING btree (patient_id, created_at DESC);

CREATE INDEX idx_session_features_patient_date ON public.session_features USING btree (patient_id, created_at DESC);

CREATE INDEX idx_sms_sessions_patient ON public.sms_checkin_sessions USING btree (patient_id, resolved_at);

CREATE INDEX idx_sms_crisis_patient ON public.sms_crisis_events USING btree (patient_id, triggered_at DESC);

CREATE INDEX sms_tokens_expires_idx ON public.sms_tokens USING btree (expires_at);

CREATE INDEX sms_tokens_patient_idx ON public.sms_tokens USING btree (patient_id);

CREATE INDEX sms_tokens_token_idx ON public.sms_tokens USING btree (token);

CREATE UNIQUE INDEX voice_baselines_one_active_per_patient ON public.voice_baselines USING btree (patient_id) WHERE (status = ANY (ARRAY['establishing'::text, 'established'::text, 'stale'::text]));

CREATE INDEX voice_baselines_patient_id_idx ON public.voice_baselines USING btree (patient_id);

CREATE INDEX voice_baselines_status_idx ON public.voice_baselines USING btree (status);

CREATE INDEX idx_voice_memos_patient_week ON public.voice_memos USING btree (patient_id, week_of DESC);

CREATE INDEX idx_voice_notes_patient ON public.voice_notes USING btree (patient_id);

CREATE INDEX voice_notes_appointment_idx ON public.voice_notes USING btree (appointment_id);

CREATE INDEX voice_notes_patient_idx ON public.voice_notes USING btree (patient_id);

CREATE INDEX idx_wearable_snapshots_patient_date ON public.wearable_snapshots USING btree (patient_id, snapshot_date DESC);

CREATE INDEX appointments_patient_idx ON public.appointments USING btree (patient_id);

CREATE TRIGGER voice_baselines_updated_at BEFORE UPDATE ON public.voice_baselines FOR EACH ROW EXECUTE FUNCTION update_voice_baselines_updated_at();

ALTER TABLE public.care_flag_responses ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.care_flags ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.care_team_members ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.checkin_schedules ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.checkin_tokens ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.checkins ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.clinical_sessions ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.daily_sms_sends ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.journal_entries ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.medication_events ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.medication_records ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.medication_reference ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.medication_sms_logs ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.medications ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.patient_consents ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.patient_invites ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.patient_profiles ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.patient_session_summaries ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.pharmacy_fills ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.proactive_insights ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.provider_appointments ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.provider_brief_views ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.provider_briefs ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.provider_focus_configs ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.session_features ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.side_effects ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.sms_checkin_sessions ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.sms_crisis_events ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.sms_tokens ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.summaries ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.user_hypotheses ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.voice_baselines ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.voice_memos ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.voice_notes ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.wearable_snapshots ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.appointments ENABLE ROW LEVEL SECURITY;

CREATE POLICY providers_own_appointments ON public.appointments AS PERMISSIVE FOR ALL TO public USING ((provider_id = auth.uid()));

CREATE POLICY care_flag_responses_select_own ON public.care_flag_responses AS PERMISSIVE FOR SELECT TO authenticated USING (can_access_patient(patient_id));

CREATE POLICY care_flags_select_own ON public.care_flags AS PERMISSIVE FOR SELECT TO authenticated USING (can_access_patient(patient_id));

CREATE POLICY care_team_members_select_own ON public.care_team_members AS PERMISSIVE FOR SELECT TO authenticated USING (((patient_id = auth.uid()) OR (provider_id = auth.uid())));

CREATE POLICY patients_own_schedule ON public.checkin_schedules AS PERMISSIVE FOR SELECT TO public USING ((patient_id = auth.uid()));

CREATE POLICY "Users can insert own checkins" ON public.checkins AS PERMISSIVE FOR INSERT TO public WITH CHECK ((auth.uid() = user_id));

CREATE POLICY "Users can update own checkins" ON public.checkins AS PERMISSIVE FOR UPDATE TO public USING ((auth.uid() = user_id));

CREATE POLICY "Users can view own checkins" ON public.checkins AS PERMISSIVE FOR SELECT TO public USING ((auth.uid() = user_id));

CREATE POLICY clinical_sessions_select_own ON public.clinical_sessions AS PERMISSIVE FOR SELECT TO authenticated USING (can_access_patient(patient_id));

CREATE POLICY "Users can insert own journals" ON public.journal_entries AS PERMISSIVE FOR INSERT TO public WITH CHECK ((auth.uid() = user_id));

CREATE POLICY "Users can view own journals" ON public.journal_entries AS PERMISSIVE FOR SELECT TO public USING ((auth.uid() = user_id));

CREATE POLICY medication_events_select_own ON public.medication_events AS PERMISSIVE FOR SELECT TO authenticated USING (can_access_patient(user_id));

CREATE POLICY medication_records_select_own ON public.medication_records AS PERMISSIVE FOR SELECT TO authenticated USING (can_access_patient(patient_id));

CREATE POLICY "Anyone can read medication reference" ON public.medication_reference AS PERMISSIVE FOR SELECT TO public USING (true);

CREATE POLICY medication_sms_logs_select_own ON public.medication_sms_logs AS PERMISSIVE FOR SELECT TO authenticated USING (can_access_patient(patient_id));

CREATE POLICY "Users can manage own medications" ON public.medications AS PERMISSIVE FOR ALL TO public USING ((auth.uid() = user_id)) WITH CHECK ((auth.uid() = user_id));

CREATE POLICY patient_consents_select_own ON public.patient_consents AS PERMISSIVE FOR SELECT TO authenticated USING (can_access_patient(patient_id));

CREATE POLICY patient_invites_select_own ON public.patient_invites AS PERMISSIVE FOR SELECT TO authenticated USING ((provider_id = auth.uid()));

CREATE POLICY "Users can insert own patient profile" ON public.patient_profiles AS PERMISSIVE FOR INSERT TO public WITH CHECK ((auth.uid() = user_id));

CREATE POLICY "Users can view own patient profile" ON public.patient_profiles AS PERMISSIVE FOR SELECT TO public USING (((auth.uid() = user_id) OR (auth.uid() = provider_id)));

CREATE POLICY patient_session_summaries_select_own ON public.patient_session_summaries AS PERMISSIVE FOR SELECT TO authenticated USING (can_access_patient(patient_id));

CREATE POLICY pharmacy_fills_select_own ON public.pharmacy_fills AS PERMISSIVE FOR SELECT TO authenticated USING (can_access_patient(patient_id));

CREATE POLICY proactive_insights_select_own ON public.proactive_insights AS PERMISSIVE FOR SELECT TO authenticated USING (can_access_patient(patient_id));

CREATE POLICY "Service role can insert profiles" ON public.profiles AS PERMISSIVE FOR INSERT TO public WITH CHECK (true);

CREATE POLICY "Users can update own profile" ON public.profiles AS PERMISSIVE FOR UPDATE TO public USING ((auth.uid() = id));

CREATE POLICY "Users can view own profile" ON public.profiles AS PERMISSIVE FOR SELECT TO public USING ((auth.uid() = id));

CREATE POLICY provider_appointments_select_own ON public.provider_appointments AS PERMISSIVE FOR SELECT TO authenticated USING ((provider_id = auth.uid()));

CREATE POLICY provider_brief_views_select_own ON public.provider_brief_views AS PERMISSIVE FOR SELECT TO authenticated USING ((provider_id = auth.uid()));

CREATE POLICY provider_briefs_select_own ON public.provider_briefs AS PERMISSIVE FOR SELECT TO authenticated USING ((provider_id = auth.uid()));

CREATE POLICY providers_manage_own_focus_configs ON public.provider_focus_configs AS PERMISSIVE FOR ALL TO public USING ((provider_id = auth.uid()));

CREATE POLICY service_role_full_access_focus_configs ON public.provider_focus_configs AS PERMISSIVE FOR ALL TO public USING ((auth.role() = 'service_role'::text));

CREATE POLICY session_features_select_own ON public.session_features AS PERMISSIVE FOR SELECT TO authenticated USING (can_access_patient(patient_id));

CREATE POLICY side_effects_select_own ON public.side_effects AS PERMISSIVE FOR SELECT TO authenticated USING (can_access_patient(user_id));

CREATE POLICY sms_checkin_sessions_select_own ON public.sms_checkin_sessions AS PERMISSIVE FOR SELECT TO authenticated USING (can_access_patient(patient_id));

CREATE POLICY sms_crisis_events_select_own ON public.sms_crisis_events AS PERMISSIVE FOR SELECT TO authenticated USING (can_access_patient(patient_id));

CREATE POLICY "Users can insert own summaries" ON public.summaries AS PERMISSIVE FOR INSERT TO public WITH CHECK ((auth.uid() = user_id));

CREATE POLICY "Users can view own summaries" ON public.summaries AS PERMISSIVE FOR SELECT TO public USING ((auth.uid() = user_id));

CREATE POLICY "Users can insert own hypotheses" ON public.user_hypotheses AS PERMISSIVE FOR INSERT TO public WITH CHECK ((auth.uid() = user_id));

CREATE POLICY "Users can view own hypotheses" ON public.user_hypotheses AS PERMISSIVE FOR SELECT TO public USING ((auth.uid() = user_id));

CREATE POLICY voice_baselines_select_own ON public.voice_baselines AS PERMISSIVE FOR SELECT TO authenticated USING (can_access_patient(patient_id));

CREATE POLICY voice_memos_select_own ON public.voice_memos AS PERMISSIVE FOR SELECT TO authenticated USING (can_access_patient(patient_id));

CREATE POLICY voice_notes_select_own ON public.voice_notes AS PERMISSIVE FOR SELECT TO authenticated USING ((can_access_patient(patient_id) OR (provider_id = auth.uid())));

CREATE POLICY wearable_snapshots_select_own ON public.wearable_snapshots AS PERMISSIVE FOR SELECT TO authenticated USING (can_access_patient(patient_id));

CREATE POLICY patients_own_appointments ON public.appointments AS PERMISSIVE FOR SELECT TO public USING ((patient_id = auth.uid()));

GRANT TRIGGER ON public.appointments TO anon;

GRANT TRUNCATE ON public.appointments TO anon;

GRANT REFERENCES ON public.appointments TO authenticated;

GRANT SELECT ON public.appointments TO authenticated;

GRANT TRIGGER ON public.appointments TO authenticated;

GRANT TRUNCATE ON public.appointments TO authenticated;

GRANT DELETE ON public.appointments TO service_role;

GRANT INSERT ON public.appointments TO service_role;

GRANT REFERENCES ON public.appointments TO service_role;

GRANT SELECT ON public.appointments TO service_role;

GRANT TRIGGER ON public.appointments TO service_role;

GRANT TRUNCATE ON public.appointments TO service_role;

GRANT UPDATE ON public.appointments TO service_role;

GRANT DELETE ON public.care_flag_responses TO service_role;

GRANT INSERT ON public.care_flag_responses TO service_role;

GRANT REFERENCES ON public.care_flag_responses TO service_role;

GRANT SELECT ON public.care_flag_responses TO service_role;

GRANT TRIGGER ON public.care_flag_responses TO service_role;

GRANT TRUNCATE ON public.care_flag_responses TO service_role;

GRANT UPDATE ON public.care_flag_responses TO service_role;

GRANT DELETE ON public.care_flags TO service_role;

GRANT INSERT ON public.care_flags TO service_role;

GRANT REFERENCES ON public.care_flags TO service_role;

GRANT SELECT ON public.care_flags TO service_role;

GRANT TRIGGER ON public.care_flags TO service_role;

GRANT TRUNCATE ON public.care_flags TO service_role;

GRANT UPDATE ON public.care_flags TO service_role;

GRANT DELETE ON public.care_team_members TO service_role;

GRANT INSERT ON public.care_team_members TO service_role;

GRANT REFERENCES ON public.care_team_members TO service_role;

GRANT SELECT ON public.care_team_members TO service_role;

GRANT TRIGGER ON public.care_team_members TO service_role;

GRANT TRUNCATE ON public.care_team_members TO service_role;

GRANT UPDATE ON public.care_team_members TO service_role;

GRANT REFERENCES ON public.checkin_schedules TO anon;

GRANT TRIGGER ON public.checkin_schedules TO anon;

GRANT TRUNCATE ON public.checkin_schedules TO anon;

GRANT REFERENCES ON public.checkin_schedules TO authenticated;

GRANT SELECT ON public.checkin_schedules TO authenticated;

GRANT TRIGGER ON public.checkin_schedules TO authenticated;

GRANT TRUNCATE ON public.checkin_schedules TO authenticated;

GRANT DELETE ON public.checkin_schedules TO service_role;

GRANT INSERT ON public.checkin_schedules TO service_role;

GRANT REFERENCES ON public.checkin_schedules TO service_role;

GRANT SELECT ON public.checkin_schedules TO service_role;

GRANT TRIGGER ON public.checkin_schedules TO service_role;

GRANT TRUNCATE ON public.checkin_schedules TO service_role;

GRANT UPDATE ON public.checkin_schedules TO service_role;

GRANT DELETE ON public.checkin_tokens TO service_role;

GRANT INSERT ON public.checkin_tokens TO service_role;

GRANT REFERENCES ON public.checkin_tokens TO service_role;

GRANT SELECT ON public.checkin_tokens TO service_role;

GRANT TRIGGER ON public.checkin_tokens TO service_role;

GRANT TRUNCATE ON public.checkin_tokens TO service_role;

GRANT UPDATE ON public.checkin_tokens TO service_role;

GRANT DELETE ON public.checkins TO anon;

GRANT INSERT ON public.checkins TO anon;

GRANT REFERENCES ON public.checkins TO anon;

GRANT SELECT ON public.checkins TO anon;

GRANT TRIGGER ON public.checkins TO anon;

GRANT TRUNCATE ON public.checkins TO anon;

GRANT UPDATE ON public.checkins TO anon;

GRANT DELETE ON public.checkins TO authenticated;

GRANT INSERT ON public.checkins TO authenticated;

GRANT REFERENCES ON public.checkins TO authenticated;

GRANT SELECT ON public.checkins TO authenticated;

GRANT TRIGGER ON public.checkins TO authenticated;

GRANT TRUNCATE ON public.checkins TO authenticated;

GRANT UPDATE ON public.checkins TO authenticated;

GRANT DELETE ON public.checkins TO service_role;

GRANT INSERT ON public.checkins TO service_role;

GRANT REFERENCES ON public.checkins TO service_role;

GRANT SELECT ON public.checkins TO service_role;

GRANT TRIGGER ON public.checkins TO service_role;

GRANT TRUNCATE ON public.checkins TO service_role;

GRANT UPDATE ON public.checkins TO service_role;

GRANT DELETE ON public.clinical_sessions TO service_role;

GRANT INSERT ON public.clinical_sessions TO service_role;

GRANT REFERENCES ON public.clinical_sessions TO service_role;

GRANT SELECT ON public.clinical_sessions TO service_role;

GRANT TRIGGER ON public.clinical_sessions TO service_role;

GRANT TRUNCATE ON public.clinical_sessions TO service_role;

GRANT UPDATE ON public.clinical_sessions TO service_role;

GRANT DELETE ON public.daily_sms_sends TO anon;

GRANT INSERT ON public.daily_sms_sends TO anon;

GRANT REFERENCES ON public.daily_sms_sends TO anon;

GRANT SELECT ON public.daily_sms_sends TO anon;

GRANT TRIGGER ON public.daily_sms_sends TO anon;

GRANT TRUNCATE ON public.daily_sms_sends TO anon;

GRANT UPDATE ON public.daily_sms_sends TO anon;

GRANT DELETE ON public.daily_sms_sends TO authenticated;

GRANT INSERT ON public.daily_sms_sends TO authenticated;

GRANT REFERENCES ON public.daily_sms_sends TO authenticated;

GRANT SELECT ON public.daily_sms_sends TO authenticated;

GRANT TRIGGER ON public.daily_sms_sends TO authenticated;

GRANT TRUNCATE ON public.daily_sms_sends TO authenticated;

GRANT UPDATE ON public.daily_sms_sends TO authenticated;

GRANT DELETE ON public.daily_sms_sends TO service_role;

GRANT INSERT ON public.daily_sms_sends TO service_role;

GRANT REFERENCES ON public.daily_sms_sends TO service_role;

GRANT SELECT ON public.daily_sms_sends TO service_role;

GRANT TRIGGER ON public.daily_sms_sends TO service_role;

GRANT TRUNCATE ON public.daily_sms_sends TO service_role;

GRANT UPDATE ON public.daily_sms_sends TO service_role;

GRANT DELETE ON public.journal_entries TO anon;

GRANT INSERT ON public.journal_entries TO anon;

GRANT REFERENCES ON public.journal_entries TO anon;

GRANT SELECT ON public.journal_entries TO anon;

GRANT TRIGGER ON public.journal_entries TO anon;

GRANT TRUNCATE ON public.journal_entries TO anon;

GRANT UPDATE ON public.journal_entries TO anon;

GRANT DELETE ON public.journal_entries TO authenticated;

GRANT INSERT ON public.journal_entries TO authenticated;

GRANT REFERENCES ON public.journal_entries TO authenticated;

GRANT SELECT ON public.journal_entries TO authenticated;

GRANT TRIGGER ON public.journal_entries TO authenticated;

GRANT TRUNCATE ON public.journal_entries TO authenticated;

GRANT UPDATE ON public.journal_entries TO authenticated;

GRANT DELETE ON public.journal_entries TO service_role;

GRANT INSERT ON public.journal_entries TO service_role;

GRANT REFERENCES ON public.journal_entries TO service_role;

GRANT SELECT ON public.journal_entries TO service_role;

GRANT TRIGGER ON public.journal_entries TO service_role;

GRANT TRUNCATE ON public.journal_entries TO service_role;

GRANT UPDATE ON public.journal_entries TO service_role;

GRANT DELETE ON public.medication_events TO service_role;

GRANT INSERT ON public.medication_events TO service_role;

GRANT REFERENCES ON public.medication_events TO service_role;

GRANT SELECT ON public.medication_events TO service_role;

GRANT TRIGGER ON public.medication_events TO service_role;

GRANT TRUNCATE ON public.medication_events TO service_role;

GRANT UPDATE ON public.medication_events TO service_role;

GRANT DELETE ON public.medication_records TO service_role;

GRANT INSERT ON public.medication_records TO service_role;

GRANT REFERENCES ON public.medication_records TO service_role;

GRANT SELECT ON public.medication_records TO service_role;

GRANT TRIGGER ON public.medication_records TO service_role;

GRANT TRUNCATE ON public.medication_records TO service_role;

GRANT UPDATE ON public.medication_records TO service_role;

GRANT REFERENCES ON public.medication_reference TO anon;

GRANT SELECT ON public.medication_reference TO anon;

GRANT TRIGGER ON public.medication_reference TO anon;

GRANT TRUNCATE ON public.medication_reference TO anon;

GRANT REFERENCES ON public.medication_reference TO authenticated;

GRANT SELECT ON public.medication_reference TO authenticated;

GRANT TRIGGER ON public.medication_reference TO authenticated;

GRANT TRUNCATE ON public.medication_reference TO authenticated;

GRANT REFERENCES ON public.medication_reference TO service_role;

GRANT SELECT ON public.medication_reference TO service_role;

GRANT TRIGGER ON public.medication_reference TO service_role;

GRANT TRUNCATE ON public.medication_reference TO service_role;

GRANT DELETE ON public.medication_sms_logs TO service_role;

GRANT INSERT ON public.medication_sms_logs TO service_role;

GRANT REFERENCES ON public.medication_sms_logs TO service_role;

GRANT SELECT ON public.medication_sms_logs TO service_role;

GRANT TRIGGER ON public.medication_sms_logs TO service_role;

GRANT TRUNCATE ON public.medication_sms_logs TO service_role;

GRANT UPDATE ON public.medication_sms_logs TO service_role;

GRANT DELETE ON public.medications TO anon;

GRANT INSERT ON public.medications TO anon;

GRANT REFERENCES ON public.medications TO anon;

GRANT SELECT ON public.medications TO anon;

GRANT TRIGGER ON public.medications TO anon;

GRANT TRUNCATE ON public.medications TO anon;

GRANT UPDATE ON public.medications TO anon;

GRANT DELETE ON public.medications TO authenticated;

GRANT INSERT ON public.medications TO authenticated;

GRANT REFERENCES ON public.medications TO authenticated;

GRANT SELECT ON public.medications TO authenticated;

GRANT TRIGGER ON public.medications TO authenticated;

GRANT TRUNCATE ON public.medications TO authenticated;

GRANT UPDATE ON public.medications TO authenticated;

GRANT DELETE ON public.medications TO service_role;

GRANT INSERT ON public.medications TO service_role;

GRANT REFERENCES ON public.medications TO service_role;

GRANT SELECT ON public.medications TO service_role;

GRANT TRIGGER ON public.medications TO service_role;

GRANT TRUNCATE ON public.medications TO service_role;

GRANT UPDATE ON public.medications TO service_role;

GRANT DELETE ON public.patient_consents TO service_role;

GRANT INSERT ON public.patient_consents TO service_role;

GRANT REFERENCES ON public.patient_consents TO service_role;

GRANT SELECT ON public.patient_consents TO service_role;

GRANT TRIGGER ON public.patient_consents TO service_role;

GRANT TRUNCATE ON public.patient_consents TO service_role;

GRANT UPDATE ON public.patient_consents TO service_role;

GRANT DELETE ON public.patient_invites TO service_role;

GRANT INSERT ON public.patient_invites TO service_role;

GRANT REFERENCES ON public.patient_invites TO service_role;

GRANT SELECT ON public.patient_invites TO service_role;

GRANT TRIGGER ON public.patient_invites TO service_role;

GRANT TRUNCATE ON public.patient_invites TO service_role;

GRANT UPDATE ON public.patient_invites TO service_role;

GRANT DELETE ON public.patient_profiles TO anon;

GRANT INSERT ON public.patient_profiles TO anon;

GRANT REFERENCES ON public.patient_profiles TO anon;

GRANT SELECT ON public.patient_profiles TO anon;

GRANT TRIGGER ON public.patient_profiles TO anon;

GRANT TRUNCATE ON public.patient_profiles TO anon;

GRANT UPDATE ON public.patient_profiles TO anon;

GRANT DELETE ON public.patient_profiles TO authenticated;

GRANT INSERT ON public.patient_profiles TO authenticated;

GRANT REFERENCES ON public.patient_profiles TO authenticated;

GRANT SELECT ON public.patient_profiles TO authenticated;

GRANT TRIGGER ON public.patient_profiles TO authenticated;

GRANT TRUNCATE ON public.patient_profiles TO authenticated;

GRANT UPDATE ON public.patient_profiles TO authenticated;

GRANT DELETE ON public.patient_profiles TO service_role;

GRANT INSERT ON public.patient_profiles TO service_role;

GRANT REFERENCES ON public.patient_profiles TO service_role;

GRANT SELECT ON public.patient_profiles TO service_role;

GRANT TRIGGER ON public.patient_profiles TO service_role;

GRANT TRUNCATE ON public.patient_profiles TO service_role;

GRANT UPDATE ON public.patient_profiles TO service_role;

GRANT DELETE ON public.patient_session_summaries TO service_role;

GRANT INSERT ON public.patient_session_summaries TO service_role;

GRANT REFERENCES ON public.patient_session_summaries TO service_role;

GRANT SELECT ON public.patient_session_summaries TO service_role;

GRANT TRIGGER ON public.patient_session_summaries TO service_role;

GRANT TRUNCATE ON public.patient_session_summaries TO service_role;

GRANT UPDATE ON public.patient_session_summaries TO service_role;

GRANT DELETE ON public.pharmacy_fills TO service_role;

GRANT INSERT ON public.pharmacy_fills TO service_role;

GRANT REFERENCES ON public.pharmacy_fills TO service_role;

GRANT SELECT ON public.pharmacy_fills TO service_role;

GRANT TRIGGER ON public.pharmacy_fills TO service_role;

GRANT TRUNCATE ON public.pharmacy_fills TO service_role;

GRANT UPDATE ON public.pharmacy_fills TO service_role;

GRANT DELETE ON public.proactive_insights TO service_role;

GRANT INSERT ON public.proactive_insights TO service_role;

GRANT REFERENCES ON public.proactive_insights TO service_role;

GRANT SELECT ON public.proactive_insights TO service_role;

GRANT TRIGGER ON public.proactive_insights TO service_role;

GRANT TRUNCATE ON public.proactive_insights TO service_role;

GRANT UPDATE ON public.proactive_insights TO service_role;

GRANT DELETE ON public.profiles TO anon;

GRANT INSERT ON public.profiles TO anon;

GRANT REFERENCES ON public.profiles TO anon;

GRANT SELECT ON public.profiles TO anon;

GRANT TRIGGER ON public.profiles TO anon;

GRANT TRUNCATE ON public.profiles TO anon;

GRANT UPDATE ON public.profiles TO anon;

GRANT DELETE ON public.profiles TO authenticated;

GRANT INSERT ON public.profiles TO authenticated;

GRANT REFERENCES ON public.profiles TO authenticated;

GRANT SELECT ON public.profiles TO authenticated;

GRANT TRIGGER ON public.profiles TO authenticated;

GRANT TRUNCATE ON public.profiles TO authenticated;

GRANT UPDATE ON public.profiles TO authenticated;

GRANT DELETE ON public.profiles TO service_role;

GRANT INSERT ON public.profiles TO service_role;

GRANT REFERENCES ON public.profiles TO service_role;

GRANT SELECT ON public.profiles TO service_role;

GRANT TRIGGER ON public.profiles TO service_role;

GRANT TRUNCATE ON public.profiles TO service_role;

GRANT UPDATE ON public.profiles TO service_role;

GRANT DELETE ON public.provider_appointments TO service_role;

GRANT INSERT ON public.provider_appointments TO service_role;

GRANT REFERENCES ON public.provider_appointments TO service_role;

GRANT SELECT ON public.provider_appointments TO service_role;

GRANT TRIGGER ON public.provider_appointments TO service_role;

GRANT TRUNCATE ON public.provider_appointments TO service_role;

GRANT UPDATE ON public.provider_appointments TO service_role;

GRANT DELETE ON public.provider_brief_views TO service_role;

GRANT INSERT ON public.provider_brief_views TO service_role;

GRANT REFERENCES ON public.provider_brief_views TO service_role;

GRANT SELECT ON public.provider_brief_views TO service_role;

GRANT TRIGGER ON public.provider_brief_views TO service_role;

GRANT TRUNCATE ON public.provider_brief_views TO service_role;

GRANT UPDATE ON public.provider_brief_views TO service_role;

GRANT DELETE ON public.provider_briefs TO service_role;

GRANT INSERT ON public.provider_briefs TO service_role;

GRANT REFERENCES ON public.provider_briefs TO service_role;

GRANT SELECT ON public.provider_briefs TO service_role;

GRANT TRIGGER ON public.provider_briefs TO service_role;

GRANT TRUNCATE ON public.provider_briefs TO service_role;

GRANT UPDATE ON public.provider_briefs TO service_role;

GRANT DELETE ON public.provider_focus_configs TO anon;

GRANT INSERT ON public.provider_focus_configs TO anon;

GRANT REFERENCES ON public.provider_focus_configs TO anon;

GRANT SELECT ON public.provider_focus_configs TO anon;

GRANT TRIGGER ON public.provider_focus_configs TO anon;

GRANT TRUNCATE ON public.provider_focus_configs TO anon;

GRANT UPDATE ON public.provider_focus_configs TO anon;

GRANT DELETE ON public.provider_focus_configs TO authenticated;

GRANT INSERT ON public.provider_focus_configs TO authenticated;

GRANT REFERENCES ON public.provider_focus_configs TO authenticated;

GRANT SELECT ON public.provider_focus_configs TO authenticated;

GRANT TRIGGER ON public.provider_focus_configs TO authenticated;

GRANT TRUNCATE ON public.provider_focus_configs TO authenticated;

GRANT UPDATE ON public.provider_focus_configs TO authenticated;

GRANT DELETE ON public.provider_focus_configs TO service_role;

GRANT INSERT ON public.provider_focus_configs TO service_role;

GRANT REFERENCES ON public.provider_focus_configs TO service_role;

GRANT SELECT ON public.provider_focus_configs TO service_role;

GRANT TRIGGER ON public.provider_focus_configs TO service_role;

GRANT TRUNCATE ON public.provider_focus_configs TO service_role;

GRANT UPDATE ON public.provider_focus_configs TO service_role;

GRANT DELETE ON public.session_features TO service_role;

GRANT INSERT ON public.session_features TO service_role;

GRANT REFERENCES ON public.session_features TO service_role;

GRANT SELECT ON public.session_features TO service_role;

GRANT TRIGGER ON public.session_features TO service_role;

GRANT TRUNCATE ON public.session_features TO service_role;

GRANT UPDATE ON public.session_features TO service_role;

GRANT REFERENCES ON public.side_effects TO service_role;

GRANT TRIGGER ON public.side_effects TO service_role;

GRANT TRUNCATE ON public.side_effects TO service_role;

GRANT DELETE ON public.sms_checkin_sessions TO service_role;

GRANT INSERT ON public.sms_checkin_sessions TO service_role;

GRANT REFERENCES ON public.sms_checkin_sessions TO service_role;

GRANT SELECT ON public.sms_checkin_sessions TO service_role;

GRANT TRIGGER ON public.sms_checkin_sessions TO service_role;

GRANT TRUNCATE ON public.sms_checkin_sessions TO service_role;

GRANT UPDATE ON public.sms_checkin_sessions TO service_role;

GRANT DELETE ON public.sms_crisis_events TO service_role;

GRANT INSERT ON public.sms_crisis_events TO service_role;

GRANT REFERENCES ON public.sms_crisis_events TO service_role;

GRANT SELECT ON public.sms_crisis_events TO service_role;

GRANT TRIGGER ON public.sms_crisis_events TO service_role;

GRANT TRUNCATE ON public.sms_crisis_events TO service_role;

GRANT UPDATE ON public.sms_crisis_events TO service_role;

GRANT DELETE ON public.sms_tokens TO service_role;

GRANT INSERT ON public.sms_tokens TO service_role;

GRANT REFERENCES ON public.sms_tokens TO service_role;

GRANT SELECT ON public.sms_tokens TO service_role;

GRANT TRIGGER ON public.sms_tokens TO service_role;

GRANT TRUNCATE ON public.sms_tokens TO service_role;

GRANT UPDATE ON public.sms_tokens TO service_role;

GRANT DELETE ON public.summaries TO anon;

GRANT INSERT ON public.summaries TO anon;

GRANT REFERENCES ON public.summaries TO anon;

GRANT SELECT ON public.summaries TO anon;

GRANT TRIGGER ON public.summaries TO anon;

GRANT TRUNCATE ON public.summaries TO anon;

GRANT UPDATE ON public.summaries TO anon;

GRANT DELETE ON public.summaries TO authenticated;

GRANT INSERT ON public.summaries TO authenticated;

GRANT REFERENCES ON public.summaries TO authenticated;

GRANT SELECT ON public.summaries TO authenticated;

GRANT TRIGGER ON public.summaries TO authenticated;

GRANT TRUNCATE ON public.summaries TO authenticated;

GRANT UPDATE ON public.summaries TO authenticated;

GRANT DELETE ON public.summaries TO service_role;

GRANT INSERT ON public.summaries TO service_role;

GRANT REFERENCES ON public.summaries TO service_role;

GRANT SELECT ON public.summaries TO service_role;

GRANT TRIGGER ON public.summaries TO service_role;

GRANT TRUNCATE ON public.summaries TO service_role;

GRANT UPDATE ON public.summaries TO service_role;

GRANT DELETE ON public.user_hypotheses TO anon;

GRANT INSERT ON public.user_hypotheses TO anon;

GRANT REFERENCES ON public.user_hypotheses TO anon;

GRANT SELECT ON public.user_hypotheses TO anon;

GRANT TRIGGER ON public.user_hypotheses TO anon;

GRANT TRUNCATE ON public.user_hypotheses TO anon;

GRANT UPDATE ON public.user_hypotheses TO anon;

GRANT DELETE ON public.user_hypotheses TO authenticated;

GRANT INSERT ON public.user_hypotheses TO authenticated;

GRANT REFERENCES ON public.user_hypotheses TO authenticated;

GRANT SELECT ON public.user_hypotheses TO authenticated;

GRANT TRIGGER ON public.user_hypotheses TO authenticated;

GRANT TRUNCATE ON public.user_hypotheses TO authenticated;

GRANT UPDATE ON public.user_hypotheses TO authenticated;

GRANT DELETE ON public.user_hypotheses TO service_role;

GRANT INSERT ON public.user_hypotheses TO service_role;

GRANT REFERENCES ON public.user_hypotheses TO service_role;

GRANT SELECT ON public.user_hypotheses TO service_role;

GRANT TRIGGER ON public.user_hypotheses TO service_role;

GRANT TRUNCATE ON public.user_hypotheses TO service_role;

GRANT UPDATE ON public.user_hypotheses TO service_role;

GRANT DELETE ON public.voice_baselines TO service_role;

GRANT INSERT ON public.voice_baselines TO service_role;

GRANT REFERENCES ON public.voice_baselines TO service_role;

GRANT SELECT ON public.voice_baselines TO service_role;

GRANT TRIGGER ON public.voice_baselines TO service_role;

GRANT TRUNCATE ON public.voice_baselines TO service_role;

GRANT UPDATE ON public.voice_baselines TO service_role;

GRANT DELETE ON public.voice_memos TO service_role;

GRANT INSERT ON public.voice_memos TO service_role;

GRANT REFERENCES ON public.voice_memos TO service_role;

GRANT SELECT ON public.voice_memos TO service_role;

GRANT TRIGGER ON public.voice_memos TO service_role;

GRANT TRUNCATE ON public.voice_memos TO service_role;

GRANT UPDATE ON public.voice_memos TO service_role;

GRANT DELETE ON public.voice_notes TO service_role;

GRANT INSERT ON public.voice_notes TO service_role;

GRANT REFERENCES ON public.voice_notes TO service_role;

GRANT SELECT ON public.voice_notes TO service_role;

GRANT TRIGGER ON public.voice_notes TO service_role;

GRANT TRUNCATE ON public.voice_notes TO service_role;

GRANT UPDATE ON public.voice_notes TO service_role;

GRANT DELETE ON public.wearable_snapshots TO service_role;

GRANT INSERT ON public.wearable_snapshots TO service_role;

GRANT REFERENCES ON public.wearable_snapshots TO service_role;

GRANT SELECT ON public.wearable_snapshots TO service_role;

GRANT TRIGGER ON public.wearable_snapshots TO service_role;

GRANT TRUNCATE ON public.wearable_snapshots TO service_role;

GRANT UPDATE ON public.wearable_snapshots TO service_role;

GRANT REFERENCES ON public.appointments TO anon;
