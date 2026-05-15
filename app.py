import os
import json
import re
import hmac
from datetime import date, timedelta
from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash
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
    """Return True if patient_id is in the provider's assigned patient list."""
    assigned = db.get_provider_patients(provider_id)
    return str(patient_id) in [str(p['patient_id']) for p in assigned]


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
    return render_template('patient/home.html',
                           user=user, profile=profile, streak=streak,
                           latest_summary=latest_summary,
                           first_name=first_name)


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
    return render_template('auth/register.html')


@app.route('/register', methods=['POST'])
def register_post():
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')
    confirm_password = request.form.get('confirm_password', '')
    full_name = request.form.get('full_name', '').strip()
    role = request.form.get('role', 'patient')
    if password != confirm_password:
        flash('Passwords do not match.', 'error')
        return render_template('auth/register.html', email=email, full_name=full_name, role=role)
    result, error = auth_module.register_user(email, password, full_name, role)
    if error:
        flash(error, 'error')
        return render_template('auth/register.html', email=email, full_name=full_name, role=role)
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

    user_id, full_name = auth_module.initiate_password_reset(email)
    if user_id:
        token = auth_module.generate_reset_token(user_id, app.secret_key)
        try:
            email_utils.send_password_reset_email(email, full_name or 'there', token)
        except Exception as e:
            app.logger.error(f"Failed to send reset email to {email}: {e}")

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
    profile_res = db.supabase_admin.table('profiles').select('id, email, full_name, status').eq('id', user_id).execute()
    if not profile_res.data:
        return 'User not found.', 404
    profile = profile_res.data[0]
    if profile['status'] == 'approved':
        return render_template('auth/approval_done.html', already=True, email=profile['email'])
    db.supabase_admin.table('profiles').update({'status': 'approved'}).eq('id', user_id).execute()
    email_utils.send_account_approved_email(profile['email'], profile['full_name'])
    return render_template('auth/approval_done.html', already=False, email=profile['email'])


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


@app.route('/provider')
def provider_dashboard():
    user, redir = _require_provider()
    if redir:
        return redir
    patients = db.get_provider_patients_with_stats(user['id'])
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
        patients     = db.get_provider_patients(user['id'])
        trends       = db.get_trends_data(patient_id, days=30) or {}
        appointments = db.get_patient_appointments(user['id'], patient_id)
        interactions = db.check_medication_interactions(patient_id)

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
                               last_checkin_date=last_checkin_date)
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

    days    = appt.get('period_days', 30)
    patient = db.get_patient_detail(patient_id, days=days)
    if not patient:
        flash('Patient not found', 'error')
        return redirect(url_for('provider_dashboard'))

    patients     = db.get_provider_patients(user['id'])
    trends       = db.get_trends_data(patient_id, days=days) or {}
    summaries    = db.get_summaries(patient_id)
    timing_stats = db.get_medication_timing_stats(patient_id, days=days)
    interactions = db.check_medication_interactions(patient_id)
    alerts       = _build_alerts(trends, days)

    # Journals scoped to the appointment's review window
    try:
        appt_start_str = (appt.get('started_at') or date.today().isoformat())[:10]
        appt_start_dt  = date.fromisoformat(appt_start_str)
    except Exception:
        appt_start_dt  = date.today()
    window_start = (appt_start_dt - timedelta(days=days)).isoformat()
    window_end   = appt_start_dt.isoformat()
    journals     = db.get_journals_in_range(patient_id, window_start, window_end,
                                            shared_only=True)

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
                           ai_questions=ai_questions)


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

    return jsonify({
        'checkin_id': checkin_id,
        'patient_id': user['id'],
        'message': 'Check-in recorded successfully',
        'ai_insight': ai_insight,
    }), 201


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
            'journal_id': journal_id,
            'patient_id': user['id'],
            'raw_entry': raw_entry,
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
        'journal_id': journal_id,
        'patient_id': user['id'],
        'raw_entry': raw_entry,
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

    try:
        result = claude_api.generate_appointment_summary(
            checkins, journals, days=days, audience='patient')
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


@app.route('/api/provider/patient/<patient_id>/trends', methods=['GET'])
def api_provider_patient_trends(patient_id):
    user, err = _api_user('provider')
    if err:
        return err
    if not _provider_owns_patient(user['id'], patient_id):
        return jsonify({'error': 'Patient not found'}), 404
    days = min(int(request.args.get('days', 30)), 365)
    trends = db.get_trends_data(patient_id, days=days)
    if not trends:
        return jsonify({'error': 'Unable to fetch trends'}), 500
    try:
        meds = db.get_user_medications(patient_id, active_only=True)
        trends['current_medications'] = [{'id': m.get('id'), 'name': m.get('name')} for m in meds] if meds else []
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
    return jsonify(detail), 200


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

    if period_start and period_end:
        if not (re.match(r'^\d{4}-\d{2}-\d{2}$', str(period_start)) and
                re.match(r'^\d{4}-\d{2}-\d{2}$', str(period_end))):
            return jsonify({'error': 'period_start and period_end must be YYYY-MM-DD'}), 400
        checkins = db.get_checkins_in_range(patient_id, period_start, period_end)
        journals = db.get_journals_in_range(patient_id, period_start, period_end)
        days = None
    else:
        days = min(int(data.get('days', 14)), 365)
        end_dt    = date.today()
        start_dt  = end_dt - timedelta(days=days)
        period_start = start_dt.isoformat()
        period_end   = end_dt.isoformat()
        checkins = db.get_checkins_in_range(patient_id, period_start, period_end)
        journals = db.get_journals_in_range(patient_id, period_start, period_end)

    if not checkins and not journals:
        return jsonify({'error': 'No data found for this patient in the selected period'}), 400

    try:
        result = claude_api.generate_appointment_summary(
            checkins, journals,
            days=days or (date.fromisoformat(period_end) - date.fromisoformat(period_start)).days,
            period_start=period_start,
            period_end=period_end,
            appointment_date=appointment_date,
            audience='provider',
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
    }), 201


# ── Settings API ──────────────────────────────────────────────────────────────

@app.route('/api/settings/profile', methods=['POST'])
def api_update_profile():
    user, err = _api_user('patient')
    if err:
        return err
    data = request.json or {}

    updates = {}
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

    result = db.compute_correlation_evidence(pairs, user_dir)
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


if __name__ == '__main__':
    port = int(os.environ.get('FLASK_PORT', 5002))
    debug = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug)
