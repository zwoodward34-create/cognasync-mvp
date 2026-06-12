"""Unit tests for the accuracy improvements added to acoustic_engine:

  * estimate_syllables / compute_transcript_timing — speech rate from ASR word
    timestamps (replacing the unreliable energy-envelope syllable proxy).
  * refine_speech_rate_with_transcript — overrides the acoustic speech_rate
    label with the transcript-derived rate, with cross-check + confidence cap.
  * reconcile_arousal — reconciles the RMS-amplitude arousal heuristic against
    the wav2vec2 VAD arousal dimension (Convergent Signal Principle, §5).
  * map_features_to_vocabulary low-quality suppression — poor audio withholds
    the alarming (pressured/elevated/agitated/strained) labels.

All tests are pure (no audio synthesis): they construct feature/word dicts
directly, mirroring the style of tests/test_acoustic_baseline.py.

Run:
    python3 -m pytest tests/test_speech_rate_transcript.py -v
"""

import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from acoustic_engine import (
    estimate_syllables,
    compute_transcript_timing,
    refine_speech_rate_with_transcript,
    reconcile_arousal,
    map_features_to_vocabulary,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _words(n, dur_ms, gap_ms, text="cat", conf=0.9):
    """Build an AssemblyAI-style word list: n words, fixed duration + gap."""
    out, t = [], 0
    for _ in range(n):
        out.append({"text": text, "start": t, "end": t + dur_ms, "confidence": conf})
        t += dur_ms + gap_ms
    return out


def _vocab(speech_rate="slowed", artic_acoustic=2.0, confidence="high",
           prosody="normal", pauses="normal", arousal="normal",
           vocal_affect="normal"):
    """Minimal acoustic vocabulary dict as produced by map_features_to_vocabulary."""
    return {
        "speech_rate": speech_rate,
        "prosody": prosody,
        "pauses": pauses,
        "arousal": arousal,
        "vocal_affect": vocal_affect,
        "confidence": confidence,
        "clinical_pattern_type": "none_detected",
        "measured": {"articulation_rate_sps": artic_acoustic},
    }


def _feat(quality="good", **kw):
    """Acoustic features dict using the keys map_features_to_vocabulary reads."""
    base = dict(
        quality=quality, articulation_rate_sps=None, speech_rate_sps=None,
        f0_cv=None, pause_ratio=None, rms_mean=None, rms_cv=None,
        jitter_local=None, shimmer_local=None, hnr_db=None,
        voiced_fraction=0.7, praat_available=False,
    )
    base.update(kw)
    return base


# --------------------------------------------------------------------------- #
# estimate_syllables
# --------------------------------------------------------------------------- #

class TestEstimateSyllables(unittest.TestCase):
    def test_monosyllable(self):
        self.assertEqual(estimate_syllables("cat"), 1)

    def test_disyllable(self):
        self.assertEqual(estimate_syllables("hello"), 2)

    def test_silent_e_kept_for_le_ending(self):
        self.assertEqual(estimate_syllables("table"), 2)

    def test_silent_e_dropped(self):
        self.assertEqual(estimate_syllables("make"), 1)

    def test_empty_and_nonalpha_are_zero(self):
        self.assertEqual(estimate_syllables(""), 0)
        self.assertEqual(estimate_syllables("123"), 0)
        self.assertEqual(estimate_syllables("..."), 0)

    def test_floor_at_one_for_consonant_cluster_with_y(self):
        self.assertGreaterEqual(estimate_syllables("rhythm"), 1)


# --------------------------------------------------------------------------- #
# compute_transcript_timing
# --------------------------------------------------------------------------- #

class TestComputeTranscriptTiming(unittest.TestCase):
    def test_none_and_empty_return_none(self):
        self.assertIsNone(compute_transcript_timing(None))
        self.assertIsNone(compute_transcript_timing([]))

    def test_too_few_words_returns_none(self):
        self.assertIsNone(compute_transcript_timing(_words(5, 300, 100)))

    def test_valid_rate(self):
        # 10 one-syllable words, 300 ms each, 100 ms gaps.
        # articulation = 10 syll / (10 * 0.3 s) = 3.33 syll/s
        r = compute_transcript_timing(_words(10, 300, 100))
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r["articulation_rate_sps"], 3.333, delta=0.05)
        self.assertEqual(r["word_count"], 10)
        self.assertEqual(r["syllable_count"], 10)
        self.assertEqual(r["source"], "transcript")
        # speech_rate (over span, includes gaps) < articulation (speaking only)
        self.assertLess(r["speech_rate_sps"], r["articulation_rate_sps"])

    def test_implausible_fast_rate_returns_none(self):
        # 12 one-syllable words at 50 ms each → ~20 syll/s, beyond the guard.
        self.assertIsNone(compute_transcript_timing(_words(12, 50, 0)))

    def test_words_missing_timestamps_are_filtered(self):
        good = _words(8, 300, 100)
        bad = [{"text": "x"}, {"text": "y", "start": None, "end": 5}]
        # Only the 8 timed words count; result still valid.
        r = compute_transcript_timing(good + bad)
        self.assertIsNotNone(r)
        self.assertEqual(r["word_count"], 8)

    def test_below_min_after_filtering_returns_none(self):
        good = _words(6, 300, 100)
        bad = [{"text": "x"}] * 5  # untimed, dropped
        self.assertIsNone(compute_transcript_timing(good + bad))


# --------------------------------------------------------------------------- #
# refine_speech_rate_with_transcript
# --------------------------------------------------------------------------- #

class TestRefineSpeechRate(unittest.TestCase):
    def test_noop_when_timing_none(self):
        v = _vocab(speech_rate="slowed")
        out = refine_speech_rate_with_transcript(v, None)
        self.assertEqual(out["speech_rate"], "slowed")
        self.assertNotIn("speech_rate_source", out)

    def test_noop_when_no_articulation(self):
        v = _vocab(speech_rate="slowed")
        out = refine_speech_rate_with_transcript(v, {"articulation_rate_sps": None})
        self.assertEqual(out["speech_rate"], "slowed")

    def test_override_changes_label_and_marks_source(self):
        # Acoustic said 'slowed' (artic 2.0); transcript says 8.0 → 'pressured'.
        v = _vocab(speech_rate="slowed", artic_acoustic=2.0, confidence="high")
        out = refine_speech_rate_with_transcript(v, {"articulation_rate_sps": 8.0})
        self.assertEqual(out["speech_rate"], "pressured")
        self.assertEqual(out["speech_rate_source"], "transcript")
        self.assertEqual(out["speech_rate_cross_check"], "disagree")
        # Disagreement caps confidence at medium.
        self.assertEqual(out["confidence"], "medium")
        # Both estimates preserved; primary now reflects transcript.
        self.assertEqual(out["measured"]["articulation_rate_acoustic_sps"], 2.0)
        self.assertEqual(out["measured"]["articulation_rate_transcript_sps"], 8.0)
        self.assertEqual(out["measured"]["articulation_rate_sps"], 8.0)

    def test_agreement_preserves_confidence(self):
        # Both in the normal band → agree, confidence stays high.
        v = _vocab(speech_rate="normal", artic_acoustic=4.0, confidence="high")
        out = refine_speech_rate_with_transcript(v, {"articulation_rate_sps": 4.5})
        self.assertEqual(out["speech_rate"], "normal")
        self.assertEqual(out["speech_rate_cross_check"], "agree")
        self.assertEqual(out["confidence"], "high")

    def test_pattern_recomputed_from_corrected_label(self):
        # Only the speech_rate carries signal (all other features normal). A
        # stale 'depressive' label must be recomputed away once the rate is
        # corrected to 'pressured' (single signal → none_detected).
        v = _vocab(speech_rate="slowed", artic_acoustic=2.0)  # others normal
        v["clinical_pattern_type"] = "depressive"             # deliberately stale
        out = refine_speech_rate_with_transcript(v, {"articulation_rate_sps": 8.0})
        self.assertEqual(out["speech_rate"], "pressured")
        self.assertEqual(out["clinical_pattern_type"], "none_detected")

    def test_baseline_zscore_used_when_provided(self):
        # artic 6.0 vs baseline mean 4.5 sd 0.8 → z=1.875 → pressured.
        bl = {"status": "established",
              "articulation_rate_mean": 4.5, "articulation_rate_sd": 0.8}
        v = _vocab(speech_rate="normal", artic_acoustic=4.5)
        out = refine_speech_rate_with_transcript(v, {"articulation_rate_sps": 6.0},
                                                 baseline=bl)
        self.assertEqual(out["speech_rate"], "pressured")


# --------------------------------------------------------------------------- #
# reconcile_arousal
# --------------------------------------------------------------------------- #

class TestReconcileArousal(unittest.TestCase):
    def _affect(self, arousal, available=True):
        return {"model_available": available, "arousal": arousal}

    def test_convergent(self):
        r = reconcile_arousal({"arousal": "elevated"}, self._affect(0.8))
        self.assertEqual(r["status"], "convergent")
        self.assertEqual(r["vad_arousal_label"], "elevated")
        self.assertEqual(r["recommended"], "elevated")

    def test_agitated_maps_to_elevated_for_comparison(self):
        r = reconcile_arousal({"arousal": "agitated"}, self._affect(0.75))
        self.assertEqual(r["status"], "convergent")

    def test_divergent(self):
        r = reconcile_arousal({"arousal": "low"}, self._affect(0.8))
        self.assertEqual(r["status"], "divergent")
        # Recommended prefers the model label.
        self.assertEqual(r["recommended"], "elevated")

    def test_partial_when_model_unavailable(self):
        r = reconcile_arousal({"arousal": "elevated"}, self._affect(None, available=False))
        self.assertEqual(r["status"], "partial")
        self.assertIsNone(r["vad_arousal_label"])
        self.assertEqual(r["recommended"], "elevated")

    def test_partial_when_acoustic_missing(self):
        r = reconcile_arousal({"arousal": None}, self._affect(0.2))
        self.assertEqual(r["status"], "partial")
        self.assertEqual(r["vad_arousal_label"], "low")

    def test_insufficient(self):
        r = reconcile_arousal({"arousal": None}, None)
        self.assertEqual(r["status"], "insufficient")
        self.assertIsNone(r["recommended"])


# --------------------------------------------------------------------------- #
# Low-quality label suppression
# --------------------------------------------------------------------------- #

class TestLowQualitySuppression(unittest.TestCase):
    """Poor audio withholds the alarming labels; good audio keeps them."""

    def _alarming_features(self, quality):
        # Values chosen to produce pressured + elevated + agitated + strained.
        return _feat(
            quality=quality,
            articulation_rate_sps=8.0,      # > 6.5 → pressured
            f0_cv=0.35,                     # > 0.28 → elevated
            rms_mean=0.05, rms_cv=1.5,      # rms_cv > 1.2 → agitated
            jitter_local=0.02, shimmer_local=0.06, hnr_db=10.0,
            praat_available=True,           # 2 strain signals → strained
        )

    def test_good_quality_keeps_alarming_labels(self):
        r = map_features_to_vocabulary(self._alarming_features("good"))
        self.assertEqual(r["speech_rate"], "pressured")
        self.assertEqual(r["prosody"], "elevated")
        self.assertEqual(r["arousal"], "agitated")
        self.assertEqual(r["vocal_affect"], "strained")
        self.assertFalse(r["low_quality_suppressed"])

    def test_poor_quality_suppresses_alarming_labels(self):
        r = map_features_to_vocabulary(self._alarming_features("poor"))
        self.assertIsNone(r["speech_rate"])
        self.assertIsNone(r["prosody"])
        self.assertIsNone(r["arousal"])
        self.assertIsNone(r["vocal_affect"])
        self.assertTrue(r["low_quality_suppressed"])
        self.assertEqual(r["clinical_pattern_type"], "none_detected")

    def test_poor_quality_does_not_suppress_quiet_labels(self):
        # slowed / flat / low should pass through even on poor audio — they
        # bias toward caution, not false alarms.
        r = map_features_to_vocabulary(_feat(
            quality="poor", articulation_rate_sps=2.0, f0_cv=0.05,
            rms_mean=0.005,
        ))
        self.assertEqual(r["speech_rate"], "slowed")
        self.assertEqual(r["prosody"], "flat")
        self.assertFalse(r["low_quality_suppressed"])

    def test_low_quality_suppressed_key_always_present(self):
        for q in ("good", "fair", "poor"):
            r = map_features_to_vocabulary(_feat(quality=q))
            self.assertIn("low_quality_suppressed", r)


if __name__ == "__main__":
    unittest.main(verbosity=2)
