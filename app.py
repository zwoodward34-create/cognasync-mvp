import os
import csv
import io
import json
import re
import hmac
from datetime import date, timedelta
from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash, Response
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

load_dotenv()

import database as db
import supabase_auth as auth_module
import claude_api

_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')

def _parse_local_date(raw) -> str:
    """Return raw if it's a valid YYYY-MM-DD string, otherwise today's server date."""
    s = str(raw or '').strip()
    return s if _DATE_RE.match(s) else date.today().isoformat()

app = Flask(__name__, static_folder='static', static_url_path='/static')

_secret_key = os.environ.get('SECRET_KEY')
if not _secret_key:
    raise RuntimeError('SECRET_KEY environment variable must be set')
app.secret_key = _secret_key

app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') != 'development'

_allowed_origin = os.environ.get('ALLOWED_ORIGIN', '*')
CORS(app, resources={r"/api/*": {"origins": _allowed_origin}})

limiter = Limiter(app=app, key_func=get_remote_address, default_limits=["1000/day"])

# Log which email provider is active at startup so Render logs make it obvious.
import email_utils as _eu
if _eu.RESEND_API_KEY:
    print(f"[email] provider=Resend from={_eu._RESEND_FROM!r}")
elif all([_eu.SMTP_HOST, _eu.SMTP_USER, _eu.SMTP_PASS]):
    print(f"[email] provider=SMTP host={_eu.SMTP_HOST!r} from={_eu.FROM_EMAIL!r}")
else:
    print("[email] WARNING: no email provider configured — emails will fail silently")

db.init_db()


@app.errorhandler(500)
def internal_error(e):
    import traceback
    app.logger.exception("Unhandled error")
    if os.environ.get('FLASK_ENV') == 'development':
        return jsonify({'error': 'An internal error occurred', 'debug': traceback.format_exc()}), 500
    return jsonify({'error': 'An internal error occurred'}), 500


# ── Helpers ───────────────────────────────────────────────────────────────────

def _session_token():
    # Never accept tokens from URL query parameters — they end up in logs
    return session.get('session_token')


def _provider_owns_patient(provider_id, patient_id):
    """Return True if provider has access to this patient (legacy or care team)."""
    # Check legacy single-provider assignment
    assigned = db.get_provider_patients(provider_id)
    if str(patient_id) in [str(p['patient_id']) for p in assigned]:
        return True
    # Check care team membership
    return db.provider_has_care_access(provider_id, patient_id)


# ── Permission helpers ────────────────────────────────────────────────────────

_ALL_PERMS_TRUE = {k: True for k in (
    'journals_raw', 'journals_themes', 'mood_stress_sleep',
    'medication_data', 'system_scores', 'advanced_data', 'cross_provider_flags'
)}

def _get_provider_perms(provider_id: str, patient_id: str) -> dict:
    """Return data_permissions for this provider-patient pair.

    If no care_team_members row exists but a legacy (patient_profiles.provider_id)
    relationship does, auto-create the row so the patient can manage permissions.
    """
    perms = db.get_care_team_permissions(patient_id, provider_id)
    if perms is None:
        # Check for legacy relationship and migrate on first access
        legacy_patients = db.get_provider_patients(provider_id)
        if str(patient_id) in [str(p['patient_id']) for p in legacy_patients]:
            perms = db.ensure_legacy_care_team_row(patient_id, provider_id)
            print(f"[perms] MIGRATED legacy: provider={provider_id} patient={patient_id} "
                  f"perms={perms}", flush=True)
        else:
            print(f"[perms] FALLBACK all-true: provider={provider_id} patient={patient_id} "
                  f"(no care team or legacy row)", flush=True)
            return dict(_ALL_PERMS_TRUE)
    print(f"[perms] OK: provider={provider_id} patient={patient_id} perms={perms}", flush=True)
    return perms


def _strip_checkin_fields(checkins: list, perms: dict) -> list:
    result = []
    for c in checkins:
        c = dict(c)
        if not perms.get('mood_stress_sleep', True):
            c['mood_score'] = None
            c['stress_score'] = None
            c['sleep_hours'] = None
        if not perms.get('system_scores', True):
            for key in ('stability_score', 'stim_load', 'crash_risk',
                        'nervous_system_load', 'dopamine_efficiency',
                        'sleep_disruption_score', 'mood_distortion',
                        'nutrition_stability'):
                c[key] = None
        if not perms.get('advanced_data', True):
            c['extended_data'] = {}
        result.append(c)
    return result


def _apply_perms_to_patient_detail(detail: dict, perms: dict) -> dict:
    if not detail:
        return detail
    detail = dict(detail)
    if not perms.get('medication_data', True):
        detail['current_medications'] = []
    if not perms.get('journals_raw', True):
        detail['journals'] = []
    if not perms.get('journals_themes', True):
        detail['latest_summary'] = None
    if detail.get('checkins'):
        detail['checkins'] = _strip_checkin_fields(detail['checkins'], perms)
    if detail.get('recent_checkins'):
        detail['recent_checkins'] = _strip_checkin_fields(detail['recent_checkins'], perms)
    return detail


def _apply_perms_to_trends(trends: dict, perms: dict) -> dict:
    if not trends:
        return trends
    trends = dict(trends)
    if not perms.get('mood_stress_sleep', True):
        for k in ('mood', 'stress', 'sleep', 'energy'):
            trends.pop(k, None)
    if not perms.get('medication_data', True):
        trends.pop('medication_adherence', None)
        trends.pop('medication_timing', None)
        trends.pop('current_medications', None)
    if not perms.get('system_scores', True):
        # Use the exact keys returned by get_trends_data
        for k in ('stability_score', 'crash_risk', 'stim_load',
                  'nervous_system_load', 'mood_distortion', 'sleep_disruption'):
            trends.pop(k, None)
    if not perms.get('advanced_data', True):
        for k in ('focus', 'dissociation', 'sleep_quality', 'caffeine',
                  'irritability', 'motivation', 'perceived_stress',
                  'alcohol', 'exercise', 'sunlight', 'screen_time',
                  'social_quality', 'workload_friction'):
            trends.pop(k, None)
    return trends


def _apply_perms_to_brief(brief: dict, perms: dict) -> dict:
    if not brief:
        return brief
    brief = dict(brief)
    if not perms.get('mood_stress_sleep', True):
        for key in ('mood_avg', 'mood_baseline', 'mood_dir', 'mood_delta',
                    'stress_avg', 'stress_baseline', 'stress_dir', 'stress_delta',
                    'sleep_avg', 'sleep_baseline', 'sleep_dir', 'sleep_delta'):
            brief[key] = None
    if not perms.get('medication_data', True):
        brief['med_doses_logged'] = None
        brief['med_days_logged'] = None
    if not perms.get('journals_raw', True):
        brief['journal_count'] = 0
        brief['journal_themes'] = []
    return brief


def _current_user():
    token = _session_token()
    return auth_module.get_current_user(token)


def _require_patient():
    user = _current_user()
    if not user:
        return None, redirect(url_for('login_page'))
    if user['role'] != 'patient':
        return None, redirect(url_for('provider_dashboard'))
    return user, None


def _require_provider():
    user = _current_user()
    if not user:
        return None, redirect(url_for('login_page'))
    if user['role'] != 'provider':
        return None, redirect(url_for('home'))
    return user, None


# ══════════════════════════════════════════════════════════════════════════════
# PAGE ROUTES — server-rendered
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/')
def home():
    user = _current_user()
    if not user:
        return redirect(url_for('login_page'))
    if user['role'] == 'provider':
        return redirect(url_for('provider_dashboard'))

    profile = db.get_patient_profile(user['id'])
    streak = db.get_checkin_streak(user['id'])
    latest_summary = db.get_latest_summary(user['id'])
    first_name = user['full_name'].split()[0]
    proactive_insights = db.get_unseen_proactive_insights(user['id'])
    next_appt = db.get_patient_next_scheduled_appointment(user['id'])
    return render_template('patient/home.html',
                           user=user, profile=profile, streak=streak,
                           latest_summary=latest_summary,
                           first_name=first_name,
                           proactive_insights=proactive_insights,
                           next_appt=next_appt)


@app.route('/login')
def login_page():
    if _current_user():
        return redirect(url_for('home'))
    return render_template('auth/login.html')


@app.route('/login', methods=['POST'])
@limiter.limit("10 per minute")
def login_post():
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')
    result, error = auth_module.login_user(email, password)
    if error:
        flash(error, 'error')
        return render_template('auth/login.html', email=email)
    session['session_token'] = result['session_token']
    session['user_id'] = result['user_id']
    session['role'] = result['role']
    if result['role'] == 'provider':
        return redirect(url_for('provider_dashboard'))
    return redirect(url_for('home'))


@app.route('/register')
def register_page():
    if _current_user():
        return redirect(url_for('home'))
    invite_token = request.args.get('invite', '').strip()
    invite_email = request.args.get('email', '').strip()
    invite_context = None
    if invite_token:
        invite_context = db.get_patient_invite_by_token(invite_token)
    return render_template('auth/register.html',
                           invite_token=invite_token,
                           invite_email=invite_email or None,
                           invite_context=invite_context)


@app.route('/register', methods=['POST'])
def register_post():
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')
    confirm_password = request.form.get('confirm_password', '')
    full_name = request.form.get('full_name', '').strip()
    role = request.form.get('role', 'patient')
    invite_token = request.form.get('invite_token', '').strip()
    provider_type = request.form.get('provider_type', '').strip() or None
    # Rebuild invite context for re-rendering on error
    invite_context = db.get_patient_invite_by_token(invite_token) if invite_token else None

    # Validate provider_type when registering as provider
    valid_provider_types = ('psychiatrist', 'therapist', 'counselor')
    if role == 'provider' and provider_type not in valid_provider_types:
        flash('Please select a provider type (Psychiatrist, Therapist, or Counselor).', 'error')
        return render_template('auth/register.html', email=email, full_name=full_name, role=role,
                               provider_type=provider_type,
                               invite_token=invite_token, invite_email=email if invite_token else None,
                               invite_context=invite_context)

    if password != confirm_password:
        flash('Passwords do not match.', 'error')
        return render_template('auth/register.html', email=email, full_name=full_name, role=role,
                               provider_type=provider_type,
                               invite_token=invite_token, invite_email=email if invite_token else None,
                               invite_context=invite_context)
    result, error = auth_module.register_user(
        email, password, full_name, role,
        provider_type=provider_type if role == 'provider' else None,
    )
    if error:
        flash(error, 'error')
        return render_template('auth/register.html', email=email, full_name=full_name, role=role,
                               provider_type=provider_type,
                               invite_token=invite_token, invite_email=email if invite_token else None,
                               invite_context=invite_context)
    email_sent = result.get('email_sent', True)
    return render_template('auth/verify_sent.html', email=email, email_sent=email_sent)


@app.route('/resend-verification', methods=['GET', 'POST'])
def resend_verification():
    """Let a stuck pending_email user request a new verification link."""
    if request.method == 'GET':
        return render_template('auth/resend_verification.html')

    email = request.form.get('email', '').strip().lower()
    if not email:
        flash('Please enter your email address.', 'error')
        return render_template('auth/resend_verification.html')

    try:
        profile_res = db.supabase_admin.table('profiles').select(
            'id, full_name, status, email_verify_token'
        ).eq('email', email).limit(1).execute()
    except Exception:
        profile_res = None

    # Always show the same success message regardless of whether the address
    # exists — prevents email enumeration.
    if profile_res and profile_res.data:
        profile = profile_res.data[0]
        if profile.get('status') == 'pending_email':
            import uuid as _uuid
            token = profile.get('email_verify_token') or str(_uuid.uuid4())
            if not profile.get('email_verify_token'):
                db.supabase_admin.table('profiles').update(
                    {'email_verify_token': token}
                ).eq('id', profile['id']).execute()
            try:
                import email_utils as _eu
                _eu.send_verification_email(email, profile.get('full_name', ''), token)
            except Exception as e:
                app.logger.error(f"Resend verification failed for {email}: {e}")

    flash('If that email has a pending account, a new verification link is on its way.', 'success')
    return render_template('auth/resend_verification.html')


@app.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit("5 per hour", methods=['POST'])
def forgot_password_page():
    if _current_user():
        return redirect(url_for('home'))
    if request.method == 'GET':
        return render_template('auth/forgot_password.html')

    email = request.form.get('email', '').strip().lower()
    if not email:
        flash('Please enter your email address.', 'error')
        return render_template('auth/forgot_password.html')

    import email_utils
    user_id, full_name = auth_module.initiate_password_reset(email)
    if user_id:
        token = auth_module.generate_reset_token(user_id, app.secret_key)
        try:
            email_utils.send_password_reset_email(email, full_name or 'there', token)
        except Exception as e:
            reset_url = f"{email_utils.APP_URL}/reset-password?token={token}"
            app.logger.error(f"Failed to send reset email to {email}: {e} — RESET URL: {reset_url}")

    # Always show success — don't reveal whether the email exists
    flash('If that email has a CognaSync account, a reset link is on its way. Check your inbox.', 'success')
    return render_template('auth/forgot_password.html')


@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password_page():
    if request.method == 'GET':
        token = request.args.get('token', '').strip()
        if not token or not auth_module.verify_reset_token(token, app.secret_key):
            flash('This reset link has expired or is invalid. Please request a new one.', 'error')
            return redirect(url_for('forgot_password_page'))
        return render_template('auth/reset_password.html', token=token)

    token = request.form.get('token', '').strip()
    new_password = request.form.get('password', '')
    confirm = request.form.get('confirm_password', '')
    if new_password != confirm:
        flash('Passwords do not match.', 'error')
        return render_template('auth/reset_password.html', token=token)

    ok, error = auth_module.reset_password_with_token(token, new_password, app.secret_key)
    if not ok:
        flash(error, 'error')
        return render_template('auth/reset_password.html', token=token)

    flash('Your password has been updated. You can now sign in.', 'success')
    return redirect(url_for('login_page'))


@app.route('/verify-email')
def verify_email():
    import email_utils
    token = request.args.get('token', '').strip()
    if not token:
        flash('Invalid verification link.', 'error')
        return redirect(url_for('login_page'))
    profile_res = db.supabase_admin.table('profiles').select('id, email, full_name, role, status').eq('email_verify_token', token).execute()
    if not profile_res.data:
        flash('Verification link is invalid or has already been used.', 'error')
        return redirect(url_for('login_page'))
    profile = profile_res.data[0]
    if profile['status'] != 'pending_email':
        flash('This link has already been used.', 'error')
        return redirect(url_for('login_page'))
    db.supabase_admin.table('profiles').update({
        'status': 'pending_approval',
        'email_verify_token': None,
    }).eq('id', profile['id']).execute()
    secret_key = app.config['SECRET_KEY']
    email_utils.send_admin_notification(
        profile['email'], profile['full_name'], profile['role'],
        profile['id'], secret_key,
    )
    return render_template('auth/pending_approval.html', email=profile['email'])


@app.route('/admin/approve')
def admin_approve():
    import email_utils
    user_id = request.args.get('id', '').strip()
    sig = request.args.get('sig', '').strip()
    if not user_id or not sig:
        return 'Invalid approval link.', 400
    secret_key = app.config['SECRET_KEY']
    expected = email_utils.approval_sig(user_id, secret_key)
    if not hmac.compare_digest(expected, sig):
        return 'Invalid or tampered approval link.', 403
    profile_res = db.supabase_admin.table('profiles').select('id, email, full_name, status, role').eq('id', user_id).execute()
    if not profile_res.data:
        return 'User not found.', 404
    profile = profile_res.data[0]
    if profile['status'] == 'approved':
        return render_template('auth/approval_done.html', already=True, email=profile['email'])
    db.supabase_admin.table('profiles').update({'status': 'approved'}).eq('id', user_id).execute()
    email_utils.send_account_approved_email(profile['email'], profile['full_name'], profile.get('role', 'patient'))
    if profile.get('role') == 'patient':
        db.process_pending_invites(profile['email'], user_id)
    return render_template('auth/approval_done.html', already=False, email=profile['email'])


# ── Admin Panel ───────────────────────────────────────────────────────────────

def _require_admin():
    """Return a redirect if the admin session is not authenticated."""
    if not session.get('admin_authed'):
        return redirect(url_for('admin_login_page'))
    return None


@app.route('/admin/login', methods=['GET'])
def admin_login_page():
    if session.get('admin_authed'):
        return redirect(url_for('admin_panel'))
    return render_template('admin/login.html')


@app.route('/admin/login', methods=['POST'])
def admin_login_post():
    secret = request.form.get('secret', '').strip()
    expected = os.environ.get('INTERNAL_SECRET', '')
    if not expected:
        flash('Admin access is not configured on this server.', 'error')
        return redirect(url_for('admin_login_page'))
    if not hmac.compare_digest(secret, expected):
        flash('Incorrect password.', 'error')
        return redirect(url_for('admin_login_page'))
    session['admin_authed'] = True
    return redirect(url_for('admin_panel'))


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_authed', None)
    return redirect(url_for('admin_login_page'))


@app.route('/admin')
def admin_panel():
    redir = _require_admin()
    if redir:
        return redir
    pending_res = (
        db.supabase_admin.table('profiles')
        .select('id, full_name, email, role, status, created_at')
        .eq('status', 'pending_approval')
        .order('created_at', desc=False)
        .execute()
    )
    approved_res = (
        db.supabase_admin.table('profiles')
        .select('id, full_name, email, role, status, created_at, updated_at')
        .eq('status', 'approved')
        .order('created_at', desc=True)
        .limit(20)
        .execute()
    )
    return render_template(
        'admin/panel.html',
        pending=pending_res.data or [],
        approved=approved_res.data or [],
    )


@app.route('/admin/approve/<user_id>', methods=['POST'])
def admin_approve_user(user_id):
    import email_utils
    redir = _require_admin()
    if redir:
        return redir
    profile_res = (
        db.supabase_admin.table('profiles')
        .select('id, email, full_name, status, role')
        .eq('id', user_id)
        .execute()
    )
    if not profile_res.data:
        flash('User not found.', 'error')
        return redirect(url_for('admin_panel'))
    profile = profile_res.data[0]
    if profile['status'] == 'approved':
        flash(f'{profile["email"]} is already approved.', 'error')
        return redirect(url_for('admin_panel'))
    db.supabase_admin.table('profiles').update({'status': 'approved'}).eq('id', user_id).execute()
    email_utils.send_account_approved_email(profile['email'], profile['full_name'], profile.get('role', 'patient'))
    if profile.get('role') == 'patient':
        db.process_pending_invites(profile['email'], user_id)
    flash(f'Approved {profile["email"]}.', 'success')
    return redirect(url_for('admin_panel'))


@app.route('/admin/reject/<user_id>', methods=['POST'])
def admin_reject_user(user_id):
    redir = _require_admin()
    if redir:
        return redir
    profile_res = (
        db.supabase_admin.table('profiles')
        .select('id, email, full_name, status')
        .eq('id', user_id)
        .execute()
    )
    if not profile_res.data:
        flash('User not found.', 'error')
        return redirect(url_for('admin_panel'))
    profile = profile_res.data[0]
    db.supabase_admin.table('profiles').update({'status': 'rejected'}).eq('id', user_id).execute()
    flash(f'Rejected {profile["email"]}.', 'success')
    return redirect(url_for('admin_panel'))


@app.route('/logout')
def logout():
    token = _session_token()
    if token:
        auth_module.logout_user(token)
    session.clear()
    return redirect(url_for('login_page'))


@app.route('/checkin')
def checkin_page():
    user, redir = _require_patient()
    if redir:
        return redir
    profile = db.get_patient_profile(user['id'])
    meds = profile.get('current_medications', []) if profile else []
    return render_template('patient/checkin_react.html', user=user, medications=meds)


@app.route('/journal')
def journal_page():
    user, redir = _require_patient()
    if redir:
        return redir
    return render_template('patient/journal_react.html', user=user)


@app.route('/medication')
def medication_page():
    user, redir = _require_patient()
    if redir:
        return redir
    profile = db.get_patient_profile(user['id'])
    meds = profile.get('current_medications', []) if profile else []
    med_names = db.get_medication_names()
    return render_template('patient/medication.html', user=user,
                           medications=meds, med_names=med_names)


@app.route('/summary')
def summary_page():
    user, redir = _require_patient()
    if redir:
        return redir
    summaries = db.get_summaries(user['id'])
    return render_template('patient/summary.html', user=user, summaries=summaries)


@app.route('/trends')
def trends_page():
    user, redir = _require_patient()
    if redir:
        return redir
    return render_template('patient/trends.html', user=user)


@app.route('/help')
def help_page():
    user = _current_user()
    if not user:
        return redirect(url_for('login_page'))
    if user['role'] == 'provider':
        return render_template('help/provider.html', user=user)
    return render_template('help/patient.html', user=user)


@app.route('/welcome')
def welcome_page():
    role = request.args.get('role', 'patient')
    if role not in ('patient', 'provider'):
        role = 'patient'
    return render_template('help/welcome.html', role=role)


@app.route('/settings')
def settings_page():
    user, redir = _require_patient()
    if redir:
        return redir
    profile = db.get_patient_profile(user['id'])
    linked_provider = None
    if profile and profile.get('provider_id'):
        linked_provider = db.get_user_by_id(profile['provider_id'])
    return render_template('patient/settings.html', user=user, profile=profile,
                           linked_provider=linked_provider)


@app.route('/voice-notes')
def patient_voice_notes_page():
    user, redir = _require_patient()
    if redir:
        return redir
    notes = db.get_voice_notes_for_patient(user['id'], limit=20)
    return render_template('patient/voice_notes.html', user=user, voice_notes=notes or [])


@app.route('/provider')
def provider_dashboard():
    user, redir = _require_provider()
    if redir:
        return redir
    patients = db.get_provider_patients_with_stats(user['id'])

    # Attach Mode D flags (substance + safety) to each patient record
    for p in patients:
        pid = p.get('id') or p.get('user_id') or p.get('patient_id', '')
        if pid:
            try:
                flags = db.get_patient_flags(pid, days=30)
                p['flags'] = flags
            except Exception:
                p['flags'] = {'substance': None, 'safety': None}
        else:
            p['flags'] = {'substance': None, 'safety': None}

    return render_template('provider/dashboard.html', user=user, patients=patients,
                           today_str=date.today().isoformat())


def _build_suggested_questions(trends, alerts, patient):
    """Derive 3-5 AI-suggested interview questions from this patient's data."""
    questions = []
    mood_t   = (trends.get('mood') or {})
    sleep_t  = (trends.get('sleep') or {})
    stress_t = (trends.get('stress') or {})
    adh      = trends.get('medication_adherence', 0)
    meds     = patient.get('current_medications') or []

    if mood_t.get('trend') == 'decreasing':
        questions.append({
            'category': 'Mood',
            'text': f"Your records show mood averaging {mood_t.get('average','?')}/10 and trending downward. "
                    "What's been contributing to that from your perspective?"
        })
    elif mood_t.get('average') and float(mood_t['average']) < 5:
        questions.append({
            'category': 'Mood',
            'text': f"Mood has averaged {mood_t['average']}/10 this period. "
                    "Can you walk me through what a typical day has felt like?"
        })

    if sleep_t.get('average') and float(sleep_t['average']) < 6.5:
        questions.append({
            'category': 'Sleep',
            'text': f"You're averaging {sleep_t['average']} hours of sleep. "
                    "Is that disruption mainly falling asleep, staying asleep, or waking too early?"
        })

    if stress_t.get('average') and float(stress_t['average']) > 6:
        questions.append({
            'category': 'Stress',
            'text': f"Stress has been elevated at {stress_t['average']}/10 on average. "
                    "What's been the biggest driver of that?"
        })

    if meds and adh and adh < 80:
        questions.append({
            'category': 'Medication',
            'text': f"Medication logs show about {adh}% adherence this period. "
                    "Are there specific days or situations where taking it becomes harder?"
        })
    elif meds:
        med_names = ', '.join(m.get('name', '').title() for m in meds[:2])
        questions.append({
            'category': 'Medication',
            'text': f"How has {med_names} been feeling for you? Any side effects or timing issues?"
        })

    if not questions:
        questions.append({
            'category': 'Functioning',
            'text': "How has your day-to-day functioning been since we last met — at work, at home, socially?"
        })

    return questions[:5]


def _build_alerts(trends, days):
    """Build clinical alert list from trends data."""
    alerts = []
    MIN_OBS = 21
    n = trends.get('checkin_count', trends.get('total_checkins', 0))
    mood_t = trends.get('mood', {})
    if (mood_t.get('trend') == 'decreasing' and n >= MIN_OBS
            and mood_t.get('p_value', 1) <= 0.05
            and mood_t.get('r_squared', 0) >= 0.25):
        alerts.append({'level': 'urgent', 'title': 'Mood Declining',
            'desc': f"Mood trending downward — average {mood_t['average']}/10 over {days} days "
                    f"(R²={mood_t['r_squared']}, p={mood_t['p_value']})."})
    if 0 < trends.get('medication_adherence', 0) < 80 and n >= MIN_OBS:
        alerts.append({'level': 'warning', 'title': 'Low Medication Adherence',
            'desc': f"Adherence at {trends['medication_adherence']}% — below the 80% threshold."})
    stress_t = trends.get('stress', {})
    if (stress_t.get('trend') == 'increasing' and stress_t.get('average', 0) > 6
            and n >= MIN_OBS
            and stress_t.get('p_value', 1) <= 0.05
            and stress_t.get('r_squared', 0) >= 0.25):
        alerts.append({'level': 'warning', 'title': 'Elevated Stress Trend',
            'desc': f"Stress trending upward — average {stress_t['average']}/10 over {days} days "
                    f"(R²={stress_t['r_squared']}, p={stress_t['p_value']})."})
    return alerts


@app.route('/provider/patient/<patient_id>')
def provider_patient_detail(patient_id):
    """Patient overview: key stats + appointment history."""
    user, redir = _require_provider()
    if redir:
        return redir
    if not _provider_owns_patient(user['id'], patient_id):
        flash('Patient not found', 'error')
        return redirect(url_for('provider_dashboard'))

    patient = db.get_patient_detail(patient_id, days=30)
    if not patient:
        flash('Patient not found', 'error')
        return redirect(url_for('provider_dashboard'))

    try:
        app.logger.info(f"[patient_detail] step=perms patient={patient_id}")
        perms        = _get_provider_perms(user['id'], patient_id)
        app.logger.info(f"[patient_detail] step=apply_perms")
        patient      = _apply_perms_to_patient_detail(patient, perms)
        app.logger.info(f"[patient_detail] step=get_patients")
        patients     = db.get_provider_patients(user['id'])
        app.logger.info(f"[patient_detail] step=trends")
        trends       = _apply_perms_to_trends(db.get_trends_data(patient_id, days=30) or {}, perms)
        app.logger.info(f"[patient_detail] step=appointments")
        appointments = db.get_patient_appointments(user['id'], patient_id)
        app.logger.info(f"[patient_detail] step=interactions")
        interactions = db.check_medication_interactions(patient_id) if perms.get('medication_data', True) else []
        app.logger.info(f"[patient_detail] step=crisis")
        current_p = next((p for p in patients if str(p['patient_id']) == str(patient_id)), {})
        patient_has_crisis = current_p.get('suicide_risk', False)
        patient_crisis_context = current_p.get('suicide_risk_context', [])
        crisis_history = db.get_crisis_history(patient_id)

        last_checkin_date = patient.get('last_checkin_date')
        days_since_last_checkin = None
        if last_checkin_date:
            try:
                days_since_last_checkin = (date.today() - date.fromisoformat(last_checkin_date)).days
            except Exception:
                pass

        app.logger.info(f"[patient_detail] step=care_role")
        provider_role = db.get_care_team_member_role(user['id'], patient_id) or 'psychiatrist'
        app.logger.info(f"[patient_detail] step=render")

        return render_template('provider/patient_detail.html',
                               user=user, patient=patient,
                               patients=patients,
                               trends=trends,
                               appointments=appointments,
                               interactions=interactions,
                               today_str=date.today().isoformat(),
                               patient_has_crisis=patient_has_crisis,
                               patient_crisis_context=patient_crisis_context,
                               crisis_history=crisis_history,
                               days_since_last_checkin=days_since_last_checkin,
                               last_checkin_date=last_checkin_date,
                               provider_role=provider_role,
                               perms=perms)
    except Exception:
        app.logger.exception(f"Error rendering patient detail for {patient_id}")
        flash("An error occurred loading this patient's details. The issue has been logged.", 'error')
        return redirect(url_for('provider_dashboard'))


@app.route('/provider/patient/<patient_id>/appointment/new', methods=['POST'])
def provider_appointment_new(patient_id):
    """Create a new appointment session and redirect to the workspace."""
    user, redir = _require_provider()
    if redir:
        return redir
    if not _provider_owns_patient(user['id'], patient_id):
        flash('Patient not found', 'error')
        return redirect(url_for('provider_dashboard'))

    period_days = int(request.form.get('period_days', 30))
    appt = db.create_provider_appointment(user['id'], patient_id, period_days)
    if not appt:
        flash('Could not create appointment — please try again.', 'error')
        return redirect(url_for('provider_patient_detail', patient_id=patient_id))

    return redirect(url_for('provider_appointment_workspace',
                            patient_id=patient_id, appt_id=appt['id']))


@app.route('/provider/patient/<patient_id>/appointment/<appt_id>')
def provider_appointment_workspace(patient_id, appt_id):
    """Active appointment workspace."""
    user, redir = _require_provider()
    if redir:
        return redir
    if not _provider_owns_patient(user['id'], patient_id):
        flash('Patient not found', 'error')
        return redirect(url_for('provider_dashboard'))

    appt = db.get_provider_appointment(appt_id, user['id'])
    if not appt or str(appt['patient_id']) != str(patient_id):
        flash('Appointment not found', 'error')
        return redirect(url_for('provider_patient_detail', patient_id=patient_id))

    try:
        days = int(request.args.get('days', appt.get('period_days', 30)))
        if days not in (7, 14, 30, 60, 90):
            days = appt.get('period_days', 30)
    except (TypeError, ValueError):
        days = appt.get('period_days', 30)
    patient = db.get_patient_detail(patient_id, days=days)
    if not patient:
        flash('Patient not found', 'error')
        return redirect(url_for('provider_dashboard'))

    perms        = _get_provider_perms(user['id'], patient_id)
    patient      = _apply_perms_to_patient_detail(patient, perms)
    patients     = db.get_provider_patients(user['id'])
    trends       = _apply_perms_to_trends(db.get_trends_data(patient_id, days=days) or {}, perms)
    summaries    = db.get_summaries(patient_id) if perms.get('journals_themes', True) else []
    timing_stats = db.get_medication_timing_stats(patient_id, days=days) if perms.get('medication_data', True) else {}
    interactions = db.check_medication_interactions(patient_id) if perms.get('medication_data', True) else []
    alerts       = _build_alerts(trends, days)

    # Journals scoped to the appointment's review window
    try:
        appt_start_str = (appt.get('started_at') or date.today().isoformat())[:10]
        appt_start_dt  = date.fromisoformat(appt_start_str)
    except Exception:
        appt_start_dt  = date.today()
    window_start = (appt_start_dt - timedelta(days=days)).isoformat()
    window_end   = appt_start_dt.isoformat()
    journals = (
        db.get_journals_in_range(patient_id, window_start, window_end, shared_only=True)
        if perms.get('journals_raw', True) else []
    )

    current_p = next((p for p in patients if str(p['patient_id']) == str(patient_id)), {})
    patient_has_crisis = current_p.get('suicide_risk', False)
    patient_crisis_context = current_p.get('suicide_risk_context', [])

    # Build AI-suggested questions from alert data + trends
    ai_questions = _build_suggested_questions(trends, alerts, patient)

    return render_template('provider/appointment.html',
                           user=user, patient=patient,
                           patients=patients,
                           appt=appt,
                           trends=trends,
                           summaries=summaries,
                           journals=journals,
                           window_start=window_start,
                           window_end=window_end,
                           timing_stats=timing_stats,
                           interactions=interactions,
                           alerts=alerts,
                           selected_days=days,
                           today_str=date.today().isoformat(),
                           patient_has_crisis=patient_has_crisis,
                           patient_crisis_context=patient_crisis_context,
                           ai_questions=ai_questions,
                           perms=perms)


@app.route('/provider/patient/<patient_id>/hub')
def provider_patient_hub(patient_id):
    """Comprehensive patient hub — check-ins, voice, sessions, meds, wearables."""
    user, redir = _require_provider()
    if redir:
        return redir
    if not _provider_owns_patient(user['id'], patient_id):
        flash('Patient not found', 'error')
        return redirect(url_for('provider_dashboard'))

    patient  = db.get_patient_detail(patient_id, days=30)
    if not patient:
        flash('Patient not found', 'error')
        return redirect(url_for('provider_dashboard'))

    checkins     = db.get_checkins(patient_id, days=30)
    voice_notes  = db.get_voice_notes_for_patient(patient_id, limit=20)
    meds         = db.get_user_medications(patient_id)
    med_events   = db.get_medication_events(patient_id, days=30)
    appointments = db.get_patient_appointments(user['id'], patient_id)
    sessions     = db.get_clinical_sessions_for_period(patient_id, limit=20)
    journals     = db.get_journals(patient_id, limit=10, shared_only=False)
    care_team    = db.get_patient_care_team(patient_id)
    next_appt    = db.get_patient_next_scheduled_appointment(patient_id)

    # Quick risk snapshot from most recent checkin scores
    recent_ci = checkins[0] if checkins else None
    risk_snap = None
    if recent_ci:
        ext = recent_ci.get('extended_data') or {}
        risk_snap = {
            'mood':       recent_ci.get('mood_score'),
            'stability':  recent_ci.get('stability_score'),
            'crash_risk': recent_ci.get('crash_risk'),
            'stim_load':  recent_ci.get('stim_load'),
            'date':       (recent_ci.get('checkin_date') or '')[:10],
        }

    return render_template(
        'provider/patient_hub.html',
        user=user,
        patient=patient,
        checkins=checkins,
        voice_notes=voice_notes or [],
        medications=meds or [],
        medication_events=med_events or [],
        appointments=appointments or [],
        sessions=sessions or [],
        journals=journals or [],
        care_team=care_team or {'active': [], 'pending': []},
        next_appt=next_appt,
        risk_snap=risk_snap,
    )


@app.route('/provider/patient/<patient_id>/trends')
def provider_patient_trends(patient_id):
    user, redir = _require_provider()
    if redir:
        return redir
    if not _provider_owns_patient(user['id'], patient_id):
        flash('Patient not found', 'error')
        return redirect(url_for('provider_dashboard'))
    patient = db.get_patient_detail(patient_id, days=1)
    patient_name = patient['full_name'] if patient else 'Patient'
    return render_template('patient/trends.html',
                           provider_view=True,
                           provider_patient_id=patient_id,
                           provider_patient_name=patient_name)


@app.route('/provider/patient/<patient_id>/summary/print')
@limiter.limit("10/hour")
def provider_summary_print(patient_id):
    """Render a print-optimized Mode C clinical summary.

    If ?brief_id=<uuid> is provided, renders the already-generated saved brief
    (same text the provider saw in the modal). Otherwise generates fresh.
    This prevents the print version from being a different Claude call.
    """
    import claude_api
    user, redir = _require_provider()
    if redir:
        return redir
    if not _provider_owns_patient(user['id'], patient_id):
        flash('Patient not found', 'error')
        return redirect(url_for('provider_dashboard'))

    days = min(int(request.args.get('days', 30)), 365)
    end_dt = date.today()
    start_dt = end_dt - timedelta(days=days)
    period_start = start_dt.isoformat()
    period_end   = end_dt.isoformat()

    patient = db.get_patient_detail(patient_id, days=days)
    if not patient:
        flash('Patient not found', 'error')
        return redirect(url_for('provider_dashboard'))

    summary_text = None
    error_msg    = None
    chart_data   = None
    provider_type = user.get('provider_type') or 'psychiatrist'

    # ── Fast path: render a previously saved brief by ID ─────────────────────
    brief_id = request.args.get('brief_id')
    if brief_id:
        saved = db.get_summary_by_id(brief_id, patient_id)
        if saved:
            summary_text = saved.get('summary_text') or saved.get('content', '')
            period_start = saved.get('date_range_start') or period_start
            period_end   = saved.get('date_range_end')   or period_end
            # For psychiatry, compute chart_data from checkins (no Claude call)
            if provider_type == 'psychiatrist':
                try:
                    perms = _get_provider_perms(user['id'], patient_id)
                    _ci   = _strip_checkin_fields(
                        db.get_checkins_in_range(patient_id, period_start, period_end), perms
                    )
                    if _ci:
                        chart_data = claude_api._build_chart_data(_ci)
                except Exception as _cde:
                    app.logger.warning(f'[print] chart_data fast path: {_cde}')
        else:
            error_msg = 'Brief not found or access denied.'

    # ── Slow path: generate fresh ─────────────────────────────────────────────
    if not summary_text and not error_msg:
        perms    = _get_provider_perms(user['id'], patient_id)
        checkins = _strip_checkin_fields(db.get_checkins_in_range(patient_id, period_start, period_end), perms)
        journals = db.get_journals_in_range(patient_id, period_start, period_end) if perms.get('journals_raw', True) else []

        if checkins or journals:
            flags           = db.get_patient_flags(patient_id, days=days)
            symptom_patterns = db.find_symptom_correlations(patient_id, days=days)
            session_context = db.get_clinical_sessions_for_period(
                patient_id=patient_id, period_start=period_start,
                period_end=period_end, limit=10,
            )
            # Voice note raw-text fallback
            raw_voice_transcripts = []
            try:
                known_dates = {s['session_date'] for s in session_context if s.get('session_date')}
                for vn in db.get_voice_notes_for_period(patient_id, period_start, period_end, limit=5):
                    vn_date = (vn.get('created_at') or '')[:10]
                    text    = (vn.get('transcript') or '').strip()
                    if text and vn_date not in known_dates:
                        raw_voice_transcripts.append({'date': vn_date, 'transcript': text})
            except Exception as _ve:
                app.logger.warning(f'[print] voice note fallback: {_ve}')

            engagement_data = db.compute_engagement_stats(
                patient_id, days=days,
                period_start=period_start, period_end=period_end,
            )

            try:
                if provider_type == 'psychiatrist':
                    result = claude_api.generate_psychiatry_summary(
                        checkins, journals,
                        days=days,
                        period_start=period_start,
                        period_end=period_end,
                        symptom_patterns=symptom_patterns,
                        substance_flags=flags.get('substance'),
                        safety_flags=flags.get('safety'),
                        session_context=session_context or [],
                        raw_voice_transcripts=raw_voice_transcripts,
                        patient_name=patient.get('full_name'),
                        engagement_data=engagement_data,
                    )
                    chart_data = result.get('chart_data')
                elif provider_type in ('therapist', 'counselor'):
                    result = claude_api.generate_therapy_summary(
                        checkins, journals,
                        days=days,
                        period_start=period_start,
                        period_end=period_end,
                        safety_flags=flags.get('safety'),
                        substance_flags=flags.get('substance'),
                        session_context=session_context or [],
                        raw_voice_transcripts=raw_voice_transcripts,
                        engagement_data=engagement_data,
                    )
                else:
                    lexical_data    = db.compute_lexical_diversity(patient_id, days=max(days, 30))
                    readability_data = db.compute_readability(patient_id, days=max(days, 30))
                    what_worked     = db.get_what_worked_patterns(patient_id, days=max(days, 60))
                    result = claude_api.generate_appointment_summary(
                        checkins, journals,
                        days=days,
                        period_start=period_start,
                        period_end=period_end,
                        audience='provider',
                        symptom_patterns=symptom_patterns,
                        substance_flags=flags.get('substance'),
                        safety_flags=flags.get('safety'),
                        what_worked=what_worked,
                        lexical_data=lexical_data,
                        readability_data=readability_data,
                        session_context=session_context or [],
                        raw_voice_transcripts=raw_voice_transcripts,
                        engagement_data=engagement_data,
                    )
                summary_text = result['text']
            except RuntimeError as e:
                error_msg = str(e)
        else:
            error_msg = 'No check-in or journal data found for this period.'

    return render_template(
        'provider/summary_print.html',
        patient=patient,
        provider_name=user.get('full_name', 'Provider'),
        summary_text=summary_text,
        error_msg=error_msg,
        period_start=period_start,
        period_end=period_end,
        days=days,
        generated_at=date.today().isoformat(),
        provider_type=provider_type,
        chart_data=chart_data,
    )


# ══════════════════════════════════════════════════════════════════════════════
# API ROUTES — JSON
# ══════════════════════════════════════════════════════════════════════════════

def _api_user(required_role=None):
    token = (
        (request.get_json(silent=True) or {}).get('session_token')
        or request.args.get('session_token')
        or request.headers.get('X-Session-Token')
        or session.get('session_token')
    )
    try:
        user = auth_module.get_current_user(token)
    except Exception as e:
        print(f"_api_user auth error: {e}")
        return None, (jsonify({'error': 'Authentication error'}), 500)
    if not user:
        return None, (jsonify({'error': 'Authentication required'}), 401)
    if required_role and user['role'] != required_role:
        return None, (jsonify({'error': f'{required_role.title()} access required'}), 403)
    return user, None


# ── Auth API ──────────────────────────────────────────────────────────────────

@app.route('/api/auth/register', methods=['POST'])
@limiter.limit("5 per minute")
def api_register():
    data = request.json or {}
    result, error = auth_module.register_user(
        data.get('email', ''),
        data.get('password', ''),
        data.get('full_name', ''),
        data.get('role', 'patient'),
    )
    if error:
        return jsonify({'error': error}), 400
    return jsonify({
        'user_id': result['user_id'],
        'email': result['email'],
        'role': result['role'],
        'session_token': result['session_token'],
        'message': 'Account created successfully',
    }), 201


@app.route('/api/auth/login', methods=['POST'])
@limiter.limit("10 per minute")
def api_login():
    data = request.json or {}
    result, error = auth_module.login_user(
        data.get('email', ''), data.get('password', ''))
    if error:
        return jsonify({'error': error}), 401
    return jsonify(result), 200


@app.route('/api/auth/logout', methods=['POST'])
def api_logout():
    data = request.json or {}
    token = data.get('session_token') or request.args.get('session_token')
    if token:
        auth_module.logout_user(token)
    return jsonify({'message': 'Logged out successfully'}), 200


# ── Check-in API ──────────────────────────────────────────────────────────────

@app.route('/api/checkins', methods=['POST'])
def api_create_checkin():
    user, err = _api_user('patient')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        mood = int(data.get('mood_score', 0))
        stress = int(data.get('stress_score', 0))
        sleep = float(data.get('sleep_hours', 0))
    except (ValueError, TypeError):
        return jsonify({'error': 'mood_score, stress_score, and sleep_hours must be numeric'}), 400

    if not (0 <= mood <= 10):
        return jsonify({'error': 'mood_score must be 0-10'}), 400
    if not (0 <= stress <= 10):
        return jsonify({'error': 'stress_score must be 0-10'}), 400
    if not (0 <= sleep <= 24):
        return jsonify({'error': 'sleep_hours must be 0-24'}), 400

    checkin_type = data.get('checkin_type', 'on_demand')
    if checkin_type not in ('morning', 'afternoon', 'evening', 'on_demand'):
        checkin_type = 'on_demand'

    raw_date = data.get('date', date.today().isoformat())
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', str(raw_date)):
        raw_date = date.today().isoformat()

    notes = data.get('notes', '')

    # ── Crisis check BEFORE DB write — must not depend on AI availability ────
    if claude_api.check_crisis(notes):
        # Still persist the check-in so the provider can see it, but skip AI
        try:
            checkin_id = db.create_checkin(
                patient_id=user['id'],
                date_str=raw_date,
                time_of_day=data.get('time_of_day', 'self-prompted'),
                mood_score=mood,
                medications=data.get('medications', []),
                sleep_hours=sleep,
                stress_score=stress,
                symptoms=data.get('symptoms', ''),
                notes=notes,
                extended_data=data.get('extended_data'),
                checkin_type=checkin_type,
            )
        except Exception as e:
            app.logger.error("create_checkin (crisis path) failed: %s", e)
            checkin_id = None
        return jsonify({
            'checkin_id': checkin_id,
            'patient_id': user['id'],
            'message': 'Check-in recorded',
            'ai_insight': claude_api.CRISIS_RESPONSE,
            'alert': 'crisis',
        }), 201

    try:
        checkin_id = db.create_checkin(
            patient_id=user['id'],
            date_str=raw_date,
            time_of_day=data.get('time_of_day', 'self-prompted'),
            mood_score=mood,
            medications=data.get('medications', []),
            sleep_hours=sleep,
            stress_score=stress,
            symptoms=data.get('symptoms', ''),
            notes=notes,
            extended_data=data.get('extended_data'),
            checkin_type=checkin_type,
        )
    except Exception as e:
        app.logger.error("create_checkin failed: %s", e)
        return jsonify({'error': 'Failed to create check-in'}), 500

    if not checkin_id:
        return jsonify({'error': 'Failed to create check-in'}), 500

    # Mirror taken medications into medication_events so the home-screen tracker shows them.
    taken_meds = [m for m in data.get('medications', []) if m.get('taken')]
    if taken_meds:
        existing_names = {(log.get('name') or '').lower() for log in db.get_today_dose_logs(user['id'], raw_date)}
        for med in taken_meds:
            name = (med.get('name') or '').strip()
            if not name or name.lower() in existing_names:
                continue
            dose_raw = str(med.get('dose') or '').strip()
            time_taken = str(med.get('time_taken') or '').strip() or None
            med_id = db.find_or_create_profile_medication(user['id'], name, dose_raw)
            if med_id:
                dose_num = re.sub(r'[^\d.]', '', dose_raw)
                db.log_medication_event(
                    user_id=user['id'],
                    medication_id=med_id,
                    event_date=raw_date,
                    actual_time=None,
                    dose=float(dose_num) if dose_num else None,
                    status='TAKEN',
                    notes=time_taken,
                )

    ai_insight = None
    try:
        baseline = db.get_checkin_baseline(user['id'], days=7)
        checkin_snapshot = {
            'mood_score': mood, 'stress_score': stress, 'sleep_hours': sleep,
            'notes': notes,
            'extended_data': data.get('extended_data'),
        }
        result = claude_api.analyze_checkin(checkin_snapshot, checkin_type, baseline)
        if result.get('status') == 'safe' and result.get('text'):
            ai_insight = result['text']
            db.update_checkin_insights(checkin_id, ai_insight)
    except Exception as _ai_err:
        app.logger.error("AI insight generation failed: %s", _ai_err, exc_info=True)

    # ── Proactive pattern detection (non-blocking) ───────────────────
    try:
        patterns = db.detect_proactive_patterns(user['id'])
        for p in patterns:
            result = claude_api.generate_proactive_insight(
                p['pattern_type'], p['supporting_data']
            )
            if result.get('status') == 'safe' and result.get('text'):
                db.save_proactive_insight(
                    user['id'], p['pattern_type'],
                    result['text'], p['supporting_data']
                )
    except Exception as _pi_err:
        app.logger.error("Proactive insight generation failed: %s", _pi_err, exc_info=True)

    return jsonify({
        'checkin_id': checkin_id,
        'patient_id': user['id'],
        'message': 'Check-in recorded successfully',
        'ai_insight': ai_insight,
    }), 201


@app.route('/api/proactive-insights', methods=['GET'])
def api_proactive_insights():
    """Return unseen proactive insights for the logged-in patient."""
    user, err = _api_user('patient')
    if err:
        return err
    insights = db.get_unseen_proactive_insights(user['id'])
    for ins in insights:
        if not ins.get('seen_at'):
            db.mark_proactive_insight_seen(user['id'], ins['id'])
    return jsonify({'insights': insights}), 200


@app.route('/api/proactive-insights/<insight_id>/dismiss', methods=['POST'])
def api_dismiss_proactive_insight(insight_id):
    """Dismiss a proactive insight so it no longer appears on the dashboard."""
    user, err = _api_user('patient')
    if err:
        return err
    ok = db.dismiss_proactive_insight(user['id'], insight_id)
    return jsonify({'ok': ok}), 200 if ok else 500


@app.route('/api/what-worked', methods=['GET'])
def api_what_worked():
    """Return what-worked pattern data + AI narrative for the logged-in patient.

    Query params:
        days (int, default 60): look-back window for pattern detection
    """
    user, err = _api_user('patient')
    if err:
        return err

    days = min(int(request.args.get('days', 60)), 180)
    patterns = db.get_what_worked_patterns(user['id'], days=days)

    if patterns is None:
        return jsonify({
            'sufficient_data': False,
            'patterns':        [],
            'narrative':       None,
            'good_day_count':  None,
            'total_days':      None,
        }), 200

    result = claude_api.generate_what_worked_summary(patterns)
    narrative = result.get('text') if result.get('status') == 'safe' else None

    return jsonify({
        'sufficient_data': True,
        'patterns':        patterns['patterns'],
        'narrative':       narrative,
        'good_day_count':  patterns['good_day_count'],
        'total_days':      patterns['total_days'],
        'good_day_threshold': patterns['good_day_threshold'],
        'days_window':     patterns['days_window'],
    }), 200


@app.route('/api/medications', methods=['GET', 'POST'])
def api_medications():
    """GET: List user's medications. POST: Create new medication."""
    user, err = _api_user('patient')
    if err:
        return err
    
    if request.method == 'POST':
        try:
            data = request.get_json(silent=True) or {}
            med = db.create_medication(
                user_id=user['id'],
                name=data.get('name'),
                category=data.get('category'),
                standard_dose=data.get('standard_dose'),
                dose_unit=data.get('dose_unit', 'mg'),
                scheduled_times=data.get('scheduled_times', []),
                date_started=data.get('date_started')
            )
            if not med:
                return jsonify({'error': 'Failed to create medication'}), 400
            return jsonify(med), 201
        except Exception as e:
            app.logger.exception("create_medication error")
            return jsonify({'error': 'Failed to create medication'}), 500

    meds = db.get_user_medications(user['id'])
    return jsonify(meds or []), 200


@app.route('/api/medications/<med_id>/events', methods=['GET', 'POST'])
def api_medication_events(med_id):
    """GET: Medication events for a specific medication. POST: Log an event."""
    user, err = _api_user('patient')
    if err:
        return err
    
    # Verify med belongs to this user
    user_meds = db.get_user_medications(user['id'])
    if not any(str(m.get('id')) == str(med_id) for m in user_meds):
        return jsonify({'error': 'Medication not found'}), 404

    if request.method == 'POST':
        try:
            data = request.get_json(silent=True) or {}
            status = data.get('status', 'TAKEN')
            if status not in {'TAKEN', 'MISSED', 'SKIPPED', 'LATE'}:
                return jsonify({'error': 'Invalid status'}), 400
            event = db.log_medication_event(
                user_id=user['id'],
                medication_id=med_id,
                event_date=data.get('event_date', date.today().isoformat()),
                actual_time=data.get('actual_time'),
                dose=data.get('dose'),
                status=status,
                notes=data.get('notes')
            )
            if not event:
                return jsonify({'error': 'Failed to log medication event'}), 400
            return jsonify(event), 201
        except Exception as e:
            app.logger.exception("log_medication_event error")
            return jsonify({'error': 'Failed to log medication event'}), 500

    events = db.get_medication_events(user['id'], medication_id=med_id)
    return jsonify(events or []), 200


@app.route('/api/medications/search', methods=['GET'])
def api_medication_search():
    """Search global medication reference database."""
    _, err = _api_user()
    if err:
        return err
    query = request.args.get('q', '')
    if not query or len(query) < 2:
        return jsonify({'error': 'Query too short'}), 400
    
    results = db.search_medication_reference(query)
    return jsonify(results), 200


@app.route('/api/medications/quick-log', methods=['POST'])
def api_medications_quick_log():
    """Fast-log a dose taken outside the full check-in flow."""
    user, err = _api_user('patient')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400
    dose_raw = str(data.get('dose') or '').strip()
    dose_num = re.sub(r'[^\d.]', '', dose_raw)  # strip unit letters ("50mg" → "50")
    time_taken = str(data.get('time') or '').strip()
    event_date = _parse_local_date(data.get('date'))

    med_id = db.find_or_create_profile_medication(user['id'], name, dose_raw)
    if not med_id:
        return jsonify({'error': 'Could not resolve medication'}), 500

    event = db.log_medication_event(
        user_id=user['id'],
        medication_id=med_id,
        event_date=event_date,
        actual_time=None,
        dose=float(dose_num) if dose_num else None,
        status='TAKEN',
        notes=time_taken or None,
    )
    if not event:
        return jsonify({'error': 'Failed to log dose'}), 500
    return jsonify({'ok': True, 'event_id': event.get('id')}), 200


@app.route('/api/medications/today-doses', methods=['GET'])
def api_medications_today_doses():
    """Return dose events logged today for the current user."""
    user, err = _api_user('patient')
    if err:
        return err
    today = _parse_local_date(request.args.get('date'))
    logs = db.get_today_dose_logs(user['id'], today)
    return jsonify({'doses': logs, 'date': today}), 200


@app.route('/api/medications/quick-log/<event_id>', methods=['DELETE'])
def api_medications_quick_log_delete(event_id):
    """Remove a specific dose event (undo an accidental log)."""
    user, err = _api_user('patient')
    if err:
        return err
    ok = db.delete_medication_event(user['id'], event_id)
    if not ok:
        return jsonify({'error': 'Failed to remove dose'}), 500
    return jsonify({'ok': True}), 200


@app.route('/api/checkins/today', methods=['GET'])
def api_checkins_today():
    """Return which check-in types have been completed today, plus their saved details."""
    user, err = _api_user('patient')
    if err:
        return err
    today = _parse_local_date(request.args.get('date'))
    checkins = db.get_checkins(user['id'], days=1)
    done = set()
    details = {}
    for c in checkins:
        if (c.get('checkin_date') or '')[:10] == today:
            ct = c.get('checkin_type', '')
            if ct in ('morning', 'afternoon', 'evening'):
                done.add(ct)
                if ct not in details:
                    details[ct] = {
                        'id': c.get('id'),
                        'ai_insight': c.get('ai_insights') or '',
                        'time_of_day': c.get('time_of_day') or ct,
                    }
    return jsonify({'completed': list(done), 'details': details, 'date': today}), 200


@app.route('/api/checkins/by-date', methods=['GET'])
def api_checkins_by_date():
    """Return all check-ins for a specific calendar date (YYYY-MM-DD)."""
    user, err = _api_user('patient')
    if err:
        return err
    date_str = request.args.get('date', '')
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', str(date_str)):
        return jsonify({'error': 'Invalid date. Use YYYY-MM-DD'}), 400
    rows = db.get_checkins_in_range(user['id'], date_str, date_str)
    checkins = []
    for c in (rows or []):
        ext = c.get('extended_data') or {}
        if isinstance(ext, str):
            try:
                ext = json.loads(ext)
            except Exception:
                ext = {}
        checkins.append({
            'checkin_type': c.get('checkin_type', 'on_demand'),
            'time_of_day':  c.get('time_of_day', ''),
            'mood_score':   c.get('mood_score'),
            'stress_score': c.get('stress_score'),
            'sleep_hours':  c.get('sleep_hours'),
            'notes':        c.get('notes', ''),
            'medications':  c.get('medications') or [],
            'energy':       ext.get('energy'),
            'focus':        ext.get('focus'),
            'caffeine_mg':  ext.get('caffeine_mg'),
            'scores':       ext.get('scores') or {},
        })
    return jsonify({'date': date_str, 'checkins': checkins}), 200


@app.route('/api/checkins/today-summary', methods=['GET'])
def api_checkins_today_summary():
    """Return cumulative caffeine breakdown and taken medications from today's check-ins.

    Used to pre-populate the check-in form so afternoon/evening check-ins carry
    forward what was logged earlier in the day.
    """
    user, err = _api_user('patient')
    if err:
        return err
    today = _parse_local_date(request.args.get('date'))
    checkins = db.get_checkins(user['id'], days=1)

    today_checkins = [c for c in (checkins or []) if (c.get('checkin_date') or '')[:10] == today]
    quick_doses = db.get_today_dose_logs(user['id'], today)

    if not today_checkins:
        # No check-ins yet today but quick-logs may exist
        ql_meds = [{'name': qd['name'], 'dose': '', 'taken': True, 'time_taken': qd.get('time') or ''}
                   for qd in quick_doses if qd.get('name')]
        return jsonify({
            'checkin_count': 0,
            'quick_log_count': len(ql_meds),
            'caffeine_breakdown': {'coffee': 0, 'tea': 0, 'soda': 0, 'energy': 0},
            'medications': ql_meds,
            'date': today,
        }), 200

    # Aggregate across ALL of today's check-ins in chronological order.
    # Cumulative behavioural fields use MAX (user logs running totals, not per-session deltas).
    # Boolean coping fields use OR (once done = stays done for the day).
    # Sleep fields come from the first check-in that recorded them (morning).
    caffeine_breakdown = {'coffee': 0, 'tea': 0, 'soda': 0, 'energy': 0}
    alcohol_units = 0
    exercise_minutes = 0
    sunlight_hours   = 0.0
    screen_time_hours = 0.0
    did_breathing = did_meditation = did_movement = hydrated = False
    wake_up_time = ''
    sleep_agg = {k: None for k in ('hours', 'quality', 'time_awake_minutes',
                                    'sleep_latency_minutes', 'night_awakenings')}

    sorted_chrono = sorted(today_checkins, key=lambda c: c.get('created_at', ''))
    for c in sorted_chrono:
        ext = c.get('extended_data') or {}
        if isinstance(ext, str):
            try:
                ext = json.loads(ext)
            except Exception:
                ext = {}

        bd = ext.get('caffeine_breakdown') or {}
        for key in caffeine_breakdown:
            caffeine_breakdown[key] = max(caffeine_breakdown[key], int(bd.get(key) or 0))

        alcohol_units   = max(alcohol_units,   int(ext.get('alcohol_units')   or 0))
        exercise_minutes = max(exercise_minutes, int(ext.get('exercise_minutes') or 0))
        sunlight_hours  = max(sunlight_hours,  float(ext.get('sunlight_hours') or 0))
        screen_time_hours = max(screen_time_hours, float(ext.get('screen_time_hours') or 0))

        coping = ext.get('coping') or {}
        if coping.get('breathing'):  did_breathing  = True
        if coping.get('meditation'): did_meditation = True
        if coping.get('movement'):   did_movement   = True
        if ext.get('hydrated'):      hydrated       = True
        if not wake_up_time and ext.get('wake_up_time'):
            wake_up_time = ext['wake_up_time']

        # Sleep — first check-in that has each field wins (logged once, in the morning)
        if sleep_agg['hours'] is None and c.get('sleep_hours') is not None:
            sleep_agg['hours'] = c['sleep_hours']
        for field in ('quality', 'time_awake_minutes', 'sleep_latency_minutes', 'night_awakenings'):
            db_key = 'sleep_quality' if field == 'quality' else field
            if sleep_agg[field] is None and ext.get(db_key) is not None:
                sleep_agg[field] = ext[db_key]

    # Union of medications across today's check-ins; most-recent check-in wins
    # on duplicate name so taken/time_taken reflects the latest logged state.
    sorted_today = sorted(today_checkins, key=lambda c: c.get('created_at', ''), reverse=True)
    seen, medications = set(), []
    for c in sorted_today:
        for med in (c.get('medications') or []):
            name = (med.get('name') or '').lower()
            if name and name not in seen:
                seen.add(name)
                medications.append(med)

    # Overlay quick-log data from medication_events — marks meds taken via the homescreen shortcut.
    for qd in quick_doses:
        qname = (qd.get('name') or '').lower()
        if not qname:
            continue
        matched = False
        for med in medications:
            if (med.get('name') or '').lower() == qname:
                med['taken'] = True
                if qd.get('time') and not med.get('time_taken'):
                    med['time_taken'] = qd['time']
                matched = True
                break
        if not matched:
            medications.append({'name': qd['name'], 'dose': '', 'taken': True, 'time_taken': qd.get('time') or ''})

    return jsonify({
        'checkin_count':    len(today_checkins),
        'quick_log_count':  len([qd for qd in quick_doses if qd.get('name')]),
        'caffeine_breakdown': caffeine_breakdown,
        'medications':      medications,
        'alcohol_units':    alcohol_units,
        'exercise_minutes': exercise_minutes,
        'sunlight_hours':   sunlight_hours,
        'screen_time_hours': screen_time_hours,
        'coping': {'breathing': did_breathing, 'meditation': did_meditation, 'movement': did_movement},
        'hydrated':         hydrated,
        'wake_up_time':     wake_up_time,
        'sleep':            sleep_agg,
        'date': today,
    }), 200


@app.route('/api/checkins/baseline', methods=['GET'])
def api_checkin_baseline():
    user, err = _api_user()
    if err:
        return err
    days = min(int(request.args.get('days', 7)), 90)
    baseline = db.get_checkin_baseline(user['id'], days=days)
    return jsonify(baseline), 200


@app.route('/api/patient/profile', methods=['GET'])
def api_patient_profile():
    user, err = _api_user('patient')
    if err:
        return err
    profile = db.get_patient_profile(user['id']) or {}
    return jsonify({
        'current_medications': profile.get('current_medications', []),
        'diagnosis': profile.get('diagnosis', ''),
    }), 200


@app.route('/api/checkins', methods=['GET'])
def api_get_checkins():
    user, err = _api_user()
    if err:
        return err
    days = min(int(request.args.get('days', 30)), 365)
    checkins = db.get_checkins(user['id'], days=days)
    return jsonify({'patient_id': user['id'], 'checkins': checkins}), 200


# ── Journal API ───────────────────────────────────────────────────────────────

@app.route('/api/journals', methods=['POST'])
@limiter.limit("30/hour")
def api_create_journal():
    user, err = _api_user('patient')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    raw_entry = data.get('raw_entry', '').strip()
    if not raw_entry:
        return jsonify({'error': 'raw_entry is required'}), 400

    share_with_provider = int(data.get('share_with_provider', 1))

    # ── Crisis check BEFORE AI call — must not depend on AI availability ─────
    if claude_api.check_crisis(raw_entry):
        journal_id = db.create_journal(
            patient_id=user['id'],
            entry_type=data.get('entry_type', 'free_flow'),
            raw_entry=raw_entry,
            ai_analysis=claude_api.CRISIS_RESPONSE,
            share_with_provider=share_with_provider,
        )
        return jsonify({
            'id': journal_id,
            'journal_id': journal_id,
            'patient_id': user['id'],
            'content': raw_entry,
            'entry_type': data.get('entry_type', 'free_flow'),
            'ai_analysis': claude_api.CRISIS_RESPONSE,
            'created_at': date.today().isoformat(),
            'alert': 'crisis',
        }), 201

    # ── Normal path: AI analysis, with graceful fallback if AI is down ────────
    ai_text = None
    try:
        result = claude_api.analyze_journal(raw_entry)
        ai_text = result['text']
    except RuntimeError as e:
        app.logger.warning("analyze_journal failed (AI unavailable): %s", e)
        ai_text = "Your journal entry has been saved. A reflection will be available once the service is restored."

    journal_id = db.create_journal(
        patient_id=user['id'],
        entry_type=data.get('entry_type', 'free_flow'),
        raw_entry=raw_entry,
        ai_analysis=ai_text,
        share_with_provider=share_with_provider,
    )
    return jsonify({
        'id': journal_id,
        'journal_id': journal_id,
        'patient_id': user['id'],
        'content': raw_entry,
        'entry_type': data.get('entry_type', 'free_flow'),
        'ai_analysis': ai_text,
        'created_at': date.today().isoformat(),
    }), 201


@app.route('/api/journals', methods=['GET'])
def api_get_journals():
    user, err = _api_user()
    if err:
        return err
    limit = int(request.args.get('limit', 20))
    journals = db.get_journals(user['id'], limit=limit)
    return jsonify({'patient_id': user['id'], 'journals': journals}), 200


# ── Summary API ───────────────────────────────────────────────────────────────

@app.route('/api/summaries', methods=['POST'])
@limiter.limit("10/hour")
def api_create_summary():
    user, err = _api_user('patient')
    if err:
        return err
    data = request.json or {}
    days = int(data.get('days', 14))

    checkins = db.get_checkins(user['id'], days=days)
    journals = db.get_journals(user['id'], limit=20, shared_only=True)

    if not checkins and not journals:
        return jsonify({'error': 'No data found for the requested period'}), 400

    symptom_patterns = db.find_symptom_correlations(user['id'], days=days)
    # Substance flags surfaced to patient only at concern level (see claude_api.py)
    flags = db.get_patient_flags(user['id'], days=days)
    what_worked = db.get_what_worked_patterns(user['id'], days=max(days, 60))
    lexical_data = db.compute_lexical_diversity(user['id'], days=max(days, 30))
    readability_data = db.compute_readability(user['id'], days=max(days, 30))
    engagement_data = db.compute_engagement_stats(user['id'], days=days)

    try:
        result = claude_api.generate_appointment_summary(
            checkins, journals, days=days, audience='patient',
            symptom_patterns=symptom_patterns,
            substance_flags=flags.get('substance'),
            safety_flags=None,   # safety flags are provider-only — never passed to patient route
            what_worked=what_worked,
            lexical_data=lexical_data,
            readability_data=readability_data,
            engagement_data=engagement_data)
    except RuntimeError as e:
        return jsonify({'error': str(e)}), 503

    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    summary_id = db.create_summary(
        patient_id=user['id'],
        summary_text=result['text'],
        date_range_start=start_date.isoformat(),
        date_range_end=end_date.isoformat(),
        raw_claude_response=result.get('raw'),
    )
    return jsonify({
        'summary_id': summary_id,
        'patient_id': user['id'],
        'date_range_start': start_date.isoformat(),
        'date_range_end': end_date.isoformat(),
        'summary_text': result['text'],
        'created_at': date.today().isoformat(),
    }), 201


@app.route('/api/summaries/<int:patient_id>', methods=['GET'])
def api_get_summaries(patient_id):
    user, err = _api_user()
    if err:
        return err
    # Patients can only see their own; providers can see assigned patients
    if user['role'] == 'patient' and user['id'] != patient_id:
        return jsonify({'error': 'Forbidden'}), 403

    summaries = db.get_summaries(patient_id)
    return jsonify({'patient_id': patient_id, 'summaries': summaries}), 200


@app.route('/api/summaries/<summary_id>', methods=['DELETE'])
def api_delete_summary(summary_id):
    user, err = _api_user('patient')
    if err:
        return err
    db.delete_summary(user['id'], summary_id)
    return jsonify({'message': 'Summary deleted'}), 200


# ── Trends API ────────────────────────────────────────────────────────────────

@app.route('/api/trends', methods=['GET'])
def api_get_trends():
    """Get trend data for the logged-in user."""
    user, err = _api_user('patient')
    if err:
        return err
    
    days = request.args.get('days', 30, type=int)
    trends = db.get_trends_data(user['id'], days=days)
    
    if not trends:
        return jsonify({'error': 'Unable to fetch trends'}), 500
    
    # Add current medications to the response
    try:
        meds = db.get_user_medications(user['id'], active_only=True)
        trends['current_medications'] = [{'id': m.get('id'), 'name': m.get('name')} for m in meds] if meds else []
    except:
        trends['current_medications'] = []
    
    return jsonify(trends), 200

# ── Provider API ──────────────────────────────────────────────────────────────

@app.route('/api/provider/patients', methods=['GET'])
def api_provider_patients():
    user, err = _api_user('provider')
    if err:
        return err
    patients = db.get_provider_patients(user['id'])
    return jsonify({'provider_id': user['id'], 'patients': patients}), 200


@app.route('/api/provider/patient/<patient_id>/perms-debug', methods=['GET'])
def api_provider_perms_debug(patient_id):
    """Diagnostic: show what permissions this provider has for a patient."""
    user, err = _api_user('provider')
    if err:
        return err
    raw = db.get_care_team_permissions(patient_id, user['id'])
    perms = _get_provider_perms(user['id'], patient_id)
    is_legacy = user['id'] in [
        str(p['patient_id']) for p in db.get_provider_patients(user['id'])
    ]
    return jsonify({
        'provider_id': user['id'],
        'patient_id': patient_id,
        'raw_db_permissions': raw,
        'effective_permissions': perms,
        'fallback_triggered': raw is None,
        'is_legacy_patient': is_legacy,
    }), 200


@app.route('/api/provider/patient/<patient_id>/trends', methods=['GET'])
def api_provider_patient_trends(patient_id):
    user, err = _api_user('provider')
    if err:
        return err
    if not _provider_owns_patient(user['id'], patient_id):
        return jsonify({'error': 'Patient not found'}), 404
    days = min(int(request.args.get('days', 30)), 365)
    perms = _get_provider_perms(user['id'], patient_id)
    trends = db.get_trends_data(patient_id, days=days)
    if not trends:
        return jsonify({'error': 'Unable to fetch trends'}), 500
    trends = _apply_perms_to_trends(trends, perms)
    try:
        if perms.get('medication_data', True):
            meds = db.get_user_medications(patient_id, active_only=True)
            trends['current_medications'] = [{'id': m.get('id'), 'name': m.get('name')} for m in meds] if meds else []
        else:
            trends['current_medications'] = []
    except Exception:
        trends['current_medications'] = []
    return jsonify(trends), 200


@app.route('/api/provider/patient/<patient_id>', methods=['GET'])
def api_provider_patient(patient_id):
    user, err = _api_user('provider')
    if err:
        return err
    if not _provider_owns_patient(user['id'], patient_id):
        return jsonify({'error': 'Patient not found'}), 404
    days = min(int(request.args.get('days', 30)), 365)
    detail = db.get_patient_detail(patient_id, days=days)
    if not detail:
        return jsonify({'error': 'Patient not found'}), 404
    perms = _get_provider_perms(user['id'], patient_id)
    return jsonify(_apply_perms_to_patient_detail(detail, perms)), 200


@app.route('/api/provider/patient/<patient_id>/checkins/by-date', methods=['GET'])
def api_provider_patient_checkins_by_date(patient_id):
    """Return a patient's check-ins for a specific date for the provider appointment view."""
    user, err = _api_user('provider')
    if err:
        return err
    if not _provider_owns_patient(user['id'], patient_id):
        return jsonify({'error': 'Patient not found'}), 404
    date_str = request.args.get('date', '')
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', str(date_str)):
        return jsonify({'error': 'Invalid date. Use YYYY-MM-DD'}), 400
    perms = _get_provider_perms(user['id'], patient_id)
    rows = db.get_checkins_in_range(patient_id, date_str, date_str)
    checkins = []
    for c in (rows or []):
        ext = c.get('extended_data') or {}
        if isinstance(ext, str):
            try:
                ext = json.loads(ext)
            except Exception:
                ext = {}
        scores = ext.get('scores') or {}
        checkins.append({
            'checkin_type':    c.get('checkin_type', 'on_demand'),
            'time_of_day':     c.get('time_of_day', ''),
            'mood_score':      c.get('mood_score'),
            'stress_score':    c.get('stress_score'),
            'sleep_hours':     c.get('sleep_hours'),
            'notes':           c.get('notes', '') if perms.get('checkin_data', True) else None,
            'medications':     (c.get('medications') or []) if perms.get('medication_data', True) else [],
            'energy':          ext.get('energy'),
            'focus':           ext.get('focus'),
            'dissociation':    ext.get('dissociation'),
            'anxiety':         ext.get('anxiety'),
            'irritability':    ext.get('irritability'),
            'motivation':      ext.get('motivation'),
            'caffeine_mg':     ext.get('caffeine_mg'),
            'exercise_minutes':ext.get('exercise_minutes'),
            'sleep_quality':   ext.get('sleep_quality'),
            'stability_score': scores.get('stability_score'),
            'crash_risk':      scores.get('crash_risk'),
            'stim_load':       scores.get('stim_load'),
            'ns_load':         scores.get('ns_load'),
        })
    return jsonify({'date': date_str, 'checkins': checkins}), 200


@app.route('/api/provider/appointment/<appt_id>/save', methods=['POST'])
def api_appointment_save(appt_id):
    """Autosave appointment workspace data (notes, Q&A, actions, care plan)."""
    user, err = _api_user('provider')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    updates = {}
    if 'notes' in data:
        updates['notes'] = str(data['notes'])
    if 'care_plan_changes' in data:
        updates['care_plan_changes'] = str(data['care_plan_changes'])
    if 'guided_qa' in data and isinstance(data['guided_qa'], list):
        updates['guided_qa'] = data['guided_qa']
    if 'actions' in data and isinstance(data['actions'], list):
        updates['actions'] = data['actions']
    if 'next_appointment_date' in data:
        nd = str(data['next_appointment_date']).strip()
        updates['next_appointment_date'] = nd if nd else None
    if 'next_appointment_time' in data:
        nt = str(data['next_appointment_time']).strip()
        updates['next_appointment_time'] = nt if nt else None
    if 'next_appointment_notes' in data:
        updates['next_appointment_notes'] = str(data['next_appointment_notes'])
    if data.get('complete'):
        from datetime import datetime as _dt
        updates['status'] = 'completed'
        updates['completed_at'] = _dt.utcnow().isoformat()
    ok = db.update_provider_appointment(appt_id, user['id'], updates)
    if not ok:
        return jsonify({'error': 'Appointment not found or not authorized'}), 404
    return jsonify({'status': 'saved'}), 200


@app.route('/api/provider/appointment/<appt_id>/synthesis', methods=['GET'])
def api_provider_appointment_synthesis(appt_id):
    """
    Bidirectional synthesis for a provider.
    Returns pre/post behavioral comparison plus Mode G (note-data alignment)
    and Mode H (patient-perspective) AI narratives.
    """
    user, err = _api_user('provider')
    if err:
        return err

    # Verify appointment belongs to this provider
    appt = db.get_provider_appointment(appt_id, user['id'])
    if not appt:
        return jsonify({'error': 'Appointment not found'}), 404

    patient_id = str(appt['patient_id'])
    synthesis  = db.get_appointment_synthesis(patient_id, appt_id)
    if not synthesis:
        return jsonify({'error': 'Synthesis data unavailable'}), 200

    provider_result = claude_api.generate_provider_synthesis(synthesis)
    patient_result  = claude_api.generate_patient_synthesis(synthesis)

    return jsonify({
        'appt_date':          synthesis['appt_date'],
        'pre':                synthesis['pre'],
        'post':               synthesis['post'],
        'deltas':             synthesis['deltas'],
        'has_post_data':      synthesis['has_post_data'],
        'pre_window':         synthesis['pre_window'],
        'post_window':        synthesis['post_window'],
        'provider_narrative': provider_result.get('text') if provider_result.get('status') == 'safe' else None,
        'patient_narrative':  patient_result.get('text')  if patient_result.get('status') == 'safe' else None,
    }), 200


@app.route('/api/patient/appointment/<appt_id>/synthesis', methods=['GET'])
def api_patient_appointment_synthesis(appt_id):
    """
    Patient-facing synthesis for a single appointment.
    Returns only the behavioral story — no session notes or clinical content.
    """
    user, err = _api_user('patient')
    if err:
        return err

    # Verify this appointment belongs to this patient
    try:
        resp = db.supabase_admin.table('provider_appointments').select(
            'patient_id').eq('id', appt_id).limit(1).execute()
        if not resp.data or str(resp.data[0]['patient_id']) != str(user['id']):
            return jsonify({'error': 'Appointment not found'}), 404
    except Exception:
        return jsonify({'error': 'Appointment not found'}), 404

    synthesis = db.get_appointment_synthesis(user['id'], appt_id)
    if not synthesis:
        return jsonify({'error': 'Synthesis data unavailable'}), 200

    patient_result = claude_api.generate_patient_synthesis(synthesis)

    return jsonify({
        'appt_date':         synthesis['appt_date'],
        'pre':               synthesis['pre'],
        'post':              synthesis['post'],
        'deltas':            synthesis['deltas'],
        'has_post_data':     synthesis['has_post_data'],
        'pre_window':        synthesis['pre_window'],
        'post_window':       synthesis['post_window'],
        'patient_narrative': patient_result.get('text') if patient_result.get('status') == 'safe' else None,
    }), 200


@app.route('/api/provider/patient/<patient_id>/resolve-crisis', methods=['POST'])
def api_resolve_crisis(patient_id):
    user, err = _api_user('provider')
    if err:
        return err
    if not _provider_owns_patient(user['id'], patient_id):
        return jsonify({'error': 'Patient not found'}), 404
    ok = db.resolve_crisis_risk(patient_id)
    if not ok:
        return jsonify({'error': 'Failed to resolve crisis flag'}), 500
    return jsonify({'status': 'resolved'}), 200


@app.route('/api/provider/patient/<patient_id>/brief', methods=['GET'])
def api_between_session_brief(patient_id):
    """Return a structured between-session brief for a patient.

    For care team providers with therapy/counselor/coach roles, the response
    also includes a `behavioral` block and `provider_role` so the dashboard
    drawer can surface the right signal set.
    """
    user, err = _api_user('provider')
    if err:
        return err
    if not _provider_owns_patient(user['id'], patient_id):
        return jsonify({'error': 'Patient not found'}), 404

    perms = _get_provider_perms(user['id'], patient_id)
    brief = _apply_perms_to_brief(db.get_between_session_brief(patient_id, user['id']), perms)

    # Detect care team role for this provider-patient pair
    care_role = db.get_care_team_member_role(user['id'], patient_id) or 'psychiatrist'
    brief['provider_role'] = care_role

    _THERAPY_ROLES = {'therapist', 'counselor', 'coach'}
    if care_role in _THERAPY_ROLES and perms.get('advanced_data', True):
        brief['behavioral'] = db.get_behavioral_data(patient_id, days=brief.get('days_in_period', 30))

    return jsonify(brief), 200


@app.route('/api/provider/patient/<patient_id>/therapy-summary', methods=['POST'])
def api_provider_therapy_summary(patient_id):
    """Generate a therapy-weighted AI summary (Mode C variant for therapists/counselors).

    Only callable when the provider has an active care team relationship with
    role therapist, counselor, or coach.
    """
    user, err = _api_user('provider')
    if err:
        return err
    if not _provider_owns_patient(user['id'], patient_id):
        return jsonify({'error': 'Patient not found'}), 404

    _THERAPY_ROLES = {'therapist', 'counselor', 'coach'}
    care_role = db.get_care_team_member_role(user['id'], patient_id)
    if care_role not in _THERAPY_ROLES:
        return jsonify({'error': 'Therapy summaries are only available for therapist / counselor / coach roles.'}), 403

    body = request.get_json(silent=True) or {}
    days = max(7, min(int(body.get('days', 14)), 90))
    perms = _get_provider_perms(user['id'], patient_id)

    checkins   = _strip_checkin_fields(db.get_checkins(patient_id, days), perms)
    journals   = db.get_journals(patient_id, limit=20, shared_only=True) if perms.get('journals_raw', True) else []
    behavioral = db.get_behavioral_data(patient_id, days=days) if perms.get('advanced_data', True) else {}
    engagement = db.compute_engagement_stats(patient_id, days=days)

    try:
        result = claude_api.generate_therapy_summary(
            checkin_data=checkins,
            journal_data=journals,
            behavioral_data=behavioral,
            days=days,
            engagement_data=engagement,
        )
        return jsonify(result), 200
    except RuntimeError as e:
        app.logger.error(f"Therapy summary failed for patient {patient_id}: {e}")
        return jsonify({'error': 'Summary generation failed — please try again.'}), 500


# ── Care Flags API ────────────────────────────────────────────────────────────

@app.route('/api/provider/patient/<patient_id>/flags', methods=['GET'])
def api_get_care_flags(patient_id):
    """Return unresolved care flags on this patient posted by other providers.

    Also returns the viewing provider's own unresolved flags so they can manage them.
    Response: { 'from_others': [...], 'my_flags': [...] }
    """
    user, err = _api_user('provider')
    if err:
        return err
    if not _provider_owns_patient(user['id'], patient_id):
        return jsonify({'error': 'Access denied.'}), 403

    from_others = db.get_care_flags_for_provider(user['id'], patient_id)
    my_flags    = db.get_my_care_flags(user['id'], patient_id)
    return jsonify({'from_others': from_others, 'my_flags': my_flags}), 200


@app.route('/api/provider/patient/<patient_id>/flags', methods=['POST'])
def api_create_care_flag(patient_id):
    """Provider posts a new care flag on a patient.

    Body: { flag_type: 'observation'|'concern'|'progress'|'coordination_needed', body: str }
    """
    user, err = _api_user('provider')
    if err:
        return err
    if not _provider_owns_patient(user['id'], patient_id):
        return jsonify({'error': 'Access denied.'}), 403

    data = request.get_json(silent=True) or {}
    flag_type  = (data.get('flag_type') or '').strip()
    body       = (data.get('body') or '').strip()
    visible_to = data.get('visible_to')  # optional list of provider_id strings

    if not flag_type:
        return jsonify({'error': 'flag_type is required.'}), 400
    if not body:
        return jsonify({'error': 'body is required.'}), 400
    if visible_to is not None and not isinstance(visible_to, list):
        return jsonify({'error': 'visible_to must be a list.'}), 400

    result = db.create_care_flag(user['id'], patient_id, flag_type, body,
                                 visible_to=visible_to or None)
    if result.get('ok'):
        return jsonify(result), 201
    return jsonify({'error': result.get('error', 'Failed to create flag.')}), 400


@app.route('/api/provider/patient/<patient_id>/flags/<flag_id>/resolve', methods=['PATCH'])
def api_resolve_care_flag(patient_id, flag_id):
    """Mark a care flag as resolved."""
    user, err = _api_user('provider')
    if err:
        return err
    if not _provider_owns_patient(user['id'], patient_id):
        return jsonify({'error': 'Access denied.'}), 403

    result = db.resolve_care_flag(flag_id, user['id'], patient_id)
    if result.get('ok'):
        return jsonify({'ok': True}), 200
    return jsonify({'error': result.get('error', 'Failed to resolve flag.')}), 400


@app.route('/api/provider/patient/<patient_id>/flags/all', methods=['GET'])
def api_get_all_care_flags(patient_id):
    """Return all flags (active + resolved) for the persistent flags panel on the hub."""
    user, err = _api_user('provider')
    if err:
        return err
    if not _provider_owns_patient(user['id'], patient_id):
        return jsonify({'error': 'Access denied.'}), 403
    flags = db.get_all_care_flags_for_hub(patient_id)
    return jsonify({'flags': flags}), 200


@app.route('/api/provider/patient/<patient_id>/summaries', methods=['GET'])
def api_provider_get_patient_summaries(patient_id):
    """Return all saved briefs/summaries for this patient (provider-authenticated)."""
    user, err = _api_user('provider')
    if err:
        return err
    if not _provider_owns_patient(user['id'], patient_id):
        return jsonify({'error': 'Access denied.'}), 403
    summaries = db.get_summaries(patient_id)
    return jsonify({'summaries': summaries}), 200


@app.route('/api/provider/patient/<patient_id>/care-team-members', methods=['GET'])
def api_get_care_team_for_flag(patient_id):
    """Returns active care team members (excluding the requesting provider) for
    the flag visibility selector."""
    user, err = _api_user('provider')
    if err:
        return err
    if not _provider_owns_patient(user['id'], patient_id):
        return jsonify({'error': 'Access denied.'}), 403
    members = db.get_care_team_for_provider(user['id'], patient_id)
    return jsonify({'members': members}), 200


@app.route('/api/provider/patient/<patient_id>/flags/<flag_id>/responses', methods=['GET'])
def api_get_flag_responses(patient_id, flag_id):
    """Returns all responses for a care flag."""
    user, err = _api_user('provider')
    if err:
        return err
    if not _provider_owns_patient(user['id'], patient_id):
        return jsonify({'error': 'Access denied.'}), 403
    responses = db.get_flag_responses(flag_id, patient_id)
    return jsonify({'responses': responses}), 200


@app.route('/api/provider/patient/<patient_id>/flags/<flag_id>/responses', methods=['POST'])
def api_create_flag_response(patient_id, flag_id):
    """Post a response to a care flag."""
    user, err = _api_user('provider')
    if err:
        return err
    if not _provider_owns_patient(user['id'], patient_id):
        return jsonify({'error': 'Access denied.'}), 403
    data = request.get_json(silent=True) or {}
    body = (data.get('body') or '').strip()
    if not body:
        return jsonify({'error': 'body is required.'}), 400
    result = db.create_flag_response(flag_id, user['id'], patient_id, body)
    if result.get('ok'):
        return jsonify(result), 201
    return jsonify({'error': result.get('error', 'Failed to post response.')}), 400


@app.route('/api/provider/patient/<patient_id>/proactive-insights', methods=['GET'])
def api_provider_proactive_insights(patient_id):
    """Return recent proactive AI insights for a patient — provider-side read."""
    user, err = _api_user('provider')
    if err:
        return err
    if not _provider_owns_patient(user['id'], patient_id):
        return jsonify({'error': 'Access denied.'}), 403
    days = int(request.args.get('days', 7))
    insights = db.get_proactive_insights_for_provider(patient_id, days=days)
    return jsonify({'insights': insights}), 200


@app.route('/api/provider/patient/<patient_id>/medications', methods=['GET'])
def api_get_patient_medications(patient_id):
    """Return the patient's active medications for the Add Medication dropdown."""
    user, err = _api_user('provider')
    if err:
        return err
    if not _provider_owns_patient(user['id'], patient_id):
        return jsonify({'error': 'Access denied.'}), 403
    if not _get_provider_perms(user['id'], patient_id).get('medication_data', True):
        return jsonify({'medications': []}), 200
    meds = db.get_user_medications(patient_id, active_only=True)
    return jsonify({'medications': meds}), 200


@app.route('/api/provider/patient/<patient_id>/medications/<med_id>', methods=['PUT'])
def api_provider_update_medication(patient_id, med_id):
    """Provider updates a patient's medication fields."""
    user, err = _api_user('provider')
    if err:
        return err
    if not _provider_owns_patient(user['id'], patient_id):
        return jsonify({'error': 'Access denied.'}), 403
    data = request.get_json(silent=True) or {}
    result = db.update_medication_by_provider(user['id'], patient_id, med_id, data)
    if result.get('ok'):
        return jsonify(result), 200
    return jsonify({'error': result.get('error', 'Update failed.')}), 400


@app.route('/api/provider/patient/<patient_id>/medications/<med_id>', methods=['DELETE'])
def api_provider_deactivate_medication(patient_id, med_id):
    """Provider deactivates (soft-deletes) a patient's medication."""
    user, err = _api_user('provider')
    if err:
        return err
    if not _provider_owns_patient(user['id'], patient_id):
        return jsonify({'error': 'Access denied.'}), 403
    ok = db.deactivate_medication_by_provider(user['id'], patient_id, med_id)
    if ok:
        return jsonify({'ok': True}), 200
    return jsonify({'error': 'Failed to deactivate medication.'}), 500


@app.route('/api/provider/patient/<patient_id>/medications', methods=['POST'])
def api_provider_add_medication(patient_id):
    """Psychiatrist adds a medication to a patient's record."""
    user, err = _api_user('provider')
    if err:
        return err
    if not _provider_owns_patient(user['id'], patient_id):
        return jsonify({'error': 'Access denied.'}), 403
    data = request.get_json(silent=True) or {}
    name            = (data.get('name') or '').strip()
    category        = (data.get('category') or '').strip()
    dose            = data.get('dose')
    dose_unit       = (data.get('dose_unit') or 'mg').strip()
    scheduled_times = data.get('scheduled_times') or []
    date_started    = (data.get('date_started') or '').strip() or None
    frequency       = (data.get('frequency') or '').strip() or None
    if not name:
        return jsonify({'error': 'name is required.'}), 400
    if not category:
        return jsonify({'error': 'category is required.'}), 400
    if dose is None:
        return jsonify({'error': 'dose is required.'}), 400
    result = db.add_medication_by_psychiatrist(
        user['id'], patient_id, name, category, dose, dose_unit,
        scheduled_times, date_started, frequency=frequency)
    if result.get('ok'):
        return jsonify(result), 201
    return jsonify({'error': result.get('error', 'Failed to add medication.')}), 400


# ── Care Team API — Provider side ─────────────────────────────────────────────

@app.route('/api/provider/care-team/request', methods=['POST'])
def api_provider_care_request():
    """Provider sends a connection request to a patient by email."""
    import email_utils
    user, err = _api_user('provider')
    if err:
        return err
    body = request.get_json(silent=True) or {}
    patient_email = (body.get('patient_email') or '').strip()
    role          = body.get('role', 'psychiatrist')
    message       = body.get('message', '')
    if not patient_email:
        return jsonify({'error': 'patient_email is required'}), 400
    result = db.send_care_team_request(user['id'], patient_email, role, message or None)
    if result.get('ok'):
        if result.get('method') == 'invitation':
            # Patient has no account yet — send pre-registration invite email
            token = result.get('token', '')
            base_url = request.host_url.rstrip('/')
            invite_url = f"{base_url}/register?invite={token}&email={patient_email}"
            role_labels = {
                'psychiatrist': 'Psychiatrist', 'therapist': 'Therapist',
                'psychologist': 'Psychologist', 'nurse_practitioner': 'Nurse Practitioner',
                'counselor': 'Counselor', 'social_worker': 'Social Worker',
                'care_coordinator': 'Care Coordinator', 'other': 'Provider',
            }
            role_label = role_labels.get(role, 'Provider')
            provider_name = user.get('full_name') or 'Your provider'
            email_utils.send_provider_patient_invite_email(
                patient_email, provider_name, role_label, message or None, invite_url
            )
        return jsonify(result), 200
    return jsonify({'error': result.get('error', 'Request failed')}), 400


@app.route('/api/provider/care-team/outbound', methods=['GET'])
def api_provider_care_outbound():
    """Returns provider's pending outbound connection requests."""
    user, err = _api_user('provider')
    if err:
        return err
    return jsonify(db.get_provider_outbound_requests(user['id'])), 200


@app.route('/api/provider/care-team/inbound', methods=['GET'])
def api_provider_care_inbound():
    """Returns pending patient-initiated requests for this provider."""
    user, err = _api_user('provider')
    if err:
        return err
    return jsonify(db.get_provider_inbound_requests(user['id'])), 200


@app.route('/api/provider/care-team/<member_id>/accept', methods=['POST'])
def api_provider_accept_inbound(member_id):
    """Provider accepts a patient-initiated care team request."""
    user, err = _api_user('provider')
    if err:
        return err
    result = db.accept_inbound_care_request(user['id'], member_id)
    if result.get('ok'):
        return jsonify({'status': 'accepted'}), 200
    return jsonify({'error': result.get('error')}), 400


@app.route('/api/provider/care-team/<member_id>/decline', methods=['POST'])
def api_provider_decline_inbound(member_id):
    """Provider declines a patient-initiated care team request."""
    user, err = _api_user('provider')
    if err:
        return err
    result = db.decline_inbound_care_request(user['id'], member_id)
    if result.get('ok'):
        return jsonify({'status': 'declined'}), 200
    return jsonify({'error': result.get('error')}), 400


# ── Care Team API — Patient side ──────────────────────────────────────────────

@app.route('/api/patient/care-team', methods=['GET'])
def api_patient_care_team():
    """Patient views their full care team (active + pending)."""
    user, err = _api_user('patient')
    if err:
        return err
    return jsonify(db.get_patient_care_team(user['id'])), 200


@app.route('/api/patient/care-team/pending', methods=['GET'])
def api_patient_care_pending():
    """Patient views only pending connection requests."""
    user, err = _api_user('patient')
    if err:
        return err
    return jsonify(db.get_pending_care_requests(user['id'])), 200


@app.route('/api/patient/care-team/<member_id>/approve', methods=['POST'])
def api_patient_care_approve(member_id):
    """Patient approves a pending care team request."""
    user, err = _api_user('patient')
    if err:
        return err
    body        = request.get_json(silent=True) or {}
    permissions = body.get('permissions')
    result      = db.approve_care_request(user['id'], member_id, permissions)
    if result.get('ok'):
        return jsonify({'status': 'approved'}), 200
    return jsonify({'error': result.get('error')}), 400


@app.route('/api/patient/care-team/<member_id>/deny', methods=['POST'])
def api_patient_care_deny(member_id):
    """Patient denies a pending care team request."""
    user, err = _api_user('patient')
    if err:
        return err
    result = db.deny_care_request(user['id'], member_id)
    if result.get('ok'):
        return jsonify({'status': 'denied'}), 200
    return jsonify({'error': result.get('error')}), 400


@app.route('/api/patient/care-team/<member_id>/revoke', methods=['DELETE'])
def api_patient_care_revoke(member_id):
    """Patient revokes an active provider's access."""
    user, err = _api_user('patient')
    if err:
        return err
    result = db.revoke_care_member(user['id'], member_id)
    if result.get('ok'):
        return jsonify({'status': 'revoked'}), 200
    return jsonify({'error': result.get('error')}), 400


@app.route('/api/patient/care-team/invite', methods=['POST'])
def api_patient_care_invite():
    """Patient invites a provider by email to join their care team."""
    user, err = _api_user('patient')
    if err:
        return err
    body = request.get_json(silent=True) or {}
    provider_email = (body.get('provider_email') or '').strip()
    role           = body.get('role', 'psychiatrist')
    message        = (body.get('message') or '').strip() or None
    if not provider_email:
        return jsonify({'error': 'provider_email is required'}), 400
    result = db.send_patient_care_request(user['id'], provider_email, role, message)
    if result.get('ok'):
        return jsonify(result), 200
    return jsonify({'error': result.get('error', 'Could not send invite')}), 400


@app.route('/api/patient/care-team/<member_id>/permissions', methods=['PATCH'])
def api_patient_care_permissions(member_id):
    """Patient updates per-provider data permissions."""
    user, err = _api_user('patient')
    if err:
        return err
    body = request.get_json(silent=True) or {}
    permissions = body.get('permissions', {})
    result = db.update_care_permissions(user['id'], member_id, permissions)
    if result.get('ok'):
        return jsonify({'status': 'updated'}), 200
    return jsonify({'error': result.get('error')}), 400


# ── Care Team Page Routes ─────────────────────────────────────────────────────

@app.route('/care-team')
def patient_care_team_page():
    """Patient's Care Team management page."""
    user, redir = _require_patient()
    if redir:
        return redir
    return render_template('patient/care_team.html', user=user)


@app.route('/appointments')
def patient_appointments_page():
    """Patient-facing appointments list and request page."""
    user, redir = _require_patient()
    if redir:
        return redir
    appointments = db.get_patient_appointment_list(user['id'])
    # Find care team providers for the request form
    care_team = db.get_care_team_for_patient(user['id'])
    return render_template('patient/appointments.html',
                           user=user,
                           appointments=appointments,
                           care_team=care_team)


@app.route('/api/patient/appointments', methods=['GET'])
def api_patient_appointments():
    """JSON endpoint: patient's appointment list."""
    user, err = _api_user('patient')
    if err:
        return err
    appointments = db.get_patient_appointment_list(user['id'])
    return jsonify(appointments), 200


@app.route('/api/patient/appointments/request', methods=['POST'])
def api_patient_appointment_request():
    """Patient sends appointment request email to a provider."""
    import email_utils
    user, err = _api_user('patient')
    if err:
        return err
    body = request.get_json(silent=True) or {}
    provider_id = (body.get('provider_id') or '').strip()
    message     = (body.get('message') or '').strip()
    if not provider_id:
        return jsonify({'error': 'provider_id is required'}), 400
    # Verify this provider is on the patient's care team
    care_team = db.get_care_team_for_patient(user['id'])
    provider = next((m for m in care_team if m.get('provider_id') == provider_id), None)
    if not provider:
        return jsonify({'error': 'Provider not found on your care team'}), 404
    provider_email = provider.get('provider_email')
    if not provider_email:
        return jsonify({'error': 'Provider email not available'}), 400
    provider_name  = provider.get('provider_name', 'Your provider')
    patient_name   = user.get('full_name', 'Your patient')
    try:
        email_utils.send_appointment_request_email(
            provider_email, provider_name, patient_name, message or None
        )
        return jsonify({'ok': True}), 200
    except Exception as e:
        return jsonify({'error': f'Could not send request: {e}'}), 500


@app.route('/api/provider/generate-summary/<patient_id>', methods=['POST'])
@limiter.limit("10/hour")
def api_provider_generate_summary(patient_id):
    user, err = _api_user('provider')
    if err:
        return err
    if not _provider_owns_patient(user['id'], patient_id):
        return jsonify({'error': 'Patient not found'}), 404
    data = request.json or {}

    # Accept explicit period_start / period_end, or fall back to rolling days
    period_start = data.get('period_start')
    period_end   = data.get('period_end')
    appointment_date = data.get('appointment_date')

    perms = _get_provider_perms(user['id'], patient_id)

    if period_start and period_end:
        if not (re.match(r'^\d{4}-\d{2}-\d{2}$', str(period_start)) and
                re.match(r'^\d{4}-\d{2}-\d{2}$', str(period_end))):
            return jsonify({'error': 'period_start and period_end must be YYYY-MM-DD'}), 400
        checkins = _strip_checkin_fields(db.get_checkins_in_range(patient_id, period_start, period_end), perms)
        journals = db.get_journals_in_range(patient_id, period_start, period_end) if perms.get('journals_raw', True) else []
        days = None
    else:
        days = min(int(data.get('days', 14)), 365)
        end_dt    = date.today()
        start_dt  = end_dt - timedelta(days=days)
        period_start = start_dt.isoformat()
        period_end   = end_dt.isoformat()
        checkins = _strip_checkin_fields(db.get_checkins_in_range(patient_id, period_start, period_end), perms)
        journals = db.get_journals_in_range(patient_id, period_start, period_end) if perms.get('journals_raw', True) else []

    if not checkins and not journals:
        return jsonify({'error': 'No data found for this patient in the selected period'}), 400

    summary_days = days or (date.fromisoformat(period_end) - date.fromisoformat(period_start)).days
    symptom_patterns = db.find_symptom_correlations(patient_id, days=summary_days)
    flags = db.get_patient_flags(patient_id, days=summary_days)
    what_worked = db.get_what_worked_patterns(patient_id, days=max(summary_days, 60))
    # Pull any uploaded transcripts / recordings processed in the same period
    session_context = db.get_clinical_sessions_for_period(
        patient_id=patient_id,
        period_start=period_start,
        period_end=period_end,
        limit=10,
    )

    # Collect raw voice note transcripts for the period.
    # Passed directly to the brief prompt — no extra Claude call, no timeout risk.
    raw_voice_transcripts = []
    try:
        known_dates = {s['session_date'] for s in session_context if s.get('session_date')}
        for vn in db.get_voice_notes_for_period(patient_id, period_start, period_end, limit=5):
            vn_date = (vn.get('created_at') or '')[:10]
            text = (vn.get('transcript') or '').strip()
            if text and vn_date not in known_dates:
                raw_voice_transcripts.append({'date': vn_date, 'transcript': text})
    except Exception as _vne:
        app.logger.warning(f'[brief] voice note query failed: {_vne}')

    provider_type = user.get('provider_type')
    try:
        engagement_data = db.compute_engagement_stats(
            patient_id, days=summary_days,
            period_start=period_start, period_end=period_end,
        )

        if provider_type in ('therapist', 'counselor'):
            result = claude_api.generate_therapy_summary(
                checkins, journals,
                days=summary_days,
                period_start=period_start,
                period_end=period_end,
                appointment_date=appointment_date,
                safety_flags=flags.get('safety'),
                substance_flags=flags.get('substance'),
                session_context=session_context or [],
                raw_voice_transcripts=raw_voice_transcripts or [],
                engagement_data=engagement_data,
            )
        elif provider_type == 'psychiatrist':
            _pt_profile = db.supabase_admin.table('profiles').select('full_name').eq('id', patient_id).limit(1).execute()
            _pt_name = (_pt_profile.data[0].get('full_name') if _pt_profile.data else None)
            result = claude_api.generate_psychiatry_summary(
                checkins, journals,
                days=summary_days,
                period_start=period_start,
                period_end=period_end,
                appointment_date=appointment_date,
                symptom_patterns=symptom_patterns,
                substance_flags=flags.get('substance'),
                safety_flags=flags.get('safety'),
                session_context=session_context or [],
                raw_voice_transcripts=raw_voice_transcripts or [],
                patient_name=_pt_name,
                engagement_data=engagement_data,
            )
        else:
            # unknown / None — fall back to Mode C provider brief
            lexical_data = db.compute_lexical_diversity(patient_id, days=max(summary_days, 30))
            readability_data = db.compute_readability(patient_id, days=max(summary_days, 30))
            result = claude_api.generate_appointment_summary(
                checkins, journals,
                days=summary_days,
                period_start=period_start,
                period_end=period_end,
                appointment_date=appointment_date,
                audience='provider',
                symptom_patterns=symptom_patterns,
                substance_flags=flags.get('substance'),
                safety_flags=flags.get('safety'),
                what_worked=what_worked,
                lexical_data=lexical_data,
                readability_data=readability_data,
                session_context=session_context or [],
                raw_voice_transcripts=raw_voice_transcripts or [],
                engagement_data=engagement_data,
            )
    except RuntimeError as e:
        return jsonify({'error': str(e)}), 503

    summary_id = db.create_summary(
        patient_id=patient_id,
        summary_text=result['text'],
        date_range_start=period_start,
        date_range_end=period_end,
        raw_claude_response=result.get('raw'),
    )
    return jsonify({
        'summary_id':       summary_id,
        'patient_id':       patient_id,
        'summary_text':     result['text'],
        'date_range_start': period_start,
        'date_range_end':   period_end,
        'appointment_date': appointment_date,
        'provider_type':    provider_type,
        'chart_data':       result.get('chart_data') or None,
    }), 201


# ── Settings API ──────────────────────────────────────────────────────────────

@app.route('/api/settings/profile', methods=['POST'])
def api_update_profile():
    user, err = _api_user('patient')
    if err:
        return err
    data = request.json or {}

    updates = {}
    if 'phone_number' in data:
        raw = (data['phone_number'] or '').strip()
        # Strip formatting to E.164-friendly digits+plus; accept empty to clear
        import re as _re
        cleaned = _re.sub(r'[\s\-\(\)\.]+', '', raw)
        updates['phone_number'] = cleaned or None
    if 'emergency_contact' in data:
        updates['emergency_contact'] = data['emergency_contact']
    if 'date_of_birth' in data:
        updates['date_of_birth'] = data['date_of_birth']
    if 'current_medications' in data:
        # Merge new medication(s) into existing list
        import json as _json
        profile = db.get_patient_profile(user['id'])
        existing = profile.get('current_medications', []) if profile else []
        if not isinstance(existing, list):
            existing = []
        new_meds = data['current_medications']
        if not isinstance(new_meds, list):
            new_meds = [new_meds]
        # Append if (name, dose) combo not already present — allows same med at different doses
        existing_keys = {(m.get('name', '').lower(), m.get('dose', '').lower()) for m in existing}
        for m in new_meds:
            key = (m.get('name', '').lower(), m.get('dose', '').lower())
            if key not in existing_keys:
                if 'start_date' not in m:
                    m['start_date'] = date.today().isoformat()
                existing.append(m)
        updates['current_medications'] = existing

    if updates:
        db.update_patient_profile(user['id'], **updates)
    return jsonify({'message': 'Profile updated'}), 200


@app.route('/api/settings/provider-profile', methods=['POST'])
def api_update_provider_profile():
    user, err = _api_user('provider')
    if err:
        return err
    data = request.json or {}

    updates = {}
    if 'provider_type' in data:
        pt = data['provider_type']
        if pt not in ('psychiatrist', 'therapist', 'counselor'):
            return jsonify({'error': 'Invalid provider_type. Must be psychiatrist, therapist, or counselor'}), 400
        updates['provider_type'] = pt

    if updates:
        try:
            db.supabase_admin.table('profiles').update(updates).eq('id', user['id']).execute()
        except Exception as e:
            return jsonify({'error': f'Could not update profile: {e}'}), 500
    return jsonify({'message': 'Provider profile updated'}), 200


@app.route('/api/settings/password', methods=['POST'])
def api_change_password():
    user, err = _api_user()
    if err:
        return err
    data = request.json or {}
    ok, msg = auth_module.change_password(
        user['id'],
        data.get('current_password', ''),
        data.get('new_password', ''),
    )
    if not ok:
        return jsonify({'error': msg}), 400
    return jsonify({'message': msg}), 200


@app.route('/api/medications/info/<name>', methods=['GET'])
def api_medication_info(name):
    _, err = _api_user()
    if err:
        return err
    info = db.get_medication_info(name)
    if not info:
        return jsonify({'error': 'Medication not found'}), 404

    dose = info.get('common_dose')
    unit = info.get('dose_unit', 'mg')
    onset_h = info.get('typical_onset_hours')
    sides_raw = info.get('common_side_effects', [])

    # Build common_doses list — prefer the new JSONB column, fall back to legacy single-dose field
    common_doses_list = info.get('common_doses_list')
    if common_doses_list and isinstance(common_doses_list, list) and len(common_doses_list) > 0:
        common_doses = common_doses_list
    elif dose is not None:
        common_doses = [f"{dose} {unit}"]
    else:
        common_doses = []

    return jsonify({
        'name': info.get('name'),
        'category': info.get('category'),
        'common_doses': common_doses,
        'typical_onset': f"~{onset_h} hour{'s' if onset_h != 1 else ''}" if onset_h else 'Varies',
        'common_side_effects': ', '.join(s.replace('_', ' ') for s in sides_raw) if isinstance(sides_raw, list) else str(sides_raw),
        'interaction_warnings': info.get('notes') or None,
        # New fields from v2 schema
        'purpose': info.get('purpose') or None,
        'conditions_treated': info.get('conditions_treated') or None,
        'dosage_range': info.get('dosage_range') or None,
        'discontinuation_notes': info.get('discontinuation_notes') or None,
    }), 200


@app.route('/api/medications/interactions', methods=['GET'])
def api_medication_interactions():
    user, err = _api_user()
    if err:
        return err
    patient_id = user['id']
    if user['role'] == 'provider':
        patient_id = int(request.args.get('patient_id', 0))
        if not patient_id:
            return jsonify({'error': 'patient_id required'}), 400
    alerts = db.check_medication_interactions(patient_id)
    return jsonify({'interactions': alerts}), 200


@app.route('/api/settings/link-provider', methods=['POST'])
def api_link_provider():
    user, err = _api_user('patient')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    email = data.get('email', '').strip().lower()
    if not email:
        return jsonify({'error': 'Provider email required'}), 400
    provider = db.get_user_by_email(email)
    if not provider or provider['role'] != 'provider':
        return jsonify({'error': 'No provider account found with that email'}), 404
    db.assign_patient_to_provider(user['id'], provider['id'])
    return jsonify({'message': f'Linked to {provider["full_name"]}',
                    'provider_name': provider['full_name'],
                    'provider_email': provider['email']}), 200


@app.route('/api/settings/unlink-provider', methods=['POST'])
def api_unlink_provider():
    user, err = _api_user('patient')
    if err:
        return err
    db.assign_patient_to_provider(user['id'], None)
    return jsonify({'message': 'Provider unlinked'}), 200


@app.route('/api/medications/compare', methods=['POST'])
def api_medications_compare():
    """Compare up to 4 medications: returns per-med info + interactions between them."""
    _, err = _api_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    names = data.get('names', [])
    if not names or not isinstance(names, list):
        return jsonify({'error': 'names array required'}), 400
    names = [n.strip() for n in names if isinstance(n, str) and n.strip()][:4]
    if not names:
        return jsonify({'error': 'At least one medication name required'}), 400

    results = []
    for name in names:
        info = db.get_medication_info(name)
        if info:
            dose = info.get('common_dose')
            unit = info.get('dose_unit', 'mg')
            onset_h = info.get('typical_onset_hours')
            sides_raw = info.get('common_side_effects', [])
            common_doses_list = info.get('common_doses_list')
            if common_doses_list and isinstance(common_doses_list, list) and len(common_doses_list) > 0:
                common_doses = common_doses_list
            elif dose is not None:
                common_doses = [f"{dose} {unit}"]
            else:
                common_doses = []
            results.append({
                'query_name': name,
                'name': info.get('name'),
                'category': info.get('category'),
                'purpose': info.get('purpose'),
                'conditions_treated': info.get('conditions_treated'),
                'dosage_range': info.get('dosage_range'),
                'typical_onset': f"~{onset_h} hour{'s' if onset_h != 1 else ''}" if onset_h else 'Varies',
                'common_doses': common_doses,
                'common_side_effects': sides_raw if isinstance(sides_raw, list) else
                                       [s.strip() for s in str(sides_raw).split(',') if s.strip()],
                'interaction_warnings': info.get('notes') or None,
                'discontinuation_notes': info.get('discontinuation_notes') or None,
            })
        else:
            results.append({'query_name': name, 'name': name, 'not_found': True})

    interactions = db.check_interactions_for_names(names)
    return jsonify({'medications': results, 'interactions': interactions}), 200


@app.route('/api/settings/profile/remove-medication', methods=['POST'])
def api_remove_medication():
    user, err = _api_user('patient')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip().lower()
    dose = data.get('dose', '').strip().lower()
    if not name:
        return jsonify({'error': 'Medication name required'}), 400
    profile = db.get_patient_profile(user['id'])
    existing = profile.get('current_medications', []) if profile else []
    if not isinstance(existing, list):
        existing = []
    if dose:
        updated = [m for m in existing if not (
            m.get('name', '').lower() == name and m.get('dose', '').lower() == dose
        )]
    else:
        updated = [m for m in existing if m.get('name', '').lower() != name]
    db.update_patient_profile(user['id'], current_medications=updated)
    return jsonify({'message': f'{name.title()} removed', 'medications': updated}), 200


@app.route('/api/settings/reminders', methods=['POST'])
def api_set_reminders():
    """Patient toggles check-in reminder emails on or off."""
    user, err = _api_user('patient')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if 'enabled' not in data:
        return jsonify({'error': 'enabled (bool) is required'}), 400
    ok = db.set_checkin_reminders_enabled(user['id'], bool(data['enabled']))
    return (jsonify({'ok': True}), 200) if ok else (jsonify({'error': 'Update failed'}), 500)


# ── Internal: check-in reminders (Render cron or external scheduler) ──────────

_INTERNAL_SECRET = os.environ.get('INTERNAL_SECRET', '')

@app.route('/api/internal/send-checkin-reminders', methods=['GET'])
def api_send_checkin_reminders():
    """Send check-in reminder emails to eligible patients.

    Protected by X-Internal-Secret header matching the INTERNAL_SECRET env var.
    Designed to be called by a Render cron job or external scheduler — e.g.,
    once daily at 10am.

    Query params:
        min_days  – minimum days inactive before reminding (default 2)
        dry_run   – if 'true', return list without sending (default false)
    """
    secret = request.headers.get('X-Internal-Secret', '')
    if not _INTERNAL_SECRET or secret != _INTERNAL_SECRET:
        return jsonify({'error': 'Unauthorized'}), 401

    import email_utils as _eu
    min_days = max(1, int(request.args.get('min_days', 2)))
    dry_run  = request.args.get('dry_run', '').lower() == 'true'

    patients = db.get_patients_needing_checkin_reminder(min_days_inactive=min_days)
    results  = []
    sent     = 0
    failed   = 0

    for p in patients:
        if dry_run:
            results.append({'email': p['email'], 'days_since': p['days_since'], 'action': 'dry_run'})
            continue
        try:
            _eu.send_checkin_reminder(
                to_email=p['email'],
                to_name=p['full_name'].split()[0] if p['full_name'] else 'there',
                days_since=p['days_since'],
            )
            db.mark_reminder_sent(p['user_id'])
            results.append({'email': p['email'], 'days_since': p['days_since'], 'action': 'sent'})
            sent += 1
        except Exception as e:
            results.append({'email': p['email'], 'days_since': p['days_since'], 'action': 'failed', 'error': str(e)})
            failed += 1

    return jsonify({
        'eligible': len(patients),
        'sent':     sent,
        'failed':   failed,
        'dry_run':  dry_run,
        'results':  results,
    }), 200


@app.route('/api/trends/medication-timing', methods=['GET'])
def api_medication_timing():
    user, err = _api_user()
    if err:
        return err
    days = min(int(request.args.get('days', 30)), 180)
    patient_id = user['id']
    if user['role'] == 'provider':
        patient_id = int(request.args.get('patient_id', 0))
        if not patient_id:
            return jsonify({'error': 'patient_id required'}), 400
    stats = db.get_medication_timing_stats(patient_id, days=days)
    return jsonify(stats), 200


# ── Hypothesis Testing API ────────────────────────────────────────────────────

@app.route('/api/hypotheses/test', methods=['POST'])
def api_test_hypothesis():
    user, err = _api_user('patient')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    var_a = data.get('variable_a', '').strip().lower()
    var_b = data.get('variable_b', '').strip().lower()
    user_dir = data.get('user_direction', 'positive')
    days = min(int(data.get('days', 60)), 180)

    if var_a not in db.VALID_HYPOTHESIS_VARS or var_b not in db.VALID_HYPOTHESIS_VARS:
        return jsonify({'error': 'Invalid variable name'}), 400
    if var_a == var_b:
        return jsonify({'error': 'Variables must be different'}), 400
    if user_dir not in {'positive', 'null', 'negative'}:
        return jsonify({'error': 'Direction must be positive, null, or negative'}), 400

    pairs = db.get_paired_values(user['id'], var_a, var_b, days)
    if len(pairs) < 5:
        return jsonify({
            'error': f'Not enough matched data ({len(pairs)} check-ins have both {var_a} and {var_b}; need at least 5)'
        }), 400

    result = db.compute_correlation_evidence(pairs, user_dir, var_a, var_b)
    db.save_hypothesis_result(user['id'], var_a, var_b, user_dir, result)
    return jsonify(result), 200


@app.route('/api/hypotheses', methods=['GET'])
def api_hypothesis_history():
    user, err = _api_user('patient')
    if err:
        return err
    history = db.get_hypothesis_history(user['id'])
    return jsonify({'history': history}), 200


@app.route('/api/hypotheses/unexpected', methods=['GET'])
def api_unexpected_pattern():
    user, err = _api_user('patient')
    if err:
        return err
    days = min(int(request.args.get('days', 30)), 180)
    patterns = db.find_top_patterns(user['id'], days)
    return jsonify({'patterns': patterns}), 200


# ── Data Export ──────────────────────────────────────────────────────────────

@app.route('/api/export/checkins', methods=['GET'])
def api_export_checkins():
    """Download all check-ins as CSV."""
    user, err = _api_user('patient')
    if err:
        return err

    checkins = db.get_checkins(user['id'], days=36500)  # all-time

    out = io.StringIO()
    writer = csv.writer(out)

    # Header row
    writer.writerow([
        'date', 'mood', 'stress', 'sleep_hours',
        'stim_load', 'stability_score', 'crash_risk',
        'energy', 'focus', 'irritability', 'motivation', 'perceived_stress',
        'alcohol_units', 'exercise_minutes', 'sunlight_hours',
        'screen_time_hours', 'social_quality', 'workload_friction',
    ])

    for c in reversed(checkins):  # chronological order
        ext = c.get('extended_data') or {}
        if isinstance(ext, str):
            try:
                ext = json.loads(ext)
            except Exception:
                ext = {}

        def _ext(key):
            v = ext.get(key)
            return '' if v is None else v

        writer.writerow([
            c.get('checkin_date', ''),
            c.get('mood_score', ''),
            c.get('stress_score', ''),
            c.get('sleep_hours', ''),
            c.get('stim_load', ''),
            c.get('stability_score', ''),
            c.get('crash_risk', ''),
            _ext('energy'),
            _ext('focus'),
            _ext('irritability'),
            _ext('motivation'),
            _ext('perceived_stress'),
            _ext('alcohol_units'),
            _ext('exercise_minutes'),
            _ext('sunlight_hours'),
            _ext('screen_time_hours'),
            _ext('social_quality'),
            _ext('workload_friction'),
        ])

    csv_bytes = out.getvalue().encode('utf-8')
    filename = f"cognasync-checkins-{date.today().isoformat()}.csv"
    return Response(
        csv_bytes,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@app.route('/api/export/journals', methods=['GET'])
def api_export_journals():
    """Download all journal entries as CSV."""
    user, err = _api_user('patient')
    if err:
        return err

    journals = db.get_journals(user['id'], limit=10000)

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['date', 'title', 'content', 'shared_with_provider', 'ai_insight'])

    for j in reversed(journals):  # chronological order
        writer.writerow([
            j.get('entry_date', ''),
            j.get('title', ''),
            j.get('content', '') or j.get('entry_text', ''),
            'yes' if j.get('share_with_provider') else 'no',
            j.get('ai_insight', '') or '',
        ])

    csv_bytes = out.getvalue().encode('utf-8')
    filename = f"cognasync-journals-{date.today().isoformat()}.csv"
    return Response(
        csv_bytes,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


# ── AI Feedback ───────────────────────────────────────────────────────────────

@app.route('/api/feedback', methods=['POST'])
def api_log_feedback():
    """Record a thumbs-up or thumbs-down on any AI-generated output."""
    user, err = _api_user('patient')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    content_type = data.get('content_type', '')
    content_id   = data.get('content_id', '')
    rating        = data.get('rating', '')
    if not content_type or not content_id or not rating:
        return jsonify({'error': 'content_type, content_id, and rating are required'}), 400
    try:
        db.log_ai_feedback(user['id'], content_type, content_id, rating)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'message': 'Feedback recorded'}), 200


# ═══════════════════════════════════════════════════════════════════════════
# INTELLIGENCE LAYER — transcript-to-brief pipeline
#
# Routes in this section power the pivot architecture.
# Provider pages:
#   GET  /provider/intel                            — patient list
#   GET  /provider/intel/<patient_id>               — transcript upload + brief view
# Provider APIs:
#   POST /api/intel/patient/<patient_id>/session    — upload transcript, extract features
#   GET  /api/intel/patient/<patient_id>/sessions   — list sessions for period
#   POST /api/intel/patient/<patient_id>/brief      — generate + store Mode C brief
#   GET  /api/intel/patient/<patient_id>/briefs     — list recent briefs
#   GET  /api/intel/brief/<brief_id>                — fetch full brief text
# ═══════════════════════════════════════════════════════════════════════════


@app.route('/provider/intel')
def provider_intel_index():
    """Intelligence layer patient list — providers see all patients with sessions."""
    provider, err = _require_provider()
    if err:
        return err

    patients = db.get_intel_patients_for_provider(provider['id'])
    return render_template(
        'provider/intel_index.html',
        provider=provider,
        patients=patients,
    )


@app.route('/provider/intel/<patient_id>')
def provider_intel_dashboard(patient_id):
    """Intelligence layer dashboard for a single patient."""
    provider, err = _require_provider()
    if err:
        return err

    patient_row = db.get_user_by_id(patient_id)
    if not patient_row:
        return 'Patient not found', 404

    sessions = db.get_clinical_sessions_for_period(patient_id, limit=20)
    briefs   = db.get_provider_briefs_for_patient(provider['id'], patient_id, limit=5)

    return render_template(
        'provider/intel_dashboard.html',
        provider=provider,
        patient=patient_row,
        sessions=sessions,
        briefs=briefs,
        today=date.today().isoformat(),
    )


@app.route('/api/intel/patient/<patient_id>/audio-session', methods=['POST'])
def api_intel_upload_audio_session(patient_id):
    """
    Upload an audio file, store it, and kick off background transcription + extraction.
    Returns immediately (201) while processing continues in a background thread.

    Accepts multipart/form-data:
        audio_file      — required, audio file (MP3, M4A, WAV, FLAC, OGG, WebM)
        session_date    — YYYY-MM-DD, defaults to today
        session_type    — 'psychiatry'|'therapy'|..., defaults to 'therapy'
        duration_minutes — optional int

    Returns:
        {
            "session_id":  str,
            "status":      "transcribing",
            "message":     str     # human-readable status
        }

    The frontend should poll GET /api/intel/patient/<id>/sessions to watch
    for status changes from 'transcribing' → 'extracting' → 'complete'|'error'.
    """
    provider, err = _api_user('provider')
    if err:
        return err

    if 'audio_file' not in request.files:
        return jsonify({'error': 'audio_file is required (multipart/form-data)'}), 400

    audio_file    = request.files['audio_file']
    session_date  = request.form.get('session_date') or str(date.today())
    session_type  = request.form.get('session_type', 'therapy')
    duration_mins = request.form.get('duration_minutes')
    if duration_mins:
        try:
            duration_mins = int(duration_mins)
        except ValueError:
            duration_mins = None

    valid_types = {'psychiatry', 'therapy', 'intake', 'followup', 'group', 'other'}
    if session_type not in valid_types:
        session_type = 'other'

    filename   = audio_file.filename or 'recording.audio'
    file_bytes = audio_file.read()
    mime_type  = audio_file.content_type

    # Validate before touching the DB
    from audio_engine import validate_audio_file
    valid, err_msg = validate_audio_file(filename, file_bytes, mime_type)
    if not valid:
        return jsonify({'error': err_msg}), 400

    # Create the session record immediately so the UI can show it
    session_id = db.store_clinical_session(
        provider_id=provider['id'],
        patient_id=patient_id,
        session_date=session_date,
        session_type=session_type,
        transcript_raw='',          # populated by background thread after transcription
        duration_minutes=duration_mins,
        transcript_source='audio_upload',
    )
    if not session_id:
        return jsonify({'error': 'Failed to create session record'}), 500

    # Set status to transcribing before kicking off the thread
    db.update_clinical_session_status(session_id, 'transcribing')

    # Fire and forget — background thread owns the rest of the pipeline
    from audio_engine import process_audio_session_async
    process_audio_session_async(
        session_id=session_id,
        patient_id=patient_id,
        file_bytes=file_bytes,
        filename=filename,
        session_date=session_date,
        session_type=session_type,
    )

    return jsonify({
        'session_id': session_id,
        'status':     'transcribing',
        'message':    'Audio uploaded. Transcription is running in the background — refresh the session list in 1–2 minutes.',
    }), 201


@app.route('/api/intel/patient/<patient_id>/session', methods=['POST'])
def api_intel_upload_session(patient_id):
    """
    Upload a session transcript, run extraction, and persist.

    Accepts JSON:
        {
            "transcript":       str,
            "session_date":     str,          # YYYY-MM-DD, defaults to today
            "session_type":     str,          # 'psychiatry'|'therapy'|..., defaults to 'therapy'
            "duration_minutes": int | null
        }

    Returns:
        {
            "session_id":          str,
            "crisis_detected":     bool,
            "safety_note":         str | null,
            "extraction_richness": int,
            "status":              "complete" | "error"
        }
    """
    provider, err = _api_user('provider')
    if err:
        return err

    data = request.get_json(silent=True) or {}
    transcript = data.get('transcript', '').strip()
    if not transcript:
        return jsonify({'error': 'transcript is required'}), 400

    session_date  = data.get('session_date') or str(date.today())
    session_type  = data.get('session_type', 'therapy')
    duration_mins = data.get('duration_minutes')

    valid_types = {'psychiatry', 'therapy', 'intake', 'followup', 'group', 'other'}
    if session_type not in valid_types:
        session_type = 'other'

    try:
        # 1. Persist raw session
        session_id = db.store_clinical_session(
            provider_id=provider['id'],
            patient_id=patient_id,
            session_date=session_date,
            session_type=session_type,
            transcript_raw=transcript,
            duration_minutes=duration_mins,
        )
        if not session_id:
            return jsonify({'error': 'Failed to store session — check server logs'}), 500

        # 2. Extract features (crisis detection runs inside extract_features)
        from transcript_engine import extract_features
        population_flags = db.get_patient_population_flags(patient_id)
        extraction = extract_features(
            transcript_text=transcript,
            session_date=session_date,
            session_type=session_type,
            population_flags=population_flags or None,
        )

        # 3. Persist features
        db.store_session_features(
            session_id=session_id,
            patient_id=patient_id,
            extraction_result=extraction,
            extraction_model=os.environ.get('CLAUDE_MODEL', 'claude-haiku-4-5-20251001'),
        )

        richness = (extraction.get('scores') or {}).get('extraction_richness', 0)
        return jsonify({
            'session_id':          session_id,
            'crisis_detected':     extraction.get('crisis_detected', False),
            'safety_note':         extraction.get('safety_note'),
            'extraction_richness': richness,
            'status':              'error' if extraction.get('error') else 'complete',
            'error':               extraction.get('error'),
        }), 201

    except Exception as _exc:
        import traceback
        print(f"api_intel_upload_session unhandled error: {_exc}\n{traceback.format_exc()}")
        return jsonify({'error': f'Server error: {str(_exc)}'}), 500


@app.route('/api/intel/patient/<patient_id>/sessions', methods=['GET'])
def api_intel_get_sessions(patient_id):
    """
    List clinical sessions for a patient.
    Query params: period_start, period_end (both YYYY-MM-DD, optional), limit (default 20).
    """
    provider, err = _api_user('provider')
    if err:
        return err

    period_start = request.args.get('period_start')
    period_end   = request.args.get('period_end')
    limit        = min(int(request.args.get('limit', 20)), 50)

    sessions = db.get_clinical_sessions_for_period(
        patient_id=patient_id,
        period_start=period_start,
        period_end=period_end,
        limit=limit,
    )
    return jsonify({'sessions': sessions})


@app.route('/api/intel/patient/<patient_id>/session/<session_id>/status', methods=['GET'])
def api_intel_session_status(patient_id, session_id):
    """
    Lightweight poll endpoint for a single session's processing status.
    Used by the frontend to track audio transcription progress.

    Returns:
        {
            "session_id":        str,
            "processing_status": str,   # pending|transcribing|extracting|complete|error
            "processing_error":  str | null,
            "crisis_detected":   bool,
            "themes":            [str],  # populated once complete
        }
    """
    provider, err = _api_user('provider')
    if err:
        return err

    session = db.get_clinical_session_by_id(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    themes = (session.get('features') or {}).get('themes') or []
    return jsonify({
        'session_id':        session['session_id'],
        'processing_status': session['processing_status'],
        'processing_error':  session.get('processing_error'),
        'crisis_detected':   session['crisis_detected'],
        'themes':            themes,
    })


@app.route('/api/intel/patient/<patient_id>/brief', methods=['POST'])
def api_intel_generate_brief(patient_id):
    """
    Generate a Mode C provider brief from stored session features.

    Accepts JSON:
        {
            "period_start":  str | null,
            "period_end":    str | null,
            "session_ids":   [str] | null   # specific sessions; omit to use period
        }

    Returns:
        {
            "brief_id":        str,
            "status":          "safe" | "crisis" | "error",
            "text":            str,
            "crisis_detected": bool,
            "session_count":   int
        }
    """
    provider, err = _api_user('provider')
    if err:
        return err

    from datetime import date as _date, timedelta as _timedelta
    data         = request.get_json(silent=True) or {}
    period_start = data.get('period_start')
    period_end   = data.get('period_end')
    session_ids  = data.get('session_ids')
    include_medications = data.get('include_medications', False)

    # Derive period from period_days if explicit dates not given
    period_days = data.get('period_days')
    if period_days and not period_start:
        try:
            n = int(period_days)
            period_end   = _date.today().isoformat()
            period_start = (_date.today() - _timedelta(days=n)).isoformat()
        except (TypeError, ValueError):
            pass

    # Fetch session feature data
    if session_ids:
        all_sessions  = db.get_clinical_sessions_for_period(patient_id=patient_id, limit=50)
        sessions_data = [s for s in all_sessions if s['session_id'] in session_ids]
    else:
        sessions_data = db.get_clinical_sessions_for_period(
            patient_id=patient_id,
            period_start=period_start,
            period_end=period_end,
            limit=20,
        )

    # Fallback: lazily process voice notes not yet in clinical_sessions
    if not session_ids:
        try:
            known_dates = {s['session_date'] for s in sessions_data if s.get('session_date')}
            orphans = db.get_voice_notes_for_period(
                patient_id=patient_id,
                period_start=period_start,
                period_end=period_end,
                limit=5,
            )
            for vn in orphans:
                vn_date = (vn.get('created_at') or '')[:10]
                if vn_date in known_dates:
                    continue
                text = (vn.get('transcript') or '').strip()
                if not text:
                    continue
                try:
                    from transcript_engine import extract_features as _ef
                    extraction = _ef(transcript_text=text, session_date=vn_date, session_type='voice_note')
                    sid = db.store_clinical_session(
                        provider_id=None,
                        patient_id=patient_id,
                        session_date=vn_date,
                        session_type='voice_note',
                        transcript_raw=text,
                        transcript_source='voice_note',
                    )
                    if sid:
                        db.store_session_features(session_id=sid, patient_id=patient_id, extraction_result=extraction)
                        sessions_data.append({
                            'session_id': sid, 'session_date': vn_date,
                            'session_type': 'voice_note', 'processing_status': 'complete',
                            'transcript_source': 'voice_note',
                            'crisis_detected': extraction.get('crisis_detected', False),
                            'features': extraction.get('features') or {},
                            'scores': extraction.get('scores') or {},
                        })
                        known_dates.add(vn_date)
                except Exception as _e:
                    app.logger.warning(f'[intel-brief] voice note fallback: {_e}')
        except Exception as _e2:
            app.logger.warning(f'[intel-brief] voice note outer: {_e2}')

    if not sessions_data:
        return jsonify({'error': 'No sessions found for the specified period'}), 404

    # Reshape for transcript_engine functions
    session_results = [
        {
            'crisis_detected': s['crisis_detected'],
            'session_date':    s['session_date'],
            'session_type':    s['session_type'],
            'features':        s['features'],
            'scores':          s['scores'],
        }
        for s in sessions_data
    ]

    from transcript_engine import score_transcript_batch
    aggregated = score_transcript_batch(session_results)

    # ── Pull acoustic and affect data from stored session scores ──────────────
    # Each session's background pipeline stored acoustic_features and
    # affect_dimensions in scores. Extract, add session_date, then aggregate.
    acoustic_vocab_list: list[dict] = []
    affect_list:         list[dict] = []

    for s in sessions_data:
        scores      = s.get('scores') or {}
        session_date = s.get('session_date')

        acf = scores.get('acoustic_features')
        if acf and isinstance(acf, dict):
            vocab = acf.get('vocabulary')
            if vocab and isinstance(vocab, dict):
                vocab = dict(vocab)
                vocab['session_date'] = session_date
                acoustic_vocab_list.append(vocab)

        afd = scores.get('affect_dimensions')
        if afd and isinstance(afd, dict) and afd.get('model_available'):
            afd = dict(afd)
            afd['session_date'] = session_date
            affect_list.append(afd)

    voice_memo_summary = None
    if acoustic_vocab_list:
        try:
            from acoustic_engine import aggregate_acoustic_sessions
            voice_memo_summary = aggregate_acoustic_sessions(acoustic_vocab_list)
        except Exception as e:
            app.logger.warning("acoustic aggregation failed: %s", e)

    affect_summary = None
    if affect_list:
        try:
            from affect_model import aggregate_affect_sessions
            affect_summary = aggregate_affect_sessions(affect_list)
        except Exception as e:
            app.logger.warning("affect aggregation failed: %s", e)

    # ── Optionally enrich with medication records ──────────────────────────────
    med_records = None
    if include_medications:
        raw_meds = db.get_user_medications(patient_id, active_only=True)
        med_records = [
            {
                'medication_name': m.get('name', ''),
                'dose_amount':     m.get('standard_dose', ''),
                'dose_unit':       m.get('dose_unit', 'mg'),
                'frequency':       m.get('frequency', ''),
            }
            for m in raw_meds
        ] if raw_meds else None

    # Generate brief
    brief_result = claude_api.generate_brief_from_sessions(
        aggregated_scores=aggregated,
        session_features=session_results,
        period_start=period_start,
        period_end=period_end,
        voice_memo_summary=voice_memo_summary,
        affect_summary=affect_summary,
        medication_records=med_records,
        audience='provider',
    )

    if brief_result.get('status') == 'error':
        return jsonify({'error': brief_result.get('text', 'Generation failed')}), 500

    # Persist
    used_session_ids = [s['session_id'] for s in sessions_data]
    brief_id = db.store_provider_brief(
        patient_id=patient_id,
        provider_id=provider['id'],
        brief_text=brief_result['text'],
        session_ids=used_session_ids,
        period_start=period_start,
        period_end=period_end,
        scores=aggregated,
        crisis_detected=(brief_result.get('crisis_sessions', 0) > 0),
        model_version=os.environ.get('CLAUDE_MODEL', 'claude-sonnet-4-6'),
    )

    return jsonify({
        'brief_id':        brief_id,
        'status':          brief_result['status'],
        'text':            brief_result['text'],
        'crisis_detected': brief_result.get('crisis_sessions', 0) > 0,
        'session_count':   aggregated['session_count'],
        'scores':          aggregated,
        'period_start':    period_start,
        'period_end':      period_end,
    }), 201


@app.route('/api/intel/patient/<patient_id>/briefs', methods=['GET'])
def api_intel_list_briefs(patient_id):
    """List recent provider briefs for a patient."""
    provider, err = _api_user('provider')
    if err:
        return err

    limit  = min(int(request.args.get('limit', 5)), 20)
    briefs = db.get_provider_briefs_for_patient(provider['id'], patient_id, limit=limit)
    return jsonify({'briefs': briefs})


@app.route('/api/intel/brief/<brief_id>', methods=['GET'])
def api_intel_get_brief(brief_id):
    """Fetch full brief text by ID."""
    provider, err = _api_user('provider')
    if err:
        return err

    brief = db.get_provider_brief_by_id(brief_id, provider['id'])
    if not brief:
        return jsonify({'error': 'Brief not found'}), 404
    return jsonify(brief)


@app.route('/api/intel/brief/<brief_id>', methods=['DELETE'])
def api_intel_delete_brief(brief_id):
    """Delete a provider brief owned by the requesting provider."""
    provider, err = _api_user('provider')
    if err:
        return err

    ok = db.delete_provider_brief(provider['id'], brief_id)
    if not ok:
        return jsonify({'error': 'Delete failed'}), 500
    return jsonify({'ok': True})


@app.route('/api/intel/patient/<patient_id>/session/<session_id>', methods=['DELETE'])
def api_intel_delete_session(patient_id, session_id):
    """Delete a clinical session and its extracted features."""
    provider, err = _api_user('provider')
    if err:
        return err
    if not _provider_owns_patient(provider['id'], patient_id):
        return jsonify({'error': 'Access denied.'}), 403

    ok = db.delete_clinical_session(patient_id, session_id)
    if not ok:
        return jsonify({'error': 'Delete failed'}), 500
    return jsonify({'ok': True})


@app.route('/api/provider/patient/<patient_id>/voice-note/<note_id>', methods=['DELETE'])
def api_provider_delete_voice_note(patient_id, note_id):
    """Delete a voice recording for a patient."""
    provider, err = _api_user('provider')
    if err:
        return err
    if not _provider_owns_patient(provider['id'], patient_id):
        return jsonify({'error': 'Access denied.'}), 403

    ok = db.delete_voice_note(patient_id, note_id)
    if not ok:
        return jsonify({'error': 'Delete failed'}), 500
    return jsonify({'ok': True})


@app.route('/api/provider/patient/<patient_id>/summary/<summary_id>', methods=['DELETE'])
def api_provider_delete_summary(patient_id, summary_id):
    """Delete a patient summary/brief from the provider hub."""
    provider, err = _api_user('provider')
    if err:
        return err
    if not _provider_owns_patient(provider['id'], patient_id):
        return jsonify({'error': 'Access denied.'}), 403

    ok = db.delete_summary(patient_id, summary_id)
    if not ok:
        return jsonify({'error': 'Delete failed'}), 500
    return jsonify({'ok': True})


# ── end intelligence layer routes ────────────────────────────────────────────


# ── SMS / Voice Note routes ───────────────────────────────────────────────────

import sms_engine as _sms

def _validate_checkin_token(token_str):
    """Return token record dict or None. Does not mark used."""
    from datetime import datetime, timezone
    try:
        res = db.supabase_admin.table('checkin_tokens').select('*').eq(
            'token', token_str).limit(1).execute()
        if not res.data:
            return None
        tok = res.data[0]
        if tok.get('used_at'):
            return None
        expires = tok.get('expires_at', '')
        if expires:
            exp_dt = datetime.fromisoformat(expires.replace('Z', '+00:00'))
            if datetime.now(timezone.utc) > exp_dt:
                return None
        return tok
    except Exception:
        return None


@app.route('/checkin/go/<token_str>')
def checkin_magic_link(token_str):
    """Magic link entry point from SMS. Validates token then redirects to check-in."""
    tok = _validate_checkin_token(token_str)
    if not tok:
        return render_template('token_invalid.html',
            message='Check-in links expire after 48 hours and can only be used once. Your provider can send a new link if needed.'), 410
    # Mark used
    db.supabase_admin.table('checkin_tokens').update(
        {'used_at': 'now()'}
    ).eq('token', token_str).execute()
    appt_id = tok.get('appointment_id')
    qs = '?mode=sms'
    if appt_id:
        qs += f'&appointment_id={appt_id}'
    return redirect(f'/checkin{qs}')


@app.route('/voice/<token_str>')
def voice_note_page(token_str):
    """Patient-facing voice note recording page. No login required."""
    tok = _validate_checkin_token(token_str)
    if not tok:
        return render_template('token_invalid.html',
            message='Voice note links expire after 48 hours. Your provider can send a new link if needed.'), 410
    prompt = tok.get('voice_prompt') or _sms.DEFAULT_VOICE_PROMPTS['default']
    return render_template('patient/voice_note.html',
                           token=token_str,
                           guiding_question=prompt)


@app.route('/api/voice/submit/<token_str>', methods=['POST'])
def api_voice_submit(token_str):
    """Receive patient voice note audio. No login required."""
    tok = _validate_checkin_token(token_str)
    if not tok:
        return jsonify({'error': 'Invalid or expired link'}), 410

    if 'audio' not in request.files:
        return jsonify({'error': 'No audio file provided'}), 400

    audio_file = request.files['audio']
    audio_bytes = audio_file.read()
    if len(audio_bytes) > 10 * 1024 * 1024:
        return jsonify({'error': 'Audio file too large (max 10 MB)'}), 413

    patient_id = tok['patient_id']
    file_name = f"{patient_id}/{token_str}.webm"

    # Upload to Supabase Storage
    audio_url = None
    try:
        db.supabase_admin.storage.from_('voice-notes').upload(
            path=file_name,
            file=audio_bytes,
            file_options={'content-type': audio_file.mimetype or 'audio/webm'},
        )
        audio_url = db.supabase_admin.storage.from_('voice-notes').get_public_url(file_name)
    except Exception as e:
        app.logger.error(f'[voice] Storage upload failed: {e}')
        # Continue — we can still store the note without a URL

    # Insert voice_notes row
    vn_row = {
        'patient_id':        patient_id,
        'token_id':          tok['id'],
        'guiding_question':  tok.get('voice_prompt'),
        'audio_url':         audio_url,
        'processing_status': 'pending',
    }
    if tok.get('appointment_id'):
        vn_row['appointment_id'] = tok['appointment_id']
    if tok.get('provider_id'):
        vn_row['provider_id'] = tok['provider_id']

    res = db.supabase_admin.table('voice_notes').insert(vn_row).execute()
    voice_note_id = res.data[0]['id'] if res.data else None

    # Mark token used
    db.supabase_admin.table('checkin_tokens').update(
        {'used_at': 'now()'}
    ).eq('token', token_str).execute()

    # Background transcription + full intelligence pipeline
    if voice_note_id and audio_bytes:
        import threading as _threading
        _audio_bytes_snapshot = audio_bytes
        _session_date_snapshot = datetime.utcnow().date().isoformat()
        def _transcribe():
            try:
                import uuid as _uuid
                from audio_engine import transcribe_audio_file, _run_acoustic_extraction
                from transcript_engine import extract_features

                # 1. Transcribe
                result = transcribe_audio_file(
                    file_bytes=_audio_bytes_snapshot,
                    filename='voice_note.webm',
                    patient_id=patient_id,
                    session_id=str(_uuid.uuid4()),
                )
                if not (result.get('status') == 'completed' and result.get('text')):
                    db.supabase_admin.table('voice_notes').update({
                        'processing_status': 'error',
                        'processing_error':  result.get('error', 'Transcription failed'),
                    }).eq('id', voice_note_id).execute()
                    return

                transcript_text = result['text']

                # Update voice_notes with transcript
                db.supabase_admin.table('voice_notes').update({
                    'transcript':        transcript_text,
                    'processing_status': 'processing',
                }).eq('id', voice_note_id).execute()

                # 2. Semantic extraction via Claude
                population_flags = db.get_patient_population_flags(patient_id) or {}
                extraction = extract_features(
                    transcript_text=transcript_text,
                    session_date=_session_date_snapshot,
                    session_type='voice_note',
                    population_flags=population_flags,
                )

                # 3. Acoustic extraction (non-fatal)
                try:
                    acoustic_result = _run_acoustic_extraction(
                        file_bytes=_audio_bytes_snapshot,
                        filename='voice_note.webm',
                        session_id=str(voice_note_id),
                        session_date=_session_date_snapshot,
                    )
                    if acoustic_result:
                        scores = extraction.setdefault('scores', {})
                        scores['acoustic_features'] = acoustic_result  # full dict: {vocabulary, raw, affect}
                        if acoustic_result.get('affect'):
                            scores['affect_dimensions'] = acoustic_result['affect']
                except Exception as ae:
                    app.logger.warning(f'[voice] Acoustic extraction skipped: {ae}')

                # 4. Create clinical_sessions row so brief generation can find it
                provider_id_for_session = tok.get('provider_id')
                session_id = db.store_clinical_session(
                    provider_id=provider_id_for_session,
                    patient_id=patient_id,
                    session_date=_session_date_snapshot,
                    session_type='voice_note',
                    transcript_raw=transcript_text,
                    transcript_source='voice_note',
                )

                if session_id:
                    db.store_session_features(
                        session_id=session_id,
                        patient_id=patient_id,
                        extraction_result=extraction,
                    )

                # Mark voice_note complete (link to session if column exists)
                vn_update = {'processing_status': 'complete'}
                if session_id:
                    try:
                        db.supabase_admin.table('voice_notes').update({
                            **vn_update, 'clinical_session_id': session_id,
                        }).eq('id', voice_note_id).execute()
                    except Exception:
                        db.supabase_admin.table('voice_notes').update(
                            vn_update).eq('id', voice_note_id).execute()
                else:
                    db.supabase_admin.table('voice_notes').update(
                        vn_update).eq('id', voice_note_id).execute()

            except Exception as ex:
                app.logger.error(f'[voice] Pipeline failed: {ex}')
                db.supabase_admin.table('voice_notes').update({
                    'processing_status': 'error',
                    'processing_error':  str(ex),
                }).eq('id', voice_note_id).execute()
        _threading.Thread(target=_transcribe, daemon=True).start()

    return jsonify({'ok': True, 'voice_note_id': voice_note_id}), 201


@app.route('/api/sms/inbound', methods=['POST'])
def api_sms_inbound():
    """Twilio inbound SMS webhook — full 8-priority routing table.

    Priority order (see CLAUDE.md / sms-checkin-design.md):
      1. Crisis keywords     → patient crisis resources + provider alert
      2. CRISIS (branch)     → patient crisis resources + provider alert
      3. Y / N               → medication adherence (if med session pending)
      4. SYSTEM (branch)     → labeled check-in guide
      5. ≥4 numbers          → parse as M·E·S·Q·H check-in
      6. SKIP                → log skip, resolve session
      7. HELP or ?           → open help branch, suspend current session
      8. Unrecognised        → context-aware hint or silent ignore
    """
    from_number = request.form.get('From', '').strip()
    body        = request.form.get('Body', '').strip()

    if not from_number or not body:
        return _twiml_empty()

    # ── Resolve patient from phone number ─────────────────────────────────────
    try:
        prof_res = db.supabase_admin.table('profiles').select(
            'id, full_name').eq('phone_number', from_number).limit(1).execute()
        if not prof_res.data:
            return _twiml_empty()
        patient_id   = prof_res.data[0]['id']
        patient_name = prof_res.data[0].get('full_name', 'Your patient')
    except Exception as e:
        app.logger.error(f'[sms_inbound] profile lookup error: {e}')
        return _twiml_empty()

    cleaned = body.strip()
    upper   = cleaned.upper()

    # ── Priority 1: Crisis keywords (free text) ───────────────────────────────
    if _sms.detect_crisis_keywords(cleaned):
        _handle_sms_crisis(patient_id, patient_name, from_number, source='keyword')
        return _twiml_empty()

    # ── Priority 2: CRISIS (explicit branch reply) ────────────────────────────
    if upper == 'CRISIS':
        session = db.get_sms_session(patient_id)
        if session and session['session_type'] == 'help_pending':
            _handle_sms_crisis(patient_id, patient_name, from_number, source='help_branch')
            db.resolve_sms_session(patient_id)
            # Discard any suspended session — patient needs space, not a re-prompt
        return _twiml_empty()

    # ── Priority 3: Y / N medication reply ───────────────────────────────────
    taken = _sms.parse_medication_reply(cleaned)
    if taken is not None:
        session = db.get_sms_session(patient_id)
        if session and session['session_type'] == 'med_pending':
            try:
                log_res = db.supabase_admin.table('medication_sms_logs').select(
                    'id').eq('patient_id', patient_id).is_(
                    'replied_at', 'null').order('sent_at', desc=True).limit(1).execute()
                if log_res.data:
                    db.supabase_admin.table('medication_sms_logs').update({
                        'replied_at': 'now()',
                        'taken':      taken,
                        'raw_reply':  cleaned[:200],
                    }).eq('id', log_res.data[0]['id']).execute()
                db.resolve_sms_session(patient_id)
            except Exception as e:
                app.logger.error(f'[sms_inbound] med reply error: {e}')
        return _twiml_empty()

    # ── Priority 4: SYSTEM (help branch — wants check-in guide) ──────────────
    if upper == 'SYSTEM':
        session = db.get_sms_session(patient_id)
        if session and session['session_type'] == 'help_pending':
            _sms.send_checkin_guide_sms(from_number)
            # Restore suspended session if there was one
            suspended = session.get('suspended_session_type')
            db.resolve_sms_session(patient_id)
            if suspended:
                db.set_sms_session(patient_id, suspended)
        return _twiml_empty()

    # ── Priority 5: ≥4 numbers — check-in reply ───────────────────────────────
    parsed = _sms.parse_checkin_reply(cleaned)
    if parsed is not None:
        session = db.get_sms_session(patient_id)
        if session and session['session_type'] == 'checkin_pending':
            try:
                sleep_hrs = parsed.get('sleep_hours')
                ext = {
                    'energy':               parsed['energy'],
                    'sleep_quality':        parsed['sleep_quality'],
                    'dissociation':         0,
                    'dissociation_source':  'sms_default',
                    'checkin_source':       'sms',
                }
                db.create_checkin(
                    user_id      = patient_id,
                    mood_score   = parsed['mood'],
                    stress_score = parsed['stress'],
                    sleep_hours  = sleep_hrs,
                    notes        = None,
                    checkin_type = 'sms',
                    extended_data= ext,
                )
                db.resolve_sms_session(patient_id)
                mood_int  = int(round(parsed['mood']))
                energy_int= int(round(parsed['energy']))
                stress_int= int(round(parsed['stress']))
                sleep_disp= (f'{sleep_hrs:.1f}' if sleep_hrs is not None
                             else '—').rstrip('0').rstrip('.')
                confirm = (
                    f"✓ Logged — Mood {mood_int} · Energy {energy_int} · "
                    f"Stress {stress_int} · Sleep {sleep_disp}hrs. Have a good day."
                )
                _sms.send_sms(from_number, confirm)
            except Exception as e:
                app.logger.error(f'[sms_inbound] checkin write error: {e}')
        return _twiml_empty()

    # ── Priority 6: SKIP ──────────────────────────────────────────────────────
    if upper == 'SKIP':
        db.resolve_sms_session(patient_id)
        return _twiml_empty()

    # ── Priority 7: HELP or ? ─────────────────────────────────────────────────
    if upper in ('HELP', '?', 'HELP?'):
        current = db.get_sms_session(patient_id)
        suspended = current['session_type'] if current else None
        db.set_sms_session(patient_id, 'help_pending',
                           suspended_session_type=suspended)
        _sms.send_help_branch_sms(from_number)
        return _twiml_empty()

    # ── Priority 8: Unrecognised — context-aware hint ─────────────────────────
    session = db.get_sms_session(patient_id)
    if session:
        stype = session['session_type']
        if stype == 'checkin_pending':
            _sms.send_sms(from_number, _sms.MSG_CHECKIN_PARSE_FAIL)
        elif stype == 'med_pending':
            _sms.send_sms(from_number, 'Reply Y if taken, N if skipped.')
        elif stype == 'help_pending':
            _sms.send_sms(from_number, 'Reply CRISIS if you need support, or SYSTEM for check-in help.')
    # No active session → ignore silently

    return _twiml_empty()


def _twiml_empty():
    """Return an empty TwiML response (no outbound message via Twilio Studio)."""
    return app.response_class(
        '<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
        mimetype='text/xml',
    )


def _handle_sms_crisis(patient_id: str, patient_name: str,
                        from_number: str, source: str) -> None:
    """Shared crisis handler: send patient resources, log event, alert provider."""
    # 1. Send patient crisis resources immediately
    _sms.send_crisis_sms_to_patient(from_number)

    # 2. Log the event (no patient text stored)
    event_id = db.log_sms_crisis(patient_id, source=source)

    # 3. Resolve any open session
    db.resolve_sms_session(patient_id)

    # 4. Alert provider via SMS + insert care_flags row (Clinical Alerts)
    try:
        provider = db.get_provider_for_patient(patient_id)
        if provider:
            # SMS the provider
            if provider.get('phone_number'):
                result = _sms.send_provider_crisis_alert(
                    provider['phone_number'], patient_name)
                if event_id and result.get('ok'):
                    db.mark_provider_notified(event_id, sms_sid=result.get('sid'))

            # Insert into care_flags (surfaces as "Clinical Alerts" on the hub)
            # flag_type='concern', author = patient's provider, body = crisis notice
            source_label = source.replace('_', ' ')  # 'keyword' or 'help branch'
            flag_body = (
                f'🔴 SMS crisis signal ({source_label}) — {patient_name} reached out '
                f'via SMS and may need immediate support. Please check in directly.'
            )
            db.supabase_admin.table('care_flags').insert({
                'patient_id':         str(patient_id),
                'author_provider_id': str(provider['id']),
                'flag_type':          'concern',
                'body':               flag_body,
                'visibility':         'care_team',
            }).execute()
    except Exception as e:
        app.logger.error(f'[sms_inbound] provider alert/flag error: {e}')


@app.route('/api/internal/send-appointment-sms', methods=['POST', 'GET'])
def api_send_appointment_sms():
    """Cron endpoint: send check-in SMS for appointments in the next 24-48 hours."""
    secret = request.headers.get('X-Internal-Secret', '')
    if not _INTERNAL_SECRET or secret != _INTERNAL_SECRET:
        return jsonify({'error': 'Unauthorized'}), 401

    dry_run = request.args.get('dry_run', '').lower() == 'true'
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    window_start = now + timedelta(hours=24)
    window_end   = now + timedelta(hours=48)

    try:
        appt_res = db.supabase_admin.table('provider_appointments').select(
            'id, patient_id, provider_id, appointment_date'
        ).gte('appointment_date', window_start.date().isoformat()).lte(
            'appointment_date', window_end.date().isoformat()
        ).execute()
        appointments = appt_res.data or []
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    results = []
    for appt in appointments:
        patient_id = appt['patient_id']
        try:
            prof = db.supabase_admin.table('profiles').select(
                'full_name, phone_number'
            ).eq('id', patient_id).single().execute()
            phone = (prof.data or {}).get('phone_number')
            name  = (prof.data or {}).get('full_name', '')
            if not phone:
                results.append({'patient_id': patient_id, 'action': 'skipped', 'reason': 'no phone'})
                continue
            if dry_run:
                results.append({'patient_id': patient_id, 'action': 'dry_run', 'phone': phone[-4:]})
                continue
            token = _sms.create_checkin_token(
                patient_id=patient_id,
                appointment_id=appt['id'],
                provider_id=appt.get('provider_id'),
            )
            res = _sms.send_checkin_sms(phone, name, token)
            results.append({'patient_id': patient_id, 'action': 'sent' if res.get('ok') else 'failed'})
        except Exception as e:
            results.append({'patient_id': patient_id, 'action': 'error', 'error': str(e)})

    return jsonify({'sent': sum(1 for r in results if r.get('action') == 'sent'),
                   'skipped': sum(1 for r in results if r.get('action') == 'skipped'),
                   'dry_run': dry_run, 'results': results})


@app.route('/api/provider/patient/<patient_id>/send-checkin-sms', methods=['POST'])
def api_send_patient_checkin_sms(patient_id):
    """Provider manually triggers check-in SMS for a specific patient."""
    provider, err = _api_user('provider')
    if err:
        return err
    if not _provider_owns_patient(provider['id'], patient_id):
        return jsonify({'error': 'Patient not found'}), 404

    data         = request.get_json(silent=True) or {}
    voice_prompt = data.get('voice_prompt')

    # phone_number lives in patient_profiles; full_name in profiles
    prof = db.supabase_admin.table('profiles').select(
        'full_name'
    ).eq('id', patient_id).single().execute()
    name  = (prof.data or {}).get('full_name', '')
    pat_prof = db.supabase_admin.table('patient_profiles').select(
        'phone_number'
    ).eq('user_id', patient_id).maybe_single().execute()
    phone = (pat_prof.data or {}).get('phone_number') if pat_prof else None

    if not phone:
        return jsonify({'error': 'Patient has no phone number on file'}), 400

    token = _sms.create_checkin_token(
        patient_id=patient_id,
        provider_id=provider['id'],
        voice_prompt=voice_prompt,
    )
    result = _sms.send_checkin_sms(phone, name, token, voice_prompt=voice_prompt)
    print(f'[sms_route] result={result}', flush=True)

    if not result.get('ok'):
        return jsonify({'error': result.get('error', 'SMS send failed')}), 500

    return jsonify({
        'ok': True,
        'phone_last4': phone[-4:] if len(phone) >= 4 else '****',
        'sid': result.get('sid', ''),
    })

@app.route('/api/provider/patient/<patient_id>/upload-voice-note', methods=['POST'])
def api_provider_upload_voice_note(patient_id):
    """Provider uploads a voice recording on behalf of a patient (e.g. in-session note)."""
    import uuid as _uuid, threading as _threading
    provider, err = _api_user('provider')
    if err:
        return err

    audio_file = request.files.get('audio')
    if not audio_file:
        return jsonify({'error': 'No audio file provided'}), 400

    note_label  = request.form.get('label', '').strip()
    audio_bytes = audio_file.read()
    if not audio_bytes:
        return jsonify({'error': 'Empty audio file'}), 400

    file_ext  = audio_file.filename.rsplit('.', 1)[-1].lower() if (audio_file.filename and '.' in audio_file.filename) else 'webm'
    file_name = f'provider_upload_{patient_id}_{_uuid.uuid4().hex[:8]}.{file_ext}'
    mime_type = audio_file.content_type or 'audio/webm'

    # Insert record immediately so the UI can show "pending" status.
    # Only include columns confirmed to exist in voice_notes (match patient-flow insert).
    vn_row = {
        'patient_id':        patient_id,
        'provider_id':       provider['id'],
        'processing_status': 'pending',
    }
    if note_label:
        vn_row['guiding_question'] = note_label

    try:
        res = db.supabase_admin.table('voice_notes').insert(vn_row).execute()
        voice_note_id = res.data[0]['id'] if res.data else None
    except Exception as e:
        app.logger.error(f'[voice-upload] DB insert failed: {e}')
        return jsonify({'error': 'Failed to create voice note record'}), 500

    if not voice_note_id:
        return jsonify({'error': 'Failed to create voice note record'}), 500

    # Fire-and-forget: transcription runs in background
    _bytes_snap = audio_bytes
    _id_snap    = voice_note_id
    _name_snap  = file_name

    def _transcribe():
        try:
            from audio_engine import transcribe_audio_file
            result = transcribe_audio_file(
                file_bytes=_bytes_snap,
                filename=_name_snap,
                patient_id=patient_id,
                session_id=str(_uuid.uuid4()),
            )
            if result.get('status') == 'completed' and result.get('text'):
                update = {
                    'transcript':        result['text'],
                    'processing_status': 'complete',
                }
                if result.get('storage_path'):
                    update['audio_url'] = result['storage_path']
                db.supabase_admin.table('voice_notes').update(update).eq('id', _id_snap).execute()
            else:
                db.supabase_admin.table('voice_notes').update({
                    'processing_status': 'error',
                    'processing_error':  result.get('error', 'Transcription failed'),
                }).eq('id', _id_snap).execute()
        except Exception as ex:
            app.logger.error(f'[voice-upload] Transcription failed: {ex}')
            try:
                db.supabase_admin.table('voice_notes').update({
                    'processing_status': 'error',
                    'processing_error':  str(ex),
                }).eq('id', _id_snap).execute()
            except Exception:
                pass

    _threading.Thread(target=_transcribe, daemon=True).start()
    return jsonify({'ok': True, 'voice_note_id': voice_note_id})


@app.route('/api/provider/patient/<patient_id>/voice-notes', methods=['GET'])
def api_get_patient_voice_notes(patient_id):
    """Return voice notes + transcripts for a patient (provider view)."""
    provider, err = _api_user('provider')
    if err:
        return err

    notes = db.get_voice_notes_for_patient(patient_id, limit=20)
    return jsonify({'ok': True, 'voice_notes': notes or []})


@app.route('/api/provider/patient/<patient_id>/send-flow-sms', methods=['POST'])
def api_send_flow_sms(patient_id):
    """Provider manually triggers a specific Twilio flow SMS for a patient.
    Body: { "flow_type": "medication" | "short" | "full" | "voice",
            "voice_prompt": "..." (optional, voice/full only),
            "medication_name": "..." (optional, medication only) }
    """
    provider, err = _api_user('provider')
    if err:
        return err
    if not _provider_owns_patient(provider['id'], patient_id):
        return jsonify({'error': 'Patient not found'}), 404

    data      = request.get_json(silent=True) or {}
    flow_type = data.get('flow_type', 'short')
    if flow_type not in ('medication', 'short', 'full', 'voice'):
        return jsonify({'error': 'flow_type must be one of: medication, short, full, voice'}), 400

    # Check flow is configured
    configured = _twilio.get_configured_flows()
    if not configured.get(flow_type):
        return jsonify({'error': f'Flow "{flow_type}" is not configured — set the Twilio env var and redeploy'}), 503

    # Resolve patient phone + name
    prof = db.supabase_admin.table('profiles').select('full_name').eq('id', patient_id).single().execute()
    name = (prof.data or {}).get('full_name', '')
    pat_prof = db.supabase_admin.table('patient_profiles').select('phone_number').eq('user_id', patient_id).maybe_single().execute()
    phone = (pat_prof.data or {}).get('phone_number') if pat_prof else None
    if not phone:
        return jsonify({'error': 'Patient has no phone number on file'}), 400

    # Resolve provider name (for full/voice flows)
    prov_prof = db.supabase_admin.table('profiles').select('full_name').eq('id', provider['id']).maybe_single().execute()
    provider_name = (prov_prof.data or {}).get('full_name', 'your provider') if prov_prof else 'your provider'

    base_url = os.environ.get('APP_URL', '').rstrip('/')

    # Build token + parameters per flow type
    metadata   = {}
    parameters = {'token': '', 'patient_name': name}

    if flow_type == 'medication':
        med_name = data.get('medication_name', '')
        if not med_name:
            p_data = db.get_patient_detail(patient_id, days=1)
            meds   = (p_data or {}).get('current_medications') or []
            med_name = meds[0]['name'].title() if meds else 'your medication'
        metadata = {'medication_name': med_name}
        parameters['medication_name'] = med_name

    elif flow_type == 'full':
        voice_prompt = data.get('voice_prompt',
            'How have you been feeling since your last appointment? '
            'Have you noticed any changes in how your medication is working?')
        voice_token = db.create_sms_token(
            patient_id=patient_id, flow_type='voice',
            metadata={'source': 'manual_full'}, ttl_hours=48,
        )
        metadata = {'provider_name': provider_name}
        parameters.update({
            'provider_name': provider_name,
            'appt_time':     '',
            'voice_prompt':  voice_prompt,
            'voice_link':    f"{base_url}/voice?token={voice_token}" if voice_token else '',
        })

    elif flow_type == 'voice':
        voice_prompt = data.get('voice_prompt', 'How have you been feeling this week?')
        metadata = {'source': 'manual_voice', 'provider_name': provider_name}
        # voice token IS the main token — link points to /voice?token=...
        token = db.create_sms_token(
            patient_id=patient_id, flow_type='voice', metadata=metadata, ttl_hours=48,
        )
        if not token:
            return jsonify({'error': 'Could not create session token'}), 500
        parameters.update({
            'token':         token,
            'provider_name': provider_name,
            'voice_prompt':  voice_prompt,
            'voice_link':    f"{base_url}/voice?token={token}",
        })
        sid = _twilio.trigger_flow(flow_type='voice', to_phone=phone, parameters=parameters)
        if not sid:
            return jsonify({'error': 'Failed to send SMS — check Twilio configuration'}), 500
        return jsonify({'ok': True, 'flow_type': 'voice', 'phone_last4': phone[-4:] if len(phone) >= 4 else '****', 'sid': sid})

    # For medication / short / full: create token now
    token = db.create_sms_token(
        patient_id=patient_id, flow_type=flow_type, metadata=metadata,
        ttl_hours=24,
    )
    if not token:
        return jsonify({'error': 'Could not create session token'}), 500
    parameters['token'] = token

    sid = _twilio.trigger_flow(flow_type=flow_type, to_phone=phone, parameters=parameters)
    if not sid:
        return jsonify({'error': 'Failed to send SMS — check Twilio configuration'}), 500

    return jsonify({
        'ok': True,
        'flow_type': flow_type,
        'phone_last4': phone[-4:] if len(phone) >= 4 else '****',
        'sid': sid,
    })


# ── end SMS / Voice Note routes ───────────────────────────────────────────────


# ═══════════════════════════════════════════════════════════════════════════════
# TWILIO INBOUND WEBHOOKS
# These endpoints receive data POSTed by Twilio Studio at the end of each flow.
# Every request is validated against the X-Twilio-Signature header before any
# data is processed. Invalid signatures → 403 immediately.
#
# Crisis detection runs on ALL free-text inputs before storage.
# ═══════════════════════════════════════════════════════════════════════════════

import twilio_client as _twilio

_INTERNAL_SECRET = os.environ.get('INTERNAL_SECRET', '')


def _validate_twilio_signature():
    """
    Validate X-Twilio-Signature on inbound webhook requests.
    Returns (True, None) if valid, (False, error_response) if invalid.
    Uses the full request URL as seen by Twilio (including https scheme).
    """
    sig = request.headers.get('X-Twilio-Signature', '')
    url = request.url
    params = request.form.to_dict()

    if not _twilio.validate_webhook_signature(url, params, sig):
        app.logger.warning(f"[twilio] Invalid webhook signature from {request.remote_addr}")
        return False, (jsonify({'error': 'Invalid Twilio signature'}), 403)
    return True, None


def _validate_internal_secret():
    """
    Validate the INTERNAL_SECRET header on cron-triggered endpoints.
    Returns (True, None) if valid, (False, error_response) if invalid.
    """
    provided = request.headers.get('X-Internal-Secret', '')
    if not _INTERNAL_SECRET or not hmac.compare_digest(provided, _INTERNAL_SECRET):
        app.logger.warning(f"[internal] Invalid secret from {request.remote_addr}")
        return False, (jsonify({'error': 'Unauthorized'}), 403)
    return True, None


@app.route('/api/twilio/medication-adherence', methods=['POST'])
@limiter.limit('500/hour')
def twilio_medication_adherence():
    """
    Inbound webhook from Twilio Flow 1 (Medication Adherence).

    Expected POST fields (from Twilio Studio HTTP Request widget):
      token           : SMS token identifying the patient
      result          : 'Y' or 'N' (patient's reply)
      medication_name : medication name passed into the flow
      responded_at    : ISO timestamp of the patient's reply (optional)
    """
    valid, err = _validate_twilio_signature()
    if not valid:
        return err

    token = request.form.get('token', '').strip()
    result_raw = request.form.get('result', '').strip().upper()
    medication_name = request.form.get('medication_name', 'medication').strip()
    responded_at = request.form.get('responded_at')

    token_data = db.validate_and_consume_token(token)
    if not token_data:
        app.logger.warning(f"[twilio/med] Invalid or expired token={token!r}")
        return jsonify({'error': 'Invalid token'}), 400

    if token_data['flow_type'] != 'medication':
        app.logger.warning(f"[twilio/med] Wrong flow_type={token_data['flow_type']!r}")
        return jsonify({'error': 'Token flow_type mismatch'}), 400

    patient_id = token_data['patient_id']
    adhered = result_raw == 'Y'

    db.log_medication_adherence_from_sms(
        patient_id=patient_id,
        adhered=adhered,
        medication_name=medication_name,
        responded_at=responded_at,
    )

    app.logger.info(f"[twilio/med] patient={patient_id!r} adhered={adhered} med={medication_name!r}")
    return jsonify({'ok': True})


@app.route('/api/twilio/checkin', methods=['POST'])
@limiter.limit('500/hour')
def twilio_checkin():
    """
    Inbound webhook from Twilio Flow 2 (Short Check-In) or Flow 3 (Full Check-In).

    Expected POST fields:
      token           : SMS token identifying the patient
      check_in_type   : 'short' or 'full'
      mood            : 1-10 integer string
      sleep_hours     : float string (e.g. '7' or '6.5')
      stress          : 1-10 integer string
      energy          : 1-10 integer string (full only)
      follow_up_note  : free text (adaptive follow-up response, if triggered)
      follow_up_type  : 'mood' | 'stress' | 'sleep' | 'energy' (which triggered it)
      medication_note : free text from Q5 branch (full only)
      agenda_note     : free text from Q6 (full only)
    """
    valid, err = _validate_twilio_signature()
    if not valid:
        return err

    token = request.form.get('token', '').strip()
    token_data = db.validate_and_consume_token(token)
    if not token_data:
        app.logger.warning(f"[twilio/checkin] Invalid or expired token={token!r}")
        return jsonify({'error': 'Invalid token'}), 400

    check_in_type = request.form.get('check_in_type', 'short').strip()
    if token_data['flow_type'] not in ('short', 'full'):
        app.logger.warning(f"[twilio/checkin] Wrong flow_type={token_data['flow_type']!r}")
        return jsonify({'error': 'Token flow_type mismatch'}), 400

    patient_id = token_data['patient_id']

    # Collect all fields — missing fields stay None (handled in log_checkin_from_sms)
    def _safe_int(key):
        try:
            v = request.form.get(key, '').strip()
            n = int(v)
            return n if 1 <= n <= 10 else None
        except (ValueError, TypeError):
            return None

    def _safe_float(key):
        try:
            return float(request.form.get(key, '').strip())
        except (ValueError, TypeError):
            return None

    data = {
        'mood':            _safe_int('mood'),
        'sleep_hours':     _safe_float('sleep_hours'),
        'stress':          _safe_int('stress'),
        'energy':          _safe_int('energy'),
        'follow_up_note':  request.form.get('follow_up_note', '').strip() or None,
        'follow_up_type':  request.form.get('follow_up_type', '').strip() or None,
        'medication_note': request.form.get('medication_note', '').strip() or None,
        'agenda_note':     request.form.get('agenda_note', '').strip() or None,
    }

    # Crisis detection on ALL free-text fields before storage
    free_text_fields = ['follow_up_note', 'medication_note', 'agenda_note']
    for field in free_text_fields:
        text = data.get(field)
        if text:
            crisis = claude_api._check_crisis(text)
            if crisis:
                app.logger.critical(
                    f"[twilio/checkin] CRISIS DETECTED patient={patient_id!r} field={field!r}"
                )
                # Notify provider immediately — crisis takes priority over normal flow
                # (Provider notification implemented in claude_api or a dedicated alert fn)
                # Store the check-in anyway so the provider sees it in context
                break

    checkin_id = db.log_checkin_from_sms(
        patient_id=patient_id,
        data=data,
        check_in_type=check_in_type,
    )

    app.logger.info(
        f"[twilio/checkin] stored id={checkin_id!r} type={check_in_type!r} patient={patient_id!r}"
    )
    return jsonify({'ok': True, 'checkin_id': checkin_id})


# ═══════════════════════════════════════════════════════════════════════════════
# INTERNAL TRIGGER ENDPOINTS (called by Render cron jobs)
# These endpoints kick off Twilio Studio flow executions for patients who are
# due for a particular SMS flow. They are NOT callable by patients or providers.
# Protected by INTERNAL_SECRET header (set as Render env var on cron service).
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/api/internal/trigger-medication-sms', methods=['POST'])
def internal_trigger_medication_sms():
    """
    Called every 15 minutes by Render cron.
    Finds patients whose medication dose time falls in the current window
    and fires Twilio Flow 1 for each.
    """
    valid, err = _validate_internal_secret()
    if not valid:
        return err

    from datetime import timezone as _tz
    import pytz

    now_utc = datetime.now(_tz.utc)
    window_start = now_utc
    window_end = now_utc + timedelta(minutes=15)

    patients = db.get_patients_due_medication_sms(
        window_start=window_start.strftime('%H:%M'),
        window_end=window_end.strftime('%H:%M'),
    )

    triggered = 0
    skipped = 0

    for patient in patients:
        # Convert patient's dose time to UTC for accurate comparison
        try:
            tz = pytz.timezone(patient['timezone'])
            dose_local = datetime.strptime(patient['dose_time_local'], '%H:%M').time()
            # Build a full datetime in patient's local tz for today
            local_now = now_utc.astimezone(tz)
            dose_dt_local = tz.localize(
                datetime(local_now.year, local_now.month, local_now.day,
                         dose_local.hour, dose_local.minute)
            )
            dose_dt_utc = dose_dt_local.astimezone(_tz.utc)

            # Skip if dose time not in this 15-min window
            if not (window_start <= dose_dt_utc < window_end):
                skipped += 1
                continue
        except Exception as e:
            app.logger.warning(f"[internal/med] TZ error patient={patient['patient_id']!r}: {e}")
            skipped += 1
            continue

        token = db.create_sms_token(
            patient_id=patient['patient_id'],
            flow_type='medication',
            metadata={'medication_name': patient['medication_name']},
        )
        if not token:
            skipped += 1
            continue

        sid = _twilio.trigger_flow(
            flow_type='medication',
            to_phone=patient['phone'],
            parameters={
                'token':           token,
                'medication_name': patient['medication_name'],
                'patient_name':    '',  # optional — add to patient profile if desired
            },
        )
        if sid:
            triggered += 1
        else:
            skipped += 1

    app.logger.info(f"[internal/med] triggered={triggered} skipped={skipped}")
    return jsonify({'ok': True, 'triggered': triggered, 'skipped': skipped})


@app.route('/api/internal/trigger-checkin-sms', methods=['POST'])
def internal_trigger_checkin_sms():
    """
    Called on check-in schedule by Render cron.
    Body JSON: {"type": "short"} or {"type": "full"}
    Finds patients due for this check-in type and fires the appropriate flow.
    """
    valid, err = _validate_internal_secret()
    if not valid:
        return err

    body = request.get_json(silent=True) or {}
    check_in_type = body.get('type', 'short')

    if check_in_type not in ('short', 'full'):
        return jsonify({'error': 'type must be short or full'}), 400

    base_url = os.environ.get('APP_URL', '').rstrip('/')
    patients = db.get_patients_due_checkin_sms(check_in_type=check_in_type)

    triggered = 0
    skipped = 0

    for patient in patients:
        # Build token metadata
        metadata = {}
        if check_in_type == 'full' and patient.get('appt_id'):
            metadata['appt_id'] = patient['appt_id']
            metadata['provider_name'] = patient.get('provider_name', 'your provider')

        token = db.create_sms_token(
            patient_id=patient['patient_id'],
            flow_type=check_in_type,
            metadata=metadata,
        )
        if not token:
            skipped += 1
            continue

        parameters = {
            'token':          token,
            'check_in_type':  check_in_type,
            'patient_name':   '',
        }

        if check_in_type == 'full':
            # Generate voice recording link with its own token
            voice_token = db.create_sms_token(
                patient_id=patient['patient_id'],
                flow_type='voice',
                metadata={'source': 'full_checkin', 'appt_id': patient.get('appt_id', '')},
                ttl_hours=48,
            )
            parameters['provider_name'] = patient.get('provider_name', 'your provider')
            parameters['appt_time'] = patient.get('appt_time', '')
            parameters['voice_prompt'] = (
                'How have you been feeling since your last appointment? '
                'Have you noticed any changes in how your medication is working?'
            )
            parameters['voice_link'] = f"{base_url}/voice?token={voice_token}" if voice_token else ''

            # Mark appointment so the cron doesn't fire again for this appt
            if patient.get('appt_id'):
                db.mark_appointment_checkin_triggered(patient['appt_id'])

        sid = _twilio.trigger_flow(
            flow_type=check_in_type,
            to_phone=patient['phone'],
            parameters=parameters,
        )
        if sid:
            triggered += 1
        else:
            skipped += 1

    app.logger.info(f"[internal/checkin/{check_in_type}] triggered={triggered} skipped={skipped}")
    return jsonify({'ok': True, 'type': check_in_type, 'triggered': triggered, 'skipped': skipped})


@app.route('/api/internal/trigger-voice-sms', methods=['POST'])
def internal_trigger_voice_sms():
    """
    Called weekly on voice_day_of_week by Render cron.
    Finds patients due for mid-week standalone voice recording and fires Flow 4.
    """
    valid, err = _validate_internal_secret()
    if not valid:
        return err

    base_url = os.environ.get('APP_URL', '').rstrip('/')
    patients = db.get_patients_due_voice_sms()

    triggered = 0
    skipped = 0

    for patient in patients:
        token = db.create_sms_token(
            patient_id=patient['patient_id'],
            flow_type='voice',
            metadata={'source': 'standalone_weekly'},
            ttl_hours=48,
        )
        if not token:
            skipped += 1
            continue

        voice_link = f"{base_url}/voice?token={token}"

        sid = _twilio.trigger_flow(
            flow_type='voice',
            to_phone=patient['phone'],
            parameters={
                'provider_name': patient.get('provider_name', 'your provider'),
                'voice_prompt':  patient.get('voice_prompt', 'How have you been feeling this week?'),
                'voice_link':    voice_link,
            },
        )
        if sid:
            triggered += 1
        else:
            skipped += 1

    app.logger.info(f"[internal/voice] triggered={triggered} skipped={skipped}")
    return jsonify({'ok': True, 'triggered': triggered, 'skipped': skipped})


# ── end Twilio routes ─────────────────────────────────────────────────────────

# ── Provider calendar API ─────────────────────────────────────────────────────

@app.route('/api/provider/patient/<patient_id>/calendar', methods=['GET'])
def api_provider_patient_calendar_list(patient_id):
    user, err = _api_user('provider')
    if err: return err
    events = db.get_provider_calendar_appointments(user['id'], patient_id)
    return jsonify({'events': events})


@app.route('/api/provider/patient/<patient_id>/calendar', methods=['POST'])
def api_provider_patient_calendar_create(patient_id):
    user, err = _api_user('provider')
    if err: return err
    data = request.get_json() or {}
    event_date = (data.get('date') or '').strip()
    if not event_date:
        return jsonify({'error': 'date is required'}), 400
    event = db.create_calendar_appointment(
        provider_id=user['id'],
        patient_id=patient_id,
        event_date=event_date,
        event_time=(data.get('time') or '').strip() or None,
        title=(data.get('title') or 'Appointment').strip(),
        notes=(data.get('notes') or '').strip(),
        event_type=(data.get('event_type') or 'appointment').strip(),
    )
    if not event:
        return jsonify({'error': 'Could not create appointment'}), 500
    return jsonify({'ok': True, 'event': event})


@app.route('/api/provider/patient/<patient_id>/calendar/<event_id>', methods=['PATCH'])
def api_provider_patient_calendar_update(patient_id, event_id):
    user, err = _api_user('provider')
    if err: return err
    data = request.get_json() or {}
    event_date = (data.get('date') or '').strip()
    if not event_date:
        return jsonify({'error': 'date is required'}), 400
    ok = db.update_calendar_appointment(
        appt_id=event_id,
        provider_id=user['id'],
        event_date=event_date,
        event_time=(data.get('time') or '').strip() or None,
        title=(data.get('title') or 'Appointment').strip(),
        notes=(data.get('notes') or '').strip(),
    )
    return jsonify({'ok': ok})


@app.route('/api/provider/patient/<patient_id>/calendar/<event_id>', methods=['DELETE'])
def api_provider_patient_calendar_delete(patient_id, event_id):
    user, err = _api_user('provider')
    if err: return err
    ok = db.delete_calendar_appointment(event_id, user['id'])
    return jsonify({'ok': ok})

# ── Provider cross-patient appointment manager API ────────────────────────────

@app.route('/api/provider/appointments', methods=['GET'])
def api_provider_appointments_all():
    """Return all appointments across all patients for the provider."""
    user, err = _api_user('provider')
    if err: return err
    from_date = request.args.get('from')
    to_date   = request.args.get('to')
    events = db.get_all_provider_appointments(user['id'], from_date, to_date)
    return jsonify(events), 200


@app.route('/api/provider/appointments', methods=['POST'])
def api_provider_appointments_create():
    """Create a scheduled appointment for any patient."""
    user, err = _api_user('provider')
    if err: return err
    data = request.get_json() or {}
    patient_id = (data.get('patient_id') or '').strip()
    event_date = (data.get('date') or '').strip()
    if not patient_id or not event_date:
        return jsonify({'error': 'patient_id and date are required'}), 400
    event = db.create_calendar_appointment(
        provider_id=user['id'],
        patient_id=patient_id,
        event_date=event_date,
        event_time=(data.get('time') or '').strip() or None,
        title=(data.get('title') or 'Appointment').strip(),
        notes=(data.get('notes') or '').strip(),
        event_type='appointment',
    )
    if not event:
        return jsonify({'error': 'Could not create appointment'}), 500
    return jsonify({'ok': True, 'event': event})


@app.route('/api/provider/appointments/<appt_id>', methods=['PATCH'])
def api_provider_appointments_update(appt_id):
    """Update a scheduled appointment."""
    user, err = _api_user('provider')
    if err: return err
    data = request.get_json() or {}
    event_date = (data.get('date') or '').strip()
    if not event_date:
        return jsonify({'error': 'date is required'}), 400
    ok = db.update_calendar_appointment(
        appt_id=appt_id,
        provider_id=user['id'],
        event_date=event_date,
        event_time=(data.get('time') or '').strip() or None,
        title=(data.get('title') or 'Appointment').strip(),
        notes=(data.get('notes') or '').strip(),
    )
    return jsonify({'ok': ok})


@app.route('/api/provider/appointments/<appt_id>', methods=['DELETE'])
def api_provider_appointments_delete(appt_id):
    """Delete a scheduled appointment."""
    user, err = _api_user('provider')
    if err: return err
    ok = db.delete_calendar_appointment(appt_id, user['id'])
    return jsonify({'ok': ok})

# ── end cross-patient appointment manager API ─────────────────────────────────

# ── end calendar API ──────────────────────────────────────────────────────────


if __name__ == '__main__':
    port = int(os.environ.get('FLASK_PORT', 5002))
    debug = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug)
