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

# Crisis keywords — any match halts normal processing (patient-facing channel).
# Aligned with CLAUDE.md §10 Detection list.
_CRISIS_KEYWORDS = (
    'suicide', 'suicidal', 'kill myself', 'end my life', 'ending my life',
    "don't want to live", "dont want to live", "don't want to be alive",
    "dont want to be alive", 'want to die', 'better off dead',
    'self-harm', 'self harm', 'hurt myself', 'cut myself',
)


def detect_crisis_keywords(body: str) -> bool:
    """Return True if body contains any crisis signal phrase."""
    lower = body.lower()
    return any(kw in lower for kw in _CRISIS_KEYWORDS)


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
    "Reply: 7 8 4 6 6.5 or SKIP"
)  # 84 chars

MSG_CHECKIN_CONFIRM = (
    "✓ Logged — Mood {mood} · Energy {energy} · "
    "Stress {stress} · Sleep {sleep_hours}hrs. Have a good day."
)

MSG_CHECKIN_PARSE_FAIL = (
    "Didn't catch that. Reply with 5 numbers:\n"
    "1 Mood · 2 Energy · 3 Stress · 4 Sleep quality · 5 Sleep hrs\n"
    "Example: 7 8 4 6 6.5 or SKIP"
)  # 132 chars

MSG_ENROLLMENT = (
    "CognaSync: You'll get a check-in text 3x/week. Reply with 5 numbers:\n"
    "1 Mood (0=low, 10=best)\n"
    "2 Energy (0=none, 10=high)\n"
    "3 Stress (0=calm, 10=severe)\n"
    "4 Sleep quality (0=poor, 10=great)\n"
    "5 Sleep hours (e.g. 6.5)\n"
    "Example: 7 8 4 6 6.5 · Reply SKIP to skip."
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


def send_daily_checkin_prompt(to_number: str) -> dict:
    """Send the short recurring check-in prompt (3x/week)."""
    return send_sms(to_number, MSG_CHECKIN_PROMPT)


def send_enrollment_guide(to_number: str) -> dict:
    """Send the one-time labeled enrollment message."""
    return send_sms(to_number, MSG_ENROLLMENT)
