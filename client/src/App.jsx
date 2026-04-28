import React, { useState, useEffect, useMemo, useCallback } from 'react';

// ── Wireframe palette ──────────────────────────────────────────────────
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
  accentHover: '#333333',
  accentLight: '#ECECEC',
};

const STEP_COLORS = {
  intro:     { fg: '#000000', bg: '#ECECEC', mid: '#333333' },
  core:      { fg: '#000000', bg: '#ECECEC', mid: '#333333' },
  sleep:     { fg: '#000000', bg: '#ECECEC', mid: '#333333' },
  meds:      { fg: '#000000', bg: '#ECECEC', mid: '#333333' },
  nutrition: { fg: '#000000', bg: '#ECECEC', mid: '#333333' },
  summary:   { fg: '#000000', bg: '#ECECEC', mid: '#333333' },
};

// ── Guardrails ────────────────────────────────────────────────────────
const G = {
  hasDx:  t => ['diagnos','disorder','illness','disease','symptom','syndrome','relapse','episode'].some(w => t.toLowerCase().includes(w)),
  hasMed: t => ['increase','decrease','adjust','discontinue','should take'].some(w => t.toLowerCase().includes(w) && (t.toLowerCase().includes('medication') || t.toLowerCase().includes('dose'))),
  isData: t => /\d+/.test(t) || (/day|week|month|hour/.test(t.toLowerCase()) && /score|average|rating|trend/.test(t.toLowerCase())),
  crisis: t => ['suicide','suicidal','kill myself','hurt myself','self-harm',"can't go on",'want to die','end it'].some(w => t.toLowerCase().includes(w)),
  pass:  (t, l) => {
    if (l === 1 && (G.hasDx(t) || !G.isData(t))) return false;
    if (l === 2 && (G.hasDx(t) || G.hasMed(t))) return false;
    if (l === 4 && G.hasDx(t)) return false;
    return true;
  },
};

const DEFAULT_BL = { avgMood: 6.8, avgEnergy: 6.5, avgAnxiety: 3.2, avgSleepHours: 5.9, avgSleepQuality: 6.2, avgCaffeineMg: 280, optimalCaffeine: { min: 200, max: 300 } };

function totalCaffeine(caf) {
  return (caf.coffee || 0) * 95 + (caf.tea || 0) * 47 + (caf.soda || 0) * 35 + (caf.energy || 0) * 150;
}

function calcScores(d, bl) {
  const caffeineMg = totalCaffeine(d.caffeine);
  const stability = (d.mood + d.energy + (10 - d.dissociation) + (10 - d.anxiety)) / 4;
  const dopamine  = (d.energy + d.focus) / 2;
  const stim      = caffeineMg > 300 ? 8 : caffeineMg > 200 ? 5 : 2;
  const nsLoad    = (d.anxiety + (10 - d.sleepQuality) + stim) / 3;

  let sleepDis = 0;
  if ((d.timeAwakeMinutes / 480) * 100 > 20) sleepDis += 3;
  if (d.sleepLatencyMinutes > 30) sleepDis += 3;
  if (d.nightAwakenings >= 2) sleepDis += 2;
  if (d.sleepHours < 6) sleepDis += 2;

  const crashRisk   = sleepDis * 0.5 + nsLoad * 0.5;
  const moodDistort = Math.abs(d.mood - stability);
  return { stability, dopamine, nsLoad, sleepDis, caffeineMg, crashRisk, moodDistort,
    moodDev: d.mood - bl.avgMood, anxietyDev: d.anxiety - bl.avgAnxiety };
}

function calcInsights(d, bl, sc) {
  if (G.crisis(d.notes)) return { crisis: true };
  const out = [];
  const sd = d.sleepHours - bl.avgSleepHours;
  out.push({ l: 1, cat: 'sleep', conf: 100, text: `You slept ${d.sleepHours}h — ${sd > 0.5 ? 'more' : sd < -0.5 ? 'less' : 'about the same'} than your 7-day average of ${bl.avgSleepHours.toFixed(1)}h.` });
  if (sc.caffeineMg > 0) {
    const cd = sc.caffeineMg - (bl.avgCaffeineMg || 0);
    out.push({ l: 1, cat: 'caffeine', conf: 100, text: `${sc.caffeineMg}mg caffeine today — ${cd > 20 ? `${Math.round(cd)}mg above` : cd < -20 ? `${Math.round(Math.abs(cd))}mg below` : 'near'} your typical intake.` });
  }
  if (sc.moodDistort > 2 && sc.moodDistort <= 4)
    out.push({ l: 2, cat: 'perception', conf: 72, text: `Your reported mood (${d.mood}/10) is ${d.mood > sc.stability ? 'higher' : 'lower'} than your stability score (${sc.stability.toFixed(1)}/10), which factors in sleep, anxiety, and energy.` });
  if (sc.nsLoad > 6 && d.sleepQuality < 6)
    out.push({ l: 2, cat: 'nervous system', conf: 75, text: `Elevated nervous system load (${sc.nsLoad.toFixed(1)}/10) combined with low sleep quality tends to correlate with difficulty settling in the evening.` });
  if (sc.moodDistort > 2)
    out.push({ l: 3, cat: 'reflection', conf: 60, text: `Your mood rating and stability score don't quite align. What felt different about today?` });
  if (sc.crashRisk > 6)
    out.push({ l: 4, cat: 'provider', conf: 82, text: `Disrupted sleep, high stimulation, and elevated anxiety together may be worth flagging for your provider if this pattern continues.` });
  return out.filter(i => G.pass(i.text, i.l)).sort((a, b) => a.l - b.l);
}

// ── Shared sub-components ─────────────────────────────────────────────

function ScoreRing({ value, max = 10, label, sub, danger }) {
  const pct = Math.min(value / max, 1);
  const sz = 88, r = 32, circ = 2 * Math.PI * r;
  const color = danger
    ? (value < 3 ? '#000000' : value < 6 ? '#555555' : '#000000')
    : (value > 7 ? '#000000' : value > 4 ? '#333333' : '#555555');
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
      <div style={{ position: 'relative', width: sz, height: sz }}>
        <svg width={sz} height={sz} style={{ transform: 'rotate(-90deg)' }}>
          <circle cx={sz/2} cy={sz/2} r={r} fill="none" stroke={P.borderLight} strokeWidth="7" />
          <circle cx={sz/2} cy={sz/2} r={r} fill="none" stroke={color} strokeWidth="7"
            strokeDasharray={circ} strokeDashoffset={circ * (1 - pct)} strokeLinecap="round"
            style={{ transition: 'stroke-dashoffset 0.8s cubic-bezier(0.4,0,0.2,1)' }} />
        </svg>
        <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <span style={{ color, fontSize: 19, fontWeight: 700, fontFamily: 'DM Sans' }}>{value.toFixed(1)}</span>
        </div>
      </div>
      <p style={{ color: P.ink, fontSize: 12, fontWeight: 600, textAlign: 'center', margin: 0 }}>{label}</p>
      {sub && <p style={{ color: P.inkFaint, fontSize: 11, textAlign: 'center', margin: 0 }}>{sub}</p>}
    </div>
  );
}

function InkSlider({ label, value, onChange, min = 0, max = 10, step = 1, lo, hi, color }) {
  const c = color || P.accent;
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <div style={{ marginBottom: 28 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
        <label style={{ color: P.inkMid, fontSize: 12, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase' }}>{label}</label>
        <span style={{ color: c, fontSize: 26, fontWeight: 700, fontFamily: 'DM Serif Display', lineHeight: 1 }}>{step < 1 ? value.toFixed(1) : value}</span>
      </div>
      <div style={{ position: 'relative', height: 6, borderRadius: 2, background: P.borderLight, cursor: 'pointer' }}>
        <div style={{ position: 'absolute', left: 0, top: 0, height: '100%', width: `${pct}%`,
          borderRadius: 2, background: c, transition: 'width 0.08s' }} />
        <input type="range" min={min} max={max} step={step} value={value}
          onChange={e => onChange(step < 1 ? parseFloat(e.target.value) : parseInt(e.target.value))}
          style={{ position: 'absolute', inset: 0, width: '100%', opacity: 0, cursor: 'pointer', margin: 0, height: '100%' }} />
        <div style={{ position: 'absolute', top: '50%', left: `${pct}%`, transform: 'translate(-50%, -50%)',
          width: 16, height: 16, borderRadius: '50%', background: P.surface,
          border: `2px solid ${c}`,
          transition: 'left 0.08s', pointerEvents: 'none' }} />
      </div>
      {(lo || hi) && (
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 5 }}>
          <span style={{ color: P.inkFaint, fontSize: 11 }}>{lo}</span>
          <span style={{ color: P.inkFaint, fontSize: 11 }}>{hi}</span>
        </div>
      )}
    </div>
  );
}

function PaperToggle({ label, checked, onChange, color }) {
  const c = color || P.accent;
  return (
    <button onClick={() => onChange(!checked)}
      style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '11px 14px',
        borderRadius: 2, border: `1px solid ${checked ? c : P.borderLight}`,
        background: checked ? P.accentLight : P.surface, cursor: 'pointer',
        textAlign: 'left', width: '100%', transition: 'all 0.15s', marginBottom: 10 }}>
      <div style={{ width: 16, height: 16, borderRadius: 2,
        border: `1.5px solid ${checked ? c : P.borderLight}`,
        background: checked ? c : 'transparent', flexShrink: 0,
        display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'all 0.15s' }}>
        {checked && <svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M2 5l2.5 2.5 3.5-4" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>}
      </div>
      <span style={{ color: P.ink, fontSize: 14, fontWeight: 500 }}>{label}</span>
    </button>
  );
}

function PaperSelect({ label, value, onChange, options }) {
  return (
    <div style={{ marginBottom: 20 }}>
      <label style={{ color: P.inkMid, fontSize: 12, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', display: 'block', marginBottom: 7 }}>{label}</label>
      <select value={value} onChange={e => onChange(e.target.value)}
        style={{ width: '100%', padding: '10px 14px', borderRadius: 2, border: `1px solid ${P.border}`,
          background: P.surface, color: P.ink, fontSize: 14, outline: 'none', cursor: 'pointer',
          fontFamily: 'DM Sans', appearance: 'none' }}>
        {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}

function PaperNumInput({ label, value, onChange, min, max, step = 1, unit, hint, color }) {
  const c = color || P.accent;
  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 7 }}>
        <label style={{ color: P.inkMid, fontSize: 12, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase' }}>{label}</label>
        <span style={{ color: c, fontSize: 16, fontWeight: 700 }}>{value}{unit}</span>
      </div>
      <input type="number" min={min} max={max} step={step} value={value}
        onChange={e => onChange(parseFloat(e.target.value) || 0)}
        style={{ width: '100%', padding: '10px 14px', borderRadius: 2, border: `1px solid ${P.border}`,
          background: P.surface, color: P.ink, fontSize: 14, outline: 'none', fontFamily: 'DM Sans' }} />
      {hint && <p style={{ color: P.inkFaint, fontSize: 11, marginTop: 5 }}>{hint}</p>}
    </div>
  );
}

const Divider = () => <div style={{ height: 1, background: P.borderLight, margin: '20px 0' }} />;

const CHECKIN_TYPES = [
  { id: 'morning',   label: 'Morning',   desc: 'Full check-in with sleep tracking. Best done before noon.', tag: 'Includes sleep' },
  { id: 'afternoon', label: 'Afternoon', desc: 'Mid-day status — mood, focus, and medications.', tag: 'Quick · 3 min' },
  { id: 'evening',   label: 'Evening',   desc: 'End-of-day reflection. Mood, energy, medication review.', tag: 'Quick · 3 min' },
  { id: 'on_demand', label: 'On-Demand', desc: 'Capture your current state at any time.', tag: 'Anytime' },
];

function getFlow(checkinType) {
  return checkinType === 'morning'
    ? ['intro', 'core', 'sleep', 'meds', 'summary']
    : ['intro', 'core', 'meds', 'summary'];
}

export default function App() {
  const [checkinType, setCheckinType] = useState(null);
  const [stepIdx, setStepIdx] = useState(0);
  const [bl, setBl] = useState(DEFAULT_BL);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveErr, setSaveErr] = useState('');
  const [aiInsight, setAiInsight] = useState('');
  const [entryDate, setEntryDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [entryTime, setEntryTime] = useState(() => new Date().toTimeString().slice(0, 5));
  const [completedToday, setCompletedToday] = useState([]);

  const [d, setD] = useState({
    timeOfCheckIn: new Date().getHours(),
    mood: 6, energy: 6, dissociation: 1, anxiety: 3, focus: 6,
    sleepHours: 6, sleepQuality: 6, timeAwakeMinutes: 0,
    sleepLatencyMinutes: 0, nightAwakenings: 0,
    caffeine: { coffee: 0, tea: 0, soda: 0, energy: 0 },
    meds: {}, notes: '',
  });

  useEffect(() => {
    fetch('/api/checkins/baseline', { credentials: 'same-origin' })
      .then(r => r.ok ? r.json() : null).then(v => { if (v && Object.keys(v).length) setBl(p => ({ ...p, ...v })); }).catch(() => {});
    fetch('/api/patient/profile', { credentials: 'same-origin' })
      .then(r => r.ok ? r.json() : null).then(v => {
        if (!v) return;
        const meds = {};
        (v.current_medications || []).forEach(m => {
          const key = m.dose ? `${m.name}|||${m.dose}` : m.name;
          meds[key] = { name: m.name, taken: false, dose: m.dose || '', timeTaken: '' };
        });
        setD(p => ({ ...p, meds }));
      }).catch(() => {});
    fetch('/api/checkins/today', { credentials: 'same-origin' })
      .then(r => r.ok ? r.json() : null).then(v => { if (v) setCompletedToday(v.completed || []); }).catch(() => {});
  }, []);

  const sc = useMemo(() => calcScores(d, bl), [d, bl]);
  const ins = useMemo(() => calcInsights(d, bl, sc), [d, sc, bl]);
  const set = useCallback((k, v) => setD(p => ({ ...p, [k]: v })), []);

  const FLOW = getFlow(checkinType);
  const stepId = FLOW[stepIdx];
  const clr = STEP_COLORS[stepId] || STEP_COLORS.intro;
  const next = () => setStepIdx(i => Math.min(i + 1, FLOW.length - 1));
  const back = () => setStepIdx(i => Math.max(i - 1, 0));

  const handleSave = async () => {
    setSaving(true); setSaveErr('');
    try {
      const medList = Object.entries(d.meds).map(([,i]) => ({ name: i.name, dose: i.dose, taken: i.taken, time_taken: i.timeTaken || null }));
      const res = await fetch('/api/checkins', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mood_score: d.mood, stress_score: d.anxiety, sleep_hours: d.sleepHours,
          medications: medList, notes: d.notes,
          date: entryDate, time_of_day: entryTime,
          checkin_type: checkinType,
          extended_data: { energy: d.energy, focus: d.focus, dissociation: d.dissociation,
            sleep_quality: d.sleepQuality, time_awake_minutes: d.timeAwakeMinutes,
            night_awakenings: d.nightAwakenings,
            caffeine_mg: sc.caffeineMg,
            caffeine_breakdown: d.caffeine,
            scores: { stability: sc.stability, crash_risk: sc.crashRisk, nervous_system_load: sc.nsLoad, dopamine_efficiency: sc.dopamine } },
        }),
      });
      if (res.ok) {
        const body = await res.json().catch(() => ({}));
        if (body.ai_insight) setAiInsight(body.ai_insight);
        setSaved(true);
        setTimeout(() => setSaved(false), 4000);
        if (checkinType !== 'on_demand') {
          setCompletedToday(prev => prev.includes(checkinType) ? prev : [...prev, checkinType]);
        }
      } else { const e = await res.json().catch(() => ({})); setSaveErr(e.error || 'Save failed.'); }
    } catch { setSaveErr('Network error.'); }
    finally { setSaving(false); }
  };

  // ── Left panel content ──────────────────────────────────────────────
  const leftContent = {
    intro: <>
      <h1 style={{ fontFamily: 'DM Serif Display', fontWeight: 400, fontSize: 36, color: P.ink, margin: '0 0 14px', lineHeight: 1.2, letterSpacing: '-0.02em' }}>Daily<br/>Check-In</h1>
      <p style={{ color: P.inkMid, fontSize: 15, lineHeight: 1.7, margin: '0 0 28px' }}>Five minutes. Real patterns. Personalized to you.</p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {[['Mental state'],['Sleep quality'],['Medications & caffeine'],['Live scores + insights']].map(([l]) => (
          <div key={l} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 4, height: 4, borderRadius: '50%', background: P.border, flexShrink: 0 }} />
            <span style={{ color: P.inkMid, fontSize: 14 }}>{l}</span>
          </div>
        ))}
      </div>
    </>,

    core: <>
      <h2 style={{ fontFamily: 'DM Serif Display', fontWeight: 400, fontSize: 30, color: P.ink, margin: '0 0 10px' }}>Mental State</h2>
      <p style={{ color: P.inkMid, fontSize: 14, lineHeight: 1.65, margin: '0 0 28px' }}>Five signals that feed your stability and crash-risk scores in real time.</p>
      <div style={{ padding: 18, background: clr.bg, border: `1px solid ${P.border}` }}>
        <p style={{ color: P.inkFaint, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.07em', margin: '0 0 8px' }}>Current estimate</p>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
          <span style={{ color: P.ink, fontSize: 40, fontFamily: 'DM Serif Display' }}>{sc.stability.toFixed(1)}</span>
          <span style={{ color: P.inkFaint, fontSize: 14 }}>/10 stability</span>
        </div>
        <p style={{ color: P.inkFaint, fontSize: 11, margin: '6px 0 0' }}>Your baseline: {bl.avgMood.toFixed(1)}</p>
      </div>
    </>,

    sleep: <>
      <h2 style={{ fontFamily: 'DM Serif Display', fontWeight: 400, fontSize: 30, color: P.ink, margin: '0 0 10px' }}>Last Night's Sleep</h2>
      <p style={{ color: P.inkMid, fontSize: 14, lineHeight: 1.65, margin: '0 0 28px' }}>Sleep quality is the strongest single predictor in your crash-risk score.</p>
      <div style={{ padding: 18, background: clr.bg, border: `1px solid ${P.border}` }}>
        <p style={{ color: P.inkFaint, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.07em', margin: '0 0 8px' }}>Sleep disruption</p>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
          <span style={{ color: P.ink, fontSize: 40, fontFamily: 'DM Serif Display' }}>{sc.sleepDis}</span>
          <span style={{ color: P.inkFaint, fontSize: 14 }}>pts</span>
        </div>
        <p style={{ color: P.inkFaint, fontSize: 11, margin: '6px 0 0' }}>{sc.sleepDis < 3 ? 'Restful night' : sc.sleepDis < 6 ? 'Some disruption' : 'Significant disruption'}</p>
      </div>
    </>,

    meds: <>
      <h2 style={{ fontFamily: 'DM Serif Display', fontWeight: 400, fontSize: 30, color: P.ink, margin: '0 0 10px' }}>Medications & Caffeine</h2>
      <p style={{ color: P.inkMid, fontSize: 14, lineHeight: 1.65, margin: '0 0 28px' }}>Log what you took and your caffeine intake today.</p>
      <div style={{ padding: 18, background: clr.bg, border: `1px solid ${P.border}` }}>
        <p style={{ color: P.inkFaint, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.07em', margin: '0 0 8px' }}>Total caffeine today</p>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
          <span style={{ color: P.ink, fontSize: 40, fontFamily: 'DM Serif Display' }}>{sc.caffeineMg}</span>
          <span style={{ color: P.inkFaint, fontSize: 14 }}>mg</span>
        </div>
        {bl.avgCaffeineMg > 0 && (
          <p style={{ color: P.inkFaint, fontSize: 11, margin: '6px 0 0' }}>Your typical: {bl.avgCaffeineMg}mg</p>
        )}
      </div>
    </>,

    summary: ins.crisis ? <>
      <h2 style={{ fontFamily: 'DM Serif Display', fontWeight: 400, fontSize: 30, color: P.ink, margin: '0 0 10px' }}>You're not alone</h2>
      <p style={{ color: P.inkMid, fontSize: 14, lineHeight: 1.65 }}>Crisis support is available 24 hours a day.</p>
    </> : <>
      <h2 style={{ fontFamily: 'DM Serif Display', fontWeight: 400, fontSize: 30, color: P.ink, margin: '0 0 20px' }}>Today's Scores</h2>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
        <ScoreRing value={sc.stability} label="Stability"    sub={`baseline ${bl.avgMood.toFixed(1)}`} />
        <ScoreRing value={sc.crashRisk} label="Crash Risk"   sub="next 6h" danger />
        <ScoreRing value={sc.nsLoad}    label="NS Load"      sub="lower = calmer" danger />
        <ScoreRing value={sc.dopamine}  label="Dopamine" />
      </div>
      {sc.moodDistort > 1.5 && (
        <div style={{ marginTop: 20, padding: '12px 14px', background: P.accentLight, border: `1px solid ${P.border}` }}>
          <p style={{ color: P.inkMid, fontSize: 12, margin: 0, lineHeight: 1.55 }}>
            Mood ({d.mood}/10) and stability ({sc.stability.toFixed(1)}/10) differ. Feelings and data sometimes tell different stories.
          </p>
        </div>
      )}
    </>,
  };

  // ── Right panel content ─────────────────────────────────────────────
  const rightContent = {
    intro: (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <div style={{ padding: '20px 22px', background: P.surface, border: `1px solid ${P.border}` }}>
          <p style={{ color: P.inkMid, fontSize: 14, lineHeight: 1.75, margin: 0 }}>
            Every check-in builds a model of <em style={{ color: P.ink, fontStyle: 'normal', fontWeight: 600 }}>your</em> patterns — how sleep, caffeine, and nutrition affect your mood and energy. Nothing is assumed. Everything is calculated from your actual data.
          </p>
        </div>

        {/* Date & time of entry */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div>
            <label style={{ display: 'block', color: P.inkFaint, fontSize: 11, fontWeight: 700,
              textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>
              Date of Entry
            </label>
            <input type="date" value={entryDate} onChange={e => setEntryDate(e.target.value)}
              style={{ width: '100%', padding: '10px 12px', border: `1px solid ${P.border}`,
                background: P.surface, color: P.ink, fontSize: 13, fontFamily: 'DM Sans',
                outline: 'none', boxSizing: 'border-box', cursor: 'pointer' }} />
          </div>
          <div>
            <label style={{ display: 'block', color: P.inkFaint, fontSize: 11, fontWeight: 700,
              textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>
              Time of Entry
            </label>
            <input type="time" value={entryTime} onChange={e => setEntryTime(e.target.value)}
              style={{ width: '100%', padding: '10px 12px', border: `1px solid ${P.border}`,
                background: P.surface, color: P.ink, fontSize: 13, fontFamily: 'DM Sans',
                outline: 'none', boxSizing: 'border-box', cursor: 'pointer' }} />
          </div>
        </div>

        <button onClick={next}
          style={{ padding: '16px 28px', border: `2px solid ${P.border}`, cursor: 'pointer',
            background: P.border, color: '#fff', fontSize: 16, fontWeight: 600, fontFamily: 'DM Sans',
            letterSpacing: '0.01em' }}>
          Begin Check-In →
        </button>
        <a href="/" style={{ color: P.inkFaint, fontSize: 13, textAlign: 'center', textDecoration: 'none' }}>← Back to dashboard</a>
      </div>
    ),

    core: (
      <div>
        <InkSlider label="Mood"                  value={d.mood}        onChange={v => set('mood', v)}        lo="Very Low"   hi="Excellent"    color={clr.fg} />
        <InkSlider label="Energy"                value={d.energy}      onChange={v => set('energy', v)}      lo="Exhausted"  hi="Energized"    color={clr.fg} />
        <InkSlider label="Focus / Clarity"       value={d.focus}       onChange={v => set('focus', v)}       lo="Foggy"      hi="Sharp"        color={clr.fg} />
        <InkSlider label="Dissociation"          value={d.dissociation}onChange={v => set('dissociation', v)}lo="Grounded"   hi="Detached"     color={clr.fg} />
        <InkSlider label="Anxiety"               value={d.anxiety}     onChange={v => set('anxiety', v)}     lo="Calm"       hi="Overwhelmed"  color={clr.fg} />
      </div>
    ),

    sleep: (
      <div>
        <div style={{ marginBottom: 28 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
            <label style={{ color: P.inkMid, fontSize: 12, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase' }}>Total Hours</label>
            <span style={{ color: clr.fg, fontSize: 26, fontWeight: 700, fontFamily: 'DM Serif Display', lineHeight: 1 }}>{d.sleepHours.toFixed(1)}h</span>
          </div>
          <div style={{ position: 'relative', height: 6, borderRadius: 2, background: P.borderLight }}>
            <div style={{ position: 'absolute', left: 0, top: 0, height: '100%', borderRadius: 2,
              width: `${(d.sleepHours / 12) * 100}%`, background: clr.fg, transition: 'width 0.08s' }} />
            <input type="range" min="0" max="12" step="0.5" value={d.sleepHours}
              onChange={e => set('sleepHours', parseFloat(e.target.value))}
              style={{ position: 'absolute', inset: 0, width: '100%', opacity: 0, cursor: 'pointer', margin: 0, height: '100%' }} />
            <div style={{ position: 'absolute', top: '50%', left: `${(d.sleepHours / 12) * 100}%`,
              transform: 'translate(-50%, -50%)', width: 16, height: 16, borderRadius: '50%',
              background: P.surface, border: `2px solid ${clr.fg}`, pointerEvents: 'none', transition: 'left 0.08s' }} />
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 5 }}>
            <span style={{ color: P.inkFaint, fontSize: 11 }}>0h</span>
            <span style={{ color: P.inkFaint, fontSize: 11 }}>12h</span>
          </div>
        </div>
        <InkSlider label="Sleep Quality"    value={d.sleepQuality}    onChange={v => set('sleepQuality', v)}    lo="Terrible"  hi="Excellent"  color={clr.fg} />
        <PaperNumInput label="Minutes Awake"  value={d.timeAwakeMinutes}  onChange={v => set('timeAwakeMinutes', v)}  min={0} max={240} step={5}  unit="min" color={clr.fg} />
        <PaperSelect label="Night Awakenings" value={String(d.nightAwakenings)} onChange={v => set('nightAwakenings', parseInt(v))}
          options={[{value:'0',label:'None'},{value:'1',label:'Once'},{value:'2',label:'Twice'},{value:'3',label:'3+'}]} />
      </div>
    ),

    meds: (
      <div>
        {Object.keys(d.meds).length === 0 ? (
          <div style={{ padding: '18px 20px', background: P.surface, border: `1px solid ${P.border}`, marginBottom: 20 }}>
            <p style={{ color: P.inkMid, fontSize: 14, margin: 0 }}>No medications on your profile. <a href="/settings" style={{ color: P.ink }}>Add them in Settings →</a></p>
          </div>
        ) : (
          <div style={{ marginBottom: 24 }}>
            <p style={{ color: P.inkFaint, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.07em', margin: '0 0 10px' }}>Taken today</p>
            {Object.entries(d.meds).map(([key, info]) => (
              <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8,
                border: `1px solid ${P.borderLight}`, background: P.surface, padding: '6px 12px' }}>
                <div style={{ flex: 1 }}>
                  <PaperToggle label={`${(info.name || key).charAt(0).toUpperCase() + (info.name || key).slice(1)} ${info.dose ? `(${info.dose})` : ''}`}
                    checked={info.taken} onChange={v => set('meds', { ...d.meds, [key]: { ...info, taken: v } })} color={clr.fg} />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2 }}>
                  <label style={{ fontSize: 10, color: P.inkFaint, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Time Taken</label>
                  <input
                    type="time"
                    value={info.timeTaken || ''}
                    onChange={e => set('meds', { ...d.meds, [key]: { ...info, timeTaken: e.target.value } })}
                    style={{ fontSize: 13, padding: '3px 7px', border: `1px solid ${info.timeTaken ? P.border : P.borderLight}`,
                      background: P.bg, color: P.ink, fontFamily: 'inherit', outline: 'none', width: 110 }}
                  />
                </div>
              </div>
            ))}
          </div>
        )}

        <p style={{ color: P.inkFaint, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.07em', margin: '0 0 12px' }}>Caffeine today</p>
        {[
          { key: 'coffee', label: 'Coffee',       unit: 'cups', mg: 95 },
          { key: 'tea',    label: 'Tea',           unit: 'cups', mg: 47 },
          { key: 'soda',   label: 'Soda',          unit: 'cans', mg: 35 },
          { key: 'energy', label: 'Energy Drink',  unit: 'cans', mg: 150 },
        ].map(bev => {
          const val = d.caffeine[bev.key] || 0;
          return (
            <div key={bev.key} style={{ display: 'flex', alignItems: 'center', marginBottom: 12,
              border: `1px solid ${P.borderLight}`, background: P.surface }}>
              <div style={{ flex: 1, padding: '10px 14px', borderRight: `1px solid ${P.borderLight}` }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: P.ink }}>{bev.label}</div>
                <div style={{ fontSize: 11, color: P.inkFaint }}>{bev.mg}mg per {bev.unit.slice(0,-1)}</div>
              </div>
              <button onClick={() => set('caffeine', { ...d.caffeine, [bev.key]: Math.max(0, val - 1) })}
                style={{ width: 40, height: 52, border: 'none', borderRight: `1px solid ${P.borderLight}`,
                  background: 'transparent', fontSize: 18, cursor: 'pointer', color: P.inkMid }}>−</button>
              <div style={{ width: 44, textAlign: 'center', fontSize: 16, fontWeight: 700, color: P.ink }}>{val}</div>
              <button onClick={() => set('caffeine', { ...d.caffeine, [bev.key]: val + 1 })}
                style={{ width: 40, height: 52, border: 'none', borderLeft: `1px solid ${P.borderLight}`,
                  background: 'transparent', fontSize: 18, cursor: 'pointer', color: P.inkMid }}>+</button>
            </div>
          );
        })}

        <Divider />
        <div>
          <label style={{ color: P.inkMid, fontSize: 12, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', display: 'block', marginBottom: 7 }}>Anything else?</label>
          <textarea value={d.notes} onChange={e => set('notes', e.target.value)}
            placeholder="Life events, stress, unexpected changes…"
            style={{ width: '100%', padding: '10px 14px', borderRadius: 2, border: `1px solid ${P.border}`,
              background: P.surface, color: P.ink, fontSize: 14, fontFamily: 'DM Sans',
              resize: 'none', height: 80, outline: 'none' }} />
        </div>
      </div>
    ),

    summary: ins.crisis ? (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <p style={{ color: P.ink, fontSize: 16, lineHeight: 1.65, margin: '0 0 8px' }}>It looks like you might be going through something really hard right now.</p>
        <a href="tel:988" style={{ display: 'block', padding: '14px 20px',
          background: P.ink, color: '#FFF', textDecoration: 'none', fontWeight: 600, fontSize: 15, textAlign: 'center' }}>
          Call 988 — Suicide & Crisis Lifeline
        </a>
        <a href="sms:741741&body=HOME" style={{ display: 'block', padding: '14px 20px',
          background: P.surface, border: `1px solid ${P.border}`, color: P.ink, textDecoration: 'none', fontWeight: 600, fontSize: 15, textAlign: 'center' }}>
          Text HOME to 741741
        </a>
        <button onClick={back} style={{ padding: '12px 20px', border: `1px solid ${P.border}`,
          background: P.surface, color: P.inkMid, fontSize: 14, cursor: 'pointer', fontFamily: 'DM Sans' }}>
          I'm safe right now
        </button>
      </div>
    ) : (
      <div>
        {Array.isArray(ins) && ins.length > 0 && (
          <div style={{ marginBottom: 28 }}>
            <p style={{ color: P.inkFaint, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.07em', margin: '0 0 12px' }}>Insights</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {ins.slice(0, 5).map((insight, i) => {
                const ilbl = { 1: 'Observation', 2: 'Pattern', 3: 'Reflection', 4: 'Provider Alert' };
                return (
                  <div key={i} style={{ padding: '13px 15px', background: P.accentLight, border: `1px solid ${P.border}` }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
                      <span style={{ color: P.ink, fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em' }}>{ilbl[insight.l]} · {insight.cat}</span>
                      <span style={{ color: P.inkFaint, fontSize: 10 }}>{insight.conf}%</span>
                    </div>
                    <p style={{ color: P.inkMid, fontSize: 13, margin: 0, lineHeight: 1.65 }}>{insight.text}</p>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {aiInsight && (
          <div style={{ marginBottom: 16, padding: '13px 15px', background: P.accentLight, border: `1px solid ${P.border}` }}>
            <p style={{ color: P.inkFaint, fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', margin: '0 0 5px' }}>AI Observation</p>
            <p style={{ color: P.inkMid, fontSize: 13, margin: 0, lineHeight: 1.65 }}>{aiInsight}</p>
          </div>
        )}
        {saveErr && <p style={{ color: P.ink, fontSize: 13, marginBottom: 10, border: `1px solid ${P.border}`, padding: '8px 12px' }}>{saveErr}</p>}
        {saved && (
          <div style={{ padding: '10px 14px', background: P.accentLight, border: `1px solid ${P.border}`, marginBottom: 12 }}>
            <p style={{ color: P.ink, fontSize: 13, margin: 0 }}>✓ Check-in saved — your trends and summary have been updated</p>
          </div>
        )}

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <button onClick={() => { setCheckinType(null); setStepIdx(0); setSaved(false); setSaveErr(''); setAiInsight(''); }}
            style={{ padding: '13px 18px', border: `1px solid ${P.border}`,
              background: P.surface, color: P.inkMid, fontSize: 13, cursor: 'pointer', fontFamily: 'DM Sans' }}>
            New Check-In
          </button>
          <button onClick={handleSave} disabled={saving || saved}
            style={{ padding: '13px 18px', border: `1px solid ${P.border}`, cursor: 'pointer',
              background: saved ? P.inkMid : P.ink, color: '#fff', fontSize: 13, fontWeight: 600, fontFamily: 'DM Sans',
              opacity: saving ? 0.65 : 1 }}>
            {saving ? 'Saving…' : saved ? '✓ Saved' : 'Save to Profile'}
          </button>
        </div>
        <a href="/" style={{ display: 'block', textAlign: 'center', marginTop: 14, color: P.inkFaint, fontSize: 12, textDecoration: 'none' }}>← Back to dashboard</a>
      </div>
    ),
  };

  // ── Type selection screen ───────────────────────────────────────────
  if (!checkinType) {
    return (
      <div style={{ height: 'calc(100vh - 52px)', background: P.bg, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', fontFamily: 'DM Sans', padding: '40px 48px' }}>
        <h1 style={{ fontFamily: 'DM Serif Display', fontWeight: 400, fontSize: 32, color: P.ink, margin: '0 0 8px', letterSpacing: '-0.02em' }}>Daily Check-In</h1>
        <p style={{ color: P.inkFaint, fontSize: 14, margin: '0 0 36px' }}>Select the type of check-in for today</p>
        <div style={{ display: 'flex', width: '100%', maxWidth: 960, border: `1px solid ${P.border}` }}>
          {CHECKIN_TYPES.map((t, i) => {
            const done = completedToday.includes(t.id);
            const doneBg = '#f0faf4';
            return (
              <button key={t.id} onClick={() => setCheckinType(t.id)}
                style={{ flex: 1, padding: '28px 24px', background: done ? doneBg : P.surface,
                  border: 'none', borderRight: i < 3 ? `1px solid ${P.border}` : 'none',
                  cursor: 'pointer', textAlign: 'left', fontFamily: 'DM Sans',
                  transition: 'background 0.12s', position: 'relative' }}
                onMouseEnter={e => e.currentTarget.style.background = done ? '#e2f5ea' : P.accentLight}
                onMouseLeave={e => e.currentTarget.style.background = done ? doneBg : P.surface}>
                {done && (
                  <div style={{ position: 'absolute', top: 14, right: 16,
                    width: 36, height: 36, borderRadius: '50%',
                    background: '#22c55e', display: 'flex', alignItems: 'center', justifyContent: 'center',
                    boxShadow: '0 2px 8px rgba(34,197,94,0.35)' }}>
                    <span style={{ color: '#fff', fontSize: 20, fontWeight: 700, lineHeight: 1 }}>✓</span>
                  </div>
                )}
                <div style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em',
                  color: done ? '#16a34a' : P.inkFaint, marginBottom: 10 }}>
                  {done ? 'Completed today' : t.tag}
                </div>
                <div style={{ fontSize: 16, fontWeight: 600, color: P.ink, marginBottom: 6 }}>{t.label}</div>
                <div style={{ fontSize: 12, color: P.inkMid, lineHeight: 1.55 }}>{t.desc}</div>
              </button>
            );
          })}
        </div>
      </div>
    );
  }

  // ── Progress indicator ──────────────────────────────────────────────
  const progressSteps = FLOW.slice(1);

  return (
    <div style={{ height: 'calc(100vh - 52px)', background: P.bg, display: 'flex', flexDirection: 'column', fontFamily: 'DM Sans' }}>

      {/* Step progress bar + caffeine running total */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0 28px', borderBottom: `1px solid ${P.borderLight}`, background: P.surface, height: 40 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {progressSteps.map((sid, i) => {
            const realIdx = i + 1;
            const active  = stepIdx === realIdx;
            const done    = stepIdx > realIdx;
            return (
              <div key={sid} style={{
                width: active ? 24 : 7, height: 7, borderRadius: 2,
                transition: 'all 0.3s ease',
                background: done ? P.ink : active ? P.ink : P.borderLight,
                opacity: done ? 0.4 : 1,
              }} />
            );
          })}
          <span style={{ color: P.inkFaint, fontSize: 11, marginLeft: 8 }}>
            {CHECKIN_TYPES.find(t => t.id === checkinType)?.label} Check-In
            {stepIdx > 0 && stepIdx < FLOW.length - 1 ? ` · ${stepIdx} of ${FLOW.length - 2}` : ''}
          </span>
        </div>
        {/* Caffeine running total — always visible */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 12px',
          border: `1px solid ${sc.caffeineMg > 400 ? P.border : P.borderLight}`,
          background: sc.caffeineMg > 400 ? P.accentLight : 'transparent' }}>
          <span style={{ fontSize: 11, color: P.inkFaint, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Caffeine</span>
          <span style={{ fontSize: 13, fontWeight: 700, color: P.ink }}>{sc.caffeineMg}mg</span>
          {d.caffeine.coffee > 0 && <span style={{ fontSize: 10, color: P.inkFaint }}>☕ {d.caffeine.coffee}</span>}
          {d.caffeine.tea > 0    && <span style={{ fontSize: 10, color: P.inkFaint }}>🍵 {d.caffeine.tea}</span>}
          {d.caffeine.soda > 0   && <span style={{ fontSize: 10, color: P.inkFaint }}>🥤 {d.caffeine.soda}</span>}
          {d.caffeine.energy > 0 && <span style={{ fontSize: 10, color: P.inkFaint }}>⚡ {d.caffeine.energy}</span>}
        </div>
      </div>

      {/* Split body */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>

        {/* Left — context panel */}
        <div style={{ width: '38%', minWidth: 280, padding: '48px 44px',
          background: P.surface, borderRight: `1px solid ${P.border}`,
          display: 'flex', flexDirection: 'column', justifyContent: 'center', overflow: 'hidden' }}>
          {leftContent[stepId] || leftContent.intro}
        </div>

        {/* Right — input panel */}
        <div style={{ flex: 1, padding: '48px 48px', overflowY: 'auto',
          display: 'flex', flexDirection: 'column' }}>
          <div style={{ maxWidth: 480 }}>
            {rightContent[stepId] || rightContent.intro}

            {stepId !== 'intro' && stepId !== 'summary' && (
              <div style={{ display: 'flex', gap: 10, marginTop: 32, paddingTop: 24, borderTop: `1px solid ${P.borderLight}` }}>
                {stepIdx > 1 && (
                  <button onClick={back}
                    style={{ padding: '13px 20px', border: `1px solid ${P.border}`,
                      background: P.surface, color: P.inkMid, fontSize: 14, cursor: 'pointer', fontFamily: 'DM Sans' }}>
                    ← Back
                  </button>
                )}
                <button onClick={next}
                  style={{ flex: 1, padding: '13px 20px', border: `2px solid ${P.border}`,
                    background: P.ink, color: '#fff', fontSize: 14, fontWeight: 600,
                    fontFamily: 'DM Sans', cursor: 'pointer' }}>
                  Continue →
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Footer */}
      <div style={{ padding: '8px 36px', borderTop: `1px solid ${P.borderLight}`, background: P.surface }}>
        <p style={{ color: P.inkFaint, fontSize: 11, margin: 0, textAlign: 'center' }}>
          HIPAA-compliant · The system learns from your patterns, never diagnoses
        </p>
      </div>
    </div>
  );
}
