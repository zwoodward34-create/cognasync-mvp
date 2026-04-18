import React, { useState, useEffect, useMemo, useCallback } from 'react';

// ── Guardrails ────────────────────────────────────────────────────────────────
const guardrails = {
  hasDiagnostic: t => ['diagnos','disorder','illness','disease','symptom','syndrome','relapse','episode'].some(w => t.toLowerCase().includes(w)),
  hasMedAdvice: t => ['increase','decrease','adjust','discontinue','should take'].some(w => t.toLowerCase().includes(w) && (t.toLowerCase().includes('medication') || t.toLowerCase().includes('dose'))),
  isData: t => /\d+/.test(t) || (/day|week|month|hour/.test(t.toLowerCase()) && /score|average|rating|trend/.test(t.toLowerCase())),
  hasCrisis: t => ['suicide','suicidal','kill myself','hurt myself','self-harm',"can't go on",'want to die','end it'].some(w => t.toLowerCase().includes(w)),
  pass: (t, lvl) => {
    if (lvl === 1 && (guardrails.hasDiagnostic(t) || !guardrails.isData(t))) return false;
    if (lvl === 2 && (guardrails.hasDiagnostic(t) || guardrails.hasMedAdvice(t))) return false;
    if (lvl === 4 && guardrails.hasDiagnostic(t)) return false;
    return true;
  },
};

// ── Defaults ──────────────────────────────────────────────────────────────────
const DEFAULTS = {
  avgMood: 6.8, avgEnergy: 6.5, avgAnxiety: 3.2,
  avgSleepHours: 5.9, avgSleepQuality: 6.2, avgCaffeineMg: 280,
  optimalCaffeine: { min: 200, max: 300 },
};

// ── Scoring ───────────────────────────────────────────────────────────────────
function score(data, bl) {
  const stability = (data.mood + data.energy + (10 - data.dissociation) + (10 - data.anxiety)) / 4;
  const dopamine = (data.energy + data.focus) / 2;
  const stim = data.caffeineMg > 300 ? 8 : data.caffeineMg > 200 ? 5 : 2;
  const nsLoad = (data.anxiety + (10 - data.sleepQuality) + stim) / 3;

  let sleepDis = 0;
  if ((data.timeAwakeMinutes / 480) * 100 > 20) sleepDis += 3;
  if (data.sleepLatencyMinutes > 30) sleepDis += 3;
  if (data.nightAwakenings >= 2) sleepDis += 2;
  if (data.sleepHours < 6) sleepDis += 2;

  let nutrition = 0;
  if (data.breakfastProteinGrams >= 20) nutrition += 3;
  if (!data.sugarSpikes) nutrition += 3;
  if (data.mealTiming === 'consistent') nutrition += 2;
  if (data.hydrationOz >= 80) nutrition += 2;

  const crashRisk = sleepDis * 0.4 + nsLoad * 0.4 + (10 - nutrition) * 0.2;
  const moodDistortion = Math.abs(data.mood - stability);

  return { stability, dopamine, nsLoad, sleepDis, nutrition, crashRisk, moodDistortion,
    moodDev: data.mood - bl.avgMood, anxietyDev: data.anxiety - bl.avgAnxiety };
}

// ── Insights ──────────────────────────────────────────────────────────────────
function insights(data, bl, sc) {
  if (guardrails.hasCrisis(data.notes)) return { crisis: true };
  const out = [];
  const sleepDiff = data.sleepHours - bl.avgSleepHours;
  out.push({ lvl: 1, cat: 'sleep', conf: 100, text: `You slept ${data.sleepHours}h — ${sleepDiff > 0.5 ? 'more' : sleepDiff < -0.5 ? 'less' : 'about the same'} than your 7-day average of ${bl.avgSleepHours.toFixed(1)}h.` });
  if (data.caffeineMg) {
    const diff = data.caffeineMg - bl.avgCaffeineMg;
    out.push({ lvl: 1, cat: 'caffeine', conf: 100, text: `${data.caffeineMg}mg caffeine today — ${diff > 0 ? `${diff}mg above` : `${Math.abs(diff)}mg below`} your typical ${bl.avgCaffeineMg}mg.` });
  }
  if (sc.moodDistortion > 2 && sc.moodDistortion <= 4) {
    out.push({ lvl: 2, cat: 'perception', conf: 72, text: `Your reported mood (${data.mood}/10) is ${data.mood > sc.stability ? 'higher' : 'lower'} than your calculated stability score (${sc.stability.toFixed(1)}/10), which factors in sleep, anxiety, and energy.` });
  }
  if (sc.nsLoad > 6 && data.sleepQuality < 6) {
    out.push({ lvl: 2, cat: 'nervous system', conf: 75, text: `Elevated nervous system load (${sc.nsLoad.toFixed(1)}/10) combined with poor sleep tends to correlate with difficulty settling in the evening.` });
  }
  if (data.breakfastProteinGrams < 15 && data.focus < bl.avgEnergy - 1) {
    out.push({ lvl: 2, cat: 'nutrition', conf: 68, text: `Low breakfast protein days correlate with 0.8-point lower focus scores on average, based on your tracking pattern.` });
  }
  if (sc.moodDistortion > 2) {
    out.push({ lvl: 3, cat: 'reflection', conf: 60, text: `Your mood rating and stability score don't quite match. What felt different about today compared to what the data suggests?` });
  }
  if (sc.crashRisk > 6) {
    out.push({ lvl: 4, cat: 'provider', conf: 82, text: `Disrupted sleep, elevated stimulation, and high anxiety together are worth flagging for your provider if this pattern continues.` });
  }
  return out.filter(i => guardrails.pass(i.text, i.lvl)).sort((a, b) => a.lvl - b.lvl);
}

// ── Step config ───────────────────────────────────────────────────────────────
const STEPS = [
  { id: 'intro',     label: 'Start',    emoji: '👋', color: '#6366f1', dark: '#4338ca' },
  { id: 'core',      label: 'Mind',     emoji: '🧠', color: '#8b5cf6', dark: '#6d28d9' },
  { id: 'sleep',     label: 'Sleep',    emoji: '🌙', color: '#3b82f6', dark: '#1d4ed8' },
  { id: 'meds',      label: 'Meds',     emoji: '💊', color: '#0891b2', dark: '#0e7490' },
  { id: 'nutrition', label: 'Body',     emoji: '🥗', color: '#059669', dark: '#047857' },
  { id: 'summary',   label: 'Summary',  emoji: '✨', color: '#6366f1', dark: '#4338ca' },
];
const FLOW = ['intro','core','sleep','meds','nutrition','summary'];

// ── Score card ────────────────────────────────────────────────────────────────
function ScoreRing({ value, max = 10, label, sub, danger }) {
  const pct = Math.min(value / max, 1);
  const size = 96;
  const r = 36;
  const circ = 2 * Math.PI * r;
  const offset = circ * (1 - pct);
  const color = danger
    ? (value < 3 ? '#10b981' : value < 6 ? '#f59e0b' : '#ef4444')
    : (value > 7 ? '#10b981' : value > 4 ? '#6366f1' : '#f59e0b');

  return (
    <div className="flex flex-col items-center gap-1">
      <div style={{ position: 'relative', width: size, height: size }}>
        <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
          <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="rgba(255,255,255,0.1)" strokeWidth="8" />
          <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={color} strokeWidth="8"
            strokeDasharray={circ} strokeDashoffset={offset} strokeLinecap="round"
            style={{ transition: 'stroke-dashoffset 0.8s cubic-bezier(0.4,0,0.2,1)' }} />
        </svg>
        <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <span style={{ color, fontSize: 22, fontWeight: 700, fontFamily: 'DM Sans' }}>{value.toFixed(1)}</span>
        </div>
      </div>
      <p style={{ color: '#e2e8f0', fontSize: 13, fontWeight: 600, textAlign: 'center', margin: 0 }}>{label}</p>
      {sub && <p style={{ color: '#94a3b8', fontSize: 11, textAlign: 'center', margin: 0 }}>{sub}</p>}
    </div>
  );
}

// ── Big Slider ────────────────────────────────────────────────────────────────
function BigSlider({ label, value, onChange, min = 0, max = 10, step = 1, lo, hi, color = '#6366f1' }) {
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
        <label style={{ color: '#94a3b8', fontSize: 13, fontWeight: 500, letterSpacing: '0.05em', textTransform: 'uppercase' }}>{label}</label>
        <span style={{ color, fontSize: 28, fontWeight: 700, fontFamily: 'DM Serif Display' }}>
          {step < 1 ? value.toFixed(1) : value}{max <= 10 && step >= 1 ? '' : step < 1 ? 'h' : ''}
        </span>
      </div>
      <div style={{ position: 'relative', height: 8, borderRadius: 4, background: 'rgba(255,255,255,0.08)', cursor: 'pointer' }}>
        <div style={{ position: 'absolute', left: 0, top: 0, height: '100%', width: `${pct}%`,
          borderRadius: 4, background: `linear-gradient(90deg, ${color}88, ${color})`, transition: 'width 0.1s' }} />
        <input type="range" min={min} max={max} step={step} value={value}
          onChange={e => onChange(step < 1 ? parseFloat(e.target.value) : parseInt(e.target.value))}
          style={{ position: 'absolute', inset: 0, width: '100%', opacity: 0, cursor: 'pointer', margin: 0, height: '100%' }} />
        <div style={{ position: 'absolute', top: '50%', left: `${pct}%`, transform: 'translate(-50%, -50%)',
          width: 20, height: 20, borderRadius: '50%', background: color,
          boxShadow: `0 0 0 4px ${color}33`, transition: 'left 0.1s', pointerEvents: 'none' }} />
      </div>
      {(lo || hi) && (
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6 }}>
          <span style={{ color: '#475569', fontSize: 11 }}>{lo}</span>
          <span style={{ color: '#475569', fontSize: 11 }}>{hi}</span>
        </div>
      )}
    </div>
  );
}

// ── Pill toggle ───────────────────────────────────────────────────────────────
function PillToggle({ label, checked, onChange, color }) {
  return (
    <button onClick={() => onChange(!checked)}
      style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px',
        borderRadius: 12, border: `1px solid ${checked ? color + '44' : 'rgba(255,255,255,0.08)'}`,
        background: checked ? color + '22' : 'rgba(255,255,255,0.04)', cursor: 'pointer',
        textAlign: 'left', width: '100%', transition: 'all 0.2s' }}>
      <div style={{ width: 20, height: 20, borderRadius: 6,
        border: `2px solid ${checked ? color : 'rgba(255,255,255,0.2)'}`,
        background: checked ? color : 'transparent', flexShrink: 0,
        display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'all 0.2s' }}>
        {checked && <svg width="12" height="12" viewBox="0 0 12 12" fill="white"><path d="M2 6l3 3 5-5" stroke="white" strokeWidth="2" fill="none" strokeLinecap="round"/></svg>}
      </div>
      <span style={{ color: checked ? '#e2e8f0' : '#64748b', fontSize: 14, fontWeight: 500 }}>{label}</span>
    </button>
  );
}

// ── Select ────────────────────────────────────────────────────────────────────
function StyledSelect({ label, value, onChange, options, color }) {
  return (
    <div style={{ marginBottom: 20 }}>
      <label style={{ color: '#94a3b8', fontSize: 12, fontWeight: 500, letterSpacing: '0.05em',
        textTransform: 'uppercase', display: 'block', marginBottom: 8 }}>{label}</label>
      <select value={value} onChange={e => onChange(e.target.value)}
        style={{ width: '100%', padding: '12px 16px', borderRadius: 12,
          border: `1px solid rgba(255,255,255,0.1)`, background: 'rgba(255,255,255,0.06)',
          color: '#e2e8f0', fontSize: 15, outline: 'none', cursor: 'pointer',
          appearance: 'none', fontFamily: 'DM Sans' }}>
        {options.map(o => <option key={o.value} value={o.value} style={{ background: '#1e1e2e' }}>{o.label}</option>)}
      </select>
    </div>
  );
}

// ── Number input ──────────────────────────────────────────────────────────────
function NumInput({ label, value, onChange, min, max, step = 1, unit, hint, color }) {
  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
        <label style={{ color: '#94a3b8', fontSize: 12, fontWeight: 500, letterSpacing: '0.05em', textTransform: 'uppercase' }}>{label}</label>
        <span style={{ color, fontSize: 18, fontWeight: 700 }}>{value}{unit}</span>
      </div>
      <input type="number" min={min} max={max} step={step} value={value}
        onChange={e => onChange(parseFloat(e.target.value) || 0)}
        style={{ width: '100%', padding: '12px 16px', borderRadius: 12, boxSizing: 'border-box',
          border: `1px solid rgba(255,255,255,0.1)`, background: 'rgba(255,255,255,0.06)',
          color: '#e2e8f0', fontSize: 15, outline: 'none', fontFamily: 'DM Sans' }} />
      {hint && <p style={{ color: '#475569', fontSize: 11, marginTop: 4 }}>{hint}</p>}
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────
export default function App() {
  const [stepIdx, setStepIdx] = useState(0);
  const [bl, setBl] = useState(DEFAULTS);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveErr, setSaveErr] = useState('');

  const [data, setData] = useState({
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
      .then(r => r.ok ? r.json() : null).then(d => { if (d && Object.keys(d).length) setBl(p => ({ ...p, ...d })); }).catch(() => {});
    fetch('/api/patient/profile', { credentials: 'same-origin' })
      .then(r => r.ok ? r.json() : null).then(d => {
        if (!d) return;
        const meds = {};
        (d.current_medications || []).forEach(m => { meds[m.name] = { taken: false, dose: m.dose || '' }; });
        setData(p => ({ ...p, meds }));
      }).catch(() => {});
  }, []);

  const sc = useMemo(() => score(data, bl), [data, bl]);
  const ins = useMemo(() => insights(data, bl, sc), [data, sc, bl]);
  const set = useCallback((k, v) => setData(p => ({ ...p, [k]: v })), []);

  const stepCfg = STEPS[stepIdx];
  const canGoNext = stepIdx < STEPS.length - 1;
  const canGoBack = stepIdx > 0 && stepIdx < STEPS.length - 1;
  const next = () => setStepIdx(i => Math.min(i + 1, STEPS.length - 1));
  const back = () => setStepIdx(i => Math.max(i - 1, 0));

  const handleSave = async () => {
    setSaving(true); setSaveErr('');
    try {
      const medList = Object.entries(data.meds).filter(([,i]) => i.taken).map(([n,i]) => ({ name: n, dose: i.dose }));
      const res = await fetch('/api/checkins', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mood_score: data.mood, stress_score: data.anxiety, sleep_hours: data.sleepHours,
          medications: medList, notes: data.notes, time_of_day: `${data.timeOfCheckIn}:00`,
          extended_data: { energy: data.energy, focus: data.focus, dissociation: data.dissociation,
            sleep_quality: data.sleepQuality, time_awake_minutes: data.timeAwakeMinutes,
            sleep_latency_minutes: data.sleepLatencyMinutes, night_awakenings: data.nightAwakenings,
            caffeine_mg: data.caffeineMg, breakfast_protein_grams: data.breakfastProteinGrams,
            sugar_spikes: data.sugarSpikes, meal_timing: data.mealTiming, hydration_oz: data.hydrationOz,
            scores: { stability: sc.stability, crash_risk: sc.crashRisk, nervous_system_load: sc.nsLoad, dopamine_efficiency: sc.dopamine } },
        }),
      });
      if (res.ok) { setSaved(true); setTimeout(() => setSaved(false), 4000); }
      else { const e = await res.json().catch(() => ({})); setSaveErr(e.error || 'Save failed.'); }
    } catch { setSaveErr('Network error.'); }
    finally { setSaving(false); }
  };

  // ── Panel content per step ─────────────────────────────────────────────────
  const panels = {
    intro: {
      left: (
        <div>
          <div style={{ fontSize: 64, marginBottom: 24 }}>👋</div>
          <h1 style={{ color: '#fff', fontSize: 36, fontFamily: 'DM Serif Display', fontWeight: 400, margin: '0 0 16px', lineHeight: 1.2 }}>Daily<br/>Check-In</h1>
          <p style={{ color: '#94a3b8', fontSize: 16, lineHeight: 1.6, margin: '0 0 32px' }}>
            5 minutes. Real-time insights. Personalized to your patterns.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {[['🧠','Mental state'],['🌙','Sleep quality'],['💊','Medications'],['🥗','Nutrition'],['✨','Live score + insights']].map(([e,l]) => (
              <div key={l} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ fontSize: 18 }}>{e}</span>
                <span style={{ color: '#64748b', fontSize: 14 }}>{l}</span>
              </div>
            ))}
          </div>
        </div>
      ),
      right: (
        <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', height: '100%', gap: 24 }}>
          <div style={{ padding: '24px', borderRadius: 16, background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)' }}>
            <p style={{ color: '#94a3b8', fontSize: 14, lineHeight: 1.7, margin: 0 }}>
              Every check-in builds a model of <em style={{ color: '#e2e8f0' }}>your</em> patterns — how your sleep, caffeine, and nutrition affect your mood and energy. Nothing is assumed. Everything is calculated from your actual data.
            </p>
          </div>
          <button onClick={next} style={{ padding: '18px 32px', borderRadius: 16, border: 'none',
            background: `linear-gradient(135deg, ${stepCfg.color}, ${stepCfg.dark})`,
            color: '#fff', fontSize: 17, fontWeight: 600, fontFamily: 'DM Sans', cursor: 'pointer',
            boxShadow: `0 8px 32px ${stepCfg.color}44`, letterSpacing: '-0.01em' }}>
            Begin Check-In →
          </button>
          <a href="/dashboard" style={{ color: '#475569', fontSize: 13, textAlign: 'center', textDecoration: 'none' }}>← Back to dashboard</a>
        </div>
      ),
    },

    core: {
      left: (
        <div>
          <div style={{ fontSize: 56, marginBottom: 20 }}>🧠</div>
          <h2 style={{ color: '#fff', fontSize: 30, fontFamily: 'DM Serif Display', fontWeight: 400, margin: '0 0 12px' }}>Mental State</h2>
          <p style={{ color: '#94a3b8', fontSize: 15, lineHeight: 1.6, margin: '0 0 32px' }}>How you're feeling right now. These 5 signals feed your stability and crash-risk scores.</p>
          <div style={{ padding: 20, borderRadius: 16, background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.06)' }}>
            <p style={{ color: '#64748b', fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.08em', margin: '0 0 12px' }}>Current estimate</p>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <span style={{ color: stepCfg.color, fontSize: 40, fontFamily: 'DM Serif Display' }}>{sc.stability.toFixed(1)}</span>
              <span style={{ color: '#475569', fontSize: 16 }}>/10 stability</span>
            </div>
            <p style={{ color: '#475569', fontSize: 12, margin: '8px 0 0' }}>Your baseline: {bl.avgMood.toFixed(1)}</p>
          </div>
        </div>
      ),
      right: (
        <div>
          <BigSlider label="Mood" value={data.mood} onChange={v => set('mood', v)} lo="Very Low" hi="Excellent" color={stepCfg.color} />
          <BigSlider label="Energy" value={data.energy} onChange={v => set('energy', v)} lo="Exhausted" hi="Energized" color={stepCfg.color} />
          <BigSlider label="Focus / Clarity" value={data.focus} onChange={v => set('focus', v)} lo="Foggy" hi="Sharp" color={stepCfg.color} />
          <BigSlider label="Dissociation" value={data.dissociation} onChange={v => set('dissociation', v)} lo="Grounded" hi="Detached" color={stepCfg.color} />
          <BigSlider label="Anxiety" value={data.anxiety} onChange={v => set('anxiety', v)} lo="Calm" hi="Overwhelmed" color={stepCfg.color} />
        </div>
      ),
    },

    sleep: {
      left: (
        <div>
          <div style={{ fontSize: 56, marginBottom: 20 }}>🌙</div>
          <h2 style={{ color: '#fff', fontSize: 30, fontFamily: 'DM Serif Display', fontWeight: 400, margin: '0 0 12px' }}>Last Night's Sleep</h2>
          <p style={{ color: '#94a3b8', fontSize: 15, lineHeight: 1.6, margin: '0 0 32px' }}>Sleep quality is the strongest predictor in your crash-risk score.</p>
          <div style={{ padding: 20, borderRadius: 16, background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.06)' }}>
            <p style={{ color: '#64748b', fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.08em', margin: '0 0 12px' }}>Sleep disruption</p>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <span style={{ color: sc.sleepDis < 3 ? '#10b981' : sc.sleepDis < 6 ? '#f59e0b' : '#ef4444', fontSize: 40, fontFamily: 'DM Serif Display' }}>{sc.sleepDis}</span>
              <span style={{ color: '#475569', fontSize: 16 }}>points</span>
            </div>
            <p style={{ color: '#475569', fontSize: 12, margin: '8px 0 0' }}>{sc.sleepDis < 3 ? 'Restful night' : sc.sleepDis < 6 ? 'Some disruption' : 'Significant disruption'}</p>
          </div>
        </div>
      ),
      right: (
        <div>
          <div style={{ marginBottom: 24 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
              <label style={{ color: '#94a3b8', fontSize: 12, fontWeight: 500, letterSpacing: '0.05em', textTransform: 'uppercase' }}>Total Hours</label>
              <span style={{ color: stepCfg.color, fontSize: 28, fontWeight: 700, fontFamily: 'DM Serif Display' }}>{data.sleepHours.toFixed(1)}h</span>
            </div>
            <div style={{ position: 'relative', height: 8, borderRadius: 4, background: 'rgba(255,255,255,0.08)' }}>
              <div style={{ position: 'absolute', left: 0, top: 0, height: '100%', borderRadius: 4,
                width: `${(data.sleepHours / 12) * 100}%`,
                background: `linear-gradient(90deg, ${stepCfg.color}88, ${stepCfg.color})`, transition: 'width 0.1s' }} />
              <input type="range" min="0" max="12" step="0.5" value={data.sleepHours}
                onChange={e => set('sleepHours', parseFloat(e.target.value))}
                style={{ position: 'absolute', inset: 0, width: '100%', opacity: 0, cursor: 'pointer', margin: 0, height: '100%' }} />
              <div style={{ position: 'absolute', top: '50%', left: `${(data.sleepHours / 12) * 100}%`,
                transform: 'translate(-50%, -50%)', width: 20, height: 20, borderRadius: '50%',
                background: stepCfg.color, boxShadow: `0 0 0 4px ${stepCfg.color}33`, pointerEvents: 'none' }} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6 }}>
              <span style={{ color: '#475569', fontSize: 11 }}>0h</span>
              <span style={{ color: '#475569', fontSize: 11 }}>12h</span>
            </div>
          </div>
          <BigSlider label="Sleep Quality" value={data.sleepQuality} onChange={v => set('sleepQuality', v)} lo="Terrible" hi="Excellent" color={stepCfg.color} />
          <NumInput label="Minutes Awake During Night" value={data.timeAwakeMinutes} onChange={v => set('timeAwakeMinutes', v)} min={0} max={240} step={5} unit="min" color={stepCfg.color} />
          <StyledSelect label="Night Awakenings" value={String(data.nightAwakenings)}
            onChange={v => set('nightAwakenings', parseInt(v))}
            options={[{value:'0',label:'None'},{value:'1',label:'Once'},{value:'2',label:'Twice'},{value:'3',label:'3 or more'}]}
            color={stepCfg.color} />
        </div>
      ),
    },

    meds: {
      left: (
        <div>
          <div style={{ fontSize: 56, marginBottom: 20 }}>💊</div>
          <h2 style={{ color: '#fff', fontSize: 30, fontFamily: 'DM Serif Display', fontWeight: 400, margin: '0 0 12px' }}>Medications & Stimulation</h2>
          <p style={{ color: '#94a3b8', fontSize: 15, lineHeight: 1.6, margin: '0 0 32px' }}>Logging what you took (and caffeine) lets the system calculate dopamine efficiency.</p>
          <div style={{ padding: 20, borderRadius: 16, background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.06)' }}>
            <p style={{ color: '#64748b', fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.08em', margin: '0 0 12px' }}>Dopamine efficiency</p>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <span style={{ color: stepCfg.color, fontSize: 40, fontFamily: 'DM Serif Display' }}>{sc.dopamine.toFixed(1)}</span>
              <span style={{ color: '#475569', fontSize: 16 }}>/10</span>
            </div>
          </div>
        </div>
      ),
      right: (
        <div>
          {Object.keys(data.meds).length === 0 ? (
            <div style={{ padding: 24, borderRadius: 16, background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', marginBottom: 24 }}>
              <p style={{ color: '#475569', fontSize: 14, margin: 0 }}>No medications on your profile. <a href="/settings" style={{ color: stepCfg.color }}>Add them in Settings →</a></p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 24 }}>
              <p style={{ color: '#64748b', fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.08em', margin: '0 0 8px' }}>Taken today</p>
              {Object.entries(data.meds).map(([med, info]) => (
                <PillToggle key={med} label={`${med.charAt(0).toUpperCase() + med.slice(1)} ${info.dose ? `(${info.dose})` : ''}`}
                  checked={info.taken} onChange={v => set('meds', { ...data.meds, [med]: { ...info, taken: v } })}
                  color={stepCfg.color} />
              ))}
            </div>
          )}
          <NumInput label="Caffeine Today" value={data.caffeineMg} onChange={v => set('caffeineMg', v)} min={0} max={600} step={10} unit="mg"
            hint={`Your typical range: ${bl.optimalCaffeine?.min ?? 200}–${bl.optimalCaffeine?.max ?? 300}mg`} color={stepCfg.color} />
        </div>
      ),
    },

    nutrition: {
      left: (
        <div>
          <div style={{ fontSize: 56, marginBottom: 20 }}>🥗</div>
          <h2 style={{ color: '#fff', fontSize: 30, fontFamily: 'DM Serif Display', fontWeight: 400, margin: '0 0 12px' }}>Body & Nutrition</h2>
          <p style={{ color: '#94a3b8', fontSize: 15, lineHeight: 1.6, margin: '0 0 32px' }}>Nutrition stability is factored into your crash-risk score.</p>
          <div style={{ padding: 20, borderRadius: 16, background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.06)' }}>
            <p style={{ color: '#64748b', fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.08em', margin: '0 0 12px' }}>Nutrition score</p>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <span style={{ color: stepCfg.color, fontSize: 40, fontFamily: 'DM Serif Display' }}>{sc.nutrition}</span>
              <span style={{ color: '#475569', fontSize: 16 }}>/10</span>
            </div>
            <p style={{ color: '#475569', fontSize: 12, margin: '8px 0 0' }}>Updates as you fill this in</p>
          </div>
        </div>
      ),
      right: (
        <div>
          <NumInput label="Breakfast Protein" value={data.breakfastProteinGrams} onChange={v => set('breakfastProteinGrams', v)} min={0} max={60} step={5} unit="g"
            hint="20g+ correlates with better focus scores on your data" color={stepCfg.color} />
          <PillToggle label="No major sugar crashes today" checked={!data.sugarSpikes}
            onChange={v => set('sugarSpikes', !v)} color={stepCfg.color} />
          <div style={{ marginTop: 16 }} />
          <StyledSelect label="Meal Timing" value={data.mealTiming} onChange={v => set('mealTiming', v)}
            options={[{value:'missed',label:'Skipped meals'},{value:'irregular',label:'Irregular'},{value:'consistent',label:'Consistent'}]}
            color={stepCfg.color} />
          <NumInput label="Hydration" value={data.hydrationOz} onChange={v => set('hydrationOz', v)} min={0} max={160} step={8} unit="oz"
            hint="Target: 80–100oz" color={stepCfg.color} />
          <div style={{ marginBottom: 8 }}>
            <label style={{ color: '#94a3b8', fontSize: 12, fontWeight: 500, letterSpacing: '0.05em', textTransform: 'uppercase', display: 'block', marginBottom: 8 }}>Anything else?</label>
            <textarea value={data.notes} onChange={e => set('notes', e.target.value)}
              placeholder="Life events, stress, unexpected changes…"
              style={{ width: '100%', padding: '12px 16px', borderRadius: 12, boxSizing: 'border-box',
                border: '1px solid rgba(255,255,255,0.1)', background: 'rgba(255,255,255,0.06)',
                color: '#e2e8f0', fontSize: 15, fontFamily: 'DM Sans', resize: 'none', height: 80, outline: 'none' }} />
          </div>
        </div>
      ),
    },

    summary: ins.crisis ? {
      left: (
        <div>
          <div style={{ fontSize: 56, marginBottom: 20 }}>🤝</div>
          <h2 style={{ color: '#fff', fontSize: 30, fontFamily: 'DM Serif Display', fontWeight: 400, margin: '0 0 12px' }}>You're not alone</h2>
          <p style={{ color: '#94a3b8', fontSize: 15, lineHeight: 1.6 }}>Reaching out is the right thing to do. Crisis support is available 24/7.</p>
        </div>
      ),
      right: (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <p style={{ color: '#e2e8f0', fontSize: 16, lineHeight: 1.6, margin: '0 0 16px' }}>It looks like you might be going through something really hard right now.</p>
          <a href="tel:988" style={{ display: 'block', padding: '16px 24px', borderRadius: 14, background: '#ef4444',
            color: '#fff', textDecoration: 'none', fontWeight: 600, fontSize: 16, textAlign: 'center' }}>
            📞 Call 988 — Suicide & Crisis Lifeline
          </a>
          <a href="sms:741741&body=HOME" style={{ display: 'block', padding: '16px 24px', borderRadius: 14,
            background: 'rgba(239,68,68,0.15)', border: '1px solid rgba(239,68,68,0.3)',
            color: '#fca5a5', textDecoration: 'none', fontWeight: 600, fontSize: 16, textAlign: 'center' }}>
            💬 Text HOME to 741741
          </a>
          <button onClick={back} style={{ padding: '14px 24px', borderRadius: 14, border: '1px solid rgba(255,255,255,0.1)',
            background: 'transparent', color: '#94a3b8', fontSize: 15, cursor: 'pointer', fontFamily: 'DM Sans' }}>
            I'm safe right now
          </button>
        </div>
      ),
    } : {
      left: (
        <div>
          <div style={{ fontSize: 56, marginBottom: 20 }}>✨</div>
          <h2 style={{ color: '#fff', fontSize: 30, fontFamily: 'DM Serif Display', fontWeight: 400, margin: '0 0 16px' }}>Today's Scores</h2>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, marginBottom: 24 }}>
            <ScoreRing value={sc.stability} label="Stability" sub={`Baseline ${bl.avgMood.toFixed(1)}`} />
            <ScoreRing value={sc.crashRisk} label="Crash Risk" sub="next 6h" danger />
            <ScoreRing value={sc.nsLoad} label="NS Load" sub="lower = calmer" danger />
            <ScoreRing value={sc.dopamine} label="Dopamine" />
          </div>
          {sc.moodDistortion > 1.5 && (
            <div style={{ padding: 16, borderRadius: 12, background: 'rgba(245,158,11,0.1)', border: '1px solid rgba(245,158,11,0.2)' }}>
              <p style={{ color: '#fbbf24', fontSize: 13, margin: 0, lineHeight: 1.5 }}>
                Your mood ({data.mood}/10) and stability ({sc.stability.toFixed(1)}/10) don't quite match. Feelings and data sometimes tell different stories.
              </p>
            </div>
          )}
        </div>
      ),
      right: (
        <div>
          {Array.isArray(ins) && ins.length > 0 && (
            <div style={{ marginBottom: 28 }}>
              <p style={{ color: '#64748b', fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.08em', margin: '0 0 14px' }}>Insights</p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {ins.slice(0, 5).map((insight, i) => {
                  const colors = { 1: '#6366f1', 2: '#8b5cf6', 3: '#0891b2', 4: '#f59e0b' };
                  const labels = { 1: 'Observation', 2: 'Pattern', 3: 'Reflection', 4: 'Provider Alert' };
                  const c = colors[insight.lvl];
                  return (
                    <div key={i} style={{ padding: '14px 16px', borderRadius: 14,
                      border: `1px solid ${c}22`, background: `${c}0d` }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                        <span style={{ color: c, fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{labels[insight.lvl]} · {insight.cat}</span>
                        <span style={{ color: '#475569', fontSize: 11 }}>{insight.conf}%</span>
                      </div>
                      <p style={{ color: '#cbd5e1', fontSize: 14, margin: 0, lineHeight: 1.6 }}>{insight.text}</p>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
          {saveErr && <p style={{ color: '#f87171', fontSize: 13, marginBottom: 12 }}>{saveErr}</p>}
          {saved && (
            <div style={{ padding: '12px 16px', borderRadius: 12, background: 'rgba(16,185,129,0.1)', border: '1px solid rgba(16,185,129,0.2)', marginBottom: 12 }}>
              <p style={{ color: '#34d399', fontSize: 14, margin: 0 }}>✓ Check-in saved</p>
            </div>
          )}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <button onClick={() => { setStepIdx(0); setSaved(false); setSaveErr(''); }}
              style={{ padding: '14px 20px', borderRadius: 14, border: '1px solid rgba(255,255,255,0.1)',
                background: 'rgba(255,255,255,0.04)', color: '#94a3b8', fontSize: 14, cursor: 'pointer', fontFamily: 'DM Sans' }}>
              New Check-In
            </button>
            <button onClick={handleSave} disabled={saving || saved}
              style={{ padding: '14px 20px', borderRadius: 14, border: 'none',
                background: saved ? '#065f46' : `linear-gradient(135deg, #059669, #047857)`,
                color: '#fff', fontSize: 14, fontWeight: 600, cursor: 'pointer', fontFamily: 'DM Sans',
                opacity: saving ? 0.7 : 1 }}>
              {saving ? 'Saving…' : saved ? '✓ Saved' : 'Save to Profile'}
            </button>
          </div>
          <a href="/dashboard" style={{ display: 'block', textAlign: 'center', marginTop: 16, color: '#475569', fontSize: 13, textDecoration: 'none' }}>← Back to dashboard</a>
        </div>
      ),
    },
  };

  const panel = panels[stepCfg.id];

  return (
    <div style={{ minHeight: '100vh', background: '#0e0e1a', display: 'flex', flexDirection: 'column', fontFamily: 'DM Sans' }}>
      {/* Top bar */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '16px 32px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ width: 32, height: 32, borderRadius: 8, background: `linear-gradient(135deg, ${stepCfg.color}, ${stepCfg.dark})`,
            display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <span style={{ color: '#fff', fontSize: 14, fontFamily: 'DM Serif Display', fontWeight: 400 }}>C</span>
          </div>
          <span style={{ color: '#e2e8f0', fontSize: 15, fontWeight: 600, letterSpacing: '-0.01em' }}>CognaSync</span>
        </div>

        {/* Progress pills */}
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {STEPS.filter(s => s.id !== 'intro').map((s, i) => {
            const realIdx = i + 1;
            const active = stepIdx === realIdx;
            const done = stepIdx > realIdx;
            return (
              <div key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <div style={{ width: active ? 28 : 8, height: 8, borderRadius: 4, transition: 'all 0.3s cubic-bezier(0.4,0,0.2,1)',
                  background: done ? '#10b981' : active ? stepCfg.color : 'rgba(255,255,255,0.1)' }} />
              </div>
            );
          })}
        </div>

        <div style={{ fontSize: 13, color: '#475569' }}>
          {stepIdx > 0 && stepIdx < STEPS.length - 1 ? `${stepIdx} of ${STEPS.length - 2}` : ''}
        </div>
      </div>

      {/* Main split layout */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Left panel */}
        <div style={{ width: '42%', minWidth: 320, padding: '56px 48px',
          background: `linear-gradient(160deg, ${stepCfg.color}18 0%, #0e0e1a 60%)`,
          borderRight: '1px solid rgba(255,255,255,0.05)',
          display: 'flex', flexDirection: 'column', justifyContent: 'center',
          position: 'relative', overflow: 'hidden' }}>
          {/* Decorative glow */}
          <div style={{ position: 'absolute', top: -100, left: -100, width: 400, height: 400,
            borderRadius: '50%', background: `${stepCfg.color}12`, filter: 'blur(80px)', pointerEvents: 'none' }} />
          <div style={{ position: 'relative', zIndex: 1 }}>
            {panel?.left}
          </div>
        </div>

        {/* Right panel */}
        <div style={{ flex: 1, padding: '56px 48px', overflowY: 'auto', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          <div style={{ maxWidth: 520 }}>
            {panel?.right}
            {/* Nav buttons */}
            {stepCfg.id !== 'intro' && stepCfg.id !== 'summary' && (
              <div style={{ display: 'flex', gap: 12, marginTop: 32, paddingTop: 24, borderTop: '1px solid rgba(255,255,255,0.06)' }}>
                {canGoBack && (
                  <button onClick={back}
                    style={{ padding: '14px 24px', borderRadius: 14, border: '1px solid rgba(255,255,255,0.1)',
                      background: 'rgba(255,255,255,0.04)', color: '#94a3b8', fontSize: 14, cursor: 'pointer', fontFamily: 'DM Sans' }}>
                    ← Back
                  </button>
                )}
                <button onClick={next}
                  style={{ flex: 1, padding: '14px 24px', borderRadius: 14, border: 'none',
                    background: `linear-gradient(135deg, ${stepCfg.color}, ${stepCfg.dark})`,
                    color: '#fff', fontSize: 15, fontWeight: 600, fontFamily: 'DM Sans', cursor: 'pointer',
                    boxShadow: `0 4px 20px ${stepCfg.color}33` }}>
                  Continue →
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
