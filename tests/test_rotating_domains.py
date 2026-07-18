"""Tests for rotating-question domain policy (option C, 2026-07-12).

Provider focus targets replace the default follow-up domains, so
with_core_stimulants() appends 'stimulants' to targeted sets to keep the
caffeine question — and with it the Stim Load → NS Load → Crash Risk chain —
alive for targeted patients. Imports sms_engine standalone (no app/Flask).
"""
import importlib.util
import os
import sys
import unittest

_repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location('sms_engine', os.path.join(_repo, 'sms_engine.py'))
sms = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sms)


class TestWithCoreStimulants(unittest.TestCase):
    def test_appends_to_targeted_set(self):
        self.assertEqual(sms.with_core_stimulants(['irritability']),
                         ['irritability', 'stimulants'])

    def test_noop_when_already_targeted(self):
        self.assertEqual(sms.with_core_stimulants(['stimulants', 'sleep']),
                         ['stimulants', 'sleep'])

    def test_noop_survives_normalization_variants(self):
        # Provider-entered domain names are normalized before lookup;
        # variants must not produce a duplicate caffeine question.
        out = sms.with_core_stimulants([' Stimulants ', 'mood'])
        self.assertEqual(len([d for d in out
                              if sms._normalize_target(d) == 'stimulants']), 1)

    def test_input_not_mutated(self):
        src = ['mood']
        sms.with_core_stimulants(src)
        self.assertEqual(src, ['mood'])


class TestSelectionOutcomes(unittest.TestCase):
    """End-to-end: what questions does each patient profile actually get?"""

    def _fields(self, domains, idx):
        return [f['field_name'] for f in
                sms.get_rotating_fields_for_checkin(domains, idx)]

    def test_default_patient_gets_both_core_questions_every_time(self):
        for idx in range(4):
            self.assertEqual(self._fields(['stimulants', 'sleep'], idx),
                             ['caffeine_drinks', 'sleep_latency_minutes'])

    def test_one_provider_target_keeps_caffeine_every_text(self):
        domains = sms.with_core_stimulants(['irritability'])
        for idx in range(4):
            fields = self._fields(domains, idx)
            self.assertIn('caffeine_drinks', fields)
            self.assertIn('irritability', fields)

    def test_two_provider_targets_rotate_caffeine_two_of_three(self):
        domains = sms.with_core_stimulants(['mood', 'side_effects'])
        appearances = sum('caffeine_drinks' in self._fields(domains, idx)
                          for idx in range(3))
        self.assertEqual(appearances, 2)
        # Provider questions must still appear across the cycle
        seen = set()
        for idx in range(3):
            seen.update(self._fields(domains, idx))
        self.assertIn('enjoyment', seen)
        self.assertIn('side_effect_burden', seen)


if __name__ == '__main__':
    unittest.main()
