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
    """Update patient profile."""
    try:
        supabase_admin.table('patient_profiles').update(kwargs).eq('user_id', str(user_id)).execute()
        return True
    except Exception as e:
        print(f"Error updating patient profile: {e}")
        return False


def assign_patient_to_provider(patient_user_id, provider_id):
    """Assign patient to provider."""
    try:
        supabase_admin.table('patient_profiles').update({'provider_id': str(provider_id)}).eq('user_id', str(patient_user_id)).execute()
        return True
    except Exception as e:
        print(f"Error assigning patient to provider: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# CHECK-INS
# ═══════════════════════════════════════════════════════════════════════════

def create_checkin(patient_id, date_str, time_of_day, mood_score, medications, sleep_hours, stress_score, symptoms, notes, checkin_type='on_demand', extended_data=None, ai_insights=None):
    """Create a new check-in."""
    try:
        checkin_data = {
            'user_id': str(patient_id),
            'checkin_date': date_str,
            'stability_score': mood_score,
            'notes': notes,
            'created_at': datetime.utcnow().isoformat()
        }
        
        response = supabase_admin.table('checkins').insert(checkin_data).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]['id']
        return None
    except Exception as e:
        print(f"Error creating checkin: {e}")
        return None


def update_checkin_insights(checkin_id, insights_text):
    """Update check-in with AI insights."""
    try:
        supabase_admin.table('checkins').update({'ai_insights': insights_text}).eq('id', str(checkin_id)).execute()
        return True
    except Exception as e:
        print(f"Error updating checkin insights: {e}")
        return False


def get_checkin_baseline(patient_id, days=7):
    """Get baseline scores for recent check-ins."""
    try:
        cutoff_date = (date.today() - timedelta(days=days)).isoformat()
        response = supabase_admin.table('checkins').select('stability_score').gte('checkin_date', cutoff_date).eq('user_id', str(patient_id)).execute()
        
        scores = [r['stability_score'] for r in response.data if r['stability_score'] is not None]
        
        def avg(lst):
            return round(sum(lst) / len(lst), 2) if lst else None
        
        return {
            'baseline': avg(scores),
            'count': len(scores)
        }
    except Exception as e:
        print(f"Error getting checkin baseline: {e}")
        return {'baseline': None, 'count': 0}


def get_checkins(patient_id, days=30):
    """Get all check-ins for a patient in the last N days."""
    try:
        cutoff_date = (date.today() - timedelta(days=days)).isoformat()
        response = supabase_admin.table('checkins').select('*').gte('checkin_date', cutoff_date).eq('user_id', str(patient_id)).order('checkin_date', desc=True).execute()
        
        return response.data if response.data else []
    except Exception as e:
        print(f"Error getting checkins: {e}")
        return []


def get_checkin_streak(patient_id):
    """Get current check-in streak."""
    try:
        response = supabase_admin.table('checkins').select('checkin_date').eq('user_id', str(patient_id)).order('checkin_date', desc=True).limit(10).execute()
        
        if not response.data:
            return 0
        
        streak = 0
        today = date.today()
        
        for i, row in enumerate(response.data):
            checkin_date = datetime.fromisoformat(row['checkin_date']).date() if isinstance(row['checkin_date'], str) else row['checkin_date']
            expected_date = today - timedelta(days=i)
            
            if checkin_date == expected_date:
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
    """Create a summary."""
    try:
        summary_data = {
            'user_id': str(patient_id),
            'summary_date': date.today().isoformat(),
            'content': summary_text,
            'created_at': datetime.utcnow().isoformat()
        }
        
        response = supabase_admin.table('summaries').insert(summary_data).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]['id']
        return None
    except Exception as e:
        print(f"Error creating summary: {e}")
        return None


def get_summaries(patient_id):
    """Get all summaries for a patient."""
    try:
        response = supabase_admin.table('summaries').select('*').eq('user_id', str(patient_id)).order('summary_date', desc=True).execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error getting summaries: {e}")
        return []


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

def get_provider_patients(provider_id):
    """Get all patients assigned to a provider."""
    try:
        response = supabase_admin.table('patient_profiles').select('user_id').eq('provider_id', str(provider_id)).execute()
        return [row['user_id'] for row in response.data] if response.data else []
    except Exception as e:
        print(f"Error getting provider patients: {e}")
        return []


def get_patient_detail(patient_id, days=30):
    """Get comprehensive patient data for provider view."""
    try:
        profile = get_patient_profile(patient_id)
        checkins = get_checkins(patient_id, days)
        journals = get_journals(patient_id, limit=20, shared_only=True)
        latest_summary = get_latest_summary(patient_id)
        
        return {
            'profile': profile,
            'checkins': checkins,
            'journals': journals,
            'latest_summary': latest_summary
        }
    except Exception as e:
        print(f"Error getting patient detail: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════
# TRENDS & ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════

def _linear_regression(values):
    """Calculate linear regression slope."""
    if not values or len(values) < 2:
        return None
    
    n = len(values)
    x_vals = list(range(n))
    x_mean = sum(x_vals) / n
    y_mean = sum(values) / n
    
    numerator = sum((x_vals[i] - x_mean) * (values[i] - y_mean) for i in range(n))
    denominator = sum((x_vals[i] - x_mean) ** 2 for i in range(n))
    
    if denominator == 0:
        return None
    
    slope = numerator / denominator
    return round(slope, 3)


def get_trends_data(user_id: str, days: int = 30):
    """Get aggregated trend data for a user."""
    try:
        start_date = (date.today() - timedelta(days=days)).isoformat()
        checkins = supabase_admin.table('checkins').select('*').eq('user_id', user_id).gte('checkin_date', start_date).execute()
        
        if not checkins.data:
            return {
                'user_id': user_id,
                'date_range': {'start': start_date, 'end': date.today().isoformat()},
                'total_checkins': 0,
                'average_stability': None,
                'average_dopamine': None,
                'average_nervous_system': None,
                'trend_direction': 'insufficient_data'
            }
        
        # Aggregate scores
        data = checkins.data
        avg_stability = sum([c.get('stability_score', 0) for c in data]) / len(data) if data else 0
        avg_dopamine = sum([c.get('dopamine_efficiency', 0) for c in data]) / len(data) if data else 0
        avg_nervous = sum([c.get('nervous_system_load', 0) for c in data]) / len(data) if data else 0
        
        return {
            'user_id': user_id,
            'date_range': {'start': start_date, 'end': date.today().isoformat()},
            'total_checkins': len(data),
            'average_stability': round(avg_stability, 2),
            'average_dopamine': round(avg_dopamine, 2),
            'average_nervous_system': round(avg_nervous, 2),
            'trend_direction': 'up' if data[-1].get('stability_score', 0) > avg_stability else 'down'
        }
    except Exception as e:
        print(f"Error getting trends: {e}")
        return None


def get_paired_values(patient_id, var_a, var_b, days=60):
    """Get paired values for correlation testing."""
    try:
        checkins = get_checkins(patient_id, days)
        
        pairs = []
        for c in checkins:
            val_a = c.get(var_a)
            val_b = c.get(var_b)
            
            if val_a is not None and val_b is not None:
                pairs.append((c['checkin_date'], val_a, val_b))
        
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
    """Analyze medication timing correlation with mood/stability."""
    try:
        checkins = get_checkins(patient_id, days)
        
        if not checkins:
            return None
        
        def _corr(pairs):
            if not pairs or len(pairs) < 2:
                return 0
            vals = [p[1] for p in pairs if p[1] is not None]
            if not vals:
                return 0
            return round(sum(vals) / len(vals), 2)
        
        return {
            'medication_consistency': _corr([(c['checkin_date'], c['stability_score']) for c in checkins]),
            'sample_size': len(checkins)
        }
    except Exception as e:
        print(f"Error getting medication timing stats: {e}")
        return None


def find_unexpected_pattern(patient_id, days=30):
    """Find unexpected patterns in patient data."""
    try:
        checkins = get_checkins(patient_id, days)
        
        if not checkins or len(checkins) < 5:
            return None
        
        stability_scores = [c['stability_score'] for c in checkins if c['stability_score'] is not None]
        
        if not stability_scores:
            return None
        
        avg_score = sum(stability_scores) / len(stability_scores)
        std_dev = (sum((s - avg_score) ** 2 for s in stability_scores) / len(stability_scores)) ** 0.5
        
        outliers = [s for s in stability_scores if abs(s - avg_score) > 2 * std_dev]
        
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