#!/usr/bin/env python3
"""
create_twilio_flows.py — Create and publish all four CognaSync Twilio Studio flows.

Run once:
    export TWILIO_ACCOUNT_SID=ACxxxxxxxx
    export TWILIO_AUTH_TOKEN=your_auth_token
    python3 create_twilio_flows.py

Diagnostic mode (tests individual widget types):
    python3 create_twilio_flows.py --diag

Twilio Studio v2 rules learned from iteration:
  - send-and-wait-for-reply: NO "to" field (recipient is implicit)
  - send-message: requires "to" field
  - Terminal transitions must be OMITTED entirely (not "" or null)
  - split-based-on conditions: use "equal_to" NOT "matches" (regex unsupported via REST API)
  - No "flags" key at flow definition level
  - Trigger: only list transitions that actually route somewhere
"""

import os
import sys
import json
import requests
from requests.auth import HTTPBasicAuth
from typing import Optional, List, Dict, Any

ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID', '')
AUTH_TOKEN  = os.environ.get('TWILIO_AUTH_TOKEN', '')

if not ACCOUNT_SID or not AUTH_TOKEN:
    print("ERROR: Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN before running.")
    sys.exit(1)

AUTH      = HTTPBasicAuth(ACCOUNT_SID, AUTH_TOKEN)
FLOWS_URL = "https://studio.twilio.com/v2/Flows"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _off(x: int, y: int) -> Dict[str, int]:
    return {"x": x, "y": y}


def _tr(event: str, next_widget: str = "") -> Optional[Dict[str, str]]:
    """Build a transition. Returns None for terminal (no next) — filter with 'if t'."""
    if not next_widget:
        return None
    return {"event": event, "next": next_widget}


def _eq(friendly_name: str, widget_ref: str, value: str, next_widget: str) -> Dict[str, Any]:
    """Build a split-based-on equal_to match transition for one specific value."""
    return {
        "event": "match",
        "conditions": [{
            "friendly_name": friendly_name,
            "arguments": [widget_ref],
            "type": "equal_to",
            "value": value,
        }],
        "next": next_widget,
    }


def _eq_many(widget_ref: str, values: List[str], next_widget: str) -> List[Dict[str, Any]]:
    """Build equal_to match transitions for multiple values → same destination."""
    return [_eq(v, widget_ref, v, next_widget) for v in values]


# ─────────────────────────────────────────────────────────────────────────────
# API helpers
# ─────────────────────────────────────────────────────────────────────────────

def upsert_flow(friendly_name: str, definition: Dict,
                dump_path: Optional[str] = None) -> Optional[str]:
    definition_json = json.dumps(definition, ensure_ascii=False)

    if dump_path:
        with open(dump_path, 'w') as f:
            f.write(definition_json)

    existing_sid = _find_existing_flow(friendly_name)

    if existing_sid:
        resp = requests.post(
            f"{FLOWS_URL}/{existing_sid}",
            auth=AUTH,
            data={'Status': 'published', 'Definition': definition_json}
        )
        action = "Updated"
    else:
        resp = requests.post(
            FLOWS_URL,
            auth=AUTH,
            data={'FriendlyName': friendly_name, 'Status': 'published',
                  'Definition': definition_json}
        )
        action = "Created"

    if resp.status_code in (200, 201):
        sid = resp.json()['sid']
        print(f"  ✓ {action} '{friendly_name}' → {sid}")
        return sid
    else:
        print(f"  ✗ Failed '{friendly_name}': HTTP {resp.status_code}")
        try:
            err = resp.json()
            print(f"    message : {err.get('message', '—')}")
            details = err.get('details') or {}
            print(f"    details : {json.dumps(details, indent=6)}")
        except Exception:
            print(f"    raw     : {resp.text[:800]}")
        if dump_path:
            print(f"    json    : {dump_path}")
        return None


def _find_existing_flow(friendly_name: str) -> Optional[str]:
    try:
        resp = requests.get(FLOWS_URL, auth=AUTH)
        if resp.status_code == 200:
            for flow in resp.json().get('flows', []):
                if flow.get('friendly_name') == friendly_name:
                    return flow['sid']
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# FLOW 1 — Daily Medication Adherence
# ─────────────────────────────────────────────────────────────────────────────
def flow_medication() -> Dict:
    REF = "{{widgets.q_adherence.inbound_message.body}}"
    return {
        "description": "CognaSync: Daily medication adherence Y/N check",
        "initial_state": "Trigger",
        "states": [
            {
                "name": "Trigger",
                "type": "trigger",
                "transitions": [_tr("incomingRequest", "q_adherence")],
                "properties": {"offset": _off(0, 0)},
            },
            {
                "name": "q_adherence",
                "type": "send-and-wait-for-reply",
                "transitions": [t for t in [
                    _tr("incomingMessage", "check_reply"),
                    _tr("timeout",         "http_post"),
                ] if t],
                "properties": {
                    "from":    "{{flow.channel.address}}",
                    "body":    "CognaSync: Did you take your {{flow.variables.medication_name}} today? Reply Y or N",
                    "timeout": "3600",
                    "offset":  _off(0, 150),
                },
            },
            {
                "name": "check_reply",
                "type": "split-based-on",
                "transitions": [
                    # Match Y (upper + lower) → send_confirmed
                    *_eq_many(REF, ["Y", "y"], "send_confirmed"),
                    # Match N (upper + lower) → send_noted
                    *_eq_many(REF, ["N", "n"], "send_noted"),
                    _tr("noMatch", "q_again"),
                ],
                "properties": {
                    "input":  REF,
                    "offset": _off(0, 350),
                },
            },
            {
                "name": "send_confirmed",
                "type": "send-message",
                "transitions": [t for t in [
                    _tr("sent",   "http_post"),
                    _tr("failed", "http_post"),
                ] if t],
                "properties": {
                    "from":   "{{flow.channel.address}}",
                    "to":     "{{contact.channel.address}}",
                    "body":   "Got it - logged for today.",
                    "offset": _off(-280, 520),
                },
            },
            {
                "name": "send_noted",
                "type": "send-message",
                "transitions": [t for t in [
                    _tr("sent",   "http_post"),
                    _tr("failed", "http_post"),
                ] if t],
                "properties": {
                    "from":   "{{flow.channel.address}}",
                    "to":     "{{contact.channel.address}}",
                    "body":   "No worries - logged. Mention it to your provider if it keeps happening.",
                    "offset": _off(0, 520),
                },
            },
            {
                "name": "q_again",
                "type": "send-and-wait-for-reply",
                "transitions": [t for t in [
                    _tr("incomingMessage", "http_post"),
                    _tr("timeout",         "http_post"),
                ] if t],
                "properties": {
                    "from":    "{{flow.channel.address}}",
                    "body":    "Just reply Y or N - did you take your {{flow.variables.medication_name}} today?",
                    "timeout": "3600",
                    "offset":  _off(280, 520),
                },
            },
            {
                "name": "http_post",
                "type": "make-http-request",
                "transitions": [],
                "properties": {
                    "method":       "POST",
                    "content_type": "application/x-www-form-urlencoded;charset=utf-8",
                    "url":          "{{flow.variables.app_url}}/api/twilio/medication-adherence",
                    "parameters": [
                        {"key": "token",           "value": "{{flow.variables.token}}"},
                        {"key": "result",          "value": REF},
                        {"key": "medication_name", "value": "{{flow.variables.medication_name}}"},
                    ],
                    "offset": _off(0, 720),
                },
            },
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# FLOW 2 — Short Check-In
# ─────────────────────────────────────────────────────────────────────────────
def flow_short_checkin() -> Dict:
    MOOD_REF = "{{widgets.q_mood.inbound_message.body}}"
    return {
        "description": "CognaSync: Short 3-question check-in with adaptive mood follow-up",
        "initial_state": "Trigger",
        "states": [
            {
                "name": "Trigger",
                "type": "trigger",
                "transitions": [_tr("incomingRequest", "q_mood")],
                "properties": {"offset": _off(0, 0)},
            },
            {
                "name": "q_mood",
                "type": "send-and-wait-for-reply",
                "transitions": [t for t in [
                    _tr("incomingMessage", "check_mood"),
                    _tr("timeout",         "q_sleep"),
                ] if t],
                "properties": {
                    "from":    "{{flow.channel.address}}",
                    "body":    "CognaSync check-in - Mood today? Reply 1-10 (1 = rough, 10 = great)",
                    "timeout": "3600",
                    "offset":  _off(0, 150),
                },
            },
            # Low mood (1, 2, or 3) → adaptive follow-up; anything else → sleep
            {
                "name": "check_mood",
                "type": "split-based-on",
                "transitions": [
                    *_eq_many(MOOD_REF, ["1", "2", "3"], "q_followup_mood"),
                    _tr("noMatch", "q_sleep"),
                ],
                "properties": {
                    "input":  MOOD_REF,
                    "offset": _off(0, 330),
                },
            },
            {
                "name": "q_followup_mood",
                "type": "send-and-wait-for-reply",
                "transitions": [t for t in [
                    _tr("incomingMessage", "q_sleep"),
                    _tr("timeout",         "q_sleep"),
                ] if t],
                "properties": {
                    "from":    "{{flow.channel.address}}",
                    "body":    "What feels heavy today?",
                    "timeout": "1800",
                    "offset":  _off(240, 490),
                },
            },
            {
                "name": "q_sleep",
                "type": "send-and-wait-for-reply",
                "transitions": [t for t in [
                    _tr("incomingMessage", "q_stress"),
                    _tr("timeout",         "q_stress"),
                ] if t],
                "properties": {
                    "from":    "{{flow.channel.address}}",
                    "body":    "How many hours of sleep last night?",
                    "timeout": "1800",
                    "offset":  _off(0, 660),
                },
            },
            {
                "name": "q_stress",
                "type": "send-and-wait-for-reply",
                "transitions": [t for t in [
                    _tr("incomingMessage", "http_post"),
                    _tr("timeout",         "http_post"),
                ] if t],
                "properties": {
                    "from":    "{{flow.channel.address}}",
                    "body":    "Stress level? Reply 1-10 (1 = calm, 10 = overwhelmed)",
                    "timeout": "1800",
                    "offset":  _off(0, 840),
                },
            },
            {
                "name": "http_post",
                "type": "make-http-request",
                "transitions": [],
                "properties": {
                    "method":       "POST",
                    "content_type": "application/x-www-form-urlencoded;charset=utf-8",
                    "url":          "{{flow.variables.app_url}}/api/twilio/checkin",
                    "parameters": [
                        {"key": "token",          "value": "{{flow.variables.token}}"},
                        {"key": "check_in_type",  "value": "short"},
                        {"key": "mood",           "value": MOOD_REF},
                        {"key": "sleep_hours",    "value": "{{widgets.q_sleep.inbound_message.body}}"},
                        {"key": "stress",         "value": "{{widgets.q_stress.inbound_message.body}}"},
                        {"key": "follow_up_note", "value": "{{widgets.q_followup_mood.inbound_message.body}}"},
                        {"key": "follow_up_type", "value": "mood"},
                    ],
                    "offset": _off(0, 1020),
                },
            },
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# FLOW 3 — Full Pre-Appointment Check-In
# ─────────────────────────────────────────────────────────────────────────────
def flow_full_checkin() -> Dict:
    MOOD_REF = "{{widgets.q_mood.inbound_message.body}}"
    MED_REF  = "{{widgets.q_med.inbound_message.body}}"
    return {
        "description": "CognaSync: Full pre-appointment check-in with adaptive follow-up, med branch, and voice invite",
        "initial_state": "Trigger",
        "states": [
            {
                "name": "Trigger",
                "type": "trigger",
                "transitions": [_tr("incomingRequest", "q_mood")],
                "properties": {"offset": _off(0, 0)},
            },
            {
                "name": "q_mood",
                "type": "send-and-wait-for-reply",
                "transitions": [t for t in [
                    _tr("incomingMessage", "check_mood"),
                    _tr("timeout",         "q_sleep"),
                ] if t],
                "properties": {
                    "from":    "{{flow.channel.address}}",
                    "body":    "Your appt with {{flow.variables.provider_name}} is {{flow.variables.appt_time}}. Quick check-in - Mood today? Reply 1-10",
                    "timeout": "3600",
                    "offset":  _off(0, 150),
                },
            },
            {
                "name": "check_mood",
                "type": "split-based-on",
                "transitions": [
                    *_eq_many(MOOD_REF, ["1", "2", "3"], "q_followup_mood"),
                    _tr("noMatch", "q_sleep"),
                ],
                "properties": {
                    "input":  MOOD_REF,
                    "offset": _off(0, 330),
                },
            },
            {
                "name": "q_followup_mood",
                "type": "send-and-wait-for-reply",
                "transitions": [t for t in [
                    _tr("incomingMessage", "q_sleep"),
                    _tr("timeout",         "q_sleep"),
                ] if t],
                "properties": {
                    "from":    "{{flow.channel.address}}",
                    "body":    "What feels heavy today?",
                    "timeout": "1800",
                    "offset":  _off(240, 490),
                },
            },
            {
                "name": "q_sleep",
                "type": "send-and-wait-for-reply",
                "transitions": [t for t in [
                    _tr("incomingMessage", "q_energy"),
                    _tr("timeout",         "q_energy"),
                ] if t],
                "properties": {
                    "from":    "{{flow.channel.address}}",
                    "body":    "Hours of sleep last night?",
                    "timeout": "1800",
                    "offset":  _off(0, 660),
                },
            },
            {
                "name": "q_energy",
                "type": "send-and-wait-for-reply",
                "transitions": [t for t in [
                    _tr("incomingMessage", "q_stress"),
                    _tr("timeout",         "q_stress"),
                ] if t],
                "properties": {
                    "from":    "{{flow.channel.address}}",
                    "body":    "Energy today? Reply 1-10 (1 = drained, 10 = energized)",
                    "timeout": "1800",
                    "offset":  _off(0, 840),
                },
            },
            {
                "name": "q_stress",
                "type": "send-and-wait-for-reply",
                "transitions": [t for t in [
                    _tr("incomingMessage", "q_med"),
                    _tr("timeout",         "q_med"),
                ] if t],
                "properties": {
                    "from":    "{{flow.channel.address}}",
                    "body":    "Stress level? Reply 1-10",
                    "timeout": "1800",
                    "offset":  _off(0, 1020),
                },
            },
            {
                "name": "q_med",
                "type": "send-and-wait-for-reply",
                "transitions": [t for t in [
                    _tr("incomingMessage", "check_med"),
                    _tr("timeout",         "q_agenda"),
                ] if t],
                "properties": {
                    "from":    "{{flow.channel.address}}",
                    "body":    "Any medication side effects or missed doses to flag? Reply Y or N",
                    "timeout": "1800",
                    "offset":  _off(0, 1200),
                },
            },
            {
                "name": "check_med",
                "type": "split-based-on",
                "transitions": [
                    *_eq_many(MED_REF, ["Y", "y"], "q_med_note"),
                    _tr("noMatch", "q_agenda"),
                ],
                "properties": {
                    "input":  MED_REF,
                    "offset": _off(0, 1380),
                },
            },
            {
                "name": "q_med_note",
                "type": "send-and-wait-for-reply",
                "transitions": [t for t in [
                    _tr("incomingMessage", "q_agenda"),
                    _tr("timeout",         "q_agenda"),
                ] if t],
                "properties": {
                    "from":    "{{flow.channel.address}}",
                    "body":    "What should your provider know?",
                    "timeout": "1800",
                    "offset":  _off(240, 1540),
                },
            },
            {
                "name": "q_agenda",
                "type": "send-and-wait-for-reply",
                "transitions": [t for t in [
                    _tr("incomingMessage", "send_voice_invite"),
                    _tr("timeout",         "send_voice_invite"),
                ] if t],
                "properties": {
                    "from":    "{{flow.channel.address}}",
                    "body":    "Anything you want to make sure gets covered today? Reply in a few words, or just say skip.",
                    "timeout": "120",
                    "offset":  _off(0, 1710),
                },
            },
            {
                "name": "send_voice_invite",
                "type": "send-message",
                "transitions": [t for t in [
                    _tr("sent",   "http_post"),
                    _tr("failed", "http_post"),
                ] if t],
                "properties": {
                    "from":   "{{flow.channel.address}}",
                    "to":     "{{contact.channel.address}}",
                    "body":   "All set! One more thing - {{flow.variables.provider_name}} has a question: \"{{flow.variables.voice_prompt}}\" Tap to record (60 sec): {{flow.variables.voice_link}}",
                    "offset": _off(0, 1890),
                },
            },
            {
                "name": "http_post",
                "type": "make-http-request",
                "transitions": [],
                "properties": {
                    "method":       "POST",
                    "content_type": "application/x-www-form-urlencoded;charset=utf-8",
                    "url":          "{{flow.variables.app_url}}/api/twilio/checkin",
                    "parameters": [
                        {"key": "token",           "value": "{{flow.variables.token}}"},
                        {"key": "check_in_type",   "value": "full"},
                        {"key": "mood",            "value": MOOD_REF},
                        {"key": "sleep_hours",     "value": "{{widgets.q_sleep.inbound_message.body}}"},
                        {"key": "energy",          "value": "{{widgets.q_energy.inbound_message.body}}"},
                        {"key": "stress",          "value": "{{widgets.q_stress.inbound_message.body}}"},
                        {"key": "medication_note", "value": "{{widgets.q_med_note.inbound_message.body}}"},
                        {"key": "agenda_note",     "value": "{{widgets.q_agenda.inbound_message.body}}"},
                        {"key": "follow_up_note",  "value": "{{widgets.q_followup_mood.inbound_message.body}}"},
                        {"key": "follow_up_type",  "value": "mood"},
                    ],
                    "offset": _off(0, 2070),
                },
            },
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# FLOW 4 — Standalone Voice Recording Invite
# ─────────────────────────────────────────────────────────────────────────────
def flow_voice_invite() -> Dict:
    return {
        "description": "CognaSync: Standalone weekly voice recording invitation",
        "initial_state": "Trigger",
        "states": [
            {
                "name": "Trigger",
                "type": "trigger",
                "transitions": [_tr("incomingRequest", "send_invite")],
                "properties": {"offset": _off(0, 0)},
            },
            {
                "name": "send_invite",
                "type": "send-message",
                "transitions": [],
                "properties": {
                    "from":   "{{flow.channel.address}}",
                    "to":     "{{contact.channel.address}}",
                    "body":   "CognaSync: {{flow.variables.provider_name}} has a question this week - \"{{flow.variables.voice_prompt}}\" Tap to record your 60-second response: {{flow.variables.voice_link}}",
                    "offset": _off(0, 150),
                },
            },
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# DIAGNOSTIC FLOWS (python3 create_twilio_flows.py --diag)
# ─────────────────────────────────────────────────────────────────────────────
def diag_sawr() -> Dict:
    return {
        "description": "Diag: send-and-wait-for-reply only",
        "initial_state": "Trigger",
        "states": [
            {"name": "Trigger", "type": "trigger",
             "transitions": [_tr("incomingRequest", "q_test")],
             "properties": {"offset": _off(0, 0)}},
            {"name": "q_test", "type": "send-and-wait-for-reply",
             "transitions": [t for t in [_tr("incomingMessage", "done"), _tr("timeout", "done")] if t],
             "properties": {"from": "{{flow.channel.address}}", "body": "Test reply", "timeout": "60",
                            "offset": _off(0, 150)}},
            {"name": "done", "type": "send-message", "transitions": [],
             "properties": {"from": "{{flow.channel.address}}", "to": "{{contact.channel.address}}",
                            "body": "ok", "offset": _off(0, 300)}},
        ],
    }


def diag_http() -> Dict:
    return {
        "description": "Diag: make-http-request only",
        "initial_state": "Trigger",
        "states": [
            {"name": "Trigger", "type": "trigger",
             "transitions": [_tr("incomingRequest", "http_test")],
             "properties": {"offset": _off(0, 0)}},
            {"name": "http_test", "type": "make-http-request",
             "transitions": [t for t in [_tr("success", "done"), _tr("failed", "done")] if t],
             "properties": {"method": "POST",
                            "content_type": "application/x-www-form-urlencoded;charset=utf-8",
                            "url": "https://example.com/test",
                            "parameters": [{"key": "k", "value": "v"}],
                            "offset": _off(0, 150)}},
            {"name": "done", "type": "send-message", "transitions": [],
             "properties": {"from": "{{flow.channel.address}}", "to": "{{contact.channel.address}}",
                            "body": "ok", "offset": _off(0, 300)}},
        ],
    }


def diag_split() -> Dict:
    REF = "{{widgets.q_test.inbound_message.body}}"
    return {
        "description": "Diag: split-based-on with equal_to",
        "initial_state": "Trigger",
        "states": [
            {"name": "Trigger", "type": "trigger",
             "transitions": [_tr("incomingRequest", "q_test")],
             "properties": {"offset": _off(0, 0)}},
            {"name": "q_test", "type": "send-and-wait-for-reply",
             "transitions": [t for t in [_tr("incomingMessage", "check"), _tr("timeout", "done")] if t],
             "properties": {"from": "{{flow.channel.address}}", "body": "Y or N?", "timeout": "60",
                            "offset": _off(0, 150)}},
            {"name": "check", "type": "split-based-on",
             "transitions": [
                 *_eq_many(REF, ["Y", "y"], "done"),
                 _tr("noMatch", "done"),
             ],
             "properties": {"input": REF, "offset": _off(0, 300)}},
            {"name": "done", "type": "send-message", "transitions": [],
             "properties": {"from": "{{flow.channel.address}}", "to": "{{contact.channel.address}}",
                            "body": "ok", "offset": _off(0, 450)}},
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    import tempfile, os as _os

    diag_mode = '--diag' in sys.argv

    if diag_mode:
        print("\nCognaSync - DIAGNOSTIC: isolating widget types")
        print("=" * 52)
        tmpdir = tempfile.mkdtemp(prefix="cognasync_diag_")
        flows = [
            ("CognaSync Diag - SAWR",  diag_sawr(),  "DIAG_SAWR",  "diag_sawr"),
            ("CognaSync Diag - HTTP",  diag_http(),  "DIAG_HTTP",  "diag_http"),
            ("CognaSync Diag - Split", diag_split(), "DIAG_SPLIT", "diag_split"),
        ]
    else:
        print("\nCognaSync - Creating Twilio Studio Flows")
        print("=" * 52)
        tmpdir = tempfile.mkdtemp(prefix="cognasync_flows_")
        flows = [
            ("CognaSync - Medication Adherence",   flow_medication(),    "TWILIO_FLOW_SID_MED",   "med"),
            ("CognaSync - Short Check-In",         flow_short_checkin(), "TWILIO_FLOW_SID_SHORT",  "short"),
            ("CognaSync - Full Pre-Appt Check-In", flow_full_checkin(),  "TWILIO_FLOW_SID_FULL",   "full"),
            ("CognaSync - Voice Invite",           flow_voice_invite(),  "TWILIO_FLOW_SID_VOICE",  "voice"),
        ]

    results = {}
    for name, definition, env_key, slug in flows:
        dump_path = _os.path.join(tmpdir, f"{slug}.json")
        sid = upsert_flow(name, definition, dump_path=dump_path)
        if sid:
            results[env_key] = sid

    print("\n" + "=" * 52)
    expected = len(flows)
    if len(results) == expected:
        if diag_mode:
            print("All diagnostic flows passed.")
        else:
            print("All four flows created. Add these to Render:\n")
            for env_key, sid in results.items():
                print(f"  {env_key:<26} = {sid}")
            print()
    else:
        failed = expected - len(results)
        print(f"WARNING: {failed} flow(s) failed.")
        if results:
            print("\nSuccessful so far:")
            for env_key, sid in results.items():
                print(f"  {env_key:<26} = {sid}")

        failed_slugs = [slug for (name, defn, env_key, slug) in flows
                        if env_key not in results]
        if failed_slugs:
            first = _os.path.join(tmpdir, f"{failed_slugs[0]}.json")
            print(f"\nFailed flow JSON: {tmpdir}")
            print(f"\nCurl to inspect raw error:\n")
            print(f'  curl -s -X POST https://studio.twilio.com/v2/Flows \\')
            print(f'    -u "$TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN" \\')
            print(f'    -d "FriendlyName=CognaSync+Diag" \\')
            print(f'    -d "Status=published" \\')
            print(f'    --data-urlencode "Definition@{first}" | python3 -m json.tool')
            print()
        sys.exit(1)


if __name__ == '__main__':
    main()
