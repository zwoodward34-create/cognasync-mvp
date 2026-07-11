"""Tests for the 60-second clinician check-in validator (CLAUDE.md §27)."""
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

validate = db.validate_clinician_ratings


class TestClinicianRatingsValidator(unittest.TestCase):
    def test_minimal_valid_payload(self):
        out = validate({'severity': 4})
        self.assertEqual(out['severity'], 4)
        self.assertIsNone(out['improvement'])
        self.assertIn('rated_at', out)
        self.assertEqual(out['version'], 1)
        self.assertNotIn('speech', out)
        self.assertNotIn('note', out)

    def test_full_valid_payload(self):
        out = validate({
            'severity': '5', 'improvement': 2,
            'speech': {'speech_rate': 'pressured', 'prosody': 'elevated'},
            'note': '  patient animated, tangential at times  ',
        })
        self.assertEqual(out['severity'], 5)          # string coerced
        self.assertEqual(out['improvement'], 2)
        self.assertEqual(out['speech'],
                         {'speech_rate': 'pressured', 'prosody': 'elevated'})
        self.assertEqual(out['note'], 'patient animated, tangential at times')

    def test_missing_severity_rejected(self):
        self.assertIsNone(validate({}))
        self.assertIsNone(validate({'improvement': 3}))
        self.assertIsNone(validate({'severity': None}))

    def test_out_of_range_rejected(self):
        self.assertIsNone(validate({'severity': 0}))
        self.assertIsNone(validate({'severity': 8}))
        self.assertIsNone(validate({'severity': 4, 'improvement': 9}))
        self.assertIsNone(validate({'severity': 'high'}))

    def test_empty_improvement_string_means_not_rated(self):
        out = validate({'severity': 3, 'improvement': ''})
        self.assertIsNone(out['improvement'])

    def test_out_of_vocabulary_speech_dropped_not_stored(self):
        out = validate({'severity': 4, 'speech': {
            'speech_rate': 'manic',        # not in §24 vocabulary
            'prosody': 'flat',             # valid
            'made_up_feature': 'weird',    # unknown key
        }})
        self.assertEqual(out['speech'], {'prosody': 'flat'})

    def test_note_truncated_to_200(self):
        out = validate({'severity': 4, 'note': 'x' * 500})
        self.assertEqual(len(out['note']), 200)

    def test_non_dict_rejected(self):
        self.assertIsNone(validate(None))
        self.assertIsNone(validate('severity 4'))
        self.assertIsNone(validate([4]))


if __name__ == '__main__':
    unittest.main()
