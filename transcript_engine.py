"""
transcript_engine.py — CognaSync Intelligence Layer

Extracts structured clinical features from session transcripts.

DESIGN PRINCIPLES:
  1. Crisis detection runs before any AI call. Always.
  2. Extraction is factual: what was mentioned, what signals were present.
     Clinical interpretation is the scoring engine's and the clinician's job.
  3. The extraction model never infers what was not said. Missing data is null,
     not zero. "Patient did not mention sleep" ≠ "Patient slept well."
  4. Speaker awareness: patient speech and provider speech are treated differently.
     Mood signals from provider speech ("you seem tired") are not patient self-report.
  5. All numbers in the output that were NOT explicitly stated by the patient
     are null. The only exception is computed scores produced by the deterministic
     scoring engine — those are always computed in Python, never by the model.

OUTPUT SCHEMA:
  extract_features() returns a dict with two top-level keys:
    - 'features': the raw extracted observations
    - 'scores':   deterministic scores computed from features
    - 'crisis_detected': bool (True means generation was blocked)
    - 'safety_note': str | None (provider-facing note when crisis_detected is True)

USAGE:
    result = extract_features(transcript_text, session_date='2026-05-26',
                               session_type='psychiatry')
    if result['crisis_detected']:
        # route to provider alert, do not generate standard brief
        pass
    else:
        # pass to generate_brief_from_sessions()
        pass
"""

import json
import logging
import os
import re

from claude_api import (
    _check_crisis, _call_claude, CRISIS_KEYWORDS,
    score_crisis, CRISIS_LEVEL_NOTES, CRISIS_LEVEL_LABELS,
)

logger = logging.getLogger(__name__)


# ── Extraction constants ────────────────────────────────────────────────────

EXTRACTION_MODEL = os.environ.get('CLAUDE_MODEL', 'claude-haiku-4-5-20251001')

# Maximum transcript length passed to the extraction call.
# Transcripts longer than this are chunked — the first and last portions
# carry the most clinically dense content in typical sessions.
MAX_TRANSCRIPT_CHARS = 12_000

# Speaker label patterns — handle common transcript formats
# "PATIENT:", "Patient:", "P:", "CLIENT:", "Client:", "C:"
_PATIENT_SPEAKER_RE = re.compile(
    r'^(?:PATIENT|Patient|patient|CLIENT|Client|client|P|C)\s*:',
    re.MULTILINE
)
_PROVIDER_SPEAKER_RE = re.compile(
    r'^(?:THERAPIST|Therapist|therapist|PSYCHIATRIST|Psychiatrist|psychiatrist'
    r'|PROVIDER|Provider|provider|DOCTOR|Doctor|doctor|DR\.|Dr\.|T|TH)\s*:',
    re.MULTILINE
)


# ── Extraction prompt ───────────────────────────────────────────────────────

_EXTRACTION_SYSTEM = """You are a clinical data extraction tool. Your job is to read a session transcript and extract structured observations — not interpretations.

ROLE: You identify what was explicitly said or described. You do not infer clinical meaning. You do not diagnose. You do not assess whether something is "concerning" or "improving" in a clinical sense. You describe what was present.

OUTPUT: Return only valid JSON matching the schema below. No other text.

EXTRACTION RULES:
- Only extract what was explicitly stated by the patient or clearly observable in their language.
- If the patient did not mention something, the field is null. Absence ≠ zero.
- mood_estimate and energy_estimate are ONLY populated when the patient named a number (e.g. "I'm about a 5 out of 10"). Otherwise null.
- Do not interpret the provider's observations as patient self-report. If the provider says "you seem tired," that is not a patient energy self-report.
- themes are topics the patient raised or spent time on — not your characterization of what those topics represent.
- concerning_language is verbatim phrases (or very close paraphrases) that suggest distress, not your assessment of their significance.
- crisis_language_detected should be true ONLY if the transcript contains explicit statements about self-harm, suicide, or wanting to die.
- session_notes is a single factual sentence describing the session's primary focus and the patient's level of engagement. No interpretation.

SPEECH AND BEHAVIORAL FEATURES:
Populate speech_features based on observable characteristics of the patient's utterances in the transcript. You are reading text, so infer from length of responses, interruptions, ellipses, stage directions, and the nature of the language used.

- speech_rate: "slowed" if responses are brief, hesitant, or the transcript notes long pauses; "pressured" if the patient produces long uninterrupted runs of text, interrupts, or the transcript notes rapid speech; "normal" otherwise; null if insufficient data.
- prosody: "flat" if emotional affect appears diminished (short affect-free responses, minimal variation); "elevated" if emotion is notably heightened or intense; "normal" otherwise; null if insufficient data.
- pauses: "increased" if ellipses, [pause] markers, or very short fragmented responses appear; "decreased" if speech is continuous and unbroken; "normal" otherwise; null if insufficient data.
- speech_coherence: "disorganized" if speech jumps between unrelated topics, is hard to follow, or contains loose associations; "intact" otherwise; null if insufficient.
- arousal: "low" if patient seems subdued, minimally responsive, flat; "elevated" if patient is animated, excitable; "agitated" if irritable or dysregulated; "normal" otherwise; null if insufficient.
- vocal_affect: "flat" if emotional expression is minimal across the session; "strained" if the patient seems to be struggling to express themselves; "normal" otherwise; null if insufficient.
- severity_note: One brief factual observation about the most notable speech or engagement characteristic. Example: "Responses were notably brief and affect appeared flat throughout." Null if nothing stands out.
- confidence: "high" if clear evidence supports the labels; "medium" if partially visible; "low" if the transcript has minimal content to assess.

BASELINE DEVIATION:
If the transcript or notes contain any reference to how the patient "usually" presents, how today compares to prior sessions, or the provider notes a change — populate baseline_deviation with one sentence. Example: "Provider noted the patient was quieter than usual." Null if no baseline comparison is available.

CLINICAL PATTERN TYPE:
Assign the single best-matching pattern for the session. Choose from:
- "depressive": low energy, withdrawal, flat speech, sleep disruption, hopelessness dominate
- "anxiety_stress": heightened arousal, restlessness, worry, physical tension themes dominate
- "mania_hypomania": pressured speech, elevated arousal, reduced sleep need, impulsive themes, expansive mood
- "psychosis_risk": disorganized speech, unusual beliefs, perceptual disturbances, marked functional decline
- "crisis": active self-harm or suicidal themes dominate the session
- "mixed": two or more patterns are clearly present and neither dominates
- "none_detected": signals present do not clearly match any pattern
- null: insufficient transcript content to assess

Apply conservatively — use "none_detected" or null when uncertain rather than over-assigning. This is a routing label for providers, not a diagnosis.

JSON SCHEMA:
{
  "patient_mood_description": string or null,
  "mood_estimate": number (1-10) or null,
  "energy_description": string or null,
  "energy_estimate": number (1-10) or null,
  "sleep_hours_mentioned": number or null,
  "sleep_quality_description": string or null,
  "stress_description": string or null,
  "themes": [string],
  "medications_mentioned": [
    {
      "name": string,
      "dose_mentioned": string or null,
      "context": string,
      "adherence_signal": "taking" | "not_taking" | "sporadic" | "side_effect_mentioned" | "unknown"
    }
  ],
  "symptoms_mentioned": [string],
  "stressors": [string],
  "positive_signals": [string],
  "concerning_language": [string],
  "crisis_language_detected": boolean,
  "functional_status": string or null,
  "session_notes": string,
  "speech_features": {
    "speech_rate": "normal" | "slowed" | "pressured" | null,
    "prosody": "normal" | "flat" | "elevated" | null,
    "pauses": "normal" | "increased" | "decreased" | null,
    "speech_coherence": "intact" | "disorganized" | null,
    "arousal": "normal" | "low" | "elevated" | "agitated" | null,
    "vocal_affect": "normal" | "flat" | "strained" | null,
    "severity_note": string or null,
    "confidence": "high" | "medium" | "low"
  },
  "clinical_pattern_type": "depressive" | "anxiety_stress" | "mania_hypomania" | "psychosis_risk" | "crisis" | "mixed" | "none_detected" | null,
  "baseline_deviation": string or null
}"""


def _trim_transcript(text: str) -> str:
    """
    Trim a long transcript for extraction.
    Keeps the first 8000 chars and last 4000 chars, with a gap marker.
    Clinical density is typically highest at the opening and close of sessions.
    """
    if len(text) <= MAX_TRANSCRIPT_CHARS:
        return text
    head = text[:8_000]
    tail = text[-4_000:]
    return (
        head
        + "\n\n[--- transcript trimmed for length ---]\n\n"
        + tail
    )


def _parse_extraction_response(raw: str) -> dict | None:
    """Parse the model's JSON response. Returns None on parse failure."""
    try:
        # Strip markdown code fences if present
        clean = raw.strip()
        if clean.startswith("```"):
            clean = re.sub(r'^```(?:json)?\n?', '', clean)
            clean = re.sub(r'\n?```$', '', clean)
        return json.loads(clean)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error("Extraction JSON parse failure: %s — raw: %s", e, raw[:200])
        return None


def _compute_transcript_scores(features: dict) -> dict:
    """
    Compute deterministic scores from extracted transcript features.

    These follow the same logic as _compute_checkin_scores() in database.py
    but work from transcript-derived signals rather than self-report fields.
    All scores that cannot be computed from available data are None.

    The AI never computes these scores. This function runs in Python.
    """
    scores = {}

    # ── Mood estimate ──────────────────────────────────────────────
    # Only set when the patient named a number. Never inferred.
    scores['mood_estimate'] = features.get('mood_estimate')

    # ── Energy estimate ────────────────────────────────────────────
    scores['energy_estimate'] = features.get('energy_estimate')

    # ── Sleep disruption proxy ─────────────────────────────────────
    # Computed from sleep_hours_mentioned. Only if mentioned.
    sleep = features.get('sleep_hours_mentioned')
    if sleep is not None:
        sd = 0
        if float(sleep) < 6:
            sd += 2
        if float(sleep) < 4:
            sd += 2  # additional penalty for very short sleep
        scores['sleep_disruption_proxy'] = min(sd, 10)
        scores['sleep_hours'] = float(sleep)
    else:
        scores['sleep_disruption_proxy'] = None
        scores['sleep_hours'] = None

    # ── Stressor load ──────────────────────────────────────────────
    # Count of distinct stressors mentioned. Not a clinical score —
    # reported as a count, not normalized.
    stressors = features.get('stressors') or []
    scores['stressor_count'] = len(stressors)

    # ── Medication adherence signal ────────────────────────────────
    meds = features.get('medications_mentioned') or []
    taking_count     = sum(1 for m in meds if m.get('adherence_signal') == 'taking')
    not_taking_count = sum(1 for m in meds if m.get('adherence_signal') == 'not_taking')
    sporadic_count   = sum(1 for m in meds if m.get('adherence_signal') == 'sporadic')
    side_effect_count = sum(1 for m in meds if m.get('adherence_signal') == 'side_effect_mentioned')
    total_meds_mentioned = len(meds)

    if total_meds_mentioned > 0:
        scores['medication_signal'] = {
            'total_mentioned':    total_meds_mentioned,
            'taking':             taking_count,
            'not_taking':         not_taking_count,
            'sporadic':           sporadic_count,
            'side_effect_flags':  side_effect_count,
        }
    else:
        scores['medication_signal'] = None

    # ── Symptom count ──────────────────────────────────────────────
    symptoms = features.get('symptoms_mentioned') or []
    scores['symptom_count'] = len(symptoms)

    # ── Speech features — pass through from extraction ────────────────
    # These are qualitative labels extracted by the model. Pass through as-is;
    # the scoring engine does not normalize them. Provider brief uses them directly.
    speech = features.get('speech_features')
    if speech and isinstance(speech, dict):
        scores['speech_features'] = speech
        # Derive a simple speech concern flag (True if any abnormal label present)
        abnormal_markers = [
            speech.get('speech_rate') in ('slowed', 'pressured'),
            speech.get('prosody') == 'flat',
            speech.get('pauses') == 'increased',
            speech.get('speech_coherence') == 'disorganized',
            speech.get('arousal') in ('low', 'elevated', 'agitated'),
            speech.get('vocal_affect') in ('flat', 'strained'),
        ]
        scores['speech_concern_flag'] = any(abnormal_markers)
    else:
        scores['speech_features'] = None
        scores['speech_concern_flag'] = False

    # ── Clinical pattern type — pass through from extraction ──────────
    scores['clinical_pattern_type'] = features.get('clinical_pattern_type')

    # ── Baseline deviation — pass through from extraction ─────────────
    scores['baseline_deviation'] = features.get('baseline_deviation')

    # ── Session signal quality ─────────────────────────────────────────
    # A rough proxy for how data-rich this session's extraction was.
    # Not a clinical score — used internally to weight brief generation.
    richness = 0
    if features.get('mood_estimate') is not None:         richness += 2
    if features.get('patient_mood_description'):          richness += 1
    if features.get('sleep_hours_mentioned') is not None: richness += 2
    if features.get('themes'):                            richness += len(features['themes'])
    if meds:                                              richness += 2
    if features.get('positive_signals'):                  richness += 1
    if speech and speech.get('confidence') == 'high':     richness += 1
    scores['extraction_richness'] = richness

    return scores


def _build_safety_note(crisis_result: dict) -> str:
    """
    Build the provider-facing safety note from a graduated crisis result.
    This note goes into the provider_brief as the highest-priority flag.
    It never goes to the patient.

    Args:
        crisis_result: Dict returned by score_crisis() with 'level', 'score',
                       'adjusted_score', 'features', and 'population_modifier'.
    """
    level = crisis_result.get('level', 3)
    score = crisis_result.get('adjusted_score', 0)
    features = crisis_result.get('features', {})
    pop_mod  = crisis_result.get('population_modifier', 0)

    # Collect which high-weight features were detected for the note
    high_weight = [
        f for f in ('direct_intent', 'specific_plan', 'means_access',
                    'recent_self_harm', 'preparatory_behavior')
        if features.get(f)
    ]
    passive_weight = [
        f for f in ('recurrent_ideation', 'cannot_safety_plan',
                    'hopelessness', 'worsening_distress')
        if features.get(f)
    ]

    feature_summary = ''
    if high_weight:
        readable = {
            'direct_intent': 'direct intent',
            'specific_plan': 'specific plan',
            'means_access': 'means access',
            'recent_self_harm': 'prior self-harm reference',
            'preparatory_behavior': 'preparatory behavior',
        }
        feature_summary = ' Signals detected: ' + ', '.join(
            readable.get(f, f) for f in high_weight
        ) + '.'
    elif passive_weight:
        readable = {
            'recurrent_ideation': 'recurrent ideation',
            'cannot_safety_plan': 'safety planning difficulty',
            'hopelessness': 'hopelessness',
            'worsening_distress': 'worsening distress',
        }
        feature_summary = ' Signals detected: ' + ', '.join(
            readable.get(f, f) for f in passive_weight
        ) + '.'

    pop_note = ''
    if pop_mod > 0:
        pop_note = f' Population modifier applied (+{pop_mod}).'

    base_note = CRISIS_LEVEL_NOTES.get(level, CRISIS_LEVEL_NOTES[3])
    return (
        f"{base_note}"
        f"{feature_summary}"
        f"{pop_note}"
        f" Risk score: {score}/14. Standard brief generation was blocked."
    )


# ── Public API ──────────────────────────────────────────────────────────────

def extract_features(
    transcript_text: str,
    session_date: str | None = None,
    session_type: str = 'therapy',
    population_flags: dict | None = None,
) -> dict:
    """
    Primary extraction function. Safe to call from any route.

    Args:
        transcript_text:  Raw transcript as a string. May be formatted with
                          speaker labels ("PATIENT: ...", "T: ...") or plain text.
        session_date:     ISO date string (YYYY-MM-DD). Passed through to output
                          for downstream brief generation.
        session_type:     'psychiatry' | 'therapy' | 'intake' | 'followup' | 'other'
        population_flags: Optional {population_name: bool} for graduated crisis scoring.
                          Valid keys: 'adolescent', 'older_adult', 'veteran',
                          'prior_self_harm', 'serious_mental_illness'

    Returns:
        {
            'crisis_detected':  bool,
            'crisis_level':     int (0-4),   # 0 = none, 4 = imminent
            'crisis_result':    dict | None, # full score_crisis() output
            'safety_note':      str | None,  # provider-only, never patient-facing
            'features':         dict | None, # None if Level 3-4 blocked extraction
            'scores':           dict | None,
            'session_date':     str | None,
            'session_type':     str,
            'transcript_length': int,
        }
    """
    if not transcript_text or not isinstance(transcript_text, str):
        return {
            'crisis_detected':   False,
            'crisis_level':      0,
            'crisis_result':     None,
            'safety_note':       None,
            'features':          None,
            'scores':            None,
            'session_date':      session_date,
            'session_type':      session_type,
            'transcript_length': 0,
            'error':             'Empty or invalid transcript',
        }

    # ── Step 1: Graduated crisis scoring — always runs before AI call ──────
    # score_crisis() uses the weighted 5-level system from spec §22.
    # Level 3-4: block extraction, return provider-only safety note.
    # Level 1-2: allow extraction to continue; include crisis info in output
    #            so the provider brief can surface appropriate flags.
    crisis_result = score_crisis(transcript_text, population_flags=population_flags)
    crisis_level  = crisis_result['level']

    if crisis_level >= 3:
        logger.warning(
            "Crisis language detected at Level %d (score=%d) in transcript "
            "(session_date=%s, session_type=%s). Extraction blocked.",
            crisis_level, crisis_result['adjusted_score'], session_date, session_type
        )
        return {
            'crisis_detected':   True,
            'crisis_level':      crisis_level,
            'crisis_result':     crisis_result,
            'safety_note':       _build_safety_note(crisis_result),
            'features':          None,
            'scores':            None,
            'session_date':      session_date,
            'session_type':      session_type,
            'transcript_length': len(transcript_text),
        }

    # ── Step 2: Trim transcript if needed ──────────────────────────────────
    trimmed = _trim_transcript(transcript_text)

    # ── Step 3: Structured extraction call ─────────────────────────────────
    user_content = (
        f"Session type: {session_type}\n"
        f"Session date: {session_date or 'not specified'}\n\n"
        f"TRANSCRIPT:\n{trimmed}"
    )

    try:
        raw_response = _call_claude(
            system_prompt=_EXTRACTION_SYSTEM,
            user_content=user_content,
            max_tokens=1_200,
        )
    except RuntimeError as e:
        logger.error("Extraction Claude call failed: %s", e)
        return {
            'crisis_detected':   False,
            'safety_note':       None,
            'features':          None,
            'scores':            None,
            'session_date':      session_date,
            'session_type':      session_type,
            'transcript_length': len(transcript_text),
            'error':             f'Extraction API error: {str(e)}',
        }

    # ── Step 4: Parse response ─────────────────────────────────────────────
    features = _parse_extraction_response(raw_response)
    if features is None:
        return {
            'crisis_detected':   False,
            'safety_note':       None,
            'features':          None,
            'scores':            None,
            'session_date':      session_date,
            'session_type':      session_type,
            'transcript_length': len(transcript_text),
            'error':             'Extraction response could not be parsed',
        }

    # ── Step 5: Secondary crisis check on extracted concerning_language ─────
    # Belt-and-suspenders: re-score against the concerning_language phrases
    # the model surfaced. Uses score_crisis() for consistency with Step 1.
    concerning = features.get('concerning_language') or []
    secondary_crisis = None
    if features.get('crisis_language_detected') and not concerning:
        # Model flagged crisis but we don't have phrases — treat as Level 3
        secondary_crisis = {'level': 3, 'score': 6, 'adjusted_score': 6,
                            'features': {}, 'population_modifier': 0}
    elif concerning:
        combined_text = ' '.join(concerning)
        secondary_crisis = score_crisis(combined_text, population_flags=population_flags)

    # If secondary check upgrades us to Level 3+, block brief generation
    if secondary_crisis and secondary_crisis['level'] >= 3:
        # Merge the two results — take the higher-scored one
        effective_crisis = (
            secondary_crisis
            if secondary_crisis['adjusted_score'] > crisis_result['adjusted_score']
            else crisis_result
        )
        effective_crisis['level'] = max(effective_crisis['level'], 3)
        logger.warning(
            "Secondary crisis check elevated level to %d (session_date=%s). "
            "Brief generation blocked.",
            effective_crisis['level'], session_date
        )
        return {
            'crisis_detected':   True,
            'crisis_level':      effective_crisis['level'],
            'crisis_result':     effective_crisis,
            'safety_note':       _build_safety_note(effective_crisis),
            'features':          features,   # features preserved for provider review
            'scores':            None,
            'session_date':      session_date,
            'session_type':      session_type,
            'transcript_length': len(transcript_text),
        }

    # ── Step 6: Deterministic scoring ─────────────────────────────────────
    scores = _compute_transcript_scores(features)

    # If Level 1-2 signals were detected, include them as non-blocking context
    # for the provider brief. crisis_detected stays False — extraction proceeds.
    passive_safety_note = None
    effective_level = crisis_level
    if secondary_crisis and secondary_crisis['level'] > crisis_level:
        effective_level = secondary_crisis['level']
    if effective_level in (1, 2):
        passive_safety_note = CRISIS_LEVEL_NOTES[effective_level]

    return {
        'crisis_detected':   False,
        'crisis_level':      effective_level,
        'crisis_result':     crisis_result,
        'safety_note':       passive_safety_note,   # non-None but non-blocking for Level 1-2
        'features':          features,
        'scores':            scores,
        'session_date':      session_date,
        'session_type':      session_type,
        'transcript_length': len(transcript_text),
    }


def extract_patient_speech(transcript_text: str) -> str:
    """
    Extract only the patient's lines from a labeled transcript.
    Returns the patient speech as a single block of text.
    Falls back to the full transcript if no speaker labels are detected.

    Useful for passing patient-only text to the crisis detector
    and for computing word count / engagement metrics.
    """
    lines = transcript_text.split('\n')
    patient_lines = []
    current_speaker_is_patient = False

    for line in lines:
        if _PATIENT_SPEAKER_RE.match(line):
            current_speaker_is_patient = True
            # Strip the speaker label
            text = _PATIENT_SPEAKER_RE.sub('', line).strip()
            if text:
                patient_lines.append(text)
        elif _PROVIDER_SPEAKER_RE.match(line):
            current_speaker_is_patient = False
        elif current_speaker_is_patient and line.strip():
            # Continuation of patient's last turn
            patient_lines.append(line.strip())

    if not patient_lines:
        # No speaker labels detected — return full transcript
        return transcript_text

    return '\n'.join(patient_lines)


def score_transcript_batch(
    session_results: list[dict],
) -> dict:
    """
    Aggregate scores across multiple session extraction results.
    Used by generate_brief_from_sessions() to build the period-level
    quantitative summary for Mode C.

    Args:
        session_results: List of dicts returned by extract_features().

    Returns:
        {
            'session_count': int,
            'sessions_with_mood': int,
            'mood_avg': float | None,
            'mood_estimates': [float],
            'sleep_avg': float | None,
            'sleep_hours_series': [float],
            'sleep_disruption_avg': float | None,
            'stressor_count_total': int,
            'stressor_count_avg': float | None,
            'medication_signals': [...],  # one per session that had meds
            'symptom_mentions': Counter,  # symptom → count across sessions
            'crisis_sessions': int,
            'themes_aggregate': [str],    # all themes, deduplicated
        }
    """
    from collections import Counter

    valid_sessions = [
        r for r in session_results
        if not r.get('error') and r.get('features') is not None
    ]

    mood_estimates    = []
    sleep_series      = []
    sleep_disruptions = []
    stressor_counts   = []
    all_med_signals   = []
    all_symptoms      = Counter()
    all_themes        = []
    crisis_count      = sum(1 for r in session_results if r.get('crisis_detected'))

    # Speech and pattern aggregation
    clinical_patterns: Counter = Counter()
    speech_concern_sessions = 0
    speech_features_list    = []
    passive_flags_by_level  = {1: 0, 2: 0}  # count of sessions at each passive level

    for result in valid_sessions:
        scores   = result.get('scores') or {}
        features = result.get('features') or {}

        if scores.get('mood_estimate') is not None:
            mood_estimates.append(float(scores['mood_estimate']))
        if scores.get('sleep_hours') is not None:
            sleep_series.append(float(scores['sleep_hours']))
        if scores.get('sleep_disruption_proxy') is not None:
            sleep_disruptions.append(float(scores['sleep_disruption_proxy']))
        if scores.get('stressor_count') is not None:
            stressor_counts.append(int(scores['stressor_count']))
        if scores.get('medication_signal'):
            all_med_signals.append({
                'session_date': result.get('session_date'),
                **scores['medication_signal']
            })
        for sym in (features.get('symptoms_mentioned') or []):
            all_symptoms[sym.lower()] += 1
        for theme in (features.get('themes') or []):
            if theme not in all_themes:
                all_themes.append(theme)

        # Clinical pattern aggregation
        pattern = scores.get('clinical_pattern_type')
        if pattern and pattern not in ('none_detected', None):
            clinical_patterns[pattern] += 1

        # Speech concern aggregation
        if scores.get('speech_concern_flag'):
            speech_concern_sessions += 1
            sf = scores.get('speech_features')
            if sf:
                speech_features_list.append({
                    'session_date': result.get('session_date'),
                    **sf,
                })

        # Passive crisis level count (Level 1-2 non-blocking sessions)
        level = result.get('crisis_level', 0)
        if level in (1, 2):
            passive_flags_by_level[level] += 1

    def _avg(lst):
        return round(sum(lst) / len(lst), 1) if lst else None

    return {
        'session_count':          len(session_results),
        'valid_session_count':    len(valid_sessions),
        'crisis_sessions':        crisis_count,
        'sessions_with_mood':     len(mood_estimates),
        'mood_avg':               _avg(mood_estimates),
        'mood_estimates':         mood_estimates,
        'sleep_avg':              _avg(sleep_series),
        'sleep_hours_series':     sleep_series,
        'sleep_disruption_avg':   _avg(sleep_disruptions),
        'stressor_count_total':   sum(stressor_counts),
        'stressor_count_avg':     _avg(stressor_counts),
        'medication_signals':     all_med_signals,
        'symptom_mentions':       dict(all_symptoms),
        'themes_aggregate':       all_themes,
        # Speech and pattern
        'clinical_pattern_counts':    dict(clinical_patterns),
        'dominant_pattern':           clinical_patterns.most_common(1)[0][0] if clinical_patterns else None,
        'speech_concern_sessions':    speech_concern_sessions,
        'speech_features_by_session': speech_features_list,
        # Passive crisis signals (non-blocking but provider-relevant)
        'passive_crisis_level_1_sessions': passive_flags_by_level[1],
        'passive_crisis_level_2_sessions': passive_flags_by_level[2],
    }
