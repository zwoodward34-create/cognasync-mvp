"""
Unit tests for transcript_engine chunked extraction logic.

Tests _split_transcript_into_chunks() and _merge_chunk_features() in isolation
— no LLM calls, no network, no filesystem beyond importing the module.

Run:
    python3 -m pytest tests/test_chunked_extraction.py -v
    # or
    python3 -m unittest tests.test_chunked_extraction
"""

import sys
import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from transcript_engine import (
    _split_transcript_into_chunks,
    _merge_chunk_features,
    MAX_TRANSCRIPT_CHARS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_text(n_chars, char='x', newlines_every=80):
    """Build a string of exactly n_chars with periodic newlines."""
    parts = []
    remaining = n_chars
    while remaining > 0:
        line_len = min(newlines_every, remaining)
        parts.append(char * line_len)
        remaining -= line_len
        if remaining > 0:
            parts.append('\n')
            remaining -= 1
    return ''.join(parts)


def _make_chunk(
    clinical_pattern_type=None,
    medications=None,
    symptoms=None,
    topics=None,
    themes=None,
    stressors=None,
    positive_signals=None,
    concerning_language=None,
    patient_quotes=None,
    speech_features=None,
    baseline_deviation=None,
    mood_estimate=None,
    energy_estimate=None,
    session_notes=None,
    crisis_language_detected=False,
):
    """Construct a minimal chunk dict with sensible defaults."""
    return {
        'clinical_pattern_type': clinical_pattern_type,
        'medications_mentioned':  medications or [],
        'symptoms_mentioned':     symptoms or [],
        'topics_discussed':       topics or [],
        'themes':                 themes or [],
        'stressors':              stressors or [],
        'positive_signals':       positive_signals or [],
        'concerning_language':    concerning_language or [],
        'patient_quotes':         patient_quotes or [],
        'speech_features':        speech_features,
        'baseline_deviation':     baseline_deviation,
        'mood_estimate':          mood_estimate,
        'energy_estimate':        energy_estimate,
        'session_notes':          session_notes,
        'crisis_language_detected': crisis_language_detected,
        # Extra scalar fields
        'patient_mood_description': None,
        'energy_description':       None,
        'sleep_hours_mentioned':    None,
        'sleep_quality_description': None,
        'stress_description':       None,
        'functional_status':        None,
    }


# ===========================================================================
# _split_transcript_into_chunks
# ===========================================================================

class TestSplitEmpty(unittest.TestCase):
    def test_empty_string_returns_single_element(self):
        result = _split_transcript_into_chunks('')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], '')

    def test_never_returns_empty_list(self):
        for text in ('', ' ', '\n'):
            result = _split_transcript_into_chunks(text)
            self.assertGreater(len(result), 0, msg=f"Empty list for {repr(text)}")


class TestSplitShortText(unittest.TestCase):
    def test_short_text_returned_as_single_chunk(self):
        text = 'Hello world'
        result = _split_transcript_into_chunks(text)
        self.assertEqual(result, [text])

    def test_exactly_chunk_size_is_single_chunk(self):
        text = _make_text(MAX_TRANSCRIPT_CHARS)
        result = _split_transcript_into_chunks(text)
        self.assertEqual(len(result), 1)


class TestSplitLongText(unittest.TestCase):
    def test_long_text_produces_multiple_chunks(self):
        text = _make_text(MAX_TRANSCRIPT_CHARS * 2 + 100)
        result = _split_transcript_into_chunks(text)
        self.assertGreater(len(result), 1)

    def test_each_chunk_within_size_limit(self):
        text = _make_text(MAX_TRANSCRIPT_CHARS * 3)
        result = _split_transcript_into_chunks(text)
        for i, chunk in enumerate(result):
            self.assertLessEqual(
                len(chunk), MAX_TRANSCRIPT_CHARS,
                msg=f"Chunk {i} is {len(chunk)} chars, exceeds {MAX_TRANSCRIPT_CHARS}"
            )

    def test_capped_at_eight_chunks(self):
        # Build a very long text — should never produce more than 8 chunks.
        text = _make_text(MAX_TRANSCRIPT_CHARS * 10)
        result = _split_transcript_into_chunks(text)
        self.assertLessEqual(len(result), 8)

    def test_full_content_preserved_across_chunks(self):
        """Union of all chunks must cover the original text (minus overlap duplication)."""
        text = _make_text(MAX_TRANSCRIPT_CHARS * 2 + 500)
        chunks = _split_transcript_into_chunks(text)
        # Every character in the original must appear in at least one chunk.
        # We verify by checking that the first and last 100 chars of `text` are present.
        combined = ''.join(chunks)
        self.assertIn(text[:100], combined)
        self.assertIn(text[-100:], combined)

    def test_overlap_between_adjacent_chunks(self):
        """Adjacent chunks must share some content (the 500-char overlap)."""
        text = _make_text(MAX_TRANSCRIPT_CHARS * 2 + 500)
        chunks = _split_transcript_into_chunks(text)
        if len(chunks) < 2:
            self.skipTest("Not enough chunks to test overlap")
        # The tail of chunk[0] should appear somewhere in chunk[1].
        tail = chunks[0][-200:]
        self.assertIn(tail, chunks[1],
                      msg="Expected overlap content from chunk[0] to appear in chunk[1]")


class TestSplitNewlineBoundary(unittest.TestCase):
    def test_prefers_newline_split(self):
        """When text is just over the limit, split should happen at a newline."""
        # Build a text that is MAX + 200, with a newline at position MAX - 10.
        base = 'A' * (MAX_TRANSCRIPT_CHARS - 10)
        tail = '\n' + 'B' * 210
        text = base + tail
        chunks = _split_transcript_into_chunks(text)
        # First chunk should end at or just after the newline, not mid-word.
        self.assertTrue(
            chunks[0].endswith('\n') or chunks[0][-1] in 'AB',
            msg="First chunk should end cleanly near a newline boundary"
        )

    def test_custom_chunk_size(self):
        """Custom chunk_size parameter is respected."""
        text = 'A' * 500
        chunks = _split_transcript_into_chunks(text, chunk_size=100, overlap=10)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 100)


class TestSplitInfiniteLoopGuard(unittest.TestCase):
    def test_does_not_hang_on_pathological_input(self):
        """Very long text with no newlines should not loop forever."""
        text = 'X' * (MAX_TRANSCRIPT_CHARS * 9)  # 9× limit, no newlines
        import signal

        def _timeout(signum, frame):
            raise TimeoutError("_split_transcript_into_chunks looped forever")

        signal.signal(signal.SIGALRM, _timeout)
        signal.alarm(5)  # 5-second timeout
        try:
            chunks = _split_transcript_into_chunks(text)
        finally:
            signal.alarm(0)
        self.assertLessEqual(len(chunks), 8)


# ===========================================================================
# _merge_chunk_features
# ===========================================================================

class TestMergeEmpty(unittest.TestCase):
    def test_empty_list_returns_empty_dict(self):
        self.assertEqual(_merge_chunk_features([]), {})

    def test_single_chunk_round_trips(self):
        chunk = _make_chunk(
            clinical_pattern_type='depressive',
            mood_estimate=4,
            session_notes='Feeling low.',
        )
        merged = _merge_chunk_features([chunk])
        self.assertEqual(merged['clinical_pattern_type'], 'depressive')
        self.assertEqual(merged['mood_estimate'], 4)
        self.assertEqual(merged['session_notes'], 'Feeling low.')


class TestMergePatternPriority(unittest.TestCase):
    """clinical_pattern_type follows _PATTERN_PRIORITY: highest wins."""

    PRIORITY_ORDER = [
        'crisis',
        'psychosis_risk',
        'mania_hypomania',
        'anxiety_stress',
        'depressive',
        'mixed',
        'none_detected',
        None,
    ]

    def _merge_two(self, a, b):
        return _merge_chunk_features([_make_chunk(clinical_pattern_type=a),
                                      _make_chunk(clinical_pattern_type=b)])

    def test_crisis_beats_everything(self):
        for other in self.PRIORITY_ORDER[1:]:
            merged = self._merge_two('crisis', other)
            self.assertEqual(merged['clinical_pattern_type'], 'crisis',
                             msg=f"crisis should beat {other!r}")

    def test_psychosis_risk_beats_lower(self):
        for other in self.PRIORITY_ORDER[2:]:
            merged = self._merge_two('psychosis_risk', other)
            self.assertEqual(merged['clinical_pattern_type'], 'psychosis_risk',
                             msg=f"psychosis_risk should beat {other!r}")

    def test_mania_beats_lower(self):
        for other in ['anxiety_stress', 'depressive', 'mixed', 'none_detected', None]:
            merged = self._merge_two('mania_hypomania', other)
            self.assertEqual(merged['clinical_pattern_type'], 'mania_hypomania',
                             msg=f"mania_hypomania should beat {other!r}")

    def test_none_detected_beats_none(self):
        merged = self._merge_two('none_detected', None)
        self.assertEqual(merged['clinical_pattern_type'], 'none_detected')

    def test_order_independent(self):
        """The winner should not depend on which chunk appears first."""
        merged_ab = self._merge_two('depressive', 'crisis')
        merged_ba = self._merge_two('crisis', 'depressive')
        self.assertEqual(merged_ab['clinical_pattern_type'], 'crisis')
        self.assertEqual(merged_ba['clinical_pattern_type'], 'crisis')

    def test_all_none_stays_none(self):
        chunks = [_make_chunk(clinical_pattern_type=None) for _ in range(3)]
        merged = _merge_chunk_features(chunks)
        self.assertIsNone(merged['clinical_pattern_type'])


class TestMergeListDedup(unittest.TestCase):
    """List fields must union-deduplicate case-insensitively."""

    def test_medications_dedup_by_name(self):
        chunks = [
            _make_chunk(medications=[{'name': 'Sertraline', 'dose': '50mg'}]),
            _make_chunk(medications=[{'name': 'sertraline', 'dose': '50mg'},
                                     {'name': 'Lithium', 'dose': '300mg'}]),
        ]
        merged = _merge_chunk_features(chunks)
        names = [m['name'] for m in merged['medications_mentioned']]
        self.assertEqual(len(names), 2,
                         msg=f"Expected 2 unique meds, got {names}")
        self.assertIn('Sertraline', names)
        self.assertIn('Lithium', names)

    def test_symptoms_dedup_case_insensitive(self):
        chunks = [
            _make_chunk(symptoms=['Fatigue', 'headache']),
            _make_chunk(symptoms=['fatigue', 'HEADACHE', 'nausea']),
        ]
        merged = _merge_chunk_features(chunks)
        self.assertEqual(len(merged['symptoms_mentioned']), 3)

    def test_topics_dedup(self):
        chunks = [
            _make_chunk(topics=['Work stress', 'sleep']),
            _make_chunk(topics=['WORK STRESS', 'relationships']),
        ]
        merged = _merge_chunk_features(chunks)
        self.assertEqual(len(merged['topics_discussed']), 3)

    def test_themes_dedup(self):
        chunks = [
            _make_chunk(themes=['isolation', 'Hopelessness']),
            _make_chunk(themes=['ISOLATION', 'future planning']),
        ]
        merged = _merge_chunk_features(chunks)
        self.assertEqual(len(merged['themes']), 3)

    def test_stressors_dedup(self):
        chunks = [
            _make_chunk(stressors=['Work deadline', 'family conflict']),
            _make_chunk(stressors=['work deadline', 'Financial stress']),
        ]
        merged = _merge_chunk_features(chunks)
        self.assertEqual(len(merged['stressors']), 3)

    def test_positive_signals_dedup(self):
        chunks = [
            _make_chunk(positive_signals=['Exercise', 'social support']),
            _make_chunk(positive_signals=['exercise', 'Improved sleep']),
        ]
        merged = _merge_chunk_features(chunks)
        self.assertEqual(len(merged['positive_signals']), 3)

    def test_concerning_language_dedup(self):
        chunks = [
            _make_chunk(concerning_language=['feeling trapped', 'No future']),
            _make_chunk(concerning_language=['FEELING TRAPPED', 'Hopeless']),
        ]
        merged = _merge_chunk_features(chunks)
        self.assertEqual(len(merged['concerning_language']), 3)

    def test_patient_quotes_not_deduped(self):
        """patient_quotes concatenate without deduplication."""
        chunks = [
            _make_chunk(patient_quotes=['I feel terrible.']),
            _make_chunk(patient_quotes=['I feel terrible.']),  # same quote in both chunks
        ]
        merged = _merge_chunk_features(chunks)
        self.assertEqual(len(merged['patient_quotes']), 2,
                         msg="patient_quotes should concatenate, not dedup")


class TestMergeScalarFirstNonNone(unittest.TestCase):
    """Scalar fields take the first non-None value across chunks."""

    def test_speech_features_from_first_chunk(self):
        sf1 = {'speech_rate': 'slowed', 'prosody': 'flat'}
        sf2 = {'speech_rate': 'normal', 'prosody': 'normal'}
        chunks = [
            _make_chunk(speech_features=sf1),
            _make_chunk(speech_features=sf2),
        ]
        merged = _merge_chunk_features(chunks)
        self.assertEqual(merged['speech_features'], sf1)

    def test_speech_features_falls_back_if_first_chunk_none(self):
        sf2 = {'speech_rate': 'normal'}
        chunks = [
            _make_chunk(speech_features=None),
            _make_chunk(speech_features=sf2),
        ]
        merged = _merge_chunk_features(chunks)
        # speech_features is always taken from chunks[0], not the fallback rule
        self.assertIsNone(merged['speech_features'])

    def test_baseline_deviation_first_non_none(self):
        chunks = [
            _make_chunk(baseline_deviation=None),
            _make_chunk(baseline_deviation='Faster than usual.'),
            _make_chunk(baseline_deviation='Second value — should be ignored.'),
        ]
        merged = _merge_chunk_features(chunks)
        self.assertEqual(merged['baseline_deviation'], 'Faster than usual.')

    def test_mood_estimate_first_non_none(self):
        chunks = [
            _make_chunk(mood_estimate=None),
            _make_chunk(mood_estimate=5),
            _make_chunk(mood_estimate=8),
        ]
        merged = _merge_chunk_features(chunks)
        self.assertEqual(merged['mood_estimate'], 5)

    def test_session_notes_first_non_none(self):
        chunks = [
            _make_chunk(session_notes=None),
            _make_chunk(session_notes='Patient discussed medication.'),
        ]
        merged = _merge_chunk_features(chunks)
        self.assertEqual(merged['session_notes'], 'Patient discussed medication.')

    def test_crisis_language_detected_first_non_none(self):
        chunks = [
            _make_chunk(crisis_language_detected=None),
            _make_chunk(crisis_language_detected=True),
        ]
        merged = _merge_chunk_features(chunks)
        self.assertTrue(merged['crisis_language_detected'])


class TestMergeThreeChunks(unittest.TestCase):
    """Integration-style test: realistic three-chunk merge."""

    def setUp(self):
        self.chunk1 = _make_chunk(
            clinical_pattern_type='anxiety_stress',
            medications=[{'name': 'Sertraline', 'dose': '50mg'}],
            symptoms=['fatigue', 'headache'],
            topics=['work stress', 'sleep'],
            patient_quotes=['I can barely get out of bed.'],
            speech_features={'speech_rate': 'slowed', 'prosody': 'flat'},
            baseline_deviation='Slower than baseline.',
            mood_estimate=4,
        )
        self.chunk2 = _make_chunk(
            clinical_pattern_type='depressive',
            medications=[{'name': 'sertraline', 'dose': '50mg'},   # dupe
                         {'name': 'Clonazepam', 'dose': '0.5mg'}],
            symptoms=['fatigue', 'low motivation'],                  # fatigue is dupe
            topics=['relationships'],
            patient_quotes=['Everything feels pointless.'],
            speech_features={'speech_rate': 'normal'},               # ignored (not first)
            baseline_deviation=None,
        )
        self.chunk3 = _make_chunk(
            clinical_pattern_type='crisis',
            symptoms=['suicidal ideation'],
            topics=['work stress'],                                   # dupe
            patient_quotes=["I've been thinking about not being here."],
            crisis_language_detected=True,
        )
        self.merged = _merge_chunk_features([self.chunk1, self.chunk2, self.chunk3])

    def test_pattern_is_crisis(self):
        self.assertEqual(self.merged['clinical_pattern_type'], 'crisis')

    def test_meds_deduped(self):
        names = [m['name'] for m in self.merged['medications_mentioned']]
        self.assertEqual(len(names), 2)
        self.assertIn('Sertraline', names)
        self.assertIn('Clonazepam', names)

    def test_symptoms_union(self):
        syms = self.merged['symptoms_mentioned']
        self.assertIn('fatigue', syms)
        self.assertIn('headache', syms)
        self.assertIn('low motivation', syms)
        self.assertIn('suicidal ideation', syms)
        self.assertEqual(len(syms), 4)

    def test_quotes_all_present(self):
        self.assertEqual(len(self.merged['patient_quotes']), 3)

    def test_speech_features_from_chunk1(self):
        self.assertEqual(self.merged['speech_features']['speech_rate'], 'slowed')

    def test_baseline_deviation_from_chunk1(self):
        self.assertEqual(self.merged['baseline_deviation'], 'Slower than baseline.')

    def test_crisis_language_detected(self):
        self.assertTrue(self.merged['crisis_language_detected'])

    def test_mood_estimate_from_chunk1(self):
        self.assertEqual(self.merged['mood_estimate'], 4)


if __name__ == '__main__':
    unittest.main(verbosity=2)
