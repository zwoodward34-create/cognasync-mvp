import sqlite3
import json
import os
from datetime import datetime, timedelta, date

DATABASE_PATH = os.environ.get('DATABASE_PATH', './cognasync.db')


def get_db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS patient_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            date_of_birth DATE,
            current_medications TEXT,
            provider_id INTEGER,
            emergency_contact TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (provider_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS checkins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            date DATE NOT NULL,
            time_of_day TEXT,
            mood_score INTEGER,
            medications TEXT,
            sleep_hours REAL,
            stress_score INTEGER,
            symptoms TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS journal_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            entry_type TEXT,
            raw_entry TEXT NOT NULL,
            ai_analysis TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            generated_by TEXT,
            summary_text TEXT NOT NULL,
            date_range_start DATE,
            date_range_end DATE,
            raw_claude_response TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS medication_reference (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            common_doses TEXT,
            typical_onset TEXT,
            common_side_effects TEXT,
            interaction_warnings TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    _seed_medication_reference(conn)
    conn.commit()
    conn.close()


def _seed_medication_reference(conn):
    meds = [
        ("sertraline", '["25mg","50mg","100mg","150mg","200mg"]', "2-4 weeks",
         "nausea, insomnia, headache, dizziness", "MAOIs: serotonin syndrome risk"),
        ("fluoxetine", '["10mg","20mg","40mg","60mg","80mg"]', "4-6 weeks",
         "nausea, headache, insomnia, sexual dysfunction", "MAOIs: serotonin syndrome risk"),
        ("escitalopram", '["5mg","10mg","20mg"]', "2-4 weeks",
         "nausea, insomnia, fatigue, dry mouth", "MAOIs: serotonin syndrome risk"),
        ("bupropion", '["75mg","100mg","150mg","200mg","300mg"]', "3-4 weeks",
         "dry mouth, insomnia, headache, nausea", "MAOIs; lowers seizure threshold"),
        ("alprazolam", '["0.25mg","0.5mg","1mg","2mg"]', "30-60 minutes (acute)",
         "drowsiness, dizziness, impaired coordination", "CNS depressants, alcohol"),
        ("lorazepam", '["0.5mg","1mg","2mg"]', "15-30 minutes (acute)",
         "drowsiness, dizziness, weakness", "CNS depressants, alcohol"),
        ("quetiapine", '["25mg","50mg","100mg","200mg","300mg","400mg"]', "1-2 weeks",
         "drowsiness, weight gain, dry mouth", "CNS depressants"),
        ("lithium", '["150mg","300mg","450mg","600mg"]', "1-3 weeks",
         "tremor, thirst, frequent urination, nausea", "NSAIDs, diuretics"),
        ("lamotrigine", '["25mg","50mg","100mg","150mg","200mg"]', "2-3 weeks",
         "headache, dizziness, rash", "Valproate increases levels; watch for SJS rash"),
        ("venlafaxine", '["37.5mg","75mg","150mg","225mg"]', "2-4 weeks",
         "nausea, headache, dizziness, insomnia", "MAOIs: serotonin syndrome risk"),
    ]
    conn.executemany('''
        INSERT OR IGNORE INTO medication_reference
        (name, common_doses, typical_onset, common_side_effects, interaction_warnings)
        VALUES (?, ?, ?, ?, ?)
    ''', meds)


# ── Users ─────────────────────────────────────────────────────────────────────

def create_user(email, password_hash, full_name, role):
    conn = get_db()
    try:
        conn.execute(
            'INSERT INTO users (email, password_hash, full_name, role) VALUES (?, ?, ?, ?)',
            (email, password_hash, full_name, role)
        )
        user_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        if role == 'patient':
            conn.execute('INSERT INTO patient_profiles (user_id) VALUES (?)', (user_id,))
        conn.commit()
        return user_id
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def get_user_by_email(email):
    conn = get_db()
    row = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id):
    conn = get_db()
    row = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_user_password(user_id, new_hash):
    conn = get_db()
    conn.execute('UPDATE users SET password_hash = ? WHERE id = ?', (new_hash, user_id))
    conn.commit()
    conn.close()


# ── Sessions ──────────────────────────────────────────────────────────────────

def create_session(user_id, token):
    expires = (datetime.utcnow() + timedelta(days=7)).isoformat()
    conn = get_db()
    conn.execute(
        'INSERT INTO sessions (user_id, token, expires_at) VALUES (?, ?, ?)',
        (user_id, token, expires)
    )
    conn.commit()
    conn.close()


def get_user_from_token(token):
    conn = get_db()
    row = conn.execute('''
        SELECT u.* FROM users u
        JOIN sessions s ON u.id = s.user_id
        WHERE s.token = ? AND s.expires_at > ?
    ''', (token, datetime.utcnow().isoformat())).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_session(token):
    conn = get_db()
    conn.execute('DELETE FROM sessions WHERE token = ?', (token,))
    conn.commit()
    conn.close()


# ── Patient Profile ───────────────────────────────────────────────────────────

def get_patient_profile(user_id):
    conn = get_db()
    row = conn.execute('SELECT * FROM patient_profiles WHERE user_id = ?', (user_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get('current_medications'):
        try:
            d['current_medications'] = json.loads(d['current_medications'])
        except Exception:
            pass
    return d


def update_patient_profile(user_id, **kwargs):
    conn = get_db()
    for key, value in kwargs.items():
        if key == 'current_medications' and isinstance(value, list):
            value = json.dumps(value)
        conn.execute(
            f'UPDATE patient_profiles SET {key} = ? WHERE user_id = ?',
            (value, user_id)
        )
    conn.commit()
    conn.close()


def assign_patient_to_provider(patient_user_id, provider_id):
    conn = get_db()
    conn.execute(
        'UPDATE patient_profiles SET provider_id = ? WHERE user_id = ?',
        (provider_id, patient_user_id)
    )
    conn.commit()
    conn.close()


# ── Check-ins ─────────────────────────────────────────────────────────────────

def create_checkin(patient_id, date_str, time_of_day, mood_score, medications,
                   sleep_hours, stress_score, symptoms, notes):
    meds_json = json.dumps(medications) if isinstance(medications, list) else medications
    conn = get_db()
    conn.execute('''
        INSERT INTO checkins
        (patient_id, date, time_of_day, mood_score, medications, sleep_hours, stress_score, symptoms, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (patient_id, date_str, time_of_day, mood_score, meds_json,
          sleep_hours, stress_score, symptoms, notes))
    checkin_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.commit()
    conn.close()
    return checkin_id


def get_checkins(patient_id, days=30):
    since = (date.today() - timedelta(days=days)).isoformat()
    conn = get_db()
    rows = conn.execute('''
        SELECT * FROM checkins WHERE patient_id = ? AND date >= ?
        ORDER BY date DESC, created_at DESC
    ''', (patient_id, since)).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        if d.get('medications'):
            try:
                d['medications'] = json.loads(d['medications'])
            except Exception:
                pass
        result.append(d)
    return result


def get_checkin_streak(patient_id):
    conn = get_db()
    rows = conn.execute('''
        SELECT DISTINCT date FROM checkins WHERE patient_id = ?
        ORDER BY date DESC
    ''', (patient_id,)).fetchall()
    conn.close()

    date_strings = {row[0] for row in rows}
    if not date_strings:
        return 0

    streak = 0
    current = date.today()
    # Allow streak to count from yesterday if no entry today
    if current.isoformat() not in date_strings:
        current -= timedelta(days=1)
    while current.isoformat() in date_strings:
        streak += 1
        current -= timedelta(days=1)
    return streak


# ── Journals ──────────────────────────────────────────────────────────────────

def create_journal(patient_id, entry_type, raw_entry, ai_analysis=None):
    conn = get_db()
    conn.execute('''
        INSERT INTO journal_entries (patient_id, entry_type, raw_entry, ai_analysis)
        VALUES (?, ?, ?, ?)
    ''', (patient_id, entry_type, raw_entry, ai_analysis))
    journal_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.commit()
    conn.close()
    return journal_id


def get_journals(patient_id, limit=20):
    conn = get_db()
    rows = conn.execute('''
        SELECT * FROM journal_entries WHERE patient_id = ?
        ORDER BY created_at DESC LIMIT ?
    ''', (patient_id, limit)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


# ── Summaries ─────────────────────────────────────────────────────────────────

def create_summary(patient_id, summary_text, date_range_start, date_range_end,
                   raw_response=None, generated_by='system'):
    conn = get_db()
    conn.execute('''
        INSERT INTO summaries
        (patient_id, generated_by, summary_text, date_range_start, date_range_end, raw_claude_response)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (patient_id, generated_by, summary_text, date_range_start, date_range_end, raw_response))
    summary_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.commit()
    conn.close()
    return summary_id


def get_summaries(patient_id):
    conn = get_db()
    rows = conn.execute('''
        SELECT * FROM summaries WHERE patient_id = ?
        ORDER BY created_at DESC
    ''', (patient_id,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_latest_summary(patient_id):
    conn = get_db()
    row = conn.execute('''
        SELECT * FROM summaries WHERE patient_id = ?
        ORDER BY created_at DESC LIMIT 1
    ''', (patient_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ── Medication Reference ──────────────────────────────────────────────────────

def get_medication_names():
    conn = get_db()
    rows = conn.execute('SELECT name FROM medication_reference ORDER BY name').fetchall()
    conn.close()
    return [row[0] for row in rows]


def get_medication_info(name):
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM medication_reference WHERE name = ?', (name.lower(),)
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get('common_doses'):
        try:
            d['common_doses'] = json.loads(d['common_doses'])
        except Exception:
            pass
    return d


# ── Provider ──────────────────────────────────────────────────────────────────

def get_provider_patients(provider_id):
    conn = get_db()
    rows = conn.execute('''
        SELECT u.id as patient_id, u.full_name, u.email,
               MAX(ci.date) as last_checkin
        FROM users u
        JOIN patient_profiles pp ON u.id = pp.user_id
        LEFT JOIN checkins ci ON u.id = ci.patient_id
        WHERE pp.provider_id = ?
        GROUP BY u.id
        ORDER BY u.full_name
    ''', (provider_id,)).fetchall()
    conn.close()

    result = []
    for row in rows:
        d = dict(row)
        d['latest_summary'] = get_latest_summary(d['patient_id'])
        result.append(d)
    return result


def get_patient_detail(patient_id, days=30):
    user = get_user_by_id(patient_id)
    if not user:
        return None
    profile = get_patient_profile(patient_id)
    checkins = get_checkins(patient_id, days=days)
    journals = get_journals(patient_id, limit=5)
    latest_summary = get_latest_summary(patient_id)
    return {
        'patient_id': patient_id,
        'full_name': user['full_name'],
        'email': user['email'],
        'current_medications': (profile or {}).get('current_medications', []),
        'emergency_contact': (profile or {}).get('emergency_contact', ''),
        'checkins_last_period': len(checkins),
        'latest_summary': latest_summary,
        'recent_checkins': checkins[:10],
        'journal_entries': journals,
    }


# ── Trends ────────────────────────────────────────────────────────────────────

def get_trends_data(patient_id, days=30):
    since = (date.today() - timedelta(days=days)).isoformat()
    conn = get_db()
    rows = conn.execute('''
        SELECT date, mood_score, sleep_hours, stress_score, medications
        FROM checkins WHERE patient_id = ? AND date >= ?
        ORDER BY date ASC
    ''', (patient_id, since)).fetchall()
    conn.close()

    checkins = [dict(r) for r in rows]

    mood_scores = [r['mood_score'] for r in checkins if r['mood_score'] is not None]
    sleep_vals = [r['sleep_hours'] for r in checkins if r['sleep_hours'] is not None]
    stress_scores = [r['stress_score'] for r in checkins if r['stress_score'] is not None]

    def avg(lst):
        return round(sum(lst) / len(lst), 1) if lst else 0

    def calc_trend(values):
        if len(values) < 4:
            return 'stable'
        mid = len(values) // 2
        first = avg(values[:mid])
        second = avg(values[mid:])
        if second - first > 0.5:
            return 'increasing'
        if first - second > 0.5:
            return 'decreasing'
        return 'stable'

    # Medication adherence
    taken_count = 0
    total_count = 0
    for r in checkins:
        if r.get('medications'):
            try:
                meds = json.loads(r['medications']) if isinstance(r['medications'], str) else r['medications']
                for m in meds:
                    total_count += 1
                    if m.get('taken'):
                        taken_count += 1
            except Exception:
                pass

    adherence = round((taken_count / total_count * 100), 1) if total_count else 0

    return {
        'patient_id': patient_id,
        'period_days': days,
        'mood': {
            'average': avg(mood_scores),
            'min': min(mood_scores) if mood_scores else 0,
            'max': max(mood_scores) if mood_scores else 0,
            'trend': calc_trend(mood_scores),
            'daily_scores': mood_scores,
        },
        'sleep': {
            'average': avg(sleep_vals),
            'min': min(sleep_vals) if sleep_vals else 0,
            'max': max(sleep_vals) if sleep_vals else 0,
            'trend': calc_trend(sleep_vals),
            'daily_hours': sleep_vals,
        },
        'stress': {
            'average': avg(stress_scores),
            'min': min(stress_scores) if stress_scores else 0,
            'max': max(stress_scores) if stress_scores else 0,
            'trend': calc_trend(stress_scores),
            'daily_scores': stress_scores,
        },
        'medication_adherence': adherence,
        'checkin_streak': get_checkin_streak(patient_id),
        'checkins_this_period': len(checkins),
    }
