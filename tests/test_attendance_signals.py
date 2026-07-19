"""Tests for §26.6 Scheduling & Attendance Signals (phase 1).

Covers the pure classification core (_attendance_from_rows) — event counts,
past-scheduled outcome classification with the ±1-day session window, and the
deliberate absence of attendance-verification claims in the data model."""
import os
import sys
import types
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:  # pragma: no cover - environment dependent
    import supabase  # noqa: F401
except Exception:  # pragma: no cover
    _fake = types.ModuleType("supabase")
    _fake.create_client = lambda *a, **k: MagicMock()
    _fake.Client = MagicMock
    sys.modules["supabase"] = _fake

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault(
    "SUPABASE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoiYW5vbiJ9.dummy")
os.environ.setdefault(
    "SUPABASE_SERVICE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.dummy")

import database as db  # noqa: E402

TODAY = '2026-07-12'


def _ev(event_type, to_date=None, from_date=None):
    return {'event_type': event_type, 'to_date': to_date, 'from_date': from_date}


def _appt(status, started_at):
    return {'status': status, 'started_at': started_at}


class TestAttendanceFromRows(unittest.TestCase):
    def test_event_counts(self):
        out = db._attendance_from_rows(
            [_ev('scheduled', '2026-07-20'), _ev('scheduled', '2026-08-01'),
             _ev('rescheduled', '2026-08-05', '2026-08-01'),
             _ev('cancelled', from_date='2026-07-20')],
            [], TODAY)
        self.assertEqual(out['scheduled'], 2)
        self.assertEqual(out['rescheduled'], 1)
        self.assertEqual(out['cancelled'], 1)
        self.assertTrue(out['has_activity'])

    def test_past_scheduled_with_session_same_day(self):
        out = db._attendance_from_rows(
            [], [_appt('scheduled', '2026-07-01'),
                 _appt('completed', '2026-07-01T15:00:00')], TODAY)
        self.assertEqual(out['past_scheduled'],
                         [{'date': '2026-07-01', 'outcome': 'session_recorded'}])
        self.assertEqual(out['passed_without_session'], 0)

    def test_session_within_one_day_counts(self):
        # Session started the day after the scheduled date still matches.
        out = db._attendance_from_rows(
            [], [_appt('scheduled', '2026-07-01'),
                 _appt('active', '2026-07-02T09:00:00')], TODAY)
        self.assertEqual(out['past_scheduled'][0]['outcome'], 'session_recorded')

    def test_past_scheduled_without_session(self):
        out = db._attendance_from_rows(
            [], [_appt('scheduled', '2026-07-01')], TODAY)
        self.assertEqual(out['past_scheduled'][0]['outcome'], 'no_session_recorded')
        self.assertEqual(out['passed_without_session'], 1)

    def test_future_scheduled_not_classified(self):
        out = db._attendance_from_rows(
            [], [_appt('scheduled', '2026-08-01')], TODAY)
        self.assertEqual(out['past_scheduled'], [])
        self.assertEqual(out['passed_without_session'], 0)

    def test_session_two_days_away_does_not_count(self):
        out = db._attendance_from_rows(
            [], [_appt('scheduled', '2026-07-01'),
                 _appt('completed', '2026-07-03T10:00:00')], TODAY)
        self.assertEqual(out['past_scheduled'][0]['outcome'], 'no_session_recorded')

    def test_no_activity_flag(self):
        out = db._attendance_from_rows([], [], TODAY)
        self.assertFalse(out['has_activity'])
        self.assertEqual(out['passed_without_session'], 0)

    def test_no_verification_vocabulary_in_outcomes(self):
        # The data model must never emit attendance-verification language.
        out = db._attendance_from_rows(
            [], [_appt('scheduled', '2026-07-01')], TODAY)
        flat = str(out).lower()
        for banned in ('no-show', 'no_show', 'missed', 'failed'):
            self.assertNotIn(banned, flat)


if __name__ == '__main__':
    unittest.main()
