"""Tests for the 2026-07-10 re-pointing of patient-language analytics from
retired journals to voice-note transcripts (CLAUDE.md §17/§18/§25).

Covers: pure TTR trend math, source selection (voice primary, journals legacy,
never pooled), and the voice-note scan paths in check_safety_signals and
check_substance_patterns. DB access is stubbed at the database-module level.
"""
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


def _notes(texts):
    return [{'date': f'2026-06-{i+1:02d}', 'text': t, 'confidence_label': 'high'}
            for i, t in enumerate(texts)]


class TestTtrTrendPure(unittest.TestCase):
    def test_declining_vocabulary(self):
        rich = ["the quick brown fox jumps over seven lazy dogs near town"] * 5
        poor = ["bad bad bad day day day bad day bad day"] * 5
        out = db._ttr_trend_from_texts(rich + poor)
        self.assertEqual(out['trend'], 'declining')
        self.assertLess(out['delta'], 0)
        self.assertEqual(out['entries_analyzed'], 10)

    def test_stable_below_delta_threshold(self):
        out = db._ttr_trend_from_texts(["one two three four five"] * 10)
        self.assertEqual(out['trend'], 'stable')


class TestSourceSelection(unittest.TestCase):
    def setUp(self):
        self._orig_vn = db.get_voice_note_texts
        self._orig_admin = db.supabase_admin

    def tearDown(self):
        db.get_voice_note_texts = self._orig_vn
        db.supabase_admin = self._orig_admin

    def test_voice_notes_preferred_and_not_pooled(self):
        db.get_voice_note_texts = lambda *a, **k: _notes(
            [f"today i felt word{i} and word{i+1} in the morning" for i in range(12)])
        db.supabase_admin = MagicMock()  # journal query iterates → TypeError → []
        out = db.compute_lexical_diversity('pid', days=30)
        self.assertEqual(out['source'], 'voice_notes')
        self.assertEqual(out['entries_analyzed'], 12)  # voice only, nothing pooled
        self.assertIsNotNone(out['type_token_ratio'])

    def test_insufficient_voice_reports_insufficient(self):
        db.get_voice_note_texts = lambda *a, **k: _notes(["short note"] * 4)
        db.supabase_admin = MagicMock()
        out = db.compute_lexical_diversity('pid', days=30)
        self.assertEqual(out['trend'], 'insufficient_data')
        self.assertEqual(out['entries_analyzed'], 4)
        self.assertEqual(out['source'], 'voice_notes')

    def test_readability_carries_source(self):
        db.get_voice_note_texts = lambda *a, **k: _notes(
            ["I went to the store today. It was a fairly ordinary trip overall."] * 12)
        db.supabase_admin = MagicMock()
        out = db.compute_readability('pid', days=30)
        self.assertEqual(out['source'], 'voice_notes')
        self.assertIsNotNone(out['avg_grade_level'])


class TestSafetySignalsFromVoiceNotes(unittest.TestCase):
    def setUp(self):
        self._orig = (db.get_journals_in_range, db.get_checkins, db.get_voice_note_texts)

    def tearDown(self):
        db.get_journals_in_range, db.get_checkins, db.get_voice_note_texts = self._orig

    def test_voice_note_triggers_safety_signal(self):
        db.get_journals_in_range = lambda *a, **k: []
        db.get_checkins = lambda *a, **k: []
        db.get_voice_note_texts = lambda *a, **k: _notes(
            ["lately I have been scared to go home because he hit me again"])
        out = db.check_safety_signals('pid', days=60)
        self.assertTrue(out['signals_found'])
        self.assertEqual(out['signal_count'], 1)
        self.assertEqual(out['alert_level'], 'concern')

    def test_injury_without_partner_context_not_flagged(self):
        db.get_journals_in_range = lambda *a, **k: []
        db.get_checkins = lambda *a, **k: []
        db.get_voice_note_texts = lambda *a, **k: _notes(
            ["found a bruise on my leg after soccer practice"])
        out = db.check_safety_signals('pid', days=60)
        self.assertFalse(out['signals_found'])

    def test_no_text_no_signal(self):
        db.get_journals_in_range = lambda *a, **k: []
        db.get_checkins = lambda *a, **k: []
        db.get_voice_note_texts = lambda *a, **k: []
        out = db.check_safety_signals('pid', days=60)
        self.assertFalse(out['signals_found'])


class TestSubstanceFlagsFromVoiceNotes(unittest.TestCase):
    def setUp(self):
        self._orig = (db.get_checkins, db.get_journals, db.get_voice_note_texts)

    def tearDown(self):
        db.get_checkins, db.get_journals, db.get_voice_note_texts = self._orig

    def test_voice_note_language_flag_recorded(self):
        # One logged drinking day so the numeric gate passes (spec §17:
        # all-zero numeric data returns None before any language scan).
        db.get_checkins = lambda *a, **k: [
            {'checkin_date': '2026-06-01', 'notes': '',
             'extended_data': {'alcohol_units': 2}},
        ]
        db.get_journals = lambda *a, **k: []
        db.get_voice_note_texts = lambda *a, **k: _notes(
            ["honestly I have been drinking to cope with all of this"])
        out = db.check_substance_patterns('pid', days=30)
        self.assertIsNotNone(out)
        self.assertEqual(len(out['journal_flags']), 1)
        self.assertIn('coping', out['journal_flags'][0]['pattern'].lower())


if __name__ == '__main__':
    unittest.main()
