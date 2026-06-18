import math
import os
import re
import json
import logging
from datetime import datetime, timedelta, date
from supabase import create_client, Client
import uuid

logger = logging.getLogger(__name__)


class DataUnavailableError(Exception):
    """Raised when a clinically load-bearing READ fails.

    The data layer must never let a failed read masquerade as genuinely
    empty data: an empty list/dict returned from an exception handler is
    indistinguishable from "no rows", and a provider summary built on it
    looks authoritative while silently omitting a safety signal, substance
    flag, or symptom pattern. Clinical read functions raise this instead of
    returning an empty default so the failure is visible to callers, which
    surface an explicit "data unavailable" state rather than a clean,
    misleading empty section.

    Carries the original exception via implicit chaining (``__cause__`` /
    ``__context__``) when raised inside an ``except`` block.
    """

    def __init__(self, message, *, source=None):
        super().__init__(message)
        # Name of the data-layer function whose read failed, for logging /
        # the section marker rendered to the provider.
        self.source = source


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
        logger.exception(f"✗ Database connection failed: {e}")


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
        logger.exception(f"Error getting user by email: {e}")
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
        logger.exception(f"Error getting user by id: {e}")
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
        logger.exception(f"Error getting patient profile: {e}")
        return None


def update_patient_profile(user_id, **kwargs):
    """Upsert patient profile (creates row if none exists yet)."""
    try:
        data = {**kwargs, 'user_id': str(user_id)}
        supabase_admin.table('patient_profiles').upsert(data, on_conflict='user_id').execute()
        return True
    except Exception as e:
        logger.exception(f"Error updating patient profile: {e}")
        return False


def set_patient_sms_consent(user_id, consent: bool) -> bool:
    """Persist a patient's SMS opt-in consent and the time it was given.

    Written as an isolated upsert so that a missing sms_consent column (e.g.
    before migrations/add_sms_consent.sql has been applied) cannot break the
    phone-number / profile save that happens in the same request. Returns True
    on success, False if the columns aren't present yet (logged as a warning,
    not an exception).
    """
    try:
        data = {'user_id': str(user_id), 'sms_consent': bool(consent)}
        if consent:
            from datetime import datetime, timezone
            data['sms_consent_at'] = datetime.now(timezone.utc).isoformat()
        supabase_admin.table('patient_profiles').upsert(data, on_conflict='user_id').execute()
        return True
    except Exception as e:
        logger.warning(
            f"Could not persist SMS consent for {user_id} "
            f"(has migrations/add_sms_consent.sql been applied?): {e}"
        )
        return False


def get_patient_population_flags(patient_user_id: str) -> dict:
    """Return the population_flags JSONB dict for a patient.

    Used by transcript_engine.extract_features() to apply population-aware
    crisis escalation modifiers. Returns an empty dict if the column is absent,
    null, or the profile row doesn't exist yet.

    Supported flag keys (all boolean):
        adolescent, older_adult, veteran, prior_self_harm, serious_mental_illness,
        substance_use_disorder
    """
    try:
        response = supabase_admin.table('patient_profiles') \
            .select('population_flags') \
            .eq('user_id', str(patient_user_id)) \
            .execute()
        if response.data:
            return response.data[0].get('population_flags') or {}
        return {}
    except Exception as e:
        logger.exception(f"Error getting population flags for {patient_user_id}: {e}")
        raise DataUnavailableError(f"Error getting population flags for {patient_user_id}", source="get_patient_population_flags")


def set_patient_population_flags(patient_user_id: str, flags: dict) -> bool:
    """Upsert the population_flags JSONB column for a patient profile.

    Merges the provided flags into any existing flags rather than replacing
    the entire object, so callers can set individual keys without clobbering
    others. Pass a key with value False/None to clear that flag.

    Example:
        set_patient_population_flags(uid, {'veteran': True})
        set_patient_population_flags(uid, {'veteran': False})  # clears it
    """
    try:
        # Fetch current flags first to merge
        current = get_patient_population_flags(patient_user_id)
        merged = {**current, **flags}
        # Remove keys explicitly set to False/None to keep the dict clean
        merged = {k: v for k, v in merged.items() if v}
        supabase_admin.table('patient_profiles').upsert(
            {'user_id': str(patient_user_id), 'population_flags': merged},
            on_conflict='user_id',
        ).execute()
        return True
    except Exception as e:
        logger.exception(f"Error setting population flags for {patient_user_id}: {e}")
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
        logger.exception(f"Error assigning patient to provider: {e}")
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
        logger.exception(f"get_patients_needing_checkin_reminder error: {e}")
        raise DataUnavailableError(f"get_patients_needing_checkin_reminder error", source="get_patients_needing_checkin_reminder")


def mark_reminder_sent(user_id: str) -> None:
    """Stamp last_reminder_sent_at on the patient profile after sending a reminder."""
    try:
        supabase_admin.table('patient_profiles').update({
            'last_reminder_sent_at': datetime.utcnow().isoformat(),
        }).eq('user_id', str(user_id)).execute()
    except Exception as e:
        logger.exception(f"mark_reminder_sent error: {e}")


def set_checkin_reminders_enabled(user_id: str, enabled: bool) -> bool:
    """Patient opts in or out of check-in reminder emails."""
    try:
        supabase_admin.table('patient_profiles').update({
            'checkin_reminders_enabled': bool(enabled),
        }).eq('user_id', str(user_id)).execute()
        return True
    except Exception as e:
        logger.exception(f"set_checkin_reminders_enabled error: {e}")
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
        logger.exception(f"Error creating checkin: {e}")
        raise  # re-raise so app.py can surface the real error


def update_checkin_insights(checkin_id, insights_text):
    """Update check-in with AI insights."""
    try:
        supabase_admin.table('checkins').update({'ai_insights': insights_text}).eq('id', str(checkin_id)).execute()
        return True
    except Exception as e:
        logger.exception(f"Error updating checkin insights: {e}")
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
        logger.debug(f"Error getting checkin baseline: {e}")
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
        logger.exception(f"Error getting checkins: {e}")
        raise DataUnavailableError(f"Error getting checkins", source="get_checkins")


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
        logger.exception(f"Error getting checkins in range: {e}")
        raise DataUnavailableError(f"Error getting checkins in range", source="get_checkins_in_range")


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
        logger.exception(f"Error getting journals in range: {e}")
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
        logger.exception(f"Error getting checkin streak: {e}")
        raise DataUnavailableError(f"Error getting checkin streak", source="get_checkin_streak")


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
            'entry_type': entry_type,
            'ai_analysis': ai_analysis,
            'is_crisis': entry_type == 'crisis',
            'share_with_provider': bool(share_with_provider),
            'created_at': datetime.utcnow().isoformat()
        }
        
        response = supabase_admin.table('journal_entries').insert(journal_data).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]['id']
        return None
    except Exception as e:
        logger.exception(f"Error creating journal: {e}")
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
        logger.exception(f"Error getting journals: {e}")
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
        logger.exception(f"Error creating summary: {e}")
        return None


def get_summary_by_id(summary_id: str, patient_id: str | None = None) -> dict | None:
    """
    Fetch a single summary row by ID.
    If patient_id is provided, verifies ownership (provider access pattern uses
    patient_id to scope the lookup).
    Returns None if not found.
    """
    try:
        q = supabase_admin.table('summaries').select('*').eq('id', str(summary_id))
        if patient_id:
            q = q.eq('user_id', str(patient_id))
        result = q.single().execute()
        row = result.data
        if row and not row.get('summary_text'):
            row['summary_text'] = row.get('content', '')
        return row
    except Exception as e:
        logger.exception(f'[db] get_summary_by_id error: {e}')
        raise DataUnavailableError(f'[db] get_summary_by_id error', source="get_summary_by_id")


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
        logger.exception(f"Error getting summaries: {e}")
        return []


def delete_summary(patient_id, summary_id):
    """Delete a summary, enforcing ownership so patients can only delete their own."""
    try:
        supabase_admin.table('summaries').delete().eq('id', str(summary_id)).eq('user_id', str(patient_id)).execute()
        return True
    except Exception as e:
        logger.exception(f"Error deleting summary: {e}")
        return False


def get_latest_summary(patient_id):
    """Get the most recent summary."""
    try:
        response = supabase_admin.table('summaries').select('*').eq('user_id', str(patient_id)).order('summary_date', desc=True).limit(1).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]
        return None
    except Exception as e:
        logger.exception(f"Error getting latest summary: {e}")
        raise DataUnavailableError(f"Error getting latest summary", source="get_latest_summary")


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
        logger.exception(f"Error creating medication: {e}")
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
        logger.exception(f"Error fetching medications: {e}")
        raise DataUnavailableError(f"Error fetching medications", source="get_user_medications")

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
        logger.exception(f"Error finding/creating profile medication: {e}")
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
        logger.exception(f"Error getting today dose logs: {e}")
        return []


def delete_medication_event(user_id: str, event_id: str) -> bool:
    """Delete a specific medication event belonging to this user."""
    try:
        supabase_admin.table('medication_events').delete() \
            .eq('id', event_id).eq('user_id', user_id).execute()
        return True
    except Exception as e:
        logger.exception(f"Error deleting medication event: {e}")
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
        logger.exception(f"Error logging medication event: {e}")
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
        logger.exception(f"Error fetching medication events: {e}")
        raise DataUnavailableError(f"Error fetching medication events", source="get_medication_events")

def get_medication_names() -> list:
    """Return a sorted list of all medication names from the reference table."""
    try:
        result = supabase_admin.table('medication_reference').select('name').execute()
        return sorted({row['name'] for row in result.data}) if result.data else []
    except Exception as e:
        logger.exception(f"Error fetching medication names: {e}")
        raise DataUnavailableError(f"Error fetching medication names", source="get_medication_names")

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
        logger.exception(f"Error fetching medication info: {e}")
        raise DataUnavailableError(f"Error fetching medication info", source="get_medication_info")


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
        logger.exception(f"Error checking medication interactions: {e}")
        raise DataUnavailableError(f"Error checking medication interactions", source="check_medication_interactions")


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
        logger.exception(f"Error searching medication reference: {e}")
        raise DataUnavailableError(f"Error searching medication reference", source="search_medication_reference")


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
        logger.exception(f"get_suicide_risk_context error for user {user_id}: {e}")
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
        logger.exception(f"get_crisis_history error for user {user_id}: {e}")
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
        logger.exception(f"resolve_crisis_risk error for patient {patient_id}: {e}")
        raise DataUnavailableError(f"resolve_crisis_risk error for patient {patient_id}", source="resolve_crisis_risk")


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
        logger.exception(f"Error getting provider patients: {e}")
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
            'phone_number':        profile.get('phone_number') if profile else None,
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
        logger.debug(f"Error getting patient detail: {e}")
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

    # ── Nutrition Stability Score (spec §5) ───────────────────────
    # +4 protein (≥7 srv), +2 (≥5 srv); +3 sugar (≤4 srv), +2 (≤6 srv);
    # +3 hydration (≥80oz), +2 (≥60oz).  None when no nutrition data logged.
    protein  = ext.get('protein_servings')
    sugar    = ext.get('sugar_servings')
    hydration_oz = ext.get('hydration_oz')
    nut_available = any(v is not None for v in (protein, sugar, hydration_oz))
    if nut_available:
        nut = 0
        if protein is not None:
            p = float(protein)
            nut += 4 if p >= 7 else (2 if p >= 5 else 0)
        if sugar is not None:
            sg = float(sugar)
            nut += 3 if sg <= 4 else (2 if sg <= 6 else 0)
        if hydration_oz is not None:
            hz = float(hydration_oz)
            nut += 3 if hz >= 80 else (2 if hz >= 60 else 0)
        s['nutrition_stability'] = min(nut, 10)
    else:
        s['nutrition_stability'] = None

    # ── Crash Risk (spec §5) ───────────────────────────────────────
    # Formula: (SD × 0.4) + (NS × 0.4) + ((10 − Nutrition) × 0.2)
    # Fallback when Nutrition absent: weight SD and NS equally at 0.5 each.
    ns = s['nervous_system_load']
    sd_val = s['sleep_disruption']
    nut_val = s['nutrition_stability']
    if ns is not None and sd_val is not None:
        if nut_val is not None:
            s['crash_risk'] = round(
                min(float(sd_val) * 0.4 + float(ns) * 0.4 + (10 - float(nut_val)) * 0.2, 10), 2
            )
        else:
            # Nutrition not logged — distribute weight equally between SD and NS
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

        # Build a set of medication names marked as-needed so they are excluded
        # from the adherence denominator — patients should not be penalized for
        # not taking a PRN medication on days they didn't need it.
        try:
            prn_rows = get_user_medications(user_id)
            prn_names = {
                m['name'].strip().lower()
                for m in prn_rows
                if (m.get('frequency') or '').lower() in ('as_needed', 'prn')
            }
        except Exception:
            logger.exception("_empty_metric_ts failed")
            prn_names = set()

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
            # Exclude as-needed medications from adherence tracking
            scheduled_meds = [
                m for m in meds
                if isinstance(m, dict)
                and m.get('name', '').strip().lower() not in prn_names
            ]
            if scheduled_meds:
                meds_with_entries += 1
                if any(m.get('taken') for m in scheduled_meds):
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
        logger.debug(f"Error getting trends: {e}")
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
        logger.debug(f"Error getting paired values: {e}")
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
        logger.exception(f"Error saving hypothesis result: {e}")
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
        logger.exception(f"Error getting hypothesis history: {e}")
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
        logger.exception(f"Error getting tested pairs: {e}")
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
                logger.exception("_time_to_min failed")
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
        logger.debug(f"Error getting medication timing stats: {e}")
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
        logger.exception(f"Error finding unexpected pattern: {e}")
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
        logger.exception(f"Error finding top patterns: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════
# SYMPTOM PATTERN DETECTION
# ═══════════════════════════════════════════════════════════════════════════

def _to_float(v):
    """Coerce a value to float, returning None if not possible."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        logger.exception("_to_float failed")
        return None


def _check_medication_context(patient_id, reference_date_str, window_days=14):
    """Look for medication logging pattern changes near reference_date_str.

    Heuristic:
    - 'new_medication': first event for a med falls within (window_days) before
      first_seen, with no events in the prior (window_days*2) window.
    - 'discontinued': a med has events in the far-before window but none
      within window_days before or after first_seen.

    Returns a dict {change_type, medication_name, days_before_symptom_onset}
    or None if nothing notable is found.
    """
    try:
        ref_date = datetime.strptime(reference_date_str, '%Y-%m-%d').date()
        far_before_start  = (ref_date - timedelta(days=window_days * 2)).isoformat()
        near_before_start = (ref_date - timedelta(days=window_days)).isoformat()
        after_end         = (ref_date + timedelta(days=window_days)).isoformat()

        result = supabase_admin.table('medication_events').select(
            'event_date, medication_id'
        ).eq('user_id', str(patient_id)).gte('event_date', far_before_start).lte('event_date', after_end).execute()

        events = result.data or []
        if not events:
            return None

        # Also pull medication names from the medications table
        med_ids = list({ev.get('medication_id', '') for ev in events if ev.get('medication_id')})
        name_map = {}
        if med_ids:
            try:
                meds_resp = supabase_admin.table('medications').select('id, name').in_('id', med_ids).execute()
                for m in (meds_resp.data or []):
                    name_map[m['id']] = m.get('name', m['id'][:8])
            except Exception:
                pass

        # Group events by medication
        med_dates = {}
        for ev in events:
            mid = ev.get('medication_id', '')
            med_dates.setdefault(mid, []).append(ev['event_date'])

        ref_iso = reference_date_str

        for mid, dates in med_dates.items():
            med_name = name_map.get(mid, mid[:8] if mid else 'unknown')
            has_far_before  = any(d <  near_before_start for d in dates)
            has_near_before = any(near_before_start <= d < ref_iso for d in dates)
            has_after        = any(d >= ref_iso for d in dates)

            # New medication: first logged in the near-before window, nothing earlier
            if has_near_before and not has_far_before:
                first_event = min(d for d in dates if near_before_start <= d < ref_iso)
                days_before = (ref_date - datetime.strptime(first_event, '%Y-%m-%d').date()).days
                return {
                    'change_type': 'new_medication',
                    'medication_name': med_name,
                    'days_before_symptom_onset': days_before,
                }

            # Discontinued: had history before near window, then nothing after
            if has_far_before and not has_near_before and not has_after:
                last_event = max(d for d in dates if d < near_before_start)
                days_before = (ref_date - datetime.strptime(last_event, '%Y-%m-%d').date()).days
                return {
                    'change_type': 'discontinued',
                    'medication_name': med_name,
                    'days_before_symptom_onset': days_before,
                }

        return None

    except Exception as e:
        logger.exception(f"Error checking medication context: {e}")
        return None


def find_symptom_correlations(patient_id, days=60):
    """Detect recurring patient-reported symptoms and co-occurring data patterns.

    Reads `notable_symptoms` from `extended_data` on each check-in row.
    For each symptom appearing on ≥3 days, computes mean differences across
    numeric variables between symptom days and non-symptom days.  Signals
    co-occurrence when |delta| ≥ 1.5 and n ≥ 3.

    Also queries medication_events for pattern changes near symptom onset.

    Returns a list of dicts, sorted by days_reported descending:
      {symptom, days_reported, total_days, first_seen, co_occurring, medication_context}

    co_occurring entries:
      {variable, label, direction, avg_on_symptom_days, avg_off_symptom_days, delta, n}

    medication_context: {change_type, medication_name, days_before_symptom_onset} or None
    """
    # Numeric variables to check for co-occurrence, in display order
    VAR_LABELS = {
        'sleep_disruption':  'sleep disruption',
        'crash_risk':        'crash risk',
        'stim_load':         'stim load',
        'stress':            'stress',
        'mood':              'mood',
        'energy':            'energy',
        'perceived_stress':  'perceived stress',
        'workload_friction': 'workload friction',
        'alcohol_units':     'alcohol units',
        'exercise_minutes':  'exercise minutes',
        'hydration':         'hydration',
    }

    try:
        checkins = get_checkins(patient_id, days)
        if not checkins:
            return []

        # ── Build per-day numeric snapshot and symptom map ────────────────
        day_data    = {}  # {date_str: {var: float|None, ...}}
        symptom_map = {}  # {symptom_str: [date_str, ...]}

        for row in checkins:
            d = row.get('checkin_date', '')
            if not d:
                continue

            ext = row.get('extended_data') or {}
            if isinstance(ext, str):
                try:
                    ext = json.loads(ext)
                except Exception:
                    ext = {}

            meds  = row.get('medications') or []
            mood  = row.get('mood_score')
            stress = row.get('stress_score')
            sleep = row.get('sleep_hours')
            scores = _compute_checkin_scores(mood, stress, sleep, ext, meds)

            hydration_raw = ext.get('hydration')
            if hydration_raw in (True, 'true', '1', 1):
                hydration_val = 1.0
            elif hydration_raw in (False, 'false', '0', 0):
                hydration_val = 0.0
            else:
                hydration_val = None

            day_data[d] = {
                'mood':             _to_float(mood),
                'stress':           _to_float(stress),
                'energy':           _to_float(ext.get('energy')),
                'exercise_minutes': _to_float(ext.get('exercise_minutes')),
                'alcohol_units':    _to_float(ext.get('alcohol_units')),
                'hydration':        hydration_val,
                'workload_friction':_to_float(ext.get('workload_friction')),
                'perceived_stress': _to_float(ext.get('perceived_stress')),
                'sleep_disruption': _to_float(scores.get('sleep_disruption')),
                'stim_load':        _to_float(scores.get('stim_load')),
                'crash_risk':       _to_float(scores.get('crash_risk')),
            }

            # Extract notable_symptoms
            raw_symptoms = ext.get('notable_symptoms') or []
            if isinstance(raw_symptoms, str):
                try:
                    raw_symptoms = json.loads(raw_symptoms)
                except Exception:
                    raw_symptoms = [s.strip() for s in raw_symptoms.split(',') if s.strip()]

            for sym in raw_symptoms:
                clean = str(sym).strip().lower()
                if clean:
                    symptom_map.setdefault(clean, []).append(d)

        if not symptom_map:
            return []

        total_days  = len(day_data)
        all_dates   = set(day_data.keys())
        results     = []

        for symptom, s_dates in symptom_map.items():
            if len(s_dates) < 3:
                continue

            s_date_set  = set(s_dates)
            non_s_dates = all_dates - s_date_set
            first_seen  = min(s_dates)

            # ── Co-occurrence analysis ────────────────────────────────────
            co_occurring = []
            for var, label in VAR_LABELS.items():
                on_vals  = [day_data[d][var] for d in s_dates
                            if d in day_data and day_data[d].get(var) is not None]
                off_vals = [day_data[d][var] for d in non_s_dates
                            if d in day_data and day_data[d].get(var) is not None]

                if len(on_vals) < 3 or len(off_vals) < 2:
                    continue

                avg_on  = sum(on_vals)  / len(on_vals)
                avg_off = sum(off_vals) / len(off_vals)
                delta   = avg_on - avg_off

                if abs(delta) >= 1.5:
                    co_occurring.append({
                        'variable':             var,
                        'label':                label,
                        'direction':            'elevated' if delta > 0 else 'reduced',
                        'avg_on_symptom_days':  round(avg_on,  2),
                        'avg_off_symptom_days': round(avg_off, 2),
                        'delta':                round(delta,   2),
                        'n':                    len(on_vals),
                    })

            co_occurring.sort(key=lambda x: abs(x['delta']), reverse=True)

            # ── Medication context ────────────────────────────────────────
            medication_context = _check_medication_context(patient_id, first_seen)

            results.append({
                'symptom':            symptom,
                'days_reported':      len(s_dates),
                'total_days':         total_days,
                'first_seen':         first_seen,
                'co_occurring':       co_occurring,
                'medication_context': medication_context,
            })

        results.sort(key=lambda x: x['days_reported'], reverse=True)
        return results

    except Exception as e:
        logger.exception(f"Error finding symptom correlations: {e}")
        raise DataUnavailableError(f"Error finding symptom correlations", source="find_symptom_correlations")


# ═══════════════════════════════════════════════════════════════════════════
# SUBSTANCE USE & SAFETY SIGNAL DETECTION
# ═══════════════════════════════════════════════════════════════════════════

# Substance use journal/notes language patterns (CLAUDE.md §17)
# Keys are category labels stored in journal_flags; verbatim text is never reproduced in output.
_SUBSTANCE_PATTERNS = {
    # Alcohol
    'alcohol_dependency':   ['need a drink', 'needed a drink', "can't function without",
                             "can't relax without", "can't sleep without a drink",
                             'wake up and need', 'first thing in the morning'],
    'alcohol_coping':       ['drinking to cope', 'drinking to forget', 'drink to get through',
                             'drink to calm', 'drink to sleep', 'drink to relax', 'drink to unwind'],
    'alcohol_volume':       ['drinking more than i should', 'drinking too much', 'drank a lot',
                             'drank more than usual', 'too much last night'],
    'alcohol_loss_control': ["couldn't stop drinking", 'blacked out', 'blackout',
                             'passed out from drinking', "can't stop drinking"],
    # Cannabis
    'cannabis_dependency':  ['need weed to', "can't sleep without weed", "can't function without weed",
                             'need cannabis to', "can't get through without weed",
                             'need to smoke to', 'have to smoke before'],
    'cannabis_coping':      ['smoking to cope', 'smoke to calm down', 'smoke to get through',
                             'smoke to forget', 'smoke to relax', 'smoke to unwind'],
    'cannabis_escalation':  ['smoking more than usual', 'smoking more than i should', 'too much weed',
                             'smoking all day', 'way too much weed'],
    # Nicotine
    'nicotine_stress':      ['smoke when stressed', 'need a cigarette when',
                             'smoking more because of stress', 'chain smoking', 'chain smoked'],
    'nicotine_escalation':  ['smoking more than usual', "can't go without a cigarette",
                             'need to smoke', 'going through a pack a day', 'pack a day'],
    # Cross-substance / prescription misuse
    'rx_misuse':            ['more than prescribed', 'taking extra', 'ran out early', 'double dosed',
                             'took more than i was supposed to', 'took more than prescribed',
                             'extra dose', 'taking more than i should'],
    'general_coping':       ['using to cope', 'need something to take the edge off',
                             "can't get through the day without"],
}

# Interpersonal safety signal patterns (CLAUDE.md §18)
_SAFETY_PATTERNS = {
    'physical':      ['hit me', 'he hit', 'she hit', 'punched me', 'slapped me', 'grabbed me',
                      'choked me', 'strangled', 'kicked me', 'shoved me', 'pushed me',
                      'threw at me', 'threw me', 'hurt me', 'he hurt', 'she hurt'],
    'injury':        ['bruise', 'bruised', 'bleeding', 'left a mark', 'had to cover it up',
                      'covering bruises'],
    'fear':          ['afraid of him', 'afraid of her', 'scared of him', 'scared of her',
                      'scared to go home', 'afraid to go home', "don't feel safe at home",
                      "don't feel safe with", "scared he'll", "scared she'll"],
    'threat':        ['threatened me', 'threatens me', 'said he would hurt', 'said she would hurt',
                      'if i tell anyone', "he said he'd", "she said she'd"],
    'control':       ["won't let me leave", "won't let me see", 'took my phone', 'locked me in',
                      "won't let me talk to", 'controls everything', 'isolating me'],
    'recurrence':    ['it happened again', 'he did it again', 'she did it again',
                      'same thing as last time', "i'm getting used to it",
                      "doesn't usually get this bad"],
}

_PARTNER_WORDS = {'husband', 'wife', 'partner', 'boyfriend', 'girlfriend', 'ex', 'fiancé', 'fiancee', 'fiance'}


def _scan_text_for_patterns(text, pattern_dict):
    """Return a list of matched category labels for any phrase found in text.
    Text is lowercased before matching. Returns empty list if no matches."""
    if not text:
        return []
    lower = text.lower()
    return [cat for cat, phrases in pattern_dict.items()
            if any(phrase in lower for phrase in phrases)]


def _has_partner_context(text):
    """Return True if text contains any partner reference word."""
    if not text:
        return False
    lower = text.lower()
    return any(word in lower for word in _PARTNER_WORDS)


def _substance_alert_level_alcohol(use_days_recent, avg_per_use_day, use_days_total,
                                    journal_flags_count):
    """Compute alert level for alcohol using CLAUDE.md §17 thresholds."""
    if (use_days_recent >= 5 and avg_per_use_day >= 3.0) or \
       (use_days_recent >= 5 and journal_flags_count >= 1):
        return 'concern'
    if (use_days_recent >= 4 and avg_per_use_day >= 2.0) or \
       (use_days_recent >= 5) or \
       (avg_per_use_day >= 4.0) or \
       (journal_flags_count >= 2) or \
       (journal_flags_count >= 1 and use_days_total >= 4):
        return 'watch'
    return None


def _substance_alert_level_cannabis(use_days_recent, avg_per_use_day, journal_flags_count):
    """Compute alert level for cannabis using CLAUDE.md §17 thresholds."""
    if use_days_recent >= 6 and avg_per_use_day >= 2.0:
        return 'concern'
    if (use_days_recent >= 4) or \
       (journal_flags_count >= 1 and use_days_recent >= 4):
        return 'watch'
    return None


def _substance_alert_level_nicotine(use_days_recent):
    """Compute alert level for nicotine using CLAUDE.md §17 thresholds."""
    if use_days_recent >= 7:
        return 'concern'
    if use_days_recent >= 5:
        return 'watch'
    return None


def _substance_alert_level_other(use_days_total):
    """Compute alert level for other substances using CLAUDE.md §17 thresholds."""
    if use_days_total >= 3:
        return 'watch'
    return None


def _highest_alert(levels):
    """Return the highest alert level from a list of None|'watch'|'concern' values."""
    if 'concern' in levels:
        return 'concern'
    if 'watch' in levels:
        return 'watch'
    return None


def check_substance_patterns(patient_id, days=30):
    """Detect recurring substance use patterns from check-in data and journal language.

    Tracks four substances: alcohol, cannabis, nicotine, other (CLAUDE.md §17).
    Returns None only if no substance data has been logged for any field in the window.

    Return structure:
      {
        total_days, journal_flags, alert_level,   # top-level (highest across substances)
        alcohol: {use_days, total_units, avg_per_use_day, frequency_rate, alert_level},
        cannabis: {use_days, total_sessions, avg_sessions_per_use_day, frequency_rate, alert_level},
        nicotine: {use_days, total_count, avg_per_use_day, frequency_rate, alert_level},
        other:    {use_days, total_count, frequency_rate, alert_level},
      }
    """
    try:
        checkins = get_checkins(patient_id, days)
        if not checkins:
            return None

        total_days = len(checkins)
        cutoff_7   = (date.today() - timedelta(days=7)).isoformat()

        # ── Per-substance accumulators ────────────────────────────────────
        alc_use_days = alc_total = alc_recent = 0
        can_use_days = can_total = can_recent = 0
        nic_use_days = nic_total = nic_recent = 0
        oth_use_days = oth_total = 0

        for row in checkins:
            ext = row.get('extended_data') or {}
            if isinstance(ext, str):
                try:
                    ext = json.loads(ext)
                except Exception:
                    ext = {}
            d_date  = row.get('checkin_date', '')
            recent  = d_date >= cutoff_7

            # Alcohol
            units = _to_float(ext.get('alcohol_units'))
            if units and units > 0:
                alc_use_days += 1
                alc_total    += units
                if recent:
                    alc_recent += 1

            # Cannabis
            sessions = _to_float(ext.get('cannabis_sessions'))
            if sessions and sessions > 0:
                can_use_days += 1
                can_total    += sessions
                if recent:
                    can_recent += 1

            # Nicotine
            nic_count = _to_float(ext.get('nicotine_count'))
            if nic_count and nic_count > 0:
                nic_use_days += 1
                nic_total    += nic_count
                if recent:
                    nic_recent += 1

            # Other
            oth_count = _to_float(ext.get('other_substance_uses'))
            if oth_count and oth_count > 0:
                oth_use_days += 1
                oth_total    += oth_count

        # No substance data at all → None
        if alc_use_days + can_use_days + nic_use_days + oth_use_days == 0:
            return None

        # ── Journal and notes language scan ───────────────────────────────
        journals      = get_journals(patient_id, limit=200)
        journal_flags = []
        for j in journals:
            content    = (j.get('content') or j.get('raw_entry') or '')
            entry_date = (j.get('entry_date') or j.get('created_at', ''))[:10]
            matches    = _scan_text_for_patterns(content, _SUBSTANCE_PATTERNS)
            if matches:
                journal_flags.append({'date': entry_date, 'pattern': ', '.join(matches)})

        for row in checkins:
            notes = row.get('notes') or ''
            if notes:
                matches = _scan_text_for_patterns(notes, _SUBSTANCE_PATTERNS)
                if matches:
                    journal_flags.append({
                        'date':    row.get('checkin_date', ''),
                        'pattern': ', '.join(matches),
                    })

        # Deduplicate by date
        seen_dates, unique_flags = set(), []
        for f in sorted(journal_flags, key=lambda x: x['date'], reverse=True):
            if f['date'] not in seen_dates:
                unique_flags.append(f)
                seen_dates.add(f['date'])
        journal_flags = unique_flags

        # ── Per-substance stats and alert levels ──────────────────────────
        alc_avg  = round(alc_total / alc_use_days, 2) if alc_use_days else 0.0
        can_avg  = round(can_total / can_use_days, 2) if can_use_days else 0.0
        nic_avg  = round(nic_total / nic_use_days, 2) if nic_use_days else 0.0

        alc_alert = _substance_alert_level_alcohol(
            alc_recent, alc_avg, alc_use_days, len(journal_flags))
        can_alert = _substance_alert_level_cannabis(can_recent, can_avg, len(journal_flags))
        nic_alert = _substance_alert_level_nicotine(nic_recent)
        oth_alert = _substance_alert_level_other(oth_use_days)

        top_alert = _highest_alert([alc_alert, can_alert, nic_alert, oth_alert])

        def _freq(use_days):
            return round(use_days / total_days, 3) if total_days else 0.0

        return {
            'total_days':    total_days,
            'journal_flags': journal_flags,
            'alert_level':   top_alert,
            'alcohol': {
                'use_days':         alc_use_days,
                'total_units':      round(alc_total, 1),
                'avg_per_use_day':  alc_avg,
                'frequency_rate':   _freq(alc_use_days),
                'alert_level':      alc_alert,
            },
            'cannabis': {
                'use_days':                 can_use_days,
                'total_sessions':           round(can_total, 1),
                'avg_sessions_per_use_day': can_avg,
                'frequency_rate':           _freq(can_use_days),
                'alert_level':              can_alert,
            },
            'nicotine': {
                'use_days':       nic_use_days,
                'total_count':    round(nic_total, 0),
                'avg_per_use_day': nic_avg,
                'frequency_rate': _freq(nic_use_days),
                'alert_level':    nic_alert,
            },
            'other': {
                'use_days':       oth_use_days,
                'total_count':    round(oth_total, 0),
                'frequency_rate': _freq(oth_use_days),
                'alert_level':    oth_alert,
            },
        }

    except Exception as e:
        logger.debug(f"Error checking substance patterns: {e}")
        return None


def check_safety_signals(patient_id, days=60):
    """Scan journals and check-in notes for language suggesting interpersonal physical harm.

    PROVIDER-ONLY — results must never appear in patient-facing output (Mode A/B).

    Returns dict: signals_found, signal_count, first_signal_date, most_recent_date,
    recency_days, alert_level (None|'concern').
    """
    try:
        # Apply the days window so stale signals don't surface as if recent (spec §18).
        cutoff     = (date.today() - timedelta(days=days)).isoformat()
        today_str  = date.today().isoformat()
        journals   = get_journals_in_range(patient_id, cutoff, today_str)
        checkins   = get_checkins(patient_id, days)

        signal_dates = []

        # ── Journal scan ──────────────────────────────────────────────────
        for j in journals:
            content    = (j.get('content') or j.get('raw_entry') or '')
            entry_date = (j.get('entry_date') or j.get('created_at', ''))[:10]
            matches    = _scan_text_for_patterns(content, _SAFETY_PATTERNS)
            if not matches:
                continue
            # 'injury' category only counts if there's also partner context
            # (bruises alone could be from many causes)
            if matches == ['injury'] and not _has_partner_context(content):
                continue
            signal_dates.append(entry_date)

        # ── Check-in notes scan ───────────────────────────────────────────
        for row in checkins:
            notes = row.get('notes') or ''
            if not notes:
                continue
            matches = _scan_text_for_patterns(notes, _SAFETY_PATTERNS)
            if not matches:
                continue
            if matches == ['injury'] and not _has_partner_context(notes):
                continue
            signal_dates.append(row.get('checkin_date', ''))

        # Deduplicate and sort
        signal_dates = sorted(set(d for d in signal_dates if d))

        if not signal_dates:
            return {'signals_found': False, 'alert_level': None}

        most_recent   = signal_dates[-1]
        first_signal  = signal_dates[0]
        recency_days  = (date.today() - datetime.strptime(most_recent, '%Y-%m-%d').date()).days

        return {
            'signals_found':      True,
            'signal_count':       len(signal_dates),
            'first_signal_date':  first_signal,
            'most_recent_date':   most_recent,
            'recency_days':       recency_days,
            'alert_level':        'concern',
        }

    except Exception as e:
        logger.exception(f"Error checking safety signals: {e}")
        return {'signals_found': False, 'alert_level': None}


def _get_engagement_flags(patient_id, days=14):
    """Return a compact engagement-flag dict for the provider dashboard badge.

    Uses a shorter window (14 days) than the full summary so the badge
    reflects recent non-response rather than historical patterns.

    Returns a dict when any flag is active, or None when no prompts have
    been sent yet (patient has never been prompted).

    Keys returned:
        extended_no_response  bool   — 5+ consecutive unanswered-prompt days
        insufficient_data     bool   — overall SMS rate < 40%
        never_responded       bool   — ≥3 prompts sent, zero answered
        complete_absence      bool   — 5+ days of overlapping calendar+prompt silence
        sms_divergent         bool   — selective channel non-response
        sms_divergent_detail  dict|None — {high_label, high_rate, low_label, low_rate}
        max_prompt_gap        int
        max_complete_absence_gap int
        overall_sms_rate      float
    """
    try:
        stats = compute_engagement_stats(patient_id, days=days)
        if not stats:
            return None
        all_sms_sent = sum(
            fs['sent'] for fs in (stats.get('sms_by_flow') or {}).values()
        )

        # Check-in gap fallback — fires even when no SMS prompts have been sent.
        # A patient who hasn't checked in for 7+ days (or never) in a 7+ day
        # window is worth surfacing regardless of whether SMS is active.
        days_since_last = stats.get('days_since_last')
        period_days     = stats.get('period_days', 0)
        no_checkins     = (period_days >= 7
                           and (days_since_last is None or days_since_last >= 7))

        if all_sms_sent == 0:
            if not no_checkins:
                return None
            return {
                'extended_no_response':     False,
                'insufficient_data':        False,
                'never_responded':          False,
                'complete_absence':         False,
                'sms_divergent':            False,
                'sms_divergent_detail':     None,
                'max_prompt_gap':           0,
                'max_complete_absence_gap': 0,
                'overall_sms_rate':         None,
                'no_checkins':              True,
                'days_since_last':          days_since_last,
                'max_consecutive_gap':      stats.get('max_consecutive_gap', 0),
            }

        extended         = bool(stats.get('extended_no_response', False))
        low_rate         = bool(stats.get('insufficient_data', False))
        never_responded  = bool(stats.get('never_responded', False))
        complete_absence = bool(stats.get('complete_absence', False))
        divergent        = bool(stats.get('sms_divergent', False))

        if not any([extended, low_rate, never_responded, complete_absence, divergent, no_checkins]):
            return None

        return {
            'extended_no_response':    extended,
            'insufficient_data':       low_rate,
            'never_responded':         never_responded,
            'complete_absence':        complete_absence,
            'sms_divergent':           divergent,
            'sms_divergent_detail':    stats.get('sms_divergent_detail'),
            'max_prompt_gap':          stats.get('max_prompt_gap', 0),
            'max_complete_absence_gap': stats.get('max_complete_absence_gap', 0),
            'overall_sms_rate':        stats.get('overall_sms_rate', 1.0),
            'no_checkins':             no_checkins,
            'days_since_last':         days_since_last,
            'max_consecutive_gap':     stats.get('max_consecutive_gap', 0),
        }
    except Exception as e:
        logger.exception(f"Error computing engagement flags for {patient_id}: {e}")
        return None


def get_patient_flags(patient_id, days=30):
    """Aggregate all active Mode D flags for a patient.

    Returns dict: {engagement: {...}|None, safety: {...}|None, sms_crisis: [...]}
    Used by provider dashboard route and Mode C summary generation.

    Note: substance patterns are still computed and passed to Mode C summaries
    via generate_appointment_summary(), but are no longer shown as a dashboard
    badge (replaced by the non-response engagement badge).
    """
    return {
        'engagement': _get_engagement_flags(patient_id, days=14),
        'safety':     check_safety_signals(patient_id, days=days),
        'sms_crisis': get_sms_crisis_events(patient_id, limit=5),
    }


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
        logger.exception(f"Error logging AI feedback: {e}")
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
        logger.exception(f"Error creating appointment: {e}")
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
        logger.exception(f"Error fetching appointment: {e}")
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
        logger.exception(f"Error fetching patient appointments: {e}")
        return []


def update_provider_appointment(appt_id: str, provider_id: str, updates: dict) -> bool:
    """Patch an appointment row. Only allowed fields are applied."""
    ALLOWED = {
        'status', 'period_days', 'guided_qa', 'notes',
        'care_plan_changes', 'actions',
        'next_appointment_date', 'next_appointment_time', 'next_appointment_notes', 'completed_at',
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
        logger.exception(f"Error updating appointment: {e}")
        return False


def get_provider_calendar_appointments(provider_id: str, patient_id: str) -> list:
    """Return calendar events for a patient: past sessions + upcoming scheduled entries."""
    try:
        today = date.today().isoformat()
        res = supabase_admin.table('provider_appointments').select(
            'id, started_at, completed_at, status, appointment_type, next_appointment_notes'
        ).eq('provider_id', str(provider_id)).eq('patient_id', str(patient_id)).order(
            'started_at', desc=False
        ).execute()
        rows = res.data or []
        events = []
        for r in rows:
            raw_started = r.get('started_at') or ''
            event_date = raw_started[:10] if raw_started else ''
            event_time = raw_started[11:16] if len(raw_started) > 10 else None
            status = r.get('status', '')
            if not event_date:
                continue
            events.append({
                'id':         r['id'],
                'date':       event_date,
                'time':       event_time,
                'title':      r.get('appointment_type') or 'Appointment',
                'event_type': 'appointment',
                'status':     status,
                'notes':      r.get('next_appointment_notes') or '',
                'is_past':    event_date < today,
                'is_session': status in ('active', 'completed'),
            })
        return events
    except Exception as e:
        logger.exception(f"[db] get_provider_calendar_appointments error: {e}")
        return []


def create_calendar_appointment(provider_id: str, patient_id: str, event_date: str,
                                event_time: str | None, title: str, notes: str,
                                event_type: str = 'appointment') -> dict | None:
    """Create a scheduled calendar entry in provider_appointments."""
    try:
        started_at = event_date
        if event_time:
            started_at = f"{event_date}T{event_time}:00"
        row = {
            'provider_id':             str(provider_id),
            'patient_id':              str(patient_id),
            'status':                  'scheduled',
            'started_at':              started_at,
            'appointment_type':        title or 'Appointment',
            'next_appointment_notes':  notes or '',
            'period_days':             30,
        }
        resp = supabase_admin.table('provider_appointments').insert(row).execute()
        return (resp.data or [None])[0]
    except Exception as e:
        logger.exception(f"[db] create_calendar_appointment error: {e}")
        return None


def update_calendar_appointment(appt_id: str, provider_id: str, event_date: str,
                                event_time: str | None, title: str, notes: str) -> bool:
    """Update a scheduled calendar entry (only status='scheduled' records)."""
    try:
        started_at = event_date
        if event_time:
            started_at = f"{event_date}T{event_time}:00"
        payload = {
            'started_at':             started_at,
            'appointment_type':       title or 'Appointment',
            'next_appointment_notes': notes or '',
            'updated_at':             datetime.utcnow().isoformat(),
        }
        supabase_admin.table('provider_appointments').update(payload).eq(
            'id', str(appt_id)).eq('provider_id', str(provider_id)).eq(
            'status', 'scheduled').execute()
        return True
    except Exception as e:
        logger.exception(f"[db] update_calendar_appointment error: {e}")
        return False


def delete_calendar_appointment(appt_id: str, provider_id: str) -> bool:
    """Delete a scheduled calendar entry (only status='scheduled' records)."""
    try:
        supabase_admin.table('provider_appointments').delete().eq(
            'id', str(appt_id)).eq('provider_id', str(provider_id)).eq(
            'status', 'scheduled').execute()
        return True
    except Exception as e:
        logger.exception(f"[db] delete_calendar_appointment error: {e}")
        return False


def get_all_provider_appointments(provider_id: str, from_date: str = None, to_date: str = None) -> list:
    """Return all appointments across all patients for a provider, enriched with patient names."""
    try:
        q = supabase_admin.table('provider_appointments').select(
            'id, patient_id, started_at, completed_at, status, appointment_type, next_appointment_notes, notes'
        ).eq('provider_id', str(provider_id))
        if from_date:
            q = q.gte('started_at', from_date)
        if to_date:
            q = q.lte('started_at', to_date + 'T23:59:59')
        resp = q.order('started_at', desc=False).execute()
        rows = resp.data or []
        # Enrich with patient names in one batch query
        patient_ids = list({r['patient_id'] for r in rows if r.get('patient_id')})
        names = {}
        if patient_ids:
            nr = supabase_admin.table('profiles').select('id, full_name').in_(
                'id', patient_ids).execute()
            names = {p['id']: p.get('full_name', 'Unknown') for p in (nr.data or [])}
        for r in rows:
            r['patient_name'] = names.get(str(r.get('patient_id', '')), 'Unknown')
        return rows
    except Exception as e:
        logger.exception(f"[db] get_all_provider_appointments error: {e}")
        return []


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
        logger.exception("get_between_session_brief failed")
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
        logger.exception("get_between_session_brief failed")
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
        logger.exception("get_between_session_brief failed")
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
            logger.exception("_delta_dir failed")
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

    # ── Clinical sessions (audio recordings / transcripts) in period ──────────
    recording_count      = 0
    recording_has_audio  = False
    recording_dominant_pattern = None
    recording_crisis_count = 0
    try:
        sess_resp = supabase_admin.table('clinical_sessions').select(
            'id, session_type, processing_status, transcript_source, '
            'session_features(scores, crisis_detected)'
        ).eq('patient_id', str(patient_id)).eq(
            'processing_status', 'complete'
        ).gte('session_date', since_iso).execute()
        sess_rows = sess_resp.data or []

        pattern_counts: dict = {}
        for sr in sess_rows:
            recording_count += 1
            sf = sr.get('session_features') or {}
            feat_row = sf if isinstance(sf, dict) else (sf[0] if sf else {})
            if feat_row.get('crisis_detected'):
                recording_crisis_count += 1
            scores = feat_row.get('scores') or {}
            acf = scores.get('acoustic_features') or {}
            if acf and (acf.get('raw') or acf.get('vocabulary')):
                recording_has_audio = True
                vocab = acf.get('vocabulary') or {}
                pattern = vocab.get('clinical_pattern_type')
                if pattern and pattern != 'none_detected':
                    pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1
        if pattern_counts:
            recording_dominant_pattern = max(pattern_counts, key=pattern_counts.get)
    except Exception:
        pass

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
        'session_notes':           session_notes,
        'care_plan_changes':       care_plan_changes,
        'session_actions':         session_actions,
        # Clinical sessions / audio recordings in period
        'recording_count':         recording_count,
        'recording_has_audio':     recording_has_audio,
        'recording_dominant_pattern': recording_dominant_pattern,
        'recording_crisis_count':  recording_crisis_count,
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
        logger.exception("get_provider_patients_with_stats failed")
        ct_roles = {}

    # ── Add care-team-only patients not already in base ───────────────────────
    # base comes from patient_profiles.provider_id (legacy single-provider model).
    # Providers added only via care_team_members never appear there — merge them in.
    existing_ids = {str(p['patient_id']) for p in base}
    for ct_pid in list(ct_roles):
        if ct_pid in existing_ids:
            continue
        user_rec = get_user_by_id(ct_pid)
        if not user_rec:
            continue
        try:
            ci_r = supabase_admin.table('checkins').select('checkin_date').eq(
                'user_id', ct_pid).order('checkin_date', desc=True).limit(1).execute()
            last_ci = ci_r.data[0]['checkin_date'][:10] if ci_r.data else None
        except Exception:
            last_ci = None
        try:
            pp_r = supabase_admin.table('patient_profiles').select(
                'current_medications').eq('user_id', ct_pid).execute()
            meds = (pp_r.data[0].get('current_medications') or []) if pp_r.data else []
        except Exception:
            meds = []
        base.append({
            'patient_id':          ct_pid,
            'full_name':           user_rec.get('full_name', 'Unknown'),
            'email':               user_rec.get('email', ''),
            'last_checkin':        last_ci,
            'has_summary':         False,
            'current_medications': meds,
            'crisis_resolved_at':  None,
        })
        existing_ids.add(ct_pid)

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
        logger.exception("get_behavioral_data failed")
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
        logger.exception("get_care_team_member_role failed")
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


def create_patient_invite(provider_id: str, patient_email: str,
                          role: str = 'psychiatrist', message: str = None) -> dict:
    """
    Create a pre-registration invite for a patient who doesn't have an account yet.
    Returns {'ok': True, 'token': ..., 'invite_id': ...}.
    """
    role = role if role in _ROLE_LABELS else 'other'
    email = patient_email.lower().strip()
    try:
        # Cancel any prior pending invite for this provider+email
        supabase_admin.table('patient_invites').update({'status': 'superseded'}).eq(
            'provider_id', str(provider_id)).eq('patient_email', email).eq(
            'status', 'pending').execute()
        res = supabase_admin.table('patient_invites').insert({
            'provider_id': str(provider_id),
            'patient_email': email,
            'role': role,
            'message': message,
            'status': 'pending',
        }).execute()
        row = res.data[0] if res.data else {}
        return {'ok': True, 'token': row.get('token'), 'invite_id': row.get('id')}
    except Exception as e:
        logger.exception("create_patient_invite failed")
        return {'ok': False, 'error': f'Could not create invite: {e}'}


def get_patient_invite_by_token(token: str) -> dict | None:
    """Fetch a valid pending invite by token."""
    try:
        res = supabase_admin.table('patient_invites').select('*, profiles!patient_invites_provider_id_fkey(full_name)').eq(
            'token', token).eq('status', 'pending').execute()
        if not res.data:
            return None
        row = res.data[0]
        # Flatten provider name
        pf = row.pop('profiles', None) or {}
        row['provider_name'] = pf.get('full_name', 'Your provider')
        return row
    except Exception:
        logger.exception("get_patient_invite_by_token failed")
        return None


def process_pending_invites(patient_email: str, patient_id: str) -> int:
    """
    When a patient account becomes active, accept all pending invites for their email.
    Creates care_team_members rows for each and marks invites as accepted.
    Returns the number of connections created.
    """
    email = patient_email.lower().strip()
    try:
        res = supabase_admin.table('patient_invites').select('*').eq(
            'patient_email', email).eq('status', 'pending').execute()
        rows = res.data or []
        created = 0
        for invite in rows:
            provider_id = invite['provider_id']
            role = invite.get('role', 'psychiatrist')
            message = invite.get('message')
            # Check for existing relationship
            existing = supabase_admin.table('care_team_members').select('id, status').eq(
                'patient_id', str(patient_id)).eq('provider_id', str(provider_id)).execute()
            if existing.data:
                # Reactivate if revoked
                rec = existing.data[0]
                if rec['status'] != 'active':
                    supabase_admin.table('care_team_members').update({
                        'status': 'active',
                        'role': role,
                        'approved_at': datetime.utcnow().isoformat(),
                    }).eq('id', rec['id']).execute()
                    created += 1
            else:
                supabase_admin.table('care_team_members').insert({
                    'patient_id': str(patient_id),
                    'provider_id': str(provider_id),
                    'role': role,
                    'status': 'active',
                    'data_permissions': _DEFAULT_PERMISSIONS,
                    'requested_by': 'provider',
                    'request_message': message,
                    'approved_at': datetime.utcnow().isoformat(),
                }).execute()
                created += 1
            # Mark invite accepted
            supabase_admin.table('patient_invites').update(
                {'status': 'accepted'}).eq('id', invite['id']).execute()
        return created
    except Exception as e:
        logger.exception(f"[db] process_pending_invites error: {e}")
        return 0


def get_patient_appointment_list(patient_id: str) -> list:
    """
    Return all appointments for a patient with provider name, newest first.
    Used for the patient-facing appointments page.
    """
    try:
        res = supabase_admin.table('provider_appointments').select(
            'id, started_at, appointment_type, period_days, provider_id'
        ).eq('patient_id', str(patient_id)).order('started_at', desc=True).execute()
        rows = res.data or []
        if not rows:
            return []
        # Batch-fetch provider names
        provider_ids = list({r['provider_id'] for r in rows if r.get('provider_id')})
        pf_res = supabase_admin.table('profiles').select('id, full_name').in_(
            'id', provider_ids).execute()
        provider_map = {p['id']: p.get('full_name', 'Provider') for p in (pf_res.data or [])}
        today = date.today().isoformat()
        result = []
        for r in rows:
            appt_date = (r.get('started_at') or '')[:10]
            result.append({
                'id':               r['id'],
                'appt_date':        appt_date,
                'provider_name':    provider_map.get(r['provider_id'], 'Provider'),
                'provider_id':      r['provider_id'],
                'appointment_type': r.get('appointment_type') or 'Appointment',
                'period_days':      r.get('period_days', 30),
                'is_upcoming':      appt_date >= today,
            })
        return result
    except Exception as e:
        logger.exception(f"[db] get_patient_appointment_list error: {e}")
        return []


def get_patient_next_scheduled_appointment(patient_id: str) -> dict | None:
    """
    Return the soonest upcoming appointment for the patient.

    Priority:
    1. Earliest future next_appointment_date explicitly set by a provider.
    2. Earliest appointment whose started_at date >= today (upcoming session),
       used as a fallback when no next_appointment_date has been set.
    """
    from datetime import datetime as _dt
    today = date.today().isoformat()

    def _build_result(appt_date_str, provider_id, time_str=None, notes_str=None):
        pf = supabase_admin.table('profiles').select('full_name').eq(
            'id', str(provider_id)).limit(1).execute()
        provider_name = ((pf.data or [{}])[0]).get('full_name', 'Your provider')
        ct = supabase_admin.table('care_team_members').select('role').eq(
            'patient_id', str(patient_id)).eq(
            'provider_id', str(provider_id)).eq('status', 'active').limit(1).execute()
        role = ((ct.data or [{}])[0]).get('role', 'other')
        try:
            d = _dt.strptime(appt_date_str, '%Y-%m-%d')
            date_display = d.strftime('%A, %B %d, %Y').replace(' 0', ' ')
            days_until = (d.date() - date.today()).days
        except Exception:
            logger.exception("_build_result failed")
            date_display = appt_date_str
            days_until = None
        time_display = ''
        raw_time = (time_str or '').strip()
        if raw_time:
            try:
                t = _dt.strptime(raw_time, '%H:%M')
                hour = t.hour % 12 or 12
                ampm = 'am' if t.hour < 12 else 'pm'
                time_display = f"{hour}:{t.strftime('%M')} {ampm}"
            except Exception:
                time_display = raw_time
        return {
            'provider_name':       provider_name,
            'provider_role':       role,
            'provider_role_label': _ROLE_LABELS.get(role, 'Provider'),
            'date':                appt_date_str,
            'date_display':        date_display,
            'time_display':        time_display,
            'days_until':          days_until,
            'notes':               (notes_str or '').strip(),
        }

    try:
        # Priority 1: provider-set next_appointment_date
        res = supabase_admin.table('provider_appointments').select(
            'provider_id, next_appointment_date, next_appointment_time, next_appointment_notes'
        ).eq('patient_id', str(patient_id)).not_.is_(
            'next_appointment_date', 'null'
        ).gte('next_appointment_date', today).order(
            'next_appointment_date', desc=False
        ).limit(1).execute()
        row = (res.data or [None])[0]
        if row:
            return _build_result(
                row['next_appointment_date'],
                row['provider_id'],
                row.get('next_appointment_time'),
                row.get('next_appointment_notes'),
            )

        # Priority 2: upcoming session by started_at (same logic as the appointments quick card)
        res2 = supabase_admin.table('provider_appointments').select(
            'provider_id, started_at'
        ).eq('patient_id', str(patient_id)).gte(
            'started_at', today
        ).order('started_at', desc=False).limit(1).execute()
        row2 = (res2.data or [None])[0]
        if row2:
            appt_date = (row2.get('started_at') or '')[:10]
            if appt_date >= today:
                return _build_result(appt_date, row2['provider_id'])

        return None
    except Exception as e:
        logger.debug(f"[db] get_patient_next_scheduled_appointment error: {e}")
        return None


def send_care_team_request(provider_id: str, patient_email: str, role: str = 'psychiatrist',
                           message: str = None) -> dict:
    """
    Provider sends a connection request to a patient by email.
    If the patient has no account yet, creates a pre-registration invite instead.
    Returns {'ok': True, 'member_id': ..., 'method': 'request'|'invitation'} or {'ok': False, ...}.
    """
    role = role if role in _ROLE_LABELS else 'other'

    # Look up patient by email
    try:
        pr = supabase_admin.table('profiles').select('id, full_name, role, status').eq(
            'email', patient_email.lower().strip()).single().execute()
        if not pr.data or pr.data.get('role') != 'patient':
            raise Exception('not found')
        patient_id = pr.data['id']
    except Exception:
        logger.exception("send_care_team_request failed")
        # Patient has no account — create a pre-registration invite
        result = create_patient_invite(provider_id, patient_email, role, message)
        if result.get('ok'):
            result['method'] = 'invitation'
        return result

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
                return {'ok': True, 'member_id': rec['id'], 'patient_name': pr.data.get('full_name'), 'method': 'request'}
    except Exception:
        logger.exception("send_care_team_request failed")
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
        return {'ok': True, 'member_id': member_id, 'patient_name': pr.data.get('full_name'), 'method': 'request'}
    except Exception as e:
        logger.exception("send_care_team_request failed")
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
        logger.exception("send_patient_care_request failed")
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
        logger.exception("send_patient_care_request failed")
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

        # Email the provider so they know they have a pending invite
        try:
            import email_utils as _eu
            pat_pr = supabase_admin.table('profiles').select(
                'full_name').eq('id', str(patient_id)).limit(1).execute()
            patient_name = pat_pr.data[0]['full_name'] if pat_pr.data else 'A patient'
            _eu.send_patient_care_invite_email(
                provider_email,
                pr.data.get('full_name', 'there'),
                patient_name,
                _ROLE_LABELS.get(role, 'Provider'),
                message,
            )
        except Exception:
            pass  # Email failure never blocks the invite

        return {'ok': True, 'member_id': member_id, 'provider_name': pr.data.get('full_name')}
    except Exception as e:
        logger.exception("send_patient_care_request failed")
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
        logger.exception("get_pending_care_requests failed")
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
        logger.exception("approve_care_request failed")
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
        logger.exception("deny_care_request failed")
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
        logger.exception("revoke_care_member failed")
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
        logger.exception("get_patient_care_team failed")
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
    except Exception as e:
        logger.exception(f"[db] get_care_team_permissions error: {e}")
        return None


def ensure_legacy_care_team_row(patient_id: str, provider_id: str) -> dict:
    """
    For a legacy provider-patient pair (assigned via patient_profiles.provider_id),
    ensure an active care_team_members row exists so permissions can be managed.

    Returns the data_permissions dict for that row (creates one on first call).
    """
    try:
        # Check if any row exists already (any status)
        existing = supabase_admin.table('care_team_members').select(
            'id, status, data_permissions'
        ).eq('patient_id', str(patient_id)).eq('provider_id', str(provider_id)).execute()

        if existing.data:
            row = existing.data[0]
            if row['status'] == 'active':
                return row.get('data_permissions') or _DEFAULT_PERMISSIONS
            # Row exists but is not active — don't auto-activate a revoked relationship
            return _DEFAULT_PERMISSIONS

        # No row at all — look up provider_type to set a sensible role
        try:
            pr = supabase_admin.table('profiles').select('provider_type').eq(
                'id', str(provider_id)).single().execute()
            role = (pr.data or {}).get('provider_type') or 'psychiatrist'
        except Exception:
            role = 'psychiatrist'

        now_iso = datetime.utcnow().isoformat()
        supabase_admin.table('care_team_members').insert({
            'patient_id':       str(patient_id),
            'provider_id':      str(provider_id),
            'role':             role,
            'status':           'active',
            'requested_by':     'migration',
            'approved_at':      now_iso,
            'data_permissions': _DEFAULT_PERMISSIONS,
        }).execute()
        print(f"[care_team] Migrated legacy pair to care_team_members: "
              f"patient={patient_id} provider={provider_id}", flush=True)
        return _DEFAULT_PERMISSIONS
    except Exception as e:
        logger.exception(f"[care_team] ensure_legacy_care_team_row error: {e}")
        return _DEFAULT_PERMISSIONS


def provider_has_care_access(provider_id: str, patient_id: str) -> bool:
    """
    Returns True if an active care team relationship exists between provider and patient.
    Used to authorise provider access to patient data.
    """
    return get_care_team_permissions(patient_id, provider_id) is not None


def get_provider_outbound_requests(provider_id: str) -> list:
    """
    Returns pending connection requests sent BY this provider (requested_by='provider').
    """
    try:
        res = supabase_admin.table('care_team_members').select(
            'id, role, status, requested_at, patient_id'
        ).eq('provider_id', str(provider_id)).eq('status', 'pending').eq(
            'requested_by', 'provider').execute()
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
        logger.exception("get_provider_outbound_requests failed")
        return []


def get_provider_inbound_requests(provider_id: str) -> list:
    """
    Returns pending connection requests sent BY a patient to this provider (requested_by='patient').
    """
    try:
        res = supabase_admin.table('care_team_members').select(
            'id, role, status, request_message, patient_id'
        ).eq('provider_id', str(provider_id)).eq('status', 'pending').eq(
            'requested_by', 'patient').execute()
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
                'id':             rec['id'],
                'patient_id':     rec['patient_id'],
                'patient_name':   patient.get('full_name') or 'Unknown Patient',
                'patient_email':  patient.get('email', ''),
                'role':           rec['role'],
                'role_label':     _ROLE_LABELS.get(rec['role'], 'Provider'),
                'request_message': rec.get('request_message'),
            })
        return out
    except Exception:
        logger.exception("get_provider_inbound_requests failed")
        return []


def accept_inbound_care_request(provider_id: str, member_id: str) -> dict:
    """Provider accepts a patient-initiated pending request."""
    try:
        rec = supabase_admin.table('care_team_members').select('id, status').eq(
            'id', str(member_id)).eq('provider_id', str(provider_id)).eq(
            'status', 'pending').execute()
        if not rec.data:
            return {'ok': False, 'error': 'Request not found.'}
        supabase_admin.table('care_team_members').update({
            'status': 'active',
            'approved_at': datetime.utcnow().isoformat(),
        }).eq('id', str(member_id)).execute()
        return {'ok': True}
    except Exception as e:
        logger.exception("accept_inbound_care_request failed")
        return {'ok': False, 'error': str(e)}


def decline_inbound_care_request(provider_id: str, member_id: str) -> dict:
    """Provider declines a patient-initiated pending request."""
    try:
        rec = supabase_admin.table('care_team_members').select('id, status').eq(
            'id', str(member_id)).eq('provider_id', str(provider_id)).eq(
            'status', 'pending').execute()
        if not rec.data:
            return {'ok': False, 'error': 'Request not found.'}
        supabase_admin.table('care_team_members').update({
            'status': 'revoked',
            'revoked_at': datetime.utcnow().isoformat(),
        }).eq('id', str(member_id)).execute()
        return {'ok': True}
    except Exception as e:
        logger.exception("decline_inbound_care_request failed")
        return {'ok': False, 'error': str(e)}


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
        print(f"[perms] SAVED member={member_id} permissions={merged}", flush=True)
        return {'ok': True}
    except Exception as e:
        logger.exception(f"[perms] SAVE FAILED member={member_id} error={e}")
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
        logger.exception("create_care_flag failed")
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
                logger.debug(f"care flag email failed for {prov['email']}: {email_err}")
    except Exception as notify_err:
        logger.exception(f"care flag notify error (non-fatal): {notify_err}")

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
        logger.exception(f"get_care_flags_for_provider error: {e}")
        raise DataUnavailableError(f"get_care_flags_for_provider error", source="get_care_flags_for_provider")


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
        logger.exception(f"get_my_care_flags error: {e}")
        raise DataUnavailableError(f"get_my_care_flags error", source="get_my_care_flags")


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
        logger.exception("resolve_care_flag failed")
        return {'ok': False, 'error': str(e)}


def get_all_care_flags_for_hub(patient_id: str) -> list:
    """
    Returns ALL care flags for a patient (active + resolved), with resolver info.
    Used by the persistent flags panel on the provider hub.
    """
    try:
        res = supabase_admin.table('care_flags').select(
            'id, flag_type, body, created_at, resolved_at, resolved_by, author_provider_id'
        ).eq('patient_id', str(patient_id)).order('created_at', desc=True).execute()
        rows = res.data or []

        # Collect provider IDs to look up names
        provider_ids = set()
        for r in rows:
            if r.get('author_provider_id'):
                provider_ids.add(r['author_provider_id'])
            if r.get('resolved_by'):
                provider_ids.add(r['resolved_by'])

        name_map: dict = {}
        if provider_ids:
            try:
                prov_res = supabase_admin.table('providers').select(
                    'id, full_name'
                ).in_('id', list(provider_ids)).execute()
                for p in (prov_res.data or []):
                    name_map[p['id']] = p.get('full_name') or 'Provider'
            except Exception:
                pass

        out = []
        for r in rows:
            out.append({
                'id':             r.get('id'),
                'flag_type':      r.get('flag_type'),
                'body':           r.get('body'),
                'created_at':     (r.get('created_at') or '')[:10],
                'author_name':    name_map.get(r.get('author_provider_id', ''), 'Provider'),
                'resolved':       bool(r.get('resolved_at')),
                'resolved_at':    (r.get('resolved_at') or '')[:10] if r.get('resolved_at') else None,
                'resolved_by_name': name_map.get(r.get('resolved_by', ''), 'Provider') if r.get('resolved_by') else None,
            })
        return out
    except Exception as e:
        logger.exception(f"get_all_care_flags_for_hub error: {e}")
        raise DataUnavailableError(f"get_all_care_flags_for_hub error", source="get_all_care_flags_for_hub")


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
        logger.exception(f"get_unresolved_flag_counts error: {e}")
        raise DataUnavailableError(f"get_unresolved_flag_counts error", source="get_unresolved_flag_counts")


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
        logger.exception(f"get_care_team_for_provider error: {e}")
        return []


def get_care_team_for_patient(patient_id: str) -> list:
    """
    Returns all active care team members visible to the patient.
    Each entry: {provider_id, provider_name, provider_email, role, role_label}
    Used for the patient appointments page (request form) and care team display.
    """
    try:
        res = supabase_admin.table('care_team_members').select(
            'provider_id, role'
        ).eq('patient_id', str(patient_id)).eq('status', 'active').execute()
        members = res.data or []
        if not members:
            return []
        provider_ids = [m['provider_id'] for m in members]
        prof_res = supabase_admin.table('profiles').select(
            'id, full_name, email').in_('id', provider_ids).execute()
        info_map = {r['id']: r for r in (prof_res.data or [])}
        return [
            {
                'provider_id':    m['provider_id'],
                'provider_name':  info_map.get(m['provider_id'], {}).get('full_name', 'Provider'),
                'provider_email': info_map.get(m['provider_id'], {}).get('email'),
                'role':           m['role'],
                'role_label':     _ROLE_LABELS.get(m['role'], 'Provider'),
            }
            for m in members
        ]
    except Exception as e:
        logger.exception(f"[db] get_care_team_for_patient error: {e}")
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
        logger.exception("create_flag_response failed")
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
        logger.exception(f"get_flag_responses error: {e}")
        raise DataUnavailableError(f"get_flag_responses error", source="get_flag_responses")


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
        logger.exception("add_medication_by_psychiatrist failed")
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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PROACTIVE INSIGHTS — Pattern detection & persistence
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# How long (hours) to suppress re-firing the same pattern type
_PROACTIVE_COOLDOWN_HOURS = 48


def _get_recent_scored_checkins(patient_id: str, days: int = 14) -> list:
    """Return the last `days` days of check-ins with computed scores, oldest-first."""
    rows = get_checkins(patient_id, days=days)
    rows = sorted(rows, key=lambda r: r.get('checkin_date', ''))  # oldest → newest
    scored = []
    for r in rows:
        ext  = r.get('extended_data') or {}
        meds = r.get('medications') or []
        scores = _compute_checkin_scores(
            r.get('mood_score'), r.get('stress_score'),
            r.get('sleep_hours'), ext, meds
        )
        scored.append({**r, **scores})
    return scored


def _recently_fired(patient_id: str, pattern_type: str) -> bool:
    """True if the same pattern fired within the cooldown window."""
    try:
        cutoff = (datetime.utcnow() - timedelta(hours=_PROACTIVE_COOLDOWN_HOURS)).isoformat()
        res = (supabase_admin.table('proactive_insights')
               .select('id')
               .eq('patient_id', str(patient_id))
               .eq('pattern_type', pattern_type)
               .gte('created_at', cutoff)
               .limit(1)
               .execute())
        return bool(res.data)
    except Exception:
        logger.exception("_recently_fired failed")
        return False


def detect_proactive_patterns(patient_id: str) -> list:
    """
    Analyse recent check-in data and return a list of triggered pattern dicts.
    Each dict: { pattern_type, supporting_data }

    Patterns
    --------
    crash_risk_climbing   — crash_risk increased on each of the last 3 check-ins, latest ≥ 5
    sleep_degradation     — avg sleep_hours last 3 days ≥ 1.5 h below 14-day avg
    mood_decline          — mood dropped on each of the last 3 check-ins, latest ≤ 5
    stim_load_spike       — stim_load ≥ 7 on 2+ of the last 3 check-ins
    positive_streak       — stability_score ≥ 7 on each of the last 3 check-ins
    """
    scored = _get_recent_scored_checkins(patient_id, days=14)
    if len(scored) < 3:
        return []

    triggered = []
    last3 = scored[-3:]   # 3 most recent, oldest→newest
    latest = last3[-1]

    def _avg(vals):
        clean = [v for v in vals if v is not None]
        return round(sum(clean) / len(clean), 2) if clean else None

    # ── 1. Crash risk climbing ────────────────────────────────────────
    if not _recently_fired(patient_id, 'crash_risk_climbing'):
        cr = [r.get('crash_risk') for r in last3]
        if (all(v is not None for v in cr)
                and cr[0] < cr[1] < cr[2]
                and cr[2] >= 5):
            baseline_cr = _avg([r.get('crash_risk') for r in scored[:-3]])
            triggered.append({
                'pattern_type': 'crash_risk_climbing',
                'supporting_data': {
                    'crash_risk_last3': cr,
                    'baseline_crash_risk': baseline_cr,
                    'sleep_hours_latest': latest.get('sleep_hours'),
                    'stress_latest': latest.get('stress_score'),
                    'stim_load_latest': latest.get('stim_load'),
                }
            })

    # ── 2. Sleep degradation ──────────────────────────────────────────
    if not _recently_fired(patient_id, 'sleep_degradation'):
        sleep_all  = [r.get('sleep_hours') for r in scored if r.get('sleep_hours') is not None]
        sleep_last3 = [r.get('sleep_hours') for r in last3 if r.get('sleep_hours') is not None]
        if len(sleep_all) >= 5 and len(sleep_last3) >= 2:
            avg_all   = _avg(sleep_all[:-3])   # baseline excludes last 3
            avg_last3 = _avg(sleep_last3)
            if avg_all is not None and avg_last3 is not None and (avg_all - avg_last3) >= 1.5:
                triggered.append({
                    'pattern_type': 'sleep_degradation',
                    'supporting_data': {
                        'avg_sleep_last3_days': avg_last3,
                        'baseline_sleep_avg': avg_all,
                        'delta_hours': round(avg_all - avg_last3, 1),
                        'sleep_disruption_latest': latest.get('sleep_disruption'),
                    }
                })

    # ── 3. Mood decline ───────────────────────────────────────────────
    if not _recently_fired(patient_id, 'mood_decline'):
        moods = [r.get('mood_score') for r in last3]
        if (all(v is not None for v in moods)
                and moods[0] > moods[1] > moods[2]
                and moods[2] <= 5):
            baseline_mood = _avg([r.get('mood_score') for r in scored[:-3]])
            triggered.append({
                'pattern_type': 'mood_decline',
                'supporting_data': {
                    'mood_last3': moods,
                    'baseline_mood': baseline_mood,
                    'stress_latest': latest.get('stress_score'),
                    'sleep_hours_latest': latest.get('sleep_hours'),
                }
            })

    # ── 4. Stim load spike ────────────────────────────────────────────
    if not _recently_fired(patient_id, 'stim_load_spike'):
        stims = [r.get('stim_load') for r in last3 if r.get('stim_load') is not None]
        high  = [v for v in stims if v >= 7]
        if len(stims) >= 2 and len(high) >= 2:
            baseline_stim = _avg([r.get('stim_load') for r in scored[:-3]
                                   if r.get('stim_load') is not None])
            triggered.append({
                'pattern_type': 'stim_load_spike',
                'supporting_data': {
                    'stim_load_last3': stims,
                    'baseline_stim_load': baseline_stim,
                    'high_load_days': len(high),
                    'nervous_system_load_latest': latest.get('nervous_system_load'),
                }
            })

    # ── 5. Positive streak ────────────────────────────────────────────
    if not _recently_fired(patient_id, 'positive_streak'):
        stabs = [r.get('stability_score') for r in last3]
        if (all(v is not None for v in stabs)
                and all(v >= 7 for v in stabs)):
            baseline_stab = _avg([r.get('stability_score') for r in scored[:-3]
                                   if r.get('stability_score') is not None])
            triggered.append({
                'pattern_type': 'positive_streak',
                'supporting_data': {
                    'stability_scores_last3': stabs,
                    'baseline_stability': baseline_stab,
                    'mood_latest': latest.get('mood_score'),
                    'sleep_hours_latest': latest.get('sleep_hours'),
                }
            })

    return triggered


def save_proactive_insight(patient_id: str, pattern_type: str,
                            insight_text: str, supporting_data: dict = None) -> str | None:
    """Persist a proactive insight. Returns the new row id or None on error."""
    try:
        res = (supabase_admin.table('proactive_insights').insert({
            'patient_id':      str(patient_id),
            'pattern_type':    pattern_type,
            'insight_text':    insight_text,
            'supporting_data': supporting_data or {},
        }).execute())
        return res.data[0]['id'] if res.data else None
    except Exception as e:
        logger.exception(f"Error saving proactive insight: {e}")
        return None


def get_unseen_proactive_insights(patient_id: str) -> list:
    """Return active (not dismissed) insights for the patient, newest first."""
    try:
        res = (supabase_admin.table('proactive_insights')
               .select('*')
               .eq('patient_id', str(patient_id))
               .is_('dismissed_at', 'null')
               .order('created_at', desc=True)
               .limit(5)
               .execute())
        return res.data if res.data else []
    except Exception as e:
        logger.exception(f"Error fetching proactive insights: {e}")
        return []


def mark_proactive_insight_seen(patient_id: str, insight_id: str) -> bool:
    """Stamp seen_at if not already set."""
    try:
        supabase_admin.table('proactive_insights').update({
            'seen_at': datetime.utcnow().isoformat()
        }).eq('id', insight_id).eq('patient_id', str(patient_id)).is_('seen_at', 'null').execute()
        return True
    except Exception as e:
        logger.exception(f"Error marking insight seen: {e}")
        return False


def dismiss_proactive_insight(patient_id: str, insight_id: str) -> bool:
    """Mark an insight dismissed so it no longer shows on the dashboard."""
    try:
        supabase_admin.table('proactive_insights').update({
            'dismissed_at': datetime.utcnow().isoformat()
        }).eq('id', insight_id).eq('patient_id', str(patient_id)).execute()
        return True
    except Exception as e:
        logger.exception(f"Error dismissing proactive insight: {e}")
        return False


def get_proactive_insights_for_provider(patient_id: str, days: int = 7) -> list:
    """Return recent undismissed proactive insights — used by provider dashboard."""
    try:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        res = (supabase_admin.table('proactive_insights')
               .select('id, pattern_type, insight_text, created_at, seen_at')
               .eq('patient_id', str(patient_id))
               .is_('dismissed_at', 'null')
               .gte('created_at', cutoff)
               .order('created_at', desc=True)
               .execute())
        return res.data if res.data else []
    except Exception as e:
        logger.exception(f"Error fetching provider proactive insights: {e}")
        return []


# ── What Worked Engine ────────────────────────────────────────────────────────

_WHAT_WORKED_MIN_CHECKINS   = 10   # minimum total check-ins to run analysis
_WHAT_WORKED_MIN_GOOD_DAYS  = 3    # minimum good days needed
_WHAT_WORKED_MIN_COVERAGE   = 3    # minimum good days a variable must appear on
_WHAT_WORKED_DELTA_THRESHOLD = 1.5 # minimum mean difference to surface a pattern

# Variables and their metadata: (extended_data key or special key, display label, unit, good_direction)
# good_direction: 'higher' means higher values → good days, 'lower' means lower → good days
_WHAT_WORKED_VARS = [
    ('sleep_hours',       'core',     'Sleep',              'hrs',    'higher'),
    ('exercise_minutes',  'extended', 'Exercise',           'min',    'higher'),
    ('social_quality',    'extended', 'Social Quality',     '/10',    'higher'),
    ('alcohol_units',     'extended', 'Alcohol',            'units',  'lower'),
    ('stim_load',         'score',    'Stim Load',          '/10',    'lower'),
    ('perceived_stress',  'extended', 'Perceived Stress',   '/10',    'lower'),
    ('workload_friction', 'extended', 'Workload Friction',  '/10',    'lower'),
    ('hydration',         'extended', 'Hydration',          '',       'higher'),  # bool → 0/1
    ('coping_any',        'computed', 'Coping Activity',    'days',   'higher'),  # any coping tool used
]


def _extract_what_worked_value(row: dict, key: str, source: str):
    """Extract a numeric value for a given variable from a scored check-in row.
    Returns float or None if not available."""
    if source == 'core':
        v = row.get(key)
    elif source == 'score':
        v = row.get(key)  # already in scores merged onto row
    elif source == 'extended':
        ext = row.get('extended_data') or {}
        if key == 'hydration':
            raw = ext.get('hydration')
            if raw is None:
                return None
            return 1.0 if (raw is True or str(raw).lower() in ('true', 'yes', '1')) else 0.0
        v = ext.get(key)
    elif source == 'computed':
        if key == 'coping_any':
            ext = row.get('extended_data') or {}
            used = any([
                ext.get('coping_breathing'),
                ext.get('coping_meditation'),
                ext.get('coping_movement'),
                ext.get('coping_journaling'),
                ext.get('coping_other'),
            ])
            return 1.0 if used else 0.0
        v = None
    else:
        v = None
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        logger.exception("_extract_what_worked_value failed")
        return None


def get_what_worked_patterns(patient_id: str, days: int = 60) -> dict | None:
    """
    Identify variables that co-occur with high-stability days.

    Returns None if insufficient data. Otherwise returns:
    {
        'good_day_count':      int,
        'total_days':          int,
        'good_day_threshold':  float,   # stability_score cutoff (75th percentile)
        'days_window':         int,
        'patterns': [
            {
                'variable':         str,    # internal key
                'label':            str,    # display label
                'unit':             str,
                'good_direction':   str,    # 'higher' | 'lower'
                'avg_good_days':    float,
                'avg_other_days':   float,
                'delta':            float,  # abs(good - other)
                'good_day_coverage': int,   # how many good days had this variable logged
                'direction_match':  bool,   # delta aligns with good_direction
            },
            ...  # sorted by delta descending, direction_match first
        ]
    }
    """
    try:
        rows = _get_recent_scored_checkins(patient_id, days=days)
        if len(rows) < _WHAT_WORKED_MIN_CHECKINS:
            return None

        # Filter rows that have a stability_score
        scored = [r for r in rows if r.get('stability_score') is not None]
        if len(scored) < _WHAT_WORKED_MIN_CHECKINS:
            return None

        stability_vals = sorted([r['stability_score'] for r in scored])
        # 75th percentile threshold
        idx_75 = max(0, int(len(stability_vals) * 0.75) - 1)
        threshold = stability_vals[idx_75]

        good_days  = [r for r in scored if r['stability_score'] >= threshold]
        other_days = [r for r in scored if r['stability_score'] <  threshold]

        if len(good_days) < _WHAT_WORKED_MIN_GOOD_DAYS or len(other_days) < 3:
            return None

        patterns = []
        for (key, source, label, unit, good_direction) in _WHAT_WORKED_VARS:
            good_vals  = [_extract_what_worked_value(r, key, source) for r in good_days]
            other_vals = [_extract_what_worked_value(r, key, source) for r in other_days]

            good_vals  = [v for v in good_vals  if v is not None]
            other_vals = [v for v in other_vals if v is not None]

            if len(good_vals) < _WHAT_WORKED_MIN_COVERAGE or len(other_vals) < 2:
                continue

            avg_good  = round(sum(good_vals)  / len(good_vals),  2)
            avg_other = round(sum(other_vals) / len(other_vals), 2)
            delta     = round(abs(avg_good - avg_other), 2)

            if delta < _WHAT_WORKED_DELTA_THRESHOLD:
                continue

            # Does the direction match what we'd expect?
            direction_match = (
                (good_direction == 'higher' and avg_good > avg_other) or
                (good_direction == 'lower'  and avg_good < avg_other)
            )

            patterns.append({
                'variable':          key,
                'label':             label,
                'unit':              unit,
                'good_direction':    good_direction,
                'avg_good_days':     avg_good,
                'avg_other_days':    avg_other,
                'delta':             delta,
                'good_day_coverage': len(good_vals),
                'direction_match':   direction_match,
            })

        # Sort: direction_match first, then by delta descending
        patterns.sort(key=lambda p: (not p['direction_match'], -p['delta']))

        return {
            'good_day_count':     len(good_days),
            'total_days':         len(scored),
            'good_day_threshold': round(threshold, 2),
            'days_window':        days,
            'patterns':           patterns,
        }

    except Exception as e:
        logger.exception(f"Error in get_what_worked_patterns: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════
# APPOINTMENT SYNTHESIS — Bidirectional pre/post behavioral comparison
# ═══════════════════════════════════════════════════════════════════════════

def get_appointment_synthesis(patient_id: str, appt_id: str) -> dict | None:
    """
    Build a pre/post behavioral comparison around an appointment date.

    Pulls scored check-ins from 14 days before and 14 days after the
    appointment, computes per-metric averages for each window, and returns
    the comparison alongside raw session notes and care plan text so callers
    can decide what to surface to each audience (provider vs. patient).

    Returns:
        {
            'appt_date':     ISO date string,
            'pre':           {mood, sleep_hours, stress, energy, stability,
                              crash_risk, n} or None,
            'post':          same shape or None,
            'deltas':        {key: post_val - pre_val} (omits keys where
                              either window lacks data),
            'has_post_data': bool — True if post window has ≥3 check-ins,
            'notes_text':    session notes (provider-only — strip before
                             passing to patient-facing AI),
            'care_plan_text':care plan changes text,
            'pre_window':    human-readable date range string,
            'post_window':   human-readable date range string,
        }
    Returns None on any error or if the appointment cannot be found.
    """
    try:
        # ── Fetch appointment row ────────────────────────────────────────
        resp = supabase_admin.table('provider_appointments').select('*').eq(
            'id', str(appt_id)).eq('patient_id', str(patient_id)).limit(1).execute()
        if not resp.data:
            return None
        appt = resp.data[0]

        appt_date_str = (appt.get('started_at') or datetime.utcnow().isoformat())[:10]
        try:
            appt_dt = date.fromisoformat(appt_date_str)
        except Exception:
            appt_dt = date.today()

        pre_start  = (appt_dt - timedelta(days=14)).isoformat()
        pre_end    = appt_date_str
        post_start = appt_date_str
        post_end   = (appt_dt + timedelta(days=14)).isoformat()

        # ── Fetch and score check-ins for each window ────────────────────
        def _fetch_scored_window(start: str, end: str) -> list:
            rows = get_checkins_in_range(patient_id, start, end)
            scored = []
            for row in rows:
                ext   = row.get('extended_data') or {}
                meds  = row.get('medications') or []
                scores = _compute_checkin_scores(
                    row.get('mood_score'), row.get('stress_score'),
                    row.get('sleep_hours'), ext, meds,
                )
                scored.append({**row, **scores})
            return scored

        pre_checkins  = _fetch_scored_window(pre_start, pre_end)
        post_checkins = _fetch_scored_window(post_start, post_end)

        # ── Compute per-metric averages ─────────────────────────────────
        # Each tuple: (row_key_after_score_merge, output_key)
        # mood_score/stress_score come from raw row; stability_score/crash_risk
        # come from _compute_checkin_scores merge; sleep_hours/energy from raw row.
        _SYNTH_METRICS = [
            ('mood_score',      'mood'),
            ('sleep_hours',     'sleep_hours'),
            ('stress_score',    'stress'),
            ('energy',          'energy'),
            ('stability_score', 'stability'),
            ('crash_risk',      'crash_risk'),
        ]

        def _avg_window(checkins: list) -> dict | None:
            if not checkins:
                return None
            result: dict = {'n': len(checkins)}
            for src_key, out_key in _SYNTH_METRICS:
                vals = [c[src_key] for c in checkins
                        if c.get(src_key) is not None]
                result[out_key] = round(sum(vals) / len(vals), 2) if vals else None
            return result

        pre  = _avg_window(pre_checkins)
        post = _avg_window(post_checkins)

        # ── Compute deltas (post − pre) ──────────────────────────────────
        deltas: dict = {}
        if pre and post:
            for _src_key, out_key in _SYNTH_METRICS:
                pre_val  = pre.get(out_key)
                post_val = post.get(out_key)
                if pre_val is not None and post_val is not None:
                    deltas[out_key] = round(post_val - pre_val, 2)

        # ── Parse guided Q&A (answered questions only) ──────────────────
        raw_qa = appt.get('guided_qa') or '[]'
        if isinstance(raw_qa, str):
            try:
                raw_qa = json.loads(raw_qa)
            except Exception:
                logger.exception("_avg_window failed")
                raw_qa = []
        answered_qa = [
            item for item in (raw_qa if isinstance(raw_qa, list) else [])
            if item.get('answer') and str(item['answer']).strip()
        ]

        return {
            'appt_date':      appt_date_str,
            'pre':            pre,
            'post':           post,
            'deltas':         deltas,
            'has_post_data':  bool(post and post.get('n', 0) >= 3),
            'notes_text':     (appt.get('notes') or '').strip(),
            'care_plan_text': (appt.get('care_plan_changes') or '').strip(),
            'guided_qa':      answered_qa,
            'pre_window':     f"{pre_start} to {pre_end}",
            'post_window':    f"{post_start} to {post_end}",
        }

    except Exception as e:
        logger.debug(f"Error in get_appointment_synthesis: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════
# INTELLIGENCE LAYER — pivot_001_intelligence_layer
#
# These functions support the transcript-to-brief pipeline introduced in the
# CognaSync pivot. They operate on the tables defined in
# migrations/pivot_001_intelligence_layer.sql.
#
# Design contracts:
#   - supabase_admin for all writes (bypasses RLS; server-side only)
#   - All functions return None (or empty list) on failure, never raise
#   - IDs returned as str(uuid) for JSON serialisation safety
#   - Transcript text stored verbatim; features stored as JSONB
#   - Function names match app.py call sites exactly (grep-safe)
# ═══════════════════════════════════════════════════════════════════════════


def store_clinical_session(
    provider_id: str,
    patient_id: str,
    session_date: str,
    session_type: str,
    transcript_raw: str,
    duration_minutes: int | None = None,
    transcript_source: str = 'upload',
) -> str | None:
    """
    Create a clinical_sessions row and return its UUID.

    Processing status is set to 'pending' — the caller is responsible for
    calling store_session_features() once extraction completes.

    Returns the new session UUID as a str, or None on failure.
    """
    row = {
        'provider_id':       provider_id,
        'patient_id':        patient_id,
        'session_date':      session_date,
        'session_type':      session_type,
        'transcript_raw':    transcript_raw,
        'transcript_source': transcript_source,
        'processing_status': 'pending',
    }
    if duration_minutes is not None:
        row['duration_minutes'] = duration_minutes

    # Loggable copy — keep the constraint-relevant fields but don't dump the
    # full transcript text into logs.
    log_row = {**row, 'transcript_raw': f'<{len(transcript_raw or "")} chars>'}

    try:
        result = supabase_admin.table('clinical_sessions').insert(row).execute()
        data = result.data
        if data and len(data) > 0:
            return str(data[0]['id'])
        print(f"Error in store_clinical_session: insert returned no data row={log_row}")
        return None
    except Exception as e:
        logger.exception(f"Error in store_clinical_session: {e} row={log_row}")
        return None


def store_session_features(
    session_id: str,
    patient_id: str,
    extraction_result: dict,
    extraction_model: str | None = None,
) -> bool:
    """
    Persist extraction results from transcript_engine.extract_features()
    into session_features. Also updates clinical_sessions.processing_status.

    Args:
        session_id:         UUID of the clinical_sessions row.
        patient_id:         UUID of the patient.
        extraction_result:  Full dict returned by extract_features().
        extraction_model:   Model identifier used for extraction (optional).

    Returns True on success, False on failure.
    """
    try:
        crisis      = extraction_result.get('crisis_detected', False)
        features    = extraction_result.get('features') or {}
        scores      = extraction_result.get('scores') or {}
        safety_note = extraction_result.get('safety_note')

        safety_flags = {}
        if crisis:
            safety_flags['crisis_detected'] = True
            if safety_note:
                safety_flags['safety_note'] = safety_note

        feature_row = {
            'session_id':       session_id,
            'patient_id':       patient_id,
            'extracted':        features,
            'scores':           scores,
            'crisis_detected':  crisis,
            'safety_flags':     safety_flags,
        }
        if extraction_model:
            feature_row['extraction_model'] = extraction_model

        supabase_admin.table('session_features').insert(feature_row).execute()

        # Update parent session processing status
        new_status = 'error' if extraction_result.get('error') else 'complete'
        update_payload = {'processing_status': new_status}
        if extraction_result.get('error'):
            update_payload['processing_error'] = extraction_result['error']
        supabase_admin.table('clinical_sessions').update(update_payload).eq('id', session_id).execute()

        return True
    except Exception as e:
        logger.exception(f"Error in store_session_features: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# VOICE BASELINE — Three-phase individual baseline lifecycle
#
# Phase 1 (anchor): patient's first recording in a calm, regulated state.
# Phase 2 (training): next 5 qualifying recordings spread over >= 14 days.
# Phase 3 (standard): all subsequent recordings, compared against baseline.
#
# See voice_baseline_schema.sql for the voice_baselines table definition and
# the voice_recording_role column on clinical_sessions.
# ═══════════════════════════════════════════════════════════════════════════

import math as _math

_BASELINE_TRAINING_MIN      = 5
_BASELINE_TRAINING_MIN_DAYS = 14
_BASELINE_QUALITY_GATE      = {'good', 'fair'}
_PHASE2_GATES = {
    'articulation_rate_sps': 0.35,
    'f0_cv':                 0.45,
    'pause_ratio':           0.55,
}
_DEVIATION_Z_THRESHOLD   = 1.5
_DEVIATION_PCT_THRESHOLD = 0.20
_BASELINE_STALE_DAYS     = 180


def get_voice_baseline(patient_id: str) -> dict | None:
    """Return the active voice_baselines row for this patient, or None."""
    try:
        result = supabase_admin.table('voice_baselines') \
            .select('*') \
            .eq('patient_id', patient_id) \
            .in_('status', ['establishing', 'established', 'stale']) \
            .limit(1) \
            .execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logger.exception(f"Error in get_voice_baseline: {e}")
        return None


def determine_voice_recording_role(patient_id: str) -> str:
    """
    Determine the voice_recording_role for a new voice memo from this patient.
    Phase 1 (anchor): no baseline exists.
    Phase 2 (baseline training): baseline is 'establishing'.
    Phase 3 (standard): baseline is 'established' or 'stale'.
    """
    baseline = get_voice_baseline(patient_id)
    if baseline is None:
        return 'voice_memo_anchor'
    if baseline['status'] == 'establishing':
        return 'voice_memo_baseline'
    return 'voice_memo_standard'


def create_voice_baseline_from_anchor(
    patient_id: str,
    session_id: str,
    recorded_at: str,
    acoustic_features: dict,
) -> str | None:
    """
    Phase 1: create the voice_baselines row from an anchor recording.
    Cross-references check-in Stability Score to verify the patient's state.
    Returns new baseline UUID or None on failure.
    """
    try:
        stability_score, state_verified = _verify_anchor_state(patient_id, recorded_at)
        m = acoustic_features.get('measured') or {}
        row = {
            'patient_id':             patient_id,
            'status':                 'establishing',
            'anchor_session_id':      session_id,
            'anchor_recorded_at':     recorded_at,
            'anchor_stability_score': stability_score,
            'anchor_state_verified':  state_verified,
            'training_recordings_count': 0,
            'articulation_rate_mean': m.get('articulation_rate_sps'),
            'articulation_rate_sd':   0.0,
            'f0_cv_mean':             m.get('f0_cv'),
            'f0_cv_sd':               0.0,
            'pause_ratio_mean':       m.get('pause_ratio'),
            'pause_ratio_sd':         0.0,
            'f0_mean_hz_mean':        m.get('f0_mean_hz'),
            'f0_mean_hz_sd':          0.0,
            'rms_mean_mean':          m.get('rms_mean'),
            'rms_mean_sd':            0.0,
            'rms_cv_mean':            m.get('rms_cv'),
            'rms_cv_sd':              0.0,
            'hnr_db_mean':            m.get('hnr_db'),
            'hnr_db_sd':              0.0 if m.get('hnr_db') is not None else None,
            'jitter_local_mean':      m.get('jitter_local'),
            'jitter_local_sd':        0.0 if m.get('jitter_local') is not None else None,
            'shimmer_local_mean':     m.get('shimmer_local'),
            'shimmer_local_sd':       0.0 if m.get('shimmer_local') is not None else None,
        }
        result = supabase_admin.table('voice_baselines').insert(row).execute()
        if result.data:
            _tag_session_voice_role(session_id, 'voice_memo_anchor')
            return str(result.data[0]['id'])
        return None
    except Exception as e:
        logger.exception(f"Error in create_voice_baseline_from_anchor: {e}")
        return None


def _verify_anchor_state(patient_id: str, recorded_at: str) -> tuple:
    """
    Look up Stability Score on the anchor recording date.
    Returns (stability_score, verified). verified=True if score >= 7.0.
    """
    try:
        recording_date = recorded_at[:10]
        result = supabase_admin.table('checkins') \
            .select('stability_score') \
            .eq('user_id', patient_id) \
            .eq('check_in_date', recording_date) \
            .limit(1) \
            .execute()
        if not result.data:
            return None, False
        score = result.data[0].get('stability_score')
        if score is None:
            return None, False
        return float(score), float(score) >= 7.0
    except Exception as e:
        logger.exception(f"Error in _verify_anchor_state: {e}")
        return None, False


def add_baseline_training_recording(
    patient_id: str,
    session_id: str,
    recorded_at: str,
    acoustic_features: dict,
) -> tuple:
    """
    Phase 2: attempt to add this recording to the training window.
    Applies quality gate and anchor-deviation gate before accepting.
    Returns (voice_recording_role, promoted_to_established).
    """
    baseline = get_voice_baseline(patient_id)
    if baseline is None or baseline['status'] != 'establishing':
        return 'voice_memo_standard', False

    quality = acoustic_features.get('quality', 'poor')
    if quality not in _BASELINE_QUALITY_GATE:
        _tag_session_voice_role(session_id, 'voice_memo_excluded')
        return 'voice_memo_excluded', False

    if not _passes_anchor_deviation_gate(acoustic_features, baseline):
        _tag_session_voice_role(session_id, 'voice_memo_excluded')
        return 'voice_memo_excluded', False

    n = baseline['training_recordings_count'] + 2   # +1 anchor, +1 this
    updates = _welford_update_baseline(baseline, acoustic_features.get('measured') or {}, n)

    anchor_dt   = _parse_baseline_dt(baseline.get('anchor_recorded_at'))
    recorded_dt = _parse_baseline_dt(recorded_at)
    span_days   = (recorded_dt - anchor_dt).days if anchor_dt and recorded_dt else 0

    new_count = baseline['training_recordings_count'] + 1
    promoted  = new_count >= _BASELINE_TRAINING_MIN and span_days >= _BASELINE_TRAINING_MIN_DAYS
    updates.update({
        'training_recordings_count': new_count,
        'training_span_days':        span_days,
        'last_baseline_at':          recorded_at,
        'status':                    'established' if promoted else 'establishing',
    })

    try:
        supabase_admin.table('voice_baselines') \
            .update(updates) \
            .eq('id', baseline['id']) \
            .execute()
        _tag_session_voice_role(session_id, 'voice_memo_baseline')
        return 'voice_memo_baseline', promoted
    except Exception as e:
        logger.exception(f"Error in add_baseline_training_recording: {e}")
        return 'voice_memo_excluded', False


def _passes_anchor_deviation_gate(acoustic_features: dict, baseline: dict) -> bool:
    """Returns True if key features are within gate thresholds of the anchor mean."""
    m = acoustic_features.get('measured') or {}
    for feat_key, (bl_key, threshold) in {
        'articulation_rate_sps': ('articulation_rate_mean', _PHASE2_GATES['articulation_rate_sps']),
        'f0_cv':                 ('f0_cv_mean',             _PHASE2_GATES['f0_cv']),
        'pause_ratio':           ('pause_ratio_mean',       _PHASE2_GATES['pause_ratio']),
    }.items():
        current = m.get(feat_key)
        bl_val  = baseline.get(bl_key)
        if current is None or bl_val is None or bl_val == 0:
            continue
        if abs(current - bl_val) / abs(bl_val) > threshold:
            return False
    return True


def _welford_update_baseline(baseline: dict, measured: dict, n: int) -> dict:
    """Update baseline means and SDs using Welford's online algorithm."""
    feature_pairs = [
        ('articulation_rate_sps', 'articulation_rate_mean', 'articulation_rate_sd'),
        ('f0_cv',                 'f0_cv_mean',             'f0_cv_sd'),
        ('pause_ratio',           'pause_ratio_mean',       'pause_ratio_sd'),
        ('f0_mean_hz',            'f0_mean_hz_mean',        'f0_mean_hz_sd'),
        ('rms_mean',              'rms_mean_mean',          'rms_mean_sd'),
        ('rms_cv',                'rms_cv_mean',            'rms_cv_sd'),
        ('hnr_db',                'hnr_db_mean',            'hnr_db_sd'),
        ('jitter_local',          'jitter_local_mean',      'jitter_local_sd'),
        ('shimmer_local',         'shimmer_local_mean',     'shimmer_local_sd'),
    ]
    updates = {}
    for meas_key, mean_key, sd_key in feature_pairs:
        new_val  = measured.get(meas_key)
        old_mean = baseline.get(mean_key)
        old_sd   = baseline.get(sd_key) or 0.0
        if new_val is None or old_mean is None:
            continue
        new_mean = old_mean + (new_val - old_mean) / n
        M2_old   = (old_sd ** 2) * max(n - 2, 0)
        M2_new   = M2_old + (new_val - old_mean) * (new_val - new_mean)
        new_sd   = _math.sqrt(M2_new / (n - 1)) if n > 1 else 0.0
        updates[mean_key] = round(new_mean, 6)
        updates[sd_key]   = round(new_sd,   6)
    return updates


def compute_baseline_deviation(acoustic_features: dict, baseline: dict) -> str | None:
    """
    Phase 3: compute the baseline_deviation string for a standard recording.
    Returns None if no features exceed both z-score and percent thresholds.
    Language follows CLAUDE.md §24 — factual, no clinical interpretation.
    """
    if baseline is None or baseline.get('status') not in ('established', 'stale'):
        return None

    m = acoustic_features.get('measured') or {}
    feature_defs = [
        ('articulation_rate_sps', 'articulation_rate_mean', 'articulation_rate_sd',
         'Articulation rate', 'slower than', 'faster than'),
        ('f0_cv', 'f0_cv_mean', 'f0_cv_sd',
         'Pitch variability', 'lower than', 'higher than'),
        ('pause_ratio', 'pause_ratio_mean', 'pause_ratio_sd',
         'Pause ratio', 'below', 'above'),
        ('f0_mean_hz', 'f0_mean_hz_mean', 'f0_mean_hz_sd',
         'Mean pitch', 'lower than', 'higher than'),
        ('hnr_db', 'hnr_db_mean', 'hnr_db_sd',
         'Harmonic quality (HNR)', 'reduced from', 'elevated above'),
    ]
    parts = []
    for meas_key, mean_key, sd_key, label, dir_down, dir_up in feature_defs:
        current = m.get(meas_key)
        bl_mean = baseline.get(mean_key)
        bl_sd   = baseline.get(sd_key)
        if current is None or bl_mean is None or bl_mean == 0:
            continue
        pct_dev = (current - bl_mean) / abs(bl_mean)
        z_score = (current - bl_mean) / bl_sd if bl_sd and bl_sd > 0 else 0.0
        if abs(z_score) >= _DEVIATION_Z_THRESHOLD and abs(pct_dev) >= _DEVIATION_PCT_THRESHOLD:
            direction = dir_down if current < bl_mean else dir_up
            parts.append(
                f'{label} {abs(pct_dev):.0%} {direction} baseline '
                f'({abs(z_score):.1f} SD from baseline mean)'
            )
    if not parts:
        return None
    total = (baseline.get('training_recordings_count') or 0) + 1
    return '; '.join(parts) + f'. Based on {total} baseline recordings.'


def flag_baseline_stale(patient_id: str, reason: str,
                         medication_event_id: str | None = None) -> bool:
    """Flag the active baseline as stale. Preserves historical data."""
    try:
        payload = {
            'status':           'stale',
            'stale_reason':     reason,
            'stale_flagged_at': datetime.utcnow().isoformat(),
        }
        if medication_event_id:
            payload['stale_medication_event_id'] = medication_event_id
        supabase_admin.table('voice_baselines').update(payload) \
            .eq('patient_id', patient_id) \
            .in_('status', ['establishing', 'established']) \
            .execute()
        return True
    except Exception as e:
        logger.exception(f"Error in flag_baseline_stale: {e}")
        raise DataUnavailableError(f"Error in flag_baseline_stale", source="flag_baseline_stale")


def check_medication_event_for_baseline_impact(
    patient_id: str, medication_event_id: str, event_type: str
) -> None:
    """
    Call from medication event ingestion. Flags baseline stale on dose changes,
    new medications, or discontinuations. Timing shifts alone do not trigger this.
    """
    if event_type in ('dose_change', 'new_medication', 'discontinued'):
        baseline = get_voice_baseline(patient_id)
        if baseline and baseline['status'] in ('establishing', 'established'):
            flag_baseline_stale(patient_id, reason='medication_change',
                                medication_event_id=medication_event_id)


def get_voice_baseline_status_summary(patient_id: str) -> dict:
    """Provider-facing summary of the patient's baseline status for the hub template."""
    baseline = get_voice_baseline(patient_id)
    if baseline is None:
        return {
            'has_baseline': False,
            'status': 'none',
            'anchor_verified': False,
            'anchor_date': None,
            'recordings_in_baseline': 0,
            'training_progress': None,
            'stale_reason': None,
            'notice': (
                'No voice baseline established. '
                'Patient has not yet completed a Phase 1 anchor recording.'
            ),
        }

    status    = baseline['status']
    n_train   = baseline.get('training_recordings_count') or 0
    span_days = baseline.get('training_span_days') or 0
    anchor_date = (baseline.get('anchor_recorded_at') or '')[:10] or None

    notice = None
    if status == 'establishing':
        notice = (
            f'Voice baseline in progress: {n_train} of {_BASELINE_TRAINING_MIN} '
            f'training recordings collected over {span_days} of {_BASELINE_TRAINING_MIN_DAYS} days. '
            f'Acoustic comparisons will activate once the baseline is established.'
        )
    elif status == 'stale':
        reason_map = {
            'medication_change': 'a medication change',
            'time_elapsed':      f'more than {_BASELINE_STALE_DAYS} days without re-baselining',
            'manual_reset':      'a manual reset',
        }
        reason_text = reason_map.get(baseline.get('stale_reason'), 'an unknown reason')
        notice = (
            f'Voice baseline flagged as potentially outdated due to {reason_text}. '
            f'Acoustic comparisons are paused until the patient submits a new anchor recording.'
        )
    elif not baseline.get('anchor_state_verified'):
        notice = (
            f'Note: anchor recording state is unverified — no check-in data was available '
            f'for {anchor_date}. Acoustic comparisons are active but the anchor\'s '
            f'regulated state is not confirmed by check-in data.'
        )

    return {
        'has_baseline':           True,
        'status':                 status,
        'anchor_verified':        baseline.get('anchor_state_verified', False),
        'anchor_date':            anchor_date,
        'recordings_in_baseline': n_train + 1,
        'training_progress': (
            f'{n_train} of {_BASELINE_TRAINING_MIN} recordings '
            f'({span_days} of {_BASELINE_TRAINING_MIN_DAYS} days)'
        ),
        'stale_reason': baseline.get('stale_reason'),
        'notice':       notice,
    }


def _tag_session_voice_role(session_id: str, role: str) -> None:
    """Update clinical_sessions.voice_recording_role for a voice memo session."""
    try:
        supabase_admin.table('clinical_sessions') \
            .update({'voice_recording_role': role}) \
            .eq('id', session_id) \
            .execute()
    except Exception as e:
        logger.exception(f"Error tagging session voice role ({session_id} → {role}): {e}")


def _parse_baseline_dt(value):
    """Parse an ISO datetime string, returning None on failure."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        logger.exception("_parse_baseline_dt failed")
        return None


def get_patients_needing_anchor_recording() -> list:
    """
    Return active patients with no voice_baselines row at all.
    Used by the SMS trigger to send the baseline anchor prompt on their
    next scheduled voice SMS day.
    Returns [{patient_id, phone}, ...]
    """
    try:
        all_baselines = supabase_admin.table('voice_baselines').select('patient_id').execute()
        has_baseline  = {r['patient_id'] for r in (all_baselines.data or [])}

        result = supabase_admin.table('checkin_schedules') \
            .select('patient_id, patient_profiles!inner(phone_number)') \
            .execute()

        patients = []
        for row in (result.data or []):
            pid = row['patient_id']
            if pid in has_baseline:
                continue
            profile = row.get('patient_profiles') or {}
            phone   = profile.get('phone_number')
            if not phone:
                continue
            patients.append({'patient_id': pid, 'phone': phone})
        return patients
    except Exception as e:
        logger.exception(f"Error in get_patients_needing_anchor_recording: {e}")
        return []


def get_clinical_sessions_for_period(
    patient_id: str,
    period_start: str | None = None,
    period_end: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """
    Return clinical sessions with their extracted features for a patient.

    Each returned dict has the shape:
        {
            'session_id':    str,
            'session_date':  str,
            'session_type':  str,
            'duration_minutes': int | None,
            'transcript_source': str,
            'processing_status': str,
            'crisis_detected':   bool,
            'features':      dict,   # from session_features.extracted
            'scores':        dict,   # from session_features.scores
        }

    Sessions with processing_status != 'complete' are included so the
    caller can see what is in the pipeline.
    """
    try:
        q = (
            supabase_admin
            .table('clinical_sessions')
            .select('id, session_date, session_type, duration_minutes, transcript_source, processing_status, session_features(extracted, scores, crisis_detected)')
            .eq('patient_id', patient_id)
            .order('session_date', desc=True)
            .limit(limit)
        )
        if period_start:
            q = q.gte('session_date', period_start)
        if period_end:
            q = q.lte('session_date', period_end)

        result = q.execute()
        rows = result.data or []

        out = []
        for row in rows:
            sf = row.get('session_features') or {}
            feat_row = sf if isinstance(sf, dict) else (sf[0] if sf else {})
            out.append({
                'session_id':        str(row['id']),
                'session_date':      row.get('session_date'),
                'session_type':      row.get('session_type', 'other'),
                'duration_minutes':  row.get('duration_minutes'),
                'transcript_source': row.get('transcript_source', 'upload'),
                'processing_status': row.get('processing_status', 'pending'),
                'crisis_detected':   feat_row.get('crisis_detected', False),
                'features':          feat_row.get('extracted') or {},
                'scores':            feat_row.get('scores') or {},
            })
        return out
    except Exception as e:
        logger.exception(f"Error in get_clinical_sessions_for_period: {e}")
        return []


def store_provider_brief(
    patient_id: str,
    provider_id: str,
    brief_text: str,
    session_ids: list[str],
    period_start: str | None = None,
    period_end: str | None = None,
    scores: dict | None = None,
    crisis_detected: bool = False,
    brief_type: str = 'pre_visit',
    model_version: str | None = None,
    wearable_days: int = 0,
    voice_memo_count: int = 0,
) -> str | None:
    """
    Persist a generated Mode C provider brief to provider_briefs.
    Returns the new brief UUID as a str, or None on failure.
    """
    try:
        data_sources = {
            'sessions':         session_ids,
            'session_count':    len(session_ids),
            'wearable_days':    wearable_days,
            'voice_memos':      voice_memo_count,
        }
        row = {
            'patient_id':      patient_id,
            'provider_id':     provider_id,
            'brief_type':      brief_type,
            'content':         brief_text,
            'data_sources':    data_sources,
            'scores':          scores or {},
            'crisis_detected': crisis_detected,
            'session_count':   len(session_ids),
        }
        if period_start:
            row['period_start'] = period_start
        if period_end:
            row['period_end'] = period_end
        if model_version:
            row['model_version'] = model_version

        result = supabase_admin.table('provider_briefs').insert(row).execute()
        data = result.data
        if data and len(data) > 0:
            return str(data[0]['id'])
        return None
    except Exception as e:
        logger.exception(f"Error in store_provider_brief: {e}")
        return None


def get_provider_briefs_for_patient(
    provider_id: str,
    patient_id: str,
    limit: int = 5,
) -> list[dict]:
    """
    Return recent provider briefs for a patient, newest first.

    Each dict has: id, brief_type, period_start, period_end,
    session_count, crisis_detected, generated_at, content (truncated to 500 chars for list view).
    """
    try:
        result = (
            supabase_admin
            .table('provider_briefs')
            .select('id, brief_type, period_start, period_end, session_count, crisis_detected, generated_at, content, scores')
            .eq('provider_id', provider_id)
            .eq('patient_id', patient_id)
            .order('generated_at', desc=True)
            .limit(limit)
            .execute()
        )
        rows = result.data or []
        out = []
        for row in rows:
            out.append({
                'id':              str(row['id']),
                'brief_type':      row.get('brief_type', 'pre_visit'),
                'period_start':    row.get('period_start'),
                'period_end':      row.get('period_end'),
                'session_count':   row.get('session_count', 0),
                'crisis_detected': row.get('crisis_detected', False),
                'generated_at':    row.get('generated_at'),
                'scores':          row.get('scores') or {},
                'content':         row.get('content', ''),
            })
        return out
    except Exception as e:
        logger.exception(f"Error in get_provider_briefs_for_patient: {e}")
        raise DataUnavailableError(f"Error in get_provider_briefs_for_patient", source="get_provider_briefs_for_patient")


def record_brief_view(brief_id: str, provider_id: str) -> bool:
    """
    Insert a view event into provider_brief_views.
    Called as a side effect of get_provider_brief_by_id. Never raises.
    """
    try:
        supabase_admin.table('provider_brief_views').insert({
            'brief_id':   brief_id,
            'provider_id': provider_id,
            'viewed_at':  datetime.utcnow().isoformat(),
        }).execute()
        return True
    except Exception as e:
        logger.exception(f"Error in record_brief_view: {e}")
        return False


def get_provider_brief_by_id(brief_id: str, provider_id: str) -> dict | None:
    """
    Fetch a single brief by ID, verifying it belongs to the requesting provider.
    Returns None if not found or access denied.
    Records a view event as a side effect (never raises).
    """
    try:
        result = (
            supabase_admin
            .table('provider_briefs')
            .select('*')
            .eq('id', brief_id)
            .eq('provider_id', provider_id)
            .single()
            .execute()
        )
        row = result.data or None
        if row:
            record_brief_view(brief_id, provider_id)
        return row
    except Exception as e:
        logger.exception(f"Error in get_provider_brief_by_id: {e}")
        raise DataUnavailableError(f"Error in get_provider_brief_by_id", source="get_provider_brief_by_id")


def get_intel_patients_for_provider(provider_id: str) -> list[dict]:
    """
    Return patients who have at least one clinical_session recorded
    for this provider. Used to populate the intelligence dashboard patient list.

    Returns list of {patient_id, full_name, session_count, latest_session_date}.
    """
    try:
        result = (
            supabase_admin
            .table('clinical_sessions')
            .select('patient_id, session_date, profiles!clinical_sessions_patient_id_fkey(full_name)')
            .eq('provider_id', provider_id)
            .order('session_date', desc=True)
            .execute()
        )
        rows = result.data or []

        # Group by patient_id
        seen: dict[str, dict] = {}
        for row in rows:
            pid = str(row['patient_id'])
            if pid not in seen:
                name = ''
                profile = row.get('profiles')
                if isinstance(profile, dict):
                    name = profile.get('full_name', '')
                elif isinstance(profile, list) and profile:
                    name = profile[0].get('full_name', '')
                seen[pid] = {
                    'patient_id':          pid,
                    'full_name':           name,
                    'session_count':       0,
                    'latest_session_date': row.get('session_date'),
                }
            seen[pid]['session_count'] += 1

        return list(seen.values())
    except Exception as e:
        logger.exception(f"Error in get_intel_patients_for_provider: {e}")
        return []


def get_clinical_session_by_id(session_id: str) -> dict | None:
    """
    Fetch a single clinical session with its extracted features.
    Returns None if not found.
    """
    try:
        result = (
            supabase_admin
            .table('clinical_sessions')
            .select('id, patient_id, session_date, session_type, duration_minutes, transcript_source, processing_status, processing_error, session_features(extracted, scores, crisis_detected)')
            .eq('id', session_id)
            .single()
            .execute()
        )
        row = result.data
        if not row:
            return None
        feat_rows = row.get('session_features') or []
        feat_row  = feat_rows[0] if feat_rows else {}
        return {
            'session_id':        str(row['id']),
            'patient_id':        str(row['patient_id']) if row.get('patient_id') else None,
            'session_date':      row.get('session_date'),
            'session_type':      row.get('session_type', 'other'),
            'duration_minutes':  row.get('duration_minutes'),
            'transcript_source': row.get('transcript_source', 'upload'),
            'processing_status': row.get('processing_status', 'pending'),
            'processing_error':  row.get('processing_error'),
            'crisis_detected':   feat_row.get('crisis_detected', False),
            'features':          feat_row.get('extracted') or {},
            'scores':            feat_row.get('scores') or {},
        }
    except Exception as e:
        logger.exception(f"Error in get_clinical_session_by_id: {e}")
        return None


def update_clinical_session_status(
    session_id: str,
    status: str,
    error_message: str | None = None,
) -> bool:
    """
    Update processing_status (and optionally processing_error) on a clinical session.
    Used by the audio processing background thread to report progress.

    Valid statuses: 'pending', 'transcribing', 'extracting', 'complete', 'error'
    """
    try:
        payload = {'processing_status': status}
        if error_message:
            payload['processing_error'] = error_message
        supabase_admin.table('clinical_sessions').update(payload).eq('id', session_id).execute()
        return True
    except Exception as e:
        logger.exception(f"Error in update_clinical_session_status: {e}")
        return False


def store_session_transcript(
    session_id: str,
    transcript_text: str,
    audio_storage_path: str | None = None,
) -> bool:
    """
    Store the transcript text (produced by audio transcription) back on the
    clinical_sessions row. Also records the audio storage path if provided.
    """
    try:
        payload = {'transcript_raw': transcript_text}
        if audio_storage_path:
            # Store the path in transcript_json as metadata
            payload['transcript_json'] = {'audio_storage_path': audio_storage_path}
        supabase_admin.table('clinical_sessions').update(payload).eq('id', session_id).execute()
        return True
    except Exception as e:
        logger.exception(f"Error in store_session_transcript: {e}")
        return False


# ── Voice Note helpers ────────────────────────────────────────────────────────

def get_voice_notes_for_appointment(patient_id: str, appointment_id: str) -> list:
    """Return voice notes for a specific appointment."""
    try:
        res = supabase_admin.table('voice_notes').select('*').eq(
            'patient_id', patient_id
        ).eq('appointment_id', appointment_id).order('created_at', desc=True).execute()
        return res.data or []
    except Exception as e:
        logger.exception(f'[db] get_voice_notes_for_appointment error: {e}')
        return []


def get_voice_notes_for_patient(patient_id: str, limit: int = 10) -> list:
    """Return recent voice notes for a patient."""
    try:
        res = supabase_admin.table('voice_notes').select('*').eq(
            'patient_id', patient_id
        ).order('created_at', desc=True).limit(limit).execute()
        return res.data or []
    except Exception as e:
        logger.exception(f'[db] get_voice_notes_for_patient error: {e}')
        return []


def get_voice_notes_for_period(
    patient_id: str,
    period_start: str | None = None,
    period_end: str | None = None,
    limit: int = 20,
) -> list:
    """
    Return voice notes with transcripts for a patient within a date range.
    Used as a fallback when voice notes were processed before the pipeline
    created clinical_sessions rows — ensures they still surface in briefs.

    Returns rows from voice_notes where transcript IS NOT NULL.
    """
    try:
        q = (
            supabase_admin.table('voice_notes')
            .select('id, patient_id, created_at, transcript, guiding_question, audio_url')
            .eq('patient_id', patient_id)
            .not_.is_('transcript', 'null')
            .order('created_at', desc=True)
            .limit(limit)
        )
        if period_start:
            q = q.gte('created_at', period_start)
        if period_end:
            # Add one day to period_end so 'YYYY-MM-DD' includes the full day
            q = q.lte('created_at', period_end + 'T23:59:59')
        res = q.execute()
        return res.data or []
    except Exception as e:
        logger.exception(f'[db] get_voice_notes_for_period error: {e}')
        return []


def update_voice_note_transcript(
    voice_note_id: str,
    transcript: str,
    status: str = 'complete',
    error: str = None,
) -> bool:
    """Update transcript and status after transcription completes."""
    try:
        updates = {'processing_status': status, 'transcript': transcript}
        if error:
            updates['processing_error'] = error
        supabase_admin.table('voice_notes').update(updates).eq('id', voice_note_id).execute()
        return True
    except Exception as e:
        logger.exception(f'[db] update_voice_note_transcript error: {e}')


def update_medication_by_provider(provider_id: str, patient_id: str, med_id: str, updates: dict) -> dict:
    """
    Provider updates a patient's medication (dose, frequency, scheduled_times).
    Enforces provider–patient relationship; does NOT require psychiatrist role so
    any care-team member can edit.  Returns {'ok': True} or {'ok': False, 'error': '...'}.
    """
    allowed = {'standard_dose', 'dose_unit', 'frequency', 'scheduled_times', 'date_started', 'name', 'category'}
    payload = {k: v for k, v in updates.items() if k in allowed}
    if not payload:
        return {'ok': False, 'error': 'No valid fields to update.'}
    # Validate dose if present
    if 'standard_dose' in payload:
        try:
            payload['standard_dose'] = float(payload['standard_dose'])
            if payload['standard_dose'] <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return {'ok': False, 'error': 'Dose must be a positive number.'}
    try:
        supabase_admin.table('medications').update(payload).eq('id', med_id).eq('user_id', patient_id).execute()
        return {'ok': True}
    except Exception as e:
        logger.exception(f'[db] update_medication_by_provider error: {e}')
        return {'ok': False, 'error': 'Update failed.'}


def deactivate_medication_by_provider(provider_id: str, patient_id: str, med_id: str) -> bool:
    """Soft-delete a medication by setting is_active=False, enforcing patient ownership."""
    try:
        supabase_admin.table('medications').update({'is_active': False}).eq('id', med_id).eq('user_id', patient_id).execute()
        return True
    except Exception as e:
        logger.exception(f'[db] deactivate_medication_by_provider error: {e}')
        return False


def delete_voice_note(patient_id: str, note_id: str) -> bool:
    """Delete a voice note, enforcing ownership via patient_id."""
    try:
        supabase_admin.table('voice_notes').delete().eq('id', note_id).eq('patient_id', patient_id).execute()
        return True
    except Exception as e:
        logger.exception(f'[db] delete_voice_note error: {e}')
        return False


def delete_clinical_session(patient_id: str, session_id: str) -> bool:
    """Delete a clinical session row (cascades to session_features), enforcing ownership."""
    try:
        supabase_admin.table('clinical_sessions').delete().eq('id', session_id).eq('patient_id', patient_id).execute()
        return True
    except Exception as e:
        logger.exception(f'[db] delete_clinical_session error: {e}')
        return False


def delete_provider_brief(provider_id: str, brief_id: str) -> bool:
    """Delete a provider brief, enforcing ownership via provider_id."""
    try:
        supabase_admin.table('provider_briefs').delete().eq('id', brief_id).eq('provider_id', provider_id).execute()
        return True
    except Exception as e:
        logger.exception(f'[db] delete_provider_brief error: {e}')
        return False


# ═══════════════════════════════════════════════════════════════════════════
# TWILIO SMS — TOKEN LIFECYCLE
# Pre-authenticated single-use tokens that identify a patient in Twilio flows.
# Tokens are embedded in webhook POSTs and voice recording URLs.
# All operations use supabase_admin (service role) — token table is backend-only.
# ═══════════════════════════════════════════════════════════════════════════

def create_sms_token(
    patient_id: str,
    flow_type: str,
    metadata: dict | None = None,
    ttl_hours: int = 24,
) -> str | None:
    """
    Generate a pre-authenticated single-use token for a Twilio SMS flow.

    The token is a UUID v4 string. It is stored in sms_tokens with an
    expiry time and optional metadata (e.g. appointment_id, voice_prompt).

    Returns the token string, or None on failure.
    """
    import uuid as _uuid
    from datetime import timezone as _tz

    token = str(_uuid.uuid4())
    expires_at = (datetime.now(_tz.utc) + timedelta(hours=ttl_hours)).isoformat()

    try:
        supabase_admin.table('sms_tokens').insert({
            'token':      token,
            'patient_id': str(patient_id),
            'flow_type':  flow_type,
            'metadata':   metadata or {},
            'expires_at': expires_at,
        }).execute()
        return token
    except Exception as e:
        logger.exception(f'[db] create_sms_token error: {e}')
        return None


def validate_and_consume_token(token: str) -> dict | None:
    """
    Validate a token and mark it as used in a single atomic-like operation.

    Checks:
      - Token exists in sms_tokens
      - used_at is NULL (not yet consumed)
      - expires_at > now()

    On success, sets used_at = now() and returns:
      {'patient_id': str, 'flow_type': str, 'metadata': dict}

    Returns None if the token is invalid, expired, or already used.
    """
    from datetime import timezone as _tz

    if not token:
        return None

    try:
        now_iso = datetime.now(_tz.utc).isoformat()

        result = supabase_admin.table('sms_tokens') \
            .select('id, patient_id, flow_type, metadata, expires_at, used_at') \
            .eq('token', token) \
            .execute()

        if not result.data:
            print(f'[db] validate_token: not found token={token!r}')
            return None

        row = result.data[0]

        if row['used_at'] is not None:
            print(f'[db] validate_token: already used token={token!r}')
            return None

        if row['expires_at'] < now_iso:
            print(f'[db] validate_token: expired token={token!r}')
            return None

        # Mark consumed
        supabase_admin.table('sms_tokens') \
            .update({'used_at': now_iso}) \
            .eq('id', row['id']) \
            .execute()

        return {
            'patient_id': row['patient_id'],
            'flow_type':  row['flow_type'],
            'metadata':   row['metadata'] or {},
        }

    except Exception as e:
        logger.exception(f'[db] validate_and_consume_token error: {e}')
        return None


def validate_sms_token_readonly(token: str) -> dict | None:
    """
    Validate a briefing token without consuming it.

    Unlike validate_and_consume_token, this does not block access after
    first use. Records used_at on first open for analytics (with an IS NULL
    guard on the UPDATE to handle concurrent opens harmlessly).

    Returns {patient_id, flow_type, metadata} or None on invalid/expired.
    """
    from datetime import timezone as _tz

    if not token:
        return None

    try:
        now_iso = datetime.now(_tz.utc).isoformat()

        result = supabase_admin.table('sms_tokens') \
            .select('id, patient_id, flow_type, metadata, expires_at') \
            .eq('token', token) \
            .execute()

        if not result.data:
            print(f'[db] validate_token_readonly: not found token={token!r}')
            return None

        row = result.data[0]

        if row['expires_at'] < now_iso:
            print(f'[db] validate_token_readonly: expired token={token!r}')
            return None

        # Record first open for analytics. IS NULL guard prevents double-write
        # from concurrent opens (e.g., link preview + actual tap). A 0-row update
        # is an acceptable "already recorded" outcome — do not check the result.
        supabase_admin.table('sms_tokens') \
            .update({'used_at': now_iso}) \
            .eq('id', row['id']) \
            .is_('used_at', 'null') \
            .execute()

        return {
            'patient_id': row['patient_id'],
            'flow_type':  row['flow_type'],
            'metadata':   row['metadata'] or {},
        }

    except Exception as e:
        logger.exception(f'[db] validate_sms_token_readonly error: {e}')
        return None


# ═══════════════════════════════════════════════════════════════════════════
# TWILIO SMS — LOGGING
# ═══════════════════════════════════════════════════════════════════════════

def log_medication_adherence_from_sms(
    patient_id: str,
    adhered: bool,
    medication_name: str,
    responded_at: str | None = None,
) -> bool:
    """
    Log a medication adherence event received via Twilio SMS.

    Inserts a row into medication_events with source='sms'.
    Also checks for 3+ consecutive non-adherence days and sets a provider flag
    on patient_profiles if the threshold is crossed.

    Returns True on success, False on failure.
    """
    from datetime import timezone as _tz

    try:
        now_iso = responded_at or datetime.now(_tz.utc).isoformat()
        today = datetime.fromisoformat(now_iso.replace('Z', '+00:00')).date().isoformat()

        # Find the medication record for this patient + medication name
        med_result = supabase_admin.table('medications') \
            .select('id') \
            .eq('name', medication_name) \
            .limit(1) \
            .execute()

        medication_id = med_result.data[0]['id'] if med_result.data else None

        event_data = {
            'patient_id':    str(patient_id),
            'medication_id': medication_id,
            'taken':         adhered,
            'taken_at':      now_iso if adhered else None,
            'notes':         f'SMS adherence response: {"Y" if adhered else "N"}',
            'date':          today,
        }

        supabase_admin.table('medication_events').insert(event_data).execute()

        # Check consecutive non-adherence (3+ days) — flag for provider review
        if not adhered:
            _check_consecutive_non_adherence(patient_id, medication_id)

        return True

    except Exception as e:
        logger.exception(f'[db] log_medication_adherence_from_sms error: {e}')
        return False


def _check_consecutive_non_adherence(patient_id: str, medication_id: str | None) -> None:
    """
    Internal: check last 3 medication events for consecutive non-adherence.
    If 3+ consecutive misses, set a flag on patient_profiles for provider review.
    Non-response is treated the same as non-adherence (NULL taken_at with taken=False).
    """
    try:
        query = supabase_admin.table('medication_events') \
            .select('taken, date') \
            .eq('patient_id', str(patient_id)) \
            .order('date', desc=True) \
            .limit(3)

        if medication_id:
            query = query.eq('medication_id', str(medication_id))

        result = query.execute()
        events = result.data or []

        if len(events) >= 3 and all(not e.get('taken') for e in events):
            # 3+ consecutive misses — flag on patient profile
            supabase_admin.table('patient_profiles') \
                .update({'adherence_alert': True}) \
                .eq('user_id', str(patient_id)) \
                .execute()
            print(f'[db] Consecutive non-adherence flag set for patient={patient_id!r}')

    except Exception as e:
        logger.exception(f'[db] _check_consecutive_non_adherence error: {e}')


def log_checkin_from_sms(
    patient_id: str,
    data: dict,
    check_in_type: str = 'short',
) -> str | None:
    """
    Store a check-in received via Twilio SMS.

    data keys (all optional except those marked required):
      mood          (int, 1-10)  required for short/full
      sleep_hours   (float)      required for short/full
      stress        (int, 1-10)  required for short/full
      energy        (int, 1-10)  full only
      medication_note (str)      full only — free text from Q5 branch
      agenda_note   (str)        full only — Q6 response
      follow_up_note (str)       adaptive follow-up free text
      follow_up_type (str)       mood | stress | sleep | energy

    Runs _compute_checkin_scores() on the incoming data before storing.
    Sets silent flags based on threshold values.
    Returns checkin_id (str UUID) on success, None on failure.
    """
    from datetime import timezone as _tz

    try:
        now_iso = datetime.now(_tz.utc).isoformat()
        today = datetime.now(_tz.utc).date().isoformat()

        # Build checkin record — map SMS field names to existing schema columns
        checkin = {
            'user_id':        str(patient_id),
            'date':           today,
            'created_at':     now_iso,
            'source':         'sms',
            'check_in_type':  check_in_type,
        }

        # Core numeric fields
        if data.get('mood') is not None:
            checkin['mood'] = int(data['mood'])
        if data.get('sleep_hours') is not None:
            checkin['sleep_hours'] = float(data['sleep_hours'])
        if data.get('stress') is not None:
            checkin['stress_score'] = int(data['stress'])
        if data.get('energy') is not None:
            checkin['energy'] = int(data['energy'])

        # Adaptive follow-up
        if data.get('follow_up_note'):
            checkin['follow_up_note'] = str(data['follow_up_note'])[:1000]
        if data.get('follow_up_type'):
            checkin['follow_up_type'] = str(data['follow_up_type'])

        # Full check-in extras — stored in extended_data JSONB
        extended = {}
        if data.get('medication_note'):
            extended['medication_note'] = str(data['medication_note'])[:500]
        if data.get('agenda_note'):
            extended['agenda_note'] = str(data['agenda_note'])[:500]
        if extended:
            checkin['extended_data'] = extended

        # Compute behavioral scores using the existing deterministic engine
        scores = _compute_checkin_scores(checkin)
        checkin.update(scores)

        # Build silent flags based on thresholds
        flags = _compute_sms_flags(data)
        if flags:
            checkin['flags'] = flags

        result = supabase_admin.table('checkins').insert(checkin).execute()

        if result.data:
            checkin_id = result.data[0]['id']
            print(f'[db] SMS check-in stored id={checkin_id!r} type={check_in_type!r} patient={patient_id!r}')
            return checkin_id

        return None

    except Exception as e:
        logger.exception(f'[db] log_checkin_from_sms error: {e}')
        return None


def set_checkin_flags(checkin_id: str, flags: dict) -> bool:
    """
    Merge additional flags into an existing checkin's flags JSONB column.
    Safe to call multiple times — merges rather than overwrites.
    """
    try:
        # Fetch current flags first, then merge
        result = supabase_admin.table('checkins') \
            .select('flags') \
            .eq('id', str(checkin_id)) \
            .execute()

        current = (result.data[0].get('flags') or {}) if result.data else {}
        current.update(flags)

        supabase_admin.table('checkins') \
            .update({'flags': current}) \
            .eq('id', str(checkin_id)) \
            .execute()
        return True

    except Exception as e:
        logger.exception(f'[db] set_checkin_flags error: {e}')
        return False


def _compute_sms_flags(data: dict) -> dict:
    """
    Internal: derive silent provider flags from check-in values.
    These flags are stored in checkins.flags and surfaced on the provider dashboard.
    No patient-facing use.
    """
    flags = {}
    mood = data.get('mood')
    stress = data.get('stress')
    sleep = data.get('sleep_hours')
    energy = data.get('energy')

    if mood is not None:
        if int(mood) <= 2:
            flags['provider_review'] = True
            flags['tier1_watch'] = True
        elif int(mood) <= 3:
            flags['tier1_watch'] = True

    if stress is not None and int(stress) >= 8:
        flags['stress_flag'] = True

    if sleep is not None and float(sleep) <= 4:
        flags['sleep_flag'] = True

    if energy is not None and int(energy) <= 3:
        flags['low_energy_flag'] = True

    return flags


# ═══════════════════════════════════════════════════════════════════════════
# TWILIO SMS — SCHEDULING QUERIES
# These functions determine which patients should receive which SMS flows
# on a given run. Called by the internal trigger endpoints in app.py,
# which are themselves called by Render cron jobs.
# ═══════════════════════════════════════════════════════════════════════════

def get_patients_due_medication_sms(window_start: str, window_end: str) -> list:
    """
    Return patients whose medication dose time falls within [window_start, window_end]
    in their local timezone, and who haven't already received the medication SMS today.

    window_start / window_end: HH:MM strings in UTC (cron runs in UTC).

    Returns a list of dicts:
      [{patient_id, phone, medication_name, timezone, dose_time_local}, ...]

    The caller is responsible for timezone-aware comparison. We return the
    timezone so the Flask route can filter accurately before triggering.
    """
    try:
        # Join checkin_schedules with patient_profiles to get phone + medication
        result = supabase_admin.table('checkin_schedules') \
            .select(
                'patient_id, medication_dose_time, timezone, '
                'patient_profiles!inner(phone_number, current_medications)'
            ) \
            .not_.is_('medication_dose_time', 'null') \
            .execute()

        patients = []
        for row in (result.data or []):
            profile = row.get('patient_profiles') or {}
            meds = profile.get('current_medications') or []
            primary_med  = meds[0].get('name', 'medication') if meds else 'medication'
            primary_dose = meds[0].get('dose', '') if meds else ''

            patients.append({
                'patient_id':       row['patient_id'],
                'phone':            profile.get('phone_number'),
                'medication_name':  primary_med,
                'dose_str':         primary_dose,
                'timezone':         row['timezone'],
                'dose_time_local':  row['medication_dose_time'],
            })

        return [p for p in patients if p['phone']]  # exclude patients without phone

    except Exception as e:
        logger.exception(f'[db] get_patients_due_medication_sms error: {e}')
        raise DataUnavailableError(f'[db] get_patients_due_medication_sms error', source="get_patients_due_medication_sms")


def upsert_medication_schedule(patient_id: str, dose_time: str | None,
                               timezone: str = 'America/New_York',
                               checkin_days: list | None = None,
                               voice_days: list | None = None) -> bool:
    """Set (or clear) a patient's daily medication reminder + follow-up cadence.

    dose_time:    'HH:MM' string to enable the daily reminder, or None to disable it
                  (a null medication_dose_time excludes the patient from the send query).
    checkin_days: list of weekday ints (Mon=0..Sun=6) on which a check-in follow-up
                  is sent after the med text. None leaves the column unchanged.
    voice_days:   list of weekday ints on which a voice follow-up is sent. None leaves
                  the column unchanged.
    Upserts the patient's checkin_schedules row, keyed on patient_id.
    """
    try:
        row = {
            'patient_id':           str(patient_id),
            'medication_dose_time': dose_time,   # None clears it (disables reminder)
            'timezone':             timezone or 'America/New_York',
            'updated_at':           datetime.utcnow().isoformat(),
        }
        if checkin_days is not None:
            row['short_checkin_days'] = [int(d) for d in checkin_days]
        if voice_days is not None:
            row['voice_days'] = [int(d) for d in voice_days]
        supabase_admin.table('checkin_schedules').upsert(
            row, on_conflict='patient_id').execute()
        return True
    except Exception as e:
        logger.exception(f'[db] upsert_medication_schedule error: {e}')
        return False


def get_scheduled_med_patients() -> list:
    """Return every patient with a daily medication reminder configured.

    Returns dicts with the full daily-cadence schedule so the trigger can decide
    what to send:
      {patient_id, phone, medication_name, dose_str, dose_time_local,
       timezone, checkin_days, voice_days}
    Patients without a phone number are excluded.
    """
    try:
        # Two plain queries joined in Python — checkin_schedules has no FK to
        # patient_profiles, so a PostgREST embed can't resolve the relationship.
        sched = supabase_admin.table('checkin_schedules').select(
            'patient_id, medication_dose_time, timezone, short_checkin_days, voice_days'
        ).not_.is_('medication_dose_time', 'null').execute()
        rows = sched.data or []
        if not rows:
            return []

        ids = [r['patient_id'] for r in rows]
        profs = supabase_admin.table('patient_profiles').select(
            'user_id, phone_number, current_medications'
        ).in_('user_id', ids).execute()
        prof_map = {p['user_id']: p for p in (profs.data or [])}

        patients = []
        for row in rows:
            profile = prof_map.get(row['patient_id']) or {}
            if not profile.get('phone_number'):
                continue
            meds = profile.get('current_medications') or []
            patients.append({
                'patient_id':      row['patient_id'],
                'phone':           profile.get('phone_number'),
                'medication_name': meds[0].get('name', 'medication') if meds else 'medication',
                'dose_str':        meds[0].get('dose', '') if meds else '',
                'dose_time_local': row['medication_dose_time'],
                'timezone':        row['timezone'],
                'checkin_days':    row.get('short_checkin_days') or [],
                'voice_days':      row.get('voice_days') or [],
            })
        return patients
    except Exception as e:
        logger.exception(f'[db] get_scheduled_med_patients error: {e}')
        raise DataUnavailableError('[db] get_scheduled_med_patients error',
                                   source='get_scheduled_med_patients')


def get_patient_schedule(patient_id: str) -> dict | None:
    """Return a single patient's daily-cadence schedule, or None if not set.

    {dose_time_local, timezone, checkin_days, voice_days}
    """
    try:
        res = supabase_admin.table('checkin_schedules').select(
            'medication_dose_time, timezone, short_checkin_days, voice_days'
        ).eq('patient_id', str(patient_id)).limit(1).execute()
        if not res.data:
            return None
        row = res.data[0]
        return {
            'dose_time_local': row.get('medication_dose_time'),
            'timezone':        row.get('timezone') or 'America/New_York',
            'checkin_days':    row.get('short_checkin_days') or [],
            'voice_days':      row.get('voice_days') or [],
        }
    except Exception as e:
        logger.exception(f'[db] get_patient_schedule error: {e}')
        return None


def has_daily_send(patient_id: str, send_type: str, send_date: str) -> bool:
    """True if a daily SMS of this type was already recorded for this date."""
    try:
        res = supabase_admin.table('daily_sms_sends').select('id') \
            .eq('patient_id', str(patient_id)) \
            .eq('send_type', send_type) \
            .eq('send_date', send_date) \
            .limit(1).execute()
        return bool(res.data)
    except Exception as e:
        logger.exception(f'[db] has_daily_send error: {e}')
        return False  # fail-open: better a possible duplicate than a missed dose


def record_daily_send(patient_id: str, send_type: str, send_date: str) -> bool:
    """Record that a daily SMS of this type was sent (idempotent via UNIQUE).

    Returns True if a new row was inserted, False if it already existed (or error).
    Use the return value to claim the slot before sending, avoiding double-sends
    when the immediate-reply path and the cron fallback race.
    """
    try:
        res = supabase_admin.table('daily_sms_sends').insert({
            'patient_id': str(patient_id),
            'send_type':  send_type,
            'send_date':  send_date,
        }).execute()
        return bool(res.data)
    except Exception:
        # UNIQUE violation → already sent today; not an error worth raising
        return False


def log_medication_sms_sent(patient_id: str, medication_name: str,
                            scheduled_time: str, phone_number: str | None = None) -> str | None:
    """Insert a medication_sms_logs row at send time (replied_at stays null).

    The inbound Y/N handler later finds the most recent unreplied row for the
    patient and fills in taken/replied_at. Returns the new row id or None.
    """
    try:
        res = supabase_admin.table('medication_sms_logs').insert({
            'patient_id':     str(patient_id),
            'medication_name': medication_name,
            'scheduled_time': scheduled_time,
            'phone_number':   phone_number,
        }).execute()
        return res.data[0]['id'] if res.data else None
    except Exception as e:
        logger.exception(f'[db] log_medication_sms_sent error: {e}')
        return None


def get_patients_due_checkin_sms(check_in_type: str, target_date: date | None = None) -> list:
    """
    Return patients due for a short or full check-in SMS on target_date.

    For 'short': returns patients whose short_checkin_days includes the
                 weekday of target_date (ISO weekday: 0=Mon, 6=Sun).

    For 'full':  returns patients who have an appointment within the next
                 full_checkin_offset_hrs hours and haven't received a full
                 check-in trigger for that appointment yet.

    Returns a list of dicts:
      [{patient_id, phone, provider_name, appt_time, voice_link, token_metadata}, ...]
      (voice_link and provider_name are None for short check-ins)
    """
    from datetime import timezone as _tz

    if target_date is None:
        target_date = datetime.now(_tz.utc).date()

    try:
        if check_in_type == 'short':
            weekday = target_date.weekday()  # 0=Mon, 6=Sun

            result = supabase_admin.table('checkin_schedules') \
                .select(
                    'patient_id, short_checkin_days, timezone, '
                    'patient_profiles!inner(phone_number)'
                ) \
                .execute()

            patients = []
            for row in (result.data or []):
                days = row.get('short_checkin_days') or []
                if weekday not in days:
                    continue
                profile = row.get('patient_profiles') or {}
                phone = profile.get('phone_number')
                if not phone:
                    continue
                patients.append({
                    'patient_id':    row['patient_id'],
                    'phone':         phone,
                    'provider_name': None,
                    'appt_time':     None,
                })
            return patients

        elif check_in_type == 'full':
            # Look for appointments in the next 24-48 hours
            now = datetime.now(_tz.utc)
            window_start = now.isoformat()
            window_end = (now + timedelta(hours=48)).isoformat()

            # Query appointments table for upcoming appointments
            appt_result = supabase_admin.table('appointments') \
                .select(
                    'id, patient_id, provider_id, scheduled_at, '
                    'checkin_triggered, '
                    'profiles!provider_id(full_name), '
                    'patient_profiles!patient_id(phone_number)'
                ) \
                .gte('scheduled_at', window_start) \
                .lte('scheduled_at', window_end) \
                .eq('checkin_triggered', False) \
                .execute()

            patients = []
            for appt in (appt_result.data or []):
                phone = (appt.get('patient_profiles') or {}).get('phone_number')
                provider_name = (appt.get('profiles') or {}).get('full_name', 'your provider')
                if not phone:
                    continue
                patients.append({
                    'patient_id':    appt['patient_id'],
                    'phone':         phone,
                    'appt_id':       appt['id'],
                    'provider_name': provider_name,
                    'appt_time':     appt['scheduled_at'],
                })
            return patients

        return []

    except Exception as e:
        logger.exception(f'[db] get_patients_due_checkin_sms error: {e}')
        raise DataUnavailableError(f'[db] get_patients_due_checkin_sms error', source="get_patients_due_checkin_sms")


def get_patients_due_voice_sms(target_date: date | None = None) -> list:
    """
    Return patients due for a mid-week standalone voice recording SMS
    on target_date (defaults to today UTC).

    A patient is due if:
      - Their voice_day_of_week matches target_date's weekday
      - They haven't received a voice invite this calendar week
        (checked via sms_tokens: no 'voice' token created in the past 7 days)

    Returns [{patient_id, phone, provider_name, voice_prompt}, ...]
    Voice prompt defaults to the provider's default — provider lookup TBD in V2.
    """
    from datetime import timezone as _tz

    if target_date is None:
        target_date = datetime.now(_tz.utc).date()

    weekday = target_date.weekday()

    try:
        result = supabase_admin.table('checkin_schedules') \
            .select(
                'patient_id, voice_day_of_week, timezone, '
                'patient_profiles!inner(phone_number, provider_id)'
            ) \
            .eq('voice_day_of_week', weekday) \
            .execute()

        # Get patient IDs who already received a voice token this week
        week_start = (target_date - timedelta(days=weekday)).isoformat()
        recent_voice = supabase_admin.table('sms_tokens') \
            .select('patient_id') \
            .eq('flow_type', 'voice') \
            .gte('created_at', week_start) \
            .execute()
        already_sent = {r['patient_id'] for r in (recent_voice.data or [])}

        patients = []
        for row in (result.data or []):
            pid = row['patient_id']
            if pid in already_sent:
                continue
            profile = row.get('patient_profiles') or {}
            phone = profile.get('phone_number')
            if not phone:
                continue
            patients.append({
                'patient_id':   pid,
                'phone':        phone,
                'voice_prompt': 'How have you been feeling since your last appointment?',
            })

        return patients

    except Exception as e:
        logger.exception(f'[db] get_patients_due_voice_sms error: {e}')
        return []


def mark_appointment_checkin_triggered(appt_id: str) -> bool:
    """
    Mark an appointment's full check-in SMS as triggered to prevent double-firing.
    Called after successfully triggering Flow 3 for a patient.
    """
    try:
        supabase_admin.table('appointments') \
            .update({'checkin_triggered': True}) \
            .eq('id', str(appt_id)) \
            .execute()
        return True
    except Exception as e:
        logger.exception(f'[db] mark_appointment_checkin_triggered error: {e}')
        return False


# ── Linguistic Biomarker Analysis ─────────────────────────────────────────────

def compute_lexical_diversity(patient_id: str, days: int = 30) -> dict:
    """
    Compute Type-Token Ratio (TTR) across journal entries to measure vocabulary
    richness over time. Returns trend direction and delta for use in appointment
    summaries (CLAUDE.md §25).

    Returns dict with keys:
      type_token_ratio   — TTR across all words in the window (float)
      trend              — "improving" | "declining" | "stable" | "insufficient_data"
      entries_analyzed   — count of entries used
      earliest_ttr       — TTR in the first half of entries
      latest_ttr         — TTR in the second half of entries
      delta              — latest_ttr - earliest_ttr (negative = declining)

    Minimum 10 entries required; otherwise trend = "insufficient_data".
    """
    try:
        since = (datetime.utcnow() - timedelta(days=days)).date().isoformat()
        res = supabase_admin.table('journal_entries').select(
            'content, entry_date'
        ).eq('user_id', str(patient_id)).gte('entry_date', since).order(
            'entry_date', desc=False
        ).execute()
        entries = [e for e in (res.data or []) if e.get('content')]

        if len(entries) < 10:
            return {
                'type_token_ratio': None,
                'trend': 'insufficient_data',
                'entries_analyzed': len(entries),
                'earliest_ttr': None,
                'latest_ttr': None,
                'delta': None,
            }

        def _ttr(texts: list) -> float:
            words = []
            for t in texts:
                words.extend(re.findall(r"[a-z']+", t.lower()))
            if not words:
                return 0.0
            return round(len(set(words)) / len(words), 4)

        all_contents = [e['content'] for e in entries]
        mid = len(entries) // 2
        early_ttr = _ttr(all_contents[:mid])
        late_ttr  = _ttr(all_contents[mid:])
        overall   = _ttr(all_contents)
        delta     = round(late_ttr - early_ttr, 4)

        if abs(delta) < 0.10:
            trend = 'stable'
        elif delta > 0:
            trend = 'improving'
        else:
            trend = 'declining'

        return {
            'type_token_ratio': overall,
            'trend': trend,
            'entries_analyzed': len(entries),
            'earliest_ttr': early_ttr,
            'latest_ttr': late_ttr,
            'delta': delta,
        }
    except Exception as e:
        logger.debug(f'compute_lexical_diversity error: {e}')
        return {
            'type_token_ratio': None,
            'trend': 'insufficient_data',
            'entries_analyzed': 0,
            'earliest_ttr': None,
            'latest_ttr': None,
            'delta': None,
        }


def compute_readability(patient_id: str, days: int = 30) -> dict:
    """
    Estimate Flesch-Kincaid Grade Level trends across journal entries to detect
    shifts in writing complexity as a cognitive load proxy (CLAUDE.md §25).

    Uses a simplified FK formula: 0.39*(words/sentences) + 11.8*(syllables/words) - 15.59
    Syllables estimated by counting vowel groups.

    Returns dict with keys:
      avg_grade_level    — mean FK grade across all entries in window (float)
      trend              — "increasing" | "decreasing" | "stable" | "insufficient_data"
      earliest_grade     — mean grade in first half of entries
      latest_grade       — mean grade in second half
      delta              — latest_grade - earliest_grade (positive = more complex)
      entries_analyzed   — count of entries used

    Minimum 10 entries required; otherwise trend = "insufficient_data".
    Grade level shift of ≥2 points sustained across the window is clinically surfaceable.
    """
    try:
        since = (datetime.utcnow() - timedelta(days=days)).date().isoformat()
        res = supabase_admin.table('journal_entries').select(
            'content, entry_date'
        ).eq('user_id', str(patient_id)).gte('entry_date', since).order(
            'entry_date', desc=False
        ).execute()
        entries = [e for e in (res.data or []) if e.get('content')]

        if len(entries) < 10:
            return {
                'avg_grade_level': None,
                'trend': 'insufficient_data',
                'earliest_grade': None,
                'latest_grade': None,
                'delta': None,
                'entries_analyzed': len(entries),
            }

        def _syllables(word: str) -> int:
            word = word.lower()
            count = len(re.findall(r'[aeiouy]+', word))
            if word.endswith('e') and count > 1:
                count -= 1
            return max(1, count)

        def _fk_grade(text: str) -> float:
            sentences = max(1, len(re.findall(r'[.!?]+', text)))
            words_list = re.findall(r"[a-z']+", text.lower())
            if not words_list:
                return 8.0  # neutral default
            total_syllables = sum(_syllables(w) for w in words_list)
            word_count = len(words_list)
            return 0.39 * (word_count / sentences) + 11.8 * (total_syllables / word_count) - 15.59

        grades = [_fk_grade(e['content']) for e in entries]
        mid = len(grades) // 2
        early_avg = round(sum(grades[:mid]) / mid, 2)
        late_avg  = round(sum(grades[mid:]) / len(grades[mid:]), 2)
        overall   = round(sum(grades) / len(grades), 2)
        delta     = round(late_avg - early_avg, 2)

        if abs(delta) < 2.0:
            trend = 'stable'
        elif delta > 0:
            trend = 'increasing'
        else:
            trend = 'decreasing'

        return {
            'avg_grade_level': overall,
            'trend': trend,
            'earliest_grade': early_avg,
            'latest_grade': late_avg,
            'delta': delta,
            'entries_analyzed': len(entries),
        }
    except Exception as e:
        logger.debug(f'compute_readability error: {e}')
        return {
            'avg_grade_level': None,
            'trend': 'insufficient_data',
            'earliest_grade': None,
            'latest_grade': None,
            'delta': None,
            'entries_analyzed': 0,
        }


def compute_engagement_stats(patient_id, days=None, period_start=None, period_end=None):
    """Compute patient engagement and response metrics for a review period.

    Returns a dict with participation rate, gap analysis, and SMS response
    rate (when SMS prompts were sent). All fields are None-safe — callers
    should treat None as "not available" rather than zero.

    Parameters
    ----------
    patient_id    : UUID str
    days          : rolling window from today (used when period_start/end absent)
    period_start  : ISO date string (YYYY-MM-DD), inclusive
    period_end    : ISO date string (YYYY-MM-DD), inclusive
    """
    try:
        from datetime import date as _date, timedelta as _td

        # ── Resolve window boundaries ─────────────────────────────────────────
        today = _date.today()
        if period_start and period_end:
            start = _date.fromisoformat(period_start)
            end   = _date.fromisoformat(period_end)
        elif days:
            end   = today
            start = today - _td(days=days - 1)
        else:
            end   = today
            start = today - _td(days=13)   # default 14-day window

        period_days = (end - start).days + 1

        # ── Fetch check-ins in window ─────────────────────────────────────────
        resp = (supabase_admin.table('checkins')
                .select('checkin_date, source, check_in_type')
                .eq('user_id', str(patient_id))
                .gte('checkin_date', start.isoformat())
                .lte('checkin_date', end.isoformat())
                .order('checkin_date')
                .execute())
        rows = resp.data or []

        # ── Active-day set (distinct calendar days with ≥1 check-in) ─────────
        active_day_set = set()
        source_counts  = {'web': 0, 'sms': 0, 'manual': 0, 'unknown': 0}
        type_counts    = {'full': 0, 'short': 0, 'micro': 0, 'unknown': 0}
        for r in rows:
            d = (r.get('checkin_date') or '')[:10]
            if d:
                active_day_set.add(d)
            src = r.get('source') or 'unknown'
            source_counts[src if src in source_counts else 'unknown'] += 1
            ctype = r.get('check_in_type') or 'unknown'
            type_counts[ctype if ctype in type_counts else 'unknown'] += 1

        active_days        = len(active_day_set)
        participation_rate = round(active_days / period_days, 3) if period_days > 0 else 0.0

        # ── Gap analysis ──────────────────────────────────────────────────────
        # Walk every calendar day in the window; find runs of silence.
        all_dates = [(start + _td(days=i)).isoformat() for i in range(period_days)]
        gap_segments = []          # runs of ≥3 consecutive silent days
        max_consecutive_gap = 0
        run_start = None
        run_len   = 0

        for d in all_dates:
            if d not in active_day_set:
                if run_start is None:
                    run_start = d
                run_len += 1
            else:
                if run_len > 0:
                    if run_len > max_consecutive_gap:
                        max_consecutive_gap = run_len
                    if run_len >= 3:
                        gap_segments.append({
                            'start': run_start,
                            'end':   ((_date.fromisoformat(run_start) + _td(days=run_len - 1))
                                      .isoformat()),
                            'days':  run_len,
                        })
                run_start = None
                run_len   = 0

        # Handle a trailing gap that reaches the end of the window
        if run_len > 0:
            if run_len > max_consecutive_gap:
                max_consecutive_gap = run_len
            if run_len >= 3:
                gap_segments.append({
                    'start': run_start,
                    'end':   end.isoformat(),
                    'days':  run_len,
                })

        # ── Last check-in date + recency ──────────────────────────────────────
        sorted_dates      = sorted(active_day_set, reverse=True)
        last_checkin_date = sorted_dates[0] if sorted_dates else None
        days_since_last   = None
        if last_checkin_date:
            days_since_last = (today - _date.fromisoformat(last_checkin_date)).days

        # ── SMS engagement — aggregate + per-feature breakdown ───────────────
        # sms_tokens table: each row = one prompt sent; used_at = patient clicked link.
        # All flow types are fetched (medication, short, full, voice) so we can
        # detect selective non-response (responds to one feature but not another).
        # Aggregate metric for check-in flows (short/full/voice) is cross-referenced
        # with checkins.source='sms' for backward compatibility; per-flow metrics use
        # used_at IS NOT NULL as the universal response signal.
        sms_resp = (supabase_admin.table('sms_tokens')
                    .select('flow_type, used_at, created_at')
                    .eq('patient_id', str(patient_id))
                    .gte('created_at', start.isoformat())
                    .lte('created_at', (end + _td(days=1)).isoformat())  # inclusive end
                    .execute())
        sms_rows = sms_resp.data or []

        # Aggregate check-in prompt metrics (short/full/voice — cross-referenced with
        # checkins table where source='sms'; medication flow tracked separately below)
        checkin_prompt_rows = [r for r in sms_rows
                               if r.get('flow_type') in ('short', 'full', 'voice')]
        sms_prompts_sent    = len(checkin_prompt_rows)
        sms_responses       = source_counts.get('sms', 0)
        sms_response_rate   = None
        if sms_prompts_sent > 0:
            sms_response_rate = round(sms_responses / sms_prompts_sent, 3)

        # Per-flow-type breakdown: used_at IS NOT NULL = patient clicked through.
        # Also tracks unanswered_dates — the calendar dates on which a prompt of this
        # type was sent but never responded to. Used to give providers a specific list
        # of which days each channel went unanswered, rather than just totals.
        _FLOW_LABELS = {
            'medication': 'medication adherence',
            'short':      'short check-in',
            'full':       'full check-in',
            'voice':      'voice recording',
        }
        sms_by_flow: dict = {}
        for r in sms_rows:
            ft = r.get('flow_type') or 'unknown'
            if ft not in sms_by_flow:
                sms_by_flow[ft] = {
                    'sent':             0,
                    'responded':        0,
                    'response_rate':    0.0,
                    'label':            _FLOW_LABELS.get(ft, ft),
                    'unanswered_dates': [],   # ISO dates of unanswered prompts
                }
            sms_by_flow[ft]['sent'] += 1
            if r.get('used_at'):
                sms_by_flow[ft]['responded'] += 1
            else:
                # Record the calendar date this unanswered prompt was sent
                sent_date = (r.get('created_at') or '')[:10]
                if sent_date and sent_date not in sms_by_flow[ft]['unanswered_dates']:
                    sms_by_flow[ft]['unanswered_dates'].append(sent_date)
        for fs in sms_by_flow.values():
            fs['response_rate'] = (round(fs['responded'] / fs['sent'], 3)
                                   if fs['sent'] > 0 else 0.0)
            fs['unanswered_dates'].sort()   # chronological order

        # Divergence flag: ≥2 flow types each with ≥2 prompts sent, where the gap
        # between the highest and lowest response rate is ≥ 0.40 (40 percentage points).
        # This signals selective non-response — the patient is engaging with some
        # features but not others, which is a distinct clinical picture from total silence.
        sms_divergent = False
        eligible = [(ft, fs['response_rate'])
                    for ft, fs in sms_by_flow.items()
                    if fs['sent'] >= 2]
        if len(eligible) >= 2:
            rates = [rate for _, rate in eligible]
            if max(rates) - min(rates) >= 0.40:
                sms_divergent = True

        # ── Consecutive no-response streak (prompt-based) ─────────────────────
        # Walk prompt dates in chronological order and find the longest run of
        # consecutive calendar days where at least one prompt was sent AND none
        # were answered. Distinct from max_consecutive_gap (calendar-day silence)
        # because it only counts days the patient was actually prompted.
        # A 5+ day streak is the threshold for a provider-facing flag.
        all_prompt_dates = sorted({
            (r.get('created_at') or '')[:10]
            for r in sms_rows
            if (r.get('created_at') or '')[:10]
        })
        unanswered_prompt_date_set = set()
        for ft, fs in sms_by_flow.items():
            unanswered_prompt_date_set.update(fs['unanswered_dates'])

        max_prompt_gap   = 0          # longest run of consecutive unanswered-prompt days
        prompt_run_start = None
        prompt_run_len   = 0
        prompt_gap_segs  = []         # [{start, end, days}] for runs ≥ 5

        for d in all_prompt_dates:
            if d in unanswered_prompt_date_set:
                if prompt_run_start is None:
                    prompt_run_start = d
                prompt_run_len += 1
            else:
                if prompt_run_len > 0:
                    if prompt_run_len > max_prompt_gap:
                        max_prompt_gap = prompt_run_len
                    if prompt_run_len >= 5:
                        prompt_run_end = (
                            _date.fromisoformat(prompt_run_start)
                            + _td(days=prompt_run_len - 1)
                        ).isoformat()
                        prompt_gap_segs.append({
                            'start': prompt_run_start,
                            'end':   prompt_run_end,
                            'days':  prompt_run_len,
                        })
                prompt_run_start = None
                prompt_run_len   = 0
        # Trailing run
        if prompt_run_len > 0:
            if prompt_run_len > max_prompt_gap:
                max_prompt_gap = prompt_run_len
            if prompt_run_len >= 5:
                prompt_run_end = (
                    _date.fromisoformat(prompt_run_start)
                    + _td(days=prompt_run_len - 1)
                ).isoformat()
                prompt_gap_segs.append({
                    'start': prompt_run_start,
                    'end':   prompt_run_end,
                    'days':  prompt_run_len,
                })

        extended_no_response = max_prompt_gap >= 5   # hard flag for Mode C / Mode D

        # ── Overall SMS response rate across all flow types ───────────────────
        all_sms_sent      = sum(fs['sent'] for fs in sms_by_flow.values())
        all_sms_responded = sum(fs['responded'] for fs in sms_by_flow.values())
        overall_sms_rate  = (round(all_sms_responded / all_sms_sent, 3)
                             if all_sms_sent > 0 else None)

        # ── Insufficient-data flag ────────────────────────────────────────────
        # True when overall SMS response rate < 40%, meaning the briefing is
        # built from a minority of the expected data — providers should weigh
        # any pattern observations accordingly. Only applies when ≥3 prompts
        # were sent (avoids false-positive on patients who just enrolled).
        insufficient_data = (
            overall_sms_rate is not None
            and all_sms_sent >= 3
            and overall_sms_rate < 0.40
        )

        # ── Never-responded flag ──────────────────────────────────────────────
        # True when ≥3 prompts have been sent but zero have ever been answered.
        # Distinct from insufficient_data (which is <40% — some responses exist).
        # Signals a patient who enrolled but has never engaged with any SMS flow.
        never_responded = (
            all_sms_sent >= 3
            and all_sms_responded == 0
        )

        # ── Complete-absence flag ─────────────────────────────────────────────
        # Identifies days where BOTH conditions are true simultaneously:
        #   (a) a prompt was sent but went unanswered, AND
        #   (b) no check-in was logged.
        # This is stronger than either signal alone — the system reached out
        # and there was no response via any channel. Runs of ≥5 such days
        # are surfaced as a combined signal for providers.
        silent_day_set = set(all_dates) - active_day_set   # calendar days with no check-in
        completely_absent_days = sorted(
            silent_day_set & unanswered_prompt_date_set
        )

        complete_absence          = False
        complete_absence_segments = []
        max_complete_absence_gap  = 0

        if completely_absent_days:
            ca_run_start = None
            ca_run_len   = 0
            # Walk the full date list so consecutive gaps are detected correctly
            for d in all_dates:
                if d in set(completely_absent_days):
                    if ca_run_start is None:
                        ca_run_start = d
                    ca_run_len += 1
                else:
                    if ca_run_len > 0:
                        if ca_run_len > max_complete_absence_gap:
                            max_complete_absence_gap = ca_run_len
                        if ca_run_len >= 5:
                            ca_run_end = (
                                _date.fromisoformat(ca_run_start)
                                + _td(days=ca_run_len - 1)
                            ).isoformat()
                            complete_absence_segments.append({
                                'start': ca_run_start,
                                'end':   ca_run_end,
                                'days':  ca_run_len,
                            })
                    ca_run_start = None
                    ca_run_len   = 0
            # Trailing run
            if ca_run_len > 0:
                if ca_run_len > max_complete_absence_gap:
                    max_complete_absence_gap = ca_run_len
                if ca_run_len >= 5:
                    ca_run_end = (
                        _date.fromisoformat(ca_run_start)
                        + _td(days=ca_run_len - 1)
                    ).isoformat()
                    complete_absence_segments.append({
                        'start': ca_run_start,
                        'end':   ca_run_end,
                        'days':  ca_run_len,
                    })
            complete_absence = len(complete_absence_segments) > 0

        # ── Selective-divergence detail ───────────────────────────────────────
        # Pre-compute the high/low channel labels and rates for dashboard display,
        # avoiding repeated iteration in the template and _get_engagement_flags.
        sms_divergent_detail: dict | None = None
        if sms_divergent:
            eligible_flows = [
                (ft, fs) for ft, fs in sms_by_flow.items() if fs['sent'] >= 2
            ]
            eligible_flows.sort(key=lambda x: x[1]['response_rate'], reverse=True)
            high_ft, high_fs = eligible_flows[0]
            low_ft,  low_fs  = eligible_flows[-1]
            sms_divergent_detail = {
                'high_label': high_fs['label'],
                'high_rate':  round(high_fs['response_rate'] * 100),
                'low_label':  low_fs['label'],
                'low_rate':   round(low_fs['response_rate'] * 100),
            }

        # ── Clean up zero-count keys ──────────────────────────────────────────
        source_breakdown = {k: v for k, v in source_counts.items() if v > 0}
        type_breakdown   = {k: v for k, v in type_counts.items() if v > 0}

        return {
            'period_days':                period_days,
            'active_days':                active_days,
            'participation_rate':         participation_rate,        # 0.0–1.0
            'max_consecutive_gap':        max_consecutive_gap,       # calendar-day gap
            'gap_segments':               gap_segments,              # [{start, end, days}] ≥3d
            'last_checkin_date':          last_checkin_date,
            'days_since_last':            days_since_last,
            'sms_prompts_sent':           sms_prompts_sent,          # short/full/voice only
            'sms_responses':              sms_responses,
            'sms_response_rate':          sms_response_rate,         # None if no prompts
            'sms_by_flow':                sms_by_flow,               # per-feature breakdown + unanswered_dates
            'sms_divergent':              sms_divergent,             # True if selective non-response
            'sms_divergent_detail':       sms_divergent_detail,      # {high_label, high_rate, low_label, low_rate} or None
            'max_prompt_gap':             max_prompt_gap,            # longest consecutive unanswered-prompt days
            'prompt_gap_segments':        prompt_gap_segs,           # [{start, end, days}] ≥5d prompt streaks
            'extended_no_response':       extended_no_response,      # True if max_prompt_gap ≥ 5
            'overall_sms_rate':           overall_sms_rate,          # rate across all flow types
            'insufficient_data':          insufficient_data,         # True if overall rate < 40%
            'never_responded':            never_responded,           # True if ≥3 prompts sent, 0 answered
            'complete_absence':           complete_absence,          # True if ≥5-day overlap of calendar gap + unanswered prompts
            'complete_absence_segments':  complete_absence_segments, # [{start, end, days}]
            'max_complete_absence_gap':   max_complete_absence_gap,
            'source_breakdown':           source_breakdown,
            'type_breakdown':             type_breakdown,
        }

    except Exception as e:
        logger.exception(f'compute_engagement_stats error: {e}')
        raise DataUnavailableError(f'compute_engagement_stats error', source="compute_engagement_stats")


# ═══════════════════════════════════════════════════════════════════════════
# SMS SESSION + CRISIS HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def get_sms_session(patient_id: str) -> dict | None:
    """Return the most recent unresolved SMS session for a patient, or None."""
    try:
        res = supabase_admin.table('sms_checkin_sessions') \
            .select('*') \
            .eq('patient_id', str(patient_id)) \
            .is_('resolved_at', 'null') \
            .order('sent_at', desc=True) \
            .limit(1) \
            .execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logger.exception(f'[db] get_sms_session error: {e}')
        return None


def set_sms_session(patient_id: str, session_type: str,
                    suspended_session_type: str | None = None,
                    metadata: dict | None = None) -> dict | None:
    """Resolve any existing open session then open a new one. Returns new row.

    metadata: optional JSONB payload — used by rotating_pending sessions to
    store {'checkin_id': str, 'rotating_fields': [field_name, ...],
           'rotating_index': int}.
    """
    try:
        resolve_sms_session(patient_id)
        row = {
            'patient_id':   str(patient_id),
            'session_type': session_type,
            'metadata':     metadata or {},
        }
        if suspended_session_type:
            row['suspended_session_type'] = suspended_session_type
        res = supabase_admin.table('sms_checkin_sessions').insert(row).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logger.exception(f'[db] set_sms_session error: {e}')
        return None


def resolve_sms_session(patient_id: str) -> None:
    """Mark all open sessions for a patient as resolved."""
    try:
        supabase_admin.table('sms_checkin_sessions') \
            .update({'resolved_at': datetime.utcnow().isoformat()}) \
            .eq('patient_id', str(patient_id)) \
            .is_('resolved_at', 'null') \
            .execute()
    except Exception as e:
        logger.exception(f'[db] resolve_sms_session error: {e}')


def log_sms_crisis(patient_id: str, source: str) -> str | None:
    """Insert a crisis event row. source = 'keyword' | 'help_branch'.
    Returns the new row id, or None on error."""
    try:
        res = supabase_admin.table('sms_crisis_events').insert({
            'patient_id': str(patient_id),
            'source':     source,
        }).execute()
        return res.data[0]['id'] if res.data else None
    except Exception as e:
        logger.exception(f'[db] log_sms_crisis error: {e}')
        return None


def mark_provider_notified(crisis_event_id: str, sms_sid: str | None = None) -> None:
    """Stamp provider_notified_at on a crisis event after the alert SMS is sent."""
    try:
        update = {'provider_notified_at': datetime.utcnow().isoformat()}
        if sms_sid:
            update['provider_sms_sid'] = sms_sid
        supabase_admin.table('sms_crisis_events') \
            .update(update) \
            .eq('id', str(crisis_event_id)) \
            .execute()
    except Exception as e:
        logger.exception(f'[db] mark_provider_notified error: {e}')


def get_sms_crisis_events(patient_id: str, limit: int = 10) -> list:
    """Return recent crisis events for a patient (for hub flags display)."""
    try:
        res = supabase_admin.table('sms_crisis_events') \
            .select('*') \
            .eq('patient_id', str(patient_id)) \
            .order('triggered_at', desc=True) \
            .limit(limit) \
            .execute()
        return res.data or []
    except Exception as e:
        logger.exception(f'[db] get_sms_crisis_events error: {e}')
        raise DataUnavailableError(f'[db] get_sms_crisis_events error', source="get_sms_crisis_events")


def get_provider_for_patient(patient_id: str) -> dict | None:
    """Return provider profile (id, phone_number, full_name) for a patient,
    or None if no active provider relationship exists."""
    try:
        rel = supabase_admin.table('provider_patient_relationships') \
            .select('provider_id') \
            .eq('patient_id', str(patient_id)) \
            .eq('status', 'active') \
            .limit(1) \
            .execute()
        if not rel.data:
            return None
        provider_id = rel.data[0]['provider_id']
        prof = supabase_admin.table('profiles') \
            .select('id, full_name, phone_number') \
            .eq('id', str(provider_id)) \
            .single() \
            .execute()
        return prof.data or None
    except Exception as e:
        logger.exception(f'[db] get_provider_for_patient error: {e}')
        return None


# ── Provider Focus Config ─────────────────────────────────────────────────────

def set_provider_focus_config(provider_id: str, patient_id: str,
                               focus_domains: list,
                               notes: str | None = None,
                               set_by_role: str | None = None,
                               weeks: int = 4) -> dict | None:
    """Create or replace the focus config for this provider-patient pair.

    Uses upsert on the UNIQUE(provider_id, patient_id) constraint so calling
    this a second time replaces rather than duplicates the record.
    expires_at is set to `weeks` weeks from now (default 4).
    """
    from datetime import timezone
    expires_at = (datetime.now(timezone.utc) + timedelta(weeks=weeks)).isoformat()
    data = {
        'provider_id':    str(provider_id),
        'patient_id':     str(patient_id),
        'focus_domains':  focus_domains,
        'notes':          notes,
        'set_by_role':    set_by_role,
        'expires_at':     expires_at,
    }
    try:
        res = supabase_admin.table('provider_focus_configs').upsert(
            data, on_conflict='provider_id,patient_id'
        ).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logger.exception(f'[db] set_provider_focus_config error: {e}')
        return None


def get_provider_focus_config(provider_id: str, patient_id: str) -> dict | None:
    """Return the active focus config for this provider-patient pair, or None.

    Returns None if no config exists or if it has expired.
    """
    from datetime import timezone
    now = datetime.now(timezone.utc).isoformat()
    try:
        res = supabase_admin.table('provider_focus_configs') \
            .select('*') \
            .eq('provider_id', str(provider_id)) \
            .eq('patient_id',  str(patient_id)) \
            .gt('expires_at', now) \
            .limit(1) \
            .execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logger.exception(f'[db] get_provider_focus_config error: {e}')
        return None


def get_all_focus_configs_for_patient(patient_id: str) -> list:
    """Return all active focus configs for a patient across the whole care team.

    Used by the care team tab to show each provider's current monitoring intent.
    Each row includes provider name and role via a join on profiles.
    """
    from datetime import timezone
    now = datetime.now(timezone.utc).isoformat()
    try:
        res = supabase_admin.table('provider_focus_configs') \
            .select('*, profiles!provider_focus_configs_provider_id_fkey(full_name, provider_type)') \
            .eq('patient_id', str(patient_id)) \
            .gt('expires_at', now) \
            .execute()
        return res.data or []
    except Exception as e:
        logger.exception(f'[db] get_all_focus_configs_for_patient error: {e}')
        return []


def clear_provider_focus_config(provider_id: str, patient_id: str) -> bool:
    """Delete the focus config for this provider-patient pair (manual clear)."""
    try:
        supabase_admin.table('provider_focus_configs') \
            .delete() \
            .eq('provider_id', str(provider_id)) \
            .eq('patient_id',  str(patient_id)) \
            .execute()
        return True
    except Exception as e:
        logger.exception(f'[db] clear_provider_focus_config error: {e}')
        return False


# ── Rotating question helpers ─────────────────────────────────────────────────

def get_patient_sms_checkin_count(patient_id: str) -> int:
    """Return the total number of SMS check-ins stored for this patient.

    Used as the checkin_index for rotating question slot selection — each
    check-in increments the index, which determines which rotating questions
    are sent as a follow-up that day.
    """
    try:
        res = supabase_admin.table('checkins') \
            .select('id', count='exact') \
            .eq('user_id', str(patient_id)) \
            .eq('source', 'sms') \
            .execute()
        return res.count or 0
    except Exception as e:
        logger.exception(f'[db] get_patient_sms_checkin_count error: {e}')
        raise DataUnavailableError(f'[db] get_patient_sms_checkin_count error', source="get_patient_sms_checkin_count")


def update_checkin_extended_data(checkin_id: str, field_dict: dict) -> bool:
    """Merge new fields into an existing checkin's extended_data JSONB column.

    Safe to call multiple times — merges rather than overwrites. Used to
    store rotating question responses after the main check-in has been saved.

    field_dict: e.g. {'irritability': 7, 'motivation': 4}
    """
    try:
        res = supabase_admin.table('checkins') \
            .select('extended_data') \
            .eq('id', str(checkin_id)) \
            .execute()

        current = {}
        if res.data:
            current = res.data[0].get('extended_data') or {}

        current.update(field_dict)

        supabase_admin.table('checkins') \
            .update({'extended_data': current}) \
            .eq('id', str(checkin_id)) \
            .execute()
        return True
    except Exception as e:
        logger.exception(f'[db] update_checkin_extended_data error: {e}')
        return False


def get_active_focus_domains_for_patient(patient_id: str) -> list:
    """Return the union of all active focus_domains across the patient's care team.

    Multiple providers may have set targets; this returns the combined list
    (deduplicated) for use by the rotating question selector.
    """
    from datetime import timezone as _tz
    now = datetime.now(_tz.utc).isoformat()
    try:
        res = supabase_admin.table('provider_focus_configs') \
            .select('focus_domains') \
            .eq('patient_id', str(patient_id)) \
            .gt('expires_at', now) \
            .execute()

        seen = set()
        combined = []
        for row in (res.data or []):
            for domain in (row.get('focus_domains') or []):
                if domain not in seen:
                    seen.add(domain)
                    combined.append(domain)
        return combined
    except Exception as e:
        logger.exception(f'[db] get_active_focus_domains_for_patient error: {e}')
        return []


# ── Patient briefing — domain labels and trend remapping ─────────────────────

_BRIEFING_DOMAIN_LABELS: dict[str, str | None] = {
    'mood':                'Mood patterns',
    'anxiety_stress':      'Stress and anxiety levels',
    'sleep':               'Sleep quality and duration',
    'energy_focus':        'Energy and focus',
    'medication_response': 'Medication response',
    'social_functioning':  'Social wellbeing',
    'irritability':        'Irritability patterns',
    'motivation':          'Motivation levels',
    'appetite_nutrition':  'Appetite and nutrition',
    'suicidality':         None,   # NEVER surface to patient — silently dropped
    # Unknown keys are also dropped (forward-compatible with new domain types)
}

# Maps _trend_stats() output strings to patient-facing vocabulary.
# 'insufficient_data' → None so the template renders no trend arrow.
_BRIEFING_TREND_REMAP: dict[str, str | None] = {
    'increasing':        'improving',
    'decreasing':        'declining',
    'stable':            'stable',
    'insufficient_data': None,
}


def get_briefing_data(patient_id: str) -> dict:
    """
    Assemble everything the patient briefing template needs in one call.

    Calls get_trends_data (14-day window), get_active_focus_domains_for_patient,
    and a profile name lookup. Returns a fully resolved dict safe to pass
    directly to briefing.html.

    Never raises — returns a zeroed structure on any failure so the route
    can always render (even if data is empty).
    """
    from datetime import timezone as _tz

    def _empty() -> dict:
        """Zeroed fallback — returned when get_trends_data fails or is None."""
        start_iso = (date.today() - timedelta(days=14)).isoformat()
        end_iso   = date.today().isoformat()
        return {
            'patient_first_name': 'there',
            'period_days':  14,
            'date_range':   {'start': start_iso, 'end': end_iso},
            'checkin_count': 0,
            'mood':   {'average': None, 'trend': None, 'daily_scores': [], 'dates': []},
            'sleep':  {'average': None, 'trend': None, 'daily_hours':  [], 'dates': []},
            'stress': {'average': None, 'trend': None, 'daily_scores': [], 'dates': []},
            'energy': {'average': None, 'trend': None, 'daily_scores': [], 'dates': []},
            'monitoring_targets': [],
            'generated_at': datetime.now(_tz.utc).isoformat(),
        }

    def _remap(raw: str | None) -> str | None:
        return _BRIEFING_TREND_REMAP.get(raw) if raw else None

    # ── 1. Trend data ────────────────────────────────────────────
    try:
        trends = get_trends_data(patient_id, days=14)
    except Exception as e:
        logger.debug(f'[db] get_briefing_data: get_trends_data failed: {e}')
        trends = None

    if not trends:
        return _empty()

    # ── 2. Patient first name ────────────────────────────────────
    first_name = 'there'
    try:
        prof = supabase_admin.table('profiles') \
            .select('full_name') \
            .eq('id', str(patient_id)) \
            .limit(1) \
            .execute()
        if prof.data and prof.data[0].get('full_name'):
            full = (prof.data[0]['full_name'] or '').strip()
            first_name = full.split()[0] if full else 'there'
    except Exception as e:
        logger.debug(f'[db] get_briefing_data: profile lookup failed: {e}')

    # ── 3. Monitoring targets ────────────────────────────────────
    try:
        raw_domains = get_active_focus_domains_for_patient(patient_id) or []
    except Exception as e:
        logger.debug(f'[db] get_briefing_data: focus domains failed: {e}')
        raw_domains = []

    monitoring_targets = []
    for domain in raw_domains:
        label = _BRIEFING_DOMAIN_LABELS.get(domain)  # None for suicidality or unknown keys
        if label is not None:
            monitoring_targets.append(label)

    # ── 4. Assemble ──────────────────────────────────────────────
    return {
        'patient_first_name': first_name,
        'period_days':        14,
        'date_range':         trends.get('date_range', {}),
        'checkin_count':      trends.get('checkin_count', 0),
        'mood': {
            'average':      trends['mood'].get('average'),
            'trend':        _remap(trends['mood'].get('trend')),
            'daily_scores': trends['mood'].get('daily_scores', []),
            'dates':        trends['mood'].get('dates', []),
        },
        'sleep': {
            'average':     trends['sleep'].get('average'),
            'trend':       _remap(trends['sleep'].get('trend')),
            'daily_hours': trends['sleep'].get('daily_hours', []),   # note: daily_hours not daily_scores
            'dates':       trends['sleep'].get('dates', []),
        },
        'stress': {
            'average':      trends['stress'].get('average'),
            'trend':        _remap(trends['stress'].get('trend')),
            'daily_scores': trends['stress'].get('daily_scores', []),
            'dates':        trends['stress'].get('dates', []),
        },
        'energy': {
            'average':      trends['energy'].get('average'),
            'trend':        _remap(trends['energy'].get('trend')),
            'daily_scores': trends['energy'].get('daily_scores', []),
            'dates':        trends['energy'].get('dates', []),
        },
        'monitoring_targets': monitoring_targets,
        'generated_at':       datetime.now(_tz.utc).isoformat(),
    }


# ── Weekly voice scheduling ───────────────────────────────────────────────────

# Maps normalized target name → (table, column) for trend detection.
# 'checkins' fields are top-level columns; 'extended_data' fields are JSONB.
_TREND_FIELD_MAP = {
    'mood':                ('checkins',     'mood_score'),
    'anxiety_stress':      ('checkins',     'stress_score'),
    'energy_focus':        ('checkins',     'energy'),
    'sleep':               ('checkins',     'sleep_hours'),
    'medication_response': ('extended_data', 'medication_effectiveness'),
    'social_functioning':  ('extended_data', 'social_quality'),
    'irritability':        ('extended_data', 'irritability'),
    'motivation':          ('extended_data', 'motivation'),
    'appetite_nutrition':  ('extended_data', 'appetite'),
}


def get_all_patients_for_weekly_voice() -> list:
    """Return all patients with a phone number who have not received a voice
    SMS token in the past 7 days.

    Replaces the old voice_day_of_week-based scheduler with a universal
    weekly cadence: every patient gets one voice prompt per week, sent
    whenever the cron fires.

    Returns [{patient_id, phone}, ...]
    """
    from datetime import timezone as _tz, timedelta as _td

    cutoff = (datetime.now(_tz.utc) - _td(days=7)).isoformat()

    try:
        # All patients with a phone number
        all_res = supabase_admin.table('patient_profiles') \
            .select('user_id, phone_number') \
            .neq('phone_number', None) \
            .neq('phone_number', '') \
            .execute()

        if not all_res.data:
            return []

        # Patients who already got a voice token this week
        recent_res = supabase_admin.table('sms_tokens') \
            .select('patient_id') \
            .eq('flow_type', 'voice') \
            .gte('created_at', cutoff) \
            .execute()
        already_sent = {r['patient_id'] for r in (recent_res.data or [])}

        return [
            {'patient_id': r['user_id'], 'phone': r['phone_number']}
            for r in all_res.data
            if r['user_id'] not in already_sent and r.get('phone_number')
        ]
    except Exception as e:
        logger.exception(f'[db] get_all_patients_for_weekly_voice error: {e}')
        return []


def get_all_patients_for_weekly_briefing() -> list:
    """Return all patients with a phone number who have not received a
    briefing SMS token in the past 7 days.

    Mirrors get_all_patients_for_weekly_voice but uses flow_type='briefing'.

    Returns [{patient_id, phone}, ...]
    """
    from datetime import timezone as _tz, timedelta as _td

    cutoff = (datetime.now(_tz.utc) - _td(days=7)).isoformat()

    try:
        all_res = supabase_admin.table('patient_profiles') \
            .select('user_id, phone_number') \
            .neq('phone_number', None) \
            .neq('phone_number', '') \
            .execute()

        if not all_res.data:
            return []

        recent_res = supabase_admin.table('sms_tokens') \
            .select('patient_id') \
            .eq('flow_type', 'briefing') \
            .gte('created_at', cutoff) \
            .execute()
        already_sent = {r['patient_id'] for r in (recent_res.data or [])}

        return [
            {'patient_id': r['user_id'], 'phone': r['phone_number']}
            for r in all_res.data
            if r['user_id'] not in already_sent and r.get('phone_number')
        ]
    except Exception as e:
        logger.exception(f'[db] get_all_patients_for_weekly_briefing error: {e}')
        raise DataUnavailableError(f'[db] get_all_patients_for_weekly_briefing error', source="get_all_patients_for_weekly_briefing")


def get_target_trend_for_voice(patient_id: str, focus_domains: list) -> str:
    """Detect the trend direction for the primary active monitoring target.

    Compares the average of the most recent 3 check-ins against the 3 before
    that for the primary target's field. Returns 'improving', 'declining', or
    'stable'. Falls back to 'stable' if there are fewer than 4 data points.

    Args:
        patient_id:    The patient's user ID.
        focus_domains: Raw target name list from provider_focus_configs.

    Returns:
        'improving' | 'declining' | 'stable'
    """
    import re as _re

    def _normalize(t):
        return _re.sub(r'[\s/\-]+', '_', t.strip().lower())

    # Find the first non-suicidality target with a trend field
    primary_field = None
    primary_source = None
    for domain in focus_domains:
        key = _normalize(domain)
        if key == 'suicidality':
            continue
        if key in _TREND_FIELD_MAP:
            primary_source, primary_field = _TREND_FIELD_MAP[key]
            break

    if not primary_field:
        return 'stable'

    try:
        if primary_source == 'checkins':
            res = supabase_admin.table('checkins') \
                .select(f'id, {primary_field}') \
                .eq('user_id', str(patient_id)) \
                .not_.is_(primary_field, 'null') \
                .order('created_at', desc=True) \
                .limit(6) \
                .execute()
            rows = res.data or []
            values = [r[primary_field] for r in rows
                      if r.get(primary_field) is not None]

        else:  # extended_data
            res = supabase_admin.table('checkins') \
                .select('id, extended_data') \
                .eq('user_id', str(patient_id)) \
                .not_.is_('extended_data', 'null') \
                .order('created_at', desc=True) \
                .limit(12) \
                .execute()
            values = []
            for row in (res.data or []):
                ext = row.get('extended_data') or {}
                if isinstance(ext, dict) and primary_field in ext:
                    v = ext[primary_field]
                    if v is not None:
                        values.append(float(v))
                if len(values) >= 6:
                    break

        if len(values) < 4:
            return 'stable'  # insufficient data

        recent = values[:3]
        older  = values[3:6]
        if not older:
            return 'stable'

        avg_recent = sum(recent) / len(recent)
        avg_older  = sum(older)  / len(older)
        delta = avg_recent - avg_older

        # For sleep and sleep_hours: higher = better (same direction as others)
        # For stress_score: higher = worse — invert direction
        if primary_field == 'stress_score':
            delta = -delta

        if delta > 0.5:
            return 'improving'
        if delta < -0.5:
            return 'declining'
        return 'stable'

    except Exception as e:
        logger.debug(f'[db] get_target_trend_for_voice error: {e}')
        return 'stable'
