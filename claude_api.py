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


_JOURNAL_SYSTEM = """You are a supportive reflection tool. Analyze the journal entry provided by the user.

INSTRUCTIONS:
- Identify 1-2 key patterns or themes
- Note any cognitive distortions (if present): all-or-nothing thinking, catastrophizing, overgeneralization, etc.
- Reflect the experience back to the writer (empathetic, non-judgmental)
- Suggest one topic to discuss with their provider (if relevant)
- DO NOT diagnose, prescribe, or replace clinical judgment
- DO NOT say "you have" or "you suffer from" or name any disorder
- Keep response to 150-200 words
- Use warm, supportive language"""


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
        ]
    if ext.get('caffeine_mg') is not None:
        summary_lines.append(f"Caffeine: {ext.get('caffeine_mg')}mg")
    if notes:
        summary_lines.append(f"Notes: {notes[:200]}")
    if baseline:
        summary_lines.append(f"7-day avg mood: {baseline.get('avgMood', 'n/a')}, avg anxiety: {baseline.get('avgAnxiety', 'n/a')}")

    data_str = '\n'.join(summary_lines)

    checkin_system = (
        f"You are a supportive mental health tracking assistant. A patient just completed a {label} check-in. "
        "Generate a brief, warm, data-grounded observation (2-3 sentences max) about their current state. "
        "RULES: Describe patterns and comparisons to their baseline — never diagnose. "
        "Do NOT say 'you have', 'you are [disorder]', or 'you should [medication]'. "
        "Be warm, specific, and clinically neutral. Reference specific numbers when meaningful."
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
                                  appointment_date=None):
    """Synthesize check-in and journal data into a pre-appointment clinical summary.

    Accepts either rolling `days` from today or an explicit `period_start` / `period_end`.
    `appointment_date` (YYYY-MM-DD string) tightens the clinical framing when provided.
    """
    # ── Build structured checkin rows ────────────────────────────────
    checkin_rows = []
    mood_vals, stress_vals, sleep_vals, energy_vals = [], [], [], []
    meds_logged = 0

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
            row['ai_observation'] = c['ai_insights'][:200]

        checkin_rows.append(row)

        if mood   is not None: mood_vals.append(float(mood))
        if stress is not None: stress_vals.append(float(stress))
        if sleep  is not None: sleep_vals.append(float(sleep))
        if energy is not None: energy_vals.append(float(energy))

    def _avg(v): return round(sum(v) / len(v), 1) if v else None
    def _trend(v):
        if len(v) < 2: return 'insufficient data'
        return 'improving' if v[-1] > v[0] else 'declining' if v[-1] < v[0] else 'stable'

    stats = {
        'total_checkins':    len(checkin_rows),
        'period_days':       days,
        'avg_mood':          _avg(mood_vals),
        'mood_trend':        _trend(mood_vals),
        'avg_stress':        _avg(stress_vals),
        'stress_trend':      _trend(stress_vals),
        'avg_sleep_hours':   _avg(sleep_vals),
        'avg_energy':        _avg(energy_vals),
        'checkins_with_meds': meds_logged,
    }

    # ── Build journal rows ───────────────────────────────────────────
    journal_rows = []
    for j in journal_data:
        entry_date = (j.get('entry_date') or j.get('created_at', ''))[:10]
        content    = j.get('content') or j.get('raw_entry') or ''
        journal_rows.append({
            'date':    entry_date,
            'excerpt': content[:300] + ('...' if len(content) > 300 else ''),
        })

    # ── Build prompt ─────────────────────────────────────────────────
    appt_context = (
        f"The appointment is scheduled for {appointment_date}. "
        if appointment_date else ""
    )
    period_label = (
        f"{period_start} to {period_end}"
        if period_start and period_end
        else f"past {days} days"
    )

    summary_system = (
        "You are a clinical reflection assistant preparing a pre-appointment briefing for a psychiatrist. "
        f"{appt_context}"
        "INSTRUCTIONS: "
        "1) Open with a one-sentence summary of the patient's overall trajectory this period. "
        "2) Summarise quantitative patterns: mood average and trend, stress/anxiety, sleep, energy. "
        "3) Note any medication adherence signals from check-in logs. "
        "4) Draw on journal excerpts to surface qualitative themes — language patterns, recurring stressors, coping style. "
        "5) Flag any concerning trends or week-over-week changes. "
        "6) Close with 2-3 specific suggested discussion topics for the appointment. "
        "Format: 4-5 short paragraphs, plain clinical language. "
        "DO NOT diagnose, prescribe, or name specific disorders. "
        "DO NOT use 'you have' or 'you suffer from'. "
        "Be specific — reference dates and numbers when useful."
    )

    user_content = (
        f"REVIEW PERIOD: {period_label}\n\n"
        f"AGGREGATE STATS:\n{json.dumps(stats, indent=2)}\n\n"
        f"DAILY CHECK-INS:\n{json.dumps(checkin_rows, indent=2, default=str)}\n\n"
        f"JOURNAL ENTRIES ({len(journal_rows)} total):\n{json.dumps(journal_rows, indent=2, default=str)}"
    )

    raw = _call_claude(summary_system, user_content, max_tokens=900)
    clean = _sanitize_output(raw)
    if clean is None:
        clean = (
            "A summary was generated but contained language that requires clinical review. "
            "Please regenerate or contact support."
        )
    return {'status': 'safe', 'text': clean, 'raw': raw}
