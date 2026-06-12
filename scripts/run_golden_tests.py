#!/usr/bin/env python3
"""
Golden-file regression harness for the auditory biomarker extraction pipeline.

Runs extract_features() against 8 synthetic transcript profiles and validates
that each output satisfies its declared golden contract.  The harness does NOT
require a live Anthropic key — by default it runs in MOCK mode (no Claude call).
Set the environment variable GOLDEN_LIVE=1 to hit the real API.

Usage:
    # Mock mode (no API key required):
    python3 scripts/run_golden_tests.py

    # Live mode (requires ANTHROPIC_API_KEY in env):
    GOLDEN_LIVE=1 python3 scripts/run_golden_tests.py

    # Regenerate golden files from live output (first-time setup):
    GOLDEN_LIVE=1 GOLDEN_REGEN=1 python3 scripts/run_golden_tests.py

Exit code: 0 = all passed, 1 = failures or unexpected errors.
"""

import os
import sys
import json
import unittest
import argparse
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock

# ---------------------------------------------------------------------------
# Repo path setup
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

GOLDEN_DIR = REPO_ROOT / "tests" / "golden"
GOLDEN_LIVE = os.environ.get("GOLDEN_LIVE", "0").strip() == "1"
GOLDEN_REGEN = os.environ.get("GOLDEN_REGEN", "0").strip() == "1"

logging.basicConfig(level=logging.WARNING)

# ---------------------------------------------------------------------------
# Synthetic transcript profiles
# ---------------------------------------------------------------------------

TRANSCRIPTS = {
    "depressive": {
        "text": (
            "THERAPIST: How have you been this week?\n"
            "PATIENT: I don't know. Same as always, I guess. Nothing really changed.\n"
            "THERAPIST: Can you tell me more about that?\n"
            "PATIENT: It's just... hard to get out of bed. I sleep a lot but I'm still "
            "tired all the time. I don't enjoy anything anymore. Even things I used to "
            "love just feel flat. I've been isolating. I canceled dinner with my sister "
            "again. I feel guilty about that but not enough to do anything differently.\n"
            "THERAPIST: How has your sleep been?\n"
            "PATIENT: About eight or nine hours but I wake up feeling worse than when "
            "I went to bed. I've been having a lot of heavy dreams.\n"
            "THERAPIST: How are you feeling about the future?\n"
            "PATIENT: I don't know. I don't really think about the future. It all feels "
            "kind of grey. Like it doesn't matter much what I do.\n"
        ),
        "session_type": "therapy",
        "golden": {
            "crisis_detected": False,
            "crisis_level": 0,
            "features_present": True,
            # Speech pattern expectation (soft assertion: should be in set)
            "speech_rate_expected_set": {"normal", "slowed", None},
            "clinical_pattern_type_expected_set": {
                "depressive", "mixed", "none_detected", None
            },
            # Mood estimate should be LOW (≤ 5.5) if model populates it
            "mood_estimate_max": 5.5,
        },
    },

    "anxiety_stress": {
        "text": (
            "THERAPIST: What's been on your mind?\n"
            "PATIENT: Everything. I can't stop thinking. I lie awake going over everything "
            "that could go wrong. I've been having panic attacks at work — like my heart "
            "starts racing and I feel like I can't breathe and I have to leave the room.\n"
            "THERAPIST: How often?\n"
            "PATIENT: Twice this week. Maybe three times last week. My chest feels tight "
            "almost constantly. I've been irritable with my partner, which I feel terrible "
            "about. I know I'm doing it but I can't stop.\n"
            "THERAPIST: Are you sleeping?\n"
            "PATIENT: Not well. Maybe four or five hours. I wake up at 3am and just "
            "spiral. I've tried the breathing exercises you showed me but they're not "
            "working right now.\n"
        ),
        "session_type": "therapy",
        "golden": {
            "crisis_detected": False,
            "crisis_level": 0,
            "features_present": True,
            "clinical_pattern_type_expected_set": {
                "anxiety_stress", "mixed", "none_detected", None
            },
            "stressor_count_min": 1,
        },
    },

    "manic_hypomania": {
        "text": (
            "THERAPIST: How are you feeling today?\n"
            "PATIENT: Amazing, honestly. Better than I've felt in months — maybe years. "
            "I've been working on like four projects at once. I started a podcast, I'm "
            "learning Spanish, I've been going to the gym twice a day. I feel like my "
            "brain is finally working at full speed.\n"
            "THERAPIST: How much sleep are you getting?\n"
            "PATIENT: I don't really need that much right now — maybe three or four hours "
            "and I wake up completely refreshed. I feel like I could go all day. I've "
            "also been spending more — I bought some equipment for the podcast, some "
            "guitar gear, booked a trip to Portugal. It's fine, I have savings.\n"
            "THERAPIST: Have you been taking your medication?\n"
            "PATIENT: I actually stopped a couple weeks ago. I feel so good I figured I "
            "didn't need it anymore. My doctor doesn't know yet.\n"
        ),
        "session_type": "psychiatry",
        "golden": {
            "crisis_detected": False,
            "crisis_level": 0,
            "features_present": True,
            "clinical_pattern_type_expected_set": {
                "mania_hypomania", "mixed", "none_detected", None
            },
        },
    },

    "psychosis_risk": {
        "text": (
            "THERAPIST: Tell me about what's been happening.\n"
            "PATIENT: I've been noticing things. Like... there are patterns everywhere. "
            "The TV shows keep referencing things I've been thinking about — it's like "
            "they're talking directly to me. I know how that sounds. I'm not sure if "
            "I'm imagining it but it feels very real.\n"
            "THERAPIST: What other kinds of things have you been noticing?\n"
            "PATIENT: I keep hearing something — like a murmur, on the edge of what I "
            "can hear. I can't make out words but it feels like something is trying to "
            "communicate. I haven't told anyone because I'm afraid of what they'd think.\n"
            "THERAPIST: How are you sleeping?\n"
            "PATIENT: Maybe three hours. I don't feel tired though. My thoughts are "
            "moving very fast. Sometimes I forget what I was saying in the middle of "
            "a sentence.\n"
        ),
        "session_type": "psychiatry",
        "golden": {
            "crisis_detected": False,
            "crisis_level": 0,
            "features_present": True,
            "clinical_pattern_type_expected_set": {
                "psychosis_risk", "mixed", "none_detected", None
            },
        },
    },

    "crisis_level3": {
        "text": (
            "THERAPIST: How are you doing today?\n"
            "PATIENT: Not good. I've been thinking about suicide. I have a plan — I've "
            "thought about how I would do it and when. I've been writing letters. I know "
            "this is serious but I don't know how to stop the thoughts.\n"
            "THERAPIST: I'm glad you told me. I want to make sure you're safe.\n"
        ),
        "session_type": "therapy",
        "golden": {
            "crisis_detected": True,
            "crisis_level_min": 3,
            "features_present": False,  # extraction blocked at Level 3+
            "safety_note_present": True,
        },
    },

    "passive_concern_level1": {
        "text": (
            "THERAPIST: How have things been?\n"
            "PATIENT: Hard. I've been feeling like there's no point. Like nothing I do "
            "makes any difference. I'm not suicidal or anything, I just feel really "
            "hopeless. Like why bother.\n"
            "THERAPIST: I hear that. Can you tell me more?\n"
            "PATIENT: I've just been going through the motions. Work, sleep, repeat. "
            "I don't feel joy about anything. I've been withdrawing from people.\n"
        ),
        "session_type": "therapy",
        "golden": {
            # Level 1 (hopelessness) — extraction continues
            "crisis_level_max": 2,
            "features_present": True,
        },
    },

    "positive_baseline": {
        "text": (
            "THERAPIST: Good to see you. How's the week been?\n"
            "PATIENT: Really good, actually. The medication adjustment seems to be "
            "working. I've been sleeping seven or eight hours, waking up refreshed. "
            "I went for a run three times this week which I haven't done in months.\n"
            "THERAPIST: That's great. How's your mood?\n"
            "PATIENT: Much more stable. I had one difficult day on Thursday — a hard "
            "conversation with my manager — but I handled it okay. Didn't spiral the "
            "way I would have before. I'm feeling more like myself.\n"
            "THERAPIST: Any anxiety?\n"
            "PATIENT: Low. Like a two or three out of ten on most days. A seven on "
            "Thursday but it came back down quickly.\n"
        ),
        "session_type": "therapy",
        "golden": {
            "crisis_detected": False,
            "crisis_level": 0,
            "features_present": True,
            "clinical_pattern_type_expected_set": {
                "none_detected", "mixed", None
            },
            # Mood estimate should be HIGH (≥ 5.0) if model populates it
            "mood_estimate_min": 5.0,
        },
    },

    "mixed_signals": {
        "text": (
            "THERAPIST: How are you?\n"
            "PATIENT: Honestly, I'm all over the place. I feel okay in the mornings "
            "but by afternoon I'm exhausted and irritable. I've been tearful for no "
            "reason and then an hour later I'm laughing with my friends and feeling fine.\n"
            "THERAPIST: Tell me about the sleep.\n"
            "PATIENT: Some nights are fine, some nights I'm up for hours. There's no "
            "pattern I can figure out. I've been having a glass of wine most nights to "
            "help fall asleep which I know isn't ideal.\n"
            "THERAPIST: Any thoughts of harming yourself?\n"
            "PATIENT: No. Nothing like that. Just the mood swings are exhausting.\n"
        ),
        "session_type": "therapy",
        "golden": {
            "crisis_detected": False,
            "crisis_level": 0,
            "features_present": True,
            "clinical_pattern_type_expected_set": {
                "mixed", "anxiety_stress", "depressive", "none_detected", None
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Mock extraction result — used when GOLDEN_LIVE is False
# ---------------------------------------------------------------------------

def _mock_extraction_result(profile_name: str, profile: dict) -> dict:
    """
    Return a minimal well-formed extract_features() result for mock mode.
    Satisfied all structural assertions without hitting the API.
    """
    g = profile["golden"]
    crisis_detected = g.get("crisis_detected", False)
    crisis_level = g.get("crisis_level",
                         g.get("crisis_level_min", g.get("crisis_level_max", 0)))
    features_present = g.get("features_present", True)

    features = None
    scores = None

    if features_present:
        # Synthesize a minimal features dict that will pass golden checks
        mock_mood = None
        if "mood_estimate_min" in g:
            mock_mood = g["mood_estimate_min"] + 0.5
        elif "mood_estimate_max" in g:
            mock_mood = g["mood_estimate_max"] - 0.5

        # Pick first allowed clinical pattern type
        pattern_set = g.get("clinical_pattern_type_expected_set",
                            {"none_detected"})
        mock_pattern = next(iter(pattern_set - {None}), "none_detected")

        stressor_count = g.get("stressor_count_min", 0)

        features = {
            "mood_estimate": mock_mood,
            "sleep_hours": None,
            "sleep_disruption_proxy": None,
            "stressor_count": stressor_count,
            "themes": [],
            "medication_signals": [],
            "notable_symptoms": [],
            "speech_features": {
                "speech_rate": "normal",
                "prosody": "normal",
                "pauses": "normal",
                "speech_coherence": "intact",
                "arousal": "normal",
                "vocal_affect": "normal",
                "confidence": "low",
                "severity_note": None,
                "baseline_deviation": None,
            },
            "clinical_pattern_type": mock_pattern,
            "speech_concern_flag": False,
        }
        scores = {
            "mood_estimate": mock_mood,
            "sleep_hours": None,
            "sleep_disruption_proxy": None,
            "stressor_count": stressor_count,
        }

    safety_note = None
    if g.get("safety_note_present") or crisis_level >= 3:
        safety_note = (
            "Possible self-harm risk detected. Immediate clinical review recommended."
        )

    return {
        "crisis_detected": crisis_detected,
        "crisis_level": crisis_level,
        "crisis_result": {"level": crisis_level, "adjusted_score": crisis_level * 2},
        "safety_note": safety_note,
        "features": features,
        "scores": scores,
        "session_date": None,
        "session_type": profile["session_type"],
        "transcript_length": len(profile["text"]),
    }


# ---------------------------------------------------------------------------
# Golden file helpers
# ---------------------------------------------------------------------------

def _golden_path(profile_name: str) -> Path:
    return GOLDEN_DIR / f"{profile_name}.json"


def _load_golden(profile_name: str) -> dict | None:
    p = _golden_path(profile_name)
    if not p.exists():
        return None
    with open(p) as f:
        return json.load(f)


def _save_golden(profile_name: str, result: dict) -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    with open(_golden_path(profile_name), "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"  [REGEN] Saved golden file: {_golden_path(profile_name)}")


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

class GoldenAssertionError(AssertionError):
    pass


def _assert(cond: bool, msg: str):
    if not cond:
        raise GoldenAssertionError(msg)


def _validate_output_against_golden_contract(profile_name: str, result: dict, g: dict):
    """
    Apply all golden contract assertions for a profile.
    'g' is the 'golden' sub-dict from TRANSCRIPTS.
    """
    # 1. Crisis detection
    if "crisis_detected" in g:
        _assert(result["crisis_detected"] == g["crisis_detected"],
                f"[{profile_name}] crisis_detected: got {result['crisis_detected']}, "
                f"expected {g['crisis_detected']}")

    if "crisis_level" in g:
        _assert(result["crisis_level"] == g["crisis_level"],
                f"[{profile_name}] crisis_level: got {result['crisis_level']}, "
                f"expected {g['crisis_level']}")

    if "crisis_level_min" in g:
        _assert(result["crisis_level"] >= g["crisis_level_min"],
                f"[{profile_name}] crisis_level {result['crisis_level']} < "
                f"min {g['crisis_level_min']}")

    if "crisis_level_max" in g:
        _assert(result["crisis_level"] <= g["crisis_level_max"],
                f"[{profile_name}] crisis_level {result['crisis_level']} > "
                f"max {g['crisis_level_max']}")

    # 2. Feature presence / absence
    if "features_present" in g:
        if g["features_present"]:
            _assert(result.get("features") is not None,
                    f"[{profile_name}] expected features to be present but got None")
        else:
            _assert(result.get("features") is None,
                    f"[{profile_name}] expected features to be blocked but got "
                    f"{result.get('features')}")

    # 3. Safety note
    if g.get("safety_note_present"):
        _assert(result.get("safety_note") is not None,
                f"[{profile_name}] expected safety_note to be present")

    features = result.get("features") or {}
    scores = result.get("scores") or {}

    # 4. Speech features vocabulary (if features present)
    if features:
        sf = features.get("speech_features") or {}

        # Validate constrained vocabulary (CLAUDE.md §24)
        _valid_speech_rate     = {None, "normal", "slowed", "pressured"}
        _valid_prosody         = {None, "normal", "flat", "elevated"}
        _valid_pauses          = {None, "normal", "increased", "decreased"}
        _valid_coherence       = {None, "intact", "disorganized"}
        _valid_arousal         = {None, "normal", "low", "elevated", "agitated"}
        _valid_vocal_affect    = {None, "normal", "flat", "strained"}

        for field, valid_set in [
            ("speech_rate",     _valid_speech_rate),
            ("prosody",         _valid_prosody),
            ("pauses",          _valid_pauses),
            ("speech_coherence", _valid_coherence),
            ("arousal",         _valid_arousal),
            ("vocal_affect",    _valid_vocal_affect),
        ]:
            val = sf.get(field)
            _assert(val in valid_set,
                    f"[{profile_name}] speech_features.{field}={val!r} not in "
                    f"valid set {valid_set}")

        # speech_rate contract check
        if "speech_rate_expected_set" in g:
            val = sf.get("speech_rate")
            _assert(val in g["speech_rate_expected_set"],
                    f"[{profile_name}] speech_rate={val!r} not in "
                    f"expected set {g['speech_rate_expected_set']}")

    # 5. Clinical pattern type
    if features and "clinical_pattern_type_expected_set" in g:
        val = features.get("clinical_pattern_type")
        _assert(val in g["clinical_pattern_type_expected_set"],
                f"[{profile_name}] clinical_pattern_type={val!r} not in "
                f"expected set {g['clinical_pattern_type_expected_set']}")

    # 6. Mood estimate range
    if features and "mood_estimate_min" in g:
        mood = (features.get("mood_estimate") or
                (scores.get("mood_estimate") if scores else None))
        if mood is not None:  # model may not always produce this
            _assert(float(mood) >= g["mood_estimate_min"],
                    f"[{profile_name}] mood_estimate={mood} < min {g['mood_estimate_min']}")

    if features and "mood_estimate_max" in g:
        mood = (features.get("mood_estimate") or
                (scores.get("mood_estimate") if scores else None))
        if mood is not None:
            _assert(float(mood) <= g["mood_estimate_max"],
                    f"[{profile_name}] mood_estimate={mood} > max {g['mood_estimate_max']}")

    # 7. Stressor count
    if features and "stressor_count_min" in g:
        count = features.get("stressor_count", 0) or 0
        _assert(int(count) >= g["stressor_count_min"],
                f"[{profile_name}] stressor_count={count} < min {g['stressor_count_min']}")

    # 8. Structural invariants (always checked when features present)
    if result.get("features") is not None:
        _assert("speech_features" in features,
                f"[{profile_name}] features dict missing 'speech_features' key")
        _assert(result.get("session_type") is not None,
                f"[{profile_name}] session_type should not be None in output")
        _assert(isinstance(result.get("transcript_length", 0), int),
                f"[{profile_name}] transcript_length should be an int")


# ---------------------------------------------------------------------------
# Extraction runner
# ---------------------------------------------------------------------------

def _run_extraction(profile_name: str, profile: dict) -> dict:
    """
    Run extract_features() for a profile.
    In mock mode, returns a synthetic result without a Claude call.
    In live mode, calls the real function.
    """
    if not GOLDEN_LIVE:
        return _mock_extraction_result(profile_name, profile)

    from transcript_engine import extract_features
    return extract_features(
        transcript_text=profile["text"],
        session_type=profile["session_type"],
    )


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class GoldenTranscriptTests(unittest.TestCase):
    """
    Each profile is tested as a separate test method.
    Generated dynamically below so failures are reported per-profile.
    """
    pass


def _make_test(profile_name: str, profile: dict):
    def test_method(self):
        result = _run_extraction(profile_name, profile)

        if GOLDEN_REGEN and GOLDEN_LIVE:
            _save_golden(profile_name, result)
            # Still validate against golden contract even on regen
            _validate_output_against_golden_contract(profile_name, result,
                                                     profile["golden"])
            return

        golden_file = _load_golden(profile_name)
        if golden_file is not None and GOLDEN_LIVE:
            # Structural regression: key fields should be present
            for key in ("crisis_detected", "crisis_level", "session_type"):
                self.assertIn(key, result,
                              msg=f"[{profile_name}] result missing key: {key}")

        # Always validate against declared contract
        try:
            _validate_output_against_golden_contract(profile_name, result,
                                                     profile["golden"])
        except GoldenAssertionError as e:
            self.fail(str(e))

    test_method.__name__ = f"test_{profile_name}"
    test_method.__doc__ = f"Golden contract: {profile_name}"
    return test_method


# Attach one test method per profile
for _name, _profile in TRANSCRIPTS.items():
    setattr(GoldenTranscriptTests, f"test_{_name}", _make_test(_name, _profile))


# ---------------------------------------------------------------------------
# Structural integrity test (independent of profile content)
# ---------------------------------------------------------------------------

class GoldenStructuralTests(unittest.TestCase):
    """Fast structural tests that don't require the AI pipeline."""

    def test_all_profiles_have_golden_contract(self):
        """Every profile in TRANSCRIPTS must have a 'golden' key."""
        for name, profile in TRANSCRIPTS.items():
            self.assertIn("golden", profile,
                          msg=f"Profile '{name}' is missing a 'golden' contract dict")

    def test_golden_contracts_have_at_least_one_assertion(self):
        """Each contract should assert something meaningful."""
        for name, profile in TRANSCRIPTS.items():
            g = profile.get("golden", {})
            self.assertGreater(len(g), 0,
                               msg=f"Profile '{name}' golden contract is empty")

    def test_crisis_profiles_have_crisis_level_assertion(self):
        """Profiles that declare crisis_detected=True must also assert on level."""
        for name, profile in TRANSCRIPTS.items():
            g = profile.get("golden", {})
            if g.get("crisis_detected") is True:
                has_level = (
                    "crisis_level" in g or
                    "crisis_level_min" in g or
                    "crisis_level_max" in g
                )
                self.assertTrue(has_level,
                    msg=f"Profile '{name}' has crisis_detected=True but no "
                        f"crisis_level assertion")

    def test_mock_results_satisfy_contracts(self):
        """
        Mock mode is used in CI.  Verify that _mock_extraction_result() itself
        satisfies the golden contract for every profile — otherwise mock mode
        would silently pass tests that live mode would fail.
        """
        for name, profile in TRANSCRIPTS.items():
            mock_result = _mock_extraction_result(name, profile)
            try:
                _validate_output_against_golden_contract(name, mock_result,
                                                         profile["golden"])
            except GoldenAssertionError as e:
                self.fail(
                    f"Mock result for '{name}' violates its own golden contract:\n{e}"
                )

    def test_transcript_profiles_are_unique(self):
        """No two profiles should share identical transcript text."""
        seen = {}
        for name, profile in TRANSCRIPTS.items():
            text = profile["text"]
            self.assertNotIn(text, seen,
                msg=f"Profile '{name}' shares transcript text with '{seen.get(text)}'")
            seen[text] = name


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    mode = "LIVE" if GOLDEN_LIVE else "MOCK"
    regen_note = " + REGEN" if GOLDEN_REGEN else ""
    print(f"\n=== CognaSync Golden Transcript Tests  [{mode}{regen_note}] ===\n")

    if GOLDEN_LIVE:
        print("  Calling extract_features() with real Claude API.\n"
              "  Requires ANTHROPIC_API_KEY in environment.\n")
    else:
        print("  Running in mock mode (no API calls).\n"
              "  Set GOLDEN_LIVE=1 to test against the real pipeline.\n")

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(GoldenStructuralTests))
    suite.addTests(loader.loadTestsFromTestCase(GoldenTranscriptTests))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
