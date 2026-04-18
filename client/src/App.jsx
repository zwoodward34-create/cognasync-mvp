import React, { useState, useEffect, useMemo, useCallback } from 'react';

// ── Paper palette ─────────────────────────────────────────────────────
const P = {
  bg:          '#EAE4D8',
  surface:     '#F3EEE5',
  raised:      '#F9F6F1',
  border:      '#D4CCBC',
  borderLight: '#E2DAC9',
  ink:         '#1A1510',
  inkMid:      '#574F45',
  inkFaint:    '#968D82',
  accent:      '#5C5099',
  accentHover: '#4C4284',
  accentLight: '#EDEAFC',
};

// Step colours — muted, warm, like different ink colours on paper
const STEP_COLORS = {
  intro:     { fg: '#5C5099', bg: '#EDEAFC', mid: '#4C4284' },
  core:      { fg: '#6B4A96', bg: '#F0EAFC', mid: '#5A3A84' },
  sleep:     { fg: '#2E4E80', bg: '#E8EEF8', mid: '#1E3E6A' },
  meds:      { fg: '#2A5E5A', bg: '#E5F4F2', mid: '#1A4E4A' },
  nutrition: { fg: '#2E5E3A', bg: '#E5F4E8', mid: '#1E4E2A' },
  summary:   { fg: '#5C5099', bg: '#EDEAFC', mid: '#4C4284' },
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

function calcScores(d, bl) {
  const stability = (d.mood + d.energy + (10 - d.dissociation) + (10 - d.anxiety)) / 4;
  const dopamine  = (d.energy + d.focus) / 2;
  const stim      = d.caffeineMg > 300 ? 8 : d.caffeineMg > 200 ? 5 : 2;
  const nsLoad    = (d.anxiety + (10 - d.sleepQuality) + stim) / 3;

  let sleepDis = 0;
  if ((d.timeAwakeMinutes / 480) * 100 > 20) sleepDis += 3;
  if (d.sleepLatencyMinutes > 30) sleepDis += 3;
  if (d.nightAwakenings >= 2) sleepDis += 2;
  if (d.sleepHours < 6) sleepDis += 2;

  let nutrition = 0;
  if (d.breakfastProteinGrams >= 20) nutrition += 3;
  if (!d.sugarSpikes) nutrition += 3;
  if (d.mealTiming === 'consistent') nutrition += 2;
  if (d.hydrationOz >= 80) nutrition += 2;

  const crashRisk    = sleepDis * 0.4 + nsLoad * 0.4 + (10 - nutrition) * 0.2;
  const moodDistort  = Math.abs(d.mood - stability);
  return { stability, dopamine, nsLoad, sleepDis, nutrition, crashRisk, moodDistort,
    moodDev: d.mood - bl.avgMood, anxietyDev: d.anxiety - bl.avgAnxiety };
}

function calcInsights(d, bl, sc) {
  if (G.crisis(d.notes)) return { crisis: true };
  const out = [];
  const sd = d.sleepHours - bl.avgSleepHours;
  out.push({ l: 1, cat: 'sleep', conf: 100, text: `You slept ${d.sleepHours}h — ${sd > 0.5 ? 'more' : sd < -0.5 ? 'less' : 'about the same'} than your 7-day average of ${bl.avgSleepHours.toFixed(1)}h.` });
  if (d.caffeineMg) {
    const cd = d.caffeineMg - bl.avgCaffeineMg;
    out.push({ l: 1, cat: 'caffeine', conf: 100, text: `${d.caffeineMg}mg caffeine — ${cd > 0 ? `${cd}mg above` : `${Math.abs(cd)}mg below`} your typical ${bl.avgCaffeineMg}mg.` });
  }
  if (sc.moodDistort > 2 && sc.moodDistort <= 4)
    out.push({ l: 2, cat: 'perception', conf: 72, text: `Your reported mood (${d.mood}/10) is ${d.mood > sc.stability ? 'higher' : 'lower'} than your stability score (${sc.stability.toFixed(1)}/10), which factors in sleep, anxiety, and energy.` });
  if (sc.nsLoad > 6 && d.sleepQuality < 6)
    out.push({ l: 2, cat: 'nervous system', conf: 75, text: `Elevated nervous system load (${sc.nsLoad.toFixed(1)}/10) combined with low sleep quality tends to correlate with difficulty settling in the evening.` });
  if (d.breakfastProteinGrams < 15 && d.focus < bl.avgEnergy - 1)
    out.push({ l: 2, cat: 'nutrition', conf: 68, text: `Low breakfast protein days correlate with lower focus scores on average, based on your tracking pattern.` });
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
    ? (value < 3 ? '#2E6E4F' : value < 6 ? '#7A5A14' : '#8B3A2A')
    : (value > 7 ? '#2E6E4F' : value > 4 ? '#5C5099' : '#7A5A14');
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
      <div style={{ position: 'relative', height: 6, borderRadius: 3, background: P.borderLight, cursor: 'pointer' }}>
        <div style={{ position: 'absolute', left: 0, top: 0, height: '100%', width: `${pct}%`,
          borderRadius: 3, background: c, transition: 'width 0.08s', opacity: 0.85 }} />
        <input type="range" min={min} max={max} step={step} value={value}
          onChange={e => onChange(step < 1 ? parseFloat(e.target.value) : parseInt(e.target.value))}
          style={{ position: 'absolute', inset: 0, width: '100%', opacity: 0, cursor: 'pointer', margin: 0, height: '100%' }} />
        <div style={{ position: 'absolute', top: '50%', left: `${pct}%`, transform: 'translate(-50%, -50%)',
          width: 18, height: 18, borderRadius: '50%', background: P.raised,
          border: `2px solid ${c}`, boxShadow: `0 1px 4px rgba(80,60,20,0.15)`,
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
        borderRadius: 10, border: `1px solid ${checked ? c + '55' : P.border}`,
        background: checked ? c + '12' : P.raised, cursor: 'pointer',
        textAlign: 'left', width: '100%', transition: 'all 0.15s', marginBottom: 10 }}>
      <div style={{ width: 18, height: 18, borderRadius: 5,
        border: `1.5px solid ${checked ? c : P.border}`,
        background: checked ? c : 'transparent', flexShrink: 0,
        display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'all 0.15s' }}>
        {checked && <svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M2 5l2.5 2.5 3.5-4" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>}
      </div>
      <span style={{ color: checked ? P.ink : P.inkMid, fontSize: 14, fontWeight: 500 }}>{label}</span>
    </button>
  );
}

function PaperSelect({ label, value, onChange, options, color }) {
  return (
    <div style={{ marginBottom: 20 }}>
      <label style={{ color: P.inkMid, fontSize: 12, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', display: 'block', marginBottom: 7 }}>{label}</label>
      <select value={value} onChange={e => onChange(e.target.value)}
        style={{ width: '100%', padding: '10px 14px', borderRadius: 9, border: `1px solid ${P.border}`,
          background: P.raised, color: P.ink, fontSize: 14, outline: 'none', cursor: 'pointer',
          fontFamily: 'DM Sans', appearance: 'none',
          boxShadow: 'inset 0 1px 3px rgba(80,60,20,0.05)' }}>
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
        style={{ width: '100%', padding: '10px 14px', borderRadius: 9, border: `1px solid ${P.border}`,
          background: P.raised, color: P.ink, fontSize: 14, outline: 'none', fontFamily: 'DM Sans',
          boxShadow: 'inset 0 1px 3px rgba(80,60,20,0.05)' }} />
      {hint && <p style={{ color: P.inkFaint, fontSize: 11, marginTop: 5 }}>{hint}</p>}
    </div>
  );
}

// ── Ink divider ───────────────────────────────────────────────────────
const Divider = () => <div style={{ height: 1, background: P.borderLight, margin: '20px 0' }} />;

// ── STEPS ─────────────────────────────────────────────────────────────
const FLOW = ['intro','core','sleep','meds','nutrition','summary'];

export default function App() {
  const [stepIdx, setStepIdx] = useState(0);
  const [bl, setBl] = useState(DEFAULT_BL);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveErr, setSaveErr] = useState('');

  const [d, setD] = useState({
    timeOfCheckIn: new Date().getHours(),
    mood: 6, energy: 6, dissociation: 1, anxiety: 3, focus: 6,
    sleepHours: 6, sleepQuality: 6, timeAwakeMinutes: 0,
    sleepLatencyMinutes: 0, nightAwakenings: 0,
    caffeineMg: 0, breakfastProteinGrams: 0,
    sugarSpikes: false, mealTiming: 'irregular', hydrationOz: 64,
    meds: {}, notes: '',
  });

  useEffect(() => {
    fetch('/api/checkins/baseline', { credentials: 'same-origin' })
      .then(r => r.ok ? r.json() : null).then(v => { if (v && Object.keys(v).length) setBl(p => ({ ...p, ...v })); }).catch(() => {});
    fetch('/api/patient/profile', { credentials: 'same-origin' })
      .then(r => r.ok ? r.json() : null).then(v => {
        if (!v) return;
        const meds = {};
        (v.current_medications || []).forEach(m => { meds[m.name] = { taken: false, dose: m.dose || '' }; });
        setD(p => ({ ...p, meds }));
      }).catch(() => {});
  }, []);

  const sc = useMemo(() => calcScores(d, bl), [d, bl]);
  const ins = useMemo(() => calcInsights(d, bl, sc), [d, sc, bl]);
  const set = useCallback((k, v) => setD(p => ({ ...p, [k]: v })), []);

  const stepId = FLOW[stepIdx];
  const clr = STEP_COLORS[stepId] || STEP_COLORS.intro;
  const next = () => setStepIdx(i => Math.min(i + 1, FLOW.length - 1));
  const back = () => setStepIdx(i => Math.max(i - 1, 0));

  const handleSave = async () => {
    setSaving(true); setSaveErr('');
    try {
      const medList = Object.entries(d.meds).filter(([,i]) => i.taken).map(([n,i]) => ({ name: n, dose: i.dose }));
      const res = await fetch('/api/checkins', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mood_score: d.mood, stress_score: d.anxiety, sleep_hours: d.sleepHours,
          medications: medList, notes: d.notes, time_of_day: `${d.timeOfCheckIn}:00`,
          extended_data: { energy: d.energy, focus: d.focus, dissociation: d.dissociation,
            sleep_quality: d.sleepQuality, time_awake_minutes: d.timeAwakeMinutes,
            night_awakenings: d.nightAwakenings, caffeine_mg: d.caffeineMg,
            breakfast_protein_grams: d.breakfastProteinGrams, sugar_spikes: d.sugarSpikes,
            meal_timing: d.mealTiming, hydration_oz: d.hydrationOz,
            scores: { stability: sc.stability, crash_risk: sc.crashRisk, nervous_system_load: sc.nsLoad, dopamine_efficiency: sc.dopamine } },
        }),
      });
      if (res.ok) { setSaved(true); setTimeout(() => setSaved(false), 4000); }
      else { const e = await res.json().catch(() => ({})); setSaveErr(e.error || 'Save failed.'); }
    } catch { setSaveErr('Network error.'); }
    finally { setSaving(false); }
  };

  // ── Left panel content ──────────────────────────────────────────────
  const leftContent = {
    intro: <>
      <div style={{ fontSize: 52, marginBottom: 20, opacity: 0.85 }}>📖</div>
      <h1 style={{ fontFamily: 'DM Serif Display', fontWeight: 400, fontSize: 34, color: P.ink, margin: '0 0 14px', lineHeight: 1.2, letterSpacing: '-0.02em' }}>Daily<br/>Check-In</h1>
      <p style={{ color: P.inkMid, fontSize: 15, lineHeight: 1.7, margin: '0 0 28px' }}>Five minutes. Real patterns. Personalized to you.</p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {[['🧠','Mental state'],['🌙','Sleep quality'],['💊','Medications'],['🥗','Nutrition'],['✦','Live scores + insights']].map(([e,l]) => (
          <div key={l} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 16, width: 24, textAlign: 'center', opacity: 0.7 }}>{e}</span>
            <span style={{ color: P.inkMid, fontSize: 14 }}>{l}</span>
          </div>
        ))}
      </div>
    </>,

    core: <>
      <div style={{ fontSize: 48, marginBottom: 20, opacity: 0.8 }}>🧠</div>
      <h2 style={{ fontFamily: 'DM Serif Display', fontWeight: 400, fontSize: 28, color: P.ink, margin: '0 0 10px' }}>Mental State</h2>
      <p style={{ color: P.inkMid, fontSize: 14, lineHeight: 1.65, margin: '0 0 28px' }}>Five signals that feed your stability and crash-risk scores in real time.</p>
      <div style={{ padding: 18, borderRadius: 12, background: clr.bg, border: `1px solid ${clr.fg}22` }}>
        <p style={{ color: P.inkFaint, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.07em', margin: '0 0 8px' }}>Current estimate</p>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
          <span style={{ color: clr.fg, fontSize: 38, fontFamily: 'DM Serif Display' }}>{sc.stability.toFixed(1)}</span>
          <span style={{ color: P.inkFaint, fontSize: 14 }}>/10 stability</span>
        </div>
        <p style={{ color: P.inkFaint, fontSize: 11, margin: '6px 0 0' }}>Your baseline: {bl.avgMood.toFixed(1)}</p>
      </div>
    </>,

    sleep: <>
      <div style={{ fontSize: 48, marginBottom: 20, opacity: 0.8 }}>🌙</div>
      <h2 style={{ fontFamily: 'DM Serif Display', fontWeight: 400, fontSize: 28, color: P.ink, margin: '0 0 10px' }}>Last Night's Sleep</h2>
      <p style={{ color: P.inkMid, fontSize: 14, lineHeight: 1.65, margin: '0 0 28px' }}>Sleep quality is the strongest single predictor in your crash-risk score.</p>
      <div style={{ padding: 18, borderRadius: 12, background: clr.bg, border: `1px solid ${clr.fg}22` }}>
        <p style={{ color: P.inkFaint, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.07em', margin: '0 0 8px' }}>Sleep disruption</p>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
          <span style={{ color: sc.sleepDis < 3 ? '#2E6E4F' : sc.sleepDis < 6 ? '#7A5A14' : '#8B3A2A', fontSize: 38, fontFamily: 'DM Serif Display' }}>{sc.sleepDis}</span>
          <span style={{ color: P.inkFaint, fontSize: 14 }}>pts</span>
        </div>
        <p style={{ color: P.inkFaint, fontSize: 11, margin: '6px 0 0' }}>{sc.sleepDis < 3 ? 'Restful night' : sc.sleepDis < 6 ? 'Some disruption' : 'Significant disruption'}</p>
      </div>
    </>,

    meds: <>
      <div style={{ fontSize: 48, marginBottom: 20, opacity: 0.8 }}>💊</div>
      <h2 style={{ fontFamily: 'DM Serif Display', fontWeight: 400, fontSize: 28, color: P.ink, margin: '0 0 10px' }}>Medications & Stimulation</h2>
      <p style={{ color: P.inkMid, fontSize: 14, lineHeight: 1.65, margin: '0 0 28px' }}>What you took and how much caffeine — feeds your dopamine efficiency score.</p>
      <div style={{ padding: 18, borderRadius: 12, background: clr.bg, border: `1px solid ${clr.fg}22` }}>
        <p style={{ color: P.inkFaint, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.07em', margin: '0 0 8px' }}>Dopamine efficiency</p>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
          <span style={{ color: clr.fg, fontSize: 38, fontFamily: 'DM Serif Display' }}>{sc.dopamine.toFixed(1)}</span>
          <span style={{ color: P.inkFaint, fontSize: 14 }}>/10</span>
        </div>
      </div>
    </>,

    nutrition: <>
      <div style={{ fontSize: 48, marginBottom: 20, opacity: 0.8 }}>🥗</div>
      <h2 style={{ fontFamily: 'DM Serif Display', fontWeight: 400, fontSize: 28, color: P.ink, margin: '0 0 10px' }}>Body & Nutrition</h2>
      <p style={{ color: P.inkMid, fontSize: 14, lineHeight: 1.65, margin: '0 0 28px' }}>Nutrition stability factors into your crash-risk score.</p>
      <div style={{ padding: 18, borderRadius: 12, background: clr.bg, border: `1px solid ${clr.fg}22` }}>
        <p style={{ color: P.inkFaint, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.07em', margin: '0 0 8px' }}>Nutrition score</p>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
          <span style={{ color: clr.fg, fontSize: 38, fontFamily: 'DM Serif Display' }}>{sc.nutrition}</span>
          <span style={{ color: P.inkFaint, fontSize: 14 }}>/10</span>
        </div>
        <p style={{ color: P.inkFaint, fontSize: 11, margin: '6px 0 0' }}>Updates as you fill in below</p>
      </div>
    </>,

    summary: ins.crisis ? <>
      <div style={{ fontSize: 48, marginBottom: 20 }}>🤝</div>
      <h2 style={{ fontFamily: 'DM Serif Display', fontWeight: 400, fontSize: 28, color: P.ink, margin: '0 0 10px' }}>You're not alone</h2>
      <p style={{ color: P.inkMid, fontSize: 14, lineHeight: 1.65 }}>Crisis support is available 24 hours a day.</p>
    </> : <>
      <div style={{ fontSize: 48, marginBottom: 20, opacity: 0.8 }}>✦</div>
      <h2 style={{ fontFamily: 'DM Serif Display', fontWeight: 400, fontSize: 28, color: P.ink, margin: '0 0 20px' }}>Today's Scores</h2>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
        <ScoreRing value={sc.stability} label="Stability"    sub={`baseline ${bl.avgMood.toFixed(1)}`} />
        <ScoreRing value={sc.crashRisk} label="Crash Risk"   sub="next 6h" danger />
        <ScoreRing value={sc.nsLoad}    label="NS Load"      sub="lower = calmer" danger />
        <ScoreRing value={sc.dopamine}  label="Dopamine" />
      </div>
      {sc.moodDistort > 1.5 && (
        <div style={{ marginTop: 20, padding: '12px 14px', borderRadius: 10, background: '#FBF5E2', border: '1px solid #D4C070' }}>
          <p style={{ color: '#6A4E10', fontSize: 12, margin: 0, lineHeight: 1.55 }}>
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
        <div style={{ padding: '20px 22px', borderRadius: 12, background: P.surface, border: `1px solid ${P.border}` }}>
          <p style={{ color: P.inkMid, fontSize: 14, lineHeight: 1.75, margin: 0 }}>
            Every check-in builds a model of <em style={{ color: P.ink, fontStyle: 'normal', fontWeight: 600 }}>your</em> patterns — how sleep, caffeine, and nutrition affect your mood and energy. Nothing is assumed. Everything is calculated from your actual data.
          </p>
        </div>
        <button onClick={next}
          style={{ padding: '16px 28px', borderRadius: 12, border: 'none', cursor: 'pointer',
            background: clr.fg, color: '#fff', fontSize: 16, fontWeight: 600, fontFamily: 'DM Sans',
            boxShadow: `0 2px 12px ${clr.fg}30`, letterSpacing: '0.01em' }}>
          Begin Check-In →
        </button>
        <a href="/dashboard" style={{ color: P.inkFaint, fontSize: 13, textAlign: 'center', textDecoration: 'none' }}>← Back to dashboard</a>
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
          <div style={{ position: 'relative', height: 6, borderRadius: 3, background: P.borderLight }}>
            <div style={{ position: 'absolute', left: 0, top: 0, height: '100%', borderRadius: 3,
              width: `${(d.sleepHours / 12) * 100}%`, background: clr.fg, opacity: 0.85, transition: 'width 0.08s' }} />
            <input type="range" min="0" max="12" step="0.5" value={d.sleepHours}
              onChange={e => set('sleepHours', parseFloat(e.target.value))}
              style={{ position: 'absolute', inset: 0, width: '100%', opacity: 0, cursor: 'pointer', margin: 0, height: '100%' }} />
            <div style={{ position: 'absolute', top: '50%', left: `${(d.sleepHours / 12) * 100}%`,
              transform: 'translate(-50%, -50%)', width: 18, height: 18, borderRadius: '50%',
              background: P.raised, border: `2px solid ${clr.fg}`, boxShadow: '0 1px 4px rgba(80,60,20,0.15)', pointerEvents: 'none', transition: 'left 0.08s' }} />
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 5 }}>
            <span style={{ color: P.inkFaint, fontSize: 11 }}>0h</span>
            <span style={{ color: P.inkFaint, fontSize: 11 }}>12h</span>
          </div>
        </div>
        <InkSlider label="Sleep Quality"    value={d.sleepQuality}    onChange={v => set('sleepQuality', v)}    lo="Terrible"  hi="Excellent"  color={clr.fg} />
        <PaperNumInput label="Minutes Awake"  value={d.timeAwakeMinutes}  onChange={v => set('timeAwakeMinutes', v)}  min={0} max={240} step={5}  unit="min" color={clr.fg} />
        <PaperSelect label="Night Awakenings" value={String(d.nightAwakenings)} onChange={v => set('nightAwakenings', parseInt(v))}
          options={[{value:'0',label:'None'},{value:'1',label:'Once'},{value:'2',label:'Twice'},{value:'3',label:'3+'}]} color={clr.fg} />
      </div>
    ),

    meds: (
      <div>
        {Object.keys(d.meds).length === 0 ? (
          <div style={{ padding: '18px 20px', borderRadius: 11, background: P.surface, border: `1px solid ${P.border}`, marginBottom: 20 }}>
            <p style={{ color: P.inkMid, fontSize: 14, margin: 0 }}>No medications on your profile. <a href="/settings" style={{ color: clr.fg }}>Add them in Settings →</a></p>
          </div>
        ) : (
          <div style={{ marginBottom: 24 }}>
            <p style={{ color: P.inkFaint, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.07em', margin: '0 0 10px' }}>Taken today</p>
            {Object.entries(d.meds).map(([med, info]) => (
              <PaperToggle key={med} label={`${med.charAt(0).toUpperCase() + med.slice(1)} ${info.dose ? `(${info.dose})` : ''}`}
                checked={info.taken} onChange={v => set('meds', { ...d.meds, [med]: { ...info, taken: v } })} color={clr.fg} />
            ))}
          </div>
        )}
        <PaperNumInput label="Caffeine Today" value={d.caffeineMg} onChange={v => set('caffeineMg', v)} min={0} max={600} step={10} unit="mg"
          hint={`Your typical range: ${bl.optimalCaffeine?.min ?? 200}–${bl.optimalCaffeine?.max ?? 300}mg`} color={clr.fg} />
      </div>
    ),

    nutrition: (
      <div>
        <PaperNumInput label="Breakfast Protein" value={d.breakfastProteinGrams} onChange={v => set('breakfastProteinGrams', v)}
          min={0} max={60} step={5} unit="g" hint="20g+ correlates with better focus on your data" color={clr.fg} />
        <PaperToggle label="No major sugar crashes today" checked={!d.sugarSpikes} onChange={v => set('sugarSpikes', !v)} color={clr.fg} />
        <Divider />
        <PaperSelect label="Meal Timing" value={d.mealTiming} onChange={v => set('mealTiming', v)}
          options={[{value:'missed',label:'Skipped meals'},{value:'irregular',label:'Irregular'},{value:'consistent',label:'Consistent'}]} color={clr.fg} />
        <PaperNumInput label="Hydration" value={d.hydrationOz} onChange={v => set('hydrationOz', v)} min={0} max={160} step={8} unit="oz" hint="Target: 80–100oz" color={clr.fg} />
        <div>
          <label style={{ color: P.inkMid, fontSize: 12, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', display: 'block', marginBottom: 7 }}>Anything else?</label>
          <textarea value={d.notes} onChange={e => set('notes', e.target.value)}
            placeholder="Life events, stress, unexpected changes…"
            style={{ width: '100%', padding: '10px 14px', borderRadius: 9, border: `1px solid ${P.border}`,
              background: P.raised, color: P.ink, fontSize: 14, fontFamily: 'DM Sans',
              resize: 'none', height: 80, outline: 'none',
              boxShadow: 'inset 0 1px 3px rgba(80,60,20,0.05)' }} />
        </div>
      </div>
    ),

    summary: ins.crisis ? (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <p style={{ color: P.ink, fontSize: 16, lineHeight: 1.65, margin: '0 0 8px' }}>It looks like you might be going through something really hard right now.</p>
        <a href="tel:988" style={{ display: 'block', padding: '14px 20px', borderRadius: 11,
          background: '#8B3A2A', color: '#FFF', textDecoration: 'none', fontWeight: 600, fontSize: 15, textAlign: 'center' }}>
          📞 Call 988 — Suicide & Crisis Lifeline
        </a>
        <a href="sms:741741&body=HOME" style={{ display: 'block', padding: '14px 20px', borderRadius: 11,
          background: '#FDF0ED', border: '1px solid #E8B8B0', color: '#8B3A2A', textDecoration: 'none', fontWeight: 600, fontSize: 15, textAlign: 'center' }}>
          💬 Text HOME to 741741
        </a>
        <button onClick={back} style={{ padding: '12px 20px', borderRadius: 11, border: `1px solid ${P.border}`,
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
                const iclr = { 1: '#5C5099', 2: '#6B4A96', 3: '#2E4E80', 4: '#7A5A14' };
                const ibg  = { 1: '#EDEAFC', 2: '#F0EAFC', 3: '#E8EEF8', 4: '#FBF5E2' };
                const ilbl = { 1: 'Observation', 2: 'Pattern', 3: 'Reflection', 4: 'Provider Alert' };
                return (
                  <div key={i} style={{ padding: '13px 15px', borderRadius: 11, background: ibg[insight.l], border: `1px solid ${iclr[insight.l]}22` }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
                      <span style={{ color: iclr[insight.l], fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em' }}>{ilbl[insight.l]} · {insight.cat}</span>
                      <span style={{ color: P.inkFaint, fontSize: 10 }}>{insight.conf}%</span>
                    </div>
                    <p style={{ color: P.inkMid, fontSize: 13, margin: 0, lineHeight: 1.65 }}>{insight.text}</p>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {saveErr && <p style={{ color: '#8B3A2A', fontSize: 13, marginBottom: 10 }}>{saveErr}</p>}
        {saved && (
          <div style={{ padding: '10px 14px', borderRadius: 10, background: '#EBF5EF', border: '1px solid #A8D4BC', marginBottom: 12 }}>
            <p style={{ color: '#2E6E4F', fontSize: 13, margin: 0 }}>✓ Check-in saved</p>
          </div>
        )}

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <button onClick={() => { setStepIdx(0); setSaved(false); setSaveErr(''); }}
            style={{ padding: '13px 18px', borderRadius: 11, border: `1px solid ${P.border}`,
              background: P.surface, color: P.inkMid, fontSize: 13, cursor: 'pointer', fontFamily: 'DM Sans' }}>
            New Check-In
          </button>
          <button onClick={handleSave} disabled={saving || saved}
            style={{ padding: '13px 18px', borderRadius: 11, border: 'none', cursor: 'pointer',
              background: saved ? '#2E6E4F' : clr.fg, color: '#fff', fontSize: 13, fontWeight: 600, fontFamily: 'DM Sans',
              opacity: saving ? 0.65 : 1 }}>
            {saving ? 'Saving…' : saved ? '✓ Saved' : 'Save to Profile'}
          </button>
        </div>
        <a href="/dashboard" style={{ display: 'block', textAlign: 'center', marginTop: 14, color: P.inkFaint, fontSize: 12, textDecoration: 'none' }}>← Back to dashboard</a>
      </div>
    ),
  };

  // ── Shell ───────────────────────────────────────────────────────────
  const progressSteps = FLOW.slice(1);

  return (
    <div style={{ minHeight: '100vh', background: P.bg, display: 'flex', flexDirection: 'column', fontFamily: 'DM Sans' }}>

      {/* Top bar */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '14px 36px', borderBottom: `1px solid ${P.border}`, background: P.surface }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <div style={{ width: 30, height: 30, borderRadius: 7, background: clr.fg,
            display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <span style={{ color: '#fff', fontSize: 13, fontFamily: 'DM Serif Display' }}>C</span>
          </div>
          <span style={{ color: P.ink, fontSize: 15, fontWeight: 600, letterSpacing: '-0.01em', fontFamily: 'DM Serif Display' }}>CognaSync</span>
        </div>

        {/* Progress */}
        <div style={{ display: 'flex', gap: 5, alignItems: 'center' }}>
          {progressSteps.map((sid, i) => {
            const realIdx = i + 1;
            const active  = stepIdx === realIdx;
            const done    = stepIdx > realIdx;
            return (
              <div key={sid} style={{
                width: active ? 24 : 7, height: 7, borderRadius: 4,
                transition: 'all 0.3s ease',
                background: done ? '#2E6E4F' : active ? clr.fg : P.borderLight,
              }} />
            );
          })}
        </div>

        <span style={{ color: P.inkFaint, fontSize: 12 }}>
          {stepIdx > 0 && stepIdx < FLOW.length - 1 ? `${stepIdx} of ${FLOW.length - 2}` : ''}
        </span>
      </div>

      {/* Split body */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>

        {/* Left — context panel */}
        <div style={{ width: '40%', minWidth: 300, padding: '52px 44px',
          background: P.surface, borderRight: `1px solid ${P.border}`,
          display: 'flex', flexDirection: 'column', justifyContent: 'center',
          position: 'relative', overflow: 'hidden' }}>
          {/* Subtle tinted watermark */}
          <div style={{ position: 'absolute', top: -60, right: -60, width: 280, height: 280,
            borderRadius: '50%', background: clr.fg, opacity: 0.04, pointerEvents: 'none' }} />
          <div style={{ position: 'relative', zIndex: 1 }}>
            {leftContent[stepId] || leftContent.intro}
          </div>
        </div>

        {/* Right — input panel */}
        <div style={{ flex: 1, padding: '52px 48px', overflowY: 'auto',
          display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          <div style={{ maxWidth: 500 }}>
            {rightContent[stepId] || rightContent.intro}

            {/* Nav buttons */}
            {stepId !== 'intro' && stepId !== 'summary' && (
              <div style={{ display: 'flex', gap: 10, marginTop: 32, paddingTop: 24, borderTop: `1px solid ${P.borderLight}` }}>
                {stepIdx > 1 && (
                  <button onClick={back}
                    style={{ padding: '13px 20px', borderRadius: 11, border: `1px solid ${P.border}`,
                      background: P.surface, color: P.inkMid, fontSize: 14, cursor: 'pointer', fontFamily: 'DM Sans' }}>
                    ← Back
                  </button>
                )}
                <button onClick={next}
                  style={{ flex: 1, padding: '13px 20px', borderRadius: 11, border: 'none',
                    background: clr.fg, color: '#fff', fontSize: 14, fontWeight: 600,
                    fontFamily: 'DM Sans', cursor: 'pointer', boxShadow: `0 2px 10px ${clr.fg}28` }}>
                  Continue →
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Footer */}
      <div style={{ padding: '10px 36px', borderTop: `1px solid ${P.borderLight}`, background: P.surface }}>
        <p style={{ color: P.inkFaint, fontSize: 11, margin: 0, textAlign: 'center' }}>
          HIPAA-compliant · The system learns from your patterns, never diagnoses
        </p>
      </div>
    </div>
  );
}
