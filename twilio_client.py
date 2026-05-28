"""
twilio_client.py — CognaSync Twilio SDK wrapper

Responsibilities:
  - Trigger Twilio Studio flow executions (send SMS flows to patients)
  - Validate inbound Twilio webhook signatures (prevent spoofed requests)

All Twilio credentials and Flow SIDs are loaded from environment variables.
This module never touches patient data directly — it only sends and validates.
"""

import os
import hmac
import hashlib
import base64
from urllib.parse import urlencode

from twilio.rest import Client
from twilio.request_validator import RequestValidator

# ─────────────────────────────────────────────────────────────────────────────
# Credentials — loaded from environment
# ─────────────────────────────────────────────────────────────────────────────
ACCOUNT_SID   = os.environ.get('TWILIO_ACCOUNT_SID', '')
AUTH_TOKEN    = os.environ.get('TWILIO_AUTH_TOKEN', '')
PHONE_NUMBER  = os.environ.get('TWILIO_PHONE_NUMBER', '')  # E.164 format: +15551234567

# Studio Flow SIDs — one per flow, set after creating each flow in Twilio console
FLOW_SID_MED   = os.environ.get('TWILIO_FLOW_SID_MED', '')    # Flow 1: Medication adherence
FLOW_SID_SHORT = os.environ.get('TWILIO_FLOW_SID_SHORT', '')  # Flow 2: Short check-in
FLOW_SID_FULL  = os.environ.get('TWILIO_FLOW_SID_FULL', '')   # Flow 3: Full pre-appt check-in
FLOW_SID_VOICE = os.environ.get('TWILIO_FLOW_SID_VOICE', '')  # Flow 4: Standalone voice invite

_FLOW_SID_MAP = {
    'medication': FLOW_SID_MED,
    'short':      FLOW_SID_SHORT,
    'full':       FLOW_SID_FULL,
    'voice':      FLOW_SID_VOICE,
}

# Lazily initialised — only created if credentials are present
_client: Client | None = None
_validator: RequestValidator | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        if not ACCOUNT_SID or not AUTH_TOKEN:
            raise RuntimeError(
                'TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set '
                'before making Twilio API calls.'
            )
        _client = Client(ACCOUNT_SID, AUTH_TOKEN)
    return _client


def _get_validator() -> RequestValidator:
    global _validator
    if _validator is None:
        if not AUTH_TOKEN:
            raise RuntimeError('TWILIO_AUTH_TOKEN must be set to validate webhooks.')
        _validator = RequestValidator(AUTH_TOKEN)
    return _validator


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def trigger_flow(flow_type: str, to_phone: str, parameters: dict) -> str | None:
    """
    Start a Twilio Studio flow execution for a patient.

    Args:
        flow_type:  One of 'medication', 'short', 'full', 'voice'
        to_phone:   Patient's phone number in E.164 format (+15551234567)
        parameters: Dict of variables passed into the Studio flow as
                    {{variable_name}} substitutions. All values must be strings.

    Returns:
        The execution SID string on success, or None on failure.

    Notes:
        - Each call starts a new independent execution for one patient.
        - parameters are available inside Studio as flow.variables.*
        - All values are coerced to strings before sending (Studio requirement).
    """
    flow_sid = _FLOW_SID_MAP.get(flow_type)
    if not flow_sid:
        print(f"[twilio] No SID configured for flow_type={flow_type!r} — skipping")
        return None

    if not to_phone:
        print(f"[twilio] No phone number provided for flow_type={flow_type!r} — skipping")
        return None

    # Studio requires all parameter values to be strings
    str_params = {k: str(v) for k, v in parameters.items()}

    try:
        execution = _get_client().studio.v2.flows(flow_sid).executions.create(
            to=to_phone,
            from_=PHONE_NUMBER,
            parameters=str_params,
        )
        print(f"[twilio] Triggered flow_type={flow_type!r} to={to_phone!r} sid={execution.sid!r}")
        return execution.sid
    except Exception as e:
        print(f"[twilio] ERROR triggering flow_type={flow_type!r} to={to_phone!r}: {e}")
        return None


def validate_webhook_signature(request_url: str, post_params: dict, signature: str) -> bool:
    """
    Validate that an inbound webhook genuinely came from Twilio.

    Twilio signs every webhook request with HMAC-SHA1 using the Auth Token.
    We must validate this before trusting any inbound data.

    Args:
        request_url: The full URL of the receiving endpoint (including https://).
                     Must match exactly what Twilio sees — include port if non-standard.
        post_params: Dict of POST body parameters from the request.
        signature:   The X-Twilio-Signature header value from the request.

    Returns:
        True if the signature is valid, False otherwise.

    Usage in Flask:
        url = request.url
        params = request.form.to_dict()
        sig = request.headers.get('X-Twilio-Signature', '')
        if not twilio_client.validate_webhook_signature(url, params, sig):
            abort(403)
    """
    if not signature:
        return False
    try:
        return _get_validator().validate(request_url, post_params, signature)
    except Exception as e:
        print(f"[twilio] Signature validation error: {e}")
        return False


def is_configured() -> bool:
    """Return True if all required Twilio env vars are set. Use for health checks."""
    return bool(ACCOUNT_SID and AUTH_TOKEN and PHONE_NUMBER)


def configured_flows() -> dict:
    """Return a dict of flow_type -> bool indicating which flows have SIDs configured."""
    return {ft: bool(sid) for ft, sid in _FLOW_SID_MAP.items()}
