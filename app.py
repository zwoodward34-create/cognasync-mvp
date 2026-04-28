import os
import json
from datetime import date, timedelta
from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

import database as db
import supabase_auth as auth_module
import claude_api

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-change-in-production')
CORS(app)

db.init_db()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _session_token():
    return session.get('session_token') or request.args.get('session_token')


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
    recent_checkins = db.get_checkins(user['id'], days=1)
    first_name = user['full_name'].split()[0]
    return render_template('patient/home.html',
                           user=user, profile=profile, streak=streak,
                           latest_summary=latest_summary,
                           has_checkin_today=len(recent_checkins) > 0,
                           first_name=first_name)


@app.route('/login')
def login_page():
    if _current_user():
        return redirect(url_for('home'))
    return render_template('auth/login.html')


@app.route('/login', methods=['POST'])
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
    full_name = request.form.get('full_name', '').strip()
    role = request.form.get('role', 'patient')
    result, error = auth_module.register_user(email, password, full_name, role)
    if error:
        flash(error, 'error')
        return render_template('auth/register.html', email=email, full_name=full_name, role=role)
    session['session_token'] = result['session_token']
    session['user_id'] = result['user_id']
    session['role'] = result['role']
    flash('Account created! Welcome to CognaSync.', 'success')
    if result['role'] == 'provider':
        return redirect(url_for('provider_dashboard'))
    return redirect(url_for('home'))


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
    return render_template('patient/checkin_react.html', user=user)


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
    patients = db.get_provider_patients(user['id'])
    return render_template('provider/dashboard.html', user=user, patients=patients,
                           today_str=date.today().isoformat())


@app.route('/provider/patient/<int:patient_id>')
def provider_patient_detail(patient_id):
    user, redir = _require_provider()
    if redir:
        return redir
    days = int(request.args.get('days', 30))
    patient = db.get_patient_detail(patient_id, days=days)
    if not patient:
        flash('Patient not found', 'error')
        return redirect(url_for('provider_dashboard'))

    patients      = db.get_provider_patients(user['id'])
    summaries     = db.get_summaries(patient_id)
    trends        = db.get_trends_data(patient_id, days=days)
    interactions  = db.check_medication_interactions(patient_id)
    journals      = db.get_journals(patient_id, limit=10, shared_only=True)
    timing_stats  = db.get_medication_timing_stats(patient_id, days=days)

    MIN_OBS = 21
    alerts = []
    n = trends.get('checkin_count', 0)
    # Only fire trend alerts when there's enough statistically valid data
    mood_t = trends['mood']
    if (mood_t['trend'] == 'decreasing' and n >= MIN_OBS
            and mood_t.get('p_value', 1) <= 0.05
            and mood_t.get('r_squared', 0) >= 0.25):
        alerts.append({'level': 'urgent', 'title': 'Mood Declining',
            'desc': f"Mood trending downward — average {mood_t['average']}/10 over {days} days "
                    f"(R²={mood_t['r_squared']}, p={mood_t['p_value']})."})
    if 0 < trends.get('medication_adherence', 0) < 80 and n >= MIN_OBS:
        alerts.append({'level': 'warning', 'title': 'Low Medication Adherence',
            'desc': f"Adherence at {trends['medication_adherence']}% — below the 80% threshold."})
    stress_t = trends['stress']
    if (stress_t['trend'] == 'increasing' and stress_t['average'] > 6
            and n >= MIN_OBS
            and stress_t.get('p_value', 1) <= 0.05
            and stress_t.get('r_squared', 0) >= 0.25):
        alerts.append({'level': 'warning', 'title': 'Elevated Stress Trend',
            'desc': f"Stress trending upward — average {stress_t['average']}/10 over {days} days "
                    f"(R²={stress_t['r_squared']}, p={stress_t['p_value']})."})

    for ta in timing_stats.get('timing_alerts', []):
        alerts.append({'level': 'warning', 'title': 'Inconsistent Medication Timing',
            'desc': ta['message']})

    return render_template('provider/patient_detail.html',
                           user=user, patient=patient,
                           patients=patients,
                           summaries=summaries, trends=trends,
                           alerts=alerts, interactions=interactions,
                           journals=journals, timing_stats=timing_stats,
                           selected_days=days)


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
    user = auth_module.get_current_user(token)
    if not user:
        return None, (jsonify({'error': 'Authentication required'}), 401)
    if required_role and user['role'] != required_role:
        return None, (jsonify({'error': f'{required_role.title()} access required'}), 403)
    return user, None


# ── Auth API ──────────────────────────────────────────────────────────────────

@app.route('/api/auth/register', methods=['POST'])
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

    checkin_id = db.create_checkin(
        patient_id=user['id'],
        date_str=data.get('date', date.today().isoformat()),
        time_of_day=data.get('time_of_day', 'self-prompted'),
        mood_score=mood,
        medications=data.get('medications', []),
        sleep_hours=sleep,
        stress_score=stress,
        symptoms=data.get('symptoms', ''),
        notes=data.get('notes', ''),
        extended_data=data.get('extended_data'),
        checkin_type=checkin_type,
    )

    # Generate AI insight for this check-in
    ai_insight = None
    try:
        baseline = db.get_checkin_baseline(user['id'], days=7)
        checkin_snapshot = {
            'mood_score': mood, 'stress_score': stress, 'sleep_hours': sleep,
            'notes': data.get('notes', ''),
            'extended_data': data.get('extended_data'),
        }
        result = claude_api.analyze_checkin(checkin_snapshot, checkin_type, baseline)
        if result.get('status') == 'safe' and result.get('text'):
            ai_insight = result['text']
            db.update_checkin_insights(checkin_id, ai_insight)
    except Exception:
        pass  # AI insight is non-blocking

    return jsonify({
        'checkin_id': checkin_id,
        'patient_id': user['id'],
        'message': 'Check-in recorded successfully',
        'ai_insight': ai_insight,
    }), 201


@app.route('/api/checkins/today', methods=['GET'])
def api_checkins_today():
    """Return which scheduled check-in types have been completed today."""
    user, err = _api_user('patient')
    if err:
        return err
    today = date.today().isoformat()
    checkins = db.get_checkins(user['id'], days=1)
    done = set()
    for c in checkins:
        ct = c.get('checkin_type') or ''
        cd = (c.get('checkin_date') or '')[:10]
        if cd == today and ct in ('morning', 'afternoon', 'evening'):
            done.add(ct)
    return jsonify({'completed': list(done), 'date': today}), 200


@app.route('/api/checkins/baseline', methods=['GET'])
def api_checkin_baseline():
    user, err = _api_user()
    if err:
        return err
    days = int(request.args.get('days', 7))
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
    days = int(request.args.get('days', 30))
    checkins = db.get_checkins(user['id'], days=days)
    return jsonify({'patient_id': user['id'], 'checkins': checkins}), 200


# ── Journal API ───────────────────────────────────────────────────────────────

@app.route('/api/journals', methods=['POST'])
def api_create_journal():
    user, err = _api_user('patient')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    raw_entry = data.get('raw_entry', '').strip()
    if not raw_entry:
        return jsonify({'error': 'raw_entry is required'}), 400

    share_with_provider = int(data.get('share_with_provider', 1))

    try:
        result = claude_api.analyze_journal(raw_entry)
    except RuntimeError as e:
        return jsonify({'error': str(e)}), 503

    ai_text = result['text']
    journal_id = db.create_journal(
        patient_id=user['id'],
        entry_type=data.get('entry_type', 'free_flow'),
        raw_entry=raw_entry,
        ai_analysis=ai_text,
        share_with_provider=share_with_provider,
    )
    response = {
        'journal_id': journal_id,
        'patient_id': user['id'],
        'raw_entry': raw_entry,
        'ai_analysis': ai_text,
        'created_at': date.today().isoformat(),
    }
    if result['status'] == 'crisis':
        response['alert'] = 'crisis'
    return jsonify(response), 201


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
        result = claude_api.generate_appointment_summary(checkins, journals, days=days)
    except RuntimeError as e:
        return jsonify({'error': str(e)}), 503

    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    summary_id = db.create_summary(
        patient_id=user['id'],
        summary_text=result['text'],
        date_range_start=start_date.isoformat(),
        date_range_end=end_date.isoformat(),
        raw_response=result.get('raw'),
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


# ── Trends API ────────────────────────────────────────────────────────────────

@app.route('/api/trends', methods=['GET'])
def api_get_trends():
    user, err = _api_user()
    if err:
        return err
    days = int(request.args.get('days', 30))
    patient_id = user['id']
    if user['role'] == 'provider':
        patient_id = int(request.args.get('patient_id', 0))
        if not patient_id:
            return jsonify({'error': 'patient_id required for provider'}), 400
    trends = db.get_trends_data(patient_id, days=days)
    profile = db.get_patient_profile(patient_id)
    trends['current_medications'] = profile.get('current_medications', []) if profile else []
    return jsonify(trends), 200


# ── Provider API ──────────────────────────────────────────────────────────────

@app.route('/api/provider/patients', methods=['GET'])
def api_provider_patients():
    user, err = _api_user('provider')
    if err:
        return err
    patients = db.get_provider_patients(user['id'])
    return jsonify({'provider_id': user['id'], 'patients': patients}), 200


@app.route('/api/provider/patient/<int:patient_id>', methods=['GET'])
def api_provider_patient(patient_id):
    user, err = _api_user('provider')
    if err:
        return err
    days = int(request.args.get('days', 30))
    detail = db.get_patient_detail(patient_id, days=days)
    if not detail:
        return jsonify({'error': 'Patient not found'}), 404
    return jsonify(detail), 200


@app.route('/api/provider/generate-summary/<int:patient_id>', methods=['POST'])
def api_provider_generate_summary(patient_id):
    user, err = _api_user('provider')
    if err:
        return err
    data = request.json or {}
    days = int(data.get('days', 14))

    checkins = db.get_checkins(patient_id, days=days)
    journals = db.get_journals(patient_id, limit=20, shared_only=True)

    if not checkins and not journals:
        return jsonify({'error': 'No data found for this patient'}), 400

    try:
        result = claude_api.generate_appointment_summary(checkins, journals, days=days)
    except RuntimeError as e:
        return jsonify({'error': str(e)}), 503

    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    summary_id = db.create_summary(
        patient_id=patient_id,
        summary_text=result['text'],
        date_range_start=start_date.isoformat(),
        date_range_end=end_date.isoformat(),
        raw_response=result.get('raw'),
        generated_by='provider',
    )
    return jsonify({
        'summary_id': summary_id,
        'patient_id': patient_id,
        'summary_text': result['text'],
        'date_range_start': start_date.isoformat(),
        'date_range_end': end_date.isoformat(),
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


@app.route('/api/medications/search', methods=['GET'])
def api_medication_search():
    names = db.get_medication_names()
    q = request.args.get('q', '').lower()
    if q:
        names = [n for n in names if q in n.lower()]
    return jsonify({'medications': names}), 200


@app.route('/api/medications/info/<name>', methods=['GET'])
def api_medication_info(name):
    info = db.get_medication_info(name)
    if not info:
        return jsonify({'error': 'Medication not found'}), 404
    return jsonify(info), 200


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
    pattern = db.find_unexpected_pattern(user['id'], days)
    return jsonify({'pattern': pattern}), 200


if __name__ == '__main__':
    port = int(os.environ.get('FLASK_PORT', 5002))
    debug = os.environ.get('FLASK_ENV', 'development') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug)
