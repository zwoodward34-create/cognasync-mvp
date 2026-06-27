"""
Route-level tests for the short check-in migration off the Twilio Studio flow
and onto the direct/session path (internal_trigger_checkin_sms in app.py).

These lock in the behavior of the new `check_in_type == 'short'` branch:
  - happy path: sends the prompt, opens a checkin_pending session, records the
    daily send, and counts the patient as triggered
  - open-session guard: an already-open SMS session is NOT clobbered (skip)
  - daily dedupe: a patient already sent a 'checkin' today is skipped
  - missing phone: skipped, no send
  - full check-in is unchanged: still dispatched via the Studio trigger_flow

No network or real Supabase/Twilio I/O — db + _sms are mocked. Importing `app`
requires the project venv (pinned requirements.txt), same as running the server.

Run:
    python3 -m pytest tests/test_short_checkin_routing.py -v
    # or
    python3 -m unittest tests.test_short_checkin_routing
"""

import os
import sys
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import app as flask_app_module  # noqa: E402


def _post_short(client):
    return client.post('/api/internal/trigger-checkin-sms', json={'type': 'short'})


def _post_full(client):
    return client.post('/api/internal/trigger-checkin-sms', json={'type': 'full'})


class ShortCheckinRoutingTests(unittest.TestCase):
    def setUp(self):
        flask_app_module.app.testing = True
        self.client = flask_app_module.app.test_client()

        # Bypass the internal-secret gate for the test.
        self._secret_patch = mock.patch.object(
            flask_app_module, '_validate_internal_secret', return_value=(True, None)
        )
        self._secret_patch.start()

        # One due patient with a phone number.
        self._patients_patch = mock.patch.object(
            flask_app_module.db, 'get_patients_due_checkin_sms',
            return_value=[{
                'patient_id': 'p-1',
                'phone': '+15555550123',
                'provider_name': None,
                'appt_time': None,
            }],
        )
        self._patients_patch.start()

        mock.patch.object(
            flask_app_module.db, 'patient_local_today', return_value='2026-06-25'
        ).start()

    def tearDown(self):
        mock.patch.stopall()

    # ── Happy path ────────────────────────────────────────────────────────────
    def test_short_happy_path_sends_and_opens_session(self):
        with mock.patch.object(flask_app_module.db, 'has_daily_send', return_value=False), \
             mock.patch.object(flask_app_module.db, 'get_sms_session', return_value=None), \
             mock.patch.object(flask_app_module._sms, 'send_daily_checkin_prompt',
                               return_value={'ok': True}) as m_send, \
             mock.patch.object(flask_app_module.db, 'set_sms_session') as m_set, \
             mock.patch.object(flask_app_module.db, 'record_daily_send') as m_record:
            resp = _post_short(self.client)

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body['triggered'], 1)
        self.assertEqual(body['skipped'], 0)
        m_send.assert_called_once_with('+15555550123')
        # Session opened as checkin_pending for this patient.
        m_set.assert_called_once()
        args, kwargs = m_set.call_args
        self.assertEqual(args[0], 'p-1')
        self.assertEqual(args[1], 'checkin_pending')
        # Daily send recorded under the shared 'checkin' type (dedup key).
        m_record.assert_called_once_with('p-1', 'checkin', '2026-06-25')

    # ── Open-session guard: do NOT clobber an in-flight conversation ──────────
    def test_short_skips_when_session_open(self):
        with mock.patch.object(flask_app_module.db, 'has_daily_send', return_value=False), \
             mock.patch.object(flask_app_module.db, 'get_sms_session',
                               return_value={'session_type': 'med_pending'}), \
             mock.patch.object(flask_app_module._sms, 'send_daily_checkin_prompt') as m_send, \
             mock.patch.object(flask_app_module.db, 'set_sms_session') as m_set:
            resp = _post_short(self.client)

        body = resp.get_json()
        self.assertEqual(body['triggered'], 0)
        self.assertEqual(body['skipped'], 1)
        m_send.assert_not_called()
        m_set.assert_not_called()

    # ── Daily dedupe: already prompted today (e.g. via med follow-up) ─────────
    def test_short_skips_when_already_sent_today(self):
        with mock.patch.object(flask_app_module.db, 'has_daily_send', return_value=True), \
             mock.patch.object(flask_app_module.db, 'get_sms_session', return_value=None) as m_sess, \
             mock.patch.object(flask_app_module._sms, 'send_daily_checkin_prompt') as m_send:
            resp = _post_short(self.client)

        body = resp.get_json()
        self.assertEqual(body['triggered'], 0)
        self.assertEqual(body['skipped'], 1)
        m_send.assert_not_called()
        # Dedupe short-circuits before the session lookup.
        m_sess.assert_not_called()

    # ── Missing phone number ─────────────────────────────────────────────────
    def test_short_skips_when_no_phone(self):
        with mock.patch.object(flask_app_module.db, 'get_patients_due_checkin_sms',
                               return_value=[{'patient_id': 'p-1', 'phone': None}]), \
             mock.patch.object(flask_app_module._sms, 'send_daily_checkin_prompt') as m_send:
            resp = _post_short(self.client)

        body = resp.get_json()
        self.assertEqual(body['triggered'], 0)
        self.assertEqual(body['skipped'], 1)
        m_send.assert_not_called()

    # ── Send failure is counted as skipped, no session opened ────────────────
    def test_short_send_failure_does_not_open_session(self):
        with mock.patch.object(flask_app_module.db, 'has_daily_send', return_value=False), \
             mock.patch.object(flask_app_module.db, 'get_sms_session', return_value=None), \
             mock.patch.object(flask_app_module._sms, 'send_daily_checkin_prompt',
                               return_value={'ok': False}), \
             mock.patch.object(flask_app_module.db, 'set_sms_session') as m_set, \
             mock.patch.object(flask_app_module.db, 'record_daily_send') as m_record:
            resp = _post_short(self.client)

        body = resp.get_json()
        self.assertEqual(body['triggered'], 0)
        self.assertEqual(body['skipped'], 1)
        m_set.assert_not_called()
        m_record.assert_not_called()

    # ── Full check-in is untouched: still a Studio flow ──────────────────────
    def test_full_still_uses_studio_flow(self):
        with mock.patch.object(flask_app_module.db, 'get_patients_due_checkin_sms',
                               return_value=[{
                                   'patient_id': 'p-2', 'phone': '+15555550124',
                                   'provider_name': 'Dr. Test', 'appt_id': 'a-1',
                                   'appt_time': '2026-06-26T15:00:00Z',
                               }]), \
             mock.patch.object(flask_app_module.db, 'create_sms_token', return_value='tok-123'), \
             mock.patch.object(flask_app_module.db, 'mark_appointment_checkin_triggered'), \
             mock.patch.object(flask_app_module._sms, 'send_daily_checkin_prompt') as m_direct, \
             mock.patch.object(flask_app_module._twilio, 'trigger_flow', return_value='FN-sid') as m_flow:
            resp = _post_full(self.client)

        self.assertEqual(resp.status_code, 200)
        # Full path must NOT use the direct/session sender …
        m_direct.assert_not_called()
        # … it must still dispatch the Studio flow.
        m_flow.assert_called_once()
        _, kwargs = m_flow.call_args
        self.assertEqual(kwargs.get('flow_type'), 'full')


if __name__ == '__main__':
    unittest.main()
