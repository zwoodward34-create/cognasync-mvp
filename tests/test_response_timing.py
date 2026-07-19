"""Tests for §26 Response Timing Signals — compute_response_timing() and its
circular-hour helpers. Pure computation; fake-supabase import pattern."""
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
os.environ.setdefault("SUPABASE_KEY", "test")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")

import database as db  # noqa: E402


def _row(sent, answered):
    return {'created_at': sent, 'used_at': answered}


def _rows(specs):
    """specs: [(day, sent_hh_mm, latency_minutes)] → sms_tokens-shaped rows (UTC)."""
    out = []
    for day, hhmm, lat in specs:
        sent = f"2026-06-{day:02d} {hhmm}:00+00"
        h, m = map(int, hhmm.split(':'))
        total = h * 60 + m + lat
        ans = (f"2026-06-{day + total // 1440:02d} "
               f"{(total // 60) % 24:02d}:{total % 60:02d}:00+00")
        out.append(_row(sent, ans))
    return out


class TestCircularHelpers(unittest.TestCase):
    def test_circular_mean_wraps_midnight(self):
        # 23:00 and 01:00 average to midnight, not noon
        self.assertAlmostEqual(db._circular_mean_hour([23.0, 1.0]), 0.0, places=1)

    def test_circular_diff_shortest_path(self):
        self.assertEqual(db._circular_diff_hours(1.0, 23.0), 2.0)   # later by 2h
        self.assertEqual(db._circular_diff_hours(23.0, 1.0), -2.0)  # earlier by 2h


class TestComputeResponseTiming(unittest.TestCase):
    def test_below_minimum_reports_nothing(self):
        out = db.compute_response_timing(_rows([(1, '09:00', 10), (2, '09:00', 12)]), 'UTC')
        self.assertEqual(out['n_answered'], 2)
        self.assertIsNone(out['median_latency_min'])

    def test_median_latency_no_shift_below_half_minimum(self):
        out = db.compute_response_timing(
            _rows([(1, '09:00', 10), (2, '09:00', 20), (3, '09:00', 30)]), 'UTC')
        self.assertEqual(out['n_answered'], 3)
        self.assertEqual(out['median_latency_min'], 20.0)
        self.assertIsNone(out['latency_shift'])  # <4 per half → no shift claim

    def test_slower_shift_requires_ratio_and_absolute(self):
        early = [(d, '09:00', 10) for d in range(1, 5)]     # median 10 min
        late  = [(d, '09:00', 120) for d in range(10, 14)]  # median 120 min
        out = db.compute_response_timing(_rows(early + late), 'UTC')
        self.assertEqual(out['latency_shift'], 'slower')
        self.assertEqual(out['early_median_latency_min'], 10.0)
        self.assertEqual(out['late_median_latency_min'], 120.0)

    def test_double_but_small_absolute_change_is_stable(self):
        early = [(d, '09:00', 5) for d in range(1, 5)]    # 5 min
        late  = [(d, '09:00', 12) for d in range(10, 14)]  # 12 min — 2.4x but Δ=7min
        out = db.compute_response_timing(_rows(early + late), 'UTC')
        self.assertEqual(out['latency_shift'], 'stable')

    def test_hour_drift_later(self):
        early = [(d, '09:00', 10) for d in range(1, 5)]    # replies ≈09:10
        late  = [(d, '14:00', 10) for d in range(10, 14)]  # replies ≈14:10
        out = db.compute_response_timing(_rows(early + late), 'UTC')
        self.assertEqual(out['hour_shift'], 'later')
        self.assertGreaterEqual(out['hour_drift'], 4.5)

    def test_timezone_shifts_local_hour(self):
        rows = _rows([(d, '02:00', 10) for d in range(1, 9)])  # 02:10 UTC replies
        utc  = db.compute_response_timing(rows, 'UTC')
        ny   = db.compute_response_timing(rows, 'America/New_York')  # UTC-4 in June
        self.assertAlmostEqual(utc['typical_response_hour'], 2.17, places=1)
        self.assertAlmostEqual(ny['typical_response_hour'], 22.17, places=1)

    def test_unanswered_and_garbage_rows_ignored(self):
        rows = _rows([(d, '09:00', 15) for d in range(1, 6)])
        rows += [_row('2026-06-07 09:00:00+00', None),
                 _row(None, None), _row('not-a-date', 'also-not')]
        out = db.compute_response_timing(rows, 'UTC')
        self.assertEqual(out['n_answered'], 5)
        self.assertEqual(out['median_latency_min'], 15.0)


if __name__ == '__main__':
    unittest.main()
