#!/bin/bash
# Run from inside the cognasync-mvp folder:
#   bash push.sh

cd "$(dirname "$0")"

rm -f .git/index.lock

git add app.py supabase_auth.py \
        templates/auth/verify_sent.html \
        templates/auth/resend_verification.html \
        static/css/style.css \
        templates/provider/dashboard.html \
        templates/provider/patient_detail.html \
        templates/provider/appointment.html \
        migrations/provider_appointments.sql

git commit -m "fix: registration orphan bug + journal sidebar on appointment screen

Auth fixes (supabase_auth.py, app.py):
  - Split monolithic try/except into 3 distinct steps with proper cleanup:
      Step 1: create Supabase Auth user
      Step 2: insert profile row (rolls back auth user on failure)
      Step 3: send verification email (non-fatal — account still created)
  - Pre-flight check for existing accounts before hitting Supabase:
      pending_email  → resend the verification link, show clear message
      pending/approved → tell user to sign in instead
  - Map Supabase 'already registered' errors to friendly messages
  - email_sent flag passed to verify_sent.html to show recovery UI
  - New /resend-verification route + template for self-service resend

Provider appointment journal sidebar (appointment.html, app.py, style.css):
  - Right sidebar showing all shared journal entries for the review window
  - Journals scoped to appointment period via get_journals_in_range
  - Collapsible panel; each entry expands to full text + AI reflection
  - Entry count badge, date range displayed in sidebar header
  - Vertical expand tab when sidebar is collapsed
  - Responsive: converts to bottom drawer on tablet/mobile"

git push origin main

echo ""
echo "Pushed. Render will deploy automatically."
echo ""
echo "IMPORTANT — run this SQL in Supabase before testing:"
echo "  migrations/provider_appointments.sql"
