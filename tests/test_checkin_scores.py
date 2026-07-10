"""
Spec-table regression tests for the deterministic scoring engine.

CLAUDE.md §5 is the authoritative definition of every composite score. The AI
layer never computes scores — it reads what _compute_checkin_scores() produced —
so a formula drifting from spec silently corrupts every downstream AI output.
These tests pin each formula to worked examples taken directly from the spec so
drift fails CI instead of shipping.

Also covers log_checkin_from_sms()'s storage contract (column names must match
the checkins table; scores ride in extended_data['scores']), which regressed
once by calling the scorer with the wrong arity — swallowed by the outer
exception handler, silently dropping every SMS check-in.

Run:
    python3 -m pytest tests/test_checkin_scores.py -v
"""

import os
import sys
import types
import unittest
from unittest.mock import MagicMock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Allow running without the real supabase package (see test_data_layer_failures).
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

score = db._compute_checkin_scores


class TestStimLoad(unittest.TestCase):
    """Stim Load = MIN(caffeine_tier + stimulant_meds + booster, 10)."""

    def _sl(self, caffeine=None, meds=None, booster=None):
        ext = {}
        if caffeine is not None:
            ext['caffeine_mg'] = caffeine
        if booster is not None:
            ext['booster_used'] = booster
        return score(5, 5, 7, ext, meds or [])['stim_load']

    def test_caffeine_tiers(self):
        # Spec table with the 0mg floor fix: 0 → 0, 1–99 → 2, <250 → 5,
        # <400 → 7, ≥400 → 9.
        self.assertEqual(self._sl(caffeine=0), 0)
        self.assertEqual(self._sl(caffeine=50), 2)
        self.assertEqual(self._sl(caffeine=99), 2)
        self.assertEqual(self._sl(caffeine=100), 5)
        self.assertEqual(self._sl(caffeine=249), 5)
        self.assertEqual(self._sl(caffeine=250), 7)
        self.assertEqual(self._sl(caffeine=399), 7)
        self.assertEqual(self._sl(caffeine=400), 9)
        self.assertEqual(self._sl(caffeine=800), 9)

    def test_stimulant_med_adds_one_each(self):
        meds = [{'name': 'Adderall XR', 'taken': True},
                {'name': 'Sertraline', 'taken': True}]     # only 1 stimulant
        self.assertEqual(self._sl(caffeine=150, meds=meds), 6)  # 5 + 1

    def test_untaken_stimulant_not_counted(self):
        meds = [{'name': 'Vyvanse', 'taken': False}]
        self.assertEqual(self._sl(caffeine=150, meds=meds), 5)

    def test_booster_and_cap(self):
        # 9 (≥400mg) + 1 stim + 2 boosters = 12 → capped at 10
        meds = [{'name': 'Ritalin', 'taken': True}]
        self.assertEqual(self._sl(caffeine=450, meds=meds, booster=2), 10)

    def test_none_when_nothing_logged(self):
        self.assertIsNone(self._sl())


class TestStimLoadDrinksFallback(unittest.TestCase):
    """SMS rotating question logs caffeine_drinks (count). Tier fallback
    per spec §5: 0 → 0, 1 → 2, 2 → 5, 3–4 → 7, ≥5 → 9."""

    def _sl(self, drinks):
        return score(5, 5, 7, {'caffeine_drinks': drinks}, [])['stim_load']

    def test_drink_tiers(self):
        self.assertEqual(self._sl(0), 0)
        self.assertEqual(self._sl(1), 2)
        self.assertEqual(self._sl(2), 5)
        self.assertEqual(self._sl(3), 7)
        self.assertEqual(self._sl(4), 7)
        self.assertEqual(self._sl(5), 9)

    def test_zero_drinks_still_computes_not_none(self):
        # 0 drinks is logged data (Stim Load 0), not missing data (None).
        self.assertEqual(self._sl(0), 0)

    def test_mg_takes_precedence_over_drinks(self):
        s = score(5, 5, 7, {'caffeine_mg': 300, 'caffeine_drinks': 1}, [])
        self.assertEqual(s['stim_load'], 7)

    def test_drinks_feed_ns_load_chain(self):
        # With caffeine_drinks + sleep_quality + stress, NS Load computes —
        # the SMS restoration path for the Stim→NS→Crash chain.
        s = score(5, 6, 7, {'caffeine_drinks': 2, 'sleep_quality': 4}, [])
        self.assertEqual(s['stim_load'], 5)
        self.assertEqual(s['nervous_system_load'], round((6 + (10 - 4) + 5) / 3, 2))


class TestStabilityAndDistortion(unittest.TestCase):
    """Stability = (Mood + Energy + (10−Dissoc) + (10−Anx)) / 4;
    Mood Distortion = |Reported Mood − Stability|."""

    def test_spec_formula(self):
        # mood 8, energy 6, dissociation 2, stress(anxiety) 4
        # → (8 + 6 + 8 + 6) / 4 = 7.0 ; distortion |8 − 7| = 1.0
        s = score(8, 4, 7, {'energy': 6, 'dissociation': 2}, [])
        self.assertEqual(s['stability_score'], 7.0)
        self.assertEqual(s['mood_distortion'], 1.0)

    def test_three_term_fallback_when_dissociation_missing(self):
        # Spec §5 fallback: dissociation not recorded (e.g. SMS short
        # check-in) → (Mood + Energy + (10 − Anxiety)) / 3, never dissoc=0.
        # mood 8, energy 6, stress(anxiety) 4 → (8 + 6 + 6) / 3 = 6.67
        s = score(8, 4, 7, {'energy': 6}, [])   # dissociation absent
        self.assertEqual(s['stability_score'], 6.67)
        self.assertEqual(s['mood_distortion'], 1.33)
        self.assertEqual(s['stability_basis'], 'no_dissociation')

    def test_fallback_beats_dissoc_zero_inflation(self):
        # The old sms_default behavior stored dissociation=0, which inflated
        # stability. The fallback must NOT reproduce that inflation.
        inflated = score(8, 4, 7, {'energy': 6, 'dissociation': 0}, [])
        fallback = score(8, 4, 7, {'energy': 6}, [])
        self.assertLess(fallback['stability_score'], inflated['stability_score'])

    def test_none_when_energy_missing(self):
        s = score(8, 4, 7, {}, [])   # energy AND dissociation absent
        self.assertIsNone(s['stability_score'])
        self.assertIsNone(s['mood_distortion'])
        self.assertIsNone(s['stability_basis'])


class TestSleepDisruption(unittest.TestCase):
    """+2 <6h; +3 latency>45; +3 time awake overnight>60; +3 not fell asleep
    easily; +2 awakenings ≥2; cap 10; None when no sleep data at all."""

    def test_each_component(self):
        self.assertEqual(score(5, 5, 5.0, {}, [])['sleep_disruption'], 2)
        self.assertEqual(score(5, 5, None, {'sleep_latency_minutes': 50}, [])['sleep_disruption'], 3)
        self.assertEqual(score(5, 5, None, {'time_awake_minutes': 75}, [])['sleep_disruption'], 3)
        self.assertEqual(score(5, 5, None, {'fell_asleep_easily': False}, [])['sleep_disruption'], 3)
        self.assertEqual(score(5, 5, None, {'night_awakenings': 2}, [])['sleep_disruption'], 2)

    def test_time_awake_at_threshold_not_counted(self):
        # Spec: "> 60 min" — exactly 60 does not add.
        self.assertEqual(score(5, 5, None, {'time_awake_minutes': 60}, [])['sleep_disruption'], 0)

    def test_legacy_sms_latency_key_accepted(self):
        # SMS rotating question historically wrote 'sleep_latency_min';
        # scoring must accept it (orphaned-key fix, 2026-07-10).
        self.assertEqual(score(5, 5, None, {'sleep_latency_min': 50}, [])['sleep_disruption'], 3)

    def test_canonical_latency_key_wins_over_legacy(self):
        ext = {'sleep_latency_minutes': 10, 'sleep_latency_min': 50}
        self.assertEqual(score(5, 5, None, ext, [])['sleep_disruption'], 0)

    def test_cap_at_ten(self):
        ext = {'sleep_latency_minutes': 90, 'time_awake_minutes': 120,
               'fell_asleep_easily': False, 'night_awakenings': 4}
        # 2 + 3 + 3 + 3 + 2 = 13 → 10
        self.assertEqual(score(5, 5, 4.0, ext, [])['sleep_disruption'], 10)

    def test_none_when_no_sleep_data(self):
        self.assertIsNone(score(5, 5, None, {}, [])['sleep_disruption'])


class TestDopamineEfficiency(unittest.TestCase):
    """Dopamine Efficiency = (Energy + Focus) / 2."""

    def test_spec_formula(self):
        s = score(5, 5, 7, {'energy': 6, 'focus': 8}, [])
        self.assertEqual(s['dopamine_efficiency'], 7.0)

    def test_none_when_partial(self):
        self.assertIsNone(score(5, 5, 7, {'energy': 6}, [])['dopamine_efficiency'])


class TestAdvancedStability(unittest.TestCase):
    """(Mood + Energy + (10−Dissoc) + (10−Anx) + (10−Irrit) + Motivation) / 6."""

    def test_spec_formula(self):
        ext = {'energy': 6, 'dissociation': 2, 'irritability': 3, 'motivation': 7}
        # (8 + 6 + 8 + 6 + 7 + 7) / 6 = 42/6 = 7.0
        s = score(8, 4, 7, ext, [])
        self.assertEqual(s['advanced_stability'], 7.0)

    def test_none_without_advanced_fields(self):
        s = score(8, 4, 7, {'energy': 6, 'dissociation': 2}, [])
        self.assertIsNone(s['advanced_stability'])


class TestNervousSystemLoad(unittest.TestCase):
    """NS Load = (Anxiety + (10 − Sleep Quality) + Stim Load) / 3."""

    def test_spec_formula(self):
        ext = {'sleep_quality': 4, 'caffeine_mg': 150}
        # (6 + 6 + 5) / 3 = 5.67
        self.assertEqual(score(5, 6, 7, ext, [])['nervous_system_load'], 5.67)


class TestNutritionStability(unittest.TestCase):
    """Protein ≥7 → +4 / ≥5 → +2; Sugar ≤4 → +3 / ≤6 → +2; Hydration ≥80 → +3 / ≥60 → +2."""

    def test_max_score(self):
        ext = {'protein_servings': 7, 'sugar_servings': 3, 'hydration_oz': 90}
        self.assertEqual(score(5, 5, 7, ext, [])['nutrition_stability'], 10)

    def test_mid_tiers(self):
        ext = {'protein_servings': 5, 'sugar_servings': 6, 'hydration_oz': 60}
        self.assertEqual(score(5, 5, 7, ext, [])['nutrition_stability'], 6)

    def test_none_when_no_nutrition(self):
        self.assertIsNone(score(5, 5, 7, {}, [])['nutrition_stability'])


class TestCrashRisk(unittest.TestCase):
    """Crash Risk = SD×0.4 + NS×0.4 + (10−Nutrition)×0.2; documented fallback
    when nutrition absent: SD×0.5 + NS×0.5."""

    def test_spec_formula_with_nutrition(self):
        ext = {'sleep_quality': 4, 'caffeine_mg': 150,
               'protein_servings': 5, 'sugar_servings': 6, 'hydration_oz': 60}
        s = score(5, 6, 5.0, ext, [])
        # SD = 2; NS = (6+6+5)/3 = 5.666..; Nutrition = 6
        expected = round(min(2 * 0.4 + (17/3) * 0.4 + (10 - 6) * 0.2, 10), 2)
        self.assertEqual(s['crash_risk'], expected)

    def test_fallback_without_nutrition(self):
        ext = {'sleep_quality': 4, 'caffeine_mg': 150}
        s = score(5, 6, 5.0, ext, [])
        expected = round(min(2 * 0.5 + (17/3) * 0.5, 10), 2)
        self.assertEqual(s['crash_risk'], expected)


class TestLogCheckinFromSms(unittest.TestCase):
    """Storage contract for the Twilio SMS check-in path."""

    def _capture_client(self):
        c = MagicMock()
        captured = {}
        exec_result = MagicMock()
        exec_result.data = [{'id': 'checkin-uuid-1'}]

        def _insert(payload):
            captured['payload'] = payload
            m = MagicMock()
            m.execute.return_value = exec_result
            return m

        c.table.return_value.insert.side_effect = _insert
        return c, captured

    def test_insert_uses_real_column_names_and_stores_scores(self):
        client, captured = self._capture_client()
        orig_admin, orig_tz = db.supabase_admin, db.patient_local_today
        db.supabase_admin = client
        db.patient_local_today = lambda pid=None, tz=None: '2026-07-06'
        try:
            checkin_id = db.log_checkin_from_sms(
                patient_id='pid-1',
                data={'mood': 7, 'sleep_hours': 6.5, 'stress': 4, 'energy': 6,
                      'follow_up_note': 'slept ok', 'follow_up_type': 'sleep'},
                check_in_type='short',
            )
        finally:
            db.supabase_admin, db.patient_local_today = orig_admin, orig_tz

        self.assertEqual(checkin_id, 'checkin-uuid-1')
        p = captured['payload']
        # Real column names — 'date' and 'mood' do not exist on checkins.
        self.assertNotIn('date', p)
        self.assertNotIn('mood', p)
        self.assertEqual(p['checkin_date'], '2026-07-06')
        self.assertEqual(p['mood_score'], 7)
        self.assertEqual(p['stress_score'], 4)
        self.assertEqual(p['sleep_hours'], 6.5)
        self.assertEqual(p['source'], 'sms')
        # Energy is not a column — it rides in extended_data, like the web path.
        self.assertNotIn('energy', p)
        self.assertEqual(p['extended_data']['energy'], 6)
        # Computed scores stored in extended_data['scores'] without exploding
        # into nonexistent table columns.
        self.assertIn('scores', p['extended_data'])
        self.assertNotIn('stim_load', p)
        self.assertNotIn('mood_distortion', p)

    def test_returns_none_and_survives_storage_failure(self):
        client = MagicMock()
        client.table.side_effect = RuntimeError('db down')
        orig_admin, orig_tz = db.supabase_admin, db.patient_local_today
        db.supabase_admin = client
        db.patient_local_today = lambda pid=None, tz=None: '2026-07-06'
        try:
            result = db.log_checkin_from_sms('pid-1', {'mood': 5}, 'short')
        finally:
            db.supabase_admin, db.patient_local_today = orig_admin, orig_tz
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
