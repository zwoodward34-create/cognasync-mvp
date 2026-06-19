"""Regression tests for the two P0 safety defects in the psychiatry brief
(claude_api.generate_psychiatry_summary).

Context — the 2026-06-18 "Clinical Summary — Zach Woodward" brief shipped with:

  P0 #1  The suicidality monitoring target rendered "no data to assess" on the
         same page as a 🔴 hopelessness voice-note flag. Root cause: target
         status was computed channel-blind (check-in rotating fields only) and
         two prompt rules contradicted each other (focus_addon "surface every
         target" vs §22 "don't scatter"). Fix: _compute_suicidality_escalation()
         joins the voice/journal crisis channel + engagement gap, folds the
         targets, and mandates one deterministic 🔴 consolidation flag, with a
         post-generation guard that prepends the routing line if it is missing.

  P0 #2  The voice note carried two different dates (06-09 vs 06-12). Root cause:
         the deterministic divergence detector had a too-tight gap<=3 gate, so a
         4-day voice/check-in gap under-fired and the model freelanced the date.
         Fix: _compute_voice_divergence() widens the gate to 7 days, counts
         crisis_detected as low-affect, and pins both ISO dates.

These tests run OFFLINE. `anthropic`, `database`, and the model call (_call_claude)
are stubbed so the suite needs no API key, no Supabase, and no network — the logic
under test is deterministic. Run with either:

    python3 tests/test_psychiatry_safety.py        # plain runner
    pytest tests/test_psychiatry_safety.py         # if pytest is installed
"""
import importlib.util
import os
import sys
import types

# ── Offline stubs (must be registered before importing claude_api) ───────────
if 'anthropic' not in sys.modules:
    _anthropic = types.ModuleType('anthropic')
    _anthropic.Anthropic = lambda *a, **k: None
    sys.modules['anthropic'] = _anthropic

if 'database' not in sys.modules:
    _database = types.ModuleType('database')
    # Only the score computation is touched during brief assembly; fixed values
    # are sufficient because these tests assert on flag/date logic, not scoring.
    _database._compute_checkin_scores = lambda mood, stress, sleep, ext, meds: {
        'stim_load': 7.0, 'stability_score': 8.8, 'crash_risk': 2.2,
        'nervous_system_load': 4.1, 'sleep_disruption_score': 0.4,
        'dopamine_efficiency': 8.0, 'mood_distortion': 0.3, 'nutrition_score': 6,
    }
    _database.__getattr__ = lambda name: (lambda *a, **k: None)
    sys.modules['database'] = _database

os.environ.setdefault('ANTHROPIC_API_KEY', 'test')

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    'claude_api', os.path.join(_REPO, 'claude_api.py'))
ca = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ca)


# ── Shared fixtures mirroring the real brief ──────────────────────────────────
def _crisis_session(date='2026-06-12'):
    return {
        'session_id': 's1', 'session_date': date, 'processing_status': 'complete',
        'crisis_detected': True,
        'features': {'speech_features': {
            'prosody': 'flat', 'arousal': 'low',
            'vocal_affect': 'flat', 'clinical_pattern_type': 'depressive'}},
        'scores': {},
    }


def _checkins():
    return [
        {'date': '2026-06-04', 'mood': 9,  'stability_score': 9.0},
        {'date': '2026-06-06', 'mood': 9,  'stability_score': 9.0},
        {'date': '2026-06-08', 'mood': 10, 'stability_score': 9.5},
    ]


def _engagement_gap():
    return {
        'period_days': 15, 'active_days': 3, 'participation_rate': 0.2,
        'max_consecutive_gap': 9, 'extended_no_response': True, 'max_prompt_gap': 9,
        'prompt_gap_segments': [{'start': '2026-06-09', 'end': '2026-06-17', 'days': 9}],
    }


_FOCUS = {'focus_domains': ['suicidality', 'mood']}
_HOPELESS_VT = [{'date': '2026-06-12',
                 'transcript': 'Overwhelmed, hopeless about job search, self-blaming.'}]


# ── P0 #2 — voice/check-in divergence fires across a 4-day gap ────────────────
def test_voice_divergence_fires_at_four_day_gap():
    div = ca._compute_voice_divergence([_crisis_session()], _checkins())
    assert len(div) == 1, "divergence must fire at a 4-day gap (was gated at <=3)"
    rec = div[0]
    assert rec['session_date'] == '2026-06-12'
    assert rec['nearest_checkin_date'] == '2026-06-08'
    assert rec['days_between'] == 4
    # The dateless engagement-gap start must never be substituted for a real date.
    assert '2026-06-09' not in (rec['session_date'], rec['nearest_checkin_date'])


def test_voice_divergence_silent_when_no_low_affect_session():
    calm = [{'session_date': '2026-06-12', 'processing_status': 'complete',
             'crisis_detected': False,
             'features': {'speech_features': {'clinical_pattern_type': 'none_detected'}}}]
    assert ca._compute_voice_divergence(calm, _checkins()) == []


# ── P0 #1 — suicidality escalation consolidates across channels ───────────────
def test_suicidality_escalation_consolidates_and_folds_targets():
    esc = ca._compute_suicidality_escalation(
        [_crisis_session()], [], _HOPELESS_VT, _FOCUS, _checkins(), _engagement_gap())
    assert esc['signal_present'] is True
    assert 'suicidality' in esc['fold_targets'] and 'mood' in esc['fold_targets']
    flag = esc['consolidated_flag']
    assert flag.startswith('🔴')
    assert 'direct clinical check-in' in flag.lower()
    assert '2026-06-12' in flag
    # Per-date de-duplication: the voice date appears exactly once.
    assert flag.count('voice note 2026-06-12') == 1


def test_no_escalation_with_only_one_signal():
    # Calm, responsive (no gap); a suicidality/mood target configured with no
    # responses = exactly ONE signal. < 2 of 3 → must NOT escalate.
    calm = [{'session_date': '2026-06-12', 'processing_status': 'complete',
             'crisis_detected': False,
             'features': {'patient_mood_description': 'Steady week, feeling fine.',
                          'speech_features': {'clinical_pattern_type': 'none_detected'}}}]
    no_gap = {'max_consecutive_gap': 1, 'max_prompt_gap': 1, 'extended_no_response': False}
    esc = ca._compute_suicidality_escalation(calm, [], [], _FOCUS, _checkins(), no_gap)
    assert esc['signal_present'] is False


def test_escalation_fires_on_production_session_shape():
    # Regression for the live 06-19 miss: the hopeless note is a clinical SESSION,
    # so its text lives in features.patient_mood_description — NOT in
    # raw_voice_transcripts (the app excludes session-dated notes). crisis_detected
    # is False and the pattern is not 'depressive'. The session-content scan must
    # still catch the hopelessness signal.
    prod = [{'session_date': '2026-06-12', 'processing_status': 'complete',
             'crisis_detected': False,
             'features': {
                 'patient_mood_description': 'Overwhelmed, hopeless about job search, self-blaming.',
                 'themes': ['job search distress', 'self-blame'],
                 'clinical_pattern_type': 'none_detected',
                 'speech_features': {'prosody': 'flat', 'arousal': 'low'}}}]
    esc = ca._compute_suicidality_escalation(
        prod, [], [], _FOCUS, _checkins(), _engagement_gap())   # raw_voice_transcripts EMPTY
    assert esc['signal_present'] is True
    assert 'suicidality' in esc['fold_targets'] and 'mood' in esc['fold_targets']
    assert 'hopelessness language' in esc['consolidated_flag']
    assert 'direct clinical check-in' in esc['consolidated_flag'].lower()
    assert '2026-06-12' in esc['consolidated_flag']


def test_escalation_fires_on_gap_plus_targets_without_hopelessness():
    # Spec §22 is >= 2 of 3. Gap + two no-response targets = 2 signals even with no
    # hopelessness anywhere — an unanswered suicidality target through a silent
    # period is itself a convergent concern.
    calm = [{'session_date': '2026-06-12', 'processing_status': 'complete',
             'crisis_detected': False,
             'features': {'patient_mood_description': 'Busy week, nothing notable.',
                          'speech_features': {'clinical_pattern_type': 'none_detected'}}}]
    esc = ca._compute_suicidality_escalation(calm, [], [], _FOCUS, _checkins(), _engagement_gap())
    assert esc['signal_present'] is True
    assert set(esc['fold_targets']) == {'suicidality', 'mood'}
    assert 'direct clinical check-in' in esc['consolidated_flag'].lower()


# ── End-to-end through the real generate_psychiatry_summary path ──────────────
def test_brief_guards_against_dropped_consolidation_flag():
    """If the model omits the mandated flag, the post-generation guard prepends it."""
    original = ca._call_claude
    ca._call_claude = lambda system, user, max_tokens=2000: (
        "## Trajectory\nMood elevated, averages stable.\n\n"
        "## 🚨 Flags\n🟡 Monitoring target — Suicidality: no responses logged this "
        "period (active target; no data to assess).\n")
    try:
        res = ca.generate_psychiatry_summary(
            [{'date': '2026-06-04', 'mood_score': 9,  'stress_score': 2, 'sleep_hours': 6},
             {'date': '2026-06-06', 'mood_score': 9,  'stress_score': 2, 'sleep_hours': 6},
             {'date': '2026-06-08', 'mood_score': 10, 'stress_score': 1, 'sleep_hours': 6}],
            [], days=14, period_start='2026-06-04', period_end='2026-06-18',
            session_context=[_crisis_session()], raw_voice_transcripts=_HOPELESS_VT,
            engagement_data=_engagement_gap(), focus_config=_FOCUS)
    finally:
        ca._call_claude = original
    assert res['status'] == 'safe'
    text = res['text']
    assert 'direct clinical check-in' in text.lower()
    assert text.lstrip().startswith('🔴'), "consolidation flag must lead the brief"
    assert '2026-06-12' in text


# ── P1 #4 — trend labels must not overclaim below minimum-N ──────────────────
def test_trend_insufficient_data_below_min_n():
    # The 2026-06-18 brief: Crash Risk over 5 logged days, range 1.83–2.5, was
    # labeled "rising (unfavorable)". With < 7 observations it must abstain.
    crash = [1.83, 2.1, 2.2, 2.4, 2.5]
    assert ca._directional_trend(crash, favorable_is_high=False) == 'insufficient data'
    assert ca._directional_trend([8.8, 9.0, 9.5, 8.0, 7.75],
                                 favorable_is_high=True) == 'insufficient data'


def test_trend_stable_when_change_is_noise():
    # >= 7 observations but the modeled change across the window is trivial.
    flat = [5.0, 5.1, 4.9, 5.0, 5.1, 4.9, 5.0]
    assert ca._directional_trend(flat, favorable_is_high=True) == 'stable'
    assert ca._directional_trend(flat, favorable_is_high=False) == 'stable'


def test_trend_directions_when_supported():
    rising = [1.0, 1.5, 2.5, 3.0, 4.0, 5.0, 6.0]   # clear upward slope, 7 pts
    falling = list(reversed(rising))
    # Lower-is-better (Crash Risk / NS Load)
    assert ca._directional_trend(rising,  favorable_is_high=False) == 'rising (unfavorable)'
    assert ca._directional_trend(falling, favorable_is_high=False) == 'declining (favorable)'
    # Higher-is-better (Mood / Stability / Energy)
    assert ca._directional_trend(rising,  favorable_is_high=True) == 'improving'
    assert ca._directional_trend(falling, favorable_is_high=True) == 'declining'


def test_trend_ignores_noisy_endpoints():
    # Endpoint-only comparison (old bug) would call this 'improving' off v[0] vs
    # v[-1]; the slope over 7 mostly-flat points is below the noise band → stable.
    series = [5.0, 5.2, 5.0, 4.9, 5.1, 5.0, 5.2]
    assert ca._directional_trend(series, favorable_is_high=True) == 'stable'


# ── P1 #5 — date verifier must not false-flag voice-divergence sentences ──────
def test_verify_skips_voice_note_dates():
    # The live 06-19 footnote false-flagged these (voice dates 06-09/06-12 sit
    # next to "voice note"; the only check-in score is correctly tied to 06-08).
    text = ("Voice-note to check-in divergence — 2026-06-12 voice note (flat affect, "
            "low arousal) vs nearest check-in 2026-06-08 (mood 10/10, stability 9.5/10, "
            "4 days prior). 2026-06-09 voice note (flat affect, low arousal) vs nearest "
            "check-in 2026-06-08 (1 day prior, same elevated scores).")
    assert ca._verify_date_claims(text, ['2026-06-08']) == []


def test_verify_still_flags_bad_checkin_score_date():
    # A genuine hallucination: a check-in SCORE attributed to a dateless day.
    text = "Per the logs, check-in mood 9/10 on 2026-06-12 was the high point of the week."
    flagged = ca._verify_date_claims(text, ['2026-06-08'])
    assert any('2026-06-12' in f for f in flagged)


def test_verify_flags_bad_checkin_date_even_beside_a_voice_date():
    # Two dates in one sentence: a voice date (skip) and a bad check-in score date
    # (flag). The voice qualifier must not shield the unrelated check-in claim.
    text = ("Voice note 2026-06-09 preceded the check-in; per the record, check-in "
            "mood 8/10 was logged on 2026-06-13 during the window.")
    flagged = ca._verify_date_claims(text, ['2026-06-08'])
    assert any('2026-06-13' in f for f in flagged)


# ── Guard: the weak estimator must not return to any summary function ─────────
def test_no_endpoint_only_trend_estimator_remains():
    src = open(os.path.join(_REPO, 'claude_api.py'), encoding='utf-8').read()
    # The old first-vs-last comparison ('v[-1] > v[0]') had no N-gate or magnitude.
    assert 'v[-1] > v[0]' not in src, "endpoint-only trend estimator reintroduced"
    # Stress is lower-is-better; it must never run through the higher-is-better wrapper.
    assert '_trend(stress_vals)' not in src, "stress routed through higher-is-better _trend"


# ── Plain runner (no pytest dependency) ──────────────────────────────────────
if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failures = []
    for t in tests:
        try:
            t()
            print('PASS', t.__name__)
        except AssertionError as e:
            print('FAIL', t.__name__, '-', e)
            failures.append(t.__name__)
    print('\nRESULT:', 'ALL PASS' if not failures else f'{len(failures)} FAILED -> {failures}')
    sys.exit(1 if failures else 0)
