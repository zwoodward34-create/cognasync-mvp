"""
sms_engine.py — CognaSync SMS Layer

Handles:
  - Pre-authenticated check-in magic links sent via SMS
  - Medication adherence Y/N SMS reminders
  - Inbound SMS reply parsing (Twilio webhook)
  - Voice note prompt delivery

Required env vars:
  TWILIO_ACCOUNT_SID
  TWILIO_AUTH_TOKEN
  TWILIO_FROM_NUMBER   — E.164 format, e.g. +15005550006
  APP_BASE_URL         — e.g. https://cognasync.com (no trailing slash)
"""

import logging
import os
import requests as http_requests

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID', '')
TWILIO_AUTH_TOKEN  = os.environ.get('TWILIO_AUTH_TOKEN', '')
# Accept either name — .env.example uses TWILIO_PHONE_NUMBER, older deploys use TWILIO_FROM_NUMBER
TWILIO_FROM_NUMBER = (
    os.environ.get('TWILIO_PHONE_NUMBER') or
    os.environ.get('TWILIO_FROM_NUMBER') or
    ''
)
APP_BASE_URL       = os.environ.get('APP_BASE_URL', 'https://cognasync.com').rstrip('/')

DEFAULT_VOICE_PROMPTS = {
    'psychiatrist': (
        "How have you been feeling since your last appointment? "
        "Have you noticed any changes in how your medication is working?"
    ),
    'therapist': (
        "What's been on your mind most since our last session? "
        "Is there anything specific you'd like to make sure we get to today?"
    ),
    'counselor': (
        "What's been on your mind most since our last session? "
        "Is there anything specific you'd like to make sure we get to today?"
    ),
    'default': (
        "How have you been feeling since your last appointment? "
        "Is there anything you'd like to make sure you cover today?"
    ),
}

# ── Weekly voice prompt system ────────────────────────────────────────────────
# Used for the universal weekly voice recording sent to all active patients.
# Completely separate from DEFAULT_VOICE_PROMPTS (which are appointment-anchored).

GENERIC_WEEKLY_VOICE_PROMPT = (
    "How have you been doing this week? Take a minute to share whatever's "
    "been most present for you."
)

# Per-target prompts with three trend variants.
# Suicidality always uses GENERIC_WEEKLY_VOICE_PROMPT — never named directly.
# Keys are normalized target names (same as ROTATING_QUESTIONS).
TARGET_VOICE_PROMPTS = {
    'mood': {
        'default':   (
            "How has your mood been this week? "
            "Walk us through what you've been noticing."
        ),
        'improving': (
            "Your check-ins have been looking a bit brighter lately. "
            "Tell us how things have been feeling from your side."
        ),
        'declining': (
            "How have you been doing this week? "
            "Take your time — whatever you want to share is worth mentioning."
        ),
    },
    'anxiety_stress': {
        'default':   (
            "How have anxiety and stress been for you this week? "
            "Tell us what's been on your mind."
        ),
        'improving': (
            "Things seem to have been a bit calmer lately based on your check-ins. "
            "Tell us how the week felt."
        ),
        'declining': (
            "How has stress been for you this week? "
            "Take a minute to share what's been weighing on you."
        ),
    },
    'energy_focus': {
        'default':   (
            "How have your energy and focus been this week? "
            "Tell us what a typical day has felt like."
        ),
        'improving': (
            "Your energy scores have been looking stronger lately. "
            "Tell us how you've been feeling."
        ),
        'declining': (
            "How have you been doing with energy and focus this week? "
            "Whatever you've noticed is worth sharing."
        ),
    },
    'sleep': {
        'default':   (
            "How has sleep been going this week? "
            "Tell us about your nights."
        ),
        'improving': (
            "Sleep seems to have been improving based on your check-ins. "
            "Tell us how things have been."
        ),
        'declining': (
            "How has sleep been for you lately? "
            "Tell us what's been going on with your nights."
        ),
    },
    'medication_response': {
        'default':   (
            "How has your medication been feeling this week? "
            "Take a minute to share what you've been noticing."
        ),
        'improving': (
            "It sounds like things may be going well with your medication. "
            "Tell us how it's been working."
        ),
        'declining': (
            "How has your medication been feeling this week? "
            "Take your time — whatever you're noticing is worth sharing."
        ),
    },
    'social_functioning': {
        'default':   (
            "How have your social connections been this week? "
            "Tell us about the people in your life lately."
        ),
        'improving': (
            "It looks like social things may have been going a bit better. "
            "Tell us how you've been connecting with people."
        ),
        'declining': (
            "How have you been doing with social connection this week? "
            "Share whatever's been on your mind."
        ),
    },
    'irritability': {
        'default':   (
            "How has irritability been for you this week? "
            "Tell us what you've been noticing."
        ),
        'improving': (
            "Based on your check-ins, things may have been a bit smoother lately. "
            "Tell us how the week felt."
        ),
        'declining': (
            "How have you been doing this week? "
            "Take your time — whatever's been most present is worth sharing."
        ),
    },
    'motivation': {
        'default':   (
            "How has your motivation been this week? "
            "Tell us what's been driving you or holding you back."
        ),
        'improving': (
            "Your check-ins suggest motivation may be picking up. "
            "Tell us how things have been feeling."
        ),
        'declining': (
            "How have you been doing with motivation this week? "
            "Share whatever's been on your mind."
        ),
    },
    'appetite_nutrition': {
        'default':   (
            "How has your appetite been this week? "
            "Tell us what eating has looked like."
        ),
        'improving': (
            "Appetite seems to be looking better based on your check-ins. "
            "Tell us how things have been."
        ),
        'declining': (
            "How has your appetite been lately? "
            "Whatever you've been noticing is worth sharing."
        ),
    },
    'substance_use': {
        # Don't name the target — use generic prompt
        'default':   GENERIC_WEEKLY_VOICE_PROMPT,
        'improving': GENERIC_WEEKLY_VOICE_PROMPT,
        'declining': GENERIC_WEEKLY_VOICE_PROMPT,
    },
    'side_effects': {
        'default':   (
            "How have you been feeling physically this week? "
            "Tell us if anything has stood out."
        ),
        'improving': (
            "How have you been feeling physically this week? "
            "Tell us if anything has stood out."
        ),
        'declining': (
            "How have you been feeling physically this week? "
            "Take your time — anything you've noticed is worth mentioning."
        ),
    },
}


def get_voice_prompt_for_patient(focus_domains: list, trend: str = 'stable') -> str:
    """Select the right weekly voice prompt for a patient's active monitoring targets.

    Args:
        focus_domains: Raw target name strings from provider_focus_configs.
        trend: Direction of the primary target's metric — 'improving', 'declining',
               or 'stable'. Determined by the caller via get_target_trend_for_voice().

    Returns:
        The prompt string to use for this patient's weekly voice recording.

    Rules:
        - Suicidality target present → always GENERIC_WEEKLY_VOICE_PROMPT
        - Otherwise, the first active target that has a prompt in TARGET_VOICE_PROMPTS
          drives the prompt, using the trend variant
        - No matching target → GENERIC_WEEKLY_VOICE_PROMPT
    """
    normalized = [_normalize_target(d) for d in focus_domains]

    # Suicidality always gets the generic neutral prompt
    if 'suicidality' in normalized:
        return GENERIC_WEEKLY_VOICE_PROMPT

    variant = trend if trend in ('improving', 'declining') else 'default'

    for key in normalized:
        if key in TARGET_VOICE_PROMPTS:
            return TARGET_VOICE_PROMPTS[key][variant]

    return GENERIC_WEEKLY_VOICE_PROMPT


# ── Baseline anchor prompt ────────────────────────────────────────────────────
# Sent to patients who have not yet completed a Phase 1 anchor recording.
# Instructions are explicit: quiet environment, calm state, ~90 seconds, natural
# speech — these conditions matter for baseline validity.
BASELINE_ANCHOR_VOICE_PROMPT = (
    "We'd like to record your voice baseline — a short reference recording we use "
    "to personalize your acoustic tracking going forward.\n\n"
    "When you're ready: find a quiet spot, take a moment to settle, then press "
    "record and talk naturally for about 90 seconds. Tell us about something you've "
    "enjoyed recently, or whatever's on your mind — there are no right answers. "
    "Speak at your normal volume and pace. This recording works best when you're "
    "feeling calm and relaxed."
)


# ── Core send ─────────────────────────────────────────────────────────────────

def send_sms(to_number: str, body: str) -> dict:
    """Send an SMS via Twilio. Returns {'ok': bool, 'sid': str} or {'ok': False, 'error': str}."""
    print(f'[sms] send_sms called: to={to_number} from={TWILIO_FROM_NUMBER or "(not set)"} '
          f'sid_set={bool(TWILIO_ACCOUNT_SID)} token_set={bool(TWILIO_AUTH_TOKEN)}', flush=True)

    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER]):
        missing = [k for k, v in [
            ('TWILIO_ACCOUNT_SID', TWILIO_ACCOUNT_SID),
            ('TWILIO_AUTH_TOKEN', TWILIO_AUTH_TOKEN),
            ('TWILIO_PHONE_NUMBER', TWILIO_FROM_NUMBER),
        ] if not v]
        print(f'[sms] ERROR: missing env vars: {missing}', flush=True)
        return {'ok': False, 'error': f'Twilio not configured (missing: {", ".join(missing)})'}
    try:
        url = f'https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json'
        resp = http_requests.post(
            url,
            auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            data={'From': TWILIO_FROM_NUMBER, 'To': to_number, 'Body': body},
            timeout=10,
        )
        data = resp.json()
        sid    = data.get('sid', '')
        status = data.get('status', '')
        print(f'[sms] Twilio response: status={resp.status_code} sid={sid} msg_status={status}', flush=True)
        if resp.status_code in (200, 201):
            return {'ok': True, 'sid': sid, 'twilio_status': status}
        else:
            err = data.get('message', resp.text)
            code = data.get('code', '')
            print(f'[sms] Twilio error {resp.status_code} code={code}: {err}', flush=True)
            return {'ok': False, 'error': f'Twilio {resp.status_code}: {err}', 'twilio_code': code}
    except Exception as e:
        print(f'[sms] Exception in send_sms: {e}', flush=True)
        return {'ok': False, 'error': str(e)}


# ── Token creation ────────────────────────────────────────────────────────────

def create_checkin_token(
    patient_id: str,
    appointment_id: str | None = None,
    provider_id: str | None = None,
    voice_prompt: str | None = None,
    hours_valid: int = 48,
) -> str:
    """Insert a checkin_token row and return the token string."""
    from database import supabase_admin
    from datetime import datetime, timezone, timedelta

    expires_at = (datetime.now(timezone.utc) + timedelta(hours=hours_valid)).isoformat()
    row = {
        'patient_id':      patient_id,
        'token_type':      'checkin',
        'expires_at':      expires_at,
    }
    if appointment_id:
        row['appointment_id'] = appointment_id
    if provider_id:
        row['provider_id'] = provider_id
    if voice_prompt:
        row['voice_prompt'] = voice_prompt

    res = supabase_admin.table('checkin_tokens').insert(row).execute()
    return res.data[0]['token']


# ── Composed sends ────────────────────────────────────────────────────────────

def send_checkin_sms(
    to_number: str,
    patient_name: str,
    token: str,
    voice_prompt: str | None = None,
) -> dict:
    """Send the pre-appointment check-in link (and optional voice note link)."""
    first = patient_name.split()[0] if patient_name else 'there'
    checkin_url = f'{APP_BASE_URL}/checkin/go/{token}'

    body = (
        f'Hi {first}, your upcoming appointment check-in is ready.\n\n'
        f'Complete your check-in here: {checkin_url}\n\n'
        f'This link expires in 48 hours and can only be used once.'
    )
    result = send_sms(to_number, body)

    if voice_prompt and result.get('ok'):
        voice_url = f'{APP_BASE_URL}/voice/{token}'
        voice_body = (
            f'Your provider also has a question for you:\n\n'
            f'"{voice_prompt}"\n\n'
            f'Record a quick voice note here: {voice_url}'
        )
        voice_result = send_sms(to_number, voice_body)
        result['voice_sms'] = voice_result

    return result


def send_voice_invite_sms(
    to_number: str,
    patient_name: str,
    token: str,
    voice_prompt: str,
) -> dict:
    """Send a standalone, CognaSync-branded voice-note invite (link only).

    Used by the provider hub "Voice Question" action. Sends only the voice
    prompt — no check-in link — so the two flows stay distinct.
    """
    first = patient_name.split()[0] if patient_name else 'there'
    voice_url = f'{APP_BASE_URL}/voice/{token}'
    body = (
        f'CognaSync: Hi {first}, your provider has a question for you:\n\n'
        f'"{voice_prompt}"\n\n'
        f'Record a quick voice note here: {voice_url}'
    )
    return send_sms(to_number, body)


def send_medication_sms(
    to_number: str,
    patient_name: str,
    medication_name: str,
    dose_str: str,
) -> dict:
    """Send a daily medication adherence reminder."""
    body = (
        f'CognaSync: Time for your {medication_name} {dose_str}. '
        f'Reply Y if taken, N if skipped.'
    )
    return send_sms(to_number, body)


# ── Reply parsing ─────────────────────────────────────────────────────────────

# Fallback crisis keywords — only used if the canonical matcher can't be
# imported. The authoritative, evasion-resistant list and normalization live in
# claude_api (single source of truth, spec §10). See detect_crisis_keywords.
_CRISIS_KEYWORDS_FALLBACK = (
    'suicide', 'suicidal', 'kill myself', 'end my life', 'ending my life',
    "don't want to live", "dont want to live", "don't want to be alive",
    "dont want to be alive", 'want to die', 'better off dead',
    'self-harm', 'self harm', 'hurt myself', 'cut myself',
)


def detect_crisis_keywords(body: str) -> bool:
    """Return True if body contains any crisis signal phrase.

    Delegates to claude_api.check_crisis — the single, evasion-resistant matcher
    shared across all patient-facing channels (H-7). Falls back to a local list
    only if the import fails, so the SMS channel never silently loses detection.
    """
    if not body:
        return False
    try:
        import claude_api
        return claude_api.check_crisis(body)
    except Exception:
        lower = body.lower()
        return any(kw in lower for kw in _CRISIS_KEYWORDS_FALLBACK)


def parse_medication_reply(body: str) -> bool | None:
    """Return True (taken), False (skipped), or None (unrecognised)."""
    cleaned = body.strip().lower()
    if cleaned in ('y', 'yes', '1', 'taken', 'done', 'yep', 'yeah'):
        return True
    if cleaned in ('n', 'no', '0', 'skip', 'skipped', 'nope', 'not yet'):
        return False
    return None


def parse_checkin_reply(body: str) -> dict | None:
    """Parse a 5-number SMS check-in reply (M E S Q H).

    Accepts several formats:
      - Space/comma/slash separated: "7 8 4 6 6.5"
      - No-separator digit string:   "15478"  → [1, 5, 4, 7, 8]
      - Mixed:                       "7,8,4,6,6.5"

    The no-separator fallback treats each character as a digit-per-score
    (valid for scores 0-9). A trailing decimal group on the last digit
    is treated as sleep hours (e.g. "7846 6.5" or "78466.5").

    Returns dict with keys: mood, energy, stress, sleep_quality, sleep_hours
    or None if the reply cannot be parsed.
    """
    import re

    def clamp(v):
        return max(0.0, min(10.0, v))

    # ── Standard parse: split on whitespace, commas, slashes ─────────────────
    tokens = re.split(r'[\s,/]+', body.strip())
    nums = []
    for t in tokens:
        try:
            nums.append(float(t))
        except ValueError:
            pass

    # ── Fallback: no-separator digit string e.g. "15478" or "1547 6.5" ───────
    # Only triggers when standard parse yielded < 4 numbers.
    # Handles two sub-cases:
    #   a) Pure 4-5 digit string:              "15478"   → [1,5,4,7,8]
    #   b) 4-digit block + sleep hrs:          "1547 6.5" → [1,5,4,7, 6.5]
    #      Standard parse sees [1547.0, 6.5]; we detect the oversized first token.
    # Strings longer than 5 bare digits are ambiguous and not attempted.
    if len(nums) < 4:
        stripped = body.strip()

        # Sub-case (a): body is exactly 4 or 5 bare digits
        if re.fullmatch(r'\d{4,5}', stripped):
            nums = [float(d) for d in stripped]

        # Sub-case (b): standard parse gave us tokens but first one is a 4-digit
        # integer (concatenated scores), optionally followed by a sleep-hours float.
        elif nums and nums[0] == int(nums[0]) and 1000 <= nums[0] <= 9999:
            digits = [float(d) for d in str(int(nums[0]))]
            rest   = nums[1:]   # anything the standard parse found after
            nums   = digits + rest

    if len(nums) < 4:
        return None

    return {
        'mood':          clamp(nums[0]),
        'energy':        clamp(nums[1]),
        'stress':        clamp(nums[2]),
        'sleep_quality': clamp(nums[3]),
        'sleep_hours':   nums[4] if len(nums) >= 5 else None,
    }


# ── SMS message templates ─────────────────────────────────────────────────────

MSG_CHECKIN_PROMPT = (
    "CognaSync: Check-in\n"
    "Mood · Energy · Stress · Sleep quality · Sleep hrs\n"
    "Use spaces or commas between numbers.\n"
    "Reply: 7 8 4 6 6.5 or SKIP"
)  # 111 chars

MSG_CHECKIN_CONFIRM = (
    "✓ Logged — Mood {mood} · Energy {energy} · "
    "Stress {stress} · Sleep {sleep_hours}hrs. Have a good day."
)

MSG_CHECKIN_PARSE_FAIL = (
    "Didn't catch that. Reply with 5 numbers separated by spaces or commas:\n"
    "Mood · Energy · Stress · Sleep quality · Sleep hrs\n"
    "Example: 7 8 4 6 6.5 or SKIP"
)  # 152 chars

MSG_ENROLLMENT = (
    "CognaSync: You'll get a check-in text 3x/week. Reply with 5 numbers:\n"
    "1 Mood (0=low, 10=best)\n"
    "2 Energy (0=none, 10=high)\n"
    "3 Stress (0=calm, 10=severe)\n"
    "4 Sleep quality (0=poor, 10=great)\n"
    "5 Sleep hours (e.g. 6.5)\n"
    "Separate with spaces or commas. Example: 7 8 4 6 6.5"
)

MSG_HELP_BRANCH = (
    "CognaSync: Are you reaching out because you're in crisis or need "
    "emotional support — or do you need help with how to use this system?\n"
    "Reply CRISIS or SYSTEM"
)  # 156 chars

MSG_CRISIS_PATIENT = (
    "You're not alone. Please reach out now:\n"
    "\U0001f4de 988 — call or text\n"
    "\U0001f4ac Text HOME to 741741\n"
    "\U0001f6a8 Emergency — call 911\n"
    "Your provider has also been notified."
)

MSG_SYSTEM_GUIDE = (
    "Check-in guide:\n"
    "1 Mood (0=low, 10=best)\n"
    "2 Energy (0=none, 10=high)\n"
    "3 Stress (0=calm, 10=severe)\n"
    "4 Sleep quality (0=poor, 10=great)\n"
    "5 Sleep hours (e.g. 6.5)\n"
    "Example: 7 8 4 6 6.5"
)  # 155 chars

MSG_PROVIDER_CRISIS_ALERT = (
    "CognaSync ALERT: {patient_name} may be in crisis — they reached out "
    "via SMS. Please check in with them directly."
)


# ── Composed sends ─────────────────────────────────────────────────────────────

def send_crisis_sms_to_patient(to_number: str) -> dict:
    """Send the patient-facing crisis resources message."""
    return send_sms(to_number, MSG_CRISIS_PATIENT)


def send_help_branch_sms(to_number: str) -> dict:
    """Send the CRISIS/SYSTEM branch prompt."""
    return send_sms(to_number, MSG_HELP_BRANCH)


def send_checkin_guide_sms(to_number: str) -> dict:
    """Send the full labeled check-in guide (system help response)."""
    return send_sms(to_number, MSG_SYSTEM_GUIDE)


def send_provider_crisis_alert(provider_number: str, patient_name: str) -> dict:
    """SMS the provider immediately when a patient crisis signal is received."""
    body = MSG_PROVIDER_CRISIS_ALERT.format(patient_name=patient_name)
    return send_sms(provider_number, body)


def escalate_crisis(db, patient_id, source, patient_name=None, from_number=None):
    """Unified crisis escalation shared by every patient-facing channel
    (inbound SMS, SMS check-in, voice note).

    Sends the patient crisis resources, logs the event, resolves any open SMS
    session, and alerts the patient's provider (SMS + a care_flags row). `db` is
    injected so this module needs no database import and is safe to call from the
    background voice-processing thread. Patient name/phone are looked up from the
    profile when not supplied. Every step is independently guarded so one failure
    (e.g. no phone on file) never prevents the others — escalation must be robust.

    `source` must be one of the values allowed by the sms_crisis_events CHECK
    constraint: 'keyword', 'help_branch', 'checkin', 'voice'.
    """
    if not from_number or not patient_name:
        try:
            res = db.supabase_admin.table('profiles').select(
                'full_name, phone_number').eq('id', str(patient_id)).limit(1).execute()
            prof = res.data[0] if res.data else {}
            patient_name = patient_name or prof.get('full_name') or 'Your patient'
            from_number  = from_number or prof.get('phone_number') or ''
        except Exception as e:
            logger.error('[crisis] profile lookup failed for %s: %s', patient_id, e)
            patient_name = patient_name or 'Your patient'

    # 1. Patient-facing resources (only if we have a number to reach them)
    if from_number:
        try:
            send_crisis_sms_to_patient(from_number)
        except Exception as e:
            logger.error('[crisis] patient SMS failed for %s: %s', patient_id, e)

    # 2. Log the event (no patient text stored)
    event_id = None
    try:
        event_id = db.log_sms_crisis(patient_id, source=source)
    except Exception as e:
        logger.error('[crisis] log_sms_crisis failed for %s: %s', patient_id, e)

    # 3. Resolve any open session
    try:
        db.resolve_sms_session(patient_id)
    except Exception:
        pass

    # 4. Alert the provider via SMS + insert a care_flags row (Clinical Alerts)
    try:
        provider = db.get_provider_for_patient(patient_id)
        if provider:
            if provider.get('phone_number'):
                result = send_provider_crisis_alert(provider['phone_number'], patient_name)
                if event_id and result.get('ok'):
                    db.mark_provider_notified(event_id, sms_sid=result.get('sid'))
            source_label = source.replace('_', ' ')
            flag_body = (
                f'🔴 Crisis signal ({source_label}) — {patient_name} may need immediate '
                f'support. Please check in directly.'
            )
            db.supabase_admin.table('care_flags').insert({
                'patient_id':         str(patient_id),
                'author_provider_id': str(provider['id']),
                'flag_type':          'concern',
                'body':               flag_body,
                'visibility':         'care_team',
            }).execute()
    except Exception as e:
        logger.error('[crisis] provider alert/flag failed for %s: %s', patient_id, e)

    return event_id


def send_daily_checkin_prompt(to_number: str) -> dict:
    """Send the short recurring check-in prompt (3x/week)."""
    return send_sms(to_number, MSG_CHECKIN_PROMPT)


def send_enrollment_guide(to_number: str) -> dict:
    """Send the one-time labeled enrollment message."""
    return send_sms(to_number, MSG_ENROLLMENT)


# ── Rotating questions ────────────────────────────────────────────────────────

# Each entry: label, prompt_text, field_name, scale, is_crisis_field
# scale: 'int_0_10' | 'int_0_3' | 'count'
ROTATING_QUESTIONS = {
    'suicidality': {
        'label': 'Safety check',
        'prompt_text': '0=feeling safe, 1=brief thoughts, 2=frequent thoughts, 3=hard to push away',
        'field_name': 'suicidality_score',
        'scale': 'int_0_3',
        'is_crisis_field': True,
    },
    'sleep': {
        'label': 'Sleep latency',
        'prompt_text': 'Minutes to fall asleep? Reply number (e.g. 20)',
        'field_name': 'sleep_latency_min',
        'scale': 'count',
        'is_crisis_field': False,
    },
    'mood': {
        'label': 'Enjoyment',
        'prompt_text': 'Enjoyment of things today? 0=nothing, 10=fully',
        'field_name': 'enjoyment',
        'scale': 'int_0_10',
        'is_crisis_field': False,
    },
    'anxiety_stress': {
        'label': 'Anxiety',
        'prompt_text': 'Anxiety today? 0=none, 10=severe',
        'field_name': 'anxiety',
        'scale': 'int_0_10',
        'is_crisis_field': False,
    },
    'energy_focus': {
        'label': 'Focus',
        'prompt_text': 'Focus today? 0=none, 10=sharp',
        'field_name': 'focus',
        'scale': 'int_0_10',
        'is_crisis_field': False,
    },
    'medication_response': {
        'label': 'Medication',
        'prompt_text': 'Medication working today? 0=not at all, 10=working well',
        'field_name': 'medication_effectiveness',
        'scale': 'int_0_10',
        'is_crisis_field': False,
    },
    'social_functioning': {
        'label': 'Social connection',
        'prompt_text': 'Social connection today? 0=isolated, 10=connected',
        'field_name': 'social_quality',
        'scale': 'int_0_10',
        'is_crisis_field': False,
    },
    'irritability': {
        'label': 'Irritability',
        'prompt_text': 'Irritability today? 0=none, 10=severe',
        'field_name': 'irritability',
        'scale': 'int_0_10',
        'is_crisis_field': False,
    },
    'motivation': {
        'label': 'Motivation',
        'prompt_text': 'Motivation today? 0=none, 10=high',
        'field_name': 'motivation',
        'scale': 'int_0_10',
        'is_crisis_field': False,
    },
    'appetite_nutrition': {
        'label': 'Appetite',
        'prompt_text': 'Appetite today? 0=no appetite, 10=normal',
        'field_name': 'appetite',
        'scale': 'int_0_10',
        'is_crisis_field': False,
    },
    'substance_use': {
        'label': 'Drinks',
        'prompt_text': 'Drinks today? Reply number (0=none)',
        'field_name': 'alcohol_units',
        'scale': 'count',
        'is_crisis_field': False,
    },
    'side_effects': {
        'label': 'Side effects',
        'prompt_text': 'Side effects today? 0=none, 10=severe',
        'field_name': 'side_effect_burden',
        'scale': 'int_0_10',
        'is_crisis_field': False,
    },
}

MSG_ROTATING_PARSE_FAIL = (
    "Didn't catch that. Reply with a number (0-10) or SKIP."
)


def _normalize_target(target: str) -> str:
    """Normalize a focus_domain target name for lookup in ROTATING_QUESTIONS."""
    import re
    return re.sub(r'[\s/\-]+', '_', target.strip().lower())


def get_rotating_fields_for_checkin(focus_domains: list, checkin_index: int) -> list:
    """Return up to 2 rotating question dicts for this check-in.

    Args:
        focus_domains: Raw target name strings from the DB (provider_focus_configs).
        checkin_index: Count of completed check-ins so far; used to rotate questions
                       when there are more than 2 active targets.

    Returns:
        List of 0–2 field dicts from ROTATING_QUESTIONS.
    """
    matched = []
    for domain in focus_domains:
        key = _normalize_target(domain)
        if key in ROTATING_QUESTIONS:
            matched.append(ROTATING_QUESTIONS[key])

    if len(matched) <= 2:
        return matched

    # More than 2: rotate start index across check-ins
    start = checkin_index % len(matched)
    selected = []
    for i in range(2):
        selected.append(matched[(start + i) % len(matched)])
    return selected


def build_rotating_prompt(rotating_fields: list) -> str:
    """Build the SMS prompt string for a rotating follow-up message.

    Args:
        rotating_fields: List of 1 or 2 field dicts from ROTATING_QUESTIONS.

    Returns:
        Formatted SMS string ready to send.
    """
    if not rotating_fields:
        return ''

    if len(rotating_fields) == 1:
        f = rotating_fields[0]
        return (
            f"CognaSync: One more —\n"
            f"{f['label']}: {f['prompt_text']}\n"
            f"Reply with a number or SKIP"
        )

    f1, f2 = rotating_fields[0], rotating_fields[1]
    return (
        f"CognaSync: Two more —\n"
        f"1. {f1['label']}: {f1['prompt_text']}\n"
        f"2. {f2['label']}: {f2['prompt_text']}\n"
        f"Reply two numbers (e.g. 3 7) or SKIP"
    )


def parse_rotating_reply(body: str, rotating_fields: list) -> dict | None:
    """Parse a patient reply to a rotating question follow-up SMS.

    Args:
        body: Raw SMS reply text.
        rotating_fields: The same list of 1 or 2 field dicts that were sent.

    Returns:
        Dict of {field_name: value} on success.
        Empty dict if the patient replied SKIP.
        None if the reply cannot be parsed.
    """
    import re

    stripped = body.strip()

    # SKIP signal
    if stripped.upper() == 'SKIP':
        return {}

    # Extract all numbers from the reply
    tokens = re.split(r'[\s,/]+', stripped)
    nums = []
    for t in tokens:
        try:
            nums.append(float(t))
        except ValueError:
            pass

    if not nums:
        return None

    n_expected = len(rotating_fields)
    if len(nums) < n_expected:
        return None

    def _apply_scale(value: float, scale: str):
        if scale == 'int_0_10':
            return max(0.0, min(10.0, value))
        elif scale == 'int_0_3':
            return max(0, min(3, int(round(value))))
        else:  # count
            return max(0.0, value)

    result = {}
    for i, field in enumerate(rotating_fields):
        result[field['field_name']] = _apply_scale(nums[i], field['scale'])

    return result
