import React, { useState, useEffect, useRef } from 'react';

const P = {
  bg:          '#F0F0F0',
  surface:     '#FFFFFF',
  raised:      '#F8F8F8',
  border:      '#000000',
  borderLight: '#CCCCCC',
  ink:         '#000000',
  inkMid:      '#333333',
  inkFaint:    '#666666',
  accent:      '#000000',
  accentLight: '#ECECEC',
};

const CRISIS_WORDS = [
  'suicide','suicidal','kill myself','hurt myself','self-harm',
  "can't go on",'want to die','end it','end my life','better off dead',
  "don't want to live",'ending my life',
];

const PROMPTS = [
  'What moment today made you pause and reflect?',
  'Describe something that has been weighing on your mind lately.',
  'What is one thing you wish someone understood about how you feel right now?',
  'What does your body feel like today — and what might that be telling you?',
  'If your emotions had a color today, what would it be and why?',
  'What are you holding onto that you might need to let go of?',
  'What made you feel most like yourself recently?',
  'Describe a recent challenge. What did it ask of you?',
];

const DAILY_QUESTIONS = [
  'What is something you\'re looking forward to today?',
  'Who is someone you can text to check in with today?',
  'What is one thing you\'re going to do for yourself today?',
];
const WELLNESS_ITEMS = [
  'Slept well?', 'Stayed hydrated?', 'Hygiene routine?',
  'Smiled or laughed?', 'Kindness to self?', 'Ate well?', 'Deep breaths?',
];

const TYPE_CONFIG = {
  free_flow: { label: 'Free Flow',      icon: '✍',  placeholder: "What's on your mind today? Write freely — there's no wrong way to start." },
  prompt:    { label: 'Journal Prompt', icon: '💡', placeholder: 'Respond to the prompt above in as much or as little detail as you like.' },
  guided:    { label: 'Guided Journal', icon: '🧭', placeholder: '' },
};

function detectCrisis(text) {
  const lower = (text || '').toLowerCase();
  return CRISIS_WORDS.some(w => lower.includes(w));
}

function timeAgo(dateStr) {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1)  return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24)  return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

// ── Shared input styles ───────────────────────────────────────────────────
const underlineInput = {
  width: '100%', border: 'none', borderBottom: `1px solid ${P.borderLight}`,
  background: 'transparent', color: P.ink, fontSize: 13,
  fontFamily: 'DM Sans', outline: 'none', padding: '6px 2px',
};

const underlineTextarea = (h = 96) => ({
  width: '100%', minHeight: h, border: 'none',
  borderBottom: `1px solid ${P.borderLight}`,
  background: 'transparent', color: P.ink, fontSize: 13,
  lineHeight: 1.7, fontFamily: 'DM Sans', resize: 'none', outline: 'none',
  padding: '6px 2px', boxSizing: 'border-box',
});

const sectionLabel = {
  fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
  letterSpacing: '0.09em', color: P.inkFaint,
  display: 'block', marginBottom: 10,
};

// ── Guided journal form ───────────────────────────────────────────────────
function GuidedJournalForm({ onSave, submitting, shareWithProvider, onShareChange }) {
  const now     = new Date();
  const todayIso = now.toISOString().slice(0, 10);
  const nowTime  = now.toTimeString().slice(0, 5);

  const [date,            setDate]            = useState(todayIso);
  const [time,            setTime]            = useState(nowTime);
  const [dailyAnswers,    setDailyAnswers]    = useState(['', '', '']);
  const [gratitude,       setGratitude]       = useState('');
  const [origThought,     setOrigThought]     = useState('');
  const [reframe,         setReframe]         = useState('');
  const [priorities,      setPriorities]      = useState(['', '', '']);
  const [wellness,        setWellness]        = useState(Object.fromEntries(WELLNESS_ITEMS.map(w => [w, null])));
  const [dailyHighlight,  setDailyHighlight]  = useState('');
  const [lessonLearned,   setLessonLearned]   = useState('');

  const allText = [...dailyAnswers, gratitude, origThought, reframe, ...priorities, dailyHighlight, lessonLearned].join(' ');
  const crisis  = detectCrisis(allText);

  const setDailyAnswer = (i, val) => setDailyAnswers(a => { const n = [...a]; n[i] = val; return n; });

  const compiledEntry = () => [
    `Date: ${date}  Time: ${time}`,
    '',
    'DAILY INTENTIONS',
    ...DAILY_QUESTIONS.map((q, i) => `  ${q}\n  ${dailyAnswers[i].trim() || '(blank)'}`),
    '',
    'GRATITUDE',
    gratitude.trim() || '(blank)',
    '',
    'THOUGHT RECONSTRUCTION',
    `  Original: ${origThought.trim() || '(blank)'}`,
    `  Reframe:  ${reframe.trim() || '(blank)'}`,
    '',
    'TOP 3 PRIORITIES',
    ...priorities.map((p, i) => `  ${i + 1}. ${p.trim() || '(blank)'}`),
    '',
    'WELLNESS CHECK-IN',
    ...WELLNESS_ITEMS.map(w => `  ${w} → ${wellness[w] ?? 'n/a'}`),
    '',
    'EVENING REFLECTION',
    `  Daily Highlight: ${dailyHighlight.trim() || '(blank)'}`,
    `  Lesson Learned:  ${lessonLearned.trim() || '(blank)'}`,
  ].join('\n');

  const setPriority = (i, val) => setPriorities(p => { const n = [...p]; n[i] = val; return n; });
  const setWell     = (item, val) => setWellness(w => ({ ...w, [item]: val }));

  const radioBtn = (item, val, label) => {
    const active = wellness[item] === val;
    return (
      <button key={val} onClick={() => setWell(item, active ? null : val)} style={{
        width: 28, height: 22, border: `1px solid ${active ? P.border : P.borderLight}`,
        background: active ? P.ink : P.surface,
        color: active ? '#fff' : P.inkFaint,
        fontSize: 9, fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase',
        fontFamily: 'DM Sans', cursor: 'pointer', transition: 'all 0.12s',
      }}>{label}</button>
    );
  };

  return (
    <div>
      {/* Crisis banner */}
      {crisis && (
        <div style={{ background: P.ink, color: '#fff', padding: '10px 16px',
          marginBottom: 20, display: 'flex', alignItems: 'center',
          justifyContent: 'space-between', flexWrap: 'wrap', gap: 10 }}>
          <span style={{ fontSize: 13, fontWeight: 600 }}>
            If you're in crisis, support is available right now.
          </span>
          <div style={{ display: 'flex', gap: 10 }}>
            <a href="tel:988" style={{ color: '#fff', fontSize: 13, fontWeight: 700,
              background: 'rgba(255,255,255,0.2)', padding: '4px 12px', textDecoration: 'none' }}>
              Call 988
            </a>
            <a href="sms:741741&body=HOME" style={{ color: '#fff', fontSize: 13,
              background: 'rgba(255,255,255,0.2)', padding: '4px 12px', textDecoration: 'none' }}>
              Text HOME to 741741
            </a>
          </div>
        </div>
      )}

      {/* Form header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end',
        borderBottom: `2px solid ${P.bg}`, paddingBottom: 20, marginBottom: 28 }}>
        <h2 style={{ fontFamily: 'DM Serif Display', fontWeight: 400, fontSize: 26,
          color: P.ink, margin: 0, fontStyle: 'italic' }}>Daily Intentions</h2>
        <div style={{ display: 'flex', gap: 20, alignItems: 'flex-end' }}>
          <div style={{ textAlign: 'right' }}>
            <span style={{ ...sectionLabel, display: 'block', marginBottom: 4 }}>Date</span>
            <input type="date" value={date} onChange={e => setDate(e.target.value)}
              style={{ fontSize: 13, fontWeight: 600, color: P.ink, border: 'none',
                outline: 'none', fontFamily: 'DM Sans', background: 'transparent', cursor: 'pointer' }} />
          </div>
          <div style={{ textAlign: 'right' }}>
            <span style={{ ...sectionLabel, display: 'block', marginBottom: 4 }}>Time</span>
            <input type="time" value={time} onChange={e => setTime(e.target.value)}
              style={{ fontSize: 13, fontWeight: 600, color: P.ink, border: 'none',
                outline: 'none', fontFamily: 'DM Sans', background: 'transparent', cursor: 'pointer' }} />
          </div>
        </div>
      </div>

      {/* Two-column body */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 40px' }}>

        {/* ── LEFT COLUMN ── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>

          {/* Daily intention questions */}
          <section>
            <span style={sectionLabel}>Daily Intentions</span>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {DAILY_QUESTIONS.map((q, i) => (
                <div key={i}>
                  <p style={{ fontSize: 12, color: P.inkMid, margin: '0 0 4px', lineHeight: 1.45 }}>{q}</p>
                  <textarea value={dailyAnswers[i]} onChange={e => setDailyAnswer(i, e.target.value)}
                    placeholder="Your answer..."
                    style={underlineTextarea(48)} />
                </div>
              ))}
            </div>
          </section>

          {/* Gratitude */}
          <section>
            <span style={sectionLabel}>Gratitude</span>
            <p style={{ fontSize: 11, fontStyle: 'italic', color: P.inkFaint, margin: '0 0 6px' }}>
              Today I am grateful for...
            </p>
            <textarea value={gratitude} onChange={e => setGratitude(e.target.value)}
              placeholder="Start writing..."
              style={{ ...underlineTextarea(96), background: P.bg }} />
          </section>

          {/* Thought reconstruction */}
          <section>
            <span style={sectionLabel}>Reconstruction</span>
            <p style={{ fontSize: 11, fontStyle: 'italic', color: P.inkFaint, margin: '0 0 14px' }}>
              Reframe a difficult thought
            </p>
            <div style={{ marginBottom: 14 }}>
              <span style={{ fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.07em', color: P.inkFaint }}>
                Original Thought
              </span>
              <textarea value={origThought} onChange={e => setOrigThought(e.target.value)}
                placeholder="What's bothering you?"
                style={underlineTextarea(52)} />
            </div>
            <div>
              <span style={{ fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.07em', color: P.inkFaint }}>
                Positive Reframe
              </span>
              <textarea value={reframe} onChange={e => setReframe(e.target.value)}
                placeholder="How else can you see this?"
                style={{ ...underlineTextarea(52), fontWeight: 500 }} />
            </div>
          </section>
        </div>

        {/* ── RIGHT COLUMN ── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>

          {/* Top 3 priorities */}
          <section>
            <span style={sectionLabel}>Top 3 Priorities</span>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {[0,1,2].map(i => (
                <div key={i} style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                  <span style={{ fontSize: 12, color: P.borderLight, flexShrink: 0 }}>{i + 1}.</span>
                  <input type="text" value={priorities[i]}
                    onChange={e => setPriority(i, e.target.value)}
                    style={underlineInput} />
                </div>
              ))}
            </div>
          </section>

          {/* Wellness check-in */}
          <section>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
              <span style={sectionLabel}>Wellness Check-In</span>
              <div style={{ display: 'flex', gap: 4 }}>
                {['Y','N','—'].map(l => (
                  <span key={l} style={{ width: 28, textAlign: 'center', fontSize: 9,
                    fontWeight: 700, color: P.inkFaint, letterSpacing: '0.04em', textTransform: 'uppercase' }}>
                    {l}
                  </span>
                ))}
              </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              {WELLNESS_ITEMS.map((item, idx) => (
                <div key={item} style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  padding: '7px 0',
                  borderBottom: idx < WELLNESS_ITEMS.length - 1 ? `1px solid ${P.bg}` : 'none',
                }}>
                  <span style={{ fontSize: 12, color: P.inkMid }}>{item}</span>
                  <div style={{ display: 'flex', gap: 4 }}>
                    {radioBtn(item, 'yes', 'Y')}
                    {radioBtn(item, 'no',  'N')}
                    {radioBtn(item, 'na',  '—')}
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Evening reflection */}
          <section>
            <span style={sectionLabel}>Evening Reflection</span>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div>
                <p style={{ fontSize: 11, fontStyle: 'italic', color: P.inkFaint, margin: '0 0 4px' }}>
                  Daily Highlight
                </p>
                <input type="text" value={dailyHighlight}
                  onChange={e => setDailyHighlight(e.target.value)}
                  style={underlineInput} />
              </div>
              <div>
                <p style={{ fontSize: 11, fontStyle: 'italic', color: P.inkFaint, margin: '0 0 4px' }}>
                  Lesson Learned
                </p>
                <input type="text" value={lessonLearned}
                  onChange={e => setLessonLearned(e.target.value)}
                  style={underlineInput} />
              </div>
            </div>
          </section>
        </div>
      </div>

      {/* Save row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginTop: 28, paddingTop: 20, borderTop: `1px solid ${P.bg}` }}>
        <ShareToggle value={shareWithProvider} onChange={onShareChange} />
        <button onClick={() => onSave(compiledEntry(), 'guided')} disabled={submitting}
          style={{ padding: '11px 28px', background: P.ink, color: '#fff',
            border: 'none', fontSize: 13, fontWeight: 600, fontFamily: 'DM Sans',
            cursor: submitting ? 'default' : 'pointer', opacity: submitting ? 0.6 : 1,
            transition: 'opacity 0.15s' }}>
          {submitting ? 'Saving…' : 'Save & Analyze'}
        </button>
      </div>
    </div>
  );
}

// ── Type selection button ─────────────────────────────────────────────────
function TypeButton({ type, active, onClick }) {
  const cfg = TYPE_CONFIG[type];
  return (
    <button onClick={onClick} style={{
      display: 'flex', alignItems: 'center', gap: 8,
      padding: '10px 20px',
      border: `1.5px solid ${active ? P.border : P.borderLight}`,
      background: active ? P.ink : P.surface,
      color: active ? '#fff' : P.inkMid,
      fontSize: 13, fontWeight: 600, fontFamily: 'DM Sans',
      cursor: 'pointer', transition: 'all 0.15s', borderRadius: 2,
    }}>
      <span style={{ fontSize: 15 }}>{cfg.icon}</span>
      {cfg.label}
    </button>
  );
}

// ── Past entry card ───────────────────────────────────────────────────────
function EntryCard({ entry, expanded, onClick }) {
  const typeLabel = { free_flow: 'Free Flow', prompt: 'Prompt', guided: 'Guided' };
  return (
    <button onClick={onClick} style={{
      width: '100%', textAlign: 'left',
      background: expanded ? P.accentLight : P.surface,
      border: `1px solid ${expanded ? P.border : P.borderLight}`,
      padding: '14px 16px', cursor: 'pointer', fontFamily: 'DM Sans',
      transition: 'all 0.12s', display: 'block',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
            letterSpacing: '0.06em', color: P.inkFaint }}>
            {new Date(entry.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
          </span>
          {entry.entry_type && (
            <span style={{ fontSize: 10, color: P.inkFaint,
              border: `1px solid ${P.borderLight}`, padding: '1px 6px' }}>
              {typeLabel[entry.entry_type] || entry.entry_type}
            </span>
          )}
        </div>
        <span style={{ fontSize: 10, color: P.inkFaint }}>{timeAgo(entry.created_at)}</span>
      </div>
      <p style={{ margin: 0, fontSize: 13, color: P.inkMid, lineHeight: 1.55,
        overflow: 'hidden', display: '-webkit-box',
        WebkitLineClamp: expanded ? 'unset' : 2, WebkitBoxOrient: 'vertical' }}>
        {entry.raw_entry}
      </p>
      {expanded && entry.ai_analysis && (
        <div style={{ marginTop: 12, paddingTop: 12, borderTop: `1px solid ${P.borderLight}` }}>
          <p style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
            letterSpacing: '0.06em', color: P.inkFaint, margin: '0 0 6px' }}>AI Reflection</p>
          <p style={{ fontSize: 12, color: P.inkMid, margin: 0, lineHeight: 1.6 }}>{entry.ai_analysis}</p>
        </div>
      )}
    </button>
  );
}

// ── Share-with-provider toggle ────────────────────────────────────────────
function ShareToggle({ value, onChange }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <span style={{ fontSize: 11, color: value ? P.ink : P.inkFaint, fontFamily: 'DM Sans',
        fontWeight: value ? 600 : 400, transition: 'color 0.15s' }}>
        Share with provider
      </span>
      <button
        onClick={() => onChange(!value)}
        aria-label={value ? 'Sharing with provider — click to stop sharing' : 'Not sharing with provider — click to share'}
        style={{
          position: 'relative', width: 40, height: 22,
          border: `1.5px solid ${value ? P.ink : P.borderLight}`,
          background: value ? P.ink : P.surface,
          cursor: 'pointer', padding: 0, outline: 'none',
          transition: 'all 0.18s', flexShrink: 0,
        }}
      >
        <span style={{
          position: 'absolute', top: 2,
          left: value ? 18 : 2,
          width: 14, height: 14,
          background: value ? '#fff' : P.borderLight,
          transition: 'left 0.18s, background 0.18s',
          display: 'block',
        }} />
      </button>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────
export default function CognaSyncJournalCrisisDetection() {
  const [entryType,          setEntryType]          = useState('free_flow');
  const [text,               setText]               = useState('');
  const [entries,            setEntries]            = useState([]);
  const [submitting,         setSubmitting]         = useState(false);
  const [result,             setResult]             = useState(null);
  const [error,              setError]              = useState('');
  const [expandedId,         setExpandedId]         = useState(null);
  const [promptIdx,          setPromptIdx]          = useState(() => Math.floor(Math.random() * PROMPTS.length));
  const [entryDate,          setEntryDate]          = useState(() => new Date().toISOString().slice(0, 10));
  const [entryTime,          setEntryTime]          = useState(() => new Date().toTimeString().slice(0, 5));
  const [shareWithProvider,  setShareWithProvider]  = useState(true);
  const textareaRef = useRef(null);

  const crisis = detectCrisis(text);

  useEffect(() => {
    fetch('/api/journals?limit=20', { credentials: 'same-origin' })
      .then(r => r.ok ? r.json() : null)
      .then(v => { if (v?.journals) setEntries(v.journals); })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = textareaRef.current.scrollHeight + 'px';
    }
  }, [text]);

  const switchType = (type) => {
    setEntryType(type);
    setText('');
    setResult(null);
    setError('');
  };

  const handleSubmit = async (overrideText, overrideType) => {
    const rawBody = overrideText ?? text;
    const type    = overrideType ?? entryType;
    const header  = type !== 'guided' ? `Date: ${entryDate}  Time: ${entryTime}\n\n` : '';
    const body    = header + rawBody;
    if (!body.trim() || submitting) return;
    setSubmitting(true); setError(''); setResult(null);
    try {
      const res = await fetch('/api/journals', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw_entry: body, entry_type: type, share_with_provider: shareWithProvider ? 1 : 0 }),
      });
      const data = await res.json();
      if (!res.ok) { setError(data.error || 'Failed to save entry.'); return; }
      setResult(data);
      setEntries(prev => [data, ...prev]);
      setText('');
    } catch { setError('Network error. Please try again.'); }
    finally { setSubmitting(false); }
  };

  return (
    <div style={{ background: P.bg, minHeight: 'calc(100vh - 52px)', overflowY: 'auto', fontFamily: 'DM Sans' }}>
      <div style={{ maxWidth: 820, margin: '0 auto', padding: '40px 24px 80px' }}>

        {/* Page title */}
        <div style={{ marginBottom: 28 }}>
          <h1 style={{ fontFamily: 'DM Serif Display', fontWeight: 400, fontSize: 32,
            color: P.ink, margin: '0 0 6px', letterSpacing: '-0.02em' }}>Journal</h1>
          <p style={{ color: P.inkFaint, fontSize: 13, margin: 0 }}>Write freely. Reflect honestly.</p>
        </div>

        {/* ── Type buttons — TOP ── */}
        <div style={{ display: 'flex', gap: 10, marginBottom: 28, flexWrap: 'wrap' }}>
          {Object.keys(TYPE_CONFIG).map(type => (
            <TypeButton key={type} type={type} active={entryType === type}
              onClick={() => switchType(type)} />
          ))}
        </div>

        {/* ── Writing area ── */}
        <div style={{ background: P.surface, border: `1px solid ${P.border}`,
          padding: '28px 28px', marginBottom: 48 }}>

          {/* Entry header — free flow + prompt only */}
          {entryType !== 'guided' && (
            <>
              {/* Crisis banner */}
              {crisis && (
                <div style={{ background: P.ink, color: '#fff', padding: '10px 16px',
                  marginBottom: 20, display: 'flex', alignItems: 'center',
                  justifyContent: 'space-between', flexWrap: 'wrap', gap: 10 }}>
                  <span style={{ fontSize: 13, fontWeight: 600 }}>
                    If you're in crisis, support is available right now.
                  </span>
                  <div style={{ display: 'flex', gap: 10 }}>
                    <a href="tel:988" style={{ color: '#fff', fontSize: 13, fontWeight: 700,
                      background: 'rgba(255,255,255,0.2)', padding: '4px 12px', textDecoration: 'none' }}>
                      Call 988
                    </a>
                    <a href="sms:741741&body=HOME" style={{ color: '#fff', fontSize: 13,
                      background: 'rgba(255,255,255,0.2)', padding: '4px 12px', textDecoration: 'none' }}>
                      Text HOME to 741741
                    </a>
                  </div>
                </div>
              )}

              <div style={{ display: 'flex', justifyContent: 'space-between',
                alignItems: 'flex-end', marginBottom: 20 }}>
                <h2 style={{ fontFamily: 'DM Serif Display', fontWeight: 400,
                  fontSize: 22, color: P.ink, margin: 0 }}>New Entry</h2>
                <div style={{ display: 'flex', gap: 16, alignItems: 'flex-end' }}>
                  <div style={{ textAlign: 'right' }}>
                    <span style={{ fontSize: 9, fontWeight: 700, textTransform: 'uppercase',
                      letterSpacing: '0.09em', color: P.inkFaint, display: 'block', marginBottom: 3 }}>Date</span>
                    <input type="date" value={entryDate} onChange={e => setEntryDate(e.target.value)}
                      style={{ fontSize: 12, fontWeight: 600, color: P.ink, border: 'none',
                        outline: 'none', fontFamily: 'DM Sans', background: 'transparent', cursor: 'pointer' }} />
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <span style={{ fontSize: 9, fontWeight: 700, textTransform: 'uppercase',
                      letterSpacing: '0.09em', color: P.inkFaint, display: 'block', marginBottom: 3 }}>Time</span>
                    <input type="time" value={entryTime} onChange={e => setEntryTime(e.target.value)}
                      style={{ fontSize: 12, fontWeight: 600, color: P.ink, border: 'none',
                        outline: 'none', fontFamily: 'DM Sans', background: 'transparent', cursor: 'pointer' }} />
                  </div>
                </div>
              </div>
            </>
          )}

          {/* ── FREE FLOW ── */}
          {entryType === 'free_flow' && (
            <>
              <textarea ref={textareaRef} value={text} onChange={e => setText(e.target.value)}
                placeholder={TYPE_CONFIG.free_flow.placeholder}
                style={{ width: '100%', minHeight: 180, padding: '14px 0', border: 'none',
                  borderTop: `1px solid ${P.borderLight}`, borderBottom: `1px solid ${P.borderLight}`,
                  background: 'transparent', color: P.ink, fontSize: 15, lineHeight: 1.75,
                  fontFamily: 'DM Sans', resize: 'none', outline: 'none', boxSizing: 'border-box' }} />
              <div style={{ display: 'flex', justifyContent: 'space-between',
                alignItems: 'center', marginTop: 14 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
                  <span style={{ fontSize: 11, color: P.inkFaint }}>{text.length} characters</span>
                  <ShareToggle value={shareWithProvider} onChange={setShareWithProvider} />
                </div>
                <button onClick={() => handleSubmit()} disabled={!text.trim() || submitting}
                  style={{ padding: '11px 26px',
                    background: text.trim() ? P.ink : P.borderLight,
                    color: '#fff', border: 'none',
                    cursor: text.trim() ? 'pointer' : 'default',
                    fontSize: 13, fontWeight: 600, fontFamily: 'DM Sans',
                    transition: 'background 0.15s' }}>
                  {submitting ? 'Analyzing…' : 'Save & Analyze'}
                </button>
              </div>
            </>
          )}

          {/* ── JOURNAL PROMPT ── */}
          {entryType === 'prompt' && (
            <>
              <div style={{ background: P.accentLight, border: `1px solid ${P.borderLight}`,
                padding: '16px 18px', marginBottom: 20 }}>
                <p style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
                  letterSpacing: '0.07em', color: P.inkFaint, margin: '0 0 8px' }}>Today's Prompt</p>
                <p style={{ fontSize: 15, color: P.ink, margin: '0 0 12px',
                  lineHeight: 1.6, fontStyle: 'italic' }}>
                  {PROMPTS[promptIdx]}
                </p>
                <button onClick={() => setPromptIdx(i => (i + 1) % PROMPTS.length)}
                  style={{ fontSize: 11, color: P.inkFaint, background: 'none', border: 'none',
                    cursor: 'pointer', padding: 0, textDecoration: 'underline', fontFamily: 'DM Sans' }}>
                  New prompt
                </button>
              </div>
              <textarea ref={textareaRef} value={text} onChange={e => setText(e.target.value)}
                placeholder={TYPE_CONFIG.prompt.placeholder}
                style={{ width: '100%', minHeight: 160, padding: '14px 0', border: 'none',
                  borderTop: `1px solid ${P.borderLight}`, borderBottom: `1px solid ${P.borderLight}`,
                  background: 'transparent', color: P.ink, fontSize: 15, lineHeight: 1.75,
                  fontFamily: 'DM Sans', resize: 'none', outline: 'none', boxSizing: 'border-box' }} />
              <div style={{ display: 'flex', justifyContent: 'space-between',
                alignItems: 'center', marginTop: 14 }}>
                <ShareToggle value={shareWithProvider} onChange={setShareWithProvider} />
                <button onClick={() => handleSubmit()} disabled={!text.trim() || submitting}
                  style={{ padding: '11px 26px',
                    background: text.trim() ? P.ink : P.borderLight,
                    color: '#fff', border: 'none',
                    cursor: text.trim() ? 'pointer' : 'default',
                    fontSize: 13, fontWeight: 600, fontFamily: 'DM Sans' }}>
                  {submitting ? 'Analyzing…' : 'Save & Analyze'}
                </button>
              </div>
            </>
          )}

          {/* ── GUIDED JOURNAL ── */}
          {entryType === 'guided' && (
            <GuidedJournalForm onSave={handleSubmit} submitting={submitting}
              shareWithProvider={shareWithProvider} onShareChange={setShareWithProvider} />
          )}

          {/* Error */}
          {error && (
            <div style={{ marginTop: 16, padding: '12px 16px',
              border: `1px solid ${P.border}`, background: P.accentLight }}>
              <p style={{ margin: 0, fontSize: 13, color: P.ink }}>{error}</p>
            </div>
          )}

          {/* Result */}
          {result && (
            <div style={{ marginTop: 20 }}>
              {result.alert === 'crisis' ? (
                <div style={{ padding: '18px 20px', border: `1px solid ${P.border}`, background: P.surface }}>
                  <p style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
                    letterSpacing: '0.07em', color: P.ink, margin: '0 0 8px' }}>A note from CognaSync</p>
                  <p style={{ fontSize: 14, color: P.inkMid, lineHeight: 1.7, margin: 0 }}>{result.ai_analysis}</p>
                </div>
              ) : (
                <div style={{ padding: '18px 20px', border: `1px solid ${P.borderLight}`, background: P.accentLight }}>
                  <p style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
                    letterSpacing: '0.07em', color: P.inkFaint, margin: '0 0 8px' }}>AI Reflection</p>
                  <p style={{ fontSize: 14, color: P.inkMid, lineHeight: 1.7, margin: '0 0 12px' }}>{result.ai_analysis}</p>
                  <p style={{ fontSize: 11, color: P.inkFaint, margin: 0 }}>
                    Entry saved · {new Date().toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── Past entries — BOTTOM ── */}
        <div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10,
            paddingBottom: 14, borderBottom: `1px solid ${P.border}`, marginBottom: 4 }}>
            <h2 style={{ fontFamily: 'DM Serif Display', fontWeight: 400,
              fontSize: 20, color: P.ink, margin: 0 }}>Past Entries</h2>
            {entries.length > 0 && (
              <span style={{ fontSize: 11, color: P.inkFaint,
                border: `1px solid ${P.borderLight}`, padding: '1px 8px', borderRadius: 999 }}>
                {entries.length}
              </span>
            )}
          </div>

          {entries.length === 0 ? (
            <p style={{ color: P.inkFaint, fontSize: 13, paddingTop: 20 }}>
              No entries yet. Write your first one above.
            </p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
              {entries.map(e => (
                <EntryCard key={e.journal_id || e.id} entry={e}
                  expanded={expandedId === (e.journal_id || e.id)}
                  onClick={() => setExpandedId(
                    expandedId === (e.journal_id || e.id) ? null : (e.journal_id || e.id)
                  )} />
              ))}
            </div>
          )}
        </div>

      </div>
    </div>
  );
}
