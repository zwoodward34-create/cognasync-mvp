#!/bin/bash
set -e

echo "=== Phase 10: Provider invite flow, print summary, patient appointments ==="

cd "$(dirname "$0")"

git add \
  app.py \
  database.py \
  email_utils.py \
  static/css/style.css \
  templates/auth/register.html \
  templates/provider/dashboard.html \
  templates/provider/patient_detail.html \
  templates/provider/summary_print.html \
  templates/patient/appointments.html \
  templates/patient/home.html \
  templates/layout.html

git commit -m "Phase 10: Provider invite flow, Mode C print export, patient appointments

Feature 1 — Provider-initiated patient invite:
- database.py: create_patient_invite(), get_patient_invite_by_token(),
  process_pending_invites(), get_patient_appointment_list()
- database.py: send_care_team_request() falls back to invite when patient
  has no account; get_care_team_for_patient() for patient-side view
- email_utils.py: send_provider_patient_invite_email(),
  send_appointment_request_email()
- app.py: /register GET accepts ?invite=TOKEN, looks up invite context
- app.py: register_post threads invite_token through form on errors
- app.py: /api/provider/care-team/request sends invite email when
  method=invitation (with branded link including token)
- app.py: both admin_approve routes call process_pending_invites() for
  patients, auto-creating care_team_members from pending invites
- register.html: invite banner, pre-filled/readonly email, hidden role
  when invite present, hidden invite_token field
- dashboard.html: updated description + handles method=invitation in JS
- style.css: .auth-invite-banner + .invite-message styles

Feature 2 — Mode C printable / PDF export:
- app.py: /provider/patient/<id>/summary/print route — generates Mode C
  and renders print-optimized template
- summary_print.html: standalone print template with period selector,
  confidentiality banner, print CSS, JS markdown formatter
- patient_detail.html: Print Summary button in patient header

Feature 4 — Patient-facing appointments:
- app.py: /appointments page route, /api/patient/appointments GET,
  /api/patient/appointments/request POST
- appointments.html: upcoming / past appointment list + request form
  with provider selector from care team
- home.html: Appointments quick-card with async next-appointment sub-text
- layout.html: Appointments nav link for patient role (desktop + mobile)"

echo "✓ Committed phase 10"
