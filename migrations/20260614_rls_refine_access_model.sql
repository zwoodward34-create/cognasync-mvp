-- 20260614_rls_refine_access_model.sql
-- APPLIED 2026-06-14 to project qsnxrfefwwybiutkynzk (migration: rls_refine_access_model).
-- Resolves the two access-model assumptions left open by 20260614_rls_policies_phi_tables.sql,
-- per product decisions:
--   (1) An "active" care-team link = care_team_members.status = 'active' (mirrors the app's own
--       _provider_owns_patient / dashboard checks) AND revoked_at IS NULL. Tighter than the prior
--       "merely not cancelled" — a pending/unapproved link no longer grants access.
--   (2) Clinician work product is provider-only: provider_appointments, provider_briefs.
--       NOTE: voice_notes is deliberately NOT locked down here — it is patient-recorded audio
--       shown back to the patient in patient/voice_notes.html, so it stays patient-visible.

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
        and ctm.status      = 'active'
        and ctm.revoked_at is null
    );
$$;

drop policy if exists provider_appointments_select_own on public.provider_appointments;
create policy provider_appointments_select_own on public.provider_appointments
  for select to authenticated using (provider_id = auth.uid());

drop policy if exists provider_briefs_select_own on public.provider_briefs;
create policy provider_briefs_select_own on public.provider_briefs
  for select to authenticated using (provider_id = auth.uid());
