"""CognaSync vocal-biomarker extractor.

`extract_acoustic_features(path)` decodes ANY ffmpeg-readable audio file
(.wav in tests, .webm/opus in production) to 16 kHz mono and computes a fixed
contract of measured acoustic features from the waveform itself — not from a
transcript. The output feeds a deterministic interpretation layer (see
`map_features_to_vocabulary`) that produces provider-facing clinical language.

Design contract (asserted by tests/test_acoustic_engine.py):

  * Always-on features (librosa + scipy, available in every environment):
      F0 stats (pyin), RMS energy + CV, energy-gated pause detection,
      voiced fraction, duration, a coarse SNR estimate, and a syllable-nuclei
      speech-rate proxy.
  * Praat/parselmouth voice-quality features (jitter, shimmer, HNR, CPP) are
      OPTIONAL. When `import parselmouth` fails (the aarch64 dev sandbox) these
      four fields are None and their `feature_confidence` entry is "low". When
      parselmouth is present (x86_64 production gets the prebuilt wheel) they
      are floats. Both branches are exercised by the test suite so it is green
      in either environment.
  * Pure / deterministic: same bytes in -> same numbers out. No LLM, no network.

The extractor measures; it never interprets. Mapping measured numbers to the
controlled §24 vocabulary, and any clinical framing, happens downstream and is
provider-channel only.
"""

from __future__ import annotations

import os
import math
import subprocess
import tempfile

import numpy as np

# Always-available DSP stack (verified present in both sandbox and prod).
import librosa
import scipy.signal
from scipy.ndimage import uniform_filter1d

SR = 16000
EXTRACTOR_VERSION = "1.0"
_EPS = 1e-10

# parselmouth/Praat is optional. Probe once at import time.
try:  # pragma: no cover - environment dependent
    import parselmouth  # noqa: F401
    from parselmouth.praat import call as _praat_call

    _PRAAT_AVAILABLE = True
except Exception:  # ImportError on aarch64 sandbox; any failure degrades safely
    parselmouth = None
    _praat_call = None
    _PRAAT_AVAILABLE = False

PRAAT_ONLY_KEYS = ("jitter_local", "shimmer_local", "hnr_db", "cpp_db")

# Every always-on feature whose confidence tracks recording quality.
_LIBROSA_KEYS = (
    "f0_mean_hz", "f0_sd_hz", "f0_range_hz", "f0_cv",
    "rms_mean", "rms_cv",
    "speech_rate_sps", "articulation_rate_sps",
    "pause_count", "pause_total_s", "pause_ratio",
    "voiced_fraction", "duration_s", "snr_db",
)


# --------------------------------------------------------------------------- #
# Decode
# --------------------------------------------------------------------------- #

def _decode_to_mono16k(path: str) -> np.ndarray:
    """Decode any ffmpeg-readable container to a float32 mono 16 kHz array.

    Routing every input (wav, webm/opus, m4a, ...) through ffmpeg keeps the
    DSP path identical regardless of source container, which is what the
    production voice-memo flow (webm/opus from the browser MediaRecorder)
    requires.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    proc = subprocess.run(
        ["ffmpeg", "-v", "quiet", "-nostdin", "-i", path,
         "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        err = proc.stderr.decode("utf-8", "ignore")[-400:]
        raise RuntimeError(f"ffmpeg failed to decode {path!r}: {err}")

    y = np.frombuffer(proc.stdout, dtype=np.float32).copy()
    # Guard against pathological NaN/Inf from a corrupt decode.
    y = np.nan_to_num(y, nan=0.0, posinf=0.0, neginf=0.0)
    return y


# --------------------------------------------------------------------------- #
# Always-on feature blocks
# --------------------------------------------------------------------------- #

def _f0_stats(y: np.ndarray):
    """F0 mean/SD/range/CV and voiced fraction via probabilistic YIN.

    Range uses a 5th-95th percentile spread rather than raw min-max so a single
    octave-error frame from pyin cannot blow up the range. voiced_fraction is
    the share of frames pyin marked voiced.
    """
    f0, voiced_flag, _ = librosa.pyin(
        y, fmin=65, fmax=400, sr=SR,
        frame_length=2048, hop_length=512,
    )
    if voiced_flag is None or len(voiced_flag) == 0:
        return dict(f0_mean_hz=None, f0_sd_hz=None, f0_range_hz=None,
                    f0_cv=None, voiced_fraction=0.0)

    voiced_fraction = float(np.mean(voiced_flag))
    f0v = f0[~np.isnan(f0)]
    if f0v.size == 0:
        return dict(f0_mean_hz=None, f0_sd_hz=None, f0_range_hz=None,
                    f0_cv=None, voiced_fraction=voiced_fraction)

    mean = float(np.mean(f0v))
    sd = float(np.std(f0v))
    rng = float(np.percentile(f0v, 95) - np.percentile(f0v, 5))
    cv = float(sd / mean) if mean > _EPS else None
    return dict(f0_mean_hz=mean, f0_sd_hz=sd, f0_range_hz=rng,
                f0_cv=cv, voiced_fraction=voiced_fraction)


def _rms_stats(y: np.ndarray):
    """Mean RMS energy and its coefficient of variation (std/mean).

    CV is the amplitude-stability signal: a steady tone -> low CV, an
    amplitude-modulated or dynamically-spoken signal -> high CV.
    """
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    mean = float(np.mean(rms))
    cv = float(np.std(rms) / mean) if mean > _EPS else 0.0
    return dict(rms_mean=mean, rms_cv=cv)


def _energy_envelope(y: np.ndarray):
    """10 ms-hop RMS envelope used for pause timing and syllable nuclei."""
    hop = int(0.010 * SR)          # 10 ms -> fine time resolution for pauses
    flen = int(0.025 * SR)         # 25 ms analysis window
    env = librosa.feature.rms(y=y, frame_length=flen, hop_length=hop)[0]
    return env, hop / SR           # envelope, seconds-per-frame


def _pause_stats(env: np.ndarray, sec_per_frame: float, duration_s: float):
    """Energy-gated pause detection.

    A pure sine is not speech-like, so webrtcvad alone would misclassify it;
    energy gating is robust to that and is fully inspectable. Leading/trailing
    silence is trimmed so only *internal* pauses count, matching how a clinician
    would read a voice memo. A pause is a contiguous sub-threshold run >= 0.3 s.
    """
    if env.size == 0:
        return dict(pause_count=0, pause_total_s=0.0, pause_ratio=0.0)

    peak = float(np.percentile(env, 95))
    thr = max(peak * 0.15, 1e-4)
    is_sil = env < thr

    active = np.where(~is_sil)[0]
    if active.size == 0:
        return dict(pause_count=0, pause_total_s=0.0, pause_ratio=0.0)

    first, last = active[0], active[-1]
    interior = is_sil[first:last + 1]

    min_frames = max(1, int(round(0.3 / sec_per_frame)))
    pause_count = 0
    pause_frames = 0
    run = 0
    for flag in interior:
        if flag:
            run += 1
        else:
            if run >= min_frames:
                pause_count += 1
                pause_frames += run
            run = 0
    if run >= min_frames:                      # trailing run inside interior
        pause_count += 1
        pause_frames += run

    pause_total_s = float(pause_frames * sec_per_frame)
    ratio = pause_total_s / duration_s if duration_s > _EPS else 0.0
    pause_ratio = float(min(max(ratio, 0.0), 1.0))
    return dict(pause_count=int(pause_count),
                pause_total_s=pause_total_s,
                pause_ratio=pause_ratio)


def _speech_rate(env: np.ndarray, sec_per_frame: float,
                 duration_s: float, pause_total_s: float):
    """Syllable-nuclei proxy: peaks in the smoothed energy envelope.

    On pure tones this is ~0 (no amplitude peaks) — speech rate is genuinely
    ill-defined there, and the contract only requires the field to be present
    and non-negative, not a specific value. Value-level validation needs
    labelled human speech, which the project does not yet have.
    """
    if env.size == 0 or duration_s <= _EPS:
        return dict(speech_rate_sps=None, articulation_rate_sps=None)

    smoothed = uniform_filter1d(env, size=5)
    peak = float(np.percentile(env, 95))
    min_dist = max(1, int(round(0.15 / sec_per_frame)))   # <= ~7 syll/s
    peaks, _ = scipy.signal.find_peaks(
        smoothed, distance=min_dist, prominence=max(peak * 0.10, 1e-4),
    )
    nuclei = int(len(peaks))

    speech_rate = float(nuclei / duration_s)
    speech_time = duration_s - pause_total_s
    artic = float(nuclei / speech_time) if speech_time > _EPS else None
    return dict(speech_rate_sps=speech_rate, articulation_rate_sps=artic)


def _snr_estimate(env: np.ndarray):
    """Coarse SNR from the frame-energy distribution.

    Where the signal has genuine quiet frames they serve as a noise floor;
    a gapless uniform tone has no usable floor, so we report a conservative
    fixed value. This estimate gates per-feature confidence only — its exact
    value is not part of the measurement contract.
    """
    if env.size == 0:
        return 0.0
    noise = float(np.percentile(env, 5))
    sig = float(np.percentile(env, 95))
    if sig <= _EPS:
        return 0.0
    if noise <= _EPS:
        return 45.0
    return float(np.clip(20.0 * math.log10(sig / noise), 0.0, 60.0))


# --------------------------------------------------------------------------- #
# Optional Praat voice-quality block
# --------------------------------------------------------------------------- #

def _praat_features(y: np.ndarray):
    """jitter, shimmer, HNR, CPP via parselmouth — production only.

    Each metric is computed independently so a version-specific signature
    mismatch (notably CPPS) degrades only that one field to None rather than
    nuking the whole block. Jitter/shimmer/CPP are reverb- and noise-sensitive;
    F0 (computed elsewhere) is comparatively robust.
    """
    out = {k: None for k in PRAAT_ONLY_KEYS}
    if not _PRAAT_AVAILABLE:
        return out

    try:  # pragma: no cover - exercised only where parselmouth is installed
        snd = parselmouth.Sound(y.astype(np.float64), SR)
        point_process = _praat_call(
            snd, "To PointProcess (periodic, cc)", 65, 400)

        try:
            out["jitter_local"] = float(_praat_call(
                point_process, "Get jitter (local)",
                0, 0, 0.0001, 0.02, 1.3))
        except Exception:
            out["jitter_local"] = None

        try:
            out["shimmer_local"] = float(_praat_call(
                [snd, point_process], "Get shimmer (local)",
                0, 0, 0.0001, 0.02, 1.3, 1.6))
        except Exception:
            out["shimmer_local"] = None

        try:
            harmonicity = _praat_call(
                snd, "To Harmonicity (cc)", 0.01, 65, 0.1, 1.0)
            out["hnr_db"] = float(_praat_call(harmonicity, "Get mean", 0, 0))
        except Exception:
            out["hnr_db"] = None

        try:
            power_cepstrogram = _praat_call(
                snd, "To PowerCepstrogram", 60, 0.002, 5000, 50)
            out["cpp_db"] = float(_praat_call(
                power_cepstrogram, "Get CPPS", "yes", 0.01, 0.001,
                60, 330, 0.05, "Parabolic", 0.001, 0, "Straight", "Robust"))
        except Exception:
            out["cpp_db"] = None
    except Exception:
        # Any failure constructing the Sound/PointProcess -> all None.
        out = {k: None for k in PRAAT_ONLY_KEYS}
    return out


# --------------------------------------------------------------------------- #
# Quality / confidence gating
# --------------------------------------------------------------------------- #

def _quality_label(snr_db: float, voiced_fraction: float) -> str:
    if snr_db >= 20.0 and voiced_fraction >= 0.40:
        return "good"
    if snr_db >= 10.0 or voiced_fraction >= 0.30:
        return "fair"
    return "poor"


def _confidence_map(quality: str, praat_available: bool,
                    praat_values: dict) -> dict:
    base = {"good": "high", "fair": "medium", "poor": "low"}[quality]
    conf = {k: base for k in _LIBROSA_KEYS}
    for k in PRAAT_ONLY_KEYS:
        if not praat_available or praat_values.get(k) is None:
            conf[k] = "low"
        else:
            conf[k] = base
    return conf


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# Interpretation thresholds (research-calibrated for adult conversational speech)
# --------------------------------------------------------------------------- #

# Articulation rate (syllables/second, excludes pause time)
_ARTIC_SLOWED   = 3.0   # below → slowed
_ARTIC_PRESSURED = 6.5  # above → pressured

# Pause ratio (fraction of total recording in silence ≥ 0.3 s)
_PAUSE_INCREASED = 0.40  # above → increased
_PAUSE_DECREASED = 0.10  # below → decreased

# Pitch variation (coefficient of variation of F0)
_F0_CV_FLAT     = 0.10   # below → flat prosody
_F0_CV_ELEVATED = 0.28   # above → elevated prosody

# Voice quality — Praat metrics
# Clinical literature: jitter > 1% and shimmer > 5% are pathological thresholds.
# Reference: Nardelli et al. / MDVP norms. Prior values (2%, 6%) were too permissive.
_JITTER_STRAIN   = 0.010  # > 1.0 % local jitter → strain signal
_SHIMMER_STRAIN  = 0.050  # > 5.0 % local shimmer → strain signal
_HNR_LOW         = 15.0   # < 15 dB → reduced harmonic quality

# Amplitude variability
_RMS_CV_AGITATED = 1.20   # high amplitude variance → agitated


def _acoustic_pattern(speech_rate, prosody, pauses, arousal, vocal_affect) -> str | None:
    """Map label cluster to §24 clinical_pattern_type. Conservative — requires ≥2 signals."""
    signals = {
        "depressive":      (speech_rate == "slowed") + (prosody == "flat") +
                           (pauses == "increased") + (arousal == "low") +
                           (vocal_affect == "flat"),
        "anxiety_stress":  (arousal in ("elevated", "agitated")) +
                           (pauses == "decreased") + (vocal_affect == "strained"),
        "mania_hypomania": (speech_rate == "pressured") + (prosody == "elevated") +
                           (pauses == "decreased") + (arousal == "elevated"),
    }
    best, best_n = max(signals.items(), key=lambda x: x[1])
    if best_n == 0:
        return "none_detected"
    sorted_vals = sorted(signals.values(), reverse=True)
    # Mixed: two patterns both ≥ 2 and within 1 of each other
    if len(sorted_vals) >= 2 and sorted_vals[0] >= 2 and sorted_vals[1] >= 2 \
            and sorted_vals[0] - sorted_vals[1] <= 1:
        return "mixed"
    return best if best_n >= 2 else "none_detected"


def _severity_note(features: dict, speech_rate, pauses, prosody, vocal_affect,
                   praat_available: bool) -> str | None:
    """One factual sentence on the most notable acoustic findings (§24 severity_note)."""
    artic    = features.get("articulation_rate_sps")
    p_ratio  = features.get("pause_ratio")
    f0_cv    = features.get("f0_cv")
    hnr      = features.get("hnr_db")
    dur      = features.get("duration_s", 0)
    parts: list[str] = []

    if speech_rate == "slowed" and artic is not None:
        parts.append(f"articulation rate {artic:.1f} sps (below normal range)")
    elif speech_rate == "pressured" and artic is not None:
        parts.append(f"articulation rate {artic:.1f} sps (above normal range)")

    if pauses == "increased" and p_ratio is not None:
        parts.append(f"pause ratio {p_ratio:.0%} of recording duration")

    if prosody == "flat" and f0_cv is not None:
        parts.append(f"pitch variation low (CV {f0_cv:.2f})")

    if praat_available and hnr is not None and hnr < _HNR_LOW:
        parts.append(f"HNR {hnr:.1f} dB (reduced harmonic quality)")

    if not parts:
        return None
    return "Acoustic measurements: " + "; ".join(parts) + f". Recording {dur:.0f} s."


def map_features_to_vocabulary(features: dict,
                                baseline: dict | None = None,
                                capture_channel: str | None = None) -> dict:
    """Map measured acoustic features to the §24 controlled vocabulary.

    The output mirrors the transcript_engine speech_features schema so that
    downstream code (store_session_features, generate_brief_from_sessions)
    can treat acoustic and transcript-derived labels uniformly.

    Adds a 'measured' sub-dict with the raw numeric values and a
    'clinical_pattern_type' derived from the label cluster.

    When `baseline` is provided and its status is 'established' or 'stale',
    speech_rate, prosody, and pauses are classified using patient-relative
    z-score thresholds (±1.5 SD) instead of the module-level absolute
    constants. Falls back to absolute constants when the baseline field is
    missing, its SD is zero, or the measured value is None.

    This function maps; it never interprets. Clinical meaning is the
    provider's job, not the AI's (CLAUDE.md §24).
    """
    quality       = features.get("quality", "poor")
    praat_avail   = features.get("praat_available", False)
    base_conf     = {"good": "high", "fair": "medium", "poor": "low"}[quality]

    # Whether the baseline path was used for at least one feature.
    baseline_used = False

    # Determine whether baseline is usable at all.
    _bl_active = (
        baseline is not None
        and baseline.get("status") in ("established", "stale")
    )

    # ── Speech rate ──────────────────────────────────────────────────────────
    artic = features.get("articulation_rate_sps")
    if artic is None:
        speech_rate = None
    elif (
        _bl_active
        and baseline.get("articulation_rate_mean") is not None
        and baseline.get("articulation_rate_sd") is not None
        and baseline["articulation_rate_sd"] > 0
    ):
        z = round((artic - baseline["articulation_rate_mean"]) / baseline["articulation_rate_sd"], 6)
        baseline_used = True
        if z <= -1.5:
            speech_rate = "slowed"
        elif z >= 1.5:
            speech_rate = "pressured"
        else:
            speech_rate = "normal"
    elif artic < _ARTIC_SLOWED:
        speech_rate = "slowed"
    elif artic > _ARTIC_PRESSURED:
        speech_rate = "pressured"
    else:
        speech_rate = "normal"

    # ── Pauses ───────────────────────────────────────────────────────────────
    p_ratio = features.get("pause_ratio")
    if p_ratio is None:
        pauses = None
    elif (
        _bl_active
        and baseline.get("pause_ratio_mean") is not None
        and baseline.get("pause_ratio_sd") is not None
        and baseline["pause_ratio_sd"] > 0
    ):
        z = round((p_ratio - baseline["pause_ratio_mean"]) / baseline["pause_ratio_sd"], 6)
        baseline_used = True
        if z >= 1.5:
            pauses = "increased"
        elif z <= -1.5:
            pauses = "decreased"
        else:
            pauses = "normal"
    elif p_ratio > _PAUSE_INCREASED:
        pauses = "increased"
    elif p_ratio < _PAUSE_DECREASED:
        pauses = "decreased"
    else:
        pauses = "normal"

    # ── Prosody (F0 variation) ────────────────────────────────────────────────
    f0_cv = features.get("f0_cv")
    if f0_cv is None:
        prosody = None
    elif (
        _bl_active
        and baseline.get("f0_cv_mean") is not None
        and baseline.get("f0_cv_sd") is not None
        and baseline["f0_cv_sd"] > 0
    ):
        z = round((f0_cv - baseline["f0_cv_mean"]) / baseline["f0_cv_sd"], 6)
        baseline_used = True
        if z <= -1.5:
            prosody = "flat"
        elif z >= 1.5:
            prosody = "elevated"
        else:
            prosody = "normal"
    elif f0_cv < _F0_CV_FLAT:
        prosody = "flat"
    elif f0_cv > _F0_CV_ELEVATED:
        prosody = "elevated"
    else:
        prosody = "normal"

    # ── Vocal affect ─────────────────────────────────────────────────────────
    jitter  = features.get("jitter_local")
    shimmer = features.get("shimmer_local")
    hnr     = features.get("hnr_db")

    if praat_avail and (jitter is not None or shimmer is not None):
        strain = sum([
            jitter  is not None and jitter  > _JITTER_STRAIN,
            shimmer is not None and shimmer > _SHIMMER_STRAIN,
            hnr     is not None and hnr     < _HNR_LOW,
        ])
        if strain >= 2:
            vocal_affect = "strained"
        elif f0_cv is not None and f0_cv < _F0_CV_FLAT:
            vocal_affect = "flat"
        else:
            vocal_affect = "normal"
    elif f0_cv is not None:
        vocal_affect = "flat" if f0_cv < _F0_CV_FLAT else "normal"
    else:
        vocal_affect = None

    # ── Arousal (amplitude) ──────────────────────────────────────────────────
    rms_mean = features.get("rms_mean") or 0.0
    rms_cv   = features.get("rms_cv")  or 0.0
    if features.get("rms_mean") is None:
        arousal = None
    elif rms_cv > _RMS_CV_AGITATED:
        arousal = "agitated"
    elif rms_mean < 0.01 and (f0_cv is None or f0_cv < _F0_CV_FLAT):
        arousal = "low"
    elif rms_mean > 0.08 or (rms_cv > 0.8 and rms_mean > 0.04):
        arousal = "elevated"
    else:
        arousal = "normal"

    # ── Low-quality suppression (asymmetric, accuracy + safety) ───────────────
    # Poor-quality audio (low SNR, dropouts, clipping) biases the DSP toward
    # spurious *abnormal* readings. False "pressured / elevated / agitated /
    # strained" labels are the most clinically costly error — they can trip
    # convergent-signal flags downstream (transcript_engine reads these labels
    # without always re-checking confidence). When quality is poor we withhold
    # the alarming labels rather than assert them. The "quiet" labels
    # (slowed / flat / low / increased pauses) are not suppressed: they bias
    # toward caution, and the measured numbers still pass through either way.
    low_quality_suppressed = False
    if quality == "poor":
        if speech_rate == "pressured":
            speech_rate = None
            low_quality_suppressed = True
        if prosody == "elevated":
            prosody = None
            low_quality_suppressed = True
        if arousal in ("elevated", "agitated"):
            arousal = None
            low_quality_suppressed = True
        if vocal_affect == "strained":
            vocal_affect = None
            low_quality_suppressed = True

    # speech_coherence cannot be measured from waveform alone — left null.
    # transcript_engine populates this from semantic content.
    speech_coherence = None

    pattern  = _acoustic_pattern(speech_rate, prosody, pauses, arousal, vocal_affect)
    sev_note = _severity_note(features, speech_rate, pauses, prosody, vocal_affect,
                              praat_avail)
    if low_quality_suppressed:
        sev_note = ("Recording quality low — elevated/agitated/strained acoustic "
                    "labels withheld to avoid false positives. Measured values are "
                    "shown for provider review.")

    # Confidence boost: when at least one feature used patient-relative thresholds
    # we have a personal reference, so "medium" grades up to "high".
    # "poor" stays "low"; "good" (already "high") is unchanged.
    if baseline_used and base_conf == "medium":
        base_conf = "high"

    return {
        # §24 vocabulary labels (shared schema with transcript_engine)
        "speech_rate":           speech_rate,
        "prosody":               prosody,
        "pauses":                pauses,
        "speech_coherence":      speech_coherence,
        "arousal":               arousal,
        "vocal_affect":          vocal_affect,
        "severity_note":         sev_note,
        "confidence":            base_conf,
        "clinical_pattern_type": pattern,
        "baseline_deviation":    None,   # populated by caller if prior sessions available
        "baseline_used":         baseline_used,
        # Measured values — provider-facing only, never patient-facing
        "measured": {
            "articulation_rate_sps": artic,
            "speech_rate_sps":       features.get("speech_rate_sps"),
            "pause_ratio":           p_ratio,
            "pause_count":           features.get("pause_count"),
            "pause_total_s":         features.get("pause_total_s"),
            "f0_mean_hz":            features.get("f0_mean_hz"),
            "f0_sd_hz":              features.get("f0_sd_hz"),
            "f0_range_hz":           features.get("f0_range_hz"),
            "f0_cv":                 f0_cv,
            "rms_mean":              rms_mean,
            "rms_cv":                rms_cv,
            "voiced_fraction":       features.get("voiced_fraction"),
            "jitter_local":          jitter,
            "shimmer_local":         shimmer,
            "hnr_db":                hnr,
            "cpp_db":                features.get("cpp_db"),
            "duration_s":            features.get("duration_s"),
            "snr_db":                features.get("snr_db"),
        },
        "recording_quality":  quality,
        "low_quality_suppressed": low_quality_suppressed,
        "praat_available":    praat_avail,
        "extractor_version":  features.get("extractor_version", EXTRACTOR_VERSION),
        # Channel provenance — used to gate cross-channel baseline comparisons.
        # "phone" | "browser" | "clinic_mic" | "unknown" | None (not provided).
        "capture_channel":    capture_channel,
    }


def _classify_articulation(artic, baseline: dict | None = None) -> str | None:
    """Slowed / normal / pressured classification for an articulation rate.

    Uses the patient baseline z-score (±1.5 SD) when an established/stale
    baseline with a usable SD is supplied, else the module absolute constants.
    Mirrors the inline logic in map_features_to_vocabulary so the transcript
    refinement path classifies a rate exactly the way the acoustic path does.
    """
    if artic is None:
        return None
    bl_active = (
        baseline is not None
        and baseline.get("status") in ("established", "stale")
        and baseline.get("articulation_rate_mean") is not None
        and baseline.get("articulation_rate_sd") is not None
        and baseline.get("articulation_rate_sd", 0) > 0
    )
    if bl_active:
        z = round((artic - baseline["articulation_rate_mean"]) / baseline["articulation_rate_sd"], 6)
        if z <= -1.5:
            return "slowed"
        if z >= 1.5:
            return "pressured"
        return "normal"
    if artic < _ARTIC_SLOWED:
        return "slowed"
    if artic > _ARTIC_PRESSURED:
        return "pressured"
    return "normal"


def estimate_syllables(word: str) -> int:
    """Deterministic English syllable estimate for one token.

    Counts vowel-letter groups, drops a single silent terminal 'e' (but not
    'le' / 'ie' / 'ee' endings), and floors at 1 for any alphabetic token.
    Non-alphabetic tokens count 0. This is a rate heuristic, not a linguistic
    analyzer — it only needs to be stable and approximately right in aggregate.
    """
    import re
    w = re.sub(r"[^a-z]", "", (word or "").lower())
    if not w:
        return 0
    count = len(re.findall(r"[aeiouy]+", w))
    if count > 1 and w.endswith("e") and not w.endswith(("le", "ie", "ee")):
        count -= 1
    return max(1, count)


def infer_capture_channel(filename: str | None,
                           session_type: str | None = None) -> str:
    """Infer the recording device / channel from filename extension and session context.

    DSP features like jitter, shimmer, HNR, and CPP are sensitive to recording
    conditions — a patient switching from a clinic microphone to a phone produces
    apparent "deterioration" that is actually device drift.  Storing the inferred
    channel alongside every extraction makes it possible to build per-channel
    baselines and flag cross-channel baseline comparisons in provider output.

    Returns one of:
        "phone"      — mobile voice memo (.m4a, .aac, .mp4, .3gp, .amr, .caf)
        "browser"    — web/browser recording (.webm, .ogg)
        "clinic_mic" — assumed for high-quality formats in a clinical session context
                       (.wav, .flac, .aiff, .aif)
        "unknown"    — fallback when no reliable signal is available

    This is heuristic — correct in the common case, not guaranteed.  The caller
    should store it and expose it in the vocabulary dict so providers can see when
    a comparison crosses channel types.
    """
    PHONE_EXTS   = {".m4a", ".aac", ".mp4", ".3gp", ".amr", ".caf"}
    BROWSER_EXTS = {".webm", ".ogg"}
    MIC_EXTS     = {".wav", ".flac", ".aiff", ".aif"}

    ext = ""
    if filename:
        import os as _os
        ext = _os.path.splitext(filename)[1].lower()

    if ext in PHONE_EXTS:
        return "phone"
    if ext in BROWSER_EXTS:
        return "browser"
    if ext in MIC_EXTS:
        # WAV from a clinical session → more likely a clinic mic than a phone export.
        # WAV from a voice-note flow (SMS/mobile) → probably a phone conversion.
        if session_type and session_type not in ("voice_note",):
            return "clinic_mic"
        return "unknown"   # WAV in voice_note context is ambiguous
    return "unknown"


def compute_transcript_timing(words: list | None, min_words: int = 8) -> dict | None:
    """Derive speech-rate measures from ASR word timestamps.

    `words` is the AssemblyAI word list — each item a dict with 'text' and
    integer 'start'/'end' in milliseconds (optionally 'confidence'). Returns
    None when there are too few timed words, or when the derived rate is
    physiologically implausible (an ASR timing artifact).

    articulation_rate_sps: syllables per second of *speaking* time (sum of
        per-word durations — naturally excludes inter-word pauses).
    speech_rate_sps: syllables per second over the full span (first word start
        → last word end — includes pauses).

    This is the reliable replacement for the energy-envelope syllable-nuclei
    proxy in _speech_rate(), built from data AssemblyAI already returns.
    """
    if not words:
        return None
    timed = [
        w for w in words
        if isinstance(w, dict)
        and w.get("start") is not None and w.get("end") is not None
        and (w.get("text") or "").strip()
    ]
    if len(timed) < min_words:
        return None

    syllables = sum(estimate_syllables(w["text"]) for w in timed)
    if syllables <= 0:
        return None

    speak_ms = sum(max(0, int(w["end"]) - int(w["start"])) for w in timed)
    span_ms = max(int(timed[-1]["end"]) - int(timed[0]["start"]), 0)
    speak_s = speak_ms / 1000.0
    span_s = span_ms / 1000.0

    artic = (syllables / speak_s) if speak_s > 0 else None
    rate = (syllables / span_s) if span_s > 0 else None

    # Plausibility guard: human articulation is ~2–9 syll/s. Outside ~1.5–10
    # the timestamps are unreliable, so treat as missing and keep the acoustic
    # fallback rather than emit a bogus "pressured"/"slowed" label.
    if artic is None or not (1.5 <= artic <= 10.0):
        return None

    confs = [w.get("confidence") for w in timed
             if isinstance(w.get("confidence"), (int, float))]
    mean_conf = (sum(confs) / len(confs)) if confs else None

    return {
        "articulation_rate_sps": round(artic, 3),
        "speech_rate_sps": round(rate, 3) if rate is not None else None,
        "syllable_count": int(syllables),
        "word_count": len(timed),
        "speaking_time_s": round(speak_s, 3),
        "span_s": round(span_s, 3),
        "mean_word_confidence": round(mean_conf, 3) if mean_conf is not None else None,
        "source": "transcript",
    }


def refine_speech_rate_with_transcript(vocab: dict,
                                       transcript_timing: dict | None,
                                       baseline: dict | None = None) -> dict:
    """Override the envelope-peak speech_rate label with the transcript rate.

    The energy-envelope syllable proxy (_speech_rate) is the least reliable
    measured feature, yet it solely drives the speech_rate label and therefore
    the depressive/mania pattern split. ASR word timestamps yield a far more
    reliable articulation rate. Mutates `vocab` in place:

      * reclassifies speech_rate from the transcript articulation rate,
      * preserves the acoustic proxy under measured.articulation_rate_acoustic_sps,
      * records speech_rate_source and a cross-check flag,
      * recomputes clinical_pattern_type from the corrected label,
      * caps confidence at 'medium' when the two estimates disagree on direction
        (independent methods contradicting each other is itself low-confidence).

    No-op when transcript_timing lacks a usable articulation rate, so the
    acoustic proxy remains the fallback.
    """
    if not transcript_timing:
        return vocab
    artic_t = transcript_timing.get("articulation_rate_sps")
    if artic_t is None:
        return vocab

    measured = vocab.get("measured") or {}
    artic_acoustic = measured.get("articulation_rate_sps")

    new_label = _classify_articulation(artic_t, baseline)

    cross_check = None
    if artic_acoustic is not None:
        cross_check = (
            "agree"
            if _classify_articulation(artic_acoustic, baseline) == new_label
            else "disagree"
        )

    vocab["speech_rate"] = new_label
    vocab["speech_rate_source"] = "transcript"
    vocab["speech_rate_cross_check"] = cross_check
    measured["articulation_rate_transcript_sps"] = artic_t
    measured["articulation_rate_acoustic_sps"] = artic_acoustic
    measured["articulation_rate_sps"] = artic_t  # primary now reflects the better estimate
    vocab["measured"] = measured

    vocab["clinical_pattern_type"] = _acoustic_pattern(
        new_label, vocab.get("prosody"), vocab.get("pauses"),
        vocab.get("arousal"), vocab.get("vocal_affect"),
    )

    if cross_check == "disagree" and vocab.get("confidence") == "high":
        vocab["confidence"] = "medium"

    return vocab


def _vad_arousal_label(v) -> str | None:
    """Map a VAD arousal value in [0,1] to the acoustic arousal vocabulary."""
    if v is None:
        return None
    if v < 0.35:
        return "low"
    if v > 0.65:
        return "elevated"
    return "normal"


_AROUSAL_RECONCILE_NOTES = {
    "convergent": ("Amplitude-based and model-based arousal agree — convergent "
                   "signal raises confidence in the arousal reading."),
    "divergent": ("Amplitude-based and model-based arousal disagree — the "
                  "divergence is itself worth noting; the model dimension is "
                  "the less gain-confounded of the two."),
    "partial": "Only one arousal estimate was available this session.",
    "insufficient": "Neither arousal estimate was available this session.",
}


def reconcile_arousal(acoustic_vocab: dict | None, affect: dict | None) -> dict:
    """Reconcile the two independent arousal estimates into one record.

    Arousal is computed twice from the same audio: an RMS-amplitude heuristic
    (acoustic_vocab['arousal'], heavily confounded by recording gain / mic
    distance) and the wav2vec2 VAD arousal dimension (affect['arousal'], better
    grounded but model-dependent). Per the Convergent Signal Principle
    (CLAUDE.md §5), agreement raises confidence and disagreement is itself
    signal — so this surfaces the relationship as a first-class field instead of
    leaving the two estimates in separate silos. 'recommended' prefers the model
    label, the less gain-confounded of the two.
    """
    ac = (acoustic_vocab or {}).get("arousal")
    affect = affect or {}
    vad = affect.get("arousal") if affect.get("model_available") else None
    vad_label = _vad_arousal_label(vad)

    if ac is None and vad_label is None:
        status = "insufficient"
    elif ac is None or vad_label is None:
        status = "partial"
    else:
        ac_norm = "elevated" if ac in ("elevated", "agitated") else ac
        status = "convergent" if ac_norm == vad_label else "divergent"

    return {
        "acoustic_arousal": ac,
        "vad_arousal_value": vad,
        "vad_arousal_label": vad_label,
        "status": status,
        "recommended": vad_label if vad_label is not None else ac,
        "note": _AROUSAL_RECONCILE_NOTES.get(status),
    }


def aggregate_acoustic_sessions(session_acoustic_list: list) -> dict:
    """Aggregate per-session acoustic vocabulary mappings for trend analysis.

    Args:
        session_acoustic_list: List of dicts from map_features_to_vocabulary(),
            each optionally carrying a 'session_date' key added by the caller.

    Returns a summary dict suitable for use as voice_memo_summary in
    generate_brief_from_sessions(). Includes per-session measured_series
    for longitudinal display, label distributions, and simple averages.
    """
    if not session_acoustic_list:
        return {"session_count": 0}

    from collections import Counter

    label_keys   = ("speech_rate", "prosody", "pauses", "arousal",
                    "vocal_affect", "clinical_pattern_type")
    distributions: dict[str, Counter] = {k: Counter() for k in label_keys}

    rms_means, pause_ratios, f0_means, artic_rates, hnr_vals = [], [], [], [], []
    speech_concern = 0
    measured_series: list[dict] = []

    for s in session_acoustic_list:
        for k in label_keys:
            val = s.get(k)
            if val:
                distributions[k][val] += 1

        m = s.get("measured") or {}
        if m.get("rms_mean") is not None:
            rms_means.append(m["rms_mean"])
        if m.get("pause_ratio") is not None:
            pause_ratios.append(m["pause_ratio"])
        if m.get("f0_mean_hz") is not None:
            f0_means.append(m["f0_mean_hz"])
        if m.get("articulation_rate_sps") is not None:
            artic_rates.append(m["articulation_rate_sps"])
        if m.get("hnr_db") is not None:
            hnr_vals.append(m["hnr_db"])

        if any([
            s.get("speech_rate") in ("slowed", "pressured"),
            s.get("prosody") == "flat",
            s.get("pauses") == "increased",
            s.get("arousal") in ("low", "elevated", "agitated"),
            s.get("vocal_affect") in ("flat", "strained"),
        ]):
            speech_concern += 1

        measured_series.append({
            "session_date":          s.get("session_date"),
            "articulation_rate_sps": m.get("articulation_rate_sps"),
            "pause_ratio":           m.get("pause_ratio"),
            "f0_cv":                 m.get("f0_cv"),
            "hnr_db":                m.get("hnr_db"),
            "speech_rate":           s.get("speech_rate"),
            "prosody":               s.get("prosody"),
            "arousal":               s.get("arousal"),
            "vocal_affect":          s.get("vocal_affect"),
        })

    def _avg(lst: list) -> float | None:
        return round(sum(lst) / len(lst), 3) if lst else None

    # Speech rate trend: majority label if it appears in > 50 % of sessions
    sr_dist = distributions["speech_rate"]
    n = len(session_acoustic_list)
    if sr_dist:
        top_sr, top_sr_n = sr_dist.most_common(1)[0]
        speech_rate_trend = top_sr if top_sr_n > n / 2 else "variable"
    else:
        speech_rate_trend = None

    dominant_pattern = None
    if distributions["clinical_pattern_type"]:
        dominant_pattern = distributions["clinical_pattern_type"].most_common(1)[0][0]

    return {
        "session_count":              n,
        "speech_rate_distribution":   dict(distributions["speech_rate"]),
        "prosody_distribution":        dict(distributions["prosody"]),
        "pause_distribution":          dict(distributions["pauses"]),
        "arousal_distribution":        dict(distributions["arousal"]),
        "vocal_affect_distribution":   dict(distributions["vocal_affect"]),
        "speech_rate_trend":           speech_rate_trend,
        "vocal_energy_avg":            _avg(rms_means),
        "pause_rate_avg":              _avg(pause_ratios),
        "f0_mean_avg":                 _avg(f0_means),
        "articulation_rate_avg":       _avg(artic_rates),
        "hnr_avg":                     _avg(hnr_vals),
        "dominant_pattern":            dominant_pattern,
        "speech_concern_sessions":     speech_concern,
        "measured_series":             measured_series,
    }


def extract_acoustic_features(path: str) -> dict:
    """Extract the full measured-feature contract from an audio file.

    Returns a flat dict of measured numbers plus metadata
    (`quality`, `feature_confidence`, `extractor_version`, `praat_available`).
    Praat-only fields are None when parselmouth is unavailable. The function is
    pure and deterministic; it performs no interpretation.
    """
    y = _decode_to_mono16k(path)
    duration_s = float(len(y) / SR)

    f0 = _f0_stats(y)
    rms = _rms_stats(y)
    env, sec_per_frame = _energy_envelope(y)
    pauses = _pause_stats(env, sec_per_frame, duration_s)
    rate = _speech_rate(env, sec_per_frame, duration_s,
                        pauses["pause_total_s"])
    snr_db = _snr_estimate(env)
    praat = _praat_features(y)

    voiced_fraction = f0["voiced_fraction"]
    quality = _quality_label(snr_db, voiced_fraction)
    confidence = _confidence_map(quality, _PRAAT_AVAILABLE, praat)

    result = {
        # F0 / pitch
        "f0_mean_hz": f0["f0_mean_hz"],
        "f0_sd_hz": f0["f0_sd_hz"],
        "f0_range_hz": f0["f0_range_hz"],
        "f0_cv": f0["f0_cv"],
        # Praat voice quality (optional)
        "jitter_local": praat["jitter_local"],
        "shimmer_local": praat["shimmer_local"],
        "hnr_db": praat["hnr_db"],
        "cpp_db": praat["cpp_db"],
        # Energy
        "rms_mean": rms["rms_mean"],
        "rms_cv": rms["rms_cv"],
        # Timing
        "speech_rate_sps": rate["speech_rate_sps"],
        "articulation_rate_sps": rate["articulation_rate_sps"],
        "pause_count": pauses["pause_count"],
        "pause_total_s": pauses["pause_total_s"],
        "pause_ratio": pauses["pause_ratio"],
        # Voicing / global
        "voiced_fraction": voiced_fraction,
        "duration_s": duration_s,
        "snr_db": snr_db,
        # Metadata
        "quality": quality,
        "feature_confidence": confidence,
        "extractor_version": EXTRACTOR_VERSION,
        "praat_available": bool(_PRAAT_AVAILABLE),
    }
    return result


# ── Subprocess CLI entry point ───────────────────────────────────────────────
# Acoustic extraction peaks at ~400 MB RSS (librosa pyin probability matrices).
# Running it inside the web worker risks an OOM kill that takes the whole
# worker down mid-pipeline, stranding voice_notes rows at 'processing'.
# audio_engine therefore invokes this module as a short-lived subprocess:
#     python acoustic_engine.py <audio_path>
# stdout: one JSON object {"raw": {...}, "vocabulary": {...}}
# Any failure (including an OOM kill of this child) leaves the parent worker
# alive to continue with transcript-only analysis.

def _json_safe(obj):
    """Recursively convert numpy scalars/arrays to plain Python types."""
    import numpy as _np
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, _np.generic):
        return obj.item()
    if isinstance(obj, _np.ndarray):
        return obj.tolist()
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def _main(argv) -> int:
    """Subprocess CLI: extract + map one audio file, print one JSON object.

    Honors the stdout contract documented above:
        {"raw": {...}, "vocabulary": {...}}
    On any failure prints {"error": "..."} and returns a non-zero code so the
    parent worker can fall back to transcript-only analysis without dying.
    """
    import json
    import sys

    if len(argv) < 2:
        sys.stdout.write(json.dumps(
            {"error": "usage: python acoustic_engine.py <audio_path>"}))
        return 2

    path = argv[1]
    try:
        raw = extract_acoustic_features(path)
        vocab = map_features_to_vocabulary(raw)
        sys.stdout.write(json.dumps(_json_safe({"raw": raw, "vocabulary": vocab})))
        return 0
    except Exception as exc:  # pragma: no cover - exercised via subprocess only
        sys.stdout.write(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    import sys

    sys.exit(_main(sys.argv))
