import os
import json
from datetime import datetime, timedelta, date
from supabase import create_client, Client
import uuid

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')

# Use service key for admin operations (bypasses RLS)
supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
# Use regular key for user operations (respects RLS)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


VALID_HYPOTHESIS_VARS = {'mood', 'stress', 'sleep', 'energy', 'focus'}


def init_db():
    """Initialize database schema in Supabase. Runs once on startup."""
    # Supabase schema is created manually via SQL Editor
    # This function now just verifies connection
    try:
        result = supabase_admin.table('profiles').select('id').limit(1).execute()
        print("✓ Database connection verified")
    except Exception as e:
        print(f"✗ Database connection failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# USER MANAGEMENT (NOTE: Auth is now handled by Supabase Auth, not here)
# These functions are kept for compatibility but mostly deprecated
# ═══════════════════════════════════════════════════════════════════════════

def create_user(email, password_hash, full_name, role):
    """DEPRECATED: Use supabase_auth.register_user instead."""
    return None


def get_user_by_email(email):
    """Get user by email. Now uses profiles table."""
    try:
        response = supabase_admin.table('profiles').select('*').eq('email', email.lower().strip()).execute()
        if response.data and len(response.data) > 0:
            user = response.data[0]
            return {
                'id': user['id'],
                'email': user['email'],
                'full_name': user['full_name'],
                'role': user['role']
            }
        return None
    except Exception as e:
        print(f"Error getting user by email: {e}")
        return None


def get_user_by_id(user_id):
    """Get user by ID."""
    try:
        response = supabase_admin.table('profiles').select('*').eq('id', str(user_id)).execute()
        if response.data and len(response.data) > 0:
            user = response.data[0]
            return {
                'id': user['id'],
                'email': user['email'],
                'full_name': user['full_name'],
                'role': user['role']
            }
        return None
    except Exception as e:
        print(f"Error getting user by id: {e}")
        return None


def update_user_password(user_id, new_hash):
    """DEPRECATED: Use Supabase Auth's password reset instead."""
    return True


def create_session(user_id, token):
    """DEPRECATED: Supabase Auth handles sessions via JWT."""
    return None


def get_user_from_token(token):
    """DEPRECATED: Use supabase_auth.verify_jwt instead."""
    return None


def delete_session(token):
    """DEPRECATED: JWT sessions are stateless."""
    return True


# ═══════════════════════════════════════════════════════════════════════════
# PATIENT PROFILES
# ═══════════════════════════════════════════════════════════════════════════

def get_patient_profile(user_id):
    """Get patient profile."""
    try:
        response = supabase_admin.table('patient_profiles').select('*').eq('user_id', str(user_id)).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error getting patient profile: {e}")
        return None


def update_patient_profile(user_id, **kwargs):
    """Upsert patient profile (creates row if none exists yet)."""
    try:
        data = {**kwargs, 'user_id': str(user_id)}
        supabase_admin.table('patient_profiles').upsert(data, on_conflict='user_id').execute()
        return True
    except Exception as e:
        print(f"Error updating patient profile: {e}")
        return False


def assign_patient_to_provider(patient_user_id, provider_id):
    """Assign patient to provider. Pass provider_id=None to unlink."""
    try:
        value = str(provider_id) if provider_id is not None else None
        supabase_admin.table('patient_profiles').update({'provider_id': value}).eq('user_id', str(patient_user_id)).execute()
        return True
    except Exception as e:
        print(f"Error assigning patient to provider: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# CHECK-INS
# ═══════════════════════════════════════════════════════════════════════════

def create_checkin(patient_id, date_str, time_of_day, mood_score, medications, sleep_hours, stress_score, symptoms, notes, checkin_type='on_demand', extended_data=None, ai_insights=None):
    """Create a new check-in, persisting all fields."""
    try:
        # Normalise extended_data — accept either a dict or a JSON string
        ext = extended_data or {}
        if isinstance(ext, str):
            try:
                ext = json.loads(ext)
            except Exception:
                ext = {}

        # Derive stability_score from the computed scores the React app sends,
        # falling back to mood_score so old callers still work.
        scores = ext.get('scores', {}) if isinstance(ext, dict) else {}
        stability = scores.get('stability', mood_score)

        checkin_data = {
            'user_id':       str(patient_id),
            'checkin_date':  date_str,
            # Core numeric fields
            'mood_score':    mood_score,
            'stress_score':  stress_score,
            'sleep_hours':   sleep_hours,
            # Check-in metadata
            'checkin_type':  checkin_type,
            'time_of_day':   time_of_day,
            # Medication log (JSON array of {name, dose, taken, time_taken})
            'medications':   medications or [],
            # Extended data blob (energy, focus, caffeine, computed scores, …)
            'extended_data': ext,
            # Backwards-compatible composite score kept for legacy queries
            'stability_score': int(round(float(stability))) if stability is not None else mood_score,
            'notes':         notes,
            'created_at':    datetime.utcnow().isoformat(),
        }

        response = supabase_admin.table('checkins').insert(checkin_data).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]['id']
        print(f"create_checkin: insert returned no data. Response: {response}")
        return None
    except Exception as e:
        print(f"Error creating checkin: {e}")
        raise  # re-raise so app.py can surface the real error


def update_checkin_insights(checkin_id, insights_text):
    """Update check-in with AI insights."""
    try:
        supabase_admin.table('checkins').update({'ai_insights': insights_text}).eq('id', str(checkin_id)).execute()
        return True
    except Exception as e:
        print(f"Error updating checkin insights: {e}")
        return False


def get_checkin_baseline(patient_id, days=7):
    """Return per-metric averages over the last N days.

    The React check-in app (App.jsx) uses this as its live baseline object and
    expects the keys:
      avgMood, avgEnergy, avgAnxiety, avgSleepHours, avgSleepQuality,
      avgCaffeineMg, optimalCaffeine
    Legacy callers receive the additional keys `baseline` and `count`.
    """
    try:
        cutoff_date = (date.today() - timedelta(days=days)).isoformat()
        response = supabase_admin.table('checkins').select(
            'mood_score, stress_score, sleep_hours, stability_score, extended_data'
        ).gte('checkin_date', cutoff_date).eq('user_id', str(patient_id)).execute()

        rows = response.data or []

        def _avg(vals):
            v = [x for x in vals if x is not None]
            return round(sum(v) / len(v), 2) if v else None

        # Pull scalar columns
        moods    = [r.get('mood_score') or r.get('stability_score') for r in rows]
        stresses = [r.get('stress_score') for r in rows]
        sleeps   = [r.get('sleep_hours') for r in rows]

        # Pull extended_data sub-fields
        energies, sleep_quals, caffeines = [], [], []
        for r in rows:
            ext = r.get('extended_data') or {}
            if isinstance(ext, str):
                try:
                    ext = json.loads(ext)
                except Exception:
                    ext = {}
            if ext.get('energy') is not None:
                energies.append(float(ext['energy']))
            if ext.get('sleep_quality') is not None:
                sleep_quals.append(float(ext['sleep_quality']))
            if ext.get('caffeine_mg') is not None:
                caffeines.append(float(ext['caffeine_mg']))

        avg_mood       = _avg(moods)   or 6.8
        avg_energy     = _avg(energies) or 6.5
        avg_anxiety    = _avg(stresses) or 3.2
        avg_sleep_hrs  = _avg(sleeps)  or 5.9
        avg_sleep_qual = _avg(sleep_quals) or 6.2
        avg_caffeine   = _avg(caffeines) or 0.0

        return {
            # Keys expected by React
            'avgMood':         avg_mood,
            'avgEnergy':       avg_energy,
            'avgAnxiety':      avg_anxiety,
            'avgSleepHours':   avg_sleep_hrs,
            'avgSleepQuality': avg_sleep_qual,
            'avgCaffeineMg':   avg_caffeine,
            'optimalCaffeine': {'min': 200, 'max': 300},
            # Legacy keys (used by claude_api.py)
            'baseline': avg_mood,
            'count':    len(rows),
        }
    except Exception as e:
        print(f"Error getting checkin baseline: {e}")
        return {
            'avgMood': 6.8, 'avgEnergy': 6.5, 'avgAnxiety': 3.2,
            'avgSleepHours': 5.9, 'avgSleepQuality': 6.2, 'avgCaffeineMg': 0.0,
            'optimalCaffeine': {'min': 200, 'max': 300},
            'baseline': None, 'count': 0,
        }


def get_checkins(patient_id, days=30):
    """Get all check-ins for a patient in the last N days."""
    try:
        cutoff_date = (date.today() - timedelta(days=days)).isoformat()
        response = supabase_admin.table('checkins').select('*').gte('checkin_date', cutoff_date).eq('user_id', str(patient_id)).order('checkin_date', desc=True).execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error getting checkins: {e}")
        return []


def get_checkins_in_range(patient_id, start_date: str, end_date: str):
    """Get check-ins for a patient within an explicit date range (inclusive)."""
    try:
        response = (supabase_admin.table('checkins').select('*')
                    .eq('user_id', str(patient_id))
                    .gte('checkin_date', start_date)
                    .lte('checkin_date', end_date)
                    .order('checkin_date', desc=False).execute())
        return response.data if response.data else []
    except Exception as e:
        print(f"Error getting checkins in range: {e}")
        return []


def get_journals_in_range(patient_id, start_date: str, end_date: str, shared_only=False):
    """Get journal entries within an explicit date range (inclusive)."""
    try:
        query = (supabase_admin.table('journal_entries').select('*')
                 .eq('user_id', str(patient_id))
                 .gte('entry_date', start_date)
                 .lte('entry_date', end_date))
        if shared_only:
            query = query.eq('share_with_provider', True)
        response = query.order('entry_date', desc=False).execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error getting journals in range: {e}")
        return []


def get_checkin_streak(patient_id):
    """Get current check-in streak.

    Multiple check-ins on the same day count as one — dates are deduplicated
    before the sequential comparison so morning/afternoon/evening check-ins
    don't reset the streak counter.
    """
    try:
        response = (supabase_admin.table('checkins')
                    .select('checkin_date')
                    .eq('user_id', str(patient_id))
                    .order('checkin_date', desc=True)
                    .limit(90)
                    .execute())

        if not response.data:
            return 0

        # Deduplicate: one entry per calendar date, preserve desc order
        seen, unique_dates = set(), []
        for row in response.data:
            d = (row.get('checkin_date') or '')[:10]
            if d and d not in seen:
                seen.add(d)
                unique_dates.append(d)

        streak = 0
        today = date.today()
        for i, date_str in enumerate(unique_dates):
            if date.fromisoformat(date_str) == today - timedelta(days=i):
                streak += 1
            else:
                break
        return streak
    except Exception as e:
        print(f"Error getting checkin streak: {e}")
        return 0


# ═══════════════════════════════════════════════════════════════════════════
# JOURNAL ENTRIES
# ═══════════════════════════════════════════════════════════════════════════

def create_journal(patient_id, entry_type, raw_entry, ai_analysis=None, share_with_provider=1):
    """Create a journal entry."""
    try:
        journal_data = {
            'user_id': str(patient_id),
            'entry_date': date.today().isoformat(),
            'content': raw_entry,
            'is_crisis': entry_type == 'crisis',
            'created_at': datetime.utcnow().isoformat()
        }
        
        response = supabase_admin.table('journal_entries').insert(journal_data).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]['id']
        return None
    except Exception as e:
        print(f"Error creating journal: {e}")
        return None


def get_journals(patient_id, limit=20, shared_only=False):
    """Get journal entries."""
    try:
        query = supabase_admin.table('journal_entries').select('*').eq('user_id', str(patient_id))
        
        if shared_only:
            query = query.eq('share_with_provider', True)
        
        response = query.order('entry_date', desc=True).limit(limit).execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error getting journals: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════
# SUMMARIES
# ═══════════════════════════════════════════════════════════════════════════

def create_summary(patient_id, summary_text, date_range_start, date_range_end, raw_claude_response=None):
    """Create a summary.

    Attempts to store all structured fields; falls back to minimal insert if the
    Supabase table only has the legacy 'content' column.
    """
    try:
        full_data = {
            'user_id':          str(patient_id),
            'summary_date':     date.today().isoformat(),
            'content':          summary_text,   # legacy column kept for compatibility
            'summary_text':     summary_text,   # preferred column
            'date_range_start': date_range_start,
            'date_range_end':   date_range_end,
            'created_at':       datetime.utcnow().isoformat(),
        }
        try:
            response = supabase_admin.table('summaries').insert(full_data).execute()
            if response.data:
                return response.data[0]['id']
        except Exception:
            # Table may not have the newer columns yet — fall back to minimal set
            minimal = {
                'user_id':      str(patient_id),
                'summary_date': date.today().isoformat(),
                'content':      summary_text,
                'created_at':   datetime.utcnow().isoformat(),
            }
            response = supabase_admin.table('summaries').insert(minimal).execute()
            if response.data:
                return response.data[0]['id']
        return None
    except Exception as e:
        print(f"Error creating summary: {e}")
        return None


def get_summaries(patient_id):
    """Get all summaries for a patient, normalising field names for template compatibility."""
    try:
        response = supabase_admin.table('summaries').select('*').eq('user_id', str(patient_id)).order('summary_date', desc=True).execute()
        rows = response.data or []
        for r in rows:
            # Normalise text — prefer summary_text column, fall back to content
            if not r.get('summary_text'):
                r['summary_text'] = r.get('content', '')
            # Derive date range from summary_date if not stored
            if not r.get('date_range_end'):
                d = (r.get('summary_date') or '')[:10]
                r['date_range_end'] = d
                try:
                    r['date_range_start'] = (date.fromisoformat(d) - timedelta(days=14)).isoformat() if d else ''
                except Exception:
                    r['date_range_start'] = ''
        return rows
    except Exception as e:
        print(f"Error getting summaries: {e}")
        return []


def delete_summary(patient_id, summary_id):
    """Delete a summary, enforcing ownership so patients can only delete their own."""
    try:
        supabase_admin.table('summaries').delete().eq('id', str(summary_id)).eq('user_id', str(patient_id)).execute()
        return True
    except Exception as e:
        print(f"Error deleting summary: {e}")
        return False


def get_latest_summary(patient_id):
    """Get the most recent summary."""
    try:
        response = supabase_admin.table('summaries').select('*').eq('user_id', str(patient_id)).order('summary_date', desc=True).limit(1).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error getting latest summary: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════
# MEDICATIONS
# ═══════════════════════════════════════════════════════════════════════════

def create_medication(user_id: str, name: str, category: str, standard_dose: float, dose_unit: str = 'mg', scheduled_times: list = None, date_started: str = None):
    """Create a medication record for the user."""
    try:
        result = supabase_admin.table('medications').insert({
            'user_id': user_id,
            'name': name,
            'category': category,
            'standard_dose': standard_dose,
            'dose_unit': dose_unit,
            'scheduled_times': scheduled_times or [],
            'date_started': date_started or date.today().isoformat(),
            'is_active': True
        }).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"Error creating medication: {e}")
        return None

def get_user_medications(user_id: str, active_only: bool = True):
    """Get all medications for a user."""
    try:
        query = supabase_admin.table('medications').select('*').eq('user_id', user_id)
        if active_only:
            query = query.eq('is_active', True)
        result = query.execute()
        return result.data or []
    except Exception as e:
        print(f"Error fetching medications: {e}")
        return []

def log_medication_event(user_id: str, medication_id: str, event_date: str, actual_time: str, dose: float, status: str = 'TAKEN', notes: str = None):
    """Log a medication event (when user took their medication)."""
    try:
        result = supabase_admin.table('medication_events').insert({
            'user_id': user_id,
            'medication_id': medication_id,
            'event_date': event_date,
            'actual_time': actual_time,
            'dose': dose,
            'status': status,
            'custom_note': notes
        }).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"Error logging medication event: {e}")
        return None

def get_medication_events(user_id: str, medication_id: str = None, days: int = 30):
    """Get medication events for a user."""
    try:
        start_date = (date.today() - timedelta(days=days)).isoformat()
        query = supabase_admin.table('medication_events').select('*').eq('user_id', user_id).gte('event_date', start_date)
        if medication_id:
            query = query.eq('medication_id', medication_id)
        result = query.execute()
        return result.data or []
    except Exception as e:
        print(f"Error fetching medication events: {e}")
        return []

def get_medication_names() -> list:
    """Return a sorted list of all medication names from the reference table."""
    try:
        result = supabase_admin.table('medication_reference').select('name').execute()
        return sorted({row['name'] for row in result.data}) if result.data else []
    except Exception as e:
        print(f"Error fetching medication names: {e}")
        return []

def get_medication_info(name: str):
    """Get full reference info for a single medication by name (case-insensitive)."""
    try:
        result = supabase_admin.table('medication_reference').select('*').ilike('name', name).limit(1).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"Error fetching medication info: {e}")
        return None

def check_medication_interactions(patient_id) -> list:
    """Return known drug interaction alerts for a patient's active medications.

    Checks a curated list of clinically significant psychiatric / neurological
    drug-drug interactions.  Matching is case-insensitive substring search so
    it handles brand names and common abbreviations (e.g. "sertraline" matches
    "sertraline 50mg", "Sertraline (Zoloft)", etc.).

    Returns a list of dicts:  {drug_a, drug_b, severity, warning}
    severity is 'serious' | 'moderate' | 'caution'.
    """
    # ── Interaction table ────────────────────────────────────────────
    # Each entry: ([drug_a_aliases], [drug_b_aliases], severity, warning)
    INTERACTIONS = [
        # ── Serotonin syndrome risk ──────────────────────────────────
        (['selegiline', 'phenelzine', 'tranylcypromine', 'isocarboxazid', 'rasagiline', 'monoamine oxidase'],
         ['sertraline', 'fluoxetine', 'paroxetine', 'escitalopram', 'citalopram', 'fluvoxamine',
          'venlafaxine', 'duloxetine', 'desvenlafaxine', 'levomilnacipran',
          'bupropion', 'tramadol', 'meperidine', 'dextromethorphan', 'triptans', 'linezolid',
          'lithium', 'tryptophan', 'st. john'],
         'serious',
         'MAOI + serotonergic agent: high risk of serotonin syndrome. Potentially life-threatening.'),

        (['sertraline', 'fluoxetine', 'paroxetine', 'escitalopram', 'citalopram', 'fluvoxamine'],
         ['tramadol'],
         'serious',
         'SSRI + tramadol: elevated serotonin syndrome risk; tramadol also lowers seizure threshold.'),

        (['sertraline', 'fluoxetine', 'paroxetine', 'escitalopram', 'citalopram', 'fluvoxamine',
          'venlafaxine', 'duloxetine'],
         ['lithium'],
         'moderate',
         'SSRI/SNRI + lithium: additive serotonergic effect; monitor for serotonin toxicity signs.'),

        # ── Lithium toxicity ─────────────────────────────────────────
        (['lithium'],
         ['ibuprofen', 'naproxen', 'diclofenac', 'celecoxib', 'nsaid', 'indomethacin',
          'aspirin'],
         'serious',
         'Lithium + NSAID: NSAIDs reduce lithium clearance, raising plasma levels to potentially toxic range. Monitor levels closely.'),

        (['lithium'],
         ['hydrochlorothiazide', 'furosemide', 'lasix', 'chlorthalidone', 'thiazide', 'diuretic'],
         'serious',
         'Lithium + diuretic: sodium depletion increases lithium reabsorption — toxicity risk. Check levels.'),

        (['lithium'],
         ['ace inhibitor', 'lisinopril', 'enalapril', 'ramipril', 'captopril',
          'losartan', 'valsartan', 'irbesartan', 'arb'],
         'serious',
         'Lithium + ACE inhibitor / ARB: significant lithium retention risk. Requires dose adjustment and close monitoring.'),

        # ── QT prolongation ──────────────────────────────────────────
        (['citalopram', 'escitalopram'],
         ['quetiapine', 'haloperidol', 'ziprasidone', 'thioridazine', 'chlorpromazine',
          'methadone', 'azithromycin', 'clarithromycin', 'ciprofloxacin', 'ondansetron'],
         'serious',
         'QT-prolonging combination: additive risk of arrhythmia (torsades de pointes).'),

        # ── CNS / respiratory depression ─────────────────────────────
        (['alprazolam', 'clonazepam', 'diazepam', 'lorazepam', 'temazepam', 'benzodiazepine',
          'zolpidem', 'eszopiclone', 'zaleplon'],
         ['oxycodone', 'hydrocodone', 'codeine', 'morphine', 'fentanyl', 'buprenorphine',
          'methadone', 'tramadol', 'opioid'],
         'serious',
         'Benzodiazepine + opioid: combined CNS/respiratory depression — risk of fatal respiratory arrest. Avoid unless closely monitored.'),

        # ── Antiepileptic interactions ───────────────────────────────
        (['valproate', 'valproic acid', 'divalproex', 'depakote'],
         ['lamotrigine', 'lamictal'],
         'serious',
         'Valproate + lamotrigine: valproate roughly doubles lamotrigine levels. Dose reduction of lamotrigine required.'),

        (['carbamazepine', 'tegretol'],
         ['clozapine'],
         'serious',
         'Carbamazepine + clozapine: additive risk of bone marrow suppression (agranulocytosis). Avoid combination.'),

        (['carbamazepine', 'tegretol', 'phenytoin', 'dilantin', 'phenobarbital'],
         ['quetiapine', 'olanzapine', 'risperidone', 'aripiprazole',
          'sertraline', 'fluoxetine', 'escitalopram', 'citalopram',
          'venlafaxine', 'duloxetine', 'clonazepam', 'alprazolam'],
         'moderate',
         'CYP3A4 inducer + substrate: enzyme-inducing anticonvulsant may significantly reduce plasma levels of co-administered drug.'),

        # ── Bupropion ────────────────────────────────────────────────
        (['bupropion', 'wellbutrin'],
         ['tramadol', 'clozapine', 'clomipramine'],
         'serious',
         'Bupropion + this agent: substantially lowers seizure threshold. Avoid unless benefit clearly outweighs risk.'),

        # ── Antipsychotic combinations ───────────────────────────────
        (['clozapine'],
         ['olanzapine'],
         'caution',
         'Two heavily sedating antipsychotics: risk of excessive sedation and metabolic side effects.'),

        # ── Stimulants ───────────────────────────────────────────────
        (['amphetamine', 'adderall', 'methylphenidate', 'ritalin', 'dexmethylphenidate',
          'lisdexamfetamine', 'vyvanse'],
         ['selegiline', 'phenelzine', 'tranylcypromine', 'isocarboxazid', 'monoamine oxidase'],
         'serious',
         'Stimulant + MAOI: hypertensive crisis risk. Absolutely contraindicated.'),
    ]

    try:
        # Collect active medication names from both the new medications table
        # and the legacy patient_profiles.current_medications JSONB array.
        med_names = set()

        active_meds = get_user_medications(patient_id, active_only=True)
        for m in active_meds:
            if m.get('name'):
                med_names.add(m['name'].lower())

        profile = get_patient_profile(patient_id)
        if profile:
            legacy = profile.get('current_medications') or []
            if isinstance(legacy, str):
                try:
                    legacy = json.loads(legacy)
                except Exception:
                    legacy = []
            for m in legacy:
                name = m.get('name', '') if isinstance(m, dict) else str(m)
                if name:
                    med_names.add(name.lower())

        if len(med_names) < 2:
            return []

        # Check every known interaction pair
        alerts = []
        seen = set()

        for aliases_a, aliases_b, severity, warning in INTERACTIONS:
            matched_a = next((n for n in med_names
                              if any(alias in n or n in alias for alias in aliases_a)), None)
            matched_b = next((n for n in med_names
                              if any(alias in n or n in alias for alias in aliases_b)), None)

            if matched_a and matched_b and matched_a != matched_b:
                key = tuple(sorted([matched_a, matched_b]))
                if key not in seen:
                    seen.add(key)
                    alerts.append({
                        'drug_a':   matched_a.title(),
                        'drug_b':   matched_b.title(),
                        'severity': severity,
                        'warning':  warning,
                    })

        return alerts

    except Exception as e:
        print(f"Error checking medication interactions: {e}")
        return []

def search_medication_reference(search_term: str):
    """Search the global medication reference database."""
    try:
        result = supabase_admin.table('medication_reference').select('*').ilike('name', f'%{search_term}%').execute()
        return result.data or []
    except Exception as e:
        print(f"Error searching medication reference: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════
# PROVIDER OPERATIONS
# ═══════════════════════════════════════════════════════════════════════════

def _has_suicide_risk(user_id: str, days: int = 7) -> bool:
    """Return True if any check-in notes or journal entries in the last N days
    contain crisis-level language (suicide / self-harm keywords)."""
    from claude_api import check_crisis
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    try:
        ci = supabase_admin.table('checkins').select('notes').eq(
            'user_id', user_id).gte('checkin_date', cutoff).execute()
        for row in (ci.data or []):
            if check_crisis(row.get('notes') or ''):
                return True
        je = supabase_admin.table('journal_entries').select('raw_entry').eq(
            'user_id', user_id).gte('entry_date', cutoff).execute()
        for row in (je.data or []):
            if check_crisis(row.get('raw_entry') or ''):
                return True
        return False
    except Exception:
        return False


def get_provider_patients(provider_id):
    """Return a list of patient summary dicts for all patients assigned to this provider.

    Each dict contains the fields the provider sidebar template expects:
      patient_id, full_name, email, last_checkin, latest_summary,
      current_medications
    """
    try:
        # Get profile rows for every patient assigned to this provider
        prof_resp = supabase_admin.table('patient_profiles').select(
            'user_id, current_medications'
        ).eq('provider_id', str(provider_id)).execute()

        if not prof_resp.data:
            return []

        patients = []
        for row in prof_resp.data:
            uid = row['user_id']

            # Fetch identity info from the profiles table
            user = get_user_by_id(uid)
            if not user:
                continue

            # Last check-in date
            ci_resp = supabase_admin.table('checkins').select('checkin_date').eq(
                'user_id', uid).order('checkin_date', desc=True).limit(1).execute()
            last_checkin = (ci_resp.data[0]['checkin_date'][:10]
                            if ci_resp.data else None)

            # Whether a summary exists
            sm_resp = supabase_admin.table('summaries').select('id').eq(
                'user_id', uid).limit(1).execute()
            has_summary = bool(sm_resp.data)

            meds = row.get('current_medications') or []
            if isinstance(meds, str):
                try:
                    meds = json.loads(meds)
                except Exception:
                    meds = []

            patients.append({
                'patient_id':          uid,
                'full_name':           user['full_name'],
                'email':               user['email'],
                'last_checkin':        last_checkin,
                'latest_summary':      has_summary,
                'current_medications': meds,
                'suicide_risk':        _has_suicide_risk(uid),
            })

        return patients
    except Exception as e:
        print(f"Error getting provider patients: {e}")
        return []


def get_patient_detail(patient_id, days=30):
    """Return a flat dict with all data the provider patient-detail template uses.

    Top-level keys the template accesses directly on `patient`:
      patient_id, full_name, email, current_medications,
      checkins_last_period, checkins, journals, latest_summary, profile
    """
    try:
        user    = get_user_by_id(patient_id)
        profile = get_patient_profile(patient_id)
        checkins = get_checkins(patient_id, days)
        journals = get_journals(patient_id, limit=20, shared_only=True)
        latest_summary = get_latest_summary(patient_id)

        meds = []
        if profile:
            meds = profile.get('current_medications') or []
            if isinstance(meds, str):
                try:
                    meds = json.loads(meds)
                except Exception:
                    meds = []

        return {
            # Flat identity / summary fields
            'patient_id':          patient_id,
            'full_name':           user['full_name'] if user else 'Unknown',
            'email':               user['email']     if user else '',
            'current_medications': meds,
            'checkins_last_period': len(checkins),
            # Nested sub-objects still available for advanced template use
            'profile':        profile,
            'checkins':       checkins,
            'journals':       journals,
            'latest_summary': latest_summary,
        }
    except Exception as e:
        print(f"Error getting patient detail: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════
# TRENDS & ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════

def _linear_regression(values):
    """Return slope, R², and an approximate p-value for a value series.

    Returns a dict:
      slope     – units-per-observation
      r_squared – coefficient of determination (0–1)
      p_value   – approximate two-tailed significance (very rough t-table)
    Returns None when there are fewer than 3 observations.
    """
    if not values or len(values) < 3:
        return None

    n = len(values)
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(values) / n

    ss_xy = sum((xs[i] - x_mean) * (values[i] - y_mean) for i in range(n))
    ss_xx = sum((xs[i] - x_mean) ** 2 for i in range(n))
    ss_yy = sum((values[i] - y_mean) ** 2 for i in range(n))

    if ss_xx == 0:
        return {'slope': 0.0, 'r_squared': 0.0, 'p_value': 1.0}

    slope   = ss_xy / ss_xx
    r_sq    = (ss_xy ** 2) / (ss_xx * ss_yy) if ss_yy > 0 else 0.0

    # Approximate p-value via t-statistic (df = n-2)
    if n > 2 and 0 < r_sq < 1:
        se_slope = ((ss_yy * (1 - r_sq) / ss_xx) / (n - 2)) ** 0.5
        t_stat   = abs(slope / se_slope) if se_slope > 0 else 0
    else:
        t_stat = 0
    if   t_stat > 3.5: p_val = 0.01
    elif t_stat > 2.5: p_val = 0.02
    elif t_stat > 2.0: p_val = 0.05
    elif t_stat > 1.5: p_val = 0.15
    else:              p_val = 0.50

    return {
        'slope':     round(slope, 4),
        'r_squared': round(r_sq,  3),
        'p_value':   round(p_val, 3),
    }


def _trend_stats(values):
    """Return the full trend dict expected by app.py provider alerts.

    Shape:
      { average, trend, slope, r_squared, p_value, values }
    """
    if not values:
        return {'average': None, 'trend': 'insufficient_data',
                'slope': None, 'r_squared': 0, 'p_value': 1, 'values': []}

    def _avg(v):
        return round(sum(v) / len(v), 2) if v else None

    reg = _linear_regression(values)
    if reg is None:
        return {'average': _avg(values), 'trend': 'insufficient_data',
                'slope': None, 'r_squared': 0, 'p_value': 1, 'values': values}

    slope = reg['slope']
    trend = ('increasing' if slope >  0.05 else
             'decreasing' if slope < -0.05 else 'stable')

    return {
        'average':   _avg(values),
        'trend':     trend,
        'slope':     slope,
        'r_squared': reg['r_squared'],
        'p_value':   reg['p_value'],
        'values':    values,
    }


def get_trends_data(user_id: str, days: int = 30):
    """Return aggregated trend data.

    Keys consumed by the patient trends JS and provider template:
      mood        – _trend_stats dict + daily_scores + dates
      stress      – _trend_stats dict + daily_scores + dates
      sleep       – {average, values, daily_hours, dates}
      energy      – {average, values, daily_scores, dates}
      medication_adherence  – int 0–100
      checkin_count / total_checkins / checkins_this_period – int
      period_days – int (the requested window)
    """
    def _empty_metric_ts():
        return {**_trend_stats([]), 'daily_scores': [], 'dates': []}

    _empty_adv = lambda: {'average': None, 'daily_scores': [], 'dates': []}
    _empty = {
        'user_id':              user_id,
        'date_range':           {'start': (date.today() - timedelta(days=days)).isoformat(),
                                 'end':   date.today().isoformat()},
        'total_checkins':       0,
        'checkin_count':        0,
        'checkins_this_period': 0,
        'period_days':          days,
        'mood':                 _empty_metric_ts(),
        'stress':               _empty_metric_ts(),
        'sleep':                {'average': None, 'values': [], 'daily_hours': [], 'dates': []},
        'energy':               {'average': None, 'values': [], 'daily_scores': [], 'dates': []},
        'medication_adherence': 0,
        # Extended base metrics
        'focus':            _empty_adv(),
        'dissociation':     _empty_adv(),
        'sleep_quality':    _empty_adv(),
        'caffeine':         _empty_adv(),
        # Advanced mode metrics
        'irritability':     _empty_adv(),
        'motivation':       _empty_adv(),
        'perceived_stress': _empty_adv(),
        'alcohol':          _empty_adv(),
        'exercise':         _empty_adv(),
        'sunlight':         _empty_adv(),
        'screen_time':      _empty_adv(),
        'social_quality':   _empty_adv(),
        'workload_friction': _empty_adv(),
    }

    try:
        start_date = (date.today() - timedelta(days=days)).isoformat()
        result = supabase_admin.table('checkins').select('*').eq(
            'user_id', user_id).gte('checkin_date', start_date).order(
            'checkin_date', desc=False).execute()

        data = result.data or []
        if not data:
            _empty['date_range']['start'] = start_date
            return _empty

        # ── Extract per-row values, tracking dates per metric ─────────
        mood_pairs, stress_pairs, sleep_pairs, energy_pairs = [], [], [], []
        # extended base
        focus_pairs, dissociation_pairs, sleep_quality_pairs, caffeine_pairs = [], [], [], []
        # advanced mode
        irritability_pairs, motivation_pairs, perceived_stress_pairs = [], [], []
        alcohol_pairs, exercise_pairs, sunlight_pairs, screen_time_pairs = [], [], [], []
        social_quality_pairs, workload_pairs = [], []

        meds_with_entries, meds_with_taken = 0, 0

        _EXT_FIELDS = [
            ('energy',            energy_pairs),
            ('focus',             focus_pairs),
            ('dissociation',      dissociation_pairs),
            ('sleep_quality',     sleep_quality_pairs),
            ('caffeine_mg',       caffeine_pairs),
            ('irritability',      irritability_pairs),
            ('motivation',        motivation_pairs),
            ('perceived_stress',  perceived_stress_pairs),
            ('alcohol_units',     alcohol_pairs),
            ('exercise_minutes',  exercise_pairs),
            ('sunlight_hours',    sunlight_pairs),
            ('screen_time_hours', screen_time_pairs),
            ('social_quality',    social_quality_pairs),
            ('workload_friction', workload_pairs),
        ]

        for row in data:
            d = row.get('checkin_date', '')

            mood = row.get('mood_score') or row.get('stability_score')
            if mood is not None:
                mood_pairs.append((d, float(mood)))

            stress = row.get('stress_score')
            if stress is not None:
                stress_pairs.append((d, float(stress)))

            sleep = row.get('sleep_hours')
            if sleep is not None:
                sleep_pairs.append((d, float(sleep)))

            ext = row.get('extended_data') or {}
            if isinstance(ext, str):
                try:
                    ext = json.loads(ext)
                except Exception:
                    ext = {}

            for key, pairs in _EXT_FIELDS:
                val = ext.get(key)
                if val is not None:
                    try:
                        pairs.append((d, float(val)))
                    except (ValueError, TypeError):
                        pass

            meds = row.get('medications') or []
            if isinstance(meds, str):
                try:
                    meds = json.loads(meds)
                except Exception:
                    meds = []
            if meds:
                meds_with_entries += 1
                if any(m.get('taken') for m in meds if isinstance(m, dict)):
                    meds_with_taken += 1

        adherence = (round((meds_with_taken / meds_with_entries) * 100)
                     if meds_with_entries > 0 else 0)

        def _avg(v):
            return round(sum(v) / len(v), 2) if v else None

        def _unzip(pairs):
            if not pairs:
                return [], []
            dates, vals = zip(*pairs)
            return list(dates), list(vals)

        def _make_ts(pairs):
            dates, vals = _unzip(pairs)
            return {'average': _avg(vals), 'daily_scores': vals, 'dates': dates}

        mood_dates,   mood_vals   = _unzip(mood_pairs)
        stress_dates, stress_vals = _unzip(stress_pairs)
        sleep_dates,  sleep_vals  = _unzip(sleep_pairs)

        mood_ts   = {**_trend_stats(mood_vals),   'daily_scores': mood_vals,   'dates': mood_dates}
        stress_ts = {**_trend_stats(stress_vals), 'daily_scores': stress_vals, 'dates': stress_dates}

        energy_ts = _make_ts(energy_pairs)

        return {
            'user_id':              user_id,
            'date_range':           {'start': start_date, 'end': date.today().isoformat()},
            'total_checkins':       len(data),
            'checkin_count':        len(data),
            'checkins_this_period': len(data),
            'period_days':          days,
            'mood':                 mood_ts,
            'stress':               stress_ts,
            'sleep':  {'average': _avg(sleep_vals), 'values': sleep_vals,
                       'daily_hours': sleep_vals,   'dates': sleep_dates},
            'energy': {'average': energy_ts['average'], 'values': energy_ts['daily_scores'],
                       'daily_scores': energy_ts['daily_scores'], 'dates': energy_ts['dates']},
            'medication_adherence': adherence,
            'average_stability':    _avg(mood_vals),
            # Extended base metrics
            'focus':            _make_ts(focus_pairs),
            'dissociation':     _make_ts(dissociation_pairs),
            'sleep_quality':    _make_ts(sleep_quality_pairs),
            'caffeine':         _make_ts(caffeine_pairs),
            # Advanced mode metrics
            'irritability':     _make_ts(irritability_pairs),
            'motivation':       _make_ts(motivation_pairs),
            'perceived_stress': _make_ts(perceived_stress_pairs),
            'alcohol':          _make_ts(alcohol_pairs),
            'exercise':         _make_ts(exercise_pairs),
            'sunlight':         _make_ts(sunlight_pairs),
            'screen_time':      _make_ts(screen_time_pairs),
            'social_quality':   _make_ts(social_quality_pairs),
            'workload_friction': _make_ts(workload_pairs),
        }
    except Exception as e:
        print(f"Error getting trends: {e}")
        return None


def get_paired_values(patient_id, var_a, var_b, days=60):
    """Return (date, val_a, val_b) triples for two VALID_HYPOTHESIS_VARS.

    Variable → storage location mapping:
      mood   → mood_score column   (fallback: stability_score)
      stress → stress_score column
      sleep  → sleep_hours column
      energy → extended_data->>'energy'
      focus  → extended_data->>'focus'
    """
    # col = database column; ext = key inside extended_data JSONB (None if not needed)
    VAR_MAP = {
        'mood':   ('mood_score',   None),
        'stress': ('stress_score', None),
        'sleep':  ('sleep_hours',  None),
        'energy': (None,           'energy'),
        'focus':  (None,           'focus'),
    }

    def _extract(row, var):
        col, ext_key = VAR_MAP.get(var, (None, None))
        if col:
            v = row.get(col)
            # Backwards-compat: old rows stored mood only in stability_score
            if v is None and var == 'mood':
                v = row.get('stability_score')
            return float(v) if v is not None else None
        if ext_key:
            ext = row.get('extended_data') or {}
            if isinstance(ext, str):
                try:
                    ext = json.loads(ext)
                except Exception:
                    ext = {}
            v = ext.get(ext_key)
            return float(v) if v is not None else None
        return None

    try:
        checkins = get_checkins(patient_id, days)
        pairs = []
        for c in checkins:
            val_a = _extract(c, var_a)
            val_b = _extract(c, var_b)
            if val_a is not None and val_b is not None:
                pairs.append((c.get('checkin_date', ''), val_a, val_b))
        return pairs
    except Exception as e:
        print(f"Error getting paired values: {e}")
        return []


def compute_correlation_evidence(pairs, user_direction):
    """Compute correlation evidence between two variables."""
    if not pairs or len(pairs) < 3:
        return {'r': None, 'p': None, 'evidence': 0.0}
    
    values_a = [p[1] for p in pairs]
    values_b = [p[2] for p in pairs]
    
    n = len(values_a)
    mean_a = sum(values_a) / n
    mean_b = sum(values_b) / n
    
    cov = sum((values_a[i] - mean_a) * (values_b[i] - mean_b) for i in range(n)) / n
    std_a = (sum((v - mean_a) ** 2 for v in values_a) / n) ** 0.5
    std_b = (sum((v - mean_b) ** 2 for v in values_b) / n) ** 0.5
    
    if std_a == 0 or std_b == 0:
        return {'r': 0, 'p': None, 'evidence': 0.0}
    
    r = cov / (std_a * std_b)
    
    # Simplified evidence calculation
    evidence = abs(r) * (n / 10.0)
    
    return {
        'r': round(r, 3),
        'p': None,
        'evidence': round(min(evidence, 1.0), 3)
    }


# ═══════════════════════════════════════════════════════════════════════════
# HYPOTHESIS TESTING
# ═══════════════════════════════════════════════════════════════════════════

def save_hypothesis_result(patient_id, var_a, var_b, user_direction, result):
    """Save hypothesis test result."""
    try:
        hyp_data = {
            'user_id': str(patient_id),
            'hypothesis': f"{var_a} -> {var_b}",
            'tested_at': datetime.utcnow().isoformat(),
            'result': json.dumps(result),
            'created_at': datetime.utcnow().isoformat()
        }
        
        response = supabase_admin.table('user_hypotheses').insert(hyp_data).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]['id']
        return None
    except Exception as e:
        print(f"Error saving hypothesis result: {e}")
        return None


def get_hypothesis_history(patient_id, limit=20):
    """Get hypothesis test history."""
    try:
        response = supabase_admin.table('user_hypotheses').select('*').eq('user_id', str(patient_id)).order('tested_at', desc=True).limit(limit).execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error getting hypothesis history: {e}")
        return []


def get_tested_pairs(patient_id):
    """Get all tested variable pairs."""
    try:
        history = get_hypothesis_history(patient_id, limit=100)
        pairs = set()
        
        for h in history:
            hyp_text = h.get('hypothesis', '')
            if '->' in hyp_text:
                var_a, var_b = hyp_text.split('->')
                pairs.add((var_a.strip(), var_b.strip()))
        
        return list(pairs)
    except Exception as e:
        print(f"Error getting tested pairs: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════
# MEDICATION TIMING STATS
# ═══════════════════════════════════════════════════════════════════════════

def get_medication_timing_stats(patient_id, days=30):
    """Compute per-medication timing stats and timing-outcome correlations.

    Returns a dict with all keys the provider patient_detail template expects:
      medications            – list of per-med timing dicts
      n_timing_records       – check-ins with at least one dose time recorded
      coverage_pct           – % of logged doses that have a time
      timing_alerts          – list of alert dicts
      dose_time_vs_mood      – Pearson correlation dict or None
      hours_since_dose_vs_mood   – Pearson correlation dict or None
      hours_since_dose_vs_energy – Pearson correlation dict or None
      medication_consistency – avg mood on days meds taken
      no_med_avg             – avg mood on days no meds taken
      sample_size            – total check-ins examined
    """
    _empty = {
        'medications': [], 'n_timing_records': 0, 'coverage_pct': 0,
        'timing_alerts': [], 'dose_time_vs_mood': None,
        'hours_since_dose_vs_mood': None, 'hours_since_dose_vs_energy': None,
        'medication_consistency': None, 'no_med_avg': None, 'sample_size': 0,
    }
    try:
        checkins = get_checkins(patient_id, days)
        if not checkins:
            return _empty

        def _parse_meds(raw):
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except Exception:
                    return []
            return [m for m in (raw or []) if isinstance(m, dict)]

        def _time_to_min(t):
            try:
                parts = str(t).split(':')
                return int(parts[0]) * 60 + int(parts[1])
            except Exception:
                return None

        def _avg(v):
            return round(sum(v) / len(v), 2) if v else None

        med_buckets = {}  # "name|||dose" -> {name, dose, n_taken, times_min}
        with_med_moods, without_med_moods = [], []
        n_dose_total = 0
        n_timed_total = 0

        for c in checkins:
            mood  = c.get('mood_score') or c.get('stability_score')
            meds  = _parse_meds(c.get('medications'))
            taken = [m for m in meds if m.get('taken')]

            if mood is not None:
                (with_med_moods if taken else without_med_moods).append(float(mood))

            for m in taken:
                n_dose_total += 1
                key = (m.get('name') or '').lower() + '|||' + (m.get('dose') or '').lower()
                if key not in med_buckets:
                    med_buckets[key] = {
                        'name': m.get('name', ''), 'dose': m.get('dose', ''),
                        'n_taken': 0, 'times_min': [],
                    }
                med_buckets[key]['n_taken'] += 1
                t = _time_to_min(m.get('taken_time') or m.get('time') or '')
                if t is not None:
                    med_buckets[key]['times_min'].append(t)
                    n_timed_total += 1

        medications_out = []
        for d in med_buckets.values():
            tm = d['times_min']
            n_timed = len(tm)
            avg_time = std_dev_h = consistency = None
            if tm:
                avg_m = sum(tm) / len(tm)
                avg_time = f"{int(avg_m) // 60:02d}:{int(avg_m) % 60:02d}"
                if n_timed >= 2:
                    variance = sum((t - avg_m) ** 2 for t in tm) / len(tm)
                    std_dev_h = round(variance ** 0.5 / 60, 1)
                    if   std_dev_h <= 0.5: consistency = 'excellent'
                    elif std_dev_h <= 1.0: consistency = 'good'
                    elif std_dev_h <= 2.0: consistency = 'fair'
                    else:                  consistency = 'poor'
            medications_out.append({
                'name': d['name'], 'dose': d['dose'],
                'avg_time': avg_time, 'consistency': consistency,
                'std_dev_hours': std_dev_h, 'n_timed': n_timed, 'n_taken': d['n_taken'],
            })

        coverage_pct = round(n_timed_total / n_dose_total * 100) if n_dose_total else 0

        return {
            'medications':               medications_out,
            'n_timing_records':          n_timed_total,
            'coverage_pct':              coverage_pct,
            'timing_alerts':             [],
            'dose_time_vs_mood':         None,
            'hours_since_dose_vs_mood':  None,
            'hours_since_dose_vs_energy': None,
            'medication_consistency':    _avg(with_med_moods),
            'no_med_avg':                _avg(without_med_moods),
            'sample_size':               len(checkins),
        }
    except Exception as e:
        print(f"Error getting medication timing stats: {e}")
        return _empty


def find_unexpected_pattern(patient_id, days=30):
    """Find unexpected patterns in patient data."""
    try:
        checkins = get_checkins(patient_id, days)
        
        if not checkins or len(checkins) < 5:
            return None
        
        mood_scores = [c.get('mood_score') or c.get('stability_score') for c in checkins]
        mood_scores = [s for s in mood_scores if s is not None]

        if not mood_scores:
            return None

        avg_score = sum(mood_scores) / len(mood_scores)
        std_dev = (sum((s - avg_score) ** 2 for s in mood_scores) / len(mood_scores)) ** 0.5

        outliers = [s for s in mood_scores if abs(s - avg_score) > 2 * std_dev]
        
        if outliers:
            return {
                'pattern_type': 'unexpected_volatility',
                'outlier_count': len(outliers),
                'average': round(avg_score, 2),
                'std_dev': round(std_dev, 2)
            }
        
        return None
    except Exception as e:
        print(f"Error finding unexpected pattern: {e}")
        return None

# ═══════════════════════════════════════════════════════════════════════════
# AI FEEDBACK
# ═══════════════════════════════════════════════════════════════════════════

def log_ai_feedback(user_id: str, content_type: str, content_id: str, rating: str):
    """Upsert a thumbs-up/thumbs-down rating on an AI-generated output.

    content_type: 'checkin' | 'journal' | 'summary'
    rating:       'up' | 'down'

    The unique constraint on (user_id, content_type, content_id) means repeated
    calls update the existing row, so users can change their vote.
    """
    if content_type not in ('checkin', 'journal', 'summary'):
        raise ValueError(f"Invalid content_type: {content_type}")
    if rating not in ('up', 'down'):
        raise ValueError(f"Invalid rating: {rating}")
    try:
        supabase_admin.table('ai_feedback').upsert(
            {
                'user_id':      str(user_id),
                'content_type': content_type,
                'content_id':   str(content_id),
                'rating':       rating,
                'created_at':   datetime.utcnow().isoformat(),
            },
            on_conflict='user_id,content_type,content_id',
        ).execute()
        return True
    except Exception as e:
        print(f"Error logging AI feedback: {e}")
        return False
