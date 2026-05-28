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

def parse_medication_reply(body: str) -> bool | None:
    """Return True (taken), False (skipped), or None (unrecognised)."""
    cleaned = body.strip().lower()
    if cleaned in ('y', 'yes', '1', 'taken', 'done', 'yep', 'yeah'):
        return True
    if cleaned in ('n', 'no', '0', 'skip', 'skipped', 'nope', 'not yet'):
        return False
    return None
