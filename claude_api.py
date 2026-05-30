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
                                  session_context=None):
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

    # ── Session transcript context (CLAUDE.md §22-24) ────────────────────────
    # Transcript and audio sessions extracted via the intel pipeline. Available
    # for both Mode B and Mode C but framed differently.
    session_section = ''
    if session_context:
        complete_sessions = [s for s in session_context if s.get('processing_status') == 'complete']
        if complete_sessions:
            lines = []
            has_speech = False
            for s in complete_sessions[:5]:  # cap at 5 most recent
                sdate    = s.get('session_date', 'unknown date')
                stype    = s.get('session_type', 'session')
                feats    = s.get('features') or {}
                scores   = s.get('scores') or {}
                crisis   = s.get('crisis_detected', False)
                speech   = feats.get('speech_features') or {}
                patterns = feats.get('themes') or []
                topics   = feats.get('main_topics') or []
                overall  = scores.get('overall_concern') or scores.get('overall')

                parts = [f"Session ({stype}) on {sdate}"]
                if overall is not None:
                    parts.append(f"concern level {overall}/10")
                if crisis:
                    parts.append("⚠️ crisis signal detected")
                if speech:
                    rate     = speech.get('speech_rate')
                    prosody  = speech.get('prosody')
                    coherence = speech.get('speech_coherence')
                    sp_parts = []
                    if rate and rate != 'normal':
                        sp_parts.append(f"speech rate: {rate}")
                    if prosody and prosody != 'normal':
                        sp_parts.append(f"prosody: {prosody}")
                    if coherence and coherence != 'intact':
                        sp_parts.append(f"coherence: {coherence}")
                    if sp_parts:
                        parts.append("speech features: " + ", ".join(sp_parts))
                        has_speech = True
                if topics:
                    parts.append("topics: " + ", ".join(str(t) for t in topics[:4]))
                if patterns:
                    parts.append("patterns: " + ", ".join(str(p) for p in patterns[:3]))

                lines.append("- " + " | ".join(parts))

            pending_count = len([s for s in session_context if s.get('processing_status') != 'complete'])

            session_section = (
                f"\n\nSESSION TRANSCRIPT/RECORDING DATA ({len(complete_sessions)} processed"
                + (f", {pending_count} still processing" if pending_count else "")
                + " — from uploaded transcripts and audio recordings):\n"
                + "\n".join(lines)
            )
            if has_speech and audience == 'provider':
                session_section += (
                    "\nNote: speech features are extracted from transcript text, not audio. "
                    "Confidence varies by transcript quality. See CLAUDE.md §24 for feature vocabulary.\n"
                )

    if session_section:
        if audience == 'provider':
            summary_system += (
                "\n\nFor SESSION TRANSCRIPT/RECORDING DATA: add a **Session Intelligence** section "
                "after Qualitative Themes. List sessions by date with concern level, speech feature "
                "observations (using CLAUDE.md §24 vocabulary exactly), and topic/pattern notes. "
                "For any session with crisis_detected=True, list it first under 🔴. "
                "Speech features describe the transcript, not a diagnosis — frame as 'session speech features showed' "
                "not 'patient exhibited.' If sessions are still processing, note that additional data is pending.\n"
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
                              session_context=None):
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
    therapy_session_section = ''
    if session_context:
        complete = [s for s in session_context if s.get('processing_status') == 'complete']
        if complete:
            lines = []
            for s in complete[:5]:
                sdate   = s.get('session_date', 'unknown date')
                stype   = s.get('session_type', 'session')
                feats   = s.get('features') or {}
                scores  = s.get('scores') or {}
                crisis  = s.get('crisis_detected', False)
                topics  = feats.get('main_topics') or []
                patterns = feats.get('themes') or []
                overall  = scores.get('overall_concern') or scores.get('overall')
                parts = [f"Session ({stype}) on {sdate}"]
                if overall is not None:
                    parts.append(f"concern {overall}/10")
                if crisis:
                    parts.append("⚠️ crisis signal")
                if topics:
                    parts.append("topics: " + ", ".join(str(t) for t in topics[:4]))
                if patterns:
                    parts.append("patterns: " + ", ".join(str(p) for p in patterns[:3]))
                lines.append("- " + " | ".join(parts))
            pending_count = len([s for s in session_context if s.get('processing_status') != 'complete'])
            therapy_session_section = (
                f"\n\nSESSION TRANSCRIPT/RECORDING DATA ({len(complete)} processed"
                + (f", {pending_count} still processing" if pending_count else "")
                + "):\n" + "\n".join(lines)
            )
            summary_system += (
                "\n\nFor SESSION TRANSCRIPT/RECORDING DATA: include a **Session Notes** section. "
                "Focus on topics and themes — this is a therapy summary so interpersonal and behavioral "
                "context from sessions is primary. Flag any crisis-detected sessions first. "
                "Do not reproduce speech feature scores or clinical labels.\n"
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

_BRIEF_FROM_SESSIONS_SYSTEM_PROVIDER = """You are a clinical data assistant preparing a pre-appointment brief for a psychiatrist or mental health provider.

Your inputs are structured features extracted from this patient's recent session transcripts, along with any available wearable biometric data and voice memo analysis.

Write in structured, clinically neutral language. Be specific — cite numbers and session counts. Describe patterns; never interpret clinical meaning.

STRUCTURE (use these exact section headers):

**Trajectory:** One sentence covering the period and overall direction.

**Quantitative Summary:**
- Mood: (include avg and range if mood estimates available; state 'patient did not self-report numeric mood this period' if not)
- Sleep: (avg hours if mentioned; sleep disruption proxy if computable)
- Stress/Stressors: (count and categories of stressors raised across sessions)
- Wearable data: (include HRV, resting HR, sleep avg from wearables if present; omit section if no wearable data)

**Medication Signal:** What medications were discussed, adherence signals from session language, any side-effect mentions. If none discussed: 'No medication discussions recorded this period.'

**Session Themes:** 2-3 dominant topics the patient raised across sessions. Language-level observations only — not clinical characterization of what those topics represent.

**Flags:** Any crisis language (blocked generation if detected — note accordingly), concerning language patterns, recurring symptoms mentioned, medication adherence concerns. If none: 'None for this period.'

**Suggested Discussion Topics:** 2-3 specific, data-anchored items the provider may wish to raise.

RULES:
- Never diagnose. Never advise medication changes.
- Do not say 'you have,' 'you suffer from,' 'this indicates [disorder],' 'this explains your [symptom],' 'this is consistent with [condition].'
- Describe co-occurrence only — never causation. 'Stressor count was elevated in sessions where sleep hours were also lower' not 'stress caused sleep disruption.'
- Every numeric claim must come from the data provided. If a value is null or not_recorded, say so — never substitute a plausible estimate.
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
            'date':         feat.get('session_date', 'unknown'),
            'session_type': feat.get('session_type', 'unknown'),
            'themes':       f.get('themes') or [],
            'stressors':    f.get('stressors') or [],
            'medications':  f.get('medications_mentioned') or [],
            'symptoms':     f.get('symptoms_mentioned') or [],
        }
        if s.get('mood_estimate') is not None:
            row['mood_self_report'] = s['mood_estimate']
        if s.get('sleep_hours') is not None:
            row['sleep_hours_mentioned'] = s['sleep_hours']
        if f.get('positive_signals'):
            row['positive_signals'] = f['positive_signals']
        if f.get('concerning_language'):
            row['concerning_language'] = f['concerning_language']
        if f.get('session_notes'):
            row['session_notes'] = f['session_notes']
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

    # ── Voice memo section ─────────────────────────────────────────────────
    voice_block = ''
    if voice_memo_summary:
        v = voice_memo_summary
        voice_block = (
            f"\n\nVOICE MEMO ACOUSTIC DATA ({v.get('weeks', '?')} weeks):\n"
            + (f"- Speech rate: {v['speech_rate_trend']}\n" if v.get('speech_rate_trend') else '')
            + (f"- Vocal energy avg: {v['vocal_energy_avg']}\n" if v.get('vocal_energy_avg') else '')
            + (f"- Pause rate avg: {v['pause_rate_avg']}\n" if v.get('pause_rate_avg') else '')
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
        + med_block
    )

    # ── Generate ───────────────────────────────────────────────────────────
    try:
        raw = _call_claude(system_prompt, user_content, max_tokens=900)
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
