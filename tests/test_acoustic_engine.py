"""TDD spec for acoustic_engine.extract_acoustic_features.

These tests define the measurement contract for CognaSync's vocal-biomarker
extractor BEFORE the implementation exists. They run against fully synthetic
audio with known ground-truth properties (a pure tone has a known F0; a swept
tone has a known pitch range; a gapped clip has known pauses) so the assertions
test real DSP behaviour, not a mock.

Design notes that the implementation (task #3) must satisfy:
  * The extractor accepts a path to ANY ffmpeg-decodable audio file (.wav in
    these tests, .webm/opus in production) and decodes internally to 16 kHz mono.
  * Praat/parselmouth voice-quality features (jitter, shimmer, HNR, CPP) are
    OPTIONAL. When `import parselmouth` is unavailable (the aarch64 sandbox),
    those fields are None with feature_confidence == "low". When available
    (x86_64 production), they are floats. Both branches are asserted so the
    suite passes in both environments.
  * Pause/silence detection is energy-gated (robust to non-speech-like tones),
    not solely webrtcvad — a pure sine is not speech-like and webrtcvad alone
    would misclassify it.
  * speech_rate on pure tones is ill-defined; the contract only requires the
    field to be present and well-typed, not a specific value. Value-level
    speech-rate validation needs labelled human speech, which we do not have.

Run: python3 -m unittest tests.test_acoustic_engine
"""

import os
import sys
import subprocess
import tempfile
import unittest

import numpy as np
import soundfile as sf

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Import under test. Until acoustic_engine.py exists this raises ModuleNotFound
# and the whole suite is RED — which is the intended starting point for TDD.
from acoustic_engine import extract_acoustic_features  # noqa: E402

SR = 16000

# Every key the return contract must expose.
REQUIRED_KEYS = {
    "f0_mean_hz", "f0_sd_hz", "f0_range_hz", "f0_cv",
    "jitter_local", "shimmer_local", "hnr_db", "cpp_db",
    "rms_mean", "rms_cv",
    "speech_rate_sps", "articulation_rate_sps",
    "pause_count", "pause_total_s", "pause_ratio",
    "voiced_fraction", "duration_s", "snr_db",
    "quality", "feature_confidence", "extractor_version", "praat_available",
}

# parselmouth/Praat-only features that degrade gracefully when the lib is absent.
PRAAT_ONLY_KEYS = ("jitter_local", "shimmer_local", "hnr_db", "cpp_db")


def _write_wav(path, samples, sr=SR):
    sf.write(path, samples.astype(np.float32), sr, subtype="PCM_16")


def _tone(freq, dur, sr=SR, amp=0.6):
    t = np.arange(int(dur * sr)) / sr
    return amp * np.sin(2 * np.pi * freq * t)


def _sweep(f_start, f_end, dur, sr=SR, amp=0.6):
    n = int(dur * sr)
    inst_freq = np.linspace(f_start, f_end, n)
    phase = 2 * np.pi * np.cumsum(inst_freq) / sr
    return amp * np.sin(phase)


def _silence(dur, sr=SR):
    return np.zeros(int(dur * sr))


class AcousticEngineContractTest(unittest.TestCase):
    """Single extraction pass per fixture, cached on the class for speed."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cogna_acoustic_")

        fixtures = {
            "flat":       _tone(150.0, 3.0),
            "sweep":      _sweep(120.0, 220.0, 3.0),
            "continuous": _tone(150.0, 3.0),
            "gapped":     np.concatenate([
                _tone(150.0, 0.8), _silence(0.5),
                _tone(150.0, 0.8), _silence(0.5),
                _tone(150.0, 0.8),
            ]),
            "const_amp":  _tone(150.0, 3.0, amp=0.6),
        }

        # Amplitude-modulated tone: same carrier, 2 Hz envelope → higher RMS CV.
        t = np.arange(int(3.0 * SR)) / SR
        env = 0.5 + 0.5 * np.sin(2 * np.pi * 2.0 * t)
        fixtures["mod_amp"] = (0.6 * np.sin(2 * np.pi * 150.0 * t)) * env

        cls.paths = {}
        for name, samples in fixtures.items():
            p = os.path.join(cls.tmp, f"{name}.wav")
            _write_wav(p, samples)
            cls.paths[name] = p

        # Production container path: encode the flat tone to webm/opus so the
        # decode chain (ffmpeg → 16 kHz mono → DSP) is exercised on a real
        # container, not just a wav.
        cls.webm_path = os.path.join(cls.tmp, "flat.webm")
        enc = subprocess.run(
            ["ffmpeg", "-y", "-i", cls.paths["flat"],
             "-c:a", "libopus", "-b:a", "24k", cls.webm_path],
            capture_output=True,
        )
        cls.webm_ok = enc.returncode == 0 and os.path.getsize(cls.webm_path) > 0

        # Extract once per fixture.
        cls.res = {name: extract_acoustic_features(p) for name, p in cls.paths.items()}

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ---- contract / shape -------------------------------------------------

    def test_returns_all_contract_keys(self):
        r = self.res["flat"]
        self.assertIsInstance(r, dict)
        self.assertEqual(REQUIRED_KEYS - set(r), set(),
                         msg="extractor is missing required contract keys")

    def test_metadata_field_types(self):
        r = self.res["flat"]
        self.assertIsInstance(r["feature_confidence"], dict)
        self.assertIsInstance(r["praat_available"], bool)
        self.assertIsInstance(r["extractor_version"], str)
        self.assertIn(r["quality"], {"good", "fair", "poor"})

    def test_duration_recovered(self):
        self.assertAlmostEqual(self.res["flat"]["duration_s"], 3.0, delta=0.2)

    # ---- F0 (pitch) -------------------------------------------------------

    def test_flat_tone_f0_mean(self):
        self.assertAlmostEqual(self.res["flat"]["f0_mean_hz"], 150.0, delta=20.0)

    def test_flat_tone_is_low_variation(self):
        # A monotone has near-zero pitch SD relative to a swept tone.
        self.assertLess(self.res["flat"]["f0_sd_hz"], 15.0)

    def test_sweep_has_wider_pitch_range_than_flat(self):
        self.assertGreater(self.res["sweep"]["f0_range_hz"],
                           self.res["flat"]["f0_range_hz"])

    def test_sweep_has_higher_pitch_sd_than_flat(self):
        self.assertGreater(self.res["sweep"]["f0_sd_hz"],
                           self.res["flat"]["f0_sd_hz"])

    def test_sweep_f0_mean_in_band(self):
        # 120→220 Hz linear sweep → mean near the midpoint.
        self.assertTrue(140.0 <= self.res["sweep"]["f0_mean_hz"] <= 200.0)

    # ---- voicing & pauses -------------------------------------------------

    def test_continuous_tone_is_mostly_voiced(self):
        self.assertGreater(self.res["continuous"]["voiced_fraction"], 0.75)

    def test_gapped_has_more_pauses_than_continuous(self):
        self.assertGreaterEqual(self.res["gapped"]["pause_count"], 2)
        self.assertLessEqual(self.res["continuous"]["pause_count"], 1)

    def test_gapped_has_more_pause_time(self):
        self.assertGreater(self.res["gapped"]["pause_total_s"],
                           self.res["continuous"]["pause_total_s"] + 0.5)

    def test_gapped_has_lower_voiced_fraction(self):
        self.assertLess(self.res["gapped"]["voiced_fraction"],
                        self.res["continuous"]["voiced_fraction"])

    def test_pause_ratio_within_unit_interval(self):
        for name in ("continuous", "gapped"):
            pr = self.res[name]["pause_ratio"]
            self.assertGreaterEqual(pr, 0.0)
            self.assertLessEqual(pr, 1.0)

    # ---- energy variability ----------------------------------------------

    def test_modulated_amplitude_has_higher_rms_cv(self):
        self.assertGreater(self.res["mod_amp"]["rms_cv"],
                           self.res["const_amp"]["rms_cv"] + 0.1)

    def test_constant_amplitude_is_steady(self):
        self.assertLess(self.res["const_amp"]["rms_cv"], 0.2)

    # ---- speech-rate fields present (value not asserted on pure tones) -----

    def test_speech_rate_fields_present_and_typed(self):
        r = self.res["flat"]
        for key in ("speech_rate_sps", "articulation_rate_sps"):
            val = r[key]
            self.assertTrue(val is None or isinstance(val, (int, float)),
                            msg=f"{key} must be None or numeric")
            if isinstance(val, (int, float)):
                self.assertGreaterEqual(val, 0.0)

    # ---- parselmouth graceful degradation ---------------------------------

    def test_praat_features_match_availability(self):
        r = self.res["flat"]
        if r["praat_available"]:
            for k in PRAAT_ONLY_KEYS:
                self.assertIsInstance(r[k], float,
                                      msg=f"{k} should be a float when Praat is available")
        else:
            for k in PRAAT_ONLY_KEYS:
                self.assertIsNone(r[k],
                                  msg=f"{k} should be None when Praat is unavailable")
                self.assertEqual(r["feature_confidence"].get(k), "low",
                                 msg=f"{k} confidence should be 'low' when degraded")

    # ---- production container decode path ---------------------------------

    def test_webm_decode_recovers_f0(self):
        if not self.webm_ok:
            self.skipTest("ffmpeg libopus webm encode unavailable in this env")
        r = extract_acoustic_features(self.webm_path)
        self.assertAlmostEqual(r["f0_mean_hz"], 150.0, delta=25.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
