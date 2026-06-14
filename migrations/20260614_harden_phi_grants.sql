-- 20260614_harden_phi_grants.sql
-- Security hardening from the June 2026 audit:
--   C-4 — revoke anon/authenticated DML on RLS-enabled, zero-policy PHI tables
--   M-4 — drop over-permissive USING(true) ALL policies on appointments / checkin_schedules
--   M-5 — revoke EXECUTE on the anon-callable SECURITY DEFINER function rls_auto_enable()
--
-- Why this is safe: the application accesses Postgres exclusively through the
-- service-role key (which BYPASSES RLS) and ships no anon key to the browser, so
-- no client flow depends on anon/authenticated table grants or on these policies.
-- service_role privileges are left fully intact. Reversible via re-GRANT if needed.

-- ── C-4: revoke anon/authenticated on the 25 RLS-enabled, zero-policy PHI tables ──
REVOKE ALL ON TABLE
    public.care_flag_responses,
    public.care_flags,
    public.care_team_members,
    public.checkin_tokens,
    public.clinical_sessions,
    public.medication_events,
    public.medication_records,
    public.medication_sms_logs,
    public.patient_consents,
    public.patient_invites,
    public.patient_session_summaries,
    public.pharmacy_fills,
    public.proactive_insights,
    public.provider_appointments,
    public.provider_brief_views,
    public.provider_briefs,
    public.session_features,
    public.side_effects,
    public.sms_checkin_sessions,
    public.sms_crisis_events,
    public.sms_tokens,
    public.voice_baselines,
    public.voice_memos,
    public.voice_notes,
    public.wearable_snapshots
FROM anon, authenticated;

-- ── M-4: drop the USING(true) ALL policies scoped to public ──
-- service_role bypasses RLS so does not need them; per-user policies remain in force.
DROP POLICY IF EXISTS service_role_all_appointments ON public.appointments;
DROP POLICY IF EXISTS service_role_all_schedules ON public.checkin_schedules;

-- ── M-5: revoke execute on the anon/authenticated-callable SECURITY DEFINER function ──
-- NOTE: EXECUTE is granted to PUBLIC by default, so revoking anon/authenticated
-- alone leaves the function callable. Revoke from PUBLIC and grant back only to
-- the privileged roles that legitimately run maintenance.
REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.rls_auto_enable() TO service_role, postgres;
