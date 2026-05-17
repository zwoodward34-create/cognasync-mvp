import math
import os
import re
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


VALID_HYPOTHESIS_VARS = {
    'mood', 'stress', 'sleep', 'energy', 'focus',
    'irritability', 'motivation', 'perceived_stress',
    'alcohol', 'exercise', 'sunlight', 'screen_time',
    'social_quality', 'workload_friction',
}

# Ordered list and labels used by find_unexpected_pattern — defined once at
# module level so they are not rebuilt on every call.
_CORRELATION_VAR_LABELS = {
    'mood': 'Mood', 'stress': 'Stress', 'sleep': 'Sleep',
    'energy': 'Energy', 'focus': 'Focus', 'irritability': 'Irritability',
    'motivation': 'Motivation', 'perceived_stress': 'Perceived Stress',
    'alcohol': 'Alcohol', 'exercise': 'Exercise', 'sunlight': 'Sunlight',
    'screen_time': 'Screen Time', 'social_quality': 'Social Quality',
    'workload_friction': 'Workload Friction',
}
_CORRELATION_VARS = list(_CORRELATION_VAR_LABELS.keys())


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
        supabase_admin.table('patient_profiles').upsert(
            {'user_id': str(patient_user_id), 'provider_id': value},
            on_conflict='user_id',
        ).execute()
        return True
    except Exception as e:
        print(f"Error assigning patient to provider: {e}")
        return False


def get_patients_needing_checkin_reminder(min_days_inactive: int = 2) -> list:
    """Return patients eligible for a check-in reminder email.

    Eligibility:
      - checkin_reminders_enabled = true
      - last check-in is >= min_days_inactive days ago (or never)
      - last_reminder_sent_at is NULL or > 48h ago (no spam)

    Returns list of dicts: {user_id, email, full_name, days_since, last_reminder_sent_at}
    """
    try:
        cutoff_checkin = (date.today() - timedelta(days=min_days_inactive)).isoformat()
        cutoff_reminder = (datetime.utcnow() - timedelta(hours=48)).isoformat()

        # Get eligible patient_profiles
        q = supabase_admin.table('patient_profiles').select(
            'user_id, last_reminder_sent_at'
        ).eq('checkin_reminders_enabled', True)
        pp_resp = q.execute()
        profiles = pp_resp.data or []

        eligible = []
        for p in profiles:
            uid = p['user_id']
            last_sent = p.get('last_reminder_sent_at')
            # Skip if reminder sent within 48h
            if last_sent and last_sent > cutoff_reminder:
                continue
            # Check most recent check-in
            ci = supabase_admin.table('checkins').select('checkin_date').eq(
                'user_id', uid).order('checkin_date', desc=True).limit(1).execute()
            if ci.data:
                last_ci = ci.data[0]['checkin_date']  # YYYY-MM-DD string
                if last_ci >= cutoff_checkin:
                    continue  # checked in recently enough
                days_since = (date.today() - date.fromisoformat(last_ci)).days
            else:
                days_since = 999  # never checked in

            # Fetch email + name
            prof = supabase_admin.table('profiles').select(
                'email, full_name').eq('id', uid).limit(1).execute()
            if not prof.data:
                continue
            eligible.append({
                'user_id':   uid,
                'email':     prof.data[0]['email'],
                'full_name': prof.data[0]['full_name'],
                'days_since': days_since,
            })

        return eligible
    except Exception as e:
        print(f"get_patients_needing_checkin_reminder error: {e}")
        return []


def mark_reminder_sent(user_id: str) -> None:
    """Stamp last_reminder_sent_at on the patient profile after sending a reminder."""
    try:
        supabase_admin.table('patient_profiles').update({
            'last_reminder_sent_at': datetime.utcnow().isoformat(),
        }).eq('user_id', str(user_id)).execute()
    except Exception as e:
        print(f"mark_reminder_sent error: {e}")


def set_checkin_reminders_enabled(user_id: str, enabled: bool) -> bool:
    """Patient opts in or out of check-in reminder emails."""
    try:
        supabase_admin.table('patient_profiles').update({
            'checkin_reminders_enabled': bool(enabled),
        }).eq('user_id', str(user_id)).execute()
        return True
    except Exception as e:
        print(f"set_checkin_reminders_enabled error: {e}")
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

def create_medication(user_id: str, name: str, category: str, standard_dose: float,
                      dose_unit: str = 'mg', scheduled_times: list = None,
                      date_started: str = None, frequency: str = None):
    """Create a medication record for the user."""
    try:
        insert_data = {
            'user_id':        user_id,
            'name':           name,
            'category':       category,
            'standard_dose':  standard_dose,
            'dose_unit':      dose_unit,
            'scheduled_times': scheduled_times or [],
            'date_started':   date_started or date.today().isoformat(),
            'is_active':      True,
        }
        if frequency:
            insert_data['frequency'] = frequency
        result = supabase_admin.table('medications').insert(insert_data).execute()
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

def find_or_create_profile_medication(user_id: str, name: str, dose_str: str = None) -> str | None:
    """Return the medications.id for a profile-based current_medication entry.

    Matches on (user_id, name, standard_dose) so two prescriptions with the
    same drug name but different doses get separate rows in the medications table.
    Creates a stub row if none exists yet.
    """
    try:
        dose_num = re.sub(r'[^\d.]', '', dose_str or '')
        dose_float = float(dose_num) if dose_num else None

        query = supabase_admin.table('medications').select('id') \
            .eq('user_id', user_id).ilike('name', name)
        if dose_float is not None:
            query = query.eq('standard_dose', dose_float)
        result = query.limit(1).execute()
        if result.data:
            return result.data[0]['id']

        ins_data = {'user_id': user_id, 'name': name, 'is_active': True,
                    'date_started': date.today().isoformat()}
        if dose_float is not None:
            ins_data['standard_dose'] = dose_float
        ins = supabase_admin.table('medications').insert(ins_data).execute()
        return ins.data[0]['id'] if ins.data else None
    except Exception as e:
        print(f"Error finding/creating profile medication: {e}")
        return None


def get_today_dose_logs(user_id: str, today: str = None) -> list:
    """Return medication events (status=TAKEN) logged today, with name and event id."""
    try:
        if today is None:
            today = date.today().isoformat()
        events = supabase_admin.table('medication_events') \
            .select('id, medication_id, actual_time, dose, custom_note') \
            .eq('user_id', user_id).eq('event_date', today).eq('status', 'TAKEN').execute()
        if not events.data:
            return []
        med_ids = list({e['medication_id'] for e in events.data})
        meds_res = supabase_admin.table('medications') \
            .select('id, name, standard_dose').in_('id', med_ids).execute()
        med_map = {m['id']: m for m in (meds_res.data or [])}
        logs = []
        for e in events.data:
            med = med_map.get(e['medication_id'], {})
            name = med.get('name', '')
            raw_time = e.get('actual_time') or ''
            time_str = raw_time[11:16] if len(raw_time) >= 16 else (e.get('custom_note') or '')
            logs.append({
                'id':   e['id'],
                'name': name,
                'time': time_str,
                'dose': e.get('dose') if e.get('dose') is not None else med.get('standard_dose'),
            })
        return logs
    except Exception as e:
        print(f"Error getting today dose logs: {e}")
        return []


def delete_medication_event(user_id: str, event_id: str) -> bool:
    """Delete a specific medication event belonging to this user."""
    try:
        supabase_admin.table('medication_events').delete() \
            .eq('id', event_id).eq('user_id', user_id).execute()
        return True
    except Exception as e:
        print(f"Error deleting medication event: {e}")
        return False


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
    """Get full reference info for a single medication by name (case-insensitive).

    Prefers enriched records (purpose field populated) over legacy sparse entries.
    Falls back to partial-word matching to handle brand-name format stored names
    like 'Sertraline (Zoloft)' → finds the enriched 'sertraline' record.
    """
    try:
        # Collect all records matching the full name (exact case-insensitive)
        result = supabase_admin.table('medication_reference').select('*').ilike('name', name).limit(5).execute()
        if result.data:
            enriched = [r for r in result.data if r.get('purpose')]
            if enriched:
                return enriched[0]
            # Found records but none are enriched — fall through to partial search

        # Partial-word fallback: handles "sertraline (zoloft)" → searches each word
        # to find the enriched generic-name entry
        import re as _re
        words = [w for w in _re.split(r'[\s()/,]+', name) if len(w) > 3]
        for word in words:
            result = supabase_admin.table('medication_reference').select('*') \
                .ilike('name', f'%{word}%').limit(10).execute()
            if result.data:
                enriched = [r for r in result.data if r.get('purpose')]
                if enriched:
                    return enriched[0]
                # Return unenriched only if no better option exists across all words
                _fallback = result.data[0]

        # Return whatever we found even if unenriched
        return locals().get('_fallback') or (result.data[0] if result.data else None)
    except Exception as e:
        print(f"Error fetching medication info: {e}")
        return None


# ── Module-level interaction table (shared by patient and comparator checks) ──
_DRUG_INTERACTIONS = [
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
        (['amphetamine', 'adderall', 'lisdexamfetamine', 'vyvanse', 'dextroamphetamine'],
         ['selegiline', 'phenelzine', 'tranylcypromine', 'isocarboxazid', 'monoamine oxidase'],
         'serious',
         'Amphetamine + MAOI: hypertensive crisis risk. Absolutely contraindicated.'),

        (['methylphenidate', 'ritalin', 'concerta', 'dexmethylphenidate', 'focalin', 'daytrana'],
         ['selegiline', 'phenelzine', 'tranylcypromine', 'isocarboxazid', 'monoamine oxidase'],
         'serious',
         'Methylphenidate + MAOI: hypertensive crisis risk. Absolutely contraindicated.'),

        # ── Stimulant + stimulant (polypharmacy) ─────────────────────
        (['amphetamine', 'adderall', 'lisdexamfetamine', 'vyvanse', 'dextroamphetamine'],
         ['methylphenidate', 'ritalin', 'concerta', 'dexmethylphenidate', 'focalin', 'daytrana'],
         'moderate',
         'Amphetamine + methylphenidate: concurrent use of two different stimulant classes increases additive cardiovascular load (elevated heart rate, blood pressure, arrhythmia risk). Combination is rarely indicated; requires explicit clinical justification, baseline ECG, and regular cardiovascular monitoring.'),

        # ── Guanfacine + stimulants ───────────────────────────────────
        (['guanfacine', 'intuniv', 'tenex'],
         ['amphetamine', 'adderall', 'lisdexamfetamine', 'vyvanse', 'dextroamphetamine',
          'methylphenidate', 'ritalin', 'concerta', 'dexmethylphenidate', 'focalin'],
         'caution',
         'Guanfacine + stimulant: guanfacine is an alpha-2 agonist that lowers blood pressure and heart rate; stimulants have the opposite cardiovascular effect. While this combination is used in ADHD management, it requires cardiovascular monitoring. Risk is amplified when multiple stimulants are co-prescribed with guanfacine.'),

        # ── CYP3A4 inhibition (non-DHP calcium channel blockers) ─────
        (['verapamil', 'diltiazem'],
         ['carbamazepine', 'tegretol'],
         'serious',
         'Verapamil/diltiazem + carbamazepine: CYP3A4 inhibition by these CCBs raises carbamazepine plasma levels significantly — toxicity risk. Monitor drug levels closely.'),

        (['verapamil', 'diltiazem'],
         ['simvastatin', 'lovastatin'],
         'serious',
         'Verapamil/diltiazem + simvastatin/lovastatin: CYP3A4 inhibition markedly increases statin exposure — myopathy and rhabdomyolysis risk. Switch to pravastatin or rosuvastatin (non-CYP3A4 substrates).'),

        # ── Bradycardia / AV nodal block ─────────────────────────────
        (['verapamil', 'diltiazem'],
         ['metoprolol', 'atenolol', 'carvedilol', 'bisoprolol', 'propranolol', 'beta-blocker'],
         'serious',
         'Non-DHP calcium channel blocker + beta-blocker: additive AV nodal depression — risk of symptomatic bradycardia, high-degree heart block, or cardiac arrest.'),

        # ── Serotonin syndrome (muscle relaxants / herbals) ──────────
        (['cyclobenzaprine', 'flexeril'],
         ['sertraline', 'fluoxetine', 'paroxetine', 'escitalopram', 'citalopram', 'fluvoxamine',
          'venlafaxine', 'duloxetine', 'desvenlafaxine', 'levomilnacipran',
          'selegiline', 'phenelzine', 'tranylcypromine', 'isocarboxazid', 'monoamine oxidase',
          'tramadol', 'linezolid'],
         'serious',
         "Cyclobenzaprine + serotonergic agent: cyclobenzaprine has serotonergic activity — combining with SSRIs, SNRIs, MAOIs, or tramadol raises serotonin syndrome risk."),

        (['st. john', 'hypericum'],
         ['sertraline', 'fluoxetine', 'paroxetine', 'escitalopram', 'citalopram', 'fluvoxamine',
          'venlafaxine', 'duloxetine', 'desvenlafaxine', 'levomilnacipran',
          'bupropion', 'tramadol', 'lithium'],
         'serious',
         "St. John's Wort + serotonergic agent: herbal serotonin reuptake inhibition combined with SSRI, SNRI, or bupropion significantly raises serotonin syndrome risk. Avoid combination."),

        # ── CNS depression (sedating antihistamines) ─────────────────
        (['diphenhydramine', 'benadryl'],
         ['alprazolam', 'clonazepam', 'diazepam', 'lorazepam', 'temazepam', 'zolpidem',
          'eszopiclone', 'zaleplon', 'oxycodone', 'hydrocodone', 'codeine', 'morphine',
          'tramadol', 'quetiapine', 'olanzapine', 'risperidone', 'haloperidol', 'gabapentin',
          'pregabalin'],
         'moderate',
         'Diphenhydramine + CNS depressant: additive sedation and anticholinergic effects. Particular caution in elderly patients (Beers Criteria); may impair psychomotor function.'),

        # ── NSAID + antihypertensives / renal risk ───────────────────
        (['ibuprofen', 'naproxen', 'diclofenac', 'celecoxib', 'nsaid', 'indomethacin'],
         ['lisinopril', 'enalapril', 'ramipril', 'captopril',
          'losartan', 'valsartan', 'irbesartan',
          'hydrochlorothiazide', 'furosemide', 'chlorthalidone'],
         'moderate',
         'NSAID + ACE inhibitor/ARB/diuretic: NSAIDs blunt antihypertensive efficacy and increase acute kidney injury risk, particularly when combined with renin-angiotensin system agents or loop/thiazide diuretics.'),
    ]

def _run_interaction_check(med_names: set) -> list:
    """Check _DRUG_INTERACTIONS against a set of lowercase medication names."""
    alerts = []
    seen = set()
    for aliases_a, aliases_b, severity, warning in _DRUG_INTERACTIONS:
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


def check_medication_interactions(patient_id) -> list:
    """Return interaction alerts for a patient's active medications."""
    try:
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
        return _run_interaction_check(med_names)
    except Exception as e:
        print(f"Error checking medication interactions: {e}")
        return []


def check_interactions_for_names(names: list) -> list:
    """Return interaction alerts for an arbitrary list of medication names."""
    med_names = {n.lower() for n in names if n}
    if len(med_names) < 2:
        return []
    return _run_interaction_check(med_names)

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

def get_suicide_risk_context(user_id: str, days: int = 7, since: str = None) -> list:
    """Return crisis-flagged entries for the last N days (or since a given ISO
    datetime string, whichever is more recent).
    Each item: {source, date, text}.  Empty list = no risk."""
    from claude_api import check_crisis
    rolling_cutoff = (date.today() - timedelta(days=days)).isoformat()
    # Advance resolution date by 1 day so same-day resolved entries don't re-trigger
    if since:
        try:
            from datetime import datetime as _dt
            since_cutoff = (_dt.fromisoformat(since[:19]).date() + timedelta(days=1)).isoformat()
        except Exception:
            since_cutoff = since[:10]
    else:
        since_cutoff = ''
    cutoff = max(rolling_cutoff, since_cutoff)
    results = []
    try:
        ci = supabase_admin.table('checkins').select('notes,checkin_date').eq(
            'user_id', user_id).gte('checkin_date', cutoff).execute()
        for row in (ci.data or []):
            text = row.get('notes') or ''
            if text and check_crisis(text):
                results.append({
                    'source': 'Check-in note',
                    'date': (row.get('checkin_date') or '')[:10],
                    'text': text[:600],
                })
        je = supabase_admin.table('journal_entries').select('content,entry_date').eq(
            'user_id', user_id).gte('entry_date', cutoff).execute()
        for row in (je.data or []):
            text = row.get('content') or ''
            if text and check_crisis(text):
                results.append({
                    'source': 'Journal entry',
                    'date': (row.get('entry_date') or '')[:10],
                    'text': text[:600],
                })
    except Exception as e:
        print(f"get_suicide_risk_context error for user {user_id}: {e}")
    return results


def _has_suicide_risk(user_id: str, days: int = 7, since: str = None) -> bool:
    return bool(get_suicide_risk_context(user_id, days, since=since))


def get_crisis_history(user_id: str) -> list:
    """Return every crisis-flagged entry across all time for a patient, sorted
    newest-first.  Each item: {source, date, text, resolved}.
    `resolved` is True when the entry predates the provider's last resolution."""
    from claude_api import check_crisis
    results = []
    try:
        prof = supabase_admin.table('patient_profiles').select('crisis_resolved_at').eq(
            'user_id', str(user_id)).limit(1).execute()
        resolved_at = None
        if prof.data:
            resolved_at = (prof.data[0].get('crisis_resolved_at') or '')[:10] or None

        ci = supabase_admin.table('checkins').select('notes,checkin_date').eq(
            'user_id', str(user_id)).execute()
        for row in (ci.data or []):
            text = row.get('notes') or ''
            if text and check_crisis(text):
                d = (row.get('checkin_date') or '')[:10]
                results.append({
                    'source': 'Check-in note',
                    'date': d,
                    'text': text[:800],
                    'resolved': bool(resolved_at and d <= resolved_at),
                })

        je = supabase_admin.table('journal_entries').select('content,entry_date').eq(
            'user_id', str(user_id)).execute()
        for row in (je.data or []):
            text = row.get('content') or ''
            if text and check_crisis(text):
                d = (row.get('entry_date') or '')[:10]
                results.append({
                    'source': 'Journal entry',
                    'date': d,
                    'text': text[:800],
                    'resolved': bool(resolved_at and d <= resolved_at),
                })
    except Exception as e:
        print(f"get_crisis_history error for user {user_id}: {e}")
    results.sort(key=lambda x: x['date'], reverse=True)
    return results


def resolve_crisis_risk(patient_id: str) -> bool:
    """Record a provider resolution: stamp crisis_resolved_at = now().
    Returns True on success."""
    try:
        supabase_admin.table('patient_profiles').update(
            {'crisis_resolved_at': datetime.utcnow().isoformat()}
        ).eq('user_id', str(patient_id)).execute()
        return True
    except Exception as e:
        print(f"resolve_crisis_risk error for patient {patient_id}: {e}")
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
            'user_id, current_medications, crisis_resolved_at'
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

            resolved_at = row.get('crisis_resolved_at') or None
            crisis_context = get_suicide_risk_context(uid, since=resolved_at)
            patients.append({
                'patient_id':           uid,
                'full_name':            user['full_name'],
                'email':                user['email'],
                'last_checkin':         last_checkin,
                'latest_summary':       has_summary,
                'current_medications':  meds,
                'suicide_risk':         bool(crisis_context),
                'suicide_risk_context': crisis_context,
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

        # Build normalised recent_checkins list (template-friendly)
        def _norm_checkin(c):
            ext = c.get('extended_data') or {}
            if isinstance(ext, str):
                try:
                    ext = json.loads(ext)
                except Exception:
                    ext = {}
            return {
                'date':         (c.get('checkin_date') or '')[:10],
                'checkin_type': c.get('checkin_type'),
                'time_of_day':  c.get('time_of_day'),
                'mood_score':   c.get('mood_score'),
                'stress_score': c.get('stress_score'),
                'sleep_hours':  c.get('sleep_hours'),
                'notes':        c.get('notes'),
                'extended_data': ext,
            }

        recent_checkins = [_norm_checkin(c) for c in checkins[:20]]
        last_checkin_date = recent_checkins[0]['date'] if recent_checkins else None

        return {
            # Flat identity / summary fields
            'patient_id':          patient_id,
            'full_name':           user['full_name'] if user else 'Unknown',
            'email':               user['email']     if user else '',
            'current_medications': meds,
            'checkins_last_period': len(checkins),
            'last_checkin_date':   last_checkin_date,
            # Nested sub-objects still available for advanced template use
            'profile':          profile,
            'checkins':         checkins,
            'recent_checkins':  recent_checkins,
            'journals':         journals,
            'latest_summary':   latest_summary,
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


def _compute_checkin_scores(mood, stress, sleep_hours, ext, meds):
    """Compute CLAUDE.md composite scores for a single check-in row.
    Returns dict; any field that can't be computed is None."""
    s = {}

    # ── Stim Load ──────────────────────────────────────────────────
    caffeine = ext.get('caffeine_mg')
    tier = 0
    if caffeine is not None:
        c = float(caffeine)
        tier = 2 if c < 100 else 5 if c < 250 else 7 if c < 400 else 9
    stim_meds = 0
    STIMULANT_CATEGORIES = {'stimulant', 'adhd', 'amphetamine'}
    STIMULANT_NAMES = {'adderall', 'vyvanse', 'ritalin', 'concerta', 'dexedrine',
                       'focalin', 'strattera', 'methylphenidate', 'amphetamine'}
    if isinstance(meds, list):
        for m in meds:
            if not isinstance(m, dict) or not m.get('taken'):
                continue
            cat = (m.get('category') or '').lower()
            name = (m.get('name') or '').lower()
            if cat in STIMULANT_CATEGORIES or any(n in name for n in STIMULANT_NAMES):
                stim_meds += 1
    booster = int(ext.get('booster_used') or 0)
    s['stim_load'] = min(tier + stim_meds + booster, 10) if (caffeine is not None or stim_meds or booster) else None

    # ── Stability Score ────────────────────────────────────────────
    energy = ext.get('energy')
    dissoc = ext.get('dissociation')
    if all(v is not None for v in [mood, energy, dissoc, stress]):
        stab = (float(mood) + float(energy) + (10 - float(dissoc)) + (10 - float(stress))) / 4
        s['stability_score'] = round(stab, 2)
        s['mood_distortion'] = round(abs(float(mood) - stab), 2)
    else:
        s['stability_score'] = None
        s['mood_distortion'] = None

    # ── Sleep Disruption Score ─────────────────────────────────────
    sd = 0
    has_sd = False
    if sleep_hours is not None:
        has_sd = True
        if float(sleep_hours) < 6:
            sd += 2
    latency = ext.get('sleep_latency_minutes')
    if latency is not None:
        has_sd = True
        if float(latency) > 45:
            sd += 3
    awakenings = ext.get('night_awakenings')
    if awakenings is not None:
        has_sd = True
        if float(awakenings) >= 2:
            sd += 2
    fae = ext.get('fell_asleep_easily')
    if fae is not None:
        has_sd = True
        if fae is False or str(fae).lower() in ('false', 'no', '0'):
            sd += 3
    s['sleep_disruption'] = min(sd, 10) if has_sd else None

    # ── Nervous System Load ────────────────────────────────────────
    sq = ext.get('sleep_quality')
    sl = s['stim_load']
    if stress is not None and sq is not None and sl is not None:
        s['nervous_system_load'] = round((float(stress) + (10 - float(sq)) + float(sl)) / 3, 2)
    else:
        s['nervous_system_load'] = None

    # ── Crash Risk (sleep + NS load; nutrition omitted when absent) ─
    ns = s['nervous_system_load']
    sd_val = s['sleep_disruption']
    if ns is not None and sd_val is not None:
        s['crash_risk'] = round(min(float(sd_val) * 0.5 + float(ns) * 0.5, 10), 2)
    else:
        s['crash_risk'] = None

    return s


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
        # Computed composite scores
        'stability_score':     _empty_adv(),
        'mood_distortion':     _empty_adv(),
        'sleep_disruption':    _empty_adv(),
        'nervous_system_load': _empty_adv(),
        'stim_load':           _empty_adv(),
        'crash_risk':          {**_empty_adv(), 'high_days': 0},
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
        # composite computed scores
        stability_pairs, mood_distortion_pairs = [], []
        sleep_disruption_pairs, ns_load_pairs = [], []
        crash_risk_pairs, stim_load_pairs = [], []

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
            d = (row.get('checkin_date') or '')[:10]

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

            # ── Composite scores ──────────────────────────────────────
            cs = _compute_checkin_scores(mood, stress, sleep, ext, meds)
            for key, pairs in [
                ('stability_score',   stability_pairs),
                ('mood_distortion',   mood_distortion_pairs),
                ('sleep_disruption',  sleep_disruption_pairs),
                ('nervous_system_load', ns_load_pairs),
                ('crash_risk',        crash_risk_pairs),
                ('stim_load',         stim_load_pairs),
            ]:
                v = cs.get(key)
                if v is not None:
                    pairs.append((d, v))

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

        energy_dates, energy_vals = _unzip(energy_pairs)
        sleep_ts  = _trend_stats(sleep_vals)
        energy_ts = _trend_stats(energy_vals)

        return {
            'user_id':              user_id,
            'date_range':           {'start': start_date, 'end': date.today().isoformat()},
            'total_checkins':       len(data),
            'checkin_count':        len(data),
            'checkins_this_period': len(data),
            'period_days':          days,
            'mood':                 mood_ts,
            'stress':               stress_ts,
            'sleep':  {**sleep_ts,  'daily_hours': sleep_vals,  'dates': sleep_dates},
            'energy': {**energy_ts, 'daily_scores': energy_vals, 'dates': energy_dates},
            'medication_adherence': adherence,
            'average_stability':    _avg(mood_vals),
            # ── Computed composite scores (CLAUDE.md formulas) ──────
            'stability_score':   _make_ts(stability_pairs),
            'mood_distortion':   _make_ts(mood_distortion_pairs),
            'sleep_disruption':  _make_ts(sleep_disruption_pairs),
            'nervous_system_load': _make_ts(ns_load_pairs),
            'stim_load':         _make_ts(stim_load_pairs),
            'crash_risk': {
                **_make_ts(crash_risk_pairs),
                'high_days': sum(1 for _, v in crash_risk_pairs if v >= 7),
            },
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


def get_paired_values(patient_id, var_a, var_b, days=60, _checkins=None):
    """Return (date, val_a, val_b) triples for two VALID_HYPOTHESIS_VARS.

    Pass ``_checkins`` (a pre-fetched row list) to skip the DB round-trip.
    This is used by find_unexpected_pattern to avoid N+1 queries.

    Variable → storage location mapping:
      mood   → mood_score column   (fallback: stability_score)
      stress → stress_score column
      sleep  → sleep_hours column
      energy → extended_data->>'energy'
      focus  → extended_data->>'focus'
    """
    # col = database column; ext = key inside extended_data JSONB (None if not needed)
    VAR_MAP = {
        'mood':              ('mood_score',   None),
        'stress':            ('stress_score', None),
        'sleep':             ('sleep_hours',  None),
        'energy':            (None,           'energy'),
        'focus':             (None,           'focus'),
        'irritability':      (None,           'irritability'),
        'motivation':        (None,           'motivation'),
        'perceived_stress':  (None,           'perceived_stress'),
        'alcohol':           (None,           'alcohol_units'),
        'exercise':          (None,           'exercise_minutes'),
        'sunlight':          (None,           'sunlight_hours'),
        'screen_time':       (None,           'screen_time_hours'),
        'social_quality':    (None,           'social_quality'),
        'workload_friction': (None,           'workload_friction'),
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
        checkins = _checkins if _checkins is not None else get_checkins(patient_id, days)
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


def compute_correlation_evidence(pairs, user_direction, var_a=None, var_b=None):
    """Compute correlation evidence between two variables.

    Tests all three directions (positive, negative, null) simultaneously and
    returns the ranked result shape that renderResult() in hypothesis-tester.js
    expects:
      ranked            – list of {rank, direction, statement, evidence}
      winner            – the highest-evidence direction object
      divergence        – bool: winner != user_direction
      divergence_message – plain-English explanation when diverged
      n                 – number of matched check-in pairs used
      r                 – Pearson correlation coefficient
      p_value           – stringified p-value threshold ('0.001'…'0.20')
    """
    DIR_PHRASES = {
        'positive': 'helps / increases',
        'negative': 'hurts / decreases',
        'null':     'has no effect on',
    }
    la = _CORRELATION_VAR_LABELS.get(var_a, var_a or 'Variable A') if var_a else 'Variable A'
    lb = _CORRELATION_VAR_LABELS.get(var_b, var_b or 'Variable B') if var_b else 'Variable B'
    n  = len(pairs) if pairs else 0

    _empty_winner = {
        'direction': 'null',
        'statement': f'{la} {DIR_PHRASES["null"]} {lb}',
        'evidence':  0.0,
        'rank':      1,
    }

    if not pairs or n < 3:
        return {
            'ranked':            [_empty_winner],
            'winner':            _empty_winner,
            'divergence':        user_direction != 'null',
            'divergence_message': 'Not enough matched data to determine a direction.',
            'n':                 n,
            'r':                 None,
            'p_value':           None,
        }

    r, p = _pearson([pair[1] for pair in pairs], [pair[2] for pair in pairs])
    if r is None:
        return {
            'ranked':            [_empty_winner],
            'winner':            _empty_winner,
            'divergence':        user_direction != 'null',
            'divergence_message': 'Insufficient data variance to determine direction.',
            'n':                 n,
            'r':                 0,
            'p_value':           None,
        }

    # Evidence per direction: scales with how well the observed r supports each claim.
    # positive: r > 0 supports this; negative: r < 0; null: |r| ≈ 0.
    pos_ev   = round(min(max(0.0,  r) * (n / 10.0), 1.0), 3)
    neg_ev   = round(min(max(0.0, -r) * (n / 10.0), 1.0), 3)
    null_ev  = round(min((1.0 - abs(r)) * (n / 20.0), 1.0), 3)

    directions = [
        {'direction': 'positive', 'statement': f'{la} {DIR_PHRASES["positive"]} {lb}', 'evidence': pos_ev},
        {'direction': 'negative', 'statement': f'{la} {DIR_PHRASES["negative"]} {lb}', 'evidence': neg_ev},
        {'direction': 'null',     'statement': f'{la} {DIR_PHRASES["null"]} {lb}',     'evidence': null_ev},
    ]
    directions.sort(key=lambda x: x['evidence'], reverse=True)
    for i, d in enumerate(directions):
        d['rank'] = i + 1

    winner = directions[0]
    divergence = (winner['direction'] != user_direction)

    if divergence:
        user_stmt = f'{la} {DIR_PHRASES[user_direction]} {lb}'
        divergence_message = (
            f'You predicted "{user_stmt}" — but the data points to '
            f'"{winner["statement"]}" (r={round(r, 3)}, n={n}).'
        )
    else:
        divergence_message = ''

    return {
        'ranked':            directions,
        'winner':            winner,
        'divergence':        divergence,
        'divergence_message': divergence_message,
        'n':                 n,
        'r':                 round(r, 3),
        'p_value':           str(p) if p is not None else None,
    }


# ═══════════════════════════════════════════════════════════════════════════
# HYPOTHESIS TESTING
# ═══════════════════════════════════════════════════════════════════════════

def save_hypothesis_result(patient_id, var_a, var_b, user_direction, result):
    """Save hypothesis test result.

    The result blob is augmented with variable_a, variable_b, user_direction, and
    result_direction so that get_hypothesis_history() can reconstruct the flat
    shape renderHistory() expects without a schema migration.
    """
    try:
        winner_dir = (result.get('winner') or {}).get('direction', 'null')
        result_to_store = {
            **result,
            'variable_a':     var_a,
            'variable_b':     var_b,
            'user_direction':  user_direction,
            'result_direction': winner_dir,
        }
        hyp_data = {
            'user_id':    str(patient_id),
            'hypothesis': f"{var_a} -> {var_b}",
            'tested_at':  datetime.utcnow().isoformat(),
            'result':     json.dumps(result_to_store),
            'created_at': datetime.utcnow().isoformat(),
        }
        response = supabase_admin.table('user_hypotheses').insert(hyp_data).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]['id']
        return None
    except Exception as e:
        print(f"Error saving hypothesis result: {e}")
        return None


def get_hypothesis_history(patient_id, limit=20):
    """Get hypothesis test history.

    Returns rows with the flat shape renderHistory() in hypothesis-tester.js
    expects: variable_a, variable_b, user_direction, result_direction,
    divergence, created_at.  Fields are extracted from the embedded JSON blob;
    legacy rows that pre-date the enriched blob fall back gracefully.
    """
    try:
        response = (
            supabase_admin.table('user_hypotheses')
            .select('*')
            .eq('user_id', str(patient_id))
            .order('tested_at', desc=True)
            .limit(limit)
            .execute()
        )
        rows = response.data if response.data else []

        normalized = []
        for h in rows:
            blob = {}
            raw = h.get('result')
            if raw:
                try:
                    blob = json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    pass

            # Prefer fields embedded in the blob; fall back to parsing hypothesis string
            var_a = blob.get('variable_a')
            var_b = blob.get('variable_b')
            if not var_a or not var_b:
                hyp_text = h.get('hypothesis', '')
                if '->' in hyp_text:
                    parts = hyp_text.split('->', 1)
                    var_a = parts[0].strip()
                    var_b = parts[1].strip()

            result_dir = blob.get('result_direction') or (blob.get('winner') or {}).get('direction', 'unknown')

            normalized.append({
                'id':              h.get('id'),
                'variable_a':      var_a,
                'variable_b':      var_b,
                'user_direction':  blob.get('user_direction', 'unknown'),
                'result_direction': result_dir,
                'divergence':      blob.get('divergence', False),
                'created_at':      h.get('tested_at') or h.get('created_at', ''),
            })

        return normalized
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


def _pearson(vals_a, vals_b):
    """Pearson r + approximate p-value for two equal-length numeric lists."""
    n = len(vals_a)
    if n < 7:
        return None, None
    mean_a = sum(vals_a) / n
    mean_b = sum(vals_b) / n
    std_a = (sum((v - mean_a) ** 2 for v in vals_a) / n) ** 0.5
    std_b = (sum((v - mean_b) ** 2 for v in vals_b) / n) ** 0.5
    if std_a == 0 or std_b == 0:
        return None, None
    cov = sum((vals_a[i] - mean_a) * (vals_b[i] - mean_b) for i in range(n)) / n
    r = max(-1.0, min(1.0, cov / (std_a * std_b)))
    # Approximate p-value via t-statistic → normal table
    if abs(r) >= 1.0:
        return r, 0.001
    t = r * math.sqrt(n - 2) / math.sqrt(1 - r ** 2)
    at = abs(t)
    if at > 3.5:    p = 0.001
    elif at > 2.58: p = 0.01
    elif at > 1.96: p = 0.05
    elif at > 1.64: p = 0.10
    else:           p = 0.20
    return r, p


def find_unexpected_pattern(patient_id, days=30):
    """Find the strongest unexamined correlation among all variable pairs.

    Returns the shape renderUnexpected() in hypothesis-tester.js expects:
      {var_a, var_b, r, p_value, n, message}
    """
    VAR_LABELS = _CORRELATION_VAR_LABELS
    VARS = _CORRELATION_VARS

    try:
        tested = set()
        for va, vb in get_tested_pairs(patient_id):
            tested.add((va, vb))
            tested.add((vb, va))

        # Fetch checkins once; pass to get_paired_values to avoid up-to-91
        # redundant DB round-trips (one per variable pair).
        all_checkins = get_checkins(patient_id, days)

        best = None
        best_score = 0.0

        for i, va in enumerate(VARS):
            for vb in VARS[i + 1:]:
                if (va, vb) in tested:
                    continue
                pairs = get_paired_values(patient_id, va, vb, days, _checkins=all_checkins)
                if len(pairs) < 7:
                    continue
                r, p = _pearson([p[1] for p in pairs], [p[2] for p in pairs])
                if r is None or abs(r) < 0.3 or p > 0.10:
                    continue
                score = abs(r) * (1 - p)
                if score > best_score:
                    best_score = score
                    la, lb = VAR_LABELS[va], VAR_LABELS[vb]
                    if r > 0:
                        msg = f"When your {la} is higher, your {lb} tends to be higher too."
                    else:
                        msg = f"When your {la} is higher, your {lb} tends to be lower."
                    best = {
                        'var_a':   va,
                        'var_b':   vb,
                        'r':       round(r, 2),
                        'p_value': str(p),
                        'n':       len(pairs),
                        'message': msg,
                    }

        return best
    except Exception as e:
        print(f"Error finding unexpected pattern: {e}")
        return None


def find_top_patterns(patient_id, days=30, limit=5):
    """Return the top N significant correlations across all variable pairs.

    Each item: {var_a, var_b, r, p_value, n, message, strength, is_new}
    is_new = True when the user hasn't run a hypothesis test on this pair yet.
    Sorted by |r| descending.
    """
    VAR_LABELS = _CORRELATION_VAR_LABELS
    VARS = _CORRELATION_VARS

    try:
        tested = set()
        for va, vb in get_tested_pairs(patient_id):
            tested.add((va, vb))
            tested.add((vb, va))

        all_checkins = get_checkins(patient_id, days)
        candidates = []

        for i, va in enumerate(VARS):
            for vb in VARS[i + 1:]:
                pairs = get_paired_values(patient_id, va, vb, days, _checkins=all_checkins)
                if len(pairs) < 7:
                    continue
                r, p = _pearson([pair[1] for pair in pairs], [pair[2] for pair in pairs])
                if r is None or abs(r) < 0.3 or p > 0.10:
                    continue

                la, lb = VAR_LABELS[va], VAR_LABELS[vb]
                abs_r = abs(r)

                if abs_r >= 0.6:
                    strength = 'strong'
                    msg = (
                        f"{la} and {lb} move together strongly — when one rises, the other tends to follow."
                        if r > 0 else
                        f"{la} and {lb} pull in opposite directions — a consistent inverse relationship."
                    )
                elif abs_r >= 0.4:
                    strength = 'moderate'
                    msg = (
                        f"Days with higher {la} tend to bring higher {lb}."
                        if r > 0 else
                        f"Higher {la} days tend to see lower {lb}."
                    )
                else:
                    strength = 'notable'
                    msg = (
                        f"A subtle link: {la} and {lb} tend to rise together."
                        if r > 0 else
                        f"A subtle link: higher {la} tends to coincide with lower {lb}."
                    )

                candidates.append({
                    'var_a':    va,
                    'var_b':    vb,
                    'r':        round(r, 2),
                    'p_value':  str(p),
                    'n':        len(pairs),
                    'message':  msg,
                    'strength': strength,
                    'is_new':   (va, vb) not in tested,
                })

        candidates.sort(key=lambda x: abs(x['r']), reverse=True)
        return candidates[:limit]
    except Exception as e:
        print(f"Error finding top patterns: {e}")
        return []


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


# ═══════════════════════════════════════════════════════════════════════════
# PROVIDER APPOINTMENTS
# ═══════════════════════════════════════════════════════════════════════════

def create_provider_appointment(provider_id: str, patient_id: str, period_days: int = 30) -> dict | None:
    """Create a new appointment session and return the row."""
    try:
        row = {
            'id':            str(uuid.uuid4()),
            'provider_id':   str(provider_id),
            'patient_id':    str(patient_id),
            'status':        'active',
            'period_days':   period_days,
            'started_at':    datetime.utcnow().isoformat(),
            'guided_qa':     json.dumps([]),
            'notes':         '',
            'care_plan_changes': '',
            'actions':       json.dumps([]),
            'next_appointment_date':  None,
            'next_appointment_notes': '',
            'created_at':    datetime.utcnow().isoformat(),
            'updated_at':    datetime.utcnow().isoformat(),
        }
        resp = supabase_admin.table('provider_appointments').insert(row).execute()
        return resp.data[0] if resp.data else None
    except Exception as e:
        print(f"Error creating appointment: {e}")
        return None


def get_provider_appointment(appt_id: str, provider_id: str) -> dict | None:
    """Fetch a single appointment, verifying it belongs to this provider."""
    try:
        resp = supabase_admin.table('provider_appointments').select('*').eq(
            'id', appt_id).eq('provider_id', str(provider_id)).limit(1).execute()
        if not resp.data:
            return None
        row = resp.data[0]
        # Deserialize JSONB fields
        for field in ('guided_qa', 'actions'):
            if isinstance(row.get(field), str):
                try:
                    row[field] = json.loads(row[field])
                except Exception:
                    row[field] = []
        return row
    except Exception as e:
        print(f"Error fetching appointment: {e}")
        return None


def get_patient_appointments(provider_id: str, patient_id: str) -> list:
    """Return all appointments for a patient (newest first)."""
    try:
        resp = supabase_admin.table('provider_appointments').select('*').eq(
            'provider_id', str(provider_id)).eq(
            'patient_id', str(patient_id)).order(
            'started_at', desc=True).execute()
        rows = resp.data or []
        for row in rows:
            for field in ('guided_qa', 'actions'):
                if isinstance(row.get(field), str):
                    try:
                        row[field] = json.loads(row[field])
                    except Exception:
                        row[field] = []
        return rows
    except Exception as e:
        print(f"Error fetching patient appointments: {e}")
        return []


def update_provider_appointment(appt_id: str, provider_id: str, updates: dict) -> bool:
    """Patch an appointment row. Only allowed fields are applied."""
    ALLOWED = {
        'status', 'period_days', 'guided_qa', 'notes',
        'care_plan_changes', 'actions',
        'next_appointment_date', 'next_appointment_notes', 'completed_at',
    }
    payload = {k: v for k, v in updates.items() if k in ALLOWED}
    if not payload:
        return False
    payload['updated_at'] = datetime.utcnow().isoformat()
    # Serialize JSON fields
    for field in ('guided_qa', 'actions'):
        if field in payload and not isinstance(payload[field], str):
            payload[field] = json.dumps(payload[field])
    try:
        supabase_admin.table('provider_appointments').update(payload).eq(
            'id', appt_id).eq('provider_id', str(provider_id)).execute()
        return True
    except Exception as e:
        print(f"Error updating appointment: {e}")
        return False


def get_between_session_brief(patient_id: str, provider_id: str) -> dict:
    """Return a structured between-session brief for a patient.

    Covers the period since the most recent *completed* appointment for this
    provider–patient pair, compared against the 90-day window before that
    appointment.  Template-driven — no AI call.

    Returns a dict with keys:
        since_date          – ISO date string (appointment date, or 90d ago if none)
        days_in_period      – int
        checkin_count       – int
        last_checkin        – ISO date or None
        days_since_checkin  – int or None
        crisis_active       – bool
        mood_avg            – float or None
        mood_baseline       – float or None
        mood_dir            – 'up'|'down'|'stable'|None
        mood_delta          – float or None
        stress_avg          – float or None
        stress_baseline     – float or None
        stress_dir          – 'up'|'down'|'stable'|None
        stress_delta        – float or None
        sleep_avg           – float or None
        sleep_baseline      – float or None
        sleep_dir           – 'up'|'down'|'stable'|None
        sleep_delta         – float or None
        med_doses_logged    – int (total dose events in period)
        med_days_logged     – int (unique days with any dose)
        journal_count       – int (shared journal entries in period)
        journal_themes      – list[str] (up to 3 brief theme labels extracted from entry text)
        has_appointment     – bool (whether a prior completed appointment was found)
        appointment_date    – ISO date or None
    """
    today = date.today()

    # ── Find most recent completed appointment ────────────────────────────────
    try:
        ar = supabase_admin.table('provider_appointments').select(
            'id, started_at, completed_at, status, notes, care_plan_changes, actions'
        ).eq('provider_id', str(provider_id)).eq(
            'patient_id', str(patient_id)
        ).eq('status', 'completed').order('started_at', desc=True).limit(1).execute()
        appt = ar.data[0] if ar.data else None
    except Exception:
        appt = None

    if appt:
        # Use completed_at if available, otherwise fall back to started_at
        appt_date_str = (appt.get('completed_at') or appt.get('started_at') or '')[:10]
        try:
            since_date = date.fromisoformat(appt_date_str)
        except Exception:
            since_date = today - timedelta(days=90)
        has_appointment = True
        appointment_date = appt_date_str
        # Extract session notes written by the provider at the last appointment
        session_notes      = (appt.get('notes') or '').strip() or None
        care_plan_changes  = (appt.get('care_plan_changes') or '').strip() or None
        # Deserialise action items (stored as JSON string or list)
        raw_actions = appt.get('actions') or []
        if isinstance(raw_actions, str):
            try:
                raw_actions = json.loads(raw_actions)
            except Exception:
                raw_actions = []
        session_actions = [a for a in raw_actions if isinstance(a, dict) and a.get('text')]
    else:
        since_date = today - timedelta(days=90)
        has_appointment = False
        appointment_date = None
        session_notes     = None
        care_plan_changes = None
        session_actions   = []

    since_iso = since_date.isoformat()
    days_in_period = (today - since_date).days

    # ── Baseline window: 90 days before the since_date ───────────────────────
    baseline_start = (since_date - timedelta(days=90)).isoformat()

    # ── Check-ins in period ───────────────────────────────────────────────────
    try:
        ci_resp = supabase_admin.table('checkins').select(
            'checkin_date, mood_score, stress_score, sleep_hours'
        ).eq('user_id', str(patient_id)).gte('checkin_date', since_iso).execute()
        period_rows = ci_resp.data or []
    except Exception:
        period_rows = []

    # ── Baseline check-ins ────────────────────────────────────────────────────
    try:
        bl_resp = supabase_admin.table('checkins').select(
            'checkin_date, mood_score, stress_score, sleep_hours'
        ).eq('user_id', str(patient_id)).gte(
            'checkin_date', baseline_start
        ).lt('checkin_date', since_iso).execute()
        baseline_rows = bl_resp.data or []
    except Exception:
        baseline_rows = []

    def _avg(rows, field):
        vals = [r[field] for r in rows if r.get(field) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    def _delta_dir(cur, base):
        if cur is None or base is None:
            return None, None
        d = round(cur - base, 1)
        if abs(d) < 0.5:
            return d, 'stable'
        return d, 'up' if d > 0 else 'down'

    mood_avg     = _avg(period_rows, 'mood_score')
    stress_avg   = _avg(period_rows, 'stress_score')
    sleep_avg    = _avg(period_rows, 'sleep_hours')
    mood_base    = _avg(baseline_rows, 'mood_score')
    stress_base  = _avg(baseline_rows, 'stress_score')
    sleep_base   = _avg(baseline_rows, 'sleep_hours')

    mood_delta,   mood_dir   = _delta_dir(mood_avg,   mood_base)
    stress_delta, stress_dir = _delta_dir(stress_avg, stress_base)
    sleep_delta,  sleep_dir  = _delta_dir(sleep_avg,  sleep_base)

    # ── Last check-in ─────────────────────────────────────────────────────────
    last_checkin = None
    days_since_checkin = None
    if period_rows:
        dates = sorted([r['checkin_date'][:10] for r in period_rows], reverse=True)
        last_checkin = dates[0]
        try:
            days_since_checkin = (today - date.fromisoformat(last_checkin)).days
        except Exception:
            pass

    # ── Crisis flag ───────────────────────────────────────────────────────────
    try:
        prof_resp = supabase_admin.table('patient_profiles').select(
            'crisis_resolved_at'
        ).eq('user_id', str(patient_id)).limit(1).execute()
        prof = prof_resp.data[0] if prof_resp.data else {}
        resolved_at = prof.get('crisis_resolved_at')
        crisis_context = get_suicide_risk_context(patient_id, since=resolved_at)
        crisis_active = bool(crisis_context)
    except Exception:
        crisis_active = False

    # ── Medication dose events in period ──────────────────────────────────────
    try:
        med_resp = supabase_admin.table('medication_events').select(
            'event_date'
        ).eq('user_id', str(patient_id)).gte('event_date', since_iso).execute()
        med_rows = med_resp.data or []
        med_doses_logged = len(med_rows)
        med_days_logged  = len({r['event_date'][:10] for r in med_rows if r.get('event_date')})
    except Exception:
        med_doses_logged = 0
        med_days_logged  = 0

    # ── Shared journal entries in period ──────────────────────────────────────
    try:
        jrn_resp = supabase_admin.table('journal_entries').select(
            'entry_date, content'
        ).eq('user_id', str(patient_id)).eq('share_with_provider', True).gte(
            'entry_date', since_iso
        ).order('entry_date', desc=True).limit(10).execute()
        journal_rows = jrn_resp.data or []
        journal_count = len(journal_rows)
    except Exception:
        journal_rows  = []
        journal_count = 0

    # Extract simple keyword themes from journal text (no AI — frequency of
    # common emotion words serves as a lightweight signal for the brief)
    THEME_WORDS = {
        'anxious': 'anxiety',  'anxiety': 'anxiety',  'worried': 'anxiety',
        'stress':  'stress',   'stressed': 'stress',  'overwhelm': 'overwhelm',
        'sad':     'low mood', 'depressed': 'low mood', 'hopeless': 'low mood',
        'tired':   'fatigue',  'exhausted': 'fatigue', 'fatigue': 'fatigue',
        'sleep':   'sleep concerns', 'insomnia': 'sleep concerns',
        'focus':   'focus/attention', 'distracted': 'focus/attention', 'adhd': 'focus/attention',
        'work':    'work', 'job': 'work', 'career': 'work',
        'family':  'family', 'relationship': 'relationships', 'social': 'social',
        'medication': 'medication', 'meds': 'medication', 'dose': 'medication',
    }
    theme_counts: dict = {}
    for entry in journal_rows:
        text = (entry.get('content') or '').lower()
        for word, theme in THEME_WORDS.items():
            if word in text:
                theme_counts[theme] = theme_counts.get(theme, 0) + 1
    journal_themes = [t for t, _ in sorted(theme_counts.items(), key=lambda x: -x[1])[:3]]

    return {
        'since_date':         since_iso,
        'days_in_period':     days_in_period,
        'checkin_count':      len(period_rows),
        'last_checkin':       last_checkin,
        'days_since_checkin': days_since_checkin,
        'crisis_active':      crisis_active,
        'mood_avg':           mood_avg,
        'mood_baseline':      mood_base,
        'mood_dir':           mood_dir,
        'mood_delta':         mood_delta,
        'stress_avg':         stress_avg,
        'stress_baseline':    stress_base,
        'stress_dir':         stress_dir,
        'stress_delta':       stress_delta,
        'sleep_avg':          sleep_avg,
        'sleep_baseline':     sleep_base,
        'sleep_dir':          sleep_dir,
        'sleep_delta':        sleep_delta,
        'med_doses_logged':   med_doses_logged,
        'med_days_logged':    med_days_logged,
        'journal_count':      journal_count,
        'journal_themes':     journal_themes,
        'has_appointment':    has_appointment,
        'appointment_date':   appointment_date,
        # Session notes from the last completed appointment (feed-forward context)
        'session_notes':      session_notes,
        'care_plan_changes':  care_plan_changes,
        'session_actions':    session_actions,
    }


def _baseline_delta(recent_vals, historical_vals, min_n=5):
    """Compute (recent_avg, delta, direction) for a metric.

    recent_vals:     values from the last 14 days
    historical_vals: values from days 15–90 (the prior baseline window)
    min_n:           minimum observations required in each window to show a delta

    Returns:
        recent_avg  – rounded average of recent window, or None if no data
        delta       – recent_avg minus historical_avg, rounded to 1dp, or None
        direction   – 'up' | 'down' | 'stable' | None
    """
    recent = [x for x in recent_vals if x is not None]
    historical = [x for x in historical_vals if x is not None]
    recent_avg = round(sum(recent) / len(recent), 1) if recent else None
    if len(recent) < min_n or len(historical) < min_n:
        return recent_avg, None, None
    hist_avg = sum(historical) / len(historical)
    delta = round((sum(recent) / len(recent)) - hist_avg, 1)
    if abs(delta) < 0.5:
        direction = 'stable'
    elif delta > 0:
        direction = 'up'
    else:
        direction = 'down'
    return recent_avg, delta, direction


def get_provider_patients_with_stats(provider_id: str) -> list:
    """Enhanced version of get_provider_patients with mood avg and adherence for the dashboard grid.

    For each patient, fetches 90 days of check-in data in a single query and
    partitions it into:
      - recent   : last 14 days  (aligns with default appointment review window)
      - historical: days 15–90   (personal baseline for comparison)

    Computes delta and direction for mood, stress, and sleep so the dashboard
    can display deviation-from-baseline rather than raw averages.
    """
    base = get_provider_patients(provider_id)
    today = date.today()
    cutoff_90d = (today - timedelta(days=90)).isoformat()
    cutoff_14d = (today - timedelta(days=14)).isoformat()

    # ── Bulk-fetch care team roles for this provider ──────────────────────────
    # Maps patient_id → care team role string so we can tag each patient card
    # without an extra per-patient query.
    _THERAPY_ROLES = {'therapist', 'counselor', 'coach'}
    try:
        ct_resp = supabase_admin.table('care_team_members').select(
            'patient_id, role'
        ).eq('provider_id', str(provider_id)).eq('status', 'active').execute()
        ct_roles = {str(r['patient_id']): r['role'] for r in (ct_resp.data or [])}
    except Exception:
        ct_roles = {}

    for p in base:
        uid = p['patient_id']

        # ── Fetch 90 days of core metrics in one query ────────────────────────
        try:
            ci = supabase_admin.table('checkins').select(
                'checkin_date, mood_score, stress_score, sleep_hours'
            ).eq('user_id', uid).gte('checkin_date', cutoff_90d).execute()
            rows = ci.data or []
        except Exception:
            rows = []

        # Partition into recent (≤14d) and historical (15–90d)
        recent_mood, hist_mood = [], []
        recent_stress, hist_stress = [], []
        recent_sleep, hist_sleep = [], []

        for r in rows:
            d = (r.get('checkin_date') or '')[:10]
            is_recent = d >= cutoff_14d
            bucket_mood   = recent_mood   if is_recent else hist_mood
            bucket_stress = recent_stress if is_recent else hist_stress
            bucket_sleep  = recent_sleep  if is_recent else hist_sleep
            if r.get('mood_score')  is not None: bucket_mood.append(r['mood_score'])
            if r.get('stress_score') is not None: bucket_stress.append(r['stress_score'])
            if r.get('sleep_hours')  is not None: bucket_sleep.append(r['sleep_hours'])

        # Compute deltas (min 5 observations per window to show a delta)
        p['mood_recent'],   p['mood_delta'],   p['mood_dir']   = _baseline_delta(recent_mood,   hist_mood)
        p['stress_recent'], p['stress_delta'], p['stress_dir'] = _baseline_delta(recent_stress, hist_stress)
        p['sleep_recent'],  p['sleep_delta'],  p['sleep_dir']  = _baseline_delta(recent_sleep,  hist_sleep)

        # Keep legacy key so existing template references don't break
        p['mood_avg_30d']     = p['mood_recent']
        p['checkin_count_30d'] = len(recent_mood)

        # ── Provider role for this patient (care team or legacy) ─────────────
        ct_role = ct_roles.get(str(uid))
        p['provider_role'] = ct_role or 'psychiatrist'
        p['is_care_team']  = ct_role is not None
        # For therapy roles, fetch behavioral signals (used in brief drawer)
        if ct_role in _THERAPY_ROLES:
            p['behavioral'] = get_behavioral_data(uid, days=14)
        else:
            p['behavioral'] = None

        # ── Days since last check-in ──────────────────────────────────────────
        if p.get('last_checkin'):
            try:
                p['days_since_checkin'] = (today - date.fromisoformat(p['last_checkin'])).days
            except Exception:
                p['days_since_checkin'] = None
        else:
            p['days_since_checkin'] = None

        # ── Last appointment date ─────────────────────────────────────────────
        try:
            ar = supabase_admin.table('provider_appointments').select(
                'id, started_at, status').eq('provider_id', str(provider_id)).eq(
                'patient_id', uid).order('started_at', desc=True).limit(1).execute()
            if ar.data:
                p['last_appointment'] = ar.data[0]['started_at'][:10]
                p['last_appointment_status'] = ar.data[0]['status']
                p['last_appointment_id'] = ar.data[0]['id']
            else:
                p['last_appointment'] = None
                p['last_appointment_status'] = None
                p['last_appointment_id'] = None
        except Exception:
            p['last_appointment'] = None
            p['last_appointment_status'] = None
            p['last_appointment_id'] = None

    # ── Care flag counts — unresolved flags from other providers ─────────────
    all_patient_ids = [str(p.get('patient_id') or p.get('id', '')) for p in base]
    flag_counts = get_unresolved_flag_counts(provider_id, all_patient_ids)
    for p in base:
        pid = str(p.get('patient_id') or p.get('id', ''))
        p['flag_count'] = flag_counts.get(pid, 0)

    # ── Urgency sort ──────────────────────────────────────────────────────────
    # Tier 0 (most urgent): active crisis flag
    # Tier 1: mood declining meaningfully OR mood is acutely low
    # Tier 2: stress rising into high territory OR no check-in in >7 days
    # Tier 3: everything else (stable / monitoring)
    def _urgency_tier(p):
        if p.get('suicide_risk'):
            return 0
        mood_alert = (
            (p.get('mood_dir') == 'down' and p.get('mood_delta') is not None and p['mood_delta'] <= -1.0)
            or (p.get('mood_recent') is not None and p['mood_recent'] < 5)
        )
        if mood_alert:
            return 1
        stress_alert = (
            p.get('stress_dir') == 'up' and p.get('stress_recent') is not None and p['stress_recent'] > 6
        )
        inactive = p.get('days_since_checkin') is not None and p['days_since_checkin'] > 7
        if stress_alert or inactive:
            return 2
        return 3

    def _sort_key(p):
        tier = _urgency_tier(p)
        # Within tier, prioritise longest gap first (None gaps sort last)
        dsc = p.get('days_since_checkin')
        gap = -(dsc if dsc is not None else -1)  # negate so larger gaps sort first
        name = (p.get('full_name') or '').lower()
        return (tier, gap, name)

    base.sort(key=_sort_key)

    # Stamp urgency tier on each patient dict so template can use it
    for p in base:
        p['urgency_tier'] = _urgency_tier(p)

    return base


def get_behavioral_data(patient_id: str, days: int = 30) -> dict:
    """Return behavioral signal averages used by therapy-lens provider views.

    Pulls advanced check-in fields for the period and aggregates:
      social_avg       – avg social quality (0–10), or None
      workload_avg     – avg workload friction (0–10), or None
      exercise_avg     – avg exercise minutes per day, or None
      coping_days      – {breathing, meditation, movement: count of days each}
      coping_any_days  – distinct days with at least one coping activity
      advanced_days    – days with any advanced field logged
    """
    _empty = {
        'social_avg': None, 'workload_avg': None, 'exercise_avg': None,
        'coping_days': {'breathing': 0, 'meditation': 0, 'movement': 0},
        'coping_any_days': 0, 'advanced_days': 0,
    }
    try:
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        ci = supabase_admin.table('checkins').select(
            'extended_data'
        ).eq('user_id', str(patient_id)).gte('checkin_date', cutoff).execute()
        rows = ci.data or []
    except Exception:
        return _empty

    social_vals, workload_vals, exercise_vals = [], [], []
    coping_counts = {'breathing': 0, 'meditation': 0, 'movement': 0}
    coping_any = 0
    advanced = 0

    for r in rows:
        ext = r.get('extended_data') or {}
        if isinstance(ext, str):
            try:
                ext = json.loads(ext)
            except Exception:
                ext = {}
        is_advanced = False
        if ext.get('social_quality') is not None:
            social_vals.append(float(ext['social_quality']))
            is_advanced = True
        if ext.get('workload_friction') is not None:
            workload_vals.append(float(ext['workload_friction']))
            is_advanced = True
        if ext.get('exercise_minutes') is not None:
            exercise_vals.append(float(ext['exercise_minutes']))
            is_advanced = True
        has_coping_today = False
        coping = ext.get('coping') or {}
        for k in coping_counts:
            if coping.get(k):
                coping_counts[k] += 1
                has_coping_today = True
        if has_coping_today:
            coping_any += 1
            is_advanced = True
        if is_advanced:
            advanced += 1

    def _avg(v): return round(sum(v) / len(v), 1) if v else None

    return {
        'social_avg':      _avg(social_vals),
        'workload_avg':    _avg(workload_vals),
        'exercise_avg':    _avg(exercise_vals),
        'coping_days':     coping_counts,
        'coping_any_days': coping_any,
        'advanced_days':   advanced,
    }


def get_care_team_member_role(provider_id: str, patient_id: str):
    """Returns the role string for an active care team relationship, or None."""
    try:
        res = supabase_admin.table('care_team_members').select('role').eq(
            'patient_id', str(patient_id)).eq(
            'provider_id', str(provider_id)).eq(
            'status', 'active').limit(1).execute()
        if res.data:
            return res.data[0].get('role')
        return None
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════
# Care Team Network
# ═══════════════════════════════════════════════════════════════════════════

_DEFAULT_PERMISSIONS = {
    'journals_raw':        True,
    'journals_themes':     True,
    'mood_stress_sleep':   True,
    'medication_data':     True,
    'system_scores':       True,
    'advanced_data':       True,
    'cross_provider_flags': True,   # Phase 4: see flags posted by other providers
}

_ROLE_LABELS = {
    'psychiatrist':    'Psychiatrist',
    'therapist':       'Therapist',
    'counselor':       'Counselor',
    'coach':           'Coach',
    'sleep_specialist':'Sleep Specialist',
    'other':           'Provider',
}


def send_care_team_request(provider_id: str, patient_email: str, role: str = 'psychiatrist',
                           message: str = None) -> dict:
    """
    Provider sends a connection request to a patient by email.
    Returns {'ok': True, 'member_id': ...} or {'ok': False, 'error': '...'}.
    """
    role = role if role in _ROLE_LABELS else 'other'

    # Look up patient by email
    try:
        pr = supabase_admin.table('profiles').select('id, full_name, role').eq(
            'email', patient_email.lower().strip()).single().execute()
        if not pr.data or pr.data.get('role') != 'patient':
            return {'ok': False, 'error': 'No patient account found with that email.'}
        patient_id = pr.data['id']
    except Exception:
        return {'ok': False, 'error': 'No patient account found with that email.'}

    # Don't allow a provider to connect to themselves
    if str(patient_id) == str(provider_id):
        return {'ok': False, 'error': 'Cannot connect to your own account.'}

    # Check for existing relationship
    try:
        existing = supabase_admin.table('care_team_members').select('id, status').eq(
            'patient_id', str(patient_id)).eq('provider_id', str(provider_id)).execute()
        if existing.data:
            rec = existing.data[0]
            if rec['status'] == 'active':
                return {'ok': False, 'error': 'You already have an active connection with this patient.'}
            if rec['status'] == 'pending':
                return {'ok': False, 'error': 'A connection request is already pending for this patient.'}
            if rec['status'] == 'revoked':
                # Re-activate as a new pending request
                supabase_admin.table('care_team_members').update({
                    'status': 'pending',
                    'role': role,
                    'request_message': message,
                    'requested_by': 'provider',
                    'requested_at': datetime.utcnow().isoformat(),
                    'approved_at': None,
                    'revoked_at': None,
                }).eq('id', rec['id']).execute()
                return {'ok': True, 'member_id': rec['id'], 'patient_name': pr.data.get('full_name')}
    except Exception:
        pass

    # Create new pending request
    try:
        insert_data = {
            'patient_id': str(patient_id),
            'provider_id': str(provider_id),
            'role': role,
            'status': 'pending',
            'data_permissions': _DEFAULT_PERMISSIONS,
            'requested_by': 'provider',
            'request_message': message,
        }
        res = supabase_admin.table('care_team_members').insert(insert_data).execute()
        member_id = res.data[0]['id'] if res.data else None
        return {'ok': True, 'member_id': member_id, 'patient_name': pr.data.get('full_name')}
    except Exception as e:
        return {'ok': False, 'error': f'Could not create request: {e}'}


def send_patient_care_request(patient_id: str, provider_email: str,
                              role: str = 'psychiatrist', message: str = None) -> dict:
    """
    Patient invites a provider by email to join their care team.
    Returns {'ok': True, 'member_id': ..., 'provider_name': ...} or {'ok': False, 'error': '...'}.
    """
    role = role if role in _ROLE_LABELS else 'other'

    # Look up provider by email
    try:
        pr = supabase_admin.table('profiles').select('id, full_name, role').eq(
            'email', provider_email.lower().strip()).single().execute()
        if not pr.data or pr.data.get('role') != 'provider':
            return {'ok': False, 'error': 'No provider account found with that email.'}
        provider_id = pr.data['id']
    except Exception:
        return {'ok': False, 'error': 'No provider account found with that email.'}

    if str(provider_id) == str(patient_id):
        return {'ok': False, 'error': 'Cannot connect to your own account.'}

    # Check for existing relationship
    try:
        existing = supabase_admin.table('care_team_members').select('id, status').eq(
            'patient_id', str(patient_id)).eq('provider_id', str(provider_id)).execute()
        if existing.data:
            rec = existing.data[0]
            if rec['status'] == 'active':
                return {'ok': False, 'error': 'This provider is already on your care team.'}
            if rec['status'] == 'pending':
                return {'ok': False, 'error': 'A connection request is already pending for this provider.'}
            if rec['status'] == 'revoked':
                supabase_admin.table('care_team_members').update({
                    'status': 'pending',
                    'role': role,
                    'request_message': message,
                    'requested_by': 'patient',
                    'requested_at': datetime.utcnow().isoformat(),
                    'approved_at': None,
                    'revoked_at': None,
                }).eq('id', rec['id']).execute()
                return {'ok': True, 'member_id': rec['id'], 'provider_name': pr.data.get('full_name')}
    except Exception:
        pass

    try:
        res = supabase_admin.table('care_team_members').insert({
            'patient_id':      str(patient_id),
            'provider_id':     str(provider_id),
            'role':            role,
            'status':          'pending',
            'data_permissions': _DEFAULT_PERMISSIONS,
            'requested_by':    'patient',
            'request_message': message,
        }).execute()
        member_id = res.data[0]['id'] if res.data else None
        return {'ok': True, 'member_id': member_id, 'provider_name': pr.data.get('full_name')}
    except Exception as e:
        return {'ok': False, 'error': f'Could not send invite: {e}'}


def get_pending_care_requests(patient_id: str) -> list:
    """
    Returns all pending care team requests for a patient, with provider details.
    """
    try:
        res = supabase_admin.table('care_team_members').select(
            'id, role, requested_by, request_message, requested_at, provider_id'
        ).eq('patient_id', str(patient_id)).eq('status', 'pending').execute()
        if not res.data:
            return []

        requests = []
        for rec in res.data:
            # Fetch provider name
            try:
                pr = supabase_admin.table('profiles').select(
                    'full_name, email, provider_type').eq('id', rec['provider_id']).single().execute()
                provider = pr.data or {}
            except Exception:
                provider = {}
            requests.append({
                'id':              rec['id'],
                'provider_id':     rec['provider_id'],
                'provider_name':   provider.get('full_name') or 'Unknown Provider',
                'provider_email':  provider.get('email', ''),
                'role':            rec['role'],
                'role_label':      _ROLE_LABELS.get(rec['role'], 'Provider'),
                'requested_by':    rec['requested_by'],
                'request_message': rec.get('request_message'),
                'requested_at':    rec['requested_at'],
            })
        return requests
    except Exception:
        return []


def approve_care_request(patient_id: str, member_id: str,
                         permissions: dict = None) -> dict:
    """
    Patient approves a pending care team request.
    Optionally overrides data_permissions.
    Returns {'ok': True} or {'ok': False, 'error': '...'}.
    """
    try:
        # Verify the record belongs to this patient and is pending
        rec = supabase_admin.table('care_team_members').select('id, status').eq(
            'id', str(member_id)).eq('patient_id', str(patient_id)).eq(
            'status', 'pending').execute()
        if not rec.data:
            return {'ok': False, 'error': 'Request not found or already actioned.'}

        update = {
            'status': 'active',
            'approved_at': datetime.utcnow().isoformat(),
        }
        if permissions:
            # Merge with defaults — patient can only restrict, not grant new keys
            merged = dict(_DEFAULT_PERMISSIONS)
            merged.update({k: bool(v) for k, v in permissions.items() if k in _DEFAULT_PERMISSIONS})
            update['data_permissions'] = merged

        supabase_admin.table('care_team_members').update(update).eq('id', str(member_id)).execute()
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def deny_care_request(patient_id: str, member_id: str) -> dict:
    """
    Patient denies a pending care team request (sets status to revoked).
    """
    try:
        rec = supabase_admin.table('care_team_members').select('id, status').eq(
            'id', str(member_id)).eq('patient_id', str(patient_id)).eq(
            'status', 'pending').execute()
        if not rec.data:
            return {'ok': False, 'error': 'Request not found.'}
        supabase_admin.table('care_team_members').update({
            'status': 'revoked',
            'revoked_at': datetime.utcnow().isoformat(),
        }).eq('id', str(member_id)).execute()
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def revoke_care_member(patient_id: str, member_id: str) -> dict:
    """
    Patient revokes an active provider's access.
    """
    try:
        rec = supabase_admin.table('care_team_members').select('id, status').eq(
            'id', str(member_id)).eq('patient_id', str(patient_id)).eq(
            'status', 'active').execute()
        if not rec.data:
            return {'ok': False, 'error': 'Active relationship not found.'}
        supabase_admin.table('care_team_members').update({
            'status': 'revoked',
            'revoked_at': datetime.utcnow().isoformat(),
        }).eq('id', str(member_id)).execute()
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def get_patient_care_team(patient_id: str) -> dict:
    """
    Returns active care team members and pending requests for a patient.
    Shape: {'active': [...], 'pending': [...]}
    """
    try:
        res = supabase_admin.table('care_team_members').select(
            'id, role, status, data_permissions, requested_at, approved_at, provider_id, requested_by, request_message'
        ).eq('patient_id', str(patient_id)).in_('status', ['active', 'pending']).execute()
        records = res.data or []
    except Exception:
        return {'active': [], 'pending': []}

    active, pending = [], []
    for rec in records:
        try:
            pr = supabase_admin.table('profiles').select(
                'full_name, email, provider_type').eq('id', rec['provider_id']).single().execute()
            provider = pr.data or {}
        except Exception:
            provider = {}

        entry = {
            'id':              rec['id'],
            'provider_id':     rec['provider_id'],
            'provider_name':   provider.get('full_name') or 'Unknown Provider',
            'provider_email':  provider.get('email', ''),
            'role':            rec['role'],
            'role_label':      _ROLE_LABELS.get(rec['role'], 'Provider'),
            'permissions':     rec.get('data_permissions') or _DEFAULT_PERMISSIONS,
            'approved_at':     rec.get('approved_at'),
            'requested_at':    rec.get('requested_at'),
            'requested_by':    rec.get('requested_by', 'provider'),
            'request_message': rec.get('request_message'),
        }
        if rec['status'] == 'active':
            active.append(entry)
        else:
            pending.append(entry)

    return {'active': active, 'pending': pending}


def get_care_team_permissions(patient_id: str, provider_id: str) -> dict | None:
    """
    Returns data_permissions dict for a specific provider-patient pair,
    or None if no active relationship exists.
    """
    try:
        res = supabase_admin.table('care_team_members').select(
            'data_permissions').eq('patient_id', str(patient_id)).eq(
            'provider_id', str(provider_id)).eq('status', 'active').execute()
        if res.data:
            return res.data[0].get('data_permissions') or _DEFAULT_PERMISSIONS
        return None
    except Exception:
        return None


def provider_has_care_access(provider_id: str, patient_id: str) -> bool:
    """
    Returns True if an active care team relationship exists between provider and patient.
    Used to authorise provider access to patient data.
    """
    return get_care_team_permissions(patient_id, provider_id) is not None


def get_provider_outbound_requests(provider_id: str) -> list:
    """
    Returns all pending outbound connection requests sent by this provider.
    """
    try:
        res = supabase_admin.table('care_team_members').select(
            'id, role, status, requested_at, patient_id'
        ).eq('provider_id', str(provider_id)).eq('status', 'pending').execute()
        if not res.data:
            return []

        out = []
        for rec in res.data:
            try:
                pr = supabase_admin.table('profiles').select(
                    'full_name, email').eq('id', rec['patient_id']).single().execute()
                patient = pr.data or {}
            except Exception:
                patient = {}
            out.append({
                'id':           rec['id'],
                'patient_id':   rec['patient_id'],
                'patient_name': patient.get('full_name') or 'Unknown Patient',
                'patient_email':patient.get('email', ''),
                'role':         rec['role'],
                'role_label':   _ROLE_LABELS.get(rec['role'], 'Provider'),
                'requested_at': rec['requested_at'],
            })
        return out
    except Exception:
        return []


def update_care_permissions(patient_id: str, member_id: str, permissions: dict) -> dict:
    """
    Patient updates per-provider data permissions for an active relationship.
    """
    try:
        rec = supabase_admin.table('care_team_members').select('id').eq(
            'id', str(member_id)).eq('patient_id', str(patient_id)).eq(
            'status', 'active').execute()
        if not rec.data:
            return {'ok': False, 'error': 'Active relationship not found.'}
        merged = dict(_DEFAULT_PERMISSIONS)
        merged.update({k: bool(v) for k, v in permissions.items() if k in _DEFAULT_PERMISSIONS})
        supabase_admin.table('care_team_members').update(
            {'data_permissions': merged}).eq('id', str(member_id)).execute()
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# Care Flags — cross-provider clinical observations (Phase 4)
# ═══════════════════════════════════════════════════════════════════════════

_FLAG_TYPES = {'observation', 'concern', 'progress', 'coordination_needed'}


def create_care_flag(author_provider_id: str, patient_id: str,
                     flag_type: str, body: str,
                     visible_to: list = None) -> dict:
    """
    Provider posts a flag on a patient record.

    visible_to: optional list of provider_id UUIDs that can see this flag.
                None / empty = visible to all active care team members who have
                cross_provider_flags permission (existing behaviour).

    Returns {'ok': True, 'flag': {...}} or {'ok': False, 'error': '...'}.
    """
    if flag_type not in _FLAG_TYPES:
        return {'ok': False, 'error': f'Invalid flag_type. Must be one of: {", ".join(sorted(_FLAG_TYPES))}'}
    body = (body or '').strip()
    if not (10 <= len(body) <= 1000):
        return {'ok': False, 'error': 'Flag body must be between 10 and 1000 characters.'}

    # Verify the author has access to this patient.
    if not provider_has_care_access(author_provider_id, patient_id):
        # Also allow legacy single-provider relationship
        try:
            legacy = supabase_admin.table('patient_profiles').select('id').eq(
                'patient_id', str(patient_id)).eq('provider_id', str(author_provider_id)).execute()
            if not legacy.data:
                return {'ok': False, 'error': 'No active relationship with this patient.'}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    # Normalise visible_to: None or empty list means no restriction
    visible_to_value = [str(pid) for pid in visible_to] if visible_to else None

    try:
        insert_data = {
            'patient_id':         str(patient_id),
            'author_provider_id': str(author_provider_id),
            'flag_type':          flag_type,
            'body':               body,
            'visibility':         'care_team',
        }
        if visible_to_value is not None:
            insert_data['visible_to_providers'] = json.dumps(visible_to_value)
        res = supabase_admin.table('care_flags').insert(insert_data).execute()
        flag_row = res.data[0] if res.data else {}
    except Exception as e:
        return {'ok': False, 'error': str(e)}

    # ── Notify other active care team providers ───────────────────────────────
    try:
        import email_utils as _eu
        # Fetch all active care team members for this patient
        ct = supabase_admin.table('care_team_members').select(
            'provider_id, role, data_permissions'
        ).eq('patient_id', str(patient_id)).eq('status', 'active').execute()

        # Fetch patient name for the email
        pr = supabase_admin.table('profiles').select(
            'full_name').eq('id', str(patient_id)).limit(1).execute()
        patient_name = pr.data[0]['full_name'] if pr.data else 'your patient'

        # Fetch author name + role
        auth_pr = supabase_admin.table('profiles').select(
            'full_name').eq('id', str(author_provider_id)).limit(1).execute()
        author_name = auth_pr.data[0]['full_name'] if auth_pr.data else 'A provider'
        author_ct_role = next(
            (r['role'] for r in (ct.data or []) if r['provider_id'] == str(author_provider_id)),
            'psychiatrist'
        )
        author_role_label = _ROLE_LABELS.get(author_ct_role, 'Provider')

        for member in (ct.data or []):
            pid = member['provider_id']
            if pid == str(author_provider_id):
                continue   # don't notify yourself
            # Respect explicit visibility list if set
            if visible_to_value is not None and pid not in visible_to_value:
                continue
            perms = member.get('data_permissions') or {}
            if isinstance(perms, str):
                try:
                    perms = json.loads(perms)
                except Exception:
                    perms = {}
            if not perms.get('cross_provider_flags', True):
                continue   # patient revoked flag visibility for this provider

            # Fetch provider email + name
            prov_pr = supabase_admin.table('profiles').select(
                'email, full_name').eq('id', pid).limit(1).execute()
            if not prov_pr.data:
                continue
            prov = prov_pr.data[0]
            try:
                _eu.send_care_flag_notification(
                    to_email=prov['email'],
                    to_name=prov['full_name'],
                    author_name=author_name,
                    author_role=author_role_label,
                    patient_name=patient_name,
                    flag_type=flag_type,
                    flag_body=body,
                )
            except Exception as email_err:
                print(f"care flag email failed for {prov['email']}: {email_err}")
    except Exception as notify_err:
        print(f"care flag notify error (non-fatal): {notify_err}")

    return {'ok': True, 'flag': flag_row}


def get_care_flags_for_provider(viewing_provider_id: str, patient_id: str) -> list:
    """
    Returns all unresolved care flags on patient_id that are visible to
    viewing_provider_id. A flag is visible when:
      - The viewing provider has an active care relationship with the patient, AND
      - That relationship's data_permissions includes cross_provider_flags: true, AND
      - The flag was NOT authored by the viewing provider themselves
        (you already know what you wrote).

    Each flag dict includes author_role derived from care_team_members.
    """
    # Check viewing provider's permission
    perms = get_care_team_permissions(patient_id, viewing_provider_id)
    if perms is None:
        # Allow if viewing provider is the legacy single-provider
        try:
            leg = supabase_admin.table('patient_profiles').select('id').eq(
                'patient_id', str(patient_id)).eq(
                'provider_id', str(viewing_provider_id)).execute()
            if not leg.data:
                return []
            # Legacy providers can see flags but we treat cross_provider_flags as True for them
        except Exception:
            return []
        cross_ok = True
    else:
        cross_ok = perms.get('cross_provider_flags', True)

    if not cross_ok:
        return []

    try:
        res = supabase_admin.table('care_flags').select(
            'id, flag_type, body, created_at, author_provider_id, visible_to_providers'
        ).eq('patient_id', str(patient_id)).is_('resolved_at', 'null').neq(
            'author_provider_id', str(viewing_provider_id)
        ).order('created_at', desc=True).execute()

        # Filter out flags where viewing_provider_id is not in the visible_to_providers list
        raw_flags = res.data or []
        flags = []
        for f in raw_flags:
            vtp = f.get('visible_to_providers')
            if isinstance(vtp, str):
                try:
                    vtp = json.loads(vtp)
                except Exception:
                    vtp = None
            if vtp is not None and str(viewing_provider_id) not in vtp:
                continue
            flags.append(f)

        # Annotate with author name + role
        if flags:
            author_ids = list({f['author_provider_id'] for f in flags})
            # Fetch author profile names
            prof_res = supabase_admin.table('profiles').select('id, full_name').in_(
                'id', author_ids).execute()
            name_map = {r['id']: r['full_name'] for r in (prof_res.data or [])}

            # Fetch author roles from care_team_members for this patient
            role_res = supabase_admin.table('care_team_members').select(
                'provider_id, role'
            ).eq('patient_id', str(patient_id)).eq('status', 'active').in_(
                'provider_id', author_ids).execute()
            role_map = {r['provider_id']: r['role'] for r in (role_res.data or [])}

            for f in flags:
                aid = f['author_provider_id']
                f['author_name'] = name_map.get(aid, 'Provider')
                f['author_role'] = _ROLE_LABELS.get(role_map.get(aid, ''), 'Provider')

        return flags
    except Exception as e:
        print(f"get_care_flags_for_provider error: {e}")
        return []


def get_my_care_flags(author_provider_id: str, patient_id: str) -> list:
    """
    Returns unresolved flags THIS provider posted on a patient — shown in
    the brief drawer so a provider can see/manage their own flags.
    """
    try:
        res = supabase_admin.table('care_flags').select(
            'id, flag_type, body, created_at'
        ).eq('patient_id', str(patient_id)).eq(
            'author_provider_id', str(author_provider_id)
        ).is_('resolved_at', 'null').order('created_at', desc=True).execute()
        return res.data or []
    except Exception as e:
        print(f"get_my_care_flags error: {e}")
        return []


def resolve_care_flag(flag_id: str, resolving_provider_id: str, patient_id: str) -> dict:
    """
    Mark a flag as resolved. Any active provider on the care team can resolve.
    Returns {'ok': True} or {'ok': False, 'error': '...'}.
    """
    # Confirm the flag belongs to this patient and is unresolved
    try:
        rec = supabase_admin.table('care_flags').select('id, resolved_at').eq(
            'id', str(flag_id)).eq('patient_id', str(patient_id)).execute()
        if not rec.data:
            return {'ok': False, 'error': 'Flag not found.'}
        if rec.data[0].get('resolved_at'):
            return {'ok': False, 'error': 'Flag already resolved.'}

        supabase_admin.table('care_flags').update({
            'resolved_at': datetime.utcnow().isoformat(),
            'resolved_by': str(resolving_provider_id),
        }).eq('id', str(flag_id)).execute()
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def get_unresolved_flag_counts(provider_id: str, patient_ids: list) -> dict:
    """
    Bulk-fetch unresolved flag counts for a list of patients, visible to provider.
    Returns {patient_id: count} dict. Used to stamp patient cards on the dashboard.
    Only counts flags NOT authored by the viewing provider.
    """
    if not patient_ids:
        return {}
    try:
        # Fetch all unresolved flags for these patients not authored by this provider
        res = supabase_admin.table('care_flags').select(
            'patient_id'
        ).in_('patient_id', [str(p) for p in patient_ids]).is_(
            'resolved_at', 'null'
        ).neq('author_provider_id', str(provider_id)).execute()

        counts: dict = {}
        for row in (res.data or []):
            pid = row['patient_id']
            counts[pid] = counts.get(pid, 0) + 1
        return counts
    except Exception as e:
        print(f"get_unresolved_flag_counts error: {e}")
        return {}


def get_care_team_for_provider(provider_id: str, patient_id: str) -> list:
    """
    Returns active care team members for a patient (excluding the requesting provider).
    Used to populate the visibility selector when posting a flag.
    Each entry: {provider_id, provider_name, role, role_label}
    """
    try:
        res = supabase_admin.table('care_team_members').select(
            'provider_id, role'
        ).eq('patient_id', str(patient_id)).eq('status', 'active').neq(
            'provider_id', str(provider_id)
        ).execute()
        members = res.data or []
        if not members:
            return []
        provider_ids = [m['provider_id'] for m in members]
        prof_res = supabase_admin.table('profiles').select(
            'id, full_name').in_('id', provider_ids).execute()
        name_map = {r['id']: r['full_name'] for r in (prof_res.data or [])}
        return [
            {
                'provider_id':  m['provider_id'],
                'provider_name': name_map.get(m['provider_id'], 'Provider'),
                'role':          m['role'],
                'role_label':    _ROLE_LABELS.get(m['role'], 'Provider'),
            }
            for m in members
        ]
    except Exception as e:
        print(f"get_care_team_for_provider error: {e}")
        return []


def create_flag_response(flag_id: str, author_provider_id: str,
                         patient_id: str, body: str) -> dict:
    """
    Post a response to a care flag. The responding provider must have access
    to the patient and the flag must be unresolved.
    Returns {'ok': True, 'response': {...}} or {'ok': False, 'error': '...'}.
    """
    body = (body or '').strip()
    if not (5 <= len(body) <= 500):
        return {'ok': False, 'error': 'Response must be between 5 and 500 characters.'}

    # Verify flag exists, belongs to patient, and is unresolved
    try:
        flag_rec = supabase_admin.table('care_flags').select(
            'id, resolved_at, visible_to_providers'
        ).eq('id', str(flag_id)).eq('patient_id', str(patient_id)).execute()
        if not flag_rec.data:
            return {'ok': False, 'error': 'Flag not found.'}
        if flag_rec.data[0].get('resolved_at'):
            return {'ok': False, 'error': 'Cannot respond to a resolved flag.'}

        # Verify responder has access to this patient
        if not provider_has_care_access(author_provider_id, patient_id):
            try:
                leg = supabase_admin.table('patient_profiles').select('id').eq(
                    'patient_id', str(patient_id)).eq(
                    'provider_id', str(author_provider_id)).execute()
                if not leg.data:
                    return {'ok': False, 'error': 'No active relationship with this patient.'}
            except Exception as e:
                return {'ok': False, 'error': str(e)}

        res = supabase_admin.table('care_flag_responses').insert({
            'flag_id':            str(flag_id),
            'patient_id':         str(patient_id),
            'author_provider_id': str(author_provider_id),
            'body':               body,
        }).execute()
        return {'ok': True, 'response': res.data[0] if res.data else {}}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def get_flag_responses(flag_id: str, patient_id: str) -> list:
    """
    Returns all responses for a flag, annotated with author name + role.
    """
    try:
        res = supabase_admin.table('care_flag_responses').select(
            'id, author_provider_id, body, created_at'
        ).eq('flag_id', str(flag_id)).eq(
            'patient_id', str(patient_id)
        ).order('created_at').execute()
        responses = res.data or []
        if not responses:
            return []
        author_ids = list({r['author_provider_id'] for r in responses})
        prof_res = supabase_admin.table('profiles').select(
            'id, full_name').in_('id', author_ids).execute()
        name_map = {r['id']: r['full_name'] for r in (prof_res.data or [])}
        role_res = supabase_admin.table('care_team_members').select(
            'provider_id, role'
        ).eq('patient_id', str(patient_id)).eq('status', 'active').in_(
            'provider_id', author_ids).execute()
        role_map = {r['provider_id']: r['role'] for r in (role_res.data or [])}
        for r in responses:
            aid = r['author_provider_id']
            r['author_name'] = name_map.get(aid, 'Provider')
            r['author_role'] = _ROLE_LABELS.get(role_map.get(aid, ''), 'Provider')
        return responses
    except Exception as e:
        print(f"get_flag_responses error: {e}")
        return []


def add_medication_by_psychiatrist(provider_id: str, patient_id: str,
                                   name: str, category: str, dose: float,
                                   dose_unit: str = 'mg',
                                   scheduled_times: list = None,
                                   date_started: str = None,
                                   frequency: str = None) -> dict:
    """
    Psychiatrist adds a medication to a patient's record.
    Enforces that the provider's role for this patient is 'psychiatrist'.
    Returns {'ok': True, 'medication': {...}} or {'ok': False, 'error': '...'}.
    """
    role = get_care_team_member_role(provider_id, patient_id)
    if role != 'psychiatrist':
        # Also allow legacy single-provider (assumed psychiatrist)
        try:
            leg = supabase_admin.table('patient_profiles').select('id').eq(
                'patient_id', str(patient_id)).eq(
                'provider_id', str(provider_id)).execute()
            if not leg.data:
                return {'ok': False, 'error': 'Only a psychiatrist can add medications.'}
        except Exception:
            return {'ok': False, 'error': 'Only a psychiatrist can add medications.'}

    name = (name or '').strip()
    if not name:
        return {'ok': False, 'error': 'Medication name is required.'}
    if not category:
        return {'ok': False, 'error': 'Category is required.'}
    try:
        dose = float(dose)
        if dose <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return {'ok': False, 'error': 'Dose must be a positive number.'}

    med = create_medication(
        user_id=str(patient_id),
        name=name,
        category=category,
        standard_dose=dose,
        dose_unit=dose_unit or 'mg',
        scheduled_times=scheduled_times or [],
        date_started=date_started or None,
        frequency=frequency or None,
    )
    if med is None:
        return {'ok': False, 'error': 'Failed to add medication — please try again.'}
    return {'ok': True, 'medication': med}
