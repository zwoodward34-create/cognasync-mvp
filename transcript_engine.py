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
- speech_coherence: "disorganized" if speech jumps between unrelated topics, is hard to follow, or contains loose associations. Default to "intact" for any session where the conversation is followable, even if brief. Only use null when the patient has fewer than 5 utterances total and you genuinely cannot assess coherence.
- arousal: "low" if patient seems subdued, minimally responsive, flat; "elevated" if patient is animated, excitable; "agitated" if irritable or dysregulated; "normal" otherwise; null if insufficient.
- vocal_affect: "flat" if emotional expression is minimal across the session; "strained" if the patient seems to be struggling to express themselves; "normal" otherwise; null if insufficient.
- severity_note: One brief factual observation about the most notable speech or engagement characteristic. Example: "Responses were notably brief and affect appeared flat throughout." Null if nothing stands out.
- confidence: "high" if clear evidence supports the labels; "medium" if partially visible; "low" if the transcript has minimal content to assess.

BASELINE DEVIATION:
Populate baseline_deviation if (a) an ACOUSTIC BASELINE COMPARISON block is present in the context — use it to write one sentence describing how today's speech features compared to the patient's established acoustic baseline, in plain language (e.g., "Articulation rate was notably slower than this patient's baseline and pitch variability was reduced.") — or (b) the transcript or notes contain any reference to how the patient "usually" presents or how today compares to prior sessions. If neither source is available, set to null.

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

    NOTE: This function is retained for backward compatibility but is no longer
    called in the main extract_features() path. Long transcripts are now handled
    by _split_transcript_into_chunks() + _merge_chunk_features().
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


def _split_transcript_into_chunks(
    text: str,
    chunk_size: int = MAX_TRANSCRIPT_CHARS,
    overlap: int = 500,
) -> list[str]:
    """
    Split a transcript into overlapping chunks of at most chunk_size chars.

    Splits at newline boundaries when possible to avoid breaking mid-utterance.
    Returns a list of chunk strings. Capped at 8 chunks for very long transcripts.
    Never returns an empty list — if text is short, returns [text].

    Args:
        text:       Full transcript text.
        chunk_size: Maximum chars per chunk (default: MAX_TRANSCRIPT_CHARS).
        overlap:    Chars of overlap between adjacent chunks (default: 500).
    """
    if not text:
        return [text]
    if len(text) <= chunk_size:
        return [text]

    MAX_CHUNKS = 8
    chunks: list[str] = []
    pos = 0
    total = len(text)

    while pos < total:
        end = min(pos + chunk_size, total)

        # If not at end of text, try to split at a newline boundary
        # within the last 200 chars of the chunk window.
        if end < total:
            search_start = max(pos, end - 200)
            last_newline = text.rfind('\n', search_start, end)
            if last_newline != -1:
                end = last_newline + 1  # include the newline in this chunk

        chunks.append(text[pos:end])

        if end >= total:
            break

        # Next chunk starts with `overlap` chars of context from the previous chunk
        next_pos = end - overlap
        # Guard: always advance to avoid infinite loop
        if next_pos <= pos:
            next_pos = pos + 1
        pos = next_pos

        # Cap at MAX_CHUNKS — if we'd exceed it, make the last chunk cover the rest
        if len(chunks) >= MAX_CHUNKS - 1:
            remaining = text[pos:]
            if remaining:
                chunks.append(remaining)
            break

    return chunks if chunks else [text]


def _extract_single_chunk(
    chunk_text: str,
    session_type: str,
    session_date: str | None,
    assemblyai_hints: dict | None = None,
    acoustic_baseline_context: str | None = None,
) -> dict | None:
    """
    Run a single extraction call for one transcript chunk.

    Mirrors the user_content construction and _call_claude() invocation from
    extract_features(), but operates on a single chunk. Crisis detection is
    intentionally omitted — it already ran on the full transcript before chunking.

    Returns the parsed features dict (the JSON object from the model response),
    or None on parse failure or API error.
    """
    hints_block = _format_assemblyai_hints(assemblyai_hints)
    baseline_block = (
        f"\n\nACOUSTIC BASELINE COMPARISON:\n{acoustic_baseline_context}"
        if acoustic_baseline_context
        else ''
    )
    user_content = (
        f"Session type: {session_type}\n"
        f"Session date: {session_date or 'not specified'}\n\n"
        f"TRANSCRIPT:\n{chunk_text}"
        + baseline_block
        + (hints_block or '')
    )

    try:
        raw_response = _call_claude(
            system_prompt=_EXTRACTION_SYSTEM,
            user_content=user_content,
            max_tokens=1_200,
        )
    except RuntimeError as e:
        logger.error("Chunk extraction Claude call failed: %s", e)
        return None

    return _parse_extraction_response(raw_response)


def _merge_chunk_features(chunks: list[dict]) -> dict:
    """
    Merge a list of per-chunk extracted feature dicts into a single features dict.

    Merge rules:
    - medications_mentioned: union deduplicated on name (case-insensitive)
    - symptoms_mentioned:    union deduplicated (case-insensitive)
    - topics_discussed:      union deduplicated (case-insensitive)
    - patient_quotes:        concatenate all (quotes are unique per chunk)
    - speech_features:       take first chunk's value (opening carries richest signal)
    - clinical_pattern_type: take highest-priority value across all chunks
      Priority: crisis > psychosis_risk > mania_hypomania > anxiety_stress >
                depressive > mixed > none_detected > None
    - baseline_deviation:    take first non-None value
    - all other scalar fields: take first non-None value across chunks

    Returns {} if chunks is empty.
    """
    if not chunks:
        return {}

    _PATTERN_PRIORITY = {
        'crisis':           7,
        'psychosis_risk':   6,
        'mania_hypomania':  5,
        'anxiety_stress':   4,
        'depressive':       3,
        'mixed':            2,
        'none_detected':    1,
        None:               0,
    }

    merged: dict = {}

    # ── List fields that union-deduplicate ─────────────────────────────────
    # medications_mentioned: deduplicate by name (case-insensitive), keep first occurrence
    all_meds: list[dict] = []
    seen_med_names: set[str] = set()
    for chunk in chunks:
        for med in (chunk.get('medications_mentioned') or []):
            key = (med.get('name') or '').lower().strip()
            if key and key not in seen_med_names:
                seen_med_names.add(key)
                all_meds.append(med)
    merged['medications_mentioned'] = all_meds

    # symptoms_mentioned: string list, deduplicate case-insensitively
    all_symptoms: list[str] = []
    seen_symptoms: set[str] = set()
    for chunk in chunks:
        for sym in (chunk.get('symptoms_mentioned') or []):
            key = sym.lower().strip()
            if key and key not in seen_symptoms:
                seen_symptoms.add(key)
                all_symptoms.append(sym)
    merged['symptoms_mentioned'] = all_symptoms

    # topics_discussed: string list, deduplicate case-insensitively
    all_topics: list[str] = []
    seen_topics: set[str] = set()
    for chunk in chunks:
        for topic in (chunk.get('topics_discussed') or []):
            key = topic.lower().strip()
            if key and key not in seen_topics:
                seen_topics.add(key)
                all_topics.append(topic)
    merged['topics_discussed'] = all_topics

    # themes: same dedup treatment (extraction schema uses "themes")
    all_themes: list[str] = []
    seen_themes: set[str] = set()
    for chunk in chunks:
        for theme in (chunk.get('themes') or []):
            key = theme.lower().strip()
            if key and key not in seen_themes:
                seen_themes.add(key)
                all_themes.append(theme)
    merged['themes'] = all_themes

    # patient_quotes: concatenate all (no dedup — each is unique in context)
    all_quotes: list[str] = []
    for chunk in chunks:
        all_quotes.extend(chunk.get('patient_quotes') or [])
    merged['patient_quotes'] = all_quotes

    # stressors: union deduplicate
    all_stressors: list[str] = []
    seen_stressors: set[str] = set()
    for chunk in chunks:
        for s in (chunk.get('stressors') or []):
            key = s.lower().strip()
            if key and key not in seen_stressors:
                seen_stressors.add(key)
                all_stressors.append(s)
    merged['stressors'] = all_stressors

    # positive_signals: union deduplicate
    all_pos: list[str] = []
    seen_pos: set[str] = set()
    for chunk in chunks:
        for p in (chunk.get('positive_signals') or []):
            key = p.lower().strip()
            if key and key not in seen_pos:
                seen_pos.add(key)
                all_pos.append(p)
    merged['positive_signals'] = all_pos

    # concerning_language: union deduplicate
    all_concern: list[str] = []
    seen_concern: set[str] = set()
    for chunk in chunks:
        for c in (chunk.get('concerning_language') or []):
            key = c.lower().strip()
            if key and key not in seen_concern:
                seen_concern.add(key)
                all_concern.append(c)
    merged['concerning_language'] = all_concern

    # ── Special scalar fields ───────────────────────────────────────────────

    # speech_features: first chunk's value (opening of session)
    merged['speech_features'] = chunks[0].get('speech_features')

    # clinical_pattern_type: highest priority across all chunks
    best_pattern = None
    best_priority = -1
    for chunk in chunks:
        p = chunk.get('clinical_pattern_type')
        priority = _PATTERN_PRIORITY.get(p, 0)
        if priority > best_priority:
            best_priority = priority
            best_pattern = p
    merged['clinical_pattern_type'] = best_pattern

    # baseline_deviation: first non-None value
    merged['baseline_deviation'] = None
    for chunk in chunks:
        val = chunk.get('baseline_deviation')
        if val is not None:
            merged['baseline_deviation'] = val
            break

    # crisis_language_detected: OR across all chunks — NEVER first-non-None.
    # A transcript where crisis language appears only in a later chunk must
    # still flag the merged session (a chunk reporting False is non-None and
    # would otherwise mask a later True).
    merged['crisis_language_detected'] = any(
        bool(chunk.get('crisis_language_detected')) for chunk in chunks
    )

    # ── Scalar fields: first non-None value across chunks ──────────────────
    scalar_fields = [
        'patient_mood_description',
        'mood_estimate',
        'energy_description',
        'energy_estimate',
        'sleep_hours_mentioned',
        'sleep_quality_description',
        'stress_description',
        'functional_status',
        'session_notes',
    ]
    for field in scalar_fields:
        if field in merged:
            continue  # already set above
        merged[field] = None
        for chunk in chunks:
            val = chunk.get(field)
            if val is not None:
                merged[field] = val
                break

    return merged


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

def _format_assemblyai_hints(hints: dict) -> str | None:
    """
    Convert AssemblyAI enrichment data (entities, highlights, sentiment) into a
    structured supplemental block appended to user_content when ASSEMBLYAI_ENHANCED
    is active.  Gives Haiku named-entity anchors and highlight keyphrases so the
    extraction picks up medication names and key topics without hallucinating them.

    Returns None when all three hint lists are empty (free-tier path).
    """
    if not hints:
        return None

    entities   = hints.get('entities') or []
    highlights = hints.get('auto_highlights') or []
    sentiments = hints.get('sentiment_results') or []

    if not (entities or highlights or sentiments):
        return None

    lines = ['\n\n--- ASSEMBLYAI ENRICHMENT (supplemental context; do not quote verbatim) ---']

    if entities:
        # Deduplicate by (text, entity_type); keep only clinically useful types
        seen = set()
        useful_types = {'medication', 'medical_process', 'medical_condition',
                        'person', 'organization', 'date', 'time', 'number'}
        for e in entities:
            key = (e.get('text', '').lower(), e.get('entity_type', ''))
            if key not in seen and e.get('entity_type', '').lower() in useful_types:
                seen.add(key)
        if seen:
            lines.append('Detected entities (type: text):')
            for text, etype in sorted(seen):
                lines.append(f'  {etype}: {text}')

    if highlights:
        # Top-8 by count; keyphrases worth surfacing as session themes
        sorted_hl = sorted(highlights, key=lambda h: h.get('count', 0), reverse=True)[:8]
        lines.append('Key phrases (frequency-ranked): ' +
                     ', '.join(h.get('text', '') for h in sorted_hl if h.get('text')))

    if sentiments:
        # Summarise overall sentiment distribution — useful for affect_model corroboration
        from collections import Counter
        dist = Counter(s.get('sentiment', '') for s in sentiments)
        total = sum(dist.values()) or 1
        parts = [f"{k}: {v/total:.0%}" for k, v in dist.most_common() if k]
        if parts:
            lines.append('Sentence-level sentiment distribution: ' + ', '.join(parts))

    lines.append('--- END ENRICHMENT ---')
    return '\n'.join(lines)


def extract_features(
    transcript_text: str,
    session_date: str | None = None,
    session_type: str = 'therapy',
    population_flags: dict | None = None,
    assemblyai_hints: dict | None = None,
    acoustic_baseline_context: str | None = None,
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
        assemblyai_hints: Optional dict with keys 'entities', 'auto_highlights',
                          'sentiment_results' from AssemblyAI enrichment (paid tier).
                          When present, appended as a structured supplemental block
                          so Haiku has named-entity anchors for medication extraction.
        acoustic_baseline_context: Optional natural-language string describing how
                          this session's acoustic features compare to the patient's
                          established voice baseline. When present, injected into
                          user_content as an ACOUSTIC BASELINE COMPARISON block so
                          the model can populate baseline_deviation with concrete data
                          rather than relying on transcript mentions alone.

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

    # ── Step 2: Extraction — short path or chunked long path ──────────────
    if len(transcript_text) <= MAX_TRANSCRIPT_CHARS:
        # ── Short path: single extraction call on the full transcript ──────
        hints_block    = _format_assemblyai_hints(assemblyai_hints)
        baseline_block = (
            f"\n\nACOUSTIC BASELINE COMPARISON:\n{acoustic_baseline_context}"
            if acoustic_baseline_context
            else ''
        )
        user_content = (
            f"Session type: {session_type}\n"
            f"Session date: {session_date or 'not specified'}\n\n"
            f"TRANSCRIPT:\n{transcript_text}"
            + baseline_block
            + (hints_block or '')
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
                'crisis_level':      crisis_level,
                'crisis_result':     crisis_result,
                'safety_note':       None,
                'features':          None,
                'scores':            None,
                'session_date':      session_date,
                'session_type':      session_type,
                'transcript_length': len(transcript_text),
                'error':             f'Extraction API error: {str(e)}',
            }

        # ── Step 3: Parse response (short path) ───────────────────────────
        features = _parse_extraction_response(raw_response)
        if features is None:
            return {
                'crisis_detected':   False,
                'crisis_level':      crisis_level,
                'crisis_result':     crisis_result,
                'safety_note':       None,
                'features':          None,
                'scores':            None,
                'session_date':      session_date,
                'session_type':      session_type,
                'transcript_length': len(transcript_text),
                'error':             'Extraction response could not be parsed',
            }

    else:
        # ── Long path: chunked extraction + merge ─────────────────────────
        chunks = _split_transcript_into_chunks(transcript_text)
        logger.info(
            "Long transcript (%d chars) split into %d chunks for extraction "
            "(session_date=%s, session_type=%s).",
            len(transcript_text), len(chunks), session_date, session_type
        )
        chunk_results: list[dict] = []
        for i, chunk in enumerate(chunks):
            chunk_features = _extract_single_chunk(
                chunk_text=chunk,
                session_type=session_type,
                session_date=session_date,
                assemblyai_hints=assemblyai_hints,
                # Acoustic baseline context only injected into the first chunk —
                # opening of session has richest speech signal.
                acoustic_baseline_context=acoustic_baseline_context if i == 0 else None,
            )
            if chunk_features is not None:
                chunk_results.append(chunk_features)
            else:
                logger.warning(
                    "Chunk %d/%d extraction failed (session_date=%s).",
                    i + 1, len(chunks), session_date
                )

        if not chunk_results:
            return {
                'crisis_detected':   False,
                'crisis_level':      crisis_level,
                'crisis_result':     crisis_result,
                'safety_note':       None,
                'features':          None,
                'scores':            None,
                'session_date':      session_date,
                'session_type':      session_type,
                'transcript_length': len(transcript_text),
                'error':             'All chunk extractions failed',
            }

        features = _merge_chunk_features(chunk_results)

    # ── Step 3: Secondary crisis check on extracted concerning_language ─────
    # Belt-and-suspenders: re-score against the concerning_language phrases
    # the model surfaced. Uses score_crisis() for consistency with Step 1.
    # Runs on both the short path and the long (chunked) path.
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

    # ── Step 4: Deterministic scoring ─────────────────────────────────────
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


def _build_convergent_signals(
    checkin_scores: dict | None,
    speech_features: dict | None,
    lexical_data: dict | None,
    affect_dimensions: dict | None = None,
) -> dict:
    """
    Detect convergent and divergent signal patterns across independent data streams.

    Implements the Convergent Signal Principle (CLAUDE.md §5):
      - Convergent: ≥2 independent streams pointing in the same direction
      - Divergent: streams pointing in opposite directions — the divergence is
        itself clinically meaningful and must be named, not suppressed

    This function is purely deterministic — no DB calls, no Claude calls.
    All numeric thresholds mirror the spec exactly.

    Args:
        checkin_scores: Aggregate scores for the period. Expected keys:
            mood_avg, stability_score, crash_risk, ns_load, stress_avg,
            sleep_disruption_score, energy_avg. Any may be absent.
        speech_features: Speech feature dict from extract_features()['scores']
            ['speech_features']. Expected keys: speech_rate, prosody, pauses,
            arousal, vocal_affect, speech_coherence. Any may be absent.
        lexical_data: Dict from compute_lexical_diversity(). Expected keys:
            type_token_ratio, trend, delta, entries_analyzed. Any may be absent.
        affect_dimensions: Optional VAD affect model output dict. Expected keys:
            model_available (bool), valence (float 0-1), arousal (float 0-1),
            dominance (float 0-1), valence_label (str), arousal_label (str).
            When None or model_available is False, VAD checks are skipped.

    Returns:
        {
            'convergent': [
                {
                    'streams':     list[str],  # e.g. ['self_report', 'acoustic']
                    'direction':   str,        # 'negative' | 'positive' | 'elevated_load'
                    'observation': str,        # plain-English sentence, no clinical terms
                    'confidence':  str,        # 'strong' (3+ streams) | 'moderate' (2 streams)
                },
                ...
            ],
            'divergent': [
                {
                    'streams':     list[str],
                    'observation': str,        # plain-English description of discrepancy
                    'significance': str,       # 'high' | 'medium'
                },
                ...
            ]
        }
    """
    convergent: list[dict] = []
    divergent:  list[dict] = []

    # Normalise None inputs to empty dicts so .get() calls below never raise
    cs = checkin_scores  or {}
    sf = speech_features or {}
    ld = lexical_data    or {}

    mood_avg        = cs.get('mood_avg')
    stability_score = cs.get('stability_score')
    crash_risk      = cs.get('crash_risk')
    ns_load         = cs.get('ns_load')
    stress_avg      = cs.get('stress_avg')

    speech_rate  = sf.get('speech_rate')
    prosody      = sf.get('prosody')
    arousal      = sf.get('arousal')
    vocal_affect = sf.get('vocal_affect')

    ld_trend    = ld.get('trend')
    ld_delta    = ld.get('delta')
    ld_entries  = ld.get('entries_analyzed', 0)

    # ── Check 1: Mood Distortion (CLAUDE.md §9) ────────────────────────────────
    # When |reported mood − stability score| > 2.5 it is a divergent signal.
    if mood_avg is not None and stability_score is not None:
        distortion = mood_avg - stability_score
        if distortion > 2.5:
            divergent.append({
                'streams':      ['self_report', 'derived_scores'],
                'observation':  (
                    f"Mood average ({mood_avg:.1f}/10) is notably higher than computed "
                    f"stability score ({stability_score:.1f}/10) — a gap of "
                    f"{distortion:.1f} points that may reflect intra-day variability "
                    "or a difference between how the patient rates their mood and what "
                    "the other data signals show."
                ),
                'significance': 'high',
            })
        elif distortion < -2.5:
            divergent.append({
                'streams':      ['self_report', 'derived_scores'],
                'observation':  (
                    f"Mood average ({mood_avg:.1f}/10) is notably lower than computed "
                    f"stability score ({stability_score:.1f}/10) — a gap of "
                    f"{abs(distortion):.1f} points. Reported mood is lower than what "
                    "the derived metrics indicate, which may be worth examining directly."
                ),
                'significance': 'high',
            })

    # ── Check 2: Negative convergent trajectory ────────────────────────────────
    # All three scores in the negative range simultaneously → strong convergence.
    if (
        mood_avg        is not None and mood_avg        <= 4.0
        and stability_score is not None and stability_score <= 4.0
        and crash_risk      is not None and crash_risk      >= 6.0
    ):
        convergent.append({
            'streams':     ['self_report', 'derived_scores'],
            'direction':   'negative',
            'observation': (
                f"Mood average ({mood_avg:.1f}/10), stability score "
                f"({stability_score:.1f}/10), and crash risk ({crash_risk:.1f}/10) "
                "are all in the lower or elevated range this period — three "
                "independent measures pointing in the same direction."
            ),
            'confidence':  'strong',
        })

    # ── Check 3: Speech-mood negative convergence ──────────────────────────────
    # Depressive speech markers co-occurring with low mood self-report.
    if mood_avg is not None and speech_features is not None:
        negative_speech_markers = sum([
            speech_rate == 'slowed',
            arousal     == 'low',
            prosody     == 'flat',
        ])
        if mood_avg <= 4.5 and negative_speech_markers >= 1:
            marker_labels = []
            if speech_rate == 'slowed': marker_labels.append('slowed speech rate')
            if arousal     == 'low':    marker_labels.append('low arousal')
            if prosody     == 'flat':   marker_labels.append('flat prosody')
            conf = 'strong' if negative_speech_markers >= 2 else 'moderate'
            convergent.append({
                'streams':     ['self_report', 'acoustic'],
                'direction':   'negative',
                'observation': (
                    f"Mood average ({mood_avg:.1f}/10) and session speech features "
                    f"({', '.join(marker_labels)}) both point in a lower-range "
                    "direction — two independent data streams in agreement."
                ),
                'confidence':  conf,
            })

    # ── Check 4: Speech-mood divergence (elevated arousal vs. normal mood) ─────
    # Pressured speech or agitation alongside a self-reported mood in normal range.
    if mood_avg is not None and speech_features is not None:
        if speech_rate == 'pressured' or arousal == 'agitated':
            if mood_avg >= 6.0:
                markers = []
                if speech_rate == 'pressured': markers.append('pressured speech rate')
                if arousal     == 'agitated':  markers.append('agitated arousal')
                divergent.append({
                    'streams':      ['self_report', 'acoustic'],
                    'observation':  (
                        f"Session speech features ({', '.join(markers)}) suggest elevated "
                        f"physiological arousal while mood self-report averaged "
                        f"{mood_avg:.1f}/10 — a discrepancy between reported state and "
                        "observed speech presentation that may be worth exploring."
                    ),
                    'significance': 'medium',
                })

    # ── Check 5: Lexical-mood convergence or divergence ────────────────────────
    # Lexical diversity trend as a cognitive trait signal (CLAUDE.md §25).
    if (
        ld_trend  is not None
        and ld_trend   != 'insufficient_data'
        and ld_delta   is not None
        and abs(ld_delta)  >= 0.10
        and ld_entries >= 10
        and mood_avg   is not None
    ):
        if ld_trend == 'declining':
            if mood_avg <= 4.5:
                # Both cognitive trait and self-report pointing negative → convergence
                convergent.append({
                    'streams':     ['lexical', 'self_report'],
                    'direction':   'negative',
                    'observation': (
                        f"Vocabulary range in journal entries has narrowed over this period "
                        f"(TTR change: {ld_delta:+.2f} across {ld_entries} entries) "
                        f"alongside a mood average of {mood_avg:.1f}/10 — two independent "
                        "data streams pointing in the same direction."
                    ),
                    'confidence':  'moderate',
                })
            elif mood_avg >= 6.0:
                # Cognitive load signal diverges from self-reported normal mood
                divergent.append({
                    'streams':      ['lexical', 'self_report'],
                    'observation':  (
                        f"Vocabulary range in journal entries has narrowed over this period "
                        f"(TTR change: {ld_delta:+.2f} across {ld_entries} entries) "
                        f"while mood self-report averaged {mood_avg:.1f}/10 — a discrepancy "
                        "between the cognitive load signal and the self-reported state that "
                        "may be worth examining further."
                    ),
                    'significance': 'medium',
                })

    # ── Check 6: Nervous system load convergence ───────────────────────────────
    # High NS Load + high stress self-report, with or without acoustic corroboration.
    if ns_load is not None and ns_load >= 7.0 and stress_avg is not None and stress_avg >= 6.0:
        has_acoustic_corroboration = (
            speech_features is not None
            and (arousal in ('elevated', 'agitated') or vocal_affect == 'strained')
        )
        if has_acoustic_corroboration:
            acoustic_markers = []
            if arousal      in ('elevated', 'agitated'): acoustic_markers.append(f"arousal: {arousal}")
            if vocal_affect == 'strained':               acoustic_markers.append('strained vocal affect')
            convergent.append({
                'streams':     ['self_report', 'derived_scores', 'acoustic'],
                'direction':   'elevated_load',
                'observation': (
                    f"Nervous system load ({ns_load:.1f}/10), stress average "
                    f"({stress_avg:.1f}/10), and session speech features "
                    f"({', '.join(acoustic_markers)}) all indicate elevated physiological "
                    "load — three independent data streams in agreement."
                ),
                'confidence':  'strong',
            })
        else:
            convergent.append({
                'streams':     ['self_report', 'derived_scores'],
                'direction':   'elevated_load',
                'observation': (
                    f"Nervous system load ({ns_load:.1f}/10) and stress average "
                    f"({stress_avg:.1f}/10) are both elevated — two derived and "
                    "self-report streams pointing in the same direction."
                ),
                'confidence':  'moderate',
            })

    # ── Check 7: Positive trajectory convergence ──────────────────────────────
    # Mood, stability, and crash risk all in healthy range, with stable speech.
    if (
        mood_avg        is not None and mood_avg        >= 6.5
        and stability_score is not None and stability_score >= 6.0
        and crash_risk      is not None and crash_risk      <= 3.0
    ):
        speech_benign = (
            speech_features is None
            or (speech_rate in ('normal', None) and arousal in ('normal', None))
        )
        if speech_features is not None and speech_benign:
            streams = ['self_report', 'derived_scores', 'acoustic']
            conf    = 'strong'
        else:
            streams = ['self_report', 'derived_scores']
            conf    = 'moderate'
        convergent.append({
            'streams':     streams,
            'direction':   'positive',
            'observation': (
                f"Mood average ({mood_avg:.1f}/10), stability score "
                f"({stability_score:.1f}/10), and crash risk ({crash_risk:.1f}/10) "
                "are all in a stable or positive range this period — "
                f"{len(streams)} independent data stream{'s' if len(streams) > 1 else ''} "
                "in agreement."
            ),
            'confidence':  conf,
        })

    # ── Checks 8–11: VAD affect model integration ─────────────────────────────
    # Only run when affect_dimensions is present, model_available is True, and
    # valence is populated. All existing checks above remain unaffected.
    if (
        affect_dimensions is not None
        and affect_dimensions.get('model_available')
        and affect_dimensions.get('valence') is not None
    ):
        afd = affect_dimensions or {}
        valence  = afd.get('valence')
        vad_arousal = afd.get('arousal')
        mood_avg = cs.get('mood_avg') if cs else None

        # ── Check 8: VAD low-valence + low mood (negative convergence) ────────
        if valence < 0.35 and mood_avg is not None and mood_avg <= 4.5:
            conf_8 = (
                'strong' if (vad_arousal is not None and vad_arousal <= 0.40)
                else 'moderate'
            )
            convergent.append({
                'streams':    ['self_report', 'affect_model'],
                'direction':  'negative',
                'confidence': conf_8,
                'observation': (
                    f"Affect model valence ({valence:.2f}) and mood average "
                    f"({mood_avg:.1f}/10) both indicate a lower-range period — "
                    "two independent measurement approaches in agreement. "
                    "(Affect model: ~70–75% accuracy ceiling; treat as supporting "
                    "signal, not a finding.)"
                ),
            })

        # ── Check 9: VAD high-valence + elevated mood (positive convergence) ──
        # Mutually exclusive with Check 8 by construction (valence can't be
        # both < 0.35 and > 0.65).
        elif valence > 0.65 and mood_avg is not None and mood_avg >= 6.5:
            conf_9 = (
                'strong'
                if (cs.get('stability_score') is not None
                    and cs['stability_score'] >= 6.0)
                else 'moderate'
            )
            convergent.append({
                'streams':    ['self_report', 'affect_model'],
                'direction':  'positive',
                'confidence': conf_9,
                'observation': (
                    f"Affect model valence ({valence:.2f}) and mood average "
                    f"({mood_avg:.1f}/10) both indicate a higher-range period — "
                    "consistent across two independent measurement approaches. "
                    "(Affect model: ~70–75% accuracy ceiling.)"
                ),
            })

        # ── Check 10: VAD-self-report divergence (only one sub-case fires) ────
        if mood_avg is not None:
            if mood_avg >= 6.5 and valence < 0.40:
                divergent.append({
                    'streams':      ['self_report', 'affect_model'],
                    'significance': 'medium',
                    'observation':  (
                        f"Reported mood ({mood_avg:.1f}/10) is in the higher range, "
                        f"but affect model valence ({valence:.2f}) is in the lower range "
                        "— a discrepancy between self-report and the acoustic affect signal "
                        "worth noting. (Affect model accuracy ceiling ~70–75%; divergence "
                        "warrants clinical inquiry rather than conclusions.)"
                    ),
                })
            elif mood_avg <= 4.0 and valence > 0.60:
                divergent.append({
                    'streams':      ['self_report', 'affect_model'],
                    'significance': 'medium',
                    'observation':  (
                        f"Reported mood ({mood_avg:.1f}/10) is in the lower range, "
                        f"but affect model valence ({valence:.2f}) is in the higher range "
                        "— self-report and acoustic affect signal point in opposite "
                        "directions. (Affect model accuracy ceiling ~70–75%; this "
                        "discrepancy may reflect self-reporting patterns or acute state "
                        "variation.)"
                    ),
                })

        # ── Check 11: High VAD arousal + acoustic agitation convergence ───────
        if (
            vad_arousal is not None and vad_arousal > 0.65
            and sf is not None
            and (sf.get('arousal') == 'agitated' or sf.get('speech_rate') == 'pressured')
        ):
            acoustic_markers_11 = []
            if sf.get('arousal') == 'agitated':
                acoustic_markers_11.append('agitated arousal')
            if sf.get('speech_rate') == 'pressured':
                acoustic_markers_11.append('pressured speech rate')
            convergent.append({
                'streams':    ['affect_model', 'acoustic'],
                'direction':  'elevated_load',
                'confidence': 'moderate',
                'observation': (
                    f"Affect model arousal ({vad_arousal:.2f}) is elevated, and session "
                    f"speech features ({', '.join(acoustic_markers_11)}) point in the same "
                    "direction — two independent acoustic-derived measurements in agreement. "
                    "(Affect model accuracy ceiling ~70–75%.)"
                ),
            })

    return {'convergent': convergent, 'divergent': divergent}


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
