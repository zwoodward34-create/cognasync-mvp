import os
import json
import anthropic

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
    'suicide', 'suicidal', 'kill myself', "don't want to live", "don't want to be alive",
    'self-harm', 'self harm', 'hurt myself', 'end my life', 'ending my life',
    'want to die', 'better off dead',
]

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
    ('stop taking', 'discuss with your provider changes to'),
    ('you should take', 'some people find it helpful to discuss'),
    ('this will make you better', 'many people find this approach helpful'),
]


def _check_crisis(text):
    lower = text.lower()
    return any(kw in lower for kw in CRISIS_KEYWORDS)


def _sanitize_output(text):
    lower = text.lower()
    for forbidden, _ in FORBIDDEN_PATTERNS:
        if forbidden in lower:
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
                                  audience='patient'):
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
    if audience == 'provider':
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
            "**Flags:** Threshold crossings with supporting data. If none, write 'None for this period.'\n"
            "**Suggested Discussion Topics:** 2-3 specific, data-anchored items.\n"
            "RULES: Never diagnose. Never advise medication changes. "
            "Do not say 'you have,' 'you suffer from,' 'this indicates [disorder].' "
            f"Always state: '{data_boundary}'"
        )
    else:
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
            "5. Two or three specific things worth bringing to the appointment, framed as questions they might want to ask.\n\n"
            "RULES:\n"
            "- Use 'you' naturally — this is their data about themselves\n"
            "- Never say 'you have [condition],' 'you suffer from,' 'you are [clinical state]'\n"
            "- Never advise medication changes\n"
            "- Translate scores into lived experience where possible ('your sleep averaged 5.2 hours, which is below where you usually aim')\n"
            "- If advanced data (exercise, social quality, coping activities) is present, weave it in naturally — don't just list fields\n"
            "- Be honest about what the data can and can't tell you\n"
            f"- End with: '{data_boundary}'"
        )

    adv_section = (
        f"\n\nADVANCED CHECK-IN DATA:\n{json.dumps(adv_stats, indent=2)}"
        if adv_stats else ""
    )

    user_content = (
        f"REVIEW PERIOD: {period_label}\n\n"
        f"AGGREGATE STATS:\n{json.dumps(stats, indent=2)}"
        f"{adv_section}\n\n"
        f"DAILY CHECK-INS ({n} total):\n{json.dumps(checkin_rows, indent=2, default=str)}\n\n"
        f"JOURNAL ENTRIES ({len(journal_rows)} total):\n{json.dumps(journal_rows, indent=2, default=str)}"
    )

    raw = _call_claude(summary_system, user_content, max_tokens=1000)
    clean = _sanitize_output(raw)
    if clean is None:
        clean = (
            "A summary was generated but contained language that requires clinical review. "
            "Please regenerate or contact support."
        )
    return {'status': 'safe', 'text': clean, 'raw': raw}
