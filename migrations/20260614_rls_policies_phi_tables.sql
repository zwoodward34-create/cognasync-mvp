-- 20260614_rls_policies_phi_tables.sql
-- ============================================================================
-- APPLIED 2026-06-14 to project qsnxrfefwwybiutkynzk (migration: rls_policies_phi_tables).
-- 23 of 25 tables now carry a *_select_own policy; checkin_tokens and sms_tokens
-- remain intentionally policy-less (backend-only, deny-all). Inert until/unless
-- anon/authenticated table grants are reintroduced. Access model assumptions
-- below were accepted as-is; revisit if care-team semantics change.
-- ============================================================================
-- Next hardening pass after 20260614_harden_phi_grants.sql (which revoked the
-- anon/authenticated grants). This adds explicit auth.uid()-scoped SELECT
-- policies so these 25 PHI tables are protected by INTENT, not just by the
-- "RLS-on, no-policy" deny-all default.
--
-- DESIGN DECISIONS (review these):
--   1. SELECT-only. Clients must never write these tables directly — the Flask
--      app writes everything via the service-role key (which bypasses RLS).
--      Omitting INSERT/UPDATE/DELETE policies keeps writes denied for client
--      roles even if table grants are ever restored.
--   2. TO authenticated. anon (logged-out) gets nothing on PHI. Ever.
--   3. Access model is centralized in can_access_patient(): a row is visible to
--      the patient themselves OR to a provider with an active (non-revoked)
--      care_team_members link to that patient. This mirrors the app's
--      _provider_owns_patient() check. ASSUMPTION: an active link is
--      revoked_at IS NULL — adjust if your model also requires status='active'.
--   4. Token tables (checkin_tokens, sms_tokens) get NO policy on purpose —
--      they are backend-only and remain deny-all to every client role.
--   5. These policies are currently INERT: with anon/authenticated table grants
--      revoked, no client role can reach the tables at all. They take effect as
--      defense-in-depth if/when grants are re-introduced for a direct-to-Supabase
--      client. Applying now is safe and forward-proofs the schema.
-- ============================================================================

-- ── Centralized access helper (SECURITY DEFINER avoids RLS recursion on
--    care_team_members and lets policies stay one-liners) ──────────────────
create or replace function public.can_access_patient(p_patient uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select
    auth.uid() = p_patient
    or exists (
      select 1
      from public.care_team_members ctm
      where ctm.patient_id  = p_patient
        and ctm.provider_id = auth.uid()
        and ctm.revoked_at is null
    );
$$;

revoke execute on function public.can_access_patient(uuid) from public, anon;
grant  execute on function public.can_access_patient(uuid) to authenticated, service_role;

-- ── Patient-scoped tables (keyed by patient_id) ────────────────────────────
do $$
declare t text;
begin
  foreach t in array array[
    'care_flags','care_flag_responses','clinical_sessions','medication_records',
    'medication_sms_logs','patient_consents','patient_session_summaries',
    'pharmacy_fills','proactive_insights','session_features','sms_checkin_sessions',
    'sms_crisis_events','voice_baselines','voice_memos','wearable_snapshots'
  ] loop
    execute format('drop policy if exists %I on public.%I', t||'_select_own', t);
    execute format(
      'create policy %I on public.%I for select to authenticated using (public.can_access_patient(patient_id))',
      t||'_select_own', t);
  end loop;
end $$;

-- ── Patient-or-owning-provider tables (patient_id + provider_id) ───────────
do $$
declare t text;
begin
  foreach t in array array['provider_appointments','provider_briefs','voice_notes'] loop
    execute format('drop policy if exists %I on public.%I', t||'_select_own', t);
    execute format(
      'create policy %I on public.%I for select to authenticated using (public.can_access_patient(patient_id) or provider_id = auth.uid())',
      t||'_select_own', t);
  end loop;
end $$;

-- ── Tables keyed by user_id (the patient's id) ─────────────────────────────
do $$
declare t text;
begin
  foreach t in array array['medication_events','side_effects'] loop
    execute format('drop policy if exists %I on public.%I', t||'_select_own', t);
    execute format(
      'create policy %I on public.%I for select to authenticated using (public.can_access_patient(user_id))',
      t||'_select_own', t);
  end loop;
end $$;

-- ── Provider-owned tables (no patient_id) ──────────────────────────────────
drop policy if exists patient_invites_select_own on public.patient_invites;
create policy patient_invites_select_own on public.patient_invites
  for select to authenticated using (provider_id = auth.uid());

drop policy if exists provider_brief_views_select_own on public.provider_brief_views;
create policy provider_brief_views_select_own on public.provider_brief_views
  for select to authenticated using (provider_id = auth.uid());

-- ── care_team_members: visible to either party of the link ─────────────────
drop policy if exists care_team_members_select_own on public.care_team_members;
create policy care_team_members_select_own on public.care_team_members
  for select to authenticated using (patient_id = auth.uid() or provider_id = auth.uid());

-- ── checkin_tokens, sms_tokens: intentionally NO policy (backend-only,
--    deny-all to every client role). Do not add policies here.
