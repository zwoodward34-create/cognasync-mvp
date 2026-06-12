"""
Unit tests for transcript_engine._build_convergent_signals() — all 11 checks.

The function is purely deterministic (no DB, no Claude calls) and accepts four
keyword dicts.  Each test class targets one check and verifies:
  - Trigger condition fires correctly
  - Non-trigger inputs produce nothing from that check
  - Key fields of the output dict are present and correct

Run:
    python3 -m pytest tests/test_convergent_signals.py -v
    # or
    python3 -m unittest tests.test_convergent_signals
"""

import sys
import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from transcript_engine import _build_convergent_signals


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cs(**kw):
    """Convenience: return a checkin_scores dict with sane defaults overridden by kw."""
    defaults = dict(mood_avg=5.0, stability_score=5.0, crash_risk=4.0,
                    ns_load=5.0, stress_avg=5.0, sleep_disruption_score=4.0,
                    energy_avg=5.0)
    defaults.update(kw)
    return defaults


def _sf(**kw):
    """Return a speech_features dict; defaults produce no signals."""
    defaults = dict(speech_rate='normal', prosody='normal', pauses='normal',
                    arousal='normal', vocal_affect='normal',
                    speech_coherence='intact')
    defaults.update(kw)
    return defaults


def _ld(**kw):
    """Return a lexical_data dict; defaults produce no signal (stable / too few entries)."""
    defaults = dict(trend='stable', delta=0.03, entries_analyzed=12,
                    type_token_ratio=0.55, earliest_ttr=0.56, latest_ttr=0.53)
    defaults.update(kw)
    return defaults


def _afd(**kw):
    """Return an affect_dimensions dict; defaults produce no signals."""
    defaults = dict(model_available=True, valence=0.50, arousal=0.50,
                    dominance=0.50, valence_label='neutral', arousal_label='neutral')
    defaults.update(kw)
    return defaults


def _result_has_convergent(result, direction=None):
    """Return True if result has at least one convergent signal, optionally filtered by direction."""
    hits = result.get('convergent', [])
    if direction:
        hits = [h for h in hits if h.get('direction') == direction]
    return len(hits) > 0


def _result_has_divergent(result, significance=None):
    """Return True if result has at least one divergent signal, optionally filtered by significance."""
    hits = result.get('divergent', [])
    if significance:
        hits = [h for h in hits if h.get('significance') == significance]
    return len(hits) > 0


# ===========================================================================
# Output structure
# ===========================================================================

class TestOutputStructure(unittest.TestCase):

    def test_returns_dict_with_convergent_and_divergent(self):
        r = _build_convergent_signals({}, {}, {})
        self.assertIn('convergent', r)
        self.assertIn('divergent', r)
        self.assertIsInstance(r['convergent'], list)
        self.assertIsInstance(r['divergent'], list)

    def test_empty_inputs_return_empty_lists(self):
        r = _build_convergent_signals({}, {}, {})
        self.assertEqual(r['convergent'], [])
        self.assertEqual(r['divergent'], [])

    def test_none_inputs_do_not_crash(self):
        try:
            r = _build_convergent_signals(None, None, None)
            self.assertIn('convergent', r)
        except Exception as e:
            self.fail(f"Crashed with None inputs: {e}")

    def test_convergent_entry_has_required_fields(self):
        # Trigger Check 2 (clear negative convergence) to get a convergent entry.
        r = _build_convergent_signals(
            _cs(mood_avg=3.0, stability_score=3.0, crash_risk=7.0),
            {}, {}
        )
        self.assertGreater(len(r['convergent']), 0)
        entry = r['convergent'][0]
        for field in ('streams', 'direction', 'observation', 'confidence'):
            self.assertIn(field, entry, msg=f"convergent entry missing field: {field}")

    def test_divergent_entry_has_required_fields(self):
        # Trigger Check 1 (mood distortion) to get a divergent entry.
        r = _build_convergent_signals(
            _cs(mood_avg=8.0, stability_score=4.0),
            {}, {}
        )
        self.assertGreater(len(r['divergent']), 0)
        entry = r['divergent'][0]
        for field in ('streams', 'observation', 'significance'):
            self.assertIn(field, entry, msg=f"divergent entry missing field: {field}")


# ===========================================================================
# Check 1 — Mood Distortion (CLAUDE.md §9)
# ===========================================================================

class TestCheck1MoodDistortion(unittest.TestCase):

    def test_positive_distortion_above_threshold_triggers(self):
        # mood 8.0, stability 5.0 → distortion 3.0 > 2.5
        r = _build_convergent_signals(_cs(mood_avg=8.0, stability_score=5.0), {}, {})
        self.assertTrue(_result_has_divergent(r))
        obs = r['divergent'][0]['observation']
        self.assertIn('higher than computed', obs)
        self.assertEqual(r['divergent'][0]['significance'], 'high')

    def test_negative_distortion_above_threshold_triggers(self):
        # mood 3.0, stability 7.0 → distortion -4.0 < -2.5
        r = _build_convergent_signals(_cs(mood_avg=3.0, stability_score=7.0), {}, {})
        self.assertTrue(_result_has_divergent(r))
        self.assertEqual(r['divergent'][0]['significance'], 'high')

    def test_distortion_exactly_at_threshold_triggers(self):
        # distortion = 2.501 → just over 2.5 → triggers
        r = _build_convergent_signals(_cs(mood_avg=7.501, stability_score=5.0), {}, {})
        self.assertTrue(_result_has_divergent(r))

    def test_distortion_just_below_threshold_does_not_trigger(self):
        # distortion = 2.499 → does NOT trigger
        r = _build_convergent_signals(_cs(mood_avg=7.499, stability_score=5.0), {}, {})
        check1_hits = [d for d in r['divergent']
                       if 'derived_scores' in d.get('streams', [])]
        self.assertEqual(len(check1_hits), 0)

    def test_no_distortion_on_matching_scores(self):
        r = _build_convergent_signals(_cs(mood_avg=5.5, stability_score=5.5), {}, {})
        check1_hits = [d for d in r['divergent']
                       if 'derived_scores' in d.get('streams', [])]
        self.assertEqual(len(check1_hits), 0)

    def test_streams_contain_self_report_and_derived_scores(self):
        r = _build_convergent_signals(_cs(mood_avg=8.0, stability_score=5.0), {}, {})
        streams = r['divergent'][0]['streams']
        self.assertIn('self_report', streams)
        self.assertIn('derived_scores', streams)


# ===========================================================================
# Check 2 — Negative convergent trajectory
# ===========================================================================

class TestCheck2NegativeConvergence(unittest.TestCase):

    def test_all_three_in_range_triggers(self):
        r = _build_convergent_signals(
            _cs(mood_avg=3.0, stability_score=3.5, crash_risk=7.0),
            {}, {}
        )
        hits = [c for c in r['convergent'] if c.get('direction') == 'negative']
        self.assertGreater(len(hits), 0)

    def test_confidence_is_strong(self):
        r = _build_convergent_signals(
            _cs(mood_avg=3.0, stability_score=3.5, crash_risk=7.0),
            {}, {}
        )
        hits = [c for c in r['convergent']
                if c.get('direction') == 'negative'
                and 'derived_scores' in c.get('streams', [])]
        self.assertTrue(any(h['confidence'] == 'strong' for h in hits))

    def test_mood_just_above_threshold_does_not_trigger(self):
        # mood_avg = 4.01 → threshold is ≤ 4.0
        r = _build_convergent_signals(
            _cs(mood_avg=4.01, stability_score=3.5, crash_risk=7.0),
            {}, {}
        )
        check2_hits = [c for c in r['convergent']
                       if 'derived_scores' in c.get('streams', [])
                       and c.get('direction') == 'negative'
                       and c.get('confidence') == 'strong']
        self.assertEqual(len(check2_hits), 0)

    def test_crash_risk_just_below_threshold_does_not_trigger(self):
        # crash_risk = 5.99 → threshold is ≥ 6.0
        r = _build_convergent_signals(
            _cs(mood_avg=3.0, stability_score=3.5, crash_risk=5.99),
            {}, {}
        )
        check2_hits = [c for c in r['convergent']
                       if 'derived_scores' in c.get('streams', [])
                       and c.get('direction') == 'negative'
                       and c.get('confidence') == 'strong']
        self.assertEqual(len(check2_hits), 0)

    def test_streams_contain_self_report_and_derived_scores(self):
        r = _build_convergent_signals(
            _cs(mood_avg=3.0, stability_score=3.5, crash_risk=7.0),
            {}, {}
        )
        hits = [c for c in r['convergent'] if c.get('direction') == 'negative']
        self.assertGreater(len(hits), 0)
        streams = hits[0]['streams']
        self.assertIn('self_report', streams)
        self.assertIn('derived_scores', streams)


# ===========================================================================
# Check 3 — Speech-mood negative convergence
# ===========================================================================

class TestCheck3SpeechMoodNegativeConvergence(unittest.TestCase):

    def test_one_speech_marker_and_low_mood_yields_moderate(self):
        r = _build_convergent_signals(
            _cs(mood_avg=4.0),
            _sf(speech_rate='slowed'),
            {}
        )
        hits = [c for c in r['convergent']
                if 'acoustic' in c.get('streams', [])]
        self.assertGreater(len(hits), 0)
        self.assertEqual(hits[0]['confidence'], 'moderate')

    def test_two_speech_markers_yields_strong(self):
        r = _build_convergent_signals(
            _cs(mood_avg=4.0),
            _sf(speech_rate='slowed', arousal='low'),
            {}
        )
        hits = [c for c in r['convergent']
                if 'acoustic' in c.get('streams', [])]
        self.assertGreater(len(hits), 0)
        self.assertEqual(hits[0]['confidence'], 'strong')

    def test_three_speech_markers_yields_strong(self):
        r = _build_convergent_signals(
            _cs(mood_avg=4.0),
            _sf(speech_rate='slowed', arousal='low', prosody='flat'),
            {}
        )
        hits = [c for c in r['convergent']
                if 'acoustic' in c.get('streams', [])]
        self.assertTrue(any(h['confidence'] == 'strong' for h in hits))

    def test_mood_at_boundary_4_5_triggers(self):
        r = _build_convergent_signals(
            _cs(mood_avg=4.5),
            _sf(arousal='low'),
            {}
        )
        hits = [c for c in r['convergent'] if 'acoustic' in c.get('streams', [])]
        self.assertGreater(len(hits), 0)

    def test_mood_just_above_4_5_does_not_trigger(self):
        r = _build_convergent_signals(
            _cs(mood_avg=4.51),
            _sf(speech_rate='slowed', arousal='low'),
            {}
        )
        hits = [c for c in r['convergent'] if 'acoustic' in c.get('streams', [])]
        self.assertEqual(len(hits), 0)

    def test_no_speech_markers_does_not_trigger(self):
        r = _build_convergent_signals(
            _cs(mood_avg=3.0),
            _sf(),  # all normal
            {}
        )
        # Check 3 acoustic hit should not exist
        hits = [c for c in r['convergent'] if 'acoustic' in c.get('streams', [])]
        self.assertEqual(len(hits), 0)

    def test_direction_is_negative(self):
        r = _build_convergent_signals(
            _cs(mood_avg=4.0),
            _sf(prosody='flat'),
            {}
        )
        hits = [c for c in r['convergent'] if 'acoustic' in c.get('streams', [])]
        self.assertTrue(all(h['direction'] == 'negative' for h in hits))


# ===========================================================================
# Check 4 — Speech-mood divergence (pressured/agitated vs. normal mood)
# ===========================================================================

class TestCheck4SpeechMoodDivergence(unittest.TestCase):

    def test_pressured_speech_high_mood_triggers_divergent(self):
        r = _build_convergent_signals(
            _cs(mood_avg=7.0),
            _sf(speech_rate='pressured'),
            {}
        )
        hits = [d for d in r['divergent']
                if 'acoustic' in d.get('streams', [])]
        self.assertGreater(len(hits), 0)
        self.assertEqual(hits[0]['significance'], 'medium')

    def test_agitated_arousal_high_mood_triggers_divergent(self):
        r = _build_convergent_signals(
            _cs(mood_avg=6.5),
            _sf(arousal='agitated'),
            {}
        )
        hits = [d for d in r['divergent']
                if 'acoustic' in d.get('streams', [])]
        self.assertGreater(len(hits), 0)

    def test_mood_at_boundary_6_0_triggers(self):
        r = _build_convergent_signals(
            _cs(mood_avg=6.0),
            _sf(speech_rate='pressured'),
            {}
        )
        hits = [d for d in r['divergent'] if 'acoustic' in d.get('streams', [])]
        self.assertGreater(len(hits), 0)

    def test_mood_just_below_6_does_not_trigger(self):
        r = _build_convergent_signals(
            _cs(mood_avg=5.99),
            _sf(speech_rate='pressured'),
            {}
        )
        hits = [d for d in r['divergent'] if 'acoustic' in d.get('streams', [])]
        self.assertEqual(len(hits), 0)

    def test_pressured_speech_low_mood_does_not_trigger_check4(self):
        # Pressured speech + low mood is not a divergence (mood not ≥ 6.0)
        r = _build_convergent_signals(
            _cs(mood_avg=3.0),
            _sf(speech_rate='pressured'),
            {}
        )
        hits = [d for d in r['divergent'] if 'acoustic' in d.get('streams', [])]
        self.assertEqual(len(hits), 0)


# ===========================================================================
# Check 5 — Lexical-mood convergence/divergence
# ===========================================================================

class TestCheck5LexicalMood(unittest.TestCase):

    def test_declining_lex_low_mood_yields_convergent(self):
        r = _build_convergent_signals(
            _cs(mood_avg=4.0),
            {},
            _ld(trend='declining', delta=-0.12, entries_analyzed=12)
        )
        hits = [c for c in r['convergent'] if 'lexical' in c.get('streams', [])]
        self.assertGreater(len(hits), 0)
        self.assertEqual(hits[0]['confidence'], 'moderate')

    def test_declining_lex_high_mood_yields_divergent(self):
        r = _build_convergent_signals(
            _cs(mood_avg=7.0),
            {},
            _ld(trend='declining', delta=-0.12, entries_analyzed=12)
        )
        hits = [d for d in r['divergent'] if 'lexical' in d.get('streams', [])]
        self.assertGreater(len(hits), 0)
        self.assertEqual(hits[0]['significance'], 'medium')

    def test_delta_below_threshold_does_not_trigger(self):
        # |delta| = 0.09 < 0.10 → no signal
        r = _build_convergent_signals(
            _cs(mood_avg=3.5),
            {},
            _ld(trend='declining', delta=-0.09, entries_analyzed=12)
        )
        hits = [c for c in r['convergent'] if 'lexical' in c.get('streams', [])]
        self.assertEqual(len(hits), 0)

    def test_delta_at_threshold_triggers(self):
        # |delta| = 0.10 → exactly at threshold → triggers
        r = _build_convergent_signals(
            _cs(mood_avg=4.0),
            {},
            _ld(trend='declining', delta=-0.10, entries_analyzed=12)
        )
        hits = [c for c in r['convergent'] if 'lexical' in c.get('streams', [])]
        self.assertGreater(len(hits), 0)

    def test_fewer_than_10_entries_does_not_trigger(self):
        r = _build_convergent_signals(
            _cs(mood_avg=3.5),
            {},
            _ld(trend='declining', delta=-0.15, entries_analyzed=9)
        )
        hits = [c for c in r['convergent'] if 'lexical' in c.get('streams', [])]
        self.assertEqual(len(hits), 0)

    def test_exactly_10_entries_triggers(self):
        r = _build_convergent_signals(
            _cs(mood_avg=4.0),
            {},
            _ld(trend='declining', delta=-0.12, entries_analyzed=10)
        )
        hits = [c for c in r['convergent'] if 'lexical' in c.get('streams', [])]
        self.assertGreater(len(hits), 0)

    def test_stable_trend_does_not_trigger(self):
        r = _build_convergent_signals(
            _cs(mood_avg=4.0),
            {},
            _ld(trend='stable', delta=-0.12, entries_analyzed=12)
        )
        hits = [c for c in r['convergent'] if 'lexical' in c.get('streams', [])]
        self.assertEqual(len(hits), 0)

    def test_insufficient_data_trend_does_not_trigger(self):
        r = _build_convergent_signals(
            _cs(mood_avg=4.0),
            {},
            _ld(trend='insufficient_data', delta=-0.15, entries_analyzed=12)
        )
        hits = [c for c in r['convergent'] if 'lexical' in c.get('streams', [])]
        self.assertEqual(len(hits), 0)

    def test_mood_in_middle_range_with_declining_lex_produces_no_signal(self):
        # mood_avg=5.5 is neither ≤ 4.5 nor ≥ 6.0 → no convergent or divergent
        r = _build_convergent_signals(
            _cs(mood_avg=5.5),
            {},
            _ld(trend='declining', delta=-0.15, entries_analyzed=12)
        )
        lex_hits = ([c for c in r['convergent'] if 'lexical' in c.get('streams', [])] +
                    [d for d in r['divergent']   if 'lexical' in d.get('streams', [])])
        self.assertEqual(len(lex_hits), 0)


# ===========================================================================
# Check 6 — Nervous system load convergence
# ===========================================================================

class TestCheck6NSLoadConvergence(unittest.TestCase):

    def test_ns_load_and_stress_high_without_acoustic_yields_moderate(self):
        r = _build_convergent_signals(
            _cs(ns_load=7.5, stress_avg=7.0),
            {},  # no speech features
            {}
        )
        hits = [c for c in r['convergent'] if c.get('direction') == 'elevated_load']
        self.assertGreater(len(hits), 0)
        self.assertEqual(hits[0]['confidence'], 'moderate')

    def test_with_elevated_arousal_yields_strong_and_three_streams(self):
        r = _build_convergent_signals(
            _cs(ns_load=7.5, stress_avg=7.0),
            _sf(arousal='elevated'),
            {}
        )
        hits = [c for c in r['convergent'] if c.get('direction') == 'elevated_load']
        self.assertGreater(len(hits), 0)
        strong_hits = [h for h in hits if h['confidence'] == 'strong']
        self.assertGreater(len(strong_hits), 0)
        self.assertIn('acoustic', strong_hits[0]['streams'])

    def test_with_agitated_arousal_yields_strong(self):
        r = _build_convergent_signals(
            _cs(ns_load=7.5, stress_avg=7.0),
            _sf(arousal='agitated'),
            {}
        )
        hits = [c for c in r['convergent'] if c.get('direction') == 'elevated_load']
        strong_hits = [h for h in hits if h['confidence'] == 'strong']
        self.assertGreater(len(strong_hits), 0)

    def test_with_strained_vocal_affect_yields_strong(self):
        r = _build_convergent_signals(
            _cs(ns_load=7.5, stress_avg=7.0),
            _sf(vocal_affect='strained'),
            {}
        )
        hits = [c for c in r['convergent'] if c.get('direction') == 'elevated_load']
        strong_hits = [h for h in hits if h['confidence'] == 'strong']
        self.assertGreater(len(strong_hits), 0)

    def test_ns_load_just_below_threshold_does_not_trigger(self):
        r = _build_convergent_signals(
            _cs(ns_load=6.99, stress_avg=7.0),
            {},
            {}
        )
        hits = [c for c in r['convergent'] if c.get('direction') == 'elevated_load']
        self.assertEqual(len(hits), 0)

    def test_stress_just_below_threshold_does_not_trigger(self):
        r = _build_convergent_signals(
            _cs(ns_load=7.5, stress_avg=5.99),
            {},
            {}
        )
        hits = [c for c in r['convergent'] if c.get('direction') == 'elevated_load']
        self.assertEqual(len(hits), 0)


# ===========================================================================
# Check 7 — Positive trajectory convergence
# ===========================================================================

class TestCheck7PositiveConvergence(unittest.TestCase):

    def test_all_three_positive_no_speech_yields_moderate(self):
        r = _build_convergent_signals(
            _cs(mood_avg=7.0, stability_score=6.5, crash_risk=2.0),
            None,
            {}
        )
        hits = [c for c in r['convergent'] if c.get('direction') == 'positive']
        self.assertGreater(len(hits), 0)
        self.assertEqual(hits[0]['confidence'], 'moderate')

    def test_all_three_positive_benign_speech_yields_strong(self):
        r = _build_convergent_signals(
            _cs(mood_avg=7.0, stability_score=6.5, crash_risk=2.0),
            _sf(speech_rate='normal', arousal='normal'),
            {}
        )
        hits = [c for c in r['convergent'] if c.get('direction') == 'positive']
        self.assertGreater(len(hits), 0)
        strong_hits = [h for h in hits if h['confidence'] == 'strong']
        self.assertGreater(len(strong_hits), 0)
        self.assertIn('acoustic', strong_hits[0]['streams'])

    def test_mood_at_boundary_6_5_triggers(self):
        r = _build_convergent_signals(
            _cs(mood_avg=6.5, stability_score=6.0, crash_risk=3.0),
            None,
            {}
        )
        hits = [c for c in r['convergent'] if c.get('direction') == 'positive']
        self.assertGreater(len(hits), 0)

    def test_mood_just_below_6_5_does_not_trigger(self):
        r = _build_convergent_signals(
            _cs(mood_avg=6.49, stability_score=6.0, crash_risk=3.0),
            None,
            {}
        )
        hits = [c for c in r['convergent'] if c.get('direction') == 'positive']
        self.assertEqual(len(hits), 0)

    def test_crash_risk_just_above_3_does_not_trigger(self):
        r = _build_convergent_signals(
            _cs(mood_avg=7.0, stability_score=6.5, crash_risk=3.01),
            None,
            {}
        )
        hits = [c for c in r['convergent'] if c.get('direction') == 'positive']
        self.assertEqual(len(hits), 0)


# ===========================================================================
# Checks 8–11 gate: VAD not available → no VAD checks
# ===========================================================================

class TestVADGate(unittest.TestCase):

    def test_none_affect_dimensions_skips_all_vad_checks(self):
        r = _build_convergent_signals(
            _cs(mood_avg=3.0),
            {},
            {},
            affect_dimensions=None
        )
        vad_hits = (
            [c for c in r['convergent'] if 'affect_model' in c.get('streams', [])] +
            [d for d in r['divergent']   if 'affect_model' in d.get('streams', [])]
        )
        self.assertEqual(len(vad_hits), 0)

    def test_model_available_false_skips_all_vad_checks(self):
        r = _build_convergent_signals(
            _cs(mood_avg=3.0),
            {},
            {},
            affect_dimensions=_afd(model_available=False, valence=0.20)
        )
        vad_hits = (
            [c for c in r['convergent'] if 'affect_model' in c.get('streams', [])] +
            [d for d in r['divergent']   if 'affect_model' in d.get('streams', [])]
        )
        self.assertEqual(len(vad_hits), 0)

    def test_valence_none_skips_all_vad_checks(self):
        r = _build_convergent_signals(
            _cs(mood_avg=3.0),
            {},
            {},
            affect_dimensions=_afd(valence=None)
        )
        vad_hits = (
            [c for c in r['convergent'] if 'affect_model' in c.get('streams', [])] +
            [d for d in r['divergent']   if 'affect_model' in d.get('streams', [])]
        )
        self.assertEqual(len(vad_hits), 0)


# ===========================================================================
# Check 8 — VAD low-valence + low mood (negative convergence)
# ===========================================================================

class TestCheck8VADLowValenceLowMood(unittest.TestCase):

    def test_low_valence_low_mood_low_arousal_yields_strong(self):
        # valence < 0.35, mood ≤ 4.5, vad_arousal ≤ 0.40 → strong
        r = _build_convergent_signals(
            _cs(mood_avg=4.0),
            {},
            {},
            affect_dimensions=_afd(valence=0.30, arousal=0.35)
        )
        hits = [c for c in r['convergent']
                if 'affect_model' in c.get('streams', [])
                and c.get('direction') == 'negative']
        self.assertGreater(len(hits), 0)
        self.assertEqual(hits[0]['confidence'], 'strong')

    def test_low_valence_low_mood_high_arousal_yields_moderate(self):
        # vad_arousal > 0.40 → moderate
        r = _build_convergent_signals(
            _cs(mood_avg=4.0),
            {},
            {},
            affect_dimensions=_afd(valence=0.30, arousal=0.55)
        )
        hits = [c for c in r['convergent']
                if 'affect_model' in c.get('streams', [])
                and c.get('direction') == 'negative']
        self.assertGreater(len(hits), 0)
        self.assertEqual(hits[0]['confidence'], 'moderate')

    def test_valence_at_0_35_triggers(self):
        # valence < 0.35 → 0.349 triggers; 0.35 does NOT
        r_trigger = _build_convergent_signals(
            _cs(mood_avg=4.0), {}, {},
            affect_dimensions=_afd(valence=0.349)
        )
        hits = [c for c in r_trigger['convergent'] if 'affect_model' in c.get('streams', [])]
        self.assertGreater(len(hits), 0)

    def test_valence_exactly_0_35_does_not_trigger(self):
        r = _build_convergent_signals(
            _cs(mood_avg=4.0), {}, {},
            affect_dimensions=_afd(valence=0.35)
        )
        hits = [c for c in r['convergent']
                if 'affect_model' in c.get('streams', []) and c.get('direction') == 'negative']
        self.assertEqual(len(hits), 0)

    def test_mood_above_4_5_does_not_trigger(self):
        r = _build_convergent_signals(
            _cs(mood_avg=4.51), {}, {},
            affect_dimensions=_afd(valence=0.30)
        )
        hits = [c for c in r['convergent']
                if 'affect_model' in c.get('streams', []) and c.get('direction') == 'negative']
        self.assertEqual(len(hits), 0)

    def test_streams_contain_self_report_and_affect_model(self):
        r = _build_convergent_signals(
            _cs(mood_avg=4.0), {}, {},
            affect_dimensions=_afd(valence=0.30, arousal=0.35)
        )
        hits = [c for c in r['convergent'] if 'affect_model' in c.get('streams', [])]
        self.assertGreater(len(hits), 0)
        streams = hits[0]['streams']
        self.assertIn('self_report', streams)
        self.assertIn('affect_model', streams)


# ===========================================================================
# Check 9 — VAD high-valence + elevated mood (positive convergence)
# ===========================================================================

class TestCheck9VADHighValenceHighMood(unittest.TestCase):

    def test_high_valence_high_mood_with_stability_yields_strong(self):
        # valence > 0.65, mood ≥ 6.5, stability_score ≥ 6.0 → strong
        r = _build_convergent_signals(
            _cs(mood_avg=7.0, stability_score=6.5),
            {},
            {},
            affect_dimensions=_afd(valence=0.70, arousal=0.5)
        )
        hits = [c for c in r['convergent']
                if 'affect_model' in c.get('streams', [])
                and c.get('direction') == 'positive']
        self.assertGreater(len(hits), 0)
        self.assertEqual(hits[0]['confidence'], 'strong')

    def test_high_valence_high_mood_without_stability_yields_moderate(self):
        # stability_score < 6.0 → moderate
        r = _build_convergent_signals(
            _cs(mood_avg=7.0, stability_score=5.5),
            {},
            {},
            affect_dimensions=_afd(valence=0.70, arousal=0.5)
        )
        hits = [c for c in r['convergent']
                if 'affect_model' in c.get('streams', [])
                and c.get('direction') == 'positive']
        self.assertGreater(len(hits), 0)
        self.assertEqual(hits[0]['confidence'], 'moderate')

    def test_valence_exactly_0_65_does_not_trigger(self):
        # must be strictly > 0.65
        r = _build_convergent_signals(
            _cs(mood_avg=7.0, stability_score=6.5), {}, {},
            affect_dimensions=_afd(valence=0.65)
        )
        hits = [c for c in r['convergent']
                if 'affect_model' in c.get('streams', []) and c.get('direction') == 'positive']
        self.assertEqual(len(hits), 0)

    def test_mood_below_6_5_does_not_trigger(self):
        r = _build_convergent_signals(
            _cs(mood_avg=6.49, stability_score=6.5), {}, {},
            affect_dimensions=_afd(valence=0.70)
        )
        hits = [c for c in r['convergent']
                if 'affect_model' in c.get('streams', []) and c.get('direction') == 'positive']
        self.assertEqual(len(hits), 0)

    def test_check_8_and_9_mutually_exclusive(self):
        # A single call cannot produce both a check-8 and a check-9 hit
        # because their valence conditions (< 0.35 vs. > 0.65) are disjoint.
        # Verify via an extreme case: valence=0.80, mood=3.0 → only Check 9 boundary check
        r = _build_convergent_signals(
            _cs(mood_avg=3.0), {}, {},
            affect_dimensions=_afd(valence=0.80)
        )
        # Check 8 needs mood ≤ 4.5; check 9 needs mood ≥ 6.5. mood=3.0 → only check8 possible
        # But valence=0.80 > 0.65, so Check 9 needs mood ≥ 6.5 → doesn't fire.
        # Check 8 needs valence < 0.35 → doesn't fire.
        affect_model_convergent = [c for c in r['convergent']
                                   if 'affect_model' in c.get('streams', [])]
        # Neither 8 nor 9 should fire here
        negative_positive = [h for h in affect_model_convergent
                              if h.get('direction') in ('negative', 'positive')]
        self.assertEqual(len(negative_positive), 0)


# ===========================================================================
# Check 10 — VAD-self-report divergence
# ===========================================================================

class TestCheck10VADSelfReportDivergence(unittest.TestCase):

    def test_case_a_high_mood_low_valence_triggers_divergent(self):
        # mood_avg ≥ 6.5, valence < 0.40
        r = _build_convergent_signals(
            _cs(mood_avg=7.0), {}, {},
            affect_dimensions=_afd(valence=0.35)
        )
        hits = [d for d in r['divergent'] if 'affect_model' in d.get('streams', [])]
        self.assertGreater(len(hits), 0)
        self.assertEqual(hits[0]['significance'], 'medium')

    def test_case_b_low_mood_high_valence_triggers_divergent(self):
        # mood_avg ≤ 4.0, valence > 0.60
        r = _build_convergent_signals(
            _cs(mood_avg=3.5), {}, {},
            affect_dimensions=_afd(valence=0.65)
        )
        hits = [d for d in r['divergent'] if 'affect_model' in d.get('streams', [])]
        self.assertGreater(len(hits), 0)
        self.assertEqual(hits[0]['significance'], 'medium')

    def test_case_a_boundary_mood_6_5_triggers(self):
        r = _build_convergent_signals(
            _cs(mood_avg=6.5), {}, {},
            affect_dimensions=_afd(valence=0.39)
        )
        hits = [d for d in r['divergent'] if 'affect_model' in d.get('streams', [])]
        self.assertGreater(len(hits), 0)

    def test_case_a_mood_just_below_6_5_does_not_trigger(self):
        r = _build_convergent_signals(
            _cs(mood_avg=6.49), {}, {},
            affect_dimensions=_afd(valence=0.30)
        )
        hits = [d for d in r['divergent'] if 'affect_model' in d.get('streams', [])]
        # Check 10 should not fire (mood < 6.5 and mood > 4.0)
        self.assertEqual(len(hits), 0)

    def test_case_b_boundary_mood_4_0_triggers(self):
        r = _build_convergent_signals(
            _cs(mood_avg=4.0), {}, {},
            affect_dimensions=_afd(valence=0.61)
        )
        hits = [d for d in r['divergent'] if 'affect_model' in d.get('streams', [])]
        self.assertGreater(len(hits), 0)

    def test_mid_range_mood_and_valence_do_not_trigger(self):
        # mood=5.5, valence=0.5 → neither Case A nor Case B
        r = _build_convergent_signals(
            _cs(mood_avg=5.5), {}, {},
            affect_dimensions=_afd(valence=0.50)
        )
        hits = [d for d in r['divergent'] if 'affect_model' in d.get('streams', [])]
        self.assertEqual(len(hits), 0)


# ===========================================================================
# Check 11 — High VAD arousal + acoustic agitation convergence
# ===========================================================================

class TestCheck11VADArousalAcousticConvergence(unittest.TestCase):

    def test_high_vad_arousal_plus_acoustic_agitated_triggers(self):
        r = _build_convergent_signals(
            _cs(), {},
            {},
            affect_dimensions={
                **_afd(valence=0.5, arousal=0.70),
            }
        )
        # Need to also pass speech features showing agitation
        r2 = _build_convergent_signals(
            _cs(),
            _sf(arousal='agitated'),
            {},
            affect_dimensions=_afd(valence=0.5, arousal=0.70)
        )
        hits = [c for c in r2['convergent']
                if 'affect_model' in c.get('streams', [])
                and c.get('direction') == 'elevated_load']
        self.assertGreater(len(hits), 0)
        self.assertEqual(hits[0]['confidence'], 'moderate')

    def test_high_vad_arousal_plus_pressured_speech_triggers(self):
        r = _build_convergent_signals(
            _cs(),
            _sf(speech_rate='pressured'),
            {},
            affect_dimensions=_afd(valence=0.5, arousal=0.70)
        )
        hits = [c for c in r['convergent']
                if 'affect_model' in c.get('streams', [])
                and c.get('direction') == 'elevated_load']
        self.assertGreater(len(hits), 0)

    def test_vad_arousal_exactly_0_65_does_not_trigger(self):
        # must be strictly > 0.65
        r = _build_convergent_signals(
            _cs(),
            _sf(arousal='agitated'),
            {},
            affect_dimensions=_afd(valence=0.5, arousal=0.65)
        )
        hits = [c for c in r['convergent']
                if 'affect_model' in c.get('streams', [])
                and c.get('direction') == 'elevated_load']
        self.assertEqual(len(hits), 0)

    def test_high_vad_arousal_but_normal_speech_does_not_trigger(self):
        r = _build_convergent_signals(
            _cs(),
            _sf(arousal='normal', speech_rate='normal'),
            {},
            affect_dimensions=_afd(valence=0.5, arousal=0.80)
        )
        hits = [c for c in r['convergent']
                if 'affect_model' in c.get('streams', [])
                and c.get('direction') == 'elevated_load']
        self.assertEqual(len(hits), 0)

    def test_streams_contain_affect_model_and_acoustic(self):
        r = _build_convergent_signals(
            _cs(),
            _sf(arousal='agitated'),
            {},
            affect_dimensions=_afd(valence=0.5, arousal=0.70)
        )
        hits = [c for c in r['convergent']
                if 'affect_model' in c.get('streams', [])
                and c.get('direction') == 'elevated_load']
        self.assertGreater(len(hits), 0)
        streams = hits[0]['streams']
        self.assertIn('affect_model', streams)
        self.assertIn('acoustic', streams)


# ===========================================================================
# Multi-check interaction
# ===========================================================================

class TestMultiCheckInteraction(unittest.TestCase):

    def test_heavily_negative_scenario_produces_multiple_convergent(self):
        """
        All negative signals combined should produce multiple convergent entries —
        demonstrating that independent checks accumulate independently.
        """
        r = _build_convergent_signals(
            _cs(mood_avg=3.0, stability_score=3.5, crash_risk=7.0,
                ns_load=7.5, stress_avg=6.5),
            _sf(speech_rate='slowed', arousal='elevated'),
            _ld(trend='declining', delta=-0.15, entries_analyzed=12),
            affect_dimensions=_afd(valence=0.28, arousal=0.38)
        )
        self.assertGreaterEqual(len(r['convergent']), 3,
                                msg="Expected at least 3 convergent signals in a heavily negative scenario")

    def test_mood_distortion_and_speech_divergence_can_coexist(self):
        """
        Check 1 (mood > stability) and Check 4 (pressured speech) can both
        fire in the same call — they are independent.
        """
        r = _build_convergent_signals(
            _cs(mood_avg=8.0, stability_score=5.0),   # Check 1 fires
            _sf(speech_rate='pressured'),              # Check 4 fires (mood=8.0 ≥ 6.0)
            {}
        )
        check1 = [d for d in r['divergent'] if 'derived_scores' in d.get('streams', [])]
        check4 = [d for d in r['divergent'] if 'acoustic' in d.get('streams', [])]
        self.assertGreater(len(check1), 0, msg="Check 1 should fire")
        self.assertGreater(len(check4), 0, msg="Check 4 should fire")

    def test_all_neutral_inputs_produce_no_signals(self):
        r = _build_convergent_signals(
            _cs(mood_avg=5.0, stability_score=5.0, crash_risk=4.0,
                ns_load=5.0, stress_avg=5.0),
            _sf(),
            _ld(),
            affect_dimensions=_afd(valence=0.50, arousal=0.50)
        )
        self.assertEqual(r['convergent'], [])
        self.assertEqual(r['divergent'], [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
