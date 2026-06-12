"""
Unit tests for the safety layer in claude_api.py — the regulatory core
(spec §2, §3, §10, §22, §23).

Covers:
  - _check_crisis / check_crisis  (binary patient-facing detection, spec §10)
  - _sanitize_output              (forbidden-language enforcement, spec §3)
  - score_crisis                  (graduated provider-channel scoring, spec §22)
  - population modifiers          (spec §23)

All functions under test are deterministic — no DB, no Claude calls.

Run:
    python3 -m pytest tests/test_safety_layer.py -v
"""

import sys
import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from claude_api import (
    _check_crisis,
    check_crisis,
    _sanitize_output,
    score_crisis,
)


# ---------------------------------------------------------------------------
# Patient-facing crisis detection (spec §10)
# ---------------------------------------------------------------------------

class TestCheckCrisis(unittest.TestCase):
    # Every keyword spec §10 requires for the patient-facing channel.
    SPEC_REQUIRED_PHRASES = [
        "suicide", "suicidal", "kill myself", "end my life", "ending my life",
        "don't want to live", "don't want to be alive", "want to die",
        "better off dead", "self-harm", "self harm", "hurt myself",
        "cut myself",
    ]

    def test_all_spec_keywords_trigger(self):
        for phrase in self.SPEC_REQUIRED_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertTrue(
                    _check_crisis(f"journal text mentioning {phrase} today"),
                    f"spec §10 keyword not detected: {phrase!r}",
                )

    def test_case_insensitive(self):
        self.assertTrue(_check_crisis("I want to KILL MYSELF"))
        self.assertTrue(_check_crisis("Suicidal thoughts again"))

    def test_benign_text_does_not_trigger(self):
        benign = [
            "Slept 7 hours, mood is a 6 today.",
            "Work was stressful but the walk helped.",
            "I'm killing it at work lately.",
            "That movie about the suicide squad was fun.",  # known substring tradeoff
        ]
        # Note: 'suicide squad' DOES trigger (substring match) — maximum
        # caution is intentional on the patient channel. Only assert the
        # genuinely keyword-free entries.
        for text in benign[:3]:
            with self.subTest(text=text):
                self.assertFalse(_check_crisis(text))

    def test_public_wrapper_handles_bad_input(self):
        self.assertFalse(check_crisis(None))
        self.assertFalse(check_crisis(""))
        self.assertFalse(check_crisis(123))
        self.assertTrue(check_crisis("i want to end my life"))


# ---------------------------------------------------------------------------
# Output sanitization (spec §3)
# ---------------------------------------------------------------------------

class TestSanitizeHardBlock(unittest.TestCase):
    """Diagnostic labels and medication advice suppress the whole output."""

    HARD_BLOCK_SAMPLES = [
        "Based on your scores, you are depressed.",
        "It seems you are anxious about work.",
        "The data suggests you are manic right now.",
        "You could stop taking the medication on weekends.",
        "You might reduce your dose if mornings are hard.",
        "Consider whether to increase your dose.",
        "You should take it earlier in the day.",
        "Stick with it — this will make you better.",
    ]

    def test_hard_block_returns_none(self):
        for text in self.HARD_BLOCK_SAMPLES:
            with self.subTest(text=text):
                self.assertIsNone(_sanitize_output(text))

    def test_hard_block_case_insensitive(self):
        self.assertIsNone(_sanitize_output("YOU ARE DEPRESSED."))
        self.assertIsNone(_sanitize_output("Stop Taking your meds."))


class TestSanitizeSubstitution(unittest.TestCase):
    """Causal/diagnostic phrasing is replaced in place; output is preserved."""

    def test_diagnostic_you_have_condition_is_substituted(self):
        out = _sanitize_output("It looks like you have depression.")
        self.assertIsNotNone(out)
        self.assertNotIn("you have", out.lower())
        self.assertIn("your logs reflect", out.lower())

    def test_you_have_with_article_keeps_article(self):
        out = _sanitize_output("The data shows you have an anxiety disorder.")
        self.assertIsNotNone(out)
        self.assertNotIn("you have", out.lower())
        self.assertIn("your logs reflect an anxiety disorder", out.lower())

    def test_substitutions_preserve_spacing(self):
        """Regression: the old substitution dropped the trailing space,
        producing glued words like 'experiencinga'."""
        cases = [
            "It looks like you have depression and low sleep.",
            "This is caused by poor sleep.",
            "This explains your fatigue.",
            "You were diagnosed with insomnia per your notes.",
        ]
        for text in cases:
            with self.subTest(text=text):
                out = _sanitize_output(text)
                self.assertIsNotNone(out)
                # No two letters glued across a replacement boundary:
                # every word in output must be separated by whitespace/punct.
                self.assertNotRegex(out, r"reflectsa|reflecta|witha|withthe")
                # Crude but effective: replacement words never fuse with the
                # following token.
                for fused in ("reflectdepression", "withpoor", "yourfatigue"):
                    self.assertNotIn(fused, out.replace(" ", "TOKEN"))

    def test_each_substitution_pattern_fires(self):
        cases = {
            "you suffer from insomnia": "you suffer from",
            "diagnosed with adhd": "diagnosed with",
            "you are struggling with focus": "you are struggling with",
            "this is a sign of progress": "this is a sign of",
            "this confirms that the trend is real": "this confirms that",
            "this explains your low energy": "this explains your",
            "this is caused by caffeine": "this is caused by",
            "caused by your medication change": "caused by your medication",
            "this is a side effect of the change": "this is a side effect",
        }
        for text, forbidden in cases.items():
            with self.subTest(forbidden=forbidden):
                out = _sanitize_output(f"Note: {text}.")
                self.assertIsNotNone(out)
                self.assertNotIn(forbidden, out.lower())


class TestSanitizeBenignTextUntouched(unittest.TestCase):
    """Regression: the old broad 'you have ' pattern mangled benign text."""

    BENIGN = [
        "Great work — you have a 7-day streak going.",
        "You have logged sleep every night this week.",
        "You have three check-ins so far this month.",
        "You have been consistent with morning check-ins.",
        "Your mood came in at 7 today — up from your 5.1 average.",
        "Sleep averaged 6.8 hours over the 14 days logged.",
    ]

    def test_benign_text_passes_through_unchanged(self):
        for text in self.BENIGN:
            with self.subTest(text=text):
                self.assertEqual(_sanitize_output(text), text)


# ---------------------------------------------------------------------------
# Graduated crisis scoring — provider/transcript channel (spec §22)
# ---------------------------------------------------------------------------

class TestScoreCrisis(unittest.TestCase):
    def test_empty_and_invalid_input(self):
        for bad in (None, "", 0):
            with self.subTest(input=bad):
                result = score_crisis(bad)
                self.assertEqual(result["level"], 0)
                self.assertEqual(result["adjusted_score"], 0)

    def test_no_signal_text_is_level_0(self):
        result = score_crisis("Patient discussed work stress and sleep routine.")
        self.assertEqual(result["level"], 0)
        self.assertEqual(result["score"], 0)

    def test_hopelessness_alone_is_level_1(self):
        result = score_crisis("Everything feels hopeless lately.")
        self.assertEqual(result["score"], 1)
        self.assertEqual(result["level"], 1)
        self.assertTrue(result["features"]["hopelessness"])

    def test_direct_intent_alone_is_level_2(self):
        result = score_crisis("I want to kill myself.")
        self.assertTrue(result["features"]["direct_intent"])
        self.assertEqual(result["score"], 4)
        self.assertEqual(result["level"], 2)

    def test_direct_intent_plus_plan_is_level_4(self):
        # Spec §22: Level 4 when direct_intent AND (plan OR means),
        # regardless of total score.
        result = score_crisis("I want to kill myself and I have a plan.")
        self.assertTrue(result["features"]["direct_intent"])
        self.assertTrue(result["features"]["specific_plan"])
        self.assertEqual(result["level"], 4)

    def test_score_threshold_level_3(self):
        # direct_intent (4) + recurrent_ideation (2) = 6 → Level 3
        result = score_crisis(
            "I keep thinking about it — I want to kill myself."
        )
        self.assertGreaterEqual(result["adjusted_score"], 6)
        self.assertGreaterEqual(result["level"], 3)

    def test_never_raises_on_weird_input(self):
        for weird in ("🙂" * 500, "a" * 100000, "\x00\x01", "ünïcødé ãccents"):
            score_crisis(weird)  # must not raise


# ---------------------------------------------------------------------------
# Population escalation modifiers (spec §23)
# ---------------------------------------------------------------------------

class TestPopulationModifiers(unittest.TestCase):
    PASSIVE_TEXT = "Everything feels hopeless."  # base score 1, Level 1

    def test_modifier_raises_passive_signal(self):
        base = score_crisis(self.PASSIVE_TEXT)
        flagged = score_crisis(
            self.PASSIVE_TEXT, population_flags={"prior_self_harm": True}
        )
        self.assertGreater(flagged["adjusted_score"], base["adjusted_score"])
        self.assertGreaterEqual(flagged["population_modifier"], 1)

    def test_modifier_capped_at_plus_2(self):
        flagged = score_crisis(
            self.PASSIVE_TEXT,
            population_flags={
                "adolescent": True,
                "veteran": True,
                "prior_self_harm": True,
                "serious_mental_illness": True,
            },
        )
        self.assertLessEqual(flagged["population_modifier"], 2)

    def test_modifier_never_applied_to_level_3_plus(self):
        # Spec §23 rule 3: Level 3 and Level 4 base scores are never modified.
        high_text = "I keep thinking about it — I want to kill myself."  # raw 6
        base = score_crisis(high_text)
        self.assertGreaterEqual(base["score"], 6)
        flagged = score_crisis(
            high_text,
            population_flags={"prior_self_harm": True, "veteran": True},
        )
        self.assertEqual(flagged["population_modifier"], 0)
        self.assertEqual(flagged["adjusted_score"], flagged["score"])
        self.assertEqual(flagged["level"], base["level"])

    def test_inactive_flags_do_nothing(self):
        flagged = score_crisis(
            self.PASSIVE_TEXT, population_flags={"veteran": False}
        )
        self.assertEqual(flagged["population_modifier"], 0)

    def test_unknown_flags_ignored(self):
        flagged = score_crisis(
            self.PASSIVE_TEXT, population_flags={"not_a_real_flag": True}
        )
        self.assertEqual(flagged["population_modifier"], 0)


if __name__ == "__main__":
    unittest.main()
