"""
Unit tests for the brief-quality fixes:
  - _verify_date_claims()  — deterministic date-claim fact check (spec §8)
  - _build_chart_data()    — full-window date axis (gaps visible, not cropped)
  - sanitizer additions    — dysregulation / causal-verb substitutions

Run:
    python3 -m pytest tests/test_brief_verification.py -v
"""

import sys
import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from claude_api import _verify_date_claims, _build_chart_data, _sanitize_output


CHECKIN_DATES = [
    "2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04",
    "2026-06-06", "2026-06-07", "2026-06-08",
]


class TestVerifyDateClaims(unittest.TestCase):
    def test_false_claim_is_flagged(self):
        # The exact hallucination from the 2026-06-12 test brief:
        text = ("Mood-speech divergence: Check-in mood 9-10/10 on 2026-06-09 and "
                "2026-06-12; voice recordings same dates report hopelessness.")
        flagged = _verify_date_claims(text, CHECKIN_DATES)
        self.assertEqual(len(flagged), 1)
        self.assertIn("2026-06-09", flagged[0])

    def test_valid_claim_passes(self):
        text = "Check-in mood 9/10 on 2026-06-08 with stim load 6."
        self.assertEqual(_verify_date_claims(text, CHECKIN_DATES), [])

    def test_absence_statements_pass(self):
        # Sentences ABOUT missing check-ins legitimately cite dateless days.
        cases = [
            "No check-in submissions 2026-06-09–2026-06-12 (4 days).",
            "Most recent check-in: 2026-06-08. No check-in data for final 4 days.",
            "Engagement gap: no check-ins between 2026-06-09 and 2026-06-12.",
            "medication adherence: unanswered on 2026-06-10, 2026-06-11 — no check-in.",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(_verify_date_claims(text, CHECKIN_DATES), [])

    def test_short_date_form(self):
        self.assertEqual(
            _verify_date_claims("Check-in mood 9/10 on 06-08.", CHECKIN_DATES), [])
        self.assertEqual(
            len(_verify_date_claims("Check-in mood 9/10 on 06-09.", CHECKIN_DATES)), 1)

    def test_non_checkin_dates_unconstrained(self):
        # Voice notes / journals on non-check-in dates are fine.
        text = "Voice note on 2026-06-12 reports hopelessness about job search."
        self.assertEqual(_verify_date_claims(text, CHECKIN_DATES), [])

    def test_empty_inputs(self):
        self.assertEqual(_verify_date_claims("", CHECKIN_DATES), [])
        self.assertEqual(_verify_date_claims(None, CHECKIN_DATES), [])
        flagged = _verify_date_claims("Check-in mood 9/10 on 2026-06-01.", [])
        self.assertEqual(len(flagged), 1)


class TestChartDataWindow(unittest.TestCase):
    def _checkins(self):
        return [
            {"checkin_date": "2026-06-01", "mood_score": 8, "stress_score": 2,
             "sleep_hours": 7, "extended_data": {}, "medications": []},
            {"checkin_date": "2026-06-03", "mood_score": 9, "stress_score": 1,
             "sleep_hours": 6, "extended_data": {}, "medications": []},
        ]

    def test_without_bounds_only_checkin_days(self):
        chart = _build_chart_data(self._checkins())
        self.assertEqual(chart["dates"], ["2026-06-01", "2026-06-03"])

    def test_with_bounds_spans_full_window(self):
        chart = _build_chart_data(self._checkins(), "2026-05-29", "2026-06-05")
        self.assertEqual(chart["dates"][0], "2026-05-29")
        self.assertEqual(chart["dates"][-1], "2026-06-05")
        self.assertEqual(len(chart["dates"]), 8)
        # No-data days are None, check-in days carry values
        idx_gap = chart["dates"].index("2026-06-02")
        idx_ci  = chart["dates"].index("2026-06-03")
        self.assertIsNone(chart["mood"][idx_gap])
        self.assertEqual(chart["mood"][idx_ci], 9.0)

    def test_averages_unaffected_by_padding(self):
        bare   = _build_chart_data(self._checkins())
        padded = _build_chart_data(self._checkins(), "2026-05-29", "2026-06-05")
        self.assertEqual(bare["averages"]["mood"], padded["averages"]["mood"])

    def test_invalid_bounds_fall_back(self):
        chart = _build_chart_data(self._checkins(), "not-a-date", "2026-06-05")
        self.assertEqual(chart["dates"], ["2026-06-01", "2026-06-03"])


class TestSanitizerClinicalVocab(unittest.TestCase):
    def test_dysregulation_substituted(self):
        out = _sanitize_output("Assess whether this reflects effort dysregulation.")
        self.assertNotIn("dysregulation", out.lower())
        self.assertIn("irregularity", out.lower())

    def test_causal_verb_substituted(self):
        out = _sanitize_output("Explore whether the stim spike contributed to fatigue.")
        self.assertNotIn("contributed to", out.lower())
        self.assertIn("coincided with", out.lower())


if __name__ == "__main__":
    unittest.main()
