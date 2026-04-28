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


def _call_claude(prompt, max_tokens=600):
    try:
        client = get_client()
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=max_tokens,
            messages=[{'role': 'user', 'content': prompt}],
        )
        return message.content[0].text
    except Exception as e:
        raise RuntimeError(f'Claude API error: {str(e)}')


def analyze_journal(entry_text):
    if _check_crisis(entry_text):
        return {'status': 'crisis', 'text': CRISIS_RESPONSE}

    prompt = f"""You are a supportive reflection tool. Analyze this journal entry for patterns, themes, and distortions.

INSTRUCTIONS:
- Identify 1-2 key patterns or themes
- Note any cognitive distortions (if present): all-or-nothing thinking, catastrophizing, overgeneralization, etc.
- Reflect the experience back to the writer (empathetic, non-judgmental)
- Suggest one topic to discuss with their provider (if relevant)
- DO NOT diagnose, prescribe, or replace clinical judgment
- DO NOT say "you have" or "you suffer from" or name any disorder
- Keep response to 150-200 words
- Use warm, supportive language

JOURNAL ENTRY:
{entry_text}

ANALYSIS:"""

    raw = _call_claude(prompt, max_tokens=400)
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

    prompt = f"""You are a supportive mental health tracking assistant. A patient just completed a {label} check-in.
Generate a brief, warm, data-grounded observation (2-3 sentences max) about their current state based on this data.

RULES:
- Describe patterns and comparisons to their baseline — never diagnose
- Do NOT say "you have", "you are [disorder]", "you should [medication]"
- If notes mention a crisis, do not analyze — that is handled separately
- Be warm, specific, and clinically neutral
- Reference specific numbers when they tell a meaningful story

CHECK-IN DATA:
{data_str}

OBSERVATION:"""

    try:
        raw = _call_claude(prompt, max_tokens=200)
        clean = _sanitize_output(raw)
        if not clean:
            clean = "Check-in recorded. Your data has been saved and will inform your next summary."
        if _check_crisis(raw):
            return {'status': 'crisis', 'text': CRISIS_RESPONSE}
        return {'status': 'safe', 'text': clean}
    except RuntimeError:
        return {'status': 'safe', 'text': 'Check-in recorded successfully.'}


def generate_appointment_summary(checkin_data, journal_data, days=14):
    checkin_rows = []
    for c in checkin_data:
        row = {
            'date': c.get('date', ''),
            'type': c.get('checkin_type', 'on_demand'),
            'mood': c.get('mood_score'),
            'anxiety': c.get('stress_score'),
            'sleep_hours': c.get('sleep_hours'),
        }
        ext = {}
        if c.get('extended_data'):
            try:
                ext = json.loads(c['extended_data']) if isinstance(c['extended_data'], str) else c.get('extended_data', {})
            except Exception:
                pass
        if ext.get('energy') is not None:
            row['energy'] = ext['energy']
        if ext.get('sleep_quality') is not None:
            row['sleep_quality'] = ext['sleep_quality']
        if c.get('ai_insights'):
            row['ai_observation'] = c['ai_insights'][:200]
        checkin_rows.append(row)
    checkin_json = json.dumps(checkin_rows, indent=2, default=str)
    journal_json = json.dumps(
        [{'date': j.get('created_at', '')[:10],
          'entry': j.get('raw_entry', '')[:300],
          'analysis': j.get('ai_analysis', '')[:200]} for j in journal_data],
        indent=2
    )

    prompt = f"""You are a clinical reflection assistant. Synthesize this patient's data into a brief summary for their psychiatrist.

INSTRUCTIONS:
- Identify 2-3 key patterns (mood, medication, sleep, stress, triggers)
- Note correlations (e.g., "mood improved on days with 7+ sleep")
- Flag any concerning trends (e.g., sustained mood decline, missed meds)
- Suggest 2-3 topics for discussion
- Format: 3-4 paragraphs, plain language
- DO NOT diagnose or prescribe
- DO NOT say "you have" or name specific disorders
- Make it clinically useful without being alarmist

PATIENT DATA (past {days} days):
Check-ins: {checkin_json}

Journal entries: {journal_json}

SUMMARY:"""

    raw = _call_claude(prompt, max_tokens=700)
    clean = _sanitize_output(raw)
    if clean is None:
        clean = (
            "A summary was generated but contained language that requires clinical review. "
            "Please regenerate or contact support."
        )
    return {'status': 'safe', 'text': clean, 'raw': raw}
