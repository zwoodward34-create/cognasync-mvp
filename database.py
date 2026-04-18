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
        # SSRIs
        ("sertraline", '["25mg","50mg","100mg","150mg","200mg"]', "2-4 weeks",
         "Nausea, insomnia, headache, dizziness, sexual dysfunction, increased sweating",
         "MAOIs (serotonin syndrome); tramadol; linezolid; blood thinners (increased bleeding risk)"),
        ("fluoxetine", '["10mg","20mg","40mg","60mg","80mg"]', "4-6 weeks",
         "Nausea, headache, insomnia, sexual dysfunction, decreased appetite, anxiety",
         "MAOIs (serotonin syndrome); thioridazine; pimozide; tamoxifen (reduced effectiveness)"),
        ("escitalopram", '["5mg","10mg","20mg"]', "2-4 weeks",
         "Nausea, insomnia, fatigue, dry mouth, sweating, sexual dysfunction",
         "MAOIs (serotonin syndrome); pimozide; cimetidine increases escitalopram levels"),
        ("paroxetine", '["10mg","20mg","30mg","40mg"]', "2-4 weeks",
         "Weight gain, sexual dysfunction, drowsiness, dry mouth, constipation, sweating",
         "MAOIs (serotonin syndrome); tamoxifen (reduces effectiveness); blood thinners"),
        ("citalopram", '["10mg","20mg","40mg"]', "2-4 weeks",
         "Nausea, dry mouth, sweating, drowsiness, insomnia, sexual dysfunction",
         "MAOIs (serotonin syndrome); pimozide; drugs that prolong QT interval"),
        ("fluvoxamine", '["50mg","100mg","150mg","200mg"]', "4-6 weeks",
         "Nausea, drowsiness, insomnia, dry mouth, constipation",
         "MAOIs; tizanidine; thioridazine; alosetron; strong CYP1A2 interactions"),
        # SNRIs
        ("venlafaxine", '["37.5mg","75mg","150mg","225mg"]', "2-4 weeks",
         "Nausea, headache, dizziness, insomnia, increased blood pressure, sexual dysfunction",
         "MAOIs (serotonin syndrome); linezolid; increases bleeding risk with NSAIDs"),
        ("duloxetine", '["20mg","30mg","60mg"]', "2-4 weeks",
         "Nausea, dry mouth, constipation, fatigue, dizziness, increased sweating",
         "MAOIs (serotonin syndrome); thioridazine; heavy alcohol use (liver risk)"),
        ("desvenlafaxine", '["25mg","50mg","100mg"]', "2-4 weeks",
         "Nausea, dizziness, insomnia, constipation, sexual dysfunction",
         "MAOIs (serotonin syndrome); linezolid; NSAIDs increase bleeding risk"),
        ("levomilnacipran", '["20mg","40mg","80mg","120mg"]', "2-4 weeks",
         "Nausea, constipation, increased heart rate, sweating, urinary hesitation",
         "MAOIs (serotonin syndrome); strong CYP3A4 inhibitors increase levels"),
        # Atypical antidepressants
        ("bupropion", '["75mg","100mg","150mg","200mg","300mg","450mg"]', "3-4 weeks",
         "Dry mouth, insomnia, headache, nausea, agitation, tremor",
         "MAOIs; lowers seizure threshold — avoid in eating disorders or seizure history; alcohol withdrawal"),
        ("mirtazapine", '["7.5mg","15mg","30mg","45mg"]', "1-3 weeks",
         "Drowsiness, increased appetite, weight gain, dry mouth, dizziness",
         "MAOIs (serotonin syndrome); CNS depressants increase sedation; alcohol"),
        ("trazodone", '["50mg","100mg","150mg","200mg","300mg"]', "1-2 weeks (sleep); 2-4 weeks (mood)",
         "Drowsiness, dizziness, dry mouth, blurred vision, priapism (rare)",
         "MAOIs; CNS depressants; increases digoxin and phenytoin levels"),
        ("vilazodone", '["10mg","20mg","40mg"]', "2-4 weeks",
         "Diarrhea, nausea, vomiting, insomnia, dizziness",
         "MAOIs (serotonin syndrome); strong CYP3A4 inhibitors/inducers"),
        ("vortioxetine", '["5mg","10mg","15mg","20mg"]', "2-4 weeks",
         "Nausea, vomiting, constipation, dizziness, sexual dysfunction",
         "MAOIs (serotonin syndrome); linezolid; strong CYP2D6 inhibitors"),
        # TCAs
        ("amitriptyline", '["10mg","25mg","50mg","75mg","100mg","150mg"]', "2-4 weeks",
         "Dry mouth, constipation, blurred vision, urinary retention, drowsiness, weight gain",
         "MAOIs (hypertensive crisis); CNS depressants; anticholinergics; can prolong QT interval"),
        ("nortriptyline", '["10mg","25mg","50mg","75mg"]', "2-4 weeks",
         "Dry mouth, constipation, drowsiness, blurred vision, weight gain",
         "MAOIs (hypertensive crisis); CNS depressants; quinidine increases nortriptyline levels"),
        ("imipramine", '["10mg","25mg","50mg","75mg"]', "2-4 weeks",
         "Dry mouth, constipation, blurred vision, urinary retention, drowsiness",
         "MAOIs (hypertensive crisis); CNS depressants; cimetidine increases levels"),
        ("clomipramine", '["25mg","50mg","75mg","100mg","150mg"]', "4-10 weeks",
         "Dry mouth, constipation, drowsiness, tremor, sexual dysfunction, weight gain",
         "MAOIs; CNS depressants; cimetidine; can lower seizure threshold"),
        # Benzodiazepines
        ("alprazolam", '["0.25mg","0.5mg","1mg","2mg"]', "30-60 minutes (acute)",
         "Drowsiness, dizziness, impaired coordination, memory problems, dependence risk",
         "CNS depressants (additive sedation); alcohol (dangerous); opioids (fatal respiratory depression); antifungals increase levels"),
        ("lorazepam", '["0.5mg","1mg","2mg"]', "15-30 minutes (acute)",
         "Drowsiness, dizziness, weakness, unsteadiness, dependence risk",
         "CNS depressants (additive sedation); alcohol (dangerous); opioids (fatal respiratory depression)"),
        ("clonazepam", '["0.5mg","1mg","2mg"]', "20-60 minutes (acute)",
         "Drowsiness, dizziness, coordination problems, memory issues, dependence risk",
         "CNS depressants; alcohol; opioids (fatal respiratory depression); valproate increases clonazepam levels"),
        ("diazepam", '["2mg","5mg","10mg"]', "30-60 minutes (acute)",
         "Drowsiness, dizziness, fatigue, muscle weakness, dependence risk",
         "CNS depressants; alcohol; opioids (fatal respiratory depression); cimetidine increases levels"),
        ("oxazepam", '["10mg","15mg","30mg"]', "45-90 minutes (acute)",
         "Drowsiness, dizziness, headache, dependence risk",
         "CNS depressants; alcohol; opioids (dangerous combination)"),
        # Antipsychotics
        ("quetiapine", '["25mg","50mg","100mg","200mg","300mg","400mg"]', "1-2 weeks",
         "Drowsiness, weight gain, dry mouth, dizziness, metabolic changes, increased blood sugar",
         "CNS depressants; drugs that prolong QT interval; strong CYP3A4 inhibitors increase levels"),
        ("aripiprazole", '["2mg","5mg","10mg","15mg","20mg","30mg"]', "1-2 weeks",
         "Restlessness (akathisia), insomnia, nausea, headache, weight gain",
         "Strong CYP2D6 or CYP3A4 inhibitors; drugs that prolong QT interval"),
        ("risperidone", '["0.5mg","1mg","2mg","3mg","4mg"]', "1-2 weeks",
         "Weight gain, drowsiness, restlessness (akathisia), metabolic changes, sexual dysfunction",
         "CNS depressants; drugs that prolong QT interval; strong CYP2D6 inhibitors"),
        ("olanzapine", '["2.5mg","5mg","7.5mg","10mg","15mg","20mg"]', "1-2 weeks",
         "Weight gain, drowsiness, increased appetite, metabolic changes, dry mouth",
         "CNS depressants; fluvoxamine increases olanzapine levels; carbamazepine reduces levels"),
        ("ziprasidone", '["20mg","40mg","60mg","80mg"]', "1-2 weeks",
         "Drowsiness, dizziness, restlessness, nausea",
         "QT-prolonging drugs (serious risk); carbamazepine reduces levels"),
        ("lurasidone", '["20mg","40mg","60mg","80mg","120mg"]', "1-2 weeks",
         "Drowsiness, restlessness (akathisia), nausea, weight gain",
         "Strong CYP3A4 inhibitors/inducers; must be taken with food (≥350 calories)"),
        ("haloperidol", '["0.5mg","1mg","2mg","5mg","10mg"]', "1-2 weeks",
         "Extrapyramidal symptoms (muscle stiffness, restlessness), drowsiness, dry mouth",
         "CNS depressants; QT-prolonging drugs; lithium; carbamazepine reduces levels"),
        ("clozapine", '["12.5mg","25mg","50mg","100mg","200mg"]', "2-4 weeks",
         "Drowsiness, weight gain, drooling, constipation, increased heart rate — requires regular blood monitoring",
         "CNS depressants; drugs that suppress bone marrow; fluvoxamine greatly increases clozapine levels"),
        # Mood stabilizers
        ("lithium", '["150mg","300mg","450mg","600mg"]', "1-3 weeks",
         "Tremor, thirst, frequent urination, nausea, weight gain, cognitive dulling",
         "NSAIDs and diuretics (increase lithium levels to toxic range); ACE inhibitors; theophylline"),
        ("lamotrigine", '["25mg","50mg","100mg","150mg","200mg","300mg","400mg"]', "2-3 weeks",
         "Headache, dizziness, rash (rare but serious: Stevens-Johnson syndrome), blurred vision",
         "Valproate doubles lamotrigine levels; carbamazepine reduces levels; oral contraceptives may reduce levels"),
        ("valproate", '["125mg","250mg","500mg","750mg","1000mg"]', "1-2 weeks",
         "Nausea, tremor, weight gain, hair loss, drowsiness, liver enzyme elevation",
         "Lamotrigine (increases levels); carbamazepine; aspirin increases free valproate; teratogenic risk"),
        ("carbamazepine", '["100mg","200mg","400mg"]', "1-2 weeks",
         "Dizziness, drowsiness, nausea, blurred vision, rash",
         "Many interactions — strong CYP3A4 inducer; reduces levels of many drugs including lamotrigine, valproate, antipsychotics"),
        ("oxcarbazepine", '["150mg","300mg","600mg"]', "1-2 weeks",
         "Dizziness, drowsiness, nausea, headache, hyponatremia (low sodium)",
         "Reduces oral contraceptive effectiveness; can affect levels of other anticonvulsants"),
        # Stimulants (ADHD)
        ("amphetamine salts", '["5mg","10mg","15mg","20mg","25mg","30mg"]', "Within hours",
         "Decreased appetite, insomnia, increased heart rate/blood pressure, dry mouth, irritability",
         "MAOIs (hypertensive crisis); antihypertensives (reduced effect); acidifying agents reduce absorption"),
        ("methylphenidate", '["5mg","10mg","20mg","36mg","54mg"]', "Within hours",
         "Decreased appetite, insomnia, headache, stomach upset, increased heart rate",
         "MAOIs (hypertensive crisis); blood pressure medications; warfarin; some seizure medications"),
        ("lisdexamfetamine", '["20mg","30mg","40mg","50mg","60mg","70mg"]', "Within hours",
         "Decreased appetite, insomnia, dry mouth, increased heart rate/blood pressure, irritability",
         "MAOIs (hypertensive crisis); antihypertensives; acidifying agents reduce effect"),
        ("atomoxetine", '["10mg","18mg","25mg","40mg","60mg","80mg","100mg"]', "2-4 weeks",
         "Decreased appetite, nausea, headache, dry mouth, insomnia, sexual dysfunction in adults",
         "MAOIs; strong CYP2D6 inhibitors (fluoxetine, paroxetine) greatly increase levels"),
        # Sleep
        ("zolpidem", '["5mg","10mg"]', "15-30 minutes",
         "Drowsiness, dizziness, headache, sleepwalking/sleep-eating (rare), next-day impairment",
         "CNS depressants; alcohol; strong CYP3A4 inhibitors; rifampin reduces effectiveness"),
        ("eszopiclone", '["1mg","2mg","3mg"]', "15-30 minutes",
         "Unpleasant taste, dizziness, drowsiness, dry mouth, next-day impairment",
         "CNS depressants; alcohol; strong CYP3A4 inhibitors"),
        ("suvorexant", '["5mg","10mg","15mg","20mg"]', "30 minutes",
         "Drowsiness, headache, dizziness, unusual dreams, sleep paralysis (rare)",
         "CNS depressants; strong CYP3A4 inhibitors significantly increase levels"),
        ("melatonin", '["0.5mg","1mg","3mg","5mg","10mg"]', "30-60 minutes",
         "Drowsiness, headache, dizziness",
         "Blood thinners (increased bleeding risk); immunosuppressants; fluvoxamine increases melatonin levels"),
        # Anti-anxiety
        ("buspirone", '["5mg","7.5mg","10mg","15mg","30mg"]', "2-4 weeks",
         "Dizziness, nausea, headache, nervousness, drowsiness",
         "MAOIs (hypertensive reaction); strong CYP3A4 inhibitors increase levels; grapefruit juice"),
        ("hydroxyzine", '["10mg","25mg","50mg"]', "30-60 minutes",
         "Drowsiness, dry mouth, dizziness, headache",
         "CNS depressants; alcohol; anticholinergics (dry mouth, urinary retention, confusion)"),
        ("pregabalin", '["25mg","50mg","75mg","100mg","150mg","200mg","225mg","300mg"]', "1 week",
         "Dizziness, drowsiness, weight gain, dry mouth, blurred vision, edema",
         "CNS depressants; alcohol; opioids (respiratory depression risk); angiotensin medications"),
        ("gabapentin", '["100mg","300mg","400mg","600mg","800mg"]', "1-2 weeks",
         "Dizziness, drowsiness, coordination problems, weight gain, fatigue",
         "CNS depressants; opioids (respiratory depression); antacids reduce gabapentin absorption"),
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


def check_medication_interactions(user_id):
    """
    Return a list of plain-language interaction alerts for the patient's
    current medication list, derived from the medication_reference table.
    """
    profile = get_patient_profile(user_id)
    if not profile:
        return []
    meds = profile.get('current_medications', [])
    if not isinstance(meds, list):
        return []

    med_names = [m.get('name', '').lower() for m in meds if m.get('name')]
    if len(med_names) < 2:
        return []

    conn = get_db()
    alerts = []
    seen = set()

    for name in med_names:
        row = conn.execute(
            'SELECT name, common_side_effects, interaction_warnings FROM medication_reference WHERE name = ?',
            (name,)
        ).fetchone()
        if not row:
            continue
        warnings = (row['interaction_warnings'] or '').lower()
        for other in med_names:
            if other == name:
                continue
            pair = tuple(sorted([name, other]))
            if pair in seen:
                continue
            # Check if the other drug name appears in this drug's interaction warnings
            if other in warnings:
                seen.add(pair)
                alerts.append({
                    'drug_a': name.title(),
                    'drug_b': other.title(),
                    'warning': row['interaction_warnings'],
                    'severity': 'caution',
                })
            # Also flag the classic dangerous combos by keyword
            dangerous_pairs = [
                (['alprazolam','lorazepam','clonazepam','diazepam','oxazepam'], ['opioid']),
                (['alprazolam','lorazepam','clonazepam','diazepam','oxazepam'],
                 ['alprazolam','lorazepam','clonazepam','diazepam','oxazepam']),
            ]

    # Catch general class interactions not caught by name matching
    benzo_names = {'alprazolam','lorazepam','clonazepam','diazepam','oxazepam'}
    ssri_snri = {'sertraline','fluoxetine','escitalopram','paroxetine','citalopram',
                 'fluvoxamine','venlafaxine','duloxetine','desvenlafaxine'}
    maoi_risk = ssri_snri | {'bupropion','mirtazapine','tramadol','trazodone','vortioxetine'}

    taking_benzos = [n for n in med_names if n in benzo_names]
    taking_ssri_snri = [n for n in med_names if n in ssri_snri]

    # Multiple benzodiazepines
    if len(taking_benzos) > 1:
        pair = tuple(sorted(taking_benzos[:2]))
        if pair not in seen:
            seen.add(pair)
            alerts.append({
                'drug_a': taking_benzos[0].title(),
                'drug_b': taking_benzos[1].title(),
                'warning': 'Multiple benzodiazepines together significantly increase CNS depression, respiratory depression, and overdose risk.',
                'severity': 'serious',
            })

    # Multiple SSRIs/SNRIs
    if len(taking_ssri_snri) > 1:
        pair = tuple(sorted(taking_ssri_snri[:2]))
        if pair not in seen:
            seen.add(pair)
            alerts.append({
                'drug_a': taking_ssri_snri[0].title(),
                'drug_b': taking_ssri_snri[1].title(),
                'warning': 'Combining two serotonergic antidepressants increases serotonin syndrome risk. Discuss with your provider.',
                'severity': 'serious',
            })

    conn.close()
    return alerts


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
