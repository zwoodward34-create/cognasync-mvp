import logging
import os
import json
import anthropic

logger = logging.getLogger(__name__)

CLAUDE_MODEL = os.environ.get('CLAUDE_MODEL', 'claude-haiku-4-5-20251001')

_client = None


def get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(
            api_key=os.environ.get('ANTHROPIC_API_KEY'),
            max_retries=3,  # retries with exponential backoff on 429 and transient 5xx
        )
    return _client


CRISIS_KEYWORDS = [
    # Explicit statements — spec §10 required terms
    'suicide', 'suicidal', 'kill myself', 'cut myself',
    "don't want to live", "don't want to be alive",
    'self-harm', 'self harm', 'hurt myself', 'end my life', 'ending my life',
    'want to die', 'better off dead',
    # Additional high-signal explicit phrases
    'take my own life', 'taking my own life', 'no reason to live',
    'never wake up', 'sleep and never wake up', 'wish i was dead',
    # Burdensomeness language — Interpersonal Psychological Theory of Suicide (IPTS)
    'better off without me', 'everyone would be better off',
    'world would be better without me', 'burden to everyone',
    # Algospeak / platform-evasion variants (research taxonomy)
    'unalive', 'unaliving', 'kms', 'sewerslide',
]

# ── Graduated crisis scoring — five-level system ──────────────────────────
# Each key maps feature names to the keyword phrases that signal that feature.
# Weights: direct_intent=4, specific_plan=3, means_access=3,
#          recent_self_harm=3, preparatory_behavior=2, recurrent_ideation=2,
#          cannot_safety_plan=2, hopelessness=1, worsening_distress=1
#
# Level 4 (Imminent): adjusted_score >= 8 OR (direct_intent AND (plan OR means))
# Level 3 (High Risk): adjusted_score >= 6
# Level 2 (Elevated):  adjusted_score >= 3
# Level 1 (Passive):   adjusted_score >= 1
# Level 0 (None):      adjusted_score == 0
#
# Used by score_crisis() for provider/transcript channels.
# Patient-facing channels continue to use _check_crisis() (binary, maximum caution).

_CRISIS_FEATURE_KEYWORDS = {
    'direct_intent': [
        'kill myself', 'take my own life', 'taking my own life',
        'end my life', 'ending my life', 'want to die', 'want to end it all',
        'planning to hurt myself', 'going to hurt myself', 'going to kill myself',
    ],
    'specific_plan': [
        'have a plan', 'made a plan', 'planning to use', 'going to use',
        'know exactly how', 'figured out how', 'know how i would',
        'with a gun', 'with pills', 'with a knife', 'overdose on',
        'jump from', 'hang myself', 'step in front of',
    ],
    'means_access': [
        'have a gun', 'have access to a gun', 'have pills', 'stockpiled',
        'have the means', 'already have what i need', 'i have the',
        'bought a', 'bought pills',
    ],
    'recent_self_harm': [
        'tried before', 'attempted before', 'last time i tried', 'hurt myself before',
        'tried to die', 'prior attempt', 'woke up in the hospital after',
        'they found me', 'cut myself', 'burned myself', 'overdosed before',
    ],
    'preparatory_behavior': [
        'giving away my', 'gave away my', 'writing a note', 'wrote a note',
        'saying goodbye', 'said my goodbyes', 'last time i see',
        'updating my will', 'changed my will', 'settled my affairs',
        'put my things in order', 'gave my stuff away',
    ],
    'recurrent_ideation': [
        'keep thinking about', 'thinking about it again', 'still thinking about dying',
        'thoughts keep coming back', "suicidal thoughts", "thoughts of suicide",
        "thoughts of death", "death thoughts", "ideation", "can't stop thinking about it",
        'been having these thoughts for', 'thoughts of ending',
    ],
    'cannot_safety_plan': [
        "can't promise", "won't promise", "can't agree to keep myself safe",
        "won't agree", "can't keep myself safe", "don't think i can stay safe",
        "not sure i can stay safe", "can't say i won't",
    ],
    'hopelessness': [
        'no point', 'pointless', 'hopeless', 'no hope', 'never get better',
        'nothing will change', 'things will never improve', 'no future',
        'no reason to continue', "what's the point of living",
        'better off dead', 'better off without me', 'everyone would be better off',
        'world would be better without me', 'burden to everyone',
        'wish i was dead', 'wish i wasn\'t here', "don't want to be here",
        "don't want to live", "don't want to be alive", 'no reason to live',
    ],
    'worsening_distress': [
        'getting worse', 'worse than before', 'harder and harder',
        "can't take it anymore", 'reached my limit', 'at my limit',
        "can't do this anymore", "don't know how much longer i can",
        "can't go on like this", 'spiraling', 'falling apart',
    ],
}

# Population modifiers — passive-signal amplification per group.
# These only raise the adjusted score when raw_score is in the passive range.
# Direct intent / plan / means always produce Level 3+ regardless.
_POPULATION_PASSIVE_MODIFIER = {
    'adolescent':             1,
    'older_adult':            1,
    'veteran':                1,
    'prior_self_harm':        1,
    'serious_mental_illness': 1,
}

# Population-specific amplifier keywords — additional contextual signals
# that add +1 to the population modifier when present alongside passive signals.
_POPULATION_AMPLIFIERS = {
    'adolescent': [
        'failing school', 'kicked out', 'parents fighting', 'being bullied',
        'not eating', 'missing school', 'kicked off the team', 'no friends left',
    ],
    'older_adult': [
        'giving things away', 'gave things away', 'changed my will',
        'chronic pain', "can't walk", "can't take care of myself",
        'no one visits', 'completely alone', 'no family left', 'memory problems',
        'neglecting medications', 'stopped eating',
    ],
    'veteran': [
        'deployment', 'combat', 'fellow soldier', 'my unit',
        'firearm', 'have a weapon', 'ptsd', 'nightmares', 'flashback',
        "can't reintegrate", "don't fit in anymore", 'back home feels wrong',
        'mission', 'trauma from service',
    ],
    'prior_self_harm': [
        'like last time', 'same as before', 'similar to when i',
        'before my attempt', 'after i got out of the hospital',
        'when i was in the hospital',
    ],
    'serious_mental_illness': [
        'voices', 'hearing things', 'seeing things',
        'not taking my medication', 'stopped my medication', 'off my meds',
        'manic episode', 'psychotic episode', "can't tell what's real",
    ],
}

CRISIS_LEVEL_LABELS = {
    0: 'No apparent risk',
    1: 'Passive concern',
    2: 'Elevated concern',
    3: 'High risk',
    4: 'Imminent danger',
}

# Provider-facing Mode D alert text per crisis level.
# Never shown to patients. Never says "confirmed" — always routes to human review.
CRISIS_LEVEL_NOTES = {
    1: (
        "🔵 Passive Concern — Language patterns suggesting hopelessness or worsening "
        "distress detected. No direct intent or plan present. Recommend monitoring and "
        "clinical discussion at next session."
    ),
    2: (
        "🟡 Elevated Concern — Passive ideation or multiple distress signals detected. "
        "Possible self-harm risk detected. Immediate human review recommended before "
        "next appointment. Safety planning discussion advised."
    ),
    3: (
        "🔴 High Risk — Language consistent with self-harm intent, plan, or means access "
        "detected. Immediate human review recommended. Emergency escalation protocol "
        "should be considered. 988 Suicide & Crisis Lifeline: call or text 988."
    ),
    4: (
        "🚨 Imminent Danger — Credible immediate self-harm intent detected. "
        "Emergency response protocol required. "
        "988 Suicide & Crisis Lifeline: call or text 988. Emergency: 911."
    ),
}


def _score_crisis_features(text: str, population_flags: dict | None = None) -> dict:
    """
    Scan text for crisis signal features and return a structured result.

    Args:
        text:             The text to scan.
        population_flags: Optional {population_name: bool} indicating which
                          population groups apply to this patient.
                          Valid keys: 'adolescent', 'older_adult', 'veteran',
                          'prior_self_harm', 'serious_mental_illness'

    Returns:
        {
            'level':             int (0-4),
            'score':             int (raw weighted score),
            'adjusted_score':    int (score after population modifier),
            'features':          dict of {feature_name: bool},
            'population_modifier': int,
        }

    Level assignment (spec §22):
        Level 4: adjusted_score >= 8 OR (direct_intent AND (specific_plan OR means_access))
        Level 3: adjusted_score >= 6
        Level 2: adjusted_score >= 3
        Level 1: adjusted_score >= 1
        Level 0: adjusted_score == 0
    """
    lower = text.lower()
    features_found = {}
    raw_score = 0

    weights = {
        'direct_intent':         4,
        'specific_plan':         3,
        'means_access':          3,
        'recent_self_harm':      3,
        'preparatory_behavior':  2,
        'recurrent_ideation':    2,
        'cannot_safety_plan':    2,
        'hopelessness':          1,
        'worsening_distress':    1,
    }

    for feature, keywords in _CRISIS_FEATURE_KEYWORDS.items():
        detected = any(kw in lower for kw in keywords)
        features_found[feature] = detected
        if detected:
            raw_score += weights.get(feature, 0)

    # Population modifier — applies only to passive-range signals
    pop_modifier = 0
    if population_flags:
        for pop, active in population_flags.items():
            if active and pop in _POPULATION_PASSIVE_MODIFIER:
                pop_modifier += _POPULATION_PASSIVE_MODIFIER[pop]
                amplifiers = _POPULATION_AMPLIFIERS.get(pop, [])
                if any(kw in lower for kw in amplifiers):
                    pop_modifier += 1

    pop_modifier = min(pop_modifier, 2)  # cap total modifier at +2
    adjusted_score = raw_score + pop_modifier

    # Level assignment — direct intent + plan/means is always Level 4 regardless of score
    direct = features_found.get('direct_intent', False)
    plan   = features_found.get('specific_plan', False)
    means  = features_found.get('means_access', False)

    if adjusted_score >= 8 or (direct and (plan or means)):
        level = 4
    elif adjusted_score >= 6:
        level = 3
    elif adjusted_score >= 3:
        level = 2
    elif adjusted_score >= 1:
        level = 1
    else:
        level = 0

    return {
        'level':               level,
        'score':               raw_score,
        'adjusted_score':      adjusted_score,
        'features':            features_found,
        'population_modifier': pop_modifier,
    }


def score_crisis(text: str, population_flags: dict | None = None) -> dict:
    """
    Public API for graduated crisis scoring. For provider/transcript channels.

    Returns the full crisis assessment dict from _score_crisis_features().
    Safe to call from any route. Never raises.

    Patient-facing channels use _check_crisis() (binary, maximum caution).
    This function is for the provider intelligence layer where graduated
    routing is appropriate and clinical judgment is always in the loop.

    Usage:
        result = score_crisis(transcript_text, population_flags)
        if result['level'] >= 3:
            # route to emergency protocol
        elif result['level'] == 2:
            # priority queue for provider review
        elif result['level'] == 1:
            # silent context flag in Mode C brief
    """
    if not text or not isinstance(text, str):
        return {
            'level': 0, 'score': 0, 'adjusted_score': 0,
            'features': {}, 'population_modifier': 0,
        }
    return _score_crisis_features(text, population_flags=population_flags)


CRISIS_RESPONSE = (
    "I noticed your entry may contain thoughts of self-harm. "
    "If you're struggling, please reach out:\n\n"
    "📞 **988 Suicide & Crisis Lifeline** — call or text 988\n"
    "💬 **Crisis Text Line** — text HOME to 741741\n"
    "🚨 **Emergency** — call 911\n\n"
    "You're not alone. Please talk to someone who can help."
)

FORBIDDEN_PATTERNS = [
    ('you have ', 'noting you may be experiencing'),
    ('you suffer from ', 'you\'ve described experiences that'),
    ('diagnosed with', 'this pattern'),
    ('you are depressed', 'you\'ve described feeling down'),
    ('you are anxious', 'you\'ve noted anxiety'),
    ('you are manic', 'you\'ve described an elevated period'),
    ('stop taking', 'discuss with your provider changes to'),
    ('reduce your dose', 'discuss dosing with your provider'),
    ('you should take', 'some people find it helpful to discuss'),
    ('this will make you better', 'many people find this approach helpful'),
    ('this explains your', 'this pattern coincides with'),
]


def _check_crisis(text):
    lower = text.lower()
    return any(kw in lower for kw in CRISIS_KEYWORDS)


def check_crisis(text):
    """Public entry point for crisis detection — safe to call from app.py routes.
    Returns True if the text contains crisis-level content, False otherwise.
    Never raises; treats empty/non-string input as safe."""
    if not text or not isinstance(text, str):
        return False
    return _check_crisis(text)


def _sanitize_output(text):
    lower = text.lower()
    for forbidden, _ in FORBIDDEN_PATTERNS:
        if forbidden in lower:
            logger.warning(
                "FORBIDDEN_PATTERN caught in output: %r — output suppressed.",
                forbidden,
            )
            return None
    return text


def _call_claude(system_prompt, user_content, max_tokens=600):
    try:
        client = get_client()
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{'role': 'user', 'content': user_content}],
        )
        return message.content[0].text
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("_call_claude failed (model=%s): %s", CLAUDE_MODEL, e, exc_info=True)
        raise RuntimeError(f'Claude API error: {str(e)}')


_JOURNAL_SYSTEM = """You are a supportive reflection tool embedded in a health tracking app. A user just wrote a journal entry.

INSTRUCTIONS:
- Identify 1-2 themes or recurring patterns in the entry
- Reflect the experience back in warm, conversational language — like a thoughtful friend, not a clinician
- If the user seems to be in a difficult moment, acknowledge it simply and directly ("That sounds really hard") — don't analyze it
- Suggest one specific thing worth mentioning at their next provider appointment, framed as a question they could raise
- Keep to 150-200 words

STRICT RULES:
- Never say "you have," "you suffer from," "you are [disorder]," or name any condition
- Do not interpret hyperbolic or venting language as evidence of cognitive distortion — someone saying "I'm a disaster" is expressing frustration, not a clinical state
- Do not offer coping advice or therapeutic interventions
- Do not use clinical terms (dysregulation, rumination, affect, etc.) — write in plain language
- Never diagnose, prescribe, or imply a clinical meaning behind what the user wrote"""


def analyze_journal(entry_text):
    if _check_crisis(entry_text):
        return {'status': 'crisis', 'text': CRISIS_RESPONSE}

    raw = _call_claude(_JOURNAL_SYSTEM, entry_text, max_tokens=400)
    clean = _sanitize_output(raw)
    if clean is None:
        clean = (
            "Thank you for sharing your thoughts today. "
            "Your entry reflects experiences worth exploring further with your provider. "
            "Consider discussing the patterns you've noticed in how you're feeling."
        )

    if _check_crisis(raw):
        return {'status': 'crisis', 'text': CRISIS_RESPONSE}

    return {'status': 'safe', 'text': clean, 'raw': raw}


def analyze_checkin(checkin_data, checkin_type, baseline=None):
    notes = checkin_data.get('notes', '')
    if notes and _check_crisis(notes):
        return {'status': 'crisis', 'text': CRISIS_RESPONSE}

    type_labels = {
        'morning': 'morning', 'afternoon': 'afternoon',
        'evening': 'evening', 'on_demand': 'on-demand',
    }
    label = type_labels.get(checkin_type, 'check-in')
    ext = checkin_data.get('extended_data', {}) or {}

    summary_lines = [
        f"Check-in type: {label}",
        f"Mood: {checkin_data.get('mood_score')}/10",
        f"Anxiety/stress: {checkin_data.get('stress_score')}/10",
        f"Energy: {ext.get('energy', 'not recorded')}/10",
        f"Focus: {ext.get('focus', 'not recorded')}/10",
    ]
    if checkin_type == 'morning':
        summary_lines += [
            f"Sleep hours: {checkin_data.get('sleep_hours')}",
            f"Sleep quality: {ext.get('sleep_quality', 'not recorded')}/10",
            f"Sleep latency (min to fall asleep): {ext.get('sleep_latency_minutes', 'not recorded')}",
            f"Night awakenings: {ext.get('night_awakenings', 'not recorded')}",
        ]
    if ext.get('caffeine_mg') is not None:
        summary_lines.append(f"Caffeine: {ext.get('caffeine_mg')}mg")
    if ext.get('stim_load') is not None:
        summary_lines.append(f"Stim Load: {ext.get('stim_load')}/10")
    # Advanced fields (only if present)
    for field, label_str in [
        ('irritability', 'Irritability'),
        ('motivation', 'Motivation'),
        ('perceived_stress', 'Perceived stress'),
    ]:
        if ext.get(field) is not None:
            summary_lines.append(f"{label_str}: {ext[field]}/10")
    for field, label_str in [
        ('exercise_minutes', 'Exercise today (min)'),
        ('sunlight_hours', 'Sunlight (hrs)'),
        ('social_quality', 'Social quality'),
        ('workload_friction', 'Workload friction'),
        ('alcohol_units', 'Alcohol units'),
    ]:
        if ext.get(field) is not None:
            summary_lines.append(f"{label_str}: {ext[field]}")
    if ext.get('coping'):
        coping = ext['coping']
        active = [k for k, v in coping.items() if v]
        if active:
            summary_lines.append(f"Coping activities today: {', '.join(active)}")
    # Notable symptoms — acknowledge today's log without correlating
    raw_symptoms = ext.get('notable_symptoms') or []
    if isinstance(raw_symptoms, str):
        try:
            import json as _json
            raw_symptoms = _json.loads(raw_symptoms)
        except Exception:
            raw_symptoms = [s.strip() for s in raw_symptoms.split(',') if s.strip()]
    if raw_symptoms:
        summary_lines.append(f"Notable symptoms logged today: {', '.join(str(s) for s in raw_symptoms)}")
    if notes:
        summary_lines.append(f"Notes: {notes[:200]}")
    if baseline:
        summary_lines.append(
            f"7-day baseline — avg mood: {baseline.get('avgMood', 'n/a')}, "
            f"avg anxiety: {baseline.get('avgAnxiety', 'n/a')}, "
            f"avg energy: {baseline.get('avgEnergy', 'n/a')}, "
            f"avg sleep: {baseline.get('avgSleep', 'n/a')} hrs"
        )

    data_str = '\n'.join(summary_lines)

    checkin_system = (
        f"You are embedded in CognaSync, a health tracking app. A user just completed a {label} check-in. "
        "Write a 2-3 sentence observation about their day — warm and conversational, like a thoughtful friend who actually looked at their numbers. "
        "Reference at least one specific number from today's data. "
        "Compare to their baseline if available (e.g., 'a bit higher than your average this week'). "
        "If advanced data was logged (exercise, coping activities, social quality), acknowledge it naturally when relevant. "
        "If 'Notable symptoms logged today' appears in the data, briefly acknowledge it in one phrase (e.g., 'Noted that you logged a headache today.') — do NOT analyze, correlate, or explain it. "
        "STRICT RULES: "
        "Never say 'you have,' 'you are [anything clinical],' or 'you should [medication].' "
        "Never diagnose or imply a clinical interpretation. "
        "Do not use clinical jargon. Write in plain, everyday language. "
        "If multiple numbers look concerning together, note the pattern once — don't list every data point."
    )

    try:
        raw = _call_claude(checkin_system, data_str, max_tokens=200)
        clean = _sanitize_output(raw)
        if not clean:
            clean = "Check-in recorded. Your data has been saved and will inform your next summary."
        if _check_crisis(raw):
            return {'status': 'crisis', 'text': CRISIS_RESPONSE}
        return {'status': 'safe', 'text': clean}
    except RuntimeError:
        return {'status': 'safe', 'text': 'Check-in recorded successfully.'}


# ─────────────────────────────────────────────────────────────────────────────
# PSYCHIATRY BRIEF — Mode C (Psychiatrist)
# Medication-first, quantitative-primary, graphical-data-ready
# ─────────────────────────────────────────────────────────────────────────────

_PSYCHIATRY_SYSTEM = """You are generating a pre-appointment clinical brief for a PSYCHIATRIST (Mode C — Psychiatrist variant).

AUDIENCE: A prescribing psychiatrist with 15–20 minutes per appointment. They need:
1. Medication-relevant signals immediately
2. Hard numbers, not prose descriptions of numbers
3. Convergence/divergence flags (self-report vs. objective indicators)
4. Clear flags at the top, not buried at the end

STRUCTURE (use exactly these section headers in this order):

## Trajectory
One sentence maximum. State the overall direction and name any key divergence (e.g., self-reported mood elevated but Stability Score lower, or Crash Risk rising despite low stress reports).

## Core Stability Metrics
Present as a compact table or tightly structured list. Include ALL of:
- Stability Score: avg X/10 | trend | high: X | low: X
- Crash Risk: avg X/10 | trend | days ≥7: N
- Nervous System Load: avg X/10 | trend
- Mood Distortion: Δ X pts (self-report vs. Stability Score) — flag if Δ > 2.5

## Medication
Lead with the current regimen. Then:
- Adherence: X/Y check-ins logged | any gaps?
- Stim Load: avg X/10 | days ≥7: N | days ≥9: N
- Timing: note variability if SD > 60 min across logged doses
- If fatigue or crash symptoms are logged and timing precedes them, note the timing pattern (not cause)
- Do NOT advise changes. Do NOT comment on whether regimen is adequate.

## Quantitative Summary
Tight data block — numbers first, words minimal:
- Mood: avg X/10 | trend | range X–X
- Sleep: avg X hrs | range X–X | Sleep Disruption avg X/10
- Energy: avg X/10 | trend
- Stress: avg X/10 | trend
- Irritability: avg X/10 (include range if notable)

## Symptom Patterns
Only include if ≥3 occurrences. Format: "[Symptom]: N of T days. Co-signals: [variable] [higher/lower] on symptom days (avg X vs X, Δ=X)." If medication context exists, note timing only. Omit if no symptoms meet threshold.

## Session Intelligence
For each processed recording, structure as:
- **[Date] [Session type]**
- Reported mood: patient's own words about how they felt
- Observed speech (text-inferred, §24 vocab): rate / prosody / coherence / vocal affect / arousal. Frame as "session speech showed [X]."
- Acoustic measurements (waveform — cite only when present in data): articulation rate (sps), pause ratio, F0 CV, HNR dB. Flag out-of-range values: artic <3.5 sps = slowed; pause ratio >35% = elevated silence; F0 CV <0.05 = flat prosody; HNR <10 dB = strained/breathy.
- Affect model (research signal — cite only when present): valence / arousal / dominance with labels. Append "— research signal, not diagnostic."
- Medication-relevant content: what the patient said about medications, side effects, timing, or adherence
- Key themes: stressors, avoidance, safety language
- Convergence note: when acoustic measurements + text features + check-in scores align, name it explicitly (e.g., "Flat prosody, reduced F0 CV 0.03, and affect model valence −0.4 are convergent with check-in mood of 3/10 that day.")
If no acoustic measurements exist for a session, state "acoustic data not available."

## 🚨 Flags
List only. Each flag = one line with supporting data point. Format: "[Flag]: [data]". If none: "No threshold alerts for this period."

## Suggested Discussion Topics
3 items maximum. Anchor each to a specific data point. Medication-relevant first.

RULES:
- No warm conversational prose. Number first, label second.
- Never say "you should" or advise medication changes.
- Never diagnose. Use "data shows" / "logged" / "reported."
- Mood Distortion (Δ > 2.5): always surface it.
- Acoustic measurements capture HOW the patient spoke — surface them as distinct from transcript content, not as a repeat of it.
- Omit Positive Correlates, Coping Activities, Sunlight, Workload Friction unless threshold-crossing.
- Alcohol: include only if ≥3 units/use day or ≥4 drinking days in 7-day window.
- Keep the entire brief under 700 words.
"""


def _build_chart_data(checkin_data):
    """Compute per-day chart arrays from checkin_data. Pure computation, no API call.

    Returns a dict with parallel arrays (one entry per check-in, sorted by date)
    suitable for Chart.js rendering.
    """
    import database as _db  # local import to avoid circular at module level

    rows = []
    for c in checkin_data:
        ext = {}
        if c.get('extended_data'):
            try:
                ext = (json.loads(c['extended_data'])
                       if isinstance(c['extended_data'], str)
                       else c.get('extended_data', {}))
            except Exception:
                pass

        mood   = c.get('mood_score')
        stress = c.get('stress_score')
        sleep  = c.get('sleep_hours')
        energy = ext.get('energy')
        meds   = c.get('medications') or []
        if isinstance(meds, str):
            try:
                meds = json.loads(meds)
            except Exception:
                meds = []

        scores = _db._compute_checkin_scores(mood, stress, sleep, ext, meds)

        date_str = c.get('checkin_date') or c.get('date') or (c.get('created_at') or '')[:10]
        rows.append({
            'date':             date_str,
            'mood':             float(mood)   if mood   is not None else None,
            'stability_score':  scores.get('stability_score'),
            'crash_risk':       scores.get('crash_risk'),
            'sleep_hours':      float(sleep)  if sleep  is not None else None,
            'sleep_disruption': scores.get('sleep_disruption'),
            'stim_load':        scores.get('stim_load'),
            'energy':           float(energy) if energy is not None else None,
            'stress':           float(stress) if stress is not None else None,
        })

    # Sort by date, deduplicate by taking last entry per date
    from collections import OrderedDict
    by_date = OrderedDict()
    for r in sorted(rows, key=lambda x: x['date']):
        by_date[r['date']] = r

    sorted_rows = list(by_date.values())
    keys = ['mood', 'stability_score', 'crash_risk', 'sleep_hours',
            'sleep_disruption', 'stim_load', 'energy', 'stress']

    chart = {'dates': [r['date'] for r in sorted_rows]}
    for k in keys:
        chart[k] = [r[k] for r in sorted_rows]

    # Period averages (skip None)
    def _avg(lst):
        vals = [v for v in lst if v is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    chart['averages'] = {k: _avg(chart[k]) for k in keys}
    return chart


def generate_psychiatry_summary(checkin_data, journal_data, days=14,
                                 period_start=None, period_end=None,
                                 appointment_date=None,
                                 symptom_patterns=None,
                                 substance_flags=None,
                                 safety_flags=None,
                                 session_context=None,
                                 raw_voice_transcripts=None):
    """Mode C (Psychiatrist) — medication-first, quantitative-primary brief.

    Returns {'status', 'text', 'raw', 'chart_data'} where chart_data contains
    parallel date-indexed arrays for Chart.js rendering on the frontend.
    """
    # Build chart data first (pure computation, always succeeds)
    try:
        chart_data = _build_chart_data(checkin_data)
    except Exception as _cde:
        chart_data = {}

    # ── Reuse generate_appointment_summary's data parsing by delegating ──────
    # We call it with audience='provider' to get the structured Mode C data
    # block, then override the system prompt with the psychiatry-specific one.
    # This avoids duplicating the 200-line checkin parsing logic.
    #
    # The approach: monkey-patch the system prompt by calling the internal
    # _call_claude directly with our prompt after building user_content
    # via generate_appointment_summary's parsing infrastructure.
    #
    # Simpler approach: duplicate the key stats extraction inline (small),
    # then call _call_claude with _PSYCHIATRY_SYSTEM.

    # ── Parse checkin data for psychiatry-relevant fields ─────────────────────
    checkin_rows = []
    mood_vals, stress_vals, sleep_vals, energy_vals = [], [], [], []
    irrit_vals, motiv_vals = [], []
    meds_logged = high_stim_days = 0

    for c in checkin_data:
        ext = {}
        if c.get('extended_data'):
            try:
                ext = (json.loads(c['extended_data'])
                       if isinstance(c['extended_data'], str)
                       else c.get('extended_data', {}))
            except Exception:
                pass

        mood   = c.get('mood_score')
        stress = c.get('stress_score')
        sleep  = c.get('sleep_hours')
        energy = ext.get('energy')

        meds = c.get('medications') or []
        if isinstance(meds, str):
            try:
                meds = json.loads(meds)
            except Exception:
                meds = []

        import database as _db
        scores = _db._compute_checkin_scores(mood, stress, sleep, ext, meds)

        stim = scores.get('stim_load')
        if stim is not None and float(stim) >= 7:
            high_stim_days += 1

        row = {
            'date':             c.get('checkin_date', c.get('date', '')),
            'type':             c.get('checkin_type', 'on_demand'),
            'mood':             mood,
            'stress':           stress,
            'sleep_hours':      sleep,
            'stability_score':  scores.get('stability_score'),
            'crash_risk':       scores.get('crash_risk'),
            'ns_load':          scores.get('ns_load'),
            'sleep_disruption': scores.get('sleep_disruption'),
            'stim_load':        stim,
            'mood_distortion':  scores.get('mood_distortion'),
        }
        if energy is not None:
            row['energy'] = energy
        if ext.get('irritability') is not None:
            row['irritability'] = ext['irritability']
            irrit_vals.append(float(ext['irritability']))
        if ext.get('motivation') is not None:
            motiv_vals.append(float(ext['motivation']))
        if ext.get('caffeine_mg') is not None:
            row['caffeine_mg'] = ext['caffeine_mg']
        if meds:
            meds_logged += 1
            row['meds_taken'] = sum(1 for m in meds if isinstance(m, dict) and m.get('taken'))

        checkin_rows.append(row)
        if mood   is not None: mood_vals.append(float(mood))
        if stress is not None: stress_vals.append(float(stress))
        if sleep  is not None: sleep_vals.append(float(sleep))
        if energy is not None: energy_vals.append(float(energy))

    def _avg(v): return round(sum(v) / len(v), 1) if v else None
    def _trend(v):
        if len(v) < 2: return 'insufficient data'
        return 'improving' if v[-1] > v[0] else 'declining' if v[-1] < v[0] else 'stable'
    def _std(v):
        if len(v) < 2: return None
        m = sum(v) / len(v)
        return round((sum((x - m) ** 2 for x in v) / len(v)) ** 0.5, 2)

    n = len(checkin_rows)

    # Compute aggregated score stats from chart_data arrays
    stab_vals  = [v for v in chart_data.get('stability_score', []) if v is not None]
    cr_vals    = [v for v in chart_data.get('crash_risk', [])       if v is not None]
    ns_vals    = [v for v in chart_data.get('stim_load', [])        if v is not None]
    sd_vals    = [v for v in chart_data.get('sleep_disruption', []) if v is not None]

    # Mood Distortion: avg |reported mood - stability_score| across paired days
    distortion_vals = []
    for r in checkin_rows:
        m = r.get('mood')
        s = r.get('stability_score')
        if m is not None and s is not None:
            distortion_vals.append(abs(float(m) - float(s)))
    avg_distortion = _avg(distortion_vals)

    stats = {
        'total_checkins':      n,
        'period_days':         days,
        'avg_mood':            _avg(mood_vals),
        'mood_trend':          _trend(mood_vals),
        'mood_range':          [min(mood_vals), max(mood_vals)] if mood_vals else None,
        'avg_stress':          _avg(stress_vals),
        'stress_trend':        _trend(stress_vals),
        'avg_sleep_hours':     _avg(sleep_vals),
        'sleep_range':         [min(sleep_vals), max(sleep_vals)] if sleep_vals else None,
        'avg_energy':          _avg(energy_vals),
        'energy_trend':        _trend(energy_vals),
        'checkins_with_meds':  meds_logged,
        'high_stim_load_days': high_stim_days,
        'avg_stability_score': _avg(stab_vals),
        'stability_trend':     _trend(stab_vals),
        'stability_range':     [round(min(stab_vals), 1), round(max(stab_vals), 1)] if stab_vals else None,
        'avg_crash_risk':      _avg(cr_vals),
        'crash_risk_trend':    _trend(cr_vals),
        'crash_risk_high_days': sum(1 for v in cr_vals if v >= 7),
        'avg_sleep_disruption':_avg(sd_vals),
        'avg_mood_distortion': avg_distortion,
        'avg_irritability':    _avg(irrit_vals) if irrit_vals else None,
    }

    n_days = days
    period_label = (
        f"{period_start} to {period_end}" if period_start and period_end
        else f"Last {n_days} days"
    )
    if appointment_date:
        period_label += f" (appointment: {appointment_date})"

    # ── Journal rows ──────────────────────────────────────────────────────────
    journal_rows = []
    for j in journal_data:
        entry_date = (j.get('entry_date') or j.get('created_at', ''))[:10]
        content    = j.get('content') or j.get('raw_entry') or ''
        if content:
            journal_rows.append({'date': entry_date, 'content': content[:600]})

    # ── Symptom section ───────────────────────────────────────────────────────
    symptom_section = ''
    if symptom_patterns:
        lines = []
        for sp in symptom_patterns:
            sym   = sp.get('symptom', '')
            d_rep = sp.get('days_reported', 0)
        d_tot = sp.get('total_days', n)
        co    = sp.get('co_occurring') or []
        med   = sp.get('medication_context')
        line  = f"{sym}: {d_rep} of {d_tot} days."
        if co:
            co_str = '; '.join(
                f"{c['label']} {c['direction']} on symptom days "
                f"(avg {c['avg_on_symptom_days']} vs {c['avg_off_symptom_days']}, Δ={c['delta']})"
                for c in co[:2]
            )
            line += f" Co-signals: {co_str}."
        if med:
            line += (f" Medication context: {med.get('change_type', 'change')} in "
                     f"{med.get('medication_name', 'medication')} "
                     f"{abs(med.get('days_before_symptom_onset', 0))} days before first entry.")
        lines.append(line)
        if lines:
            symptom_section = '\n\nSYMPTOM PATTERNS:\n' + '\n'.join(lines)

    # ── Safety section ────────────────────────────────────────────────────────
    safety_section = ''
    if safety_flags and safety_flags.get('signals_found'):
        sf = safety_flags
        safety_section = (
            f"\n\nINTERPERSONAL SAFETY SIGNAL: Language patterns in {sf.get('signal_count', '?')} "
            f"journal entries ({sf.get('first_signal_date', '?')} – {sf.get('most_recent_date', '?')}; "
            f"most recent {sf.get('recency_days', '?')} days ago). Clinical assessment recommended."
        )

    # ── Substance section ─────────────────────────────────────────────────────
    substance_section = ''
    if substance_flags and substance_flags.get('alert_level') in ('watch', 'concern'):
        sf = substance_flags
        lines = []
        for sub in ('alcohol', 'cannabis', 'nicotine', 'other'):
            sd = sf.get(sub, {})
            if sd.get('use_days', 0) > 0:
                lines.append(
                    f"{sub.capitalize()}: {sd['use_days']} of {sf.get('total_days', n)} days "
                    f"(alert: {sd.get('alert_level', 'watch')})"
                )
        if lines:
            substance_section = '\n\nSUBSTANCE USE FLAGS:\n' + '\n'.join(lines)

    # ── Session context ───────────────────────────────────────────────────────
    session_section = ''
    has_acoustic = False
    if session_context:
        blocks = []
        for s in session_context[:5]:
            if s.get('processing_status') != 'complete':
                continue
            feat   = s.get('features') or {}
            sc     = s.get('scores') or {}
            sf_obs = feat.get('speech_features') or {}
            acf    = sc.get('acoustic_features') or {}
            afd    = sc.get('affect_dimensions') or {}
            vocab  = acf.get('vocabulary') or {}
            raw_m  = acf.get('raw') or {}

            b = f"[{s.get('session_date', '?')}] {s.get('session_type', 'session').replace('_', ' ')}"
            if s.get('crisis_detected'):
                b = '🔴 CRISIS DETECTED — ' + b

            # Patient-reported mood from transcript
            mood_d = feat.get('mood_description') or feat.get('patient_mood_description')
            if mood_d:
                b += f'\n  Reported mood: {mood_d}'

            # Observed affect + speech (text-inferred, §24 vocabulary)
            sf_parts = []
            if sf_obs.get('speech_rate'):
                sf_parts.append(f"rate={sf_obs['speech_rate']}")
            if sf_obs.get('prosody'):
                sf_parts.append(f"prosody={sf_obs['prosody']}")
            if sf_obs.get('pauses'):
                sf_parts.append(f"pauses={sf_obs['pauses']}")
            if sf_obs.get('speech_coherence'):
                sf_parts.append(f"coherence={sf_obs['speech_coherence']}")
            if sf_obs.get('arousal'):
                sf_parts.append(f"arousal={sf_obs['arousal']}")
            if sf_obs.get('vocal_affect'):
                sf_parts.append(f"vocal_affect={sf_obs['vocal_affect']}")
            if sf_parts:
                b += f'\n  Speech features (text-inferred): {", ".join(sf_parts)}'
            if sf_obs.get('clinical_pattern_type') and sf_obs['clinical_pattern_type'] != 'none_detected':
                b += f'\n  Clinical pattern type: {sf_obs["clinical_pattern_type"]}'

            # Waveform acoustic measurements (from audio processing)
            measured = []
            if raw_m.get('articulation_rate_sps') is not None:
                measured.append(f"articulation rate {raw_m['articulation_rate_sps']:.2f} sps")
            if raw_m.get('pause_ratio') is not None:
                measured.append(f"pause ratio {raw_m['pause_ratio']:.0%}")
            if raw_m.get('f0_cv') is not None:
                measured.append(f"F0 CV {raw_m['f0_cv']:.3f}")
            if raw_m.get('hnr_db') is not None:
                measured.append(f"HNR {raw_m['hnr_db']:.1f} dB")
            if measured:
                has_acoustic = True
                b += f'\n  Acoustic measurements (waveform): {", ".join(measured)}'
            if vocab.get('clinical_pattern_type') and vocab['clinical_pattern_type'] != 'none_detected':
                b += f'\n  Waveform-inferred pattern: {vocab["clinical_pattern_type"]}'

            # Affect model output (VAD — valence/arousal/dominance)
            if afd.get('model_available') and afd.get('valence') is not None:
                b += (
                    f'\n  Affect model (research signal): '
                    f'valence {afd["valence"]:.2f} ({afd.get("valence_label","?")}), '
                    f'arousal {afd["arousal"]:.2f} ({afd.get("arousal_label","?")}), '
                    f'dominance {afd["dominance"]:.2f} ({afd.get("dominance_label","?")}) '
                    f'— pattern: {afd.get("pattern","N/A")}'
                )

            # Key themes from transcript
            themes = feat.get('key_themes') or []
            if themes:
                b += f'\n  Themes: {", ".join(themes[:4])}'

            # Baseline deviation note
            if sf_obs.get('baseline_deviation'):
                b += f'\n  Baseline deviation: {sf_obs["baseline_deviation"]}'

            blocks.append(b)

        pending = [s for s in session_context if s.get('processing_status') != 'complete']
        if blocks:
            session_section = (
                f'\n\nSESSION RECORDINGS ({len(blocks)} processed'
                + (f', {len(pending)} pending' if pending else '')
                + '):\n\n'
                + '\n\n'.join(blocks)
            )
            if has_acoustic:
                session_section += (
                    '\n\nNote: sessions with acoustic measurements were processed from audio. '
                    'Articulation rate (sps = syllables/sec; typical 4–6), pause ratio '
                    '(proportion of recording in silence; elevated = psychomotor slowing or '
                    'planning difficulty), F0 CV (pitch variability; reduced = flat prosody), '
                    'HNR dB (voice quality; lower = breathiness/strain). '
                    'Apply §24 interpretation vocabulary. No diagnostic claims.\n'
                )

    # ── Raw voice transcripts ─────────────────────────────────────────────────
    voice_block = ''
    if raw_voice_transcripts:
        lines = []
        for vt in raw_voice_transcripts:
            lines.append(f"[{vt.get('date', '?')}] {vt.get('transcript', '').strip()}")
        if lines:
            voice_block = (
                '\n\nPATIENT VOICE RECORDINGS (raw transcripts — analyze for medication-relevant '
                'content, mood themes, avoidance patterns, and safety language):\n\n'
                + '\n\n'.join(lines)
            )

    user_content = (
        f"REVIEW PERIOD: {period_label}\n\n"
        f"AGGREGATE STATS:\n{json.dumps(stats, indent=2)}\n\n"
        f"DAILY CHECK-INS ({n} total):\n{json.dumps(checkin_rows, indent=2, default=str)}\n\n"
        f"JOURNAL ENTRIES ({len(journal_rows)} total):\n{json.dumps(journal_rows, indent=2, default=str)}"
        f"{symptom_section}"
        f"{substance_section}"
        f"{safety_section}"
        f"{session_section}"
        f"{voice_block}"
    )

    raw   = _call_claude(_PSYCHIATRY_SYSTEM, user_content, max_tokens=1000)
    clean = _sanitize_output(raw)
    if clean is None:
        clean = (
            "A summary was generated but contained language that requires clinical review. "
            "Please regenerate or contact support."
        )
    return {'status': 'safe', 'text': clean, 'raw': raw, 'chart_data': chart_data}


def generate_appointment_summary(checkin_data, journal_data, days=14,
                                  period_start=None, period_end=None,
                                  appointment_date=None,
                                  audience='patient',
                                  symptom_patterns=None,
                                  substance_flags=None,
                                  safety_flags=None,
                                  what_worked=None,
                                  lexical_data=None,
                                  readability_data=None,
                                  session_context=None,
                                  raw_voice_transcripts=None):
    """Synthesize check-in and journal data into a pre-appointment summary.

    audience='patient'  → humanized, conversational (Mode B)
    audience='provider' → structured, data-dense (Mode C)

    Accepts either rolling `days` from today or an explicit `period_start` / `period_end`.
    `appointment_date` (YYYY-MM-DD string) tightens the framing when provided.
    """
    # ── Parse checkin rows ────────────────────────────────────────────
    checkin_rows = []
    mood_vals, stress_vals, sleep_vals, energy_vals = [], [], [], []
    irrit_vals, motiv_vals, perceived_stress_vals = [], [], []
    exercise_vals, social_vals, workload_vals = [], [], []
    alcohol_vals, sunlight_vals, screen_vals = [], [], []
    coping_days = {'breathing': 0, 'meditation': 0, 'movement': 0}
    advanced_days = 0
    meds_logged = 0
    high_stim_days = 0

    for c in checkin_data:
        ext = {}
        if c.get('extended_data'):
            try:
                ext = json.loads(c['extended_data']) if isinstance(c['extended_data'], str) else c.get('extended_data', {})
            except Exception:
                pass

        mood   = c.get('mood_score')
        stress = c.get('stress_score')
        sleep  = c.get('sleep_hours')
        energy = ext.get('energy')

        row = {
            'date':        c.get('checkin_date', c.get('date', '')),
            'type':        c.get('checkin_type', 'on_demand'),
            'mood':        mood,
            'stress':      stress,
            'sleep_hours': sleep,
        }
        if energy is not None:
            row['energy'] = energy
        if ext.get('sleep_quality') is not None:
            row['sleep_quality'] = ext['sleep_quality']
        if ext.get('caffeine_mg') is not None:
            row['caffeine_mg'] = ext['caffeine_mg']
        if ext.get('stim_load') is not None:
            row['stim_load'] = ext['stim_load']
            if float(ext['stim_load']) >= 7:
                high_stim_days += 1

        # Advanced fields
        is_advanced = False
        for field, store_list, row_key in [
            ('irritability',     irrit_vals,            'irritability'),
            ('motivation',       motiv_vals,             'motivation'),
            ('perceived_stress', perceived_stress_vals,  'perceived_stress'),
            ('exercise_minutes', exercise_vals,          'exercise_minutes'),
            ('social_quality',   social_vals,            'social_quality'),
            ('workload_friction',workload_vals,          'workload_friction'),
            ('alcohol_units',    alcohol_vals,           'alcohol_units'),
            ('sunlight_hours',   sunlight_vals,          'sunlight_hours'),
            ('screen_time_hours',screen_vals,            'screen_time_hours'),
        ]:
            val = ext.get(field)
            if val is not None:
                store_list.append(float(val))
                row[row_key] = val
                is_advanced = True
        if ext.get('coping'):
            coping = ext['coping']
            for k in coping_days:
                if coping.get(k):
                    coping_days[k] += 1
            is_advanced = True
        if is_advanced:
            advanced_days += 1

        meds = c.get('medications') or []
        if isinstance(meds, str):
            try:
                meds = json.loads(meds)
            except Exception:
                meds = []
        if meds:
            meds_logged += 1
            row['meds_taken'] = sum(1 for m in meds if isinstance(m, dict) and m.get('taken'))

        if c.get('ai_insights'):
            row['ai_observation'] = c['ai_insights'][:150]

        checkin_rows.append(row)

        if mood   is not None: mood_vals.append(float(mood))
        if stress is not None: stress_vals.append(float(stress))
        if sleep  is not None: sleep_vals.append(float(sleep))
        if energy is not None: energy_vals.append(float(energy))

    def _avg(v): return round(sum(v) / len(v), 1) if v else None
    def _trend(v):
        if len(v) < 2: return 'insufficient data'
        return 'improving' if v[-1] > v[0] else 'declining' if v[-1] < v[0] else 'stable'

    n = len(checkin_rows)
    stats = {
        'total_checkins':     n,
        'period_days':        days,
        'avg_mood':           _avg(mood_vals),
        'mood_trend':         _trend(mood_vals),
        'avg_stress':         _avg(stress_vals),
        'stress_trend':       _trend(stress_vals),
        'avg_sleep_hours':    _avg(sleep_vals),
        'avg_energy':         _avg(energy_vals),
        'checkins_with_meds': meds_logged,
        'high_stim_load_days': high_stim_days,
    }

    # Advanced stats (only include if enough observations)
    adv_stats = {}
    if advanced_days >= 3:
        adv_stats['advanced_checkin_days'] = advanced_days
        if len(irrit_vals)   >= 3: adv_stats['avg_irritability']    = _avg(irrit_vals)
        if len(motiv_vals)   >= 3: adv_stats['avg_motivation']      = _avg(motiv_vals)
        if len(perceived_stress_vals) >= 3: adv_stats['avg_perceived_stress'] = _avg(perceived_stress_vals)
        if len(exercise_vals) >= 3: adv_stats['avg_exercise_minutes'] = _avg(exercise_vals)
        if len(social_vals)  >= 3: adv_stats['avg_social_quality']  = _avg(social_vals)
        if len(workload_vals) >= 3: adv_stats['avg_workload_friction'] = _avg(workload_vals)
        if len(alcohol_vals) >= 3: adv_stats['avg_alcohol_units']   = _avg(alcohol_vals)
        if len(sunlight_vals) >= 3: adv_stats['avg_sunlight_hours'] = _avg(sunlight_vals)
        if any(v > 0 for v in coping_days.values()):
            adv_stats['coping_activity_days'] = coping_days

    # ── Journal rows ─────────────────────────────────────────────────
    journal_rows = []
    for j in journal_data:
        entry_date = (j.get('entry_date') or j.get('created_at', ''))[:10]
        content    = j.get('content') or j.get('raw_entry') or ''
        journal_rows.append({
            'date':    entry_date,
            'excerpt': content[:300] + ('...' if len(content) > 300 else ''),
        })

    # ── Crisis interception on journal content ────────────────────────
    # Spec §10: crisis detection must run on ALL user-provided text before
    # any model invocation.  Journal excerpts pass through raw — scan them.
    _journal_crisis = False
    for _j in journal_data:
        _jc = _j.get('content') or _j.get('raw_entry') or ''
        if _jc and _check_crisis(_jc):
            _journal_crisis = True
            break

    if _journal_crisis and audience == 'patient':
        return {'status': 'crisis', 'text': CRISIS_RESPONSE}

    # ── Build period label ────────────────────────────────────────────
    appt_context = (
        f"The appointment is on {appointment_date}. "
        if appointment_date else ""
    )
    period_label = (
        f"{period_start} to {period_end}"
        if period_start and period_end
        else f"past {days} days"
    )
    data_boundary = f"This summary is based on {n} check-in{'s' if n != 1 else ''} over {days or 'the selected'} days."
    if advanced_days >= 3:
        data_boundary += f" Advanced data available for {advanced_days} of those days."

    # ── System prompt: split by audience ─────────────────────────────
    # ── Symptom patterns section ──────────────────────────────────────
    symptom_section = ''
    if symptom_patterns:
        lines = []
        for sp in symptom_patterns:
            sym   = sp.get('symptom', '')
            n_sym = sp.get('days_reported', 0)
            total = sp.get('total_days', 0)
            first = sp.get('first_seen', '')
            co    = sp.get('co_occurring') or []
            mctx  = sp.get('medication_context')

            co_parts = []
            for c in co[:3]:  # top 3 co-occurring signals
                lbl = c.get('label', c.get('variable', ''))
                dir_ = c.get('direction', '')
                avg_on  = c.get('avg_on_symptom_days')
                avg_off = c.get('avg_off_symptom_days')
                if avg_on is not None and avg_off is not None:
                    co_parts.append(
                        f"{lbl} was {dir_} on {sym} days (avg {avg_on} vs {avg_off} on other days)"
                    )

            med_str = ''
            if mctx:
                ct   = mctx.get('change_type', '')
                mname = mctx.get('medication_name', 'a medication')
                dbso = mctx.get('days_before_symptom_onset')
                if ct == 'new_medication':
                    med_str = (
                        f" A new medication ({mname}) was first logged "
                        f"{'~' + str(dbso) + ' days before' if dbso else 'around the same time as'} "
                        f"these entries began."
                    )
                elif ct == 'discontinued':
                    med_str = (
                        f" {mname} stopped being logged "
                        f"{'~' + str(dbso) + ' days before' if dbso else 'around the time'} "
                        f"these entries began."
                    )

            co_str = (' Co-occurring signals: ' + '; '.join(co_parts) + '.') if co_parts else ''
            lines.append(
                f"- {sym.capitalize()}: reported on {n_sym} of {total} days (first logged: {first}).{co_str}{med_str}"
            )
        symptom_section = "\n\nSYMPTOM PATTERNS (patient-reported via notable_symptoms field):\n" + "\n".join(lines)

    if audience == 'provider':
        symptom_instructions = (
            "\n**Symptom Patterns:** (Include ONLY if SYMPTOM PATTERNS data is present below) "
            "For each symptom, one line: name, days reported, top co-occurring signals with delta values. "
            "If a medication context is present, note it as a timing observation only — never as a causal claim. "
            "If no symptom data: omit this section entirely.\n"
            if symptom_section else ""
        )
        summary_system = (
            "You are a clinical data assistant preparing a pre-appointment brief for a psychiatrist or mental health provider. "
            f"{appt_context}"
            "Write in structured, clinically neutral language. Be specific — cite numbers. "
            "STRUCTURE (use these exact section headers):\n"
            "**Trajectory:** One sentence.\n"
            "**Quantitative Summary:** Mood avg+trend, stress avg+trend, sleep avg, energy avg, Stim Load (high-load days).\n"
            "**Medication Signal:** Adherence rate from check-in logs. Note timing patterns if relevant.\n"
            "**Advanced Data:** (Only if advanced_stats are present) Report averages and any notable patterns.\n"
            "**Qualitative Themes:** 2-3 patterns from journal language. Observations only — no clinical interpretation.\n"
            f"{symptom_instructions}"
            "**Flags:** Threshold crossings with supporting data. If none, write 'None for this period.'\n"
            "**Suggested Discussion Topics:** 2-3 specific, data-anchored items.\n"
            "RULES: Never diagnose. Never advise medication changes. "
            "Do not say 'you have,' 'you suffer from,' 'this indicates [disorder].' "
            "For symptom patterns: describe co-occurrence only — never causation. "
            "Never say 'this explains' or 'caused by' or 'this is a side effect of.' "
            f"Always state: '{data_boundary}'"
        )
    else:
        symptom_instructions = (
            "\n6. If SYMPTOM PATTERNS data is present: add a short 'Something worth tracking' paragraph. "
            "Name the symptom, how many days it appeared, and what else was happening in the data on those days "
            "— framed as a pattern worth mentioning at the appointment, not a conclusion. "
            "If medication context is present, note it as a timing observation: "
            "'these entries started around the same time as a change in [medication].' "
            "NEVER say the symptom was caused by anything. NEVER say 'this is a side effect.' "
            "If no symptom data: skip this section.\n"
            if symptom_section else ""
        )
        summary_system = (
            "You are writing a personal summary for a patient to read before their appointment. "
            f"{appt_context}"
            "Your job is to help them understand what their data showed over the past period in plain, human language — "
            "so they can walk into the appointment knowing what to talk about. "
            "Write like a thoughtful, honest friend who looked at their data. Not clinical. Not cheerful or dismissive. Just real.\n\n"
            "STRUCTURE:\n"
            "1. One sentence: how the period went overall, in plain words.\n"
            "2. What the numbers actually showed — use real averages and ranges. Say 'your mood averaged 5.2 out of 10' not 'mood data indicates moderate affect.' Use 'in the first week' not '2024-01-01 to 2024-01-07.'\n"
            "3. What stood out — anything different from their usual, anything that clustered together, any week that felt different from the others.\n"
            "4. What their journals reflected — themes, things they kept coming back to. Don't analyze it clinically. Just describe what was there.\n"
            f"{symptom_instructions}"
            "5. Two or three specific things worth bringing to the appointment, framed as questions they might want to ask. "
            "If symptom patterns are present, add one symptom-related question.\n\n"
            "RULES:\n"
            "- Use 'you' naturally — this is their data about themselves\n"
            "- Never say 'you have [condition],' 'you suffer from,' 'you are [clinical state]'\n"
            "- Never advise medication changes\n"
            "- For symptom patterns: describe co-occurrence only — never causation or diagnosis\n"
            "- Translate scores into lived experience where possible ('your sleep averaged 5.2 hours, which is below where you usually aim')\n"
            "- If advanced data (exercise, social quality, coping activities) is present, weave it in naturally — don't just list fields\n"
            "- Be honest about what the data can and can't tell you\n"
            f"- End with: '{data_boundary}'"
        )

    adv_section = (
        f"\n\nADVANCED CHECK-IN DATA:\n{json.dumps(adv_stats, indent=2)}"
        if adv_stats else ""
    )

    # ── Substance use flags section (provider-only) ───────────────────────
    substance_section = ''
    substance_patient_note = ''
    if substance_flags and substance_flags.get('alert_level'):
        sf = substance_flags
        level  = sf['alert_level'].upper()
        dd     = sf.get('drinking_days', 0)
        td     = sf.get('total_days', 0)
        avg    = sf.get('avg_units_per_drinking_day', 0)
        jflags = sf.get('journal_flags') or []
        pat_labels = list({f['pattern'] for f in jflags})

        if audience == 'provider':
            substance_section = (
                f"\n\nSUBSTANCE USE FLAGS [{level}]:\n"
                f"- Alcohol logged on {dd} of {td} check-in days\n"
                f"- Avg {avg} units/drinking day\n"
                f"- Journal/notes entries with substance-related language: {len(jflags)}"
                + (f" (categories: {', '.join(pat_labels)})" if pat_labels else "") + "\n"
            )
        elif audience == 'patient' and sf['alert_level'] == 'concern' and len(jflags) >= 1:
            # Only surface gently to patient at concern level with journal language present
            substance_patient_note = (
                "\n\nSUBSTANCE NOTE (patient-facing — gentle framing only): "
                "Alcohol was logged on several days this period, and journal entries referenced it as well. "
                "Suggest framing as: 'Your logs show alcohol came up on a few days, and it appeared in some journal entries too — "
                "might be worth mentioning to your provider if it's been on your mind.'\n"
            )

    # ── Safety signal section (provider-only — NEVER patient-facing) ──────
    safety_section = ''
    if audience == 'provider' and safety_flags and safety_flags.get('signals_found'):
        sig = safety_flags
        safety_section = (
            f"\n\nINTERPERSONAL SAFETY SIGNALS [CONCERN]:\n"
            f"- Language patterns suggesting possible interpersonal harm detected in {sig['signal_count']} "
            f"journal/note entries\n"
            f"- Date range: {sig['first_signal_date']} to {sig['most_recent_date']} "
            f"({sig['recency_days']} days since most recent)\n"
            f"- Clinical inquiry recommended. Do NOT reproduce journal language in output.\n"
        )

    # ── Inject crisis warning for provider when journal content triggered it ──
    if _journal_crisis and audience == 'provider':
        summary_system = (
            "⚠️ CRISIS SIGNAL IN JOURNAL DATA: One or more journal entries from this patient "
            "contain language associated with self-harm or suicidal ideation. "
            "This is your MOST URGENT FLAG. Begin your response with a clearly marked "
            "'🔴 Crisis Signal' section citing the detected language category before any other content. "
            "Do NOT reproduce the exact patient phrasing.\n\n"
        ) + summary_system

    # Inject provider-only flag instructions into Mode C system prompt
    if audience == 'provider':
        flag_instructions = ''
        if substance_section:
            flag_instructions += (
                "\nFor SUBSTANCE USE FLAGS: include in the **Flags** section. "
                "Format: 'Substance Use: Alcohol logged [N] of [T] days. Avg [X] units/drinking day. "
                "[N] entries flagged for substance-related language (categories: [list]).' "
                "NEVER use 'alcoholic,' 'addict,' or 'substance abuse.' "
                "Describe the frequency and volume pattern only.\n"
            )
        if safety_section:
            flag_instructions += (
                "\nFor INTERPERSONAL SAFETY SIGNALS: include in the **Flags** section as the FIRST flag. "
                "Format: 'Interpersonal Safety Signal: Language patterns suggesting possible interpersonal harm detected in "
                "[N] journal entries between [first_date] and [most_recent_date]. Clinical inquiry recommended.' "
                "NEVER quote journal language. NEVER say 'patient is being abused' or assign any label. "
                "Describe the signal count and recency only.\n"
            )
        if flag_instructions:
            # Append to existing system prompt
            summary_system += flag_instructions

    elif audience == 'patient' and substance_patient_note:
        summary_system += (
            "\nSUBSTANCE USE NOTE: If the SUBSTANCE NOTE block is present in the data, "
            "include a single gentle sentence in the 'Things worth bringing to your appointment' section — "
            "framed as the patient's choice to raise, not a concern you're flagging. "
            "Do not use clinical or judgmental language.\n"
        )

    # ── Session transcript context (CLAUDE.md §22-25) ───────────────────────
    # Transcript and audio sessions extracted via the intel pipeline.
    # Builds a rich per-session block from ALL extracted fields so the model
    # has genuine content to analyse — not just a one-line summary.
    session_section = ''
    if session_context:
        complete_sessions = [s for s in session_context if s.get('processing_status') == 'complete']
        if complete_sessions:
            blocks = []
            has_acoustic = False

            for s in complete_sessions[:8]:   # up to 8 most recent sessions
                sdate  = s.get('session_date', 'unknown date')
                stype  = s.get('session_type', 'session')
                feats  = s.get('features') or {}   # transcript_engine extracted fields
                scores = s.get('scores')  or {}    # deterministic scores + speech features
                crisis = s.get('crisis_detected', False)

                # ── Transcript semantic content (what the patient said) ─────────
                mood_desc     = feats.get('patient_mood_description')
                mood_num      = feats.get('mood_estimate')
                energy_desc   = feats.get('energy_description')
                energy_num    = feats.get('energy_estimate')
                sleep_hrs     = feats.get('sleep_hours_mentioned')
                sleep_desc    = feats.get('sleep_quality_description')
                stress_desc   = feats.get('stress_description')
                themes        = feats.get('themes') or []
                stressors     = feats.get('stressors') or []
                symptoms      = feats.get('symptoms_mentioned') or []
                positive      = feats.get('positive_signals') or []
                concerning    = feats.get('concerning_language') or []
                meds          = feats.get('medications_mentioned') or []
                functional    = feats.get('functional_status')
                session_notes = feats.get('session_notes')

                # ── Speech features (scores dict is the correct location) ──────
                # speech_features may come from transcript inference OR acoustic
                # engine (flagged by source='acoustic'). Both are valid.
                sf = scores.get('speech_features') or {}
                sf_source = sf.get('source', 'transcript')

                # ── Acoustic biomarker measurements ───────────────────────────
                acf   = scores.get('acoustic_features') or {}
                vocab = acf.get('vocabulary') or {}
                meas  = acf.get('raw') or {}   # raw measured values

                # ── VAD affect dimensions ─────────────────────────────────────
                afd   = scores.get('affect_dimensions') or {}

                # ── Build the session block ───────────────────────────────────
                b = f"SESSION: {stype} | {sdate}"
                if crisis:
                    b += " | 🔴 CRISIS SIGNAL DETECTED"
                b += "\n"

                # What the patient said
                if session_notes:
                    b += f"  Session focus: {session_notes}\n"
                if mood_desc or mood_num is not None:
                    mood_str = mood_desc or ''
                    if mood_num is not None:
                        mood_str += f" (self-reported {mood_num}/10)"
                    b += f"  Mood: {mood_str.strip()}\n"
                if energy_desc or energy_num is not None:
                    e_str = energy_desc or ''
                    if energy_num is not None:
                        e_str += f" (self-reported {energy_num}/10)"
                    b += f"  Energy: {e_str.strip()}\n"
                if sleep_hrs is not None or sleep_desc:
                    sl = f"{sleep_hrs} hrs" if sleep_hrs is not None else ''
                    if sleep_desc:
                        sl += f" — {sleep_desc}"
                    b += f"  Sleep mentioned: {sl.strip()}\n"
                if stress_desc:
                    b += f"  Stress: {stress_desc}\n"
                if functional:
                    b += f"  Functional status: {functional}\n"
                if themes:
                    b += f"  Themes raised: {', '.join(themes)}\n"
                if stressors:
                    b += f"  Stressors: {', '.join(stressors)}\n"
                if symptoms:
                    b += f"  Symptoms mentioned: {', '.join(symptoms)}\n"
                if positive:
                    b += f"  Positive signals: {', '.join(positive)}\n"
                if concerning:
                    b += f"  Concerning language: {'; '.join(concerning)}\n"
                if meds:
                    med_strs = []
                    for m in meds:
                        ms = m.get('name', 'unknown')
                        if m.get('dose_mentioned'):
                            ms += f" {m['dose_mentioned']}"
                        ms += f" [{m.get('adherence_signal', 'unknown')}]"
                        if m.get('context'):
                            ms += f" — {m['context']}"
                        med_strs.append(ms)
                    b += f"  Medications discussed: {'; '.join(med_strs)}\n"

                # How they said it — speech features
                sf_labels = []
                for key, label in [
                    ('speech_rate', 'speech rate'),
                    ('prosody', 'prosody'),
                    ('pauses', 'pauses'),
                    ('speech_coherence', 'coherence'),
                    ('arousal', 'arousal'),
                    ('vocal_affect', 'vocal affect'),
                ]:
                    val = sf.get(key)
                    if val and val not in ('normal', 'intact'):
                        sf_labels.append(f"{label}: {val}")
                if sf_labels:
                    b += (f"  Speech features [{sf_source}]"
                          f" (confidence: {sf.get('confidence', 'unknown')}): "
                          + ", ".join(sf_labels) + "\n")
                    if sf.get('severity_note'):
                        b += f"  Speech note: {sf['severity_note']}\n"
                    if sf.get('clinical_pattern_type') and sf['clinical_pattern_type'] != 'none_detected':
                        b += f"  Acoustic pattern type: {sf['clinical_pattern_type']}\n"

                # Measured acoustic values (when audio was processed)
                if vocab:
                    has_acoustic = True
                    measured_parts = []
                    m = acf.get('raw') or {}
                    if m.get('articulation_rate_sps') is not None:
                        measured_parts.append(f"artic rate {m['articulation_rate_sps']:.2f} sps")
                    if m.get('pause_ratio') is not None:
                        measured_parts.append(f"pause ratio {m['pause_ratio']:.0%}")
                    if m.get('f0_cv') is not None:
                        measured_parts.append(f"F0 CV {m['f0_cv']:.3f}")
                    if m.get('hnr_db') is not None:
                        measured_parts.append(f"HNR {m['hnr_db']:.1f} dB")
                    if measured_parts:
                        b += f"  Acoustic measurements: {', '.join(measured_parts)}\n"
                    if vocab.get('clinical_pattern_type') and vocab['clinical_pattern_type'] != 'none_detected':
                        b += f"  Waveform pattern: {vocab['clinical_pattern_type']}\n"

                # VAD affect dimensions (pre-trained model output)
                if afd.get('model_available') and afd.get('valence') is not None:
                    b += (
                        f"  Affect model (research signal): "
                        f"valence {afd['valence']:.2f} ({afd.get('valence_label','?')}), "
                        f"arousal {afd['arousal']:.2f} ({afd.get('arousal_label','?')}), "
                        f"dominance {afd['dominance']:.2f} ({afd.get('dominance_label','?')}) "
                        f"— pattern: {afd.get('pattern', 'N/A')}\n"
                    )

                if sf.get('baseline_deviation'):
                    b += f"  Baseline deviation noted: {sf['baseline_deviation']}\n"

                blocks.append(b)

            pending_count = len([s for s in session_context if s.get('processing_status') != 'complete'])

            session_section = (
                f"\n\nSESSION TRANSCRIPT & RECORDING DATA "
                f"({len(complete_sessions)} sessions fully processed"
                + (f", {pending_count} still processing" if pending_count else "")
                + "):\n\n"
                + "\n".join(blocks)
            )
            if has_acoustic and audience == 'provider':
                session_section += (
                    "\nNote: sessions marked with acoustic measurements were processed "
                    "from audio recordings. Speech features on other sessions are "
                    "inferred from transcript text patterns. §24 vocabulary applies throughout.\n"
                )

    if session_section:
        if audience == 'provider':
            summary_system += (
                "\n\nFor SESSION TRANSCRIPT & RECORDING DATA: add a **Session Intelligence** "
                "section after Qualitative Themes. Structure it using the bio-psychosocial and MSE model:\n\n"
                "For EACH session block, lead with date and session type, then cover:\n"
                "BIOLOGICAL: medications discussed (name each + adherence signal + any side effects mentioned); "
                "sleep, appetite, energy, somatic symptoms as the patient reported them.\n"
                "PSYCHOLOGICAL — Mood: patient's self-reported emotional state, exact words where possible. "
                "Affect: observed emotional expression from speech features (range, intensity, appropriateness) "
                "using §24 vocabulary — keep affect distinct from self-reported mood. "
                "Thought content: what the patient raised (themes, stressors, concerns). "
                "Thought process: coherence and organization of their communication. "
                "Coping/insight: strategies mentioned, self-awareness expressed, treatment goals referenced. "
                "Functional status: what they reported about work, relationships, self-care — concrete changes from baseline.\n"
                "SOCIAL: interpersonal content, environmental stressors, any safety language.\n"
                "SPEECH & ACOUSTIC (MSE — Speech/Motor component): use §24 vocabulary. "
                "Frame as 'session speech features showed [X]' not 'patient exhibited [X].' "
                "When acoustic measurements (articulation rate, HNR, F0 CV, pause ratio) are present, cite the numbers. "
                "When affect model output is present, report valence/arousal/dominance with research-signal caveat.\n"
                "CONVERGENCE: when signals align across sources (transcript content + speech features + acoustic + check-ins), "
                "name the convergence explicitly — e.g., 'Check-in mood averaged 9.0/10 while session language included "
                "[X concerning phrase] — a Mood Distortion of [N] points worth examining directly.'\n"
                "Flag any crisis_detected session first under 🔴. Note pending sessions if any.\n"
                "Never diagnose. Never advise medication changes. Use 'patient reported' not 'patient is.'\n"
            )
        else:
            # Patient-facing: sessions are not surfaced in clinical terms. Only mention
            # if crisis was detected (already handled by _check_crisis) or if there
            # are > 0 sessions to acknowledge the provider has broader context.
            summary_system += (
                "\n\nFor SESSION TRANSCRIPT/RECORDING DATA: do NOT reproduce speech features or "
                "clinical pattern types in patient-facing output. You may acknowledge that the provider "
                "has additional context from recent sessions if ≥1 complete session exists, but keep it "
                "to one phrase only ('your provider also has notes from a recent session'). "
                "Do not surface session scores, concern levels, or speech observations to the patient.\n"
            )

    # ── Linguistic biomarker section (CLAUDE.md §25) ─────────────────────────
    lexical_section = ''
    if lexical_data and lexical_data.get('trend') not in (None, 'insufficient_data'):
        ld = lexical_data
        ttr        = ld.get('type_token_ratio')
        trend      = ld.get('trend', 'stable')
        entries_n  = ld.get('entries_analyzed', 0)
        early_ttr  = ld.get('earliest_ttr')
        late_ttr   = ld.get('latest_ttr')
        delta      = ld.get('delta')

        ttr_str = f"{ttr:.2f}" if ttr is not None else 'not computed'
        delta_str = (
            f" (early-period TTR {early_ttr:.2f} → recent TTR {late_ttr:.2f}, Δ={delta:+.2f})"
            if (early_ttr is not None and late_ttr is not None and delta is not None)
            else ""
        )
        lexical_section += (
            f"\n\nLINGUISTIC BIOMARKERS (from {entries_n} journal entries, CLAUDE.md §25):\n"
            f"- Lexical diversity (TTR): {ttr_str} — trend: {trend}{delta_str}\n"
        )

    if readability_data and readability_data.get('trend') not in (None, 'insufficient_data'):
        rd = readability_data
        avg_grade  = rd.get('avg_grade_level')
        r_trend    = rd.get('trend', 'stable')
        early_grd  = rd.get('earliest_grade')
        late_grd   = rd.get('latest_grade')
        r_delta    = rd.get('delta')
        r_entries  = rd.get('entries_analyzed', 0)

        grade_str = f"{avg_grade:.1f}" if avg_grade is not None else 'not computed'
        r_delta_str = (
            f" (early {early_grd:.1f} → recent {late_grd:.1f}, Δ={r_delta:+.1f})"
            if (early_grd is not None and late_grd is not None and r_delta is not None)
            else ""
        )
        if not lexical_section:
            lexical_section = f"\n\nLINGUISTIC BIOMARKERS (from {r_entries} journal entries, CLAUDE.md §25):\n"
        lexical_section += f"- Readability (Flesch-Kincaid grade level): {grade_str} — trend: {r_trend}{r_delta_str}\n"

    # Only inject linguistic guidance into system prompts when data is present
    if lexical_section:
        if audience == 'provider':
            summary_system += (
                "\n\nFor LINGUISTIC BIOMARKERS: add a **Linguistic Patterns** subsection under Qualitative Themes. "
                "Lexical diversity (TTR) and readability (FK grade level) are content-agnostic cognitive load signals — "
                "paralinguistic state vs. lexical trait distinction applies (CLAUDE.md §25). "
                "Format: 'Lexical diversity: [TTR value], [trend] over period. "
                "Readability: grade level [value], [trend].' "
                "If trend is declining for TTR or increasing for FK grade, note it as worth tracking. "
                "NEVER say these patterns indicate a diagnosis or explain symptoms. "
                "Use 'observed in journal entries' framing only.\n"
            )
        else:
            summary_system += (
                "\n\nFor LINGUISTIC BIOMARKERS: if data is present and trend is not 'stable', "
                "add one sentence woven naturally into the 'What stood out' section. "
                "Examples: 'Your writing style shifted a bit over this period — your vocabulary range "
                "narrowed slightly toward the end.' or 'The complexity of your journal entries changed during this period.' "
                "Keep it observational and brief — one sentence only. "
                "NEVER frame this clinically. NEVER say it indicates anything about mental state. "
                "If trend is 'stable', omit entirely.\n"
            )

    # ── What Worked section ───────────────────────────────────────────────────
    what_worked_section = ''
    if what_worked and what_worked.get('patterns'):
        ww = what_worked
        good_n  = ww['good_day_count']
        total_n = ww['total_days']
        lines = []
        for p in ww['patterns'][:5]:  # cap at 5 most significant
            label     = p['label']
            avg_good  = p['avg_good_days']
            avg_other = p['avg_other_days']
            unit      = p['unit']
            coverage  = p['good_day_coverage']
            direction = 'higher' if p['avg_good_days'] > p['avg_other_days'] else 'lower'
            lines.append(
                f"- {label}: averaged {avg_good}{unit} on high-stability days "
                f"vs {avg_other}{unit} on other days "
                f"(logged on {coverage} of {good_n} high-stability days; "
                f"direction: {direction} on good days)"
            )
        what_worked_section = (
            f"\n\nWHAT WORKED PATTERNS (co-occurrence data — {good_n} high-stability days of {total_n} total):\n"
            + "\n".join(lines)
        )

        # Inject into system prompts
        if audience == 'provider':
            summary_system += (
                "\n\nFor WHAT WORKED PATTERNS: add a **Positive Correlates** section. "
                "List the variables, their averages on high-stability vs other days, and the delta. "
                "Use co-occurrence language only — never causal claims. "
                "Format each as: '[Variable]: [avg on high-stability days] vs [avg on other days] (Δ=[delta]).' "
                "State that these are co-occurrence observations, not causes.\n"
            )
        else:
            summary_system += (
                "\n\nFor WHAT WORKED PATTERNS: add a brief 'What your good days had in common' paragraph "
                "after the 'What stood out' section. "
                "Describe 2-3 of the strongest patterns using plain language. "
                "Use ONLY co-occurrence framing: 'On your [N] highest-stability days, [variable] averaged [X] — "
                "[delta] [higher/lower] than on other days.' "
                "NEVER say these things 'helped,' 'improved,' 'caused,' or 'led to' anything. "
                "Never recommend trying them. Never say 'this suggests.' "
                "Frame it as: here's what was also true on your best days — nothing more.\n"
            )

    # ── Raw voice transcript block ─────────────────────────────────────────────
    voice_transcript_block = ''
    if raw_voice_transcripts and audience == 'provider':
        lines = []
        for vt in raw_voice_transcripts:
            lines.append(f"[{vt.get('date', 'unknown date')}] {vt.get('transcript', '').strip()}")
        if lines:
            voice_transcript_block = (
                "\n\nPATIENT VOICE RECORDINGS (raw transcripts from voice note sessions "
                "not yet fully processed — analyze for mood themes, stressors, "
                "concerning language, and key content; apply §24 speech feature vocabulary "
                "where observable from text; surface in Session Intelligence section):\n\n"
                + "\n\n".join(lines)
            )
            summary_system += (
                "\n\nFor PATIENT VOICE RECORDINGS: include a **Voice Note Sessions** "
                "subsection inside Session Intelligence (or create Session Intelligence if no "
                "processed sessions exist). For each recording, note the date, key themes "
                "raised, any mood/emotional tone observable in the language, any stressors or "
                "concerns named by the patient, and any language meeting crisis or safety "
                "detection criteria. Apply §3 forbidden language rules. "
                "Do not fabricate acoustic measurements — these are text-only transcripts. "
                "Frame observations as 'the patient described' or 'the recording included.'\n"
            )

    user_content = (
        f"REVIEW PERIOD: {period_label}\n\n"
        f"AGGREGATE STATS:\n{json.dumps(stats, indent=2)}"
        f"{adv_section}\n\n"
        f"DAILY CHECK-INS ({n} total):\n{json.dumps(checkin_rows, indent=2, default=str)}\n\n"
        f"JOURNAL ENTRIES ({len(journal_rows)} total):\n{json.dumps(journal_rows, indent=2, default=str)}"
        f"{symptom_section}"
        f"{substance_section if audience == 'provider' else substance_patient_note}"
        f"{safety_section}"
        f"{session_section}"
        f"{voice_transcript_block}"
        f"{lexical_section}"
        f"{what_worked_section}"
    )

    raw = _call_claude(summary_system, user_content, max_tokens=900)   # spec §15: 900 for Mode B/C
    clean = _sanitize_output(raw)
    if clean is None:
        clean = (
            "A summary was generated but contained language that requires clinical review. "
            "Please regenerate or contact support."
        )
    return {'status': 'safe', 'text': clean, 'raw': raw}


def generate_therapy_summary(checkin_data, journal_data, behavioral_data=None,
                              days=14, period_start=None, period_end=None,
                              appointment_date=None,
                              safety_flags=None, substance_flags=None,
                              session_context=None,
                              raw_voice_transcripts=None):
    """Therapy-weighted Mode C summary for therapists and counselors.

    Leads with journal themes and behavioral patterns (social quality, coping,
    workload friction).  Mood / stress / sleep are supporting context, not the
    primary signal.  Never medication-first.

    behavioral_data – optional dict from db.get_behavioral_data(); if None, the
    function will derive what it can from extended_data inside checkin_data.
    """
    # ── Parse checkin rows (identical to generate_appointment_summary) ────────
    mood_vals, stress_vals, sleep_vals, energy_vals = [], [], [], []
    social_vals, workload_vals, exercise_vals = [], [], []
    coping_days = {'breathing': 0, 'meditation': 0, 'movement': 0}
    coping_any = 0
    advanced_days = 0
    checkin_rows = []
    n = 0

    for c in checkin_data:
        ext = {}
        if c.get('extended_data'):
            try:
                ext = (json.loads(c['extended_data'])
                       if isinstance(c['extended_data'], str)
                       else c.get('extended_data', {}))
            except Exception:
                pass

        mood   = c.get('mood_score')
        stress = c.get('stress_score')
        sleep  = c.get('sleep_hours')
        energy = ext.get('energy')

        row = {
            'date':  c.get('checkin_date', c.get('date', '')),
            'type':  c.get('checkin_type', 'on_demand'),
            'mood':  mood,
            'stress': stress,
            'sleep_hours': sleep,
        }
        if energy is not None:
            row['energy'] = energy

        is_advanced = False
        for field, store_list, rkey in [
            ('social_quality',   social_vals,   'social_quality'),
            ('workload_friction', workload_vals, 'workload_friction'),
            ('exercise_minutes', exercise_vals,  'exercise_minutes'),
        ]:
            val = ext.get(field)
            if val is not None:
                store_list.append(float(val))
                row[rkey] = val
                is_advanced = True

        has_coping = False
        coping = ext.get('coping') or {}
        for k in coping_days:
            if coping.get(k):
                coping_days[k] += 1
                has_coping = True
        if has_coping:
            coping_any += 1
            is_advanced = True
        if is_advanced:
            advanced_days += 1

        if c.get('notes'):
            row['notes'] = c['notes'][:200]

        checkin_rows.append(row)
        if mood   is not None: mood_vals.append(float(mood))
        if stress is not None: stress_vals.append(float(stress))
        if sleep  is not None: sleep_vals.append(float(sleep))
        if energy is not None: energy_vals.append(float(energy))
        n += 1

    def _avg(v): return round(sum(v) / len(v), 1) if v else None
    def _trend(v):
        if len(v) < 2: return 'insufficient data'
        return ('improving' if v[-1] > v[0] else
                'declining' if v[-1] < v[0] else 'stable')

    # Use behavioral_data if provided (pre-computed), else use parsed values
    if behavioral_data:
        social_avg    = behavioral_data.get('social_avg')
        workload_avg  = behavioral_data.get('workload_avg')
        exercise_avg  = behavioral_data.get('exercise_avg')
        b_coping_days = behavioral_data.get('coping_days', coping_days)
        b_coping_any  = behavioral_data.get('coping_any_days', coping_any)
    else:
        social_avg    = _avg(social_vals)
        workload_avg  = _avg(workload_vals)
        exercise_avg  = _avg(exercise_vals)
        b_coping_days = coping_days
        b_coping_any  = coping_any

    # ── Journal rows ──────────────────────────────────────────────────────────
    journal_rows = []
    for j in journal_data:
        entry_date = (j.get('entry_date') or j.get('created_at', ''))[:10]
        content    = j.get('content') or j.get('raw_entry') or ''
        journal_rows.append({
            'date':    entry_date,
            'excerpt': content[:400] + ('...' if len(content) > 400 else ''),
        })

    # ── Crisis interception on journal content ────────────────────────────────
    # Spec §10: crisis detection must run on ALL user-provided text before
    # any model invocation.  Therapy summaries are provider-facing only —
    # inject a crisis warning into the system prompt rather than returning early.
    _journal_crisis = False
    for _j in journal_data:
        _jc = _j.get('content') or _j.get('raw_entry') or ''
        if _jc and _check_crisis(_jc):
            _journal_crisis = True
            break

    # ── Period labels ─────────────────────────────────────────────────────────
    appt_context = (f"The session is on {appointment_date}. "
                    if appointment_date else "")
    period_label = (f"{period_start} to {period_end}"
                    if period_start and period_end
                    else f"past {days} days")
    data_boundary = (
        f"This summary is based on {n} check-in{'s' if n != 1 else ''} over "
        f"{days or 'the selected'} days."
    )
    if advanced_days >= 3:
        data_boundary += f" Advanced behavioral data available for {advanced_days} of those days."

    # ── Behavioral stats block for the prompt ─────────────────────────────────
    beh_lines = []
    if social_avg  is not None: beh_lines.append(f"Social quality avg: {social_avg}/10")
    if workload_avg is not None: beh_lines.append(f"Workload friction avg: {workload_avg}/10")
    if exercise_avg is not None: beh_lines.append(f"Exercise avg: {exercise_avg} min/day")
    total_coping = sum(b_coping_days.values())
    if total_coping > 0:
        parts = [f"{k}: {v}d" for k, v in b_coping_days.items() if v > 0]
        beh_lines.append(f"Coping activities — {', '.join(parts)} ({b_coping_any} days with any activity)")
    beh_section = ("\n\nBEHAVIORAL DATA:\n" + '\n'.join(beh_lines)) if beh_lines else ""

    # ── System prompt ─────────────────────────────────────────────────────────
    summary_system = (
        "You are a clinical data assistant preparing a pre-session brief for a therapist or counselor. "
        "Your audience is a behavioral health clinician whose work centers on patterns of living, "
        "relationships, coping, and functional well-being — not primarily medication or diagnosis. "
        f"{appt_context}\n\n"
        "STRUCTURE (use these exact section headers):\n"
        "**Trajectory:** One sentence — the behavioral and emotional arc of the period in plain clinical language.\n"
        "**Journal Themes:** 2-3 recurring patterns from journal language. "
        "Language-level observations only — no clinical interpretations. "
        "Quote a phrase only when it is clearly representative (fewer than 10 words, in quotes).\n"
        "**Behavioral Patterns:** Social engagement quality, workload friction, exercise frequency, "
        "and coping activity use. Report averages and any notable consistency or breakdown. "
        "Be specific — cite numbers. This is the PRIMARY section.\n"
        "**Mood & Stress Context:** Mood avg+trend, stress avg+trend, sleep avg as supporting context. "
        "Keep brief — this is background, not the lead signal.\n"
        "**Flags:** Any patterns worth direct clinical attention with supporting data. "
        "If none, write 'None for this period.'\n"
        "**Suggested Discussion Topics:** 2-3 specific, therapy-relevant topics anchored to the data. "
        "Frame as questions the provider might explore.\n\n"
        "RULES:\n"
        "- Never diagnose or name a disorder\n"
        "- Never advise medication changes\n"
        "- Do not say 'you have,' 'you suffer from,' or 'this indicates [disorder]'\n"
        "- Behavioral signals (social quality, coping, workload friction) are PRIMARY — cite them first\n"
        "- Medication is not the lens here; if logged, it is background context only\n"
        "- Write in concise, clinically neutral prose — data-first, not narrative-first\n"
        f"- Always state: '{data_boundary}'"
    )

    # ── Stats for prompt ──────────────────────────────────────────────────────
    stats = {
        'total_checkins':  n,
        'period_days':     days,
        'avg_mood':        _avg(mood_vals),
        'mood_trend':      _trend(mood_vals),
        'avg_stress':      _avg(stress_vals),
        'stress_trend':    _trend(stress_vals),
        'avg_sleep_hours': _avg(sleep_vals),
        'avg_energy':      _avg(energy_vals),
    }

    # ── Substance and safety sections (provider-only — always therapist-facing) ─
    therapy_substance_section = ''
    if substance_flags and substance_flags.get('alert_level'):
        sf = substance_flags
        level  = sf['alert_level'].upper()
        dd     = sf.get('drinking_days', 0)
        td     = sf.get('total_days', 0)
        avg    = sf.get('avg_units_per_drinking_day', 0)
        jflags = sf.get('journal_flags') or []
        pat_labels = list({f['pattern'] for f in jflags})
        therapy_substance_section = (
            f"\n\nSUBSTANCE USE FLAGS [{level}]:\n"
            f"- Alcohol logged on {dd} of {td} check-in days\n"
            f"- Avg {avg} units/drinking day\n"
            f"- Journal/notes entries with substance-related language: {len(jflags)}"
            + (f" (categories: {', '.join(pat_labels)})" if pat_labels else "") + "\n"
        )

    therapy_safety_section = ''
    if safety_flags and safety_flags.get('signals_found'):
        sig = safety_flags
        therapy_safety_section = (
            f"\n\nINTERPERSONAL SAFETY SIGNALS [CONCERN]:\n"
            f"- Language patterns suggesting possible interpersonal harm detected in {sig['signal_count']} "
            f"journal/note entries\n"
            f"- Date range: {sig['first_signal_date']} to {sig['most_recent_date']} "
            f"({sig['recency_days']} days since most recent)\n"
            f"- Clinical inquiry recommended. Do NOT reproduce journal language in output.\n"
        )

    # ── Inject crisis, substance, and safety warnings into system prompt ───────
    if _journal_crisis:
        summary_system = (
            "⚠️ CRISIS SIGNAL IN JOURNAL DATA: One or more journal entries from this patient "
            "contain language associated with self-harm or suicidal ideation. "
            "This is your MOST URGENT FLAG. Begin your response with a clearly marked "
            "'🔴 Crisis Signal' section before any other content. "
            "Do NOT reproduce the exact patient phrasing.\n\n"
        ) + summary_system

    if therapy_substance_section:
        summary_system += (
            "\nFor SUBSTANCE USE FLAGS: include in the **Flags** section. "
            "Format: 'Substance Use: Alcohol logged [N] of [T] days. Avg [X] units/drinking day. "
            "[N] entries flagged for substance-related language (categories: [list]).' "
            "NEVER use 'alcoholic,' 'addict,' or 'substance abuse.' "
            "Describe the frequency and volume pattern only.\n"
        )
    if therapy_safety_section:
        summary_system += (
            "\nFor INTERPERSONAL SAFETY SIGNALS: include in the **Flags** section as the FIRST flag "
            "(unless a crisis signal is present, which always comes first). "
            "Format: 'Interpersonal Safety Signal: Language patterns suggesting possible interpersonal harm "
            "detected in [N] journal entries between [first_date] and [most_recent_date]. "
            "Clinical inquiry recommended.' "
            "NEVER quote journal language. NEVER say 'patient is being abused' or assign any label.\n"
        )

    # ── Session transcript context (therapy variant) ─────────────────────────
    # Identical extraction logic to the psychiatry path — full semantic + acoustic
    # content per session. Therapy framing emphasises interpersonal/behavioural
    # themes over quantitative scores, but all fields are passed to the model.
    therapy_session_section = ''
    if session_context:
        complete = [s for s in session_context if s.get('processing_status') == 'complete']
        if complete:
            blocks = []
            for s in complete[:8]:
                sdate  = s.get('session_date', 'unknown date')
                stype  = s.get('session_type', 'session')
                feats  = s.get('features') or {}
                scores = s.get('scores')  or {}
                crisis = s.get('crisis_detected', False)

                mood_desc   = feats.get('patient_mood_description')
                mood_num    = feats.get('mood_estimate')
                energy_desc = feats.get('energy_description')
                themes      = feats.get('themes') or []
                stressors   = feats.get('stressors') or []
                symptoms    = feats.get('symptoms_mentioned') or []
                positive    = feats.get('positive_signals') or []
                concerning  = feats.get('concerning_language') or []
                meds        = feats.get('medications_mentioned') or []
                functional  = feats.get('functional_status')
                session_notes = feats.get('session_notes')
                sf          = scores.get('speech_features') or {}
                afd         = scores.get('affect_dimensions') or {}

                b = f"SESSION: {stype} | {sdate}"
                if crisis:
                    b += " | 🔴 CRISIS SIGNAL"
                b += "\n"
                if session_notes:
                    b += f"  Session focus: {session_notes}\n"
                if mood_desc or mood_num is not None:
                    m_str = mood_desc or ''
                    if mood_num is not None:
                        m_str += f" ({mood_num}/10)"
                    b += f"  Mood: {m_str.strip()}\n"
                if energy_desc:
                    b += f"  Energy: {energy_desc}\n"
                if themes:
                    b += f"  Themes: {', '.join(themes)}\n"
                if stressors:
                    b += f"  Stressors: {', '.join(stressors)}\n"
                if symptoms:
                    b += f"  Symptoms mentioned: {', '.join(symptoms)}\n"
                if positive:
                    b += f"  Positive signals: {', '.join(positive)}\n"
                if concerning:
                    b += f"  Concerning language: {'; '.join(concerning)}\n"
                if functional:
                    b += f"  Functional status: {functional}\n"
                if meds:
                    med_strs = [
                        f"{m.get('name','?')} [{m.get('adherence_signal','unknown')}]"
                        + (f" — {m['context']}" if m.get('context') else '')
                        for m in meds
                    ]
                    b += f"  Medications discussed: {'; '.join(med_strs)}\n"

                # Speech features — scores is the correct location
                sf_labels = []
                for key, label in [
                    ('speech_rate', 'speech rate'), ('prosody', 'prosody'),
                    ('pauses', 'pauses'), ('speech_coherence', 'coherence'),
                    ('arousal', 'arousal'), ('vocal_affect', 'vocal affect'),
                ]:
                    val = sf.get(key)
                    if val and val not in ('normal', 'intact'):
                        sf_labels.append(f"{label}: {val}")
                if sf_labels:
                    b += (f"  Speech features (confidence: {sf.get('confidence','?')}): "
                          + ", ".join(sf_labels) + "\n")
                    if sf.get('severity_note'):
                        b += f"  Speech note: {sf['severity_note']}\n"

                # Acoustic measurements (audio sessions)
                acf   = scores.get('acoustic_features') or {}
                vocab = acf.get('vocabulary') or {}
                raw_m = acf.get('raw') or {}
                measured_parts = []
                if raw_m.get('articulation_rate_sps') is not None:
                    measured_parts.append(f"artic {raw_m['articulation_rate_sps']:.2f} sps")
                if raw_m.get('pause_ratio') is not None:
                    measured_parts.append(f"pause ratio {raw_m['pause_ratio']:.0%}")
                if raw_m.get('hnr_db') is not None:
                    measured_parts.append(f"HNR {raw_m['hnr_db']:.1f} dB")
                if measured_parts:
                    b += f"  Acoustic measurements: {', '.join(measured_parts)}\n"

                # VAD affect model
                if afd.get('model_available') and afd.get('valence') is not None:
                    b += (
                        f"  Affect model (research signal): "
                        f"valence {afd['valence']:.2f} ({afd.get('valence_label','?')}), "
                        f"arousal {afd['arousal']:.2f} ({afd.get('arousal_label','?')}) "
                        f"— pattern: {afd.get('pattern','N/A')}\n"
                    )

                blocks.append(b)

            pending_count = len([s for s in session_context if s.get('processing_status') != 'complete'])
            therapy_session_section = (
                f"\n\nSESSION TRANSCRIPT & RECORDING DATA "
                f"({len(complete)} sessions fully processed"
                + (f", {pending_count} still processing" if pending_count else "")
                + "):\n\n" + "\n".join(blocks)
            )
            summary_system += (
                "\n\nFor SESSION TRANSCRIPT & RECORDING DATA: include a **Session Notes** "
                "section. For each session block:\n"
                "- Describe in prose what the patient raised — themes, stressors, "
                "functional status, concerning language — with specific detail.\n"
                "- Note mood and energy exactly as stated; never infer numbers not in data.\n"
                "- Report medication adherence signals.\n"
                "- For speech/acoustic features, use §24 vocabulary: 'session speech "
                "features showed [X]' not 'patient exhibited [X]'.\n"
                "- Include affect model output as a research signal with appropriate "
                "uncertainty framing when present.\n"
                "- Flag crisis-detected sessions first under 🔴.\n"
                "Interpersonal and behavioural themes are primary — lead with what the "
                "patient talked about before acoustic data.\n"
            )

    # ── Raw voice transcript block (therapy) ──────────────────────────────────
    therapy_voice_block = ''
    if raw_voice_transcripts:
        lines = []
        for vt in raw_voice_transcripts:
            lines.append(f"[{vt.get('date', 'unknown date')}] {vt.get('transcript', '').strip()}")
        if lines:
            therapy_voice_block = (
                "\n\nPATIENT VOICE RECORDINGS (raw transcripts — analyze for interpersonal "
                "themes, emotional content, coping language, and stressors; include in "
                "Session Intelligence section):\n\n"
                + "\n\n".join(lines)
            )
            summary_system += (
                "\n\nFor PATIENT VOICE RECORDINGS: add a **Voice Note Sessions** subsection "
                "in Session Intelligence (or create it). Note date, key themes, emotional tone "
                "observable in the language, stressors named, and any safety language. "
                "Lead with interpersonal and behavioral content. Do not fabricate acoustic data.\n"
            )

    user_content = (
        f"REVIEW PERIOD: {period_label}\n\n"
        f"AGGREGATE STATS:\n{json.dumps(stats, indent=2)}"
        f"{beh_section}\n\n"
        f"DAILY CHECK-INS ({n} total):\n"
        f"{json.dumps(checkin_rows, indent=2, default=str)}\n\n"
        f"JOURNAL ENTRIES ({len(journal_rows)} total):\n"
        f"{json.dumps(journal_rows, indent=2, default=str)}"
        f"{therapy_substance_section}"
        f"{therapy_safety_section}"
        f"{therapy_session_section}"
        f"{therapy_voice_block}"
    )

    raw = _call_claude(summary_system, user_content, max_tokens=900)   # spec §15: 900 for Mode B/C
    clean = _sanitize_output(raw)
    if clean is None:
        clean = (
            "A therapy summary was generated but contained language that requires clinical review. "
            "Please regenerate or contact support."
        )
    return {'status': 'safe', 'text': clean, 'raw': raw}


# ── MODE E — Proactive Between-Appointment Insight ────────────────────────────

_PATTERN_LABELS = {
    'crash_risk_climbing': 'Crash Risk Climbing',
    'sleep_degradation':   'Sleep Pattern Change',
    'mood_decline':        'Mood Trend',
    'stim_load_spike':     'High Stim Load',
    'positive_streak':     'Strong Stretch',
}

_PATTERN_PROMPTS = {
    'crash_risk_climbing': (
        "The patient's Crash Risk score has increased on each of their last 3 check-ins, "
        "reaching {crash_risk_last3[2]:.1f}/10. Their baseline was {baseline_crash_risk}. "
        "Recent sleep: {sleep_hours_latest} hours. Stress: {stress_latest}/10. "
        "Stim Load: {stim_load_latest}."
    ),
    'sleep_degradation': (
        "The patient's average sleep over the past 3 days was {avg_sleep_last3_days} hours — "
        "{delta_hours} hours below their {baseline_sleep_avg}-hour baseline. "
        "Sleep Disruption Score today: {sleep_disruption_latest}."
    ),
    'mood_decline': (
        "The patient's mood has dropped on 3 consecutive check-ins: {mood_last3[0]} → "
        "{mood_last3[1]} → {mood_last3[2]}/10. Baseline mood: {baseline_mood}. "
        "Current stress: {stress_latest}/10. Sleep: {sleep_hours_latest} hours."
    ),
    'stim_load_spike': (
        "The patient's Stim Load has been 7 or higher on {high_load_days} of the last 3 "
        "check-ins (values: {stim_load_last3}). Baseline Stim Load: {baseline_stim_load}. "
        "Nervous System Load today: {nervous_system_load_latest}."
    ),
    'positive_streak': (
        "The patient's Stability Score has been 7 or above for 3 consecutive check-ins "
        "({stability_scores_last3[0]}, {stability_scores_last3[1]}, {stability_scores_last3[2]}). "
        "Baseline stability: {baseline_stability}. "
        "Today's mood: {mood_latest}/10. Sleep: {sleep_hours_latest} hours."
    ),
}

_MODE_E_SYSTEM = (
    "You are CognaSync's proactive behavioral intelligence layer. "
    "Your job is to surface a meaningful pattern to the patient between appointments — "
    "something they might not notice themselves — in 2–3 warm, grounded sentences.\n\n"
    "Rules:\n"
    "- Anchor every observation to at least one specific number from the data provided.\n"
    "- Be warm and human, not clinical or alarming.\n"
    "- Never diagnose, never suggest medication changes, never use clinical terminology.\n"
    "- For concerning patterns (crash risk, sleep, mood, stim): end with one gentle "
    "forward-looking nudge — something worth watching or mentioning to their provider.\n"
    "- For positive patterns: acknowledge the stretch genuinely. Note what's behind it if "
    "the data supports it. Don't be sycophantic.\n"
    "- Never start with 'I noticed' or 'I wanted to share'. Get straight to the observation.\n"
    "- 2–3 sentences maximum. No headers, no bullets."
)


def generate_proactive_insight(pattern_type: str, supporting_data: dict) -> dict:
    """
    Mode E — generate a proactive between-appointment insight for the patient.
    Returns {'status': 'safe'|'error', 'text': str}.
    """
    template = _PATTERN_PROMPTS.get(pattern_type)
    if not template:
        return {'status': 'error', 'text': ''}

    # Safely format the template — replace missing keys with 'N/A'
    class _SafeDict(dict):
        def __missing__(self, key):
            return 'N/A'

    try:
        data_summary = template.format_map(_SafeDict(supporting_data))
    except Exception:
        data_summary = str(supporting_data)

    label = _PATTERN_LABELS.get(pattern_type, pattern_type.replace('_', ' ').title())
    user_content = f"Pattern detected: {label}\n\nData:\n{data_summary}"

    try:
        raw = _call_claude(_MODE_E_SYSTEM, user_content, max_tokens=150)
        clean = _sanitize_output(raw)
        if not clean:
            return {'status': 'error', 'text': ''}
        return {'status': 'safe', 'text': clean}
    except Exception as e:
        print(f"Mode E generation error: {e}")
        return {'status': 'error', 'text': ''}


# ── MODE F — What Worked Engine (Patient-Facing Narrative) ────────────────────

_MODE_F_SYSTEM = (
    "You are CognaSync's pattern narrator. Your job is to describe what was "
    "true on a patient's best days — nothing more. "
    "You have co-occurrence data: variables that were statistically different "
    "on high-stability days vs other days. "
    "Write 2-3 sentences in warm, plain English. "
    "STRICT RULES:\n"
    "- Use ONLY co-occurrence framing: 'On your [N] best days, [variable] averaged [X] — "
    "[delta] [higher/lower] than on your other days.'\n"
    "- NEVER say these patterns 'helped,' 'worked,' 'caused,' 'improved,' or 'led to' anything\n"
    "- NEVER recommend trying anything or suggest the patient do something\n"
    "- NEVER say 'this suggests,' 'this may indicate,' or any causal phrase\n"
    "- NEVER use clinical language or diagnose anything\n"
    "- Every sentence must cite at least one specific number\n"
    "- Do not mention all patterns — pick the 2-3 with the largest, clearest deltas\n"
    "- Tone: matter-of-fact, warm, like reading data aloud to a friend\n"
    "- If fewer than 2 patterns have clear direction, write one sentence acknowledging "
    "there isn't enough variation in the data to surface a clear pattern yet"
)


def generate_what_worked_summary(what_worked: dict) -> dict:
    """
    Mode F — standalone patient-facing narrative describing co-occurrence patterns
    on high-stability days.

    what_worked: the dict returned by db.get_what_worked_patterns()
    Returns: {'status': 'safe'|'error', 'text': str}
    """
    if not what_worked or not what_worked.get('patterns'):
        return {'status': 'error', 'text': ''}

    good_n  = what_worked['good_day_count']
    total_n = what_worked['total_days']
    window  = what_worked.get('days_window', 60)

    lines = []
    for p in what_worked['patterns'][:5]:
        direction = 'higher' if p['avg_good_days'] > p['avg_other_days'] else 'lower'
        lines.append(
            f"- {p['label']}: {p['avg_good_days']}{p['unit']} on high-stability days "
            f"vs {p['avg_other_days']}{p['unit']} on other days "
            f"(delta {p['delta']}, {direction} on good days, "
            f"logged on {p['good_day_coverage']} of {good_n} high-stability days)"
        )

    user_content = (
        f"Co-occurrence data — {good_n} high-stability days out of {total_n} check-ins "
        f"over the past {window} days:\n"
        + "\n".join(lines)
    )

    try:
        raw   = _call_claude(_MODE_F_SYSTEM, user_content, max_tokens=200)
        clean = _sanitize_output(raw)
        if not clean:
            return {'status': 'error', 'text': ''}
        return {'status': 'safe', 'text': clean}
    except Exception as e:
        print(f"Mode F generation error: {e}")
        return {'status': 'error', 'text': ''}


# ── MODE G — Provider Synthesis (Note-Data Alignment) ─────────────────────────

_MODE_G_SYSTEM = (
    "You are a clinical data alignment assistant for CognaSync. "
    "You receive: (1) behavioral check-in averages from the 14 days before and after "
    "an appointment; (2) optional session notes; (3) optional guided Q&A — patient "
    "answers to specific clinical questions recorded by the provider during the session.\n\n"
    "Your task: write 3-4 clinical-neutral sentences that surface alignment or divergence "
    "between what was reported/described in the session and what the objective behavioral "
    "data shows.\n\n"
    "Structure:\n"
    "1. State the pre→post behavioral trajectory with specific numbers for at least "
    "two metrics.\n"
    "2. Patient self-report check (if Q&A answers are present): identify discrepancies "
    "between what the patient reported during the session and what the pre-appointment "
    "behavioral data actually showed. Format: 'Patient reported [X] — behavioral data "
    "in the prior 14 days shows [specific number].' Only flag discrepancies where the "
    "gap is meaningful (e.g., patient said sleep was fine but sleep averaged 5.1 hrs "
    "with disruption score 7.2).\n"
    "3. Clinical direction check (if notes are non-empty): identify whether the "
    "post-appointment behavioral data moves in the same or different direction as "
    "the session summary describes. Name the specific divergence if one exists. "
    "Do NOT quote notes verbatim.\n"
    "4. Name 1 metric or pattern worth tracking in the next review period.\n\n"
    "STRICT RULES:\n"
    "- Every claim must cite a specific number from the provided data\n"
    "- Never diagnose, never prescribe, never evaluate quality of clinical care\n"
    "- If post-window has fewer than 3 check-ins: state that explicitly; skip the "
    "clinical direction check and describe pre-window only\n"
    "- If neither notes nor Q&A are present: skip sentences 2 and 3\n"
    "- Do not reference notes as 'notes' — say 'the session summary describes' or "
    "describe the direction implied\n"
    "- Do not attribute Q&A answers as exact quotes — say 'patient reported' not "
    "'patient said' and never reproduce the verbatim answer text\n"
    "- Forbidden: 'the provider wrote,' 'you noted,' 'the notes say,' 'you said'\n"
    "- Forbidden: all standard CognaSync forbidden terms (diagnose, you are, etc.)\n"
    "- Max 4 sentences total"
)


# ── MODE H — Patient Synthesis (Behavioral Story Around Appointment) ──────────

_MODE_H_SYSTEM = (
    "You are a warm, honest data narrator for CognaSync patients. "
    "You receive behavioral check-in averages from the 14 days before and 14 days "
    "after an appointment. You do NOT have access to session notes or clinical content.\n\n"
    "Your task: write 2-3 sentences describing the patient's behavioral journey "
    "around the appointment in plain, human language.\n\n"
    "Structure:\n"
    "1. Describe the pre-appointment window using at least one specific average "
    "(mood, sleep, or stability — whichever is most notable).\n"
    "2. If post-data exists with ≥3 check-ins: describe what changed or stayed "
    "similar. If post data is sparse, say it's too early to see the full picture.\n"
    "3. Optional: one observation worth watching — framed as a question the patient "
    "might hold, not as advice.\n\n"
    "STRICT RULES:\n"
    "- Write in second person: 'your mood averaged…', 'in the two weeks before…'\n"
    "- Use plain time references: 'in the two weeks before,' 'in the days since'\n"
    "- Never mention the session, the provider, or clinical notes\n"
    "- Never diagnose, never advise on medications\n"
    "- Never use the words 'improved,' 'declined,' 'worsened' — instead say "
    "'rose,' 'dropped,' 'was higher,' 'was lower'\n"
    "- Never say 'this suggests' or any causal phrase\n"
    "- If only pre-window data exists: write 1-2 sentences about that window only, "
    "noting it's the data leading into the appointment\n"
    "- Warm but not cheerful — honest without being alarming\n"
    "- Max 3 sentences"
)


def generate_provider_synthesis(synthesis: dict) -> dict:
    """
    Mode G — provider-facing synthesis comparing pre/post behavioral data
    against session notes.

    synthesis: the dict returned by db.get_appointment_synthesis()
    Returns: {'status': 'safe'|'error', 'text': str}
    """
    if not synthesis:
        return {'status': 'error', 'text': ''}

    pre      = synthesis.get('pre')  or {}
    post     = synthesis.get('post') or {}
    deltas   = synthesis.get('deltas') or {}
    notes    = synthesis.get('notes_text', '').strip()
    appt_dt  = synthesis.get('appt_date', 'unknown date')
    pre_win  = synthesis.get('pre_window', '')
    post_win = synthesis.get('post_window', '')
    has_post = synthesis.get('has_post_data', False)

    def _fmt(window: dict, label: str) -> str:
        parts = []
        for key, display in [('mood', 'mood'), ('sleep_hours', 'sleep hrs'),
                              ('stress', 'stress'), ('energy', 'energy'),
                              ('stability', 'stability'), ('crash_risk', 'crash risk')]:
            val = window.get(key)
            if val is not None:
                parts.append(f"{display}={val}/10" if key not in ('sleep_hours',)
                             else f"sleep={val}hrs")
        n = window.get('n', 0)
        return f"{label} ({n} check-ins, {pre_win if label=='Pre' else post_win}): " + ", ".join(parts)

    lines = [_fmt(pre, 'Pre')] if pre else ["Pre-window: no check-in data"]
    if has_post:
        lines.append(_fmt(post, 'Post'))
    else:
        post_n = post.get('n', 0) if post else 0
        lines.append(f"Post-window: {post_n} check-in(s) — insufficient for trend analysis")

    if deltas:
        delta_parts = []
        for key, display in [('mood', 'mood'), ('sleep_hours', 'sleep'),
                              ('stress', 'stress'), ('stability', 'stability')]:
            d = deltas.get(key)
            if d is not None:
                sign = '+' if d >= 0 else ''
                delta_parts.append(f"{display}: {sign}{d}")
        if delta_parts:
            lines.append("Deltas (post − pre): " + ", ".join(delta_parts))

    # ── Guided Q&A — patient self-report during session ──────────────
    guided_qa = synthesis.get('guided_qa') or []
    if guided_qa:
        qa_lines = []
        for item in guided_qa[:6]:   # cap at 6 answered questions
            q   = (item.get('question') or '').strip()[:120]
            a   = (item.get('answer')   or '').strip()[:200]
            cat = (item.get('category') or 'General').strip()
            if q and a:
                qa_lines.append(f"  [{cat}] {q} → {a}")
        if qa_lines:
            lines.append("Patient-reported (session Q&A):\n" + "\n".join(qa_lines))
    else:
        lines.append("Guided Q&A: not recorded")

    if notes:
        lines.append(f"Session summary: {notes[:400]}")
    else:
        lines.append("Session notes: not recorded")

    user_content = f"Appointment date: {appt_dt}\n" + "\n".join(lines)

    try:
        raw   = _call_claude(_MODE_G_SYSTEM, user_content, max_tokens=300)
        clean = _sanitize_output(raw)
        if not clean:
            return {'status': 'error', 'text': ''}
        return {'status': 'safe', 'text': clean}
    except Exception as e:
        print(f"Mode G generation error: {e}")
        return {'status': 'error', 'text': ''}


def generate_patient_synthesis(synthesis: dict) -> dict:
    """
    Mode H — patient-facing synthesis: behavioral story around the appointment.
    NOTE: Never pass session notes or care plan to this function — only
    behavioral data is included.

    synthesis: the dict returned by db.get_appointment_synthesis()
    Returns: {'status': 'safe'|'error', 'text': str}
    """
    if not synthesis:
        return {'status': 'error', 'text': ''}

    pre      = synthesis.get('pre')  or {}
    post     = synthesis.get('post') or {}
    deltas   = synthesis.get('deltas') or {}
    appt_dt  = synthesis.get('appt_date', 'unknown date')
    has_post = synthesis.get('has_post_data', False)
    pre_win  = synthesis.get('pre_window', '')
    post_win = synthesis.get('post_window', '')

    def _fmt_patient(window: dict, label: str) -> str:
        parts = []
        for key, display in [('mood', 'mood avg'), ('sleep_hours', 'sleep avg'),
                              ('stress', 'stress avg'), ('energy', 'energy avg'),
                              ('stability', 'stability avg')]:
            val = window.get(key)
            if val is not None:
                unit = 'hrs' if key == 'sleep_hours' else '/10'
                parts.append(f"{display} {val}{unit}")
        n = window.get('n', 0)
        return f"{label} window ({n} check-ins): " + ", ".join(parts)

    lines = [_fmt_patient(pre, 'Pre-appointment')] if pre else ["Pre-appointment: no check-in data"]

    if has_post:
        lines.append(_fmt_patient(post, 'Post-appointment'))
        if deltas:
            delta_parts = []
            for key, display in [('mood', 'mood'), ('sleep_hours', 'sleep'),
                                  ('stress', 'stress'), ('stability', 'stability')]:
                d = deltas.get(key)
                if d is not None:
                    sign = '+' if d >= 0 else ''
                    delta_parts.append(f"{display} {sign}{d}")
            if delta_parts:
                lines.append("Changes: " + ", ".join(delta_parts))
    else:
        post_n = post.get('n', 0) if post else 0
        lines.append(f"Post-appointment: only {post_n} check-in(s) recorded so far")

    user_content = f"Appointment date: {appt_dt}\n" + "\n".join(lines)

    try:
        raw   = _call_claude(_MODE_H_SYSTEM, user_content, max_tokens=250)
        clean = _sanitize_output(raw)
        if not clean:
            return {'status': 'error', 'text': ''}
        return {'status': 'safe', 'text': clean}
    except Exception as e:
        print(f"Mode H generation error: {e}")
        return {'status': 'error', 'text': ''}


# ═══════════════════════════════════════════════════════════════════════════
# INTELLIGENCE LAYER — PIVOT FUNCTIONS
# Generates Mode C briefs from transcript-derived features rather than
# patient self-report check-ins. All four safety rules and the forbidden-
# language sanitization layer apply identically to these outputs.
# ═══════════════════════════════════════════════════════════════════════════

_BRIEF_FROM_SESSIONS_SYSTEM_PROVIDER = """You are a clinical data assistant preparing a pre-appointment brief for a psychiatrist or mental health provider. The structure follows the bio-psychosocial model and aligns with standard Mental Status Exam (MSE) documentation practice.

Your inputs are structured features extracted from this patient's recent session transcripts and voice recordings, including acoustic biomarker analysis from actual audio files.

Write in structured, clinically neutral language. Be specific — cite numbers and session counts. Describe observed patterns; never interpret clinical meaning or diagnose.

STRUCTURE (use these exact section headers):

**Trajectory:** One sentence covering the period, session count, and general direction of presentation.

**Biological**
- Medications: What medications were discussed. Adherence signals from session language ("took as prescribed," "missed doses," "ran out"). Any side-effect mentions. Cite which sessions. If no medication discussions: 'Not discussed this period.'
- Physical/Somatic: Any somatic symptoms mentioned (sleep, appetite, energy, pain, physical complaints). Cite how many sessions.
- Sleep: Average hours mentioned; if disruption patterns were described, note them.
- Substances: If alcohol, cannabis, or other substances were mentioned in session language, note frequency and context (not interpretation).
- Wearable data: Include HRV, resting HR, sleep avg from wearables if present. Omit if no wearable data.

**Psychological**
- Mood (self-reported): Patient's own description of their emotional state across sessions. Include numeric estimates if reported. Distinguish patient self-report from clinician-observed affect.
- Affect (observed): Emotional expression as inferred from session language and speech features — range, intensity, appropriateness to content. Use §24 vocabulary.
- Thought content: Topics the patient raised — stressors, preoccupations, recurring concerns. Language-level observations only, no clinical characterization.
- Thought process: Coherence and organization of communication as reflected in transcript. Note if sessions showed tangential, disorganized, or fragmented narrative vs. linear and organized.
- Coping and insight: What coping tools or strategies the patient mentioned using. What understanding of their own situation they expressed. Note any statements about treatment goals or self-awareness.
- Functional status: What the patient reported about daily functioning — work, relationships, self-care, activities. Be specific about what changed from their baseline if mentioned.

**Social/Contextual**
- Interpersonal: Relationships, family, social support — what the patient raised and in how many sessions.
- Environmental stressors: Work, financial, housing, life events mentioned. Count distinct stressors across sessions.
- Safety signals: Any language flagged for interpersonal safety concerns (provider-only). Note if absent.

**Mental Status — Acoustic Observations**
Include this section whenever acoustic or voice recording data is provided.
- Speech rate: Label (slowed / normal / pressured) + numeric articulation rate in sps. Distribution across sessions if multiple.
- Prosody: Label (flat / normal / elevated) + F0 CV if available. Note consistency across sessions.
- Pauses: Label + mean pause ratio as percentage. Note direction trend across sessions.
- Voice quality: HNR, jitter, shimmer as measured numbers if available. HNR below 15 dB = reduced harmonic quality — report what was measured.
- Arousal: Label (low / normal / elevated / agitated) + RMS amplitude if available.
- Speech coherence: intact / disorganized as observed in transcript.
- Acoustic pattern type: Name the label (depressive / anxiety_stress / mania_hypomania / mixed / none_detected) and in how many sessions. Not a diagnosis — an acoustic cluster observation.
- Poor recording quality: Note if applicable; confidence reduced for those sessions.
- If no acoustic data: 'No audio recordings processed this period.'

Affect Model (Research Signal) — include when VAD data is present:
- Report valence, arousal, dominance averages and trends as measured numbers.
- Always include the ⚠ disclaimer verbatim — mandatory.
- Correct: 'Acoustic valence averaged 0.29 across N sessions (low range; model scale 0–1).'
- Correct: 'Arousal was in the neutral range (avg 0.48) with a declining trend.'
- Never: 'the model detected depression,' 'the patient is depressed,' or any diagnostic label.
- When VAD patterns converge with acoustic labels (low valence + slowed speech + flat prosody), name the convergence explicitly without inferring a diagnosis. Cite model accuracy ceiling (~70–75%).

**Risk and Safety**
- Suicidal ideation / self-harm: Any language detected or absence thereof. Note session date if present.
- Homicidal ideation / other-directed: Note if present or absent.
- Crisis events between sessions: Patient-reported ER visits, crisis line use, acute deterioration.
- Protective factors mentioned: Social support, future orientation, reasons for living — if patient raised them.
- Overall risk signal this period: 'No crisis language detected' OR specific flags with session dates.

**Treatment Progress**
- Symptom trajectory: Are the presenting concerns becoming less frequent, less intense, or more manageable — per the patient's own reported experience? Cite supporting data.
- Skills practice: Did the patient mention using therapeutic skills, coping strategies, or self-management tools between sessions? Cite examples.
- Goal alignment: What treatment goals did the patient reference? Are they on track per their own account?

**Suggested Discussion Topics**
2-3 specific, data-anchored items for the provider to raise. Anchor each to a concrete data point (session date, transcript language, acoustic measurement, or check-in score). When acoustic patterns are notable, include at least one topic grounded in those findings.

LANGUAGE RULES — ACOUSTIC BIOMARKERS:
- Acoustic labels describe waveform measurements — not clinical diagnoses.
- Never write 'this suggests depression,' 'this indicates anxiety,' 'the patient appears manic.'
- Correct: 'Speech rate was measured at [X] sps, below normal adult range, in [N] of [T] sessions.'
- Correct: 'Pitch variation (F0 CV) averaged [X] — in the flat-prosody range — across [N] sessions.'
- Correct: 'Acoustic pattern consistent with [label] profile observed in [N] sessions.'
- Converging signals (slowed speech + flat prosody + increased pauses across sessions) are named as a cluster — still without inferring clinical meaning.

GENERAL RULES:
- Never diagnose. Never advise medication changes.
- Do not say 'you have,' 'you suffer from,' 'this indicates [disorder],' 'this explains your [symptom].'
- Describe co-occurrence only — never causation.
- Every numeric claim must come from the data. If null or not_recorded, say so — never substitute.
- Use 'patient states' or 'patient reported' rather than asserting internal states as fact.
- The methodology footer at the end of every brief is mandatory."""

_BRIEF_FROM_SESSIONS_SYSTEM_PATIENT = """You are writing a plain-language session summary for a patient to read before their next appointment.

Your goal is to help them walk into the appointment knowing what to bring up — based on what came up in their recent sessions and what their data showed.

Write like a thoughtful friend who actually reviewed their sessions. Not clinical. Not cheerful or dismissive. Honest and specific.

STRUCTURE:
1. One sentence: what the period looked like overall, in plain words.
2. What came up in sessions: the main things they talked about, in their own terms. No clinical framing.
3. What the data showed: if wearable or acoustic data is available, translate it into plain language ('your sleep averaged 5.8 hours over these weeks'). If not available, skip.
4. What stood out: anything different from usual, anything they kept coming back to.
5. Two or three things worth raising at the appointment, framed as questions they might want to ask their provider.

RULES:
- Use 'you' naturally — this is about their own experience
- Never say 'you have [condition],' 'you suffer from,' 'you are [clinical state]'
- Never advise medication changes
- Translate session themes into the patient's own language where possible — not your characterization
- Be honest about what the data can and cannot tell them
- The note at the end about data sources is mandatory"""

_METHODOLOGY_FOOTER = (
    "\n\n---\n*Methodology: Session themes extracted via structured AI analysis of transcript text. "
    "Numeric scores computed deterministically in Python prior to AI generation — "
    "the model describes patterns; it does not compute scores. "
    "Acoustic biomarker labels (speech rate, prosody, pauses, arousal, vocal affect) derived from "
    "waveform analysis using librosa and Praat/parselmouth; measurements map to §24 controlled vocabulary "
    "and represent signal-level observations, not clinical assessments. "
    "This brief does not constitute a diagnosis, clinical assessment, or medication recommendation. "
    "Clinical interpretation is the provider's responsibility.*"
)


def generate_brief_from_sessions(
    aggregated_scores: dict,
    session_features: list,
    period_start: str | None = None,
    period_end: str | None = None,
    wearable_summary: dict | None = None,
    voice_memo_summary: dict | None = None,
    affect_summary: dict | None = None,
    medication_records: list | None = None,
    audience: str = 'provider',
) -> dict:
    """
    Generate a Mode C provider brief (or patient session summary) from
    transcript-derived session features.

    This function is the intelligence layer equivalent of
    generate_appointment_summary(). The output format and safety rules
    are identical. The input source changes from patient self-report
    check-ins to passively collected session features.

    Args:
        aggregated_scores:  Output of transcript_engine.score_transcript_batch().
                            Contains mood_avg, sleep_avg, stressor counts, themes, etc.
        session_features:   List of individual session extraction results from
                            transcript_engine.extract_features(). Used to build
                            the per-session narrative.
        period_start:       ISO date string (YYYY-MM-DD) or None.
        period_end:         ISO date string (YYYY-MM-DD) or None.
        wearable_summary:   Aggregated wearable data dict or None.
                            Shape: {sleep_avg, hrv_avg, resting_hr_avg, active_min_avg, days}
        voice_memo_summary: Aggregated acoustic features or None.
                            Shape: {speech_rate_trend, vocal_energy_avg, pause_rate_avg, weeks}
        affect_summary:     Aggregated VAD affect dimensions or None.
                            Output of affect_model.aggregate_affect_sessions().
                            Provider-only — never passed on patient audience path.
        medication_records: List of active medication records from the DB or None.
        audience:           'provider' (Mode C) or 'patient' (plain-language summary).

    Returns:
        {'status': 'safe'|'crisis'|'error', 'text': str, 'raw': str}
    """
    # ── Crisis check: scan all session features before generating ──────────
    # Any crisis-detected session blocks standard brief generation for provider path;
    # for patient path, any crisis signal blocks entirely.
    crisis_sessions = [
        f for f in (session_features or []) if f.get('crisis_detected')
    ]
    if crisis_sessions:
        if audience == 'patient':
            return {'status': 'crisis', 'text': CRISIS_RESPONSE}
        # Provider path: prepend crisis warning, continue generation
        crisis_warning = (
            "🔴 CRISIS SIGNAL DETECTED\n"
            f"Crisis language was identified in {len(crisis_sessions)} session(s) during this period. "
            "Standard brief content follows, but this flag must be addressed before the appointment. "
            "Affected sessions: " + ", ".join(
                f.get('session_date', 'date unknown') for f in crisis_sessions
            ) + "\n\n"
        )
    else:
        crisis_warning = ""

    # ── Build period label ─────────────────────────────────────────────────
    n_sessions = aggregated_scores.get('session_count', len(session_features or []))
    period_label = (
        f"{period_start} to {period_end}"
        if period_start and period_end
        else f"recent {n_sessions} session{'s' if n_sessions != 1 else ''}"
    )
    data_boundary = (
        f"Based on {aggregated_scores.get('valid_session_count', n_sessions)} of {n_sessions} "
        f"session transcript{'s' if n_sessions != 1 else ''} processed"
        + (f" ({period_start} to {period_end})" if period_start and period_end else "")
        + "."
    )

    # ── Build per-session narrative block ─────────────────────────────────
    session_rows = []
    for feat in (session_features or []):
        if feat.get('crisis_detected') or not feat.get('features'):
            continue
        f = feat['features']
        s = feat.get('scores') or {}
        row = {
            'date':              feat.get('session_date', 'unknown'),
            'session_type':      feat.get('session_type', 'unknown'),
            'themes':            f.get('themes') or [],
            'stressors':         f.get('stressors') or [],
            'medications':       f.get('medications_mentioned') or [],
            'symptoms':          f.get('symptoms_mentioned') or [],
            'positive_signals':  f.get('positive_signals') or [],
            'concerning_language': f.get('concerning_language') or [],
        }
        # Mood / energy / sleep — patient self-report (keep distinct from affect)
        if f.get('patient_mood_description'):
            row['mood_description'] = f['patient_mood_description']
        if s.get('mood_estimate') is not None:
            row['mood_self_report_numeric'] = s['mood_estimate']
        if f.get('energy_description'):
            row['energy_description'] = f['energy_description']
        if s.get('energy_estimate') is not None:
            row['energy_self_report_numeric'] = s['energy_estimate']
        if f.get('sleep_hours_mentioned') is not None:
            row['sleep_hours'] = f['sleep_hours_mentioned']
        if f.get('sleep_quality_description'):
            row['sleep_quality'] = f['sleep_quality_description']
        if f.get('stress_description'):
            row['stress_description'] = f['stress_description']
        # Functional status and clinical notes
        if f.get('functional_status'):
            row['functional_status'] = f['functional_status']
        if f.get('session_notes'):
            row['session_notes'] = f['session_notes']
        # Speech features (MSE — observed affect / speech component)
        sf = s.get('speech_features') or {}
        if sf:
            sf_notable = {k: v for k, v in sf.items()
                          if k not in ('confidence', 'source', 'baseline_deviation')
                          and v and v not in ('normal', 'intact', 'none_detected')}
            if sf_notable:
                row['speech_features_observed'] = sf_notable
                row['speech_feature_source'] = sf.get('source', 'transcript')
                row['speech_confidence'] = sf.get('confidence', 'unknown')
            if sf.get('clinical_pattern_type') and sf['clinical_pattern_type'] != 'none_detected':
                row['acoustic_pattern_type'] = sf['clinical_pattern_type']
            if sf.get('severity_note'):
                row['speech_severity_note'] = sf['severity_note']
            if sf.get('baseline_deviation'):
                row['baseline_deviation'] = sf['baseline_deviation']
        # Acoustic measurements
        acf = s.get('acoustic_features') or {}
        vocab = acf.get('vocabulary') or acf  # handle both nested and flat storage
        raw   = acf.get('raw') or {}
        measured = {}
        if raw.get('articulation_rate_sps') is not None:
            measured['articulation_rate_sps'] = round(raw['articulation_rate_sps'], 2)
        if raw.get('pause_ratio') is not None:
            measured['pause_ratio_pct'] = f"{raw['pause_ratio']:.0%}"
        if raw.get('f0_cv') is not None:
            measured['f0_cv'] = round(raw['f0_cv'], 3)
        if raw.get('hnr_db') is not None:
            measured['hnr_db'] = round(raw['hnr_db'], 1)
        if measured:
            row['acoustic_measurements'] = measured
        # VAD affect model output
        afd = s.get('affect_dimensions') or {}
        if afd.get('model_available') and afd.get('valence') is not None:
            row['affect_model'] = {
                'valence':   afd['valence'],
                'arousal':   afd['arousal'],
                'dominance': afd['dominance'],
                'pattern':   afd.get('pattern'),
                'disclaimer': '⚠ Research signal — ~70–75% accuracy ceiling. Not a diagnostic instrument.',
            }
        session_rows.append(row)

    # ── Build aggregate stats block ────────────────────────────────────────
    agg = aggregated_scores
    stats = {
        'session_count':       n_sessions,
        'period':              period_label,
        'mood_avg':            agg.get('mood_avg'),
        'mood_estimates':      agg.get('mood_estimates') or [],
        'sessions_with_mood':  agg.get('sessions_with_mood', 0),
        'sleep_avg_mentioned': agg.get('sleep_avg'),
        'sleep_disruption_avg': agg.get('sleep_disruption_avg'),
        'stressor_count_total': agg.get('stressor_count_total', 0),
        'stressor_count_avg':  agg.get('stressor_count_avg'),
        'themes_across_sessions': agg.get('themes_aggregate') or [],
        'symptom_mentions':    agg.get('symptom_mentions') or {},
        'medication_signals':  agg.get('medication_signals') or [],
    }

    # ── Wearable section ───────────────────────────────────────────────────
    wearable_block = ''
    if wearable_summary:
        w = wearable_summary
        wearable_block = (
            f"\n\nWEARABLE DATA ({w.get('source', 'wearable')}, {w.get('days', '?')} days):\n"
            + (f"- Sleep avg: {w['sleep_avg']} hrs/night\n" if w.get('sleep_avg') else '')
            + (f"- HRV (RMSSD) avg: {w['hrv_avg']} ms\n" if w.get('hrv_avg') else '')
            + (f"- Resting HR avg: {w['resting_hr_avg']} bpm\n" if w.get('resting_hr_avg') else '')
            + (f"- Active minutes avg: {w['active_min_avg']}/day\n" if w.get('active_min_avg') else '')
        )

    # ── Acoustic biomarker section ─────────────────────────────────────────
    # voice_memo_summary is the output of acoustic_engine.aggregate_acoustic_sessions().
    # Build a rich, structured block that the system prompt knows how to cite.
    voice_block = ''
    if voice_memo_summary:
        v = voice_memo_summary
        n_acoustic = v.get('session_count', 0)

        def _dist_str(d: dict) -> str:
            """Format a label-distribution dict as 'label: N, ...' string."""
            if not d:
                return 'no data'
            return ', '.join(f"{lbl}: {cnt}" for lbl, cnt in sorted(d.items()))

        measured_series = v.get('measured_series') or []
        series_lines = ''
        for ms in measured_series:
            date  = ms.get('session_date', 'unknown date')
            artic = ms.get('articulation_rate_sps')
            pr    = ms.get('pause_ratio')
            f0cv  = ms.get('f0_cv')
            hnr   = ms.get('hnr_db')
            sr    = ms.get('speech_rate', 'N/A')
            pros  = ms.get('prosody', 'N/A')
            arou  = ms.get('arousal', 'N/A')
            vaf   = ms.get('vocal_affect', 'N/A')
            series_lines += (
                f"  {date}: speech_rate={sr}, prosody={pros}, arousal={arou}, "
                f"vocal_affect={vaf}"
                + (f", artic={artic:.2f} sps" if artic is not None else '')
                + (f", pause_ratio={pr:.2f}" if pr is not None else '')
                + (f", F0_CV={f0cv:.3f}" if f0cv is not None else '')
                + (f", HNR={hnr:.1f} dB" if hnr is not None else '')
                + "\n"
            )

        voice_block = (
            f"\n\nACOUSTIC BIOMARKER DATA ({n_acoustic} session{'s' if n_acoustic != 1 else ''} "
            f"with audio recordings processed):\n"
            + f"- Speech rate trend: {v.get('speech_rate_trend', 'insufficient data')}\n"
            + f"  Distribution across sessions: {_dist_str(v.get('speech_rate_distribution'))}\n"
            + (f"  Articulation rate avg: {v['articulation_rate_avg']:.2f} sps\n"
               if v.get('articulation_rate_avg') is not None else '')
            + f"- Prosody distribution: {_dist_str(v.get('prosody_distribution'))}\n"
            + (f"  F0 mean avg across sessions: {v['f0_mean_avg']:.1f} Hz\n"
               if v.get('f0_mean_avg') is not None else '')
            + f"- Pause patterns: {_dist_str(v.get('pause_distribution'))}\n"
            + (f"  Mean pause ratio: {v['pause_rate_avg']:.2f} ({v['pause_rate_avg']*100:.0f}% of recording)\n"
               if v.get('pause_rate_avg') is not None else '')
            + f"- Arousal distribution: {_dist_str(v.get('arousal_distribution'))}\n"
            + f"- Vocal affect distribution: {_dist_str(v.get('vocal_affect_distribution'))}\n"
            + (f"- Voice quality (HNR) avg: {v['hnr_avg']:.1f} dB "
               f"({'within normal range' if v['hnr_avg'] >= 15 else 'below 15 dB threshold'})\n"
               if v.get('hnr_avg') is not None else '')
            + (f"- Dominant acoustic pattern: {v['dominant_pattern']}\n"
               if v.get('dominant_pattern') else '')
            + (f"- Sessions with ≥1 abnormal acoustic label: {v['speech_concern_sessions']} of {n_acoustic}\n"
               if v.get('speech_concern_sessions') is not None else '')
            + (f"- RMS vocal energy avg: {v['vocal_energy_avg']:.4f}\n"
               if v.get('vocal_energy_avg') is not None else '')
            + (f"\nPer-session acoustic measurements:\n{series_lines}" if series_lines else '')
        )

    # ── Acoustic affect dimensions section (VAD, provider-only) ──────────────
    # affect_summary is the output of affect_model.aggregate_affect_sessions().
    # Never included on the patient audience path — guarded below at generation time.
    affect_block = ''
    if affect_summary and affect_summary.get('model_available') and audience == 'provider':
        a = affect_summary
        n_af   = a.get('valid_count', 0)
        n_tot  = a.get('session_count', 0)

        def _vad_label(avg: float | None) -> str:
            if avg is None:
                return 'not measured'
            if avg < 0.35:
                return f"{avg:.3f} (low)"
            if avg > 0.65:
                return f"{avg:.3f} (high)"
            return f"{avg:.3f} (neutral range)"

        series_lines_af = ''
        for row in (a.get('series') or []):
            date = row.get('session_date', 'unknown')
            series_lines_af += (
                f"  {date}: valence={row.get('valence')}, "
                f"arousal={row.get('arousal')}, "
                f"dominance={row.get('dominance')}, "
                f"pattern={row.get('pattern')}\n"
            )

        pat_dist = a.get('pattern_distribution') or {}
        pat_str  = ', '.join(f"{k}: {v}" for k, v in pat_dist.items()) or 'none detected'

        affect_block = (
            f"\n\nACOUSTIC AFFECT DIMENSIONS — RESEARCH SIGNAL "
            f"({n_af} of {n_tot} sessions with model output):\n"
            f"Model: {a.get('model_id', 'unknown')} | "
            f"Training: {a.get('training_source', 'unknown')}\n"
            f"- Valence avg  : {_vad_label(a.get('valence_avg'))} "
            f"| trend: {a.get('valence_trend', 'N/A')} "
            f"| range: {a.get('valence_min')}–{a.get('valence_max')}\n"
            f"- Arousal avg  : {_vad_label(a.get('arousal_avg'))} "
            f"| trend: {a.get('arousal_trend', 'N/A')} "
            f"| range: {a.get('arousal_min')}–{a.get('arousal_max')}\n"
            f"- Dominance avg: {_vad_label(a.get('dominance_avg'))}\n"
            f"- Pattern distribution: {pat_str}\n"
            f"- Dominant pattern: {a.get('dominant_pattern', 'none')}\n"
            + (f"\nPer-session VAD:\n{series_lines_af}" if series_lines_af else '')
            + f"\n⚠ {a.get('disclaimer', '')}\n"
        )

    # ── Medication records section ─────────────────────────────────────────
    med_block = ''
    if medication_records:
        med_lines = []
        for m in medication_records:
            name  = m.get('medication_name', 'unknown')
            dose  = f"{m.get('dose_amount', '')} {m.get('dose_unit', '')}".strip()
            freq  = m.get('frequency', '')
            parts = [name]
            if dose:    parts.append(dose)
            if freq:    parts.append(freq)
            med_lines.append('- ' + ' | '.join(parts))
        med_block = "\n\nACTIVE MEDICATIONS (from records):\n" + '\n'.join(med_lines)

    # ── Select system prompt ───────────────────────────────────────────────
    if audience == 'provider':
        system_prompt = (
            crisis_warning
            + _BRIEF_FROM_SESSIONS_SYSTEM_PROVIDER
            + f"\n\nData boundary statement (include verbatim at end of brief): {data_boundary}"
        )
    else:
        system_prompt = (
            _BRIEF_FROM_SESSIONS_SYSTEM_PATIENT
            + f"\n\nData note (include at end): {data_boundary}"
        )

    # ── Build user content ─────────────────────────────────────────────────
    user_content = (
        f"REVIEW PERIOD: {period_label}\n\n"
        f"AGGREGATE STATS:\n{json.dumps(stats, indent=2)}\n\n"
        f"INDIVIDUAL SESSION SUMMARIES ({len(session_rows)} sessions):\n"
        f"{json.dumps(session_rows, indent=2, default=str)}"
        + wearable_block
        + voice_block
        + affect_block
        + med_block
    )

    # ── Generate ───────────────────────────────────────────────────────────
    # 1400 tokens: the bio-psychosocial + MSE structure is substantively longer
    # than the prior flat-section format. Spec §15 cap (900) applies to Mode B/C
    # check-in summaries; this intel brief is a distinct output surface.
    try:
        raw = _call_claude(system_prompt, user_content, max_tokens=1400)
    except RuntimeError as e:
        import logging
        logging.getLogger(__name__).error("generate_brief_from_sessions failed: %s", e)
        return {'status': 'error', 'text': str(e)}

    clean = _sanitize_output(raw)
    if clean is None:
        clean = (
            "A brief was generated but contained language flagged by the safety filter. "
            "Please regenerate or contact support."
        )

    # Append methodology footer (mandatory per CLAUDE.md §14, applied to pivot output)
    final = clean + _METHODOLOGY_FOOTER

    return {
        'status': 'crisis' if crisis_sessions and audience == 'provider' else 'safe',
        'text':   final,
        'raw':    raw,
        'crisis_sessions': len(crisis_sessions),
    }
