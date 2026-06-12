"""
Unit tests for acoustic_engine.map_features_to_vocabulary() — specifically the
baseline-relative z-score path added in the June 2026 architectural update.

No audio is synthesized here; we construct minimal feature dicts directly.

Run:
    python3 -m pytest tests/test_acoustic_baseline.py -v
    # or
    python3 -m unittest tests.test_acoustic_baseline
"""

import sys
import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from acoustic_engine import map_features_to_vocabulary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _baseline(
    artic_mean=4.5, artic_sd=0.8,
    f0_cv_mean=0.18, f0_cv_sd=0.05,
    pause_ratio_mean=0.25, pause_ratio_sd=0.08,
    f0_mean_hz=150.0,
    hnr_db=12.0,
    status='established',
):
    """Return a well-formed baseline dict."""
    return {
        'status': status,
        'articulation_rate_mean': artic_mean,
        'articulation_rate_sd':   artic_sd,
        'f0_cv_mean':             f0_cv_mean,
        'f0_cv_sd':               f0_cv_sd,
        'pause_ratio_mean':       pause_ratio_mean,
        'pause_ratio_sd':         pause_ratio_sd,
        'f0_mean_hz':             f0_mean_hz,
        'hnr_db':                 hnr_db,
    }


def _features(
    articulation_rate=4.5,
    f0_cv=0.18,
    pause_ratio=0.25,
    f0_mean_hz=150.0,
    hnr_db=12.0,
    voiced_fraction=0.7,
    jitter=0.01,
    shimmer=0.05,
    speech_rate=3.5,
):
    """Return a minimal acoustic features dict."""
    return {
        'articulation_rate': articulation_rate,
        'f0_cv':             f0_cv,
        'pause_ratio':       pause_ratio,
        'f0_mean_hz':        f0_mean_hz,
        'hnr_db':            hnr_db,
        'voiced_fraction':   voiced_fraction,
        'jitter':            jitter,
        'shimmer':           shimmer,
        'speech_rate':       speech_rate,
    }


# ===========================================================================
# No-baseline path
# ===========================================================================

class TestNoBaseline(unittest.TestCase):
    """Without a baseline, absolute fallback constants govern classification."""

    def test_returns_dict_without_crash(self):
        result = map_features_to_vocabulary(_features())
        self.assertIsInstance(result, dict)

    def test_baseline_used_is_false(self):
        result = map_features_to_vocabulary(_features())
        self.assertFalse(result.get('baseline_used'),
                         msg="baseline_used should be False when no baseline passed")

    def test_normal_values_map_to_normal(self):
        # Mid-range values should not trigger any abnormal classification.
        f = _features(articulation_rate=4.5, f0_cv=0.18, pause_ratio=0.25)
        result = map_features_to_vocabulary(f)
        self.assertEqual(result.get('speech_rate'), 'normal')
        self.assertEqual(result.get('prosody'),     'normal')
        self.assertEqual(result.get('pauses'),      'normal')

    def test_slowed_via_absolute_constant(self):
        # Default absolute threshold for slowed: articulation_rate < 3.0
        f = _features(articulation_rate=2.5)
        result = map_features_to_vocabulary(f)
        self.assertEqual(result.get('speech_rate'), 'slowed')

    def test_pressured_via_absolute_constant(self):
        # Default absolute threshold for pressured: articulation_rate > 6.5
        f = _features(articulation_rate=7.0)
        result = map_features_to_vocabulary(f)
        self.assertEqual(result.get('speech_rate'), 'pressured')

    def test_flat_prosody_via_absolute_constant(self):
        # f0_cv < 0.10 → flat
        f = _features(f0_cv=0.06)
        result = map_features_to_vocabulary(f)
        self.assertEqual(result.get('prosody'), 'flat')

    def test_elevated_prosody_via_absolute_constant(self):
        # f0_cv > 0.28 → elevated
        f = _features(f0_cv=0.35)
        result = map_features_to_vocabulary(f)
        self.assertEqual(result.get('prosody'), 'elevated')

    def test_increased_pauses_via_absolute_constant(self):
        # pause_ratio > 0.40 → increased
        f = _features(pause_ratio=0.50)
        result = map_features_to_vocabulary(f)
        self.assertEqual(result.get('pauses'), 'increased')

    def test_decreased_pauses_via_absolute_constant(self):
        # pause_ratio < 0.10 → decreased
        f = _features(pause_ratio=0.05)
        result = map_features_to_vocabulary(f)
        self.assertEqual(result.get('pauses'), 'decreased')


# ===========================================================================
# Baseline-relative z-score path — status guard
# ===========================================================================

class TestBaselineStatusGuard(unittest.TestCase):
    """Baseline is only activated when status is 'established' or 'stale'."""

    def test_established_activates_baseline(self):
        bl = _baseline(status='established')
        result = map_features_to_vocabulary(_features(), baseline=bl)
        self.assertTrue(result.get('baseline_used'))

    def test_stale_activates_baseline(self):
        bl = _baseline(status='stale')
        result = map_features_to_vocabulary(_features(), baseline=bl)
        self.assertTrue(result.get('baseline_used'))

    def test_pending_does_not_activate_baseline(self):
        bl = _baseline(status='pending')
        result = map_features_to_vocabulary(_features(), baseline=bl)
        self.assertFalse(result.get('baseline_used'))

    def test_none_status_does_not_activate_baseline(self):
        bl = _baseline(status=None)
        result = map_features_to_vocabulary(_features(), baseline=bl)
        self.assertFalse(result.get('baseline_used'))

    def test_none_baseline_does_not_activate(self):
        result = map_features_to_vocabulary(_features(), baseline=None)
        self.assertFalse(result.get('baseline_used'))


# ===========================================================================
# Z-score boundary conditions — speech rate
# ===========================================================================

class TestZScoreSpeechRate(unittest.TestCase):
    """
    Baseline: artic_mean=4.5, artic_sd=0.8
    z = (artic - 4.5) / 0.8
    Slowed:    z < -1.5  → artic < 4.5 - 1.2 = 3.3
    Normal:   -1.5 ≤ z ≤ 1.5
    Pressured: z > 1.5   → artic > 4.5 + 1.2 = 5.7
    """

    def setUp(self):
        self.bl = _baseline(artic_mean=4.5, artic_sd=0.8)

    def _result(self, artic):
        return map_features_to_vocabulary(
            _features(articulation_rate=artic), baseline=self.bl
        )

    def test_exactly_at_negative_threshold_is_slowed(self):
        # z = (3.3 - 4.5) / 0.8 = -1.5 → slowed (boundary is inclusive on slowed side)
        r = self._result(3.3)
        self.assertEqual(r['speech_rate'], 'slowed')

    def test_just_above_negative_threshold_is_normal(self):
        # z ≈ -1.499 → normal
        r = self._result(3.301)
        self.assertEqual(r['speech_rate'], 'normal')

    def test_at_positive_threshold_is_pressured(self):
        # z = (5.7 - 4.5) / 0.8 = 1.5 → pressured
        r = self._result(5.7)
        self.assertEqual(r['speech_rate'], 'pressured')

    def test_just_below_positive_threshold_is_normal(self):
        # z ≈ 1.499 → normal
        r = self._result(5.699)
        self.assertEqual(r['speech_rate'], 'normal')

    def test_clearly_slowed(self):
        r = self._result(2.0)  # z = (2.0 - 4.5) / 0.8 = -3.125
        self.assertEqual(r['speech_rate'], 'slowed')

    def test_clearly_pressured(self):
        r = self._result(7.0)  # z = (7.0 - 4.5) / 0.8 = 3.125
        self.assertEqual(r['speech_rate'], 'pressured')

    def test_at_mean_is_normal(self):
        r = self._result(4.5)  # z = 0.0
        self.assertEqual(r['speech_rate'], 'normal')


# ===========================================================================
# Z-score boundary conditions — pauses
# ===========================================================================

class TestZScorePauses(unittest.TestCase):
    """
    Baseline: pause_ratio_mean=0.25, pause_ratio_sd=0.08
    z = (ratio - 0.25) / 0.08
    Increased: z > 1.5  → ratio > 0.25 + 0.12 = 0.37
    Decreased: z < -1.5 → ratio < 0.25 - 0.12 = 0.13
    """

    def setUp(self):
        self.bl = _baseline(pause_ratio_mean=0.25, pause_ratio_sd=0.08)

    def _result(self, pause_ratio):
        return map_features_to_vocabulary(
            _features(pause_ratio=pause_ratio), baseline=self.bl
        )

    def test_at_upper_threshold_is_increased(self):
        r = self._result(0.37)
        self.assertEqual(r['pauses'], 'increased')

    def test_just_below_upper_threshold_is_normal(self):
        r = self._result(0.369)
        self.assertEqual(r['pauses'], 'normal')

    def test_at_lower_threshold_is_decreased(self):
        r = self._result(0.13)
        self.assertEqual(r['pauses'], 'decreased')

    def test_just_above_lower_threshold_is_normal(self):
        r = self._result(0.131)
        self.assertEqual(r['pauses'], 'normal')

    def test_at_mean_is_normal(self):
        r = self._result(0.25)
        self.assertEqual(r['pauses'], 'normal')


# ===========================================================================
# Z-score boundary conditions — prosody
# ===========================================================================

class TestZScoreProsody(unittest.TestCase):
    """
    Baseline: f0_cv_mean=0.18, f0_cv_sd=0.05
    Flat:     z < -1.5 → f0_cv < 0.18 - 0.075 = 0.105
    Elevated: z > 1.5  → f0_cv > 0.18 + 0.075 = 0.255
    """

    def setUp(self):
        self.bl = _baseline(f0_cv_mean=0.18, f0_cv_sd=0.05)

    def _result(self, f0_cv):
        return map_features_to_vocabulary(
            _features(f0_cv=f0_cv), baseline=self.bl
        )

    def test_at_lower_threshold_is_flat(self):
        r = self._result(0.105)
        self.assertEqual(r['prosody'], 'flat')

    def test_just_above_lower_threshold_is_normal(self):
        r = self._result(0.106)
        self.assertEqual(r['prosody'], 'normal')

    def test_at_upper_threshold_is_elevated(self):
        r = self._result(0.255)
        self.assertEqual(r['prosody'], 'elevated')

    def test_just_below_upper_threshold_is_normal(self):
        r = self._result(0.254)
        self.assertEqual(r['prosody'], 'normal')

    def test_at_mean_is_normal(self):
        r = self._result(0.18)
        self.assertEqual(r['prosody'], 'normal')


# ===========================================================================
# SD=0 fallback (division-by-zero guard)
# ===========================================================================

class TestZeroSDFallback(unittest.TestCase):
    """When a baseline SD is 0, the feature falls back to absolute constants."""

    def test_zero_artic_sd_falls_back_to_absolute(self):
        bl = _baseline(artic_mean=4.5, artic_sd=0.0)
        # articulation_rate=2.0 is below absolute threshold (3.0) → slowed
        r = map_features_to_vocabulary(_features(articulation_rate=2.0), baseline=bl)
        self.assertEqual(r['speech_rate'], 'slowed')

    def test_zero_pause_sd_falls_back_to_absolute(self):
        bl = _baseline(pause_ratio_mean=0.25, pause_ratio_sd=0.0)
        # pause_ratio=0.5 is above absolute threshold (0.40) → increased
        r = map_features_to_vocabulary(_features(pause_ratio=0.50), baseline=bl)
        self.assertEqual(r['pauses'], 'increased')

    def test_zero_f0_cv_sd_falls_back_to_absolute(self):
        bl = _baseline(f0_cv_mean=0.18, f0_cv_sd=0.0)
        # f0_cv=0.06 is below absolute threshold (0.10) → flat
        r = map_features_to_vocabulary(_features(f0_cv=0.06), baseline=bl)
        self.assertEqual(r['prosody'], 'flat')

    def test_zero_sd_does_not_raise(self):
        """SD=0 must not raise ZeroDivisionError."""
        bl = _baseline(artic_sd=0.0, f0_cv_sd=0.0, pause_ratio_sd=0.0)
        try:
            map_features_to_vocabulary(_features(), baseline=bl)
        except ZeroDivisionError:
            self.fail("map_features_to_vocabulary raised ZeroDivisionError with SD=0")


# ===========================================================================
# Missing baseline fields fallback
# ===========================================================================

class TestMissingBaselineFields(unittest.TestCase):
    """When a baseline field is None, that feature falls back to absolute constants."""

    def test_none_artic_mean_falls_back(self):
        bl = _baseline()
        bl['articulation_rate_mean'] = None
        r = map_features_to_vocabulary(_features(articulation_rate=2.0), baseline=bl)
        self.assertEqual(r['speech_rate'], 'slowed')  # via absolute constant

    def test_none_artic_sd_falls_back(self):
        bl = _baseline()
        bl['articulation_rate_sd'] = None
        r = map_features_to_vocabulary(_features(articulation_rate=2.0), baseline=bl)
        self.assertEqual(r['speech_rate'], 'slowed')

    def test_all_none_baseline_falls_back_to_absolute(self):
        bl = {
            'status': 'established',
            'articulation_rate_mean': None, 'articulation_rate_sd': None,
            'f0_cv_mean': None,             'f0_cv_sd': None,
            'pause_ratio_mean': None,       'pause_ratio_sd': None,
            'f0_mean_hz': None,             'hnr_db': None,
        }
        r = map_features_to_vocabulary(_features(articulation_rate=2.0), baseline=bl)
        self.assertEqual(r['speech_rate'], 'slowed')  # via absolute constant

    def test_all_none_baseline_does_not_crash(self):
        bl = {
            'status': 'established',
            'articulation_rate_mean': None, 'articulation_rate_sd': None,
            'f0_cv_mean': None,             'f0_cv_sd': None,
            'pause_ratio_mean': None,       'pause_ratio_sd': None,
            'f0_mean_hz': None,             'hnr_db': None,
        }
        try:
            map_features_to_vocabulary(_features(), baseline=bl)
        except Exception as e:
            self.fail(f"Crashed with all-None baseline: {e}")


# ===========================================================================
# baseline_used flag and confidence boost
# ===========================================================================

class TestBaselineUsedAndConfidenceBoost(unittest.TestCase):
    """
    baseline_used = True when any field was actually classified via z-score.
    Confidence is boosted from 'medium' to 'high' when baseline was used.
    """

    def test_baseline_used_true_with_valid_baseline(self):
        bl = _baseline()
        r = map_features_to_vocabulary(_features(), baseline=bl)
        self.assertTrue(r.get('baseline_used'))

    def test_baseline_used_false_with_no_baseline(self):
        r = map_features_to_vocabulary(_features())
        self.assertFalse(r.get('baseline_used'))

    def test_confidence_boosted_from_medium_to_high(self):
        """
        Without a baseline, a mid-quality audio may get 'medium' confidence.
        With a baseline, the same features should yield 'high' confidence.
        """
        # Use audio values that would likely result in medium confidence
        # (not very extreme, not perfect quality).
        f = _features(voiced_fraction=0.65, hnr_db=10.0)

        no_bl = map_features_to_vocabulary(f)
        with_bl = map_features_to_vocabulary(f, baseline=_baseline())

        # When baseline is used and prior confidence was medium → should be high
        if no_bl.get('confidence') == 'medium':
            self.assertEqual(with_bl.get('confidence'), 'high',
                             msg="Confidence should boost from medium to high when baseline used")

    def test_baseline_used_key_always_present(self):
        """baseline_used must always be in the return dict regardless of path."""
        for bl in (None, _baseline(status='pending'), _baseline()):
            r = map_features_to_vocabulary(_features(), baseline=bl)
            self.assertIn('baseline_used', r,
                          msg=f"baseline_used missing from result with baseline={bl}")


# ===========================================================================
# Stale baseline still activates z-score path
# ===========================================================================

class TestStaleBaselineActivation(unittest.TestCase):

    def test_stale_baseline_is_used(self):
        bl = _baseline(status='stale')
        r = map_features_to_vocabulary(_features(), baseline=bl)
        self.assertTrue(r.get('baseline_used'))

    def test_stale_baseline_classifies_correctly(self):
        bl = _baseline(artic_mean=4.5, artic_sd=0.8, status='stale')
        # z = (2.0 - 4.5) / 0.8 = -3.125 → slowed
        r = map_features_to_vocabulary(_features(articulation_rate=2.0), baseline=bl)
        self.assertEqual(r['speech_rate'], 'slowed')


# ===========================================================================
# Vocabulary constraint — return values must match CLAUDE.md §24
# ===========================================================================

class TestVocabularyConstraints(unittest.TestCase):
    """
    CLAUDE.md §24 specifies allowed values for each speech feature field.
    No value outside these sets should appear in the output.
    """

    ALLOWED = {
        'speech_rate':      {'normal', 'slowed', 'pressured', 'null', None},
        'prosody':          {'normal', 'flat', 'elevated', 'null', None},
        'pauses':           {'normal', 'increased', 'decreased', 'null', None},
        'speech_coherence': {'intact', 'disorganized', 'null', None},
        'arousal':          {'normal', 'low', 'elevated', 'agitated', 'null', None},
        'vocal_affect':     {'normal', 'flat', 'strained', 'null', None},
        'confidence':       {'high', 'medium', 'low', None},
    }

    def _check_result(self, result):
        for field, allowed in self.ALLOWED.items():
            if field in result:
                val = result[field]
                self.assertIn(val, allowed,
                              msg=f"{field}={val!r} not in allowed values {allowed}")

    def test_vocabulary_no_baseline(self):
        self._check_result(map_features_to_vocabulary(_features()))

    def test_vocabulary_with_baseline(self):
        self._check_result(map_features_to_vocabulary(_features(), baseline=_baseline()))

    def test_vocabulary_extreme_slowed(self):
        self._check_result(map_features_to_vocabulary(
            _features(articulation_rate=1.0, f0_cv=0.03, pause_ratio=0.60),
            baseline=_baseline()
        ))

    def test_vocabulary_extreme_pressured(self):
        self._check_result(map_features_to_vocabulary(
            _features(articulation_rate=9.0, f0_cv=0.45, pause_ratio=0.05),
            baseline=_baseline()
        ))


if __name__ == '__main__':
    unittest.main(verbosity=2)
