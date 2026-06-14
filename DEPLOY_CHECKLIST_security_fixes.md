# Deploy & Verification Checklist — June 2026 Security Fixes

Covers the immediate audit remediations. **The database migration (C-4/M-4/M-5) is already
applied to production.** The code changes below are committed to the working tree but still
need to be pushed from your Mac (the Cowork sandbox has no GitHub credentials). Render
auto-deploys on push to `main`.

---

## 0. What's in this batch

| ID | Fix | Type | Status |
|----|-----|------|--------|
| C-1 | `/api/sms/inbound` now requires a valid Twilio signature + rate limit | code (`app.py`) | needs push |
| H-1 | Login fails closed when profile row/status missing | code (`supabase_auth.py`) | needs push |
| C-2/C-3/H-7 | Hardened + unified crisis matcher; psychiatry summary scans journals; SMS uses canonical matcher | code (`claude_api.py`, `sms_engine.py`) | needs push |
| C-4/M-4/M-5 | Revoked anon/authenticated PHI grants; dropped `USING(true)` policies; locked `rls_auto_enable()` | DB migration | **applied to prod** |
| (next pass) | Explicit `auth.uid()` SELECT policies on 23 PHI tables + `can_access_patient()` helper | DB migration | **applied to prod** |

---

## 1. Pre-push review (on your Mac)

- [ ] `git diff` the four changed files: `app.py`, `supabase_auth.py`, `claude_api.py`, `sms_engine.py`.
- [ ] Confirm the two new migration files are present:
  - `migrations/20260614_harden_phi_grants.sql` (already applied — for the record)
  - `migrations/20260614_rls_policies_phi_tables_DRAFT.sql` (**DRAFT — do not apply yet**, see §5)
- [ ] Local syntax check: `python -m py_compile app.py supabase_auth.py claude_api.py sms_engine.py`
- [ ] (If git leaves a stale lock: `mv .git/index.lock .git/stale-index.lock.bak` and retry.)

## 2. Push & deploy

- [ ] `git add -A && git commit -m "security: authenticate SMS webhook, fail-closed login, harden crisis detection"`
- [ ] `git push origin main`
- [ ] Watch the Render deploy finish (Events tab). Confirm the service is healthy, not crash-looping.

## 3. Post-deploy smoke tests

**C-1 — SMS webhook auth**
- [ ] Send a real text from an enrolled patient phone to the Twilio number → confirm normal handling still works (Twilio signs legit requests, so they pass).
- [ ] `curl -X POST https://<app>/api/sms/inbound -d 'From=%2B15551234567&Body=test'` (no signature) → expect **403** `Invalid Twilio signature` (previously this would have been accepted).
- [ ] Check Render logs for `[twilio] Invalid webhook signature` on the curl attempt.
- [ ] ⚠️ If legit inbound texts start returning 403: the signed URL Twilio uses doesn't match `request.url` behind Render's proxy. Fix by honoring `X-Forwarded-Proto`/host so `request.url` is the external `https://` URL — do **not** remove the check.

**H-1 — login fail-closed**
- [ ] Log in with a normal approved account → still works.
- [ ] Confirm pending-email and pending-approval accounts still get their specific messages.
- [ ] (Optional) Temporarily point a test auth user with no `profiles` row at login → expect denial ("account is not fully set up"), not access.

**C-2/C-3/H-7 — crisis detection**
- [ ] Patient journal entry containing `i want to d1e` → crisis resources shown (988/911 block), entry not given a normal reflection. (Was previously missed.)
- [ ] Text `unalive myself` to the SMS line → crisis SMS + provider alert fires.
- [ ] Generate a **psychiatrist** appointment summary for a patient whose journals contain self-harm language → brief begins with a `🔴 Crisis Signal` section. (Was previously absent.)
- [ ] Sanity: a benign journal ("had a good day, mood 8") → normal insight, no false crisis.

## 4. Database fix — already live, verify it held

Run in the Supabase SQL editor (read-only):
```sql
-- expect 0, 0, 0
select
 (select count(*) from information_schema.role_table_grants
   where table_schema='public' and grantee in ('anon','authenticated')
   and table_name in ('clinical_sessions','voice_notes','provider_briefs','sms_crisis_events','session_features')) as phi_anon_grants,
 (select count(*) from pg_policies where policyname in ('service_role_all_appointments','service_role_all_schedules')) as using_true_policies,
 (select count(*) from pg_proc p join aclexplode(p.proacl) a on true join pg_roles r on r.oid=a.grantee
   where p.proname='rls_auto_enable' and a.privilege_type='EXECUTE' and r.rolname in ('anon','authenticated')) as func_exec;
```
- [ ] Confirm the app still reads/writes PHI normally after the migration (it uses the service-role key, which is unaffected). Spot-check: load a provider dashboard, open a patient, view transcripts/briefs.

## 5. RLS policies — APPLIED 2026-06-14 (review the assumptions retroactively)

`migrations/20260614_rls_policies_phi_tables.sql` has been **applied to prod**: explicit
`auth.uid()`-scoped SELECT policies on 23 of the 25 PHI tables, plus a `can_access_patient()`
helper. `checkin_tokens` and `sms_tokens` stay deny-all by design. The policies are **inert today**
(client roles have no table grants), so they changed nothing functionally — they're defense-in-depth
for any future direct-to-Supabase client. The two open assumptions were RESOLVED 2026-06-14 in
`migrations/20260614_rls_refine_access_model.sql` (applied to prod):
- [x] `can_access_patient()` now requires `status = 'active' AND revoked_at IS NULL` — matches the
      app's own care-team check; a pending/unapproved link no longer grants access.
- [x] Clinician work product (`provider_appointments`, `provider_briefs`) is now **provider-only**.
      `voice_notes` was kept patient-visible because it is patient-recorded audio shown back to the
      patient (`patient/voice_notes.html`), not a clinician note.
- [ ] Functional enforcement is still not runtime-tested because the tables are correctly grant-less
      today; re-test if/when a client role is ever granted direct access.

## 6. Rollback notes

- **Code:** revert the commit and re-push; Render redeploys the previous build.
- **DB grants (C-4):** if some unknown client flow breaks (not expected — no anon key ships to the
  browser), re-grant narrowly, e.g. `GRANT SELECT ON public.<table> TO authenticated;` for the
  specific table, then add a scoped policy rather than restoring blanket `GRANT ALL`.
- **`rls_auto_enable` (M-5):** `GRANT EXECUTE ON FUNCTION public.rls_auto_enable() TO authenticated;`
  restores prior behavior (not recommended).
