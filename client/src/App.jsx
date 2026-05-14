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
  advBg:       '#F5F3FF',   // subtle lavender tint for advanced sections
  advBorder:   '#C4B5FD',
};

const STEP_COLORS = {
  intro:     { fg: '#000000', bg: '#ECECEC', mid: '#333333' },
  core:      { fg: '#000000', bg: '#ECECEC', mid: '#333333' },
  sleep:     { fg: '#000000', bg: '#ECECEC', mid: '#333333' },
  meds:      { fg: '#000000', bg: '#ECECEC', mid: '#333333' },
  nutrition: { fg: '#000000', bg: '#ECECEC', mid: '#333333' },
  summary:   { fg: '#000000', bg: '#ECECEC', mid: '#333333' },
};

// ── Helpers ───────────────────────────────────────────────────────────
function localDateStr() {
  const n = new Date();
  return n.getFullYear() + '-' + String(n.getMonth() + 1).padStart(2, '0') + '-' + String(n.getDate()).padStart(2, '0');
}

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

  // Advanced composite — motivation and irritability modulate the stability reading
  const advancedStability = d.irritability !== undefined
    ? (stability + (10 - d.irritability) / 2 + d.motivation / 2) / 2
    : stability;

  return {
    stability, advancedStability, dopamine, nsLoad, sleepDis, caffeineMg, crashRisk, moodDistort,
    moodDev: d.mood - bl.avgMood, anxietyDev: d.anxiety - bl.avgAnxiety,
  };
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

function InkSlider({ label, hint, value, onChange, min = 0, max = 10, step = 1, lo, hi, color }) {
  const c = color || P.accent;
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <div style={{ marginBottom: 28 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: hint ? 2 : 10 }}>
        <label style={{ color: P.inkMid, fontSize: 12, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase' }}>{label}</label>
        <span style={{ color: c, fontSize: 26, fontWeight: 700, fontFamily: 'DM Serif Display', lineHeight: 1 }}>{step < 1 ? value.toFixed(1) : value}</span>
      </div>
      {hint && <p style={{ color: P.inkFaint, fontSize: 11, margin: '0 0 8px', lineHeight: 1.4 }}>{hint}</p>}
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

function PaperToggle({ label, hint, checked, onChange, color }) {
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
      <div>
        <div style={{ color: P.ink, fontSize: 14, fontWeight: 500 }}>{label}</div>
        {hint && <div style={{ color: P.inkFaint, fontSize: 11, marginTop: 2 }}>{hint}</div>}
      </div>
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

function PaperNumInput({ label, hint, value, onChange, min, max, step = 1, unit, color }) {
  const c = color || P.accent;
  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: hint ? 2 : 7 }}>
        <label style={{ color: P.inkMid, fontSize: 12, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase' }}>{label}</label>
        <span style={{ color: c, fontSize: 16, fontWeight: 700 }}>{value}{unit}</span>
      </div>
      {hint && <p style={{ color: P.inkFaint, fontSize: 11, margin: '0 0 6px', lineHeight: 1.4 }}>{hint}</p>}
      <input type="number" min={min} max={max} step={step} value={value}
        onChange={e => onChange(parseFloat(e.target.value) || 0)}
        style={{ width: '100%', padding: '10px 14px', borderRadius: 2, border: `1px solid ${P.border}`,
          background: P.surface, color: P.ink, fontSize: 14, outline: 'none', fontFamily: 'DM Sans' }} />
    </div>
  );
}

// Advanced section wrapper — subtle lavender tint to visually separate
function AdvancedSection({ title, children }) {
  const [open, setOpen] = useState(true);
  return (
    <div style={{ marginTop: 8, border: `1px solid ${P.advBorder}`, borderRadius: 2 }}>
      <button onClick={() => setOpen(o => !o)}
        style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '10px 14px', background: P.advBg, border: 'none', cursor: 'pointer',
          borderBottom: open ? `1px solid ${P.advBorder}` : 'none' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 10, background: '#7C3AED', color: '#fff', padding: '2px 7px',
            borderRadius: 10, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase' }}>Advanced</span>
          <span style={{ color: '#5B21B6', fontSize: 12, fontWeight: 600 }}>{title}</span>
        </div>
        <span style={{ color: '#7C3AED', fontSize: 14 }}>{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div style={{ padding: '18px 16px', background: P.advBg }}>
          {children}
        </div>
      )}
    </div>
  );
}

const Divider = () => <div style={{ height: 1, background: P.borderLight, margin: '20px 0' }} />;

function useMobile(bp = 768) {
  const [m, setM] = useState(() => typeof window !== 'undefined' && window.innerWidth <= bp);
  useEffect(() => {
    const h = () => setM(window.innerWidth <= bp);
    window.addEventListener('resize', h);
    return () => window.removeEventListener('resize', h);
  }, [bp]);
  return m;
}

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
  const [checkinId, setCheckinId] = useState(null);
  const [insightFeedback, setInsightFeedback] = useState(null); // 'up' | 'down' | null
  const [entryDate, setEntryDate] = useState(() => localDateStr());
  const [entryTime, setEntryTime] = useState(() => new Date().toTimeString().slice(0, 5));
  const [completedToday, setCompletedToday] = useState([]);
  const [completedDetails, setCompletedDetails] = useState({});
  const [viewingCompleted, setViewingCompleted] = useState(null);
  const [advancedMode, setAdvancedMode] = useState(false);
  const [todayCheckinCount, setTodayCheckinCount] = useState(0);
  const isMobile = useMobile();

  const [d, setD] = useState({
    timeOfCheckIn: new Date().getHours(),
    // ── Core ──────────────────────────────────────────────
    mood: 6, energy: 6, dissociation: 1, anxiety: 3, focus: 6,
    // ── Core advanced ─────────────────────────────────────
    irritability: 3,     // 1–10, early burnout indicator
    motivation: 6,       // 1–10, anhedonia / executive function
    perceivedStress: 3,  // 1–10, external pressure load
    // ── Sleep ─────────────────────────────────────────────
    sleepHours: 6, sleepQuality: 6, timeAwakeMinutes: 0,
    sleepLatencyMinutes: 0, nightAwakenings: 0,
    // ── Sleep advanced ────────────────────────────────────
    wakeUpTime: '',
    // ── Medications & caffeine ────────────────────────────
    caffeine: { coffee: 0, tea: 0, soda: 0, energy: 0 },
    meds: {}, notes: '',
    // ── Substances & lifestyle (advanced) ─────────────────
    alcoholUnits: 0,        // drinks today
    hydrated: true,         // self-assessed hydration
    exerciseMinutes: 0,     // physical activity
    sunlightHours: 1,       // outdoor/sunlight exposure
    screenTimeHours: 4,     // total screen time
    socialQuality: 3,       // 1–5, connection quality
    workloadFriction: 3,    // 1–5, task/work pressure
    // ── Coping & interventions (advanced) ─────────────────
    didBreathing: false,
    didMeditation: false,
    didMovement: false,
  });

  useEffect(() => {
    Promise.all([
      fetch('/api/checkins/baseline',     { credentials: 'same-origin' }).then(r => r.ok ? r.json() : null).catch(() => null),
      fetch('/api/patient/profile',       { credentials: 'same-origin' }).then(r => r.ok ? r.json() : null).catch(() => null),
      fetch('/api/checkins/today?date='        + localDateStr(), { credentials: 'same-origin' }).then(r => r.ok ? r.json() : null).catch(() => null),
      fetch('/api/checkins/today-summary?date=' + localDateStr(), { credentials: 'same-origin' }).then(r => r.ok ? r.json() : null).catch(() => null),
    ]).then(([baseline, profile, todayCompletion, todaySummary]) => {
      if (baseline && Object.keys(baseline).length) setBl(p => ({ ...p, ...baseline }));
      if (todayCompletion) {
        setCompletedToday(todayCompletion.completed || []);
        setCompletedDetails(todayCompletion.details || {});
      }

      // Build meds map — prefer server-injected list (window.__medications__) over XHR
      // so medications are never lost if the profile API call fails silently.
      const medList = (profile?.current_medications?.length ? profile.current_medications : null)
        || (window.__medications__?.length ? window.__medications__ : []);
      const meds = {};
      medList.forEach(m => {
        const key = m.dose ? `${m.name}|||${m.dose}` : m.name;
        meds[key] = { name: m.name, taken: false, dose: m.dose || '', timeTaken: '' };
      });

      const updates = { meds };

      // Always apply medication taken-status — includes both check-in logs and homescreen quick-logs.
      (todaySummary?.medications || []).forEach(logged => {
        if (!logged.taken) return;
        const key = logged.dose ? `${logged.name}|||${logged.dose}` : logged.name;
        // Also try bare name match (quick-logs don't carry dose context)
        const bareKey = logged.name;
        const target = meds[key] || meds[bareKey];
        if (target) target.taken = true, target.timeTaken = logged.time_taken || '';
      });

      // Pre-populate cumulative daily fields from earlier check-ins today.
      // Behavioural/lifestyle data accumulates; subjective state (mood, anxiety…) stays fresh.
      if (todaySummary?.checkin_count > 0) {
        setTodayCheckinCount(todaySummary.checkin_count);

        // Caffeine (running total per beverage)
        const bd = todaySummary.caffeine_breakdown || {};
        updates.caffeine = { coffee: bd.coffee || 0, tea: bd.tea || 0,
                             soda: bd.soda || 0, energy: bd.energy || 0 };

        // Alcohol
        if (todaySummary.alcohol_units > 0) updates.alcoholUnits = todaySummary.alcohol_units;

        // Physical activity, sunlight, screen time (cumulative running totals)
        if (todaySummary.exercise_minutes  > 0) updates.exerciseMinutes  = todaySummary.exercise_minutes;
        if (todaySummary.sunlight_hours    > 0) updates.sunlightHours    = todaySummary.sunlight_hours;
        if (todaySummary.screen_time_hours > 0) updates.screenTimeHours  = todaySummary.screen_time_hours;

        // Coping & hydration (boolean OR — once done it stays done for the day)
        const coping = todaySummary.coping || {};
        if (coping.breathing)       updates.didBreathing  = true;
        if (coping.meditation)      updates.didMeditation = true;
        if (coping.movement)        updates.didMovement   = true;
        if (todaySummary.hydrated)  updates.hydrated      = true;

        // Wake-up time (logged once; carry it through all check-ins)
        if (todaySummary.wake_up_time) updates.wakeUpTime = todaySummary.wake_up_time;

        // Sleep (carry from the morning check-in through the rest of the day)
        const sl = todaySummary.sleep || {};
        if (sl.hours               != null) updates.sleepHours             = sl.hours;
        if (sl.quality             != null) updates.sleepQuality           = sl.quality;
        if (sl.time_awake_minutes  != null) updates.timeAwakeMinutes       = sl.time_awake_minutes;
        if (sl.sleep_latency_minutes != null) updates.sleepLatencyMinutes  = sl.sleep_latency_minutes;
        if (sl.night_awakenings    != null) updates.nightAwakenings        = sl.night_awakenings;
      }

      setD(p => ({ ...p, ...updates }));
    });
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

      const extendedData = {
        energy: d.energy, focus: d.focus, dissociation: d.dissociation,
        sleep_quality: d.sleepQuality, time_awake_minutes: d.timeAwakeMinutes,
        night_awakenings: d.nightAwakenings, sleep_latency_minutes: d.sleepLatencyMinutes,
        caffeine_mg: sc.caffeineMg, caffeine_breakdown: d.caffeine,
        alcohol_units: d.alcoholUnits,
        scores: { stability: sc.stability, crash_risk: sc.crashRisk, nervous_system_load: sc.nsLoad, dopamine_efficiency: sc.dopamine },
      };

      if (advancedMode) {
        Object.assign(extendedData, {
          irritability: d.irritability,
          motivation: d.motivation,
          perceived_stress: d.perceivedStress,
          wake_up_time: d.wakeUpTime,
          hydrated: d.hydrated,
          exercise_minutes: d.exerciseMinutes,
          sunlight_hours: d.sunlightHours,
          screen_time_hours: d.screenTimeHours,
          social_quality: d.socialQuality,
          workload_friction: d.workloadFriction,
          coping: { breathing: d.didBreathing, meditation: d.didMeditation, movement: d.didMovement },
        });
      }

      const res = await fetch('/api/checkins', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mood_score: d.mood, stress_score: d.anxiety, sleep_hours: d.sleepHours,
          medications: medList, notes: d.notes,
          date: entryDate, time_of_day: entryTime,
          checkin_type: checkinType,
          extended_data: extendedData,
        }),
      });
      if (res.ok) {
        const body = await res.json().catch(() => ({}));
        if (body.ai_insight) setAiInsight(body.ai_insight);
        if (body.checkin_id) { setCheckinId(body.checkin_id); setInsightFeedback(null); }
        setSaved(true);
        setTimeout(() => setSaved(false), 4000);
        if (checkinType !== 'on_demand') {
          setCompletedToday(prev => prev.includes(checkinType) ? prev : [...prev, checkinType]);
        }
      } else { const e = await res.json().catch(() => ({})); setSaveErr(e.error || e.detail || 'Save failed.'); }
    } catch { setSaveErr('Network error.'); }
    finally { setSaving(false); }
  };

  // ── Left panel content ──────────────────────────────────────────────
  const leftContent = {
    intro: <>
      <h1 style={{ fontFamily: 'DM Serif Display', fontWeight: 400, fontSize: 36, color: P.ink, margin: '0 0 14px', lineHeight: 1.2, letterSpacing: '-0.02em' }}>Daily<br/>Check-In</h1>
      <p style={{ color: P.inkMid, fontSize: 15, lineHeight: 1.7, margin: '0 0 28px' }}>Five minutes. Real patterns. Personalized to you.</p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {[
          ['Mental state'],
          ['Sleep quality'],
          ['Medications & caffeine'],
          ['Live scores + insights'],
          ...(advancedMode ? [['+ Mood nuance (irritability, motivation)'], ['+ Lifestyle (exercise, sunlight, hydration)'], ['+ Coping & social quality']] : []),
        ].map(([l]) => (
          <div key={l} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 4, height: 4, borderRadius: '50%', background: l.startsWith('+') ? '#7C3AED' : P.border, flexShrink: 0 }} />
            <span style={{ color: l.startsWith('+') ? '#5B21B6' : P.inkMid, fontSize: 14 }}>{l}</span>
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
      {advancedMode && (
        <div style={{ marginTop: 12, padding: '12px 14px', background: P.advBg, border: `1px solid ${P.advBorder}` }}>
          <p style={{ color: '#5B21B6', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.07em', margin: '0 0 4px', fontWeight: 700 }}>Advanced mode on</p>
          <p style={{ color: '#7C3AED', fontSize: 12, margin: 0, lineHeight: 1.5 }}>Tracking irritability, motivation, and perceived stress in addition to core signals.</p>
        </div>
      )}
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
      <div style={{ marginTop: 14, padding: '12px 14px', background: P.accentLight, border: `1px solid ${P.borderLight}` }}>
        <p style={{ color: P.inkFaint, fontSize: 11, margin: 0, lineHeight: 1.55 }}>
          <strong>Sleep latency</strong> (time to fall asleep) is factored into your crash-risk score. Enter it below if you remember.
        </p>
      </div>
    </>,

    meds: <>
      <h2 style={{ fontFamily: 'DM Serif Display', fontWeight: 400, fontSize: 30, color: P.ink, margin: '0 0 10px' }}>Medications & Caffeine</h2>
      <p style={{ color: P.inkMid, fontSize: 14, lineHeight: 1.65, margin: '0 0 28px' }}>Log what you took and your caffeine intake today.</p>
      {todayCheckinCount > 0 && (
        <div style={{ padding: '10px 14px', background: P.accentLight, border: `1px solid ${P.borderLight}`, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 13 }}>↑</span>
          <p style={{ color: P.inkMid, fontSize: 12, margin: 0, lineHeight: 1.4 }}>
            Continued from earlier today — add anything since your last check-in.
          </p>
        </div>
      )}
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
      {advancedMode && (
        <div style={{ marginTop: 12, padding: '12px 14px', background: P.advBg, border: `1px solid ${P.advBorder}` }}>
          <p style={{ color: '#5B21B6', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.07em', margin: '0 0 4px', fontWeight: 700 }}>Advanced mode on</p>
          <p style={{ color: '#7C3AED', fontSize: 12, margin: 0, lineHeight: 1.5 }}>Also tracking substances, hydration, exercise, sunlight, and coping strategies.</p>
        </div>
      )}
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

        {/* Advanced mode toggle */}
        <div style={{ border: `1px solid ${advancedMode ? P.advBorder : P.borderLight}`, background: advancedMode ? P.advBg : P.surface, transition: 'all 0.2s' }}>
          <button onClick={() => setAdvancedMode(m => !m)}
            style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '14px 16px', background: 'transparent', border: 'none', cursor: 'pointer', textAlign: 'left' }}>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                <span style={{ fontSize: 10, background: advancedMode ? '#7C3AED' : P.inkFaint, color: '#fff',
                  padding: '2px 7px', borderRadius: 10, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase',
                  transition: 'background 0.2s' }}>Advanced</span>
                <span style={{ color: advancedMode ? '#5B21B6' : P.ink, fontSize: 14, fontWeight: 600 }}>Expanded Check-In</span>
              </div>
              <p style={{ color: P.inkFaint, fontSize: 12, margin: 0, lineHeight: 1.5 }}>
                Adds mood nuance, lifestyle factors, substances, and coping strategies. Takes ~3 extra minutes.
              </p>
            </div>
            <div style={{ width: 40, height: 22, borderRadius: 11, background: advancedMode ? '#7C3AED' : P.borderLight,
              position: 'relative', flexShrink: 0, marginLeft: 12, transition: 'background 0.2s' }}>
              <div style={{ position: 'absolute', top: 3, left: advancedMode ? 21 : 3, width: 16, height: 16,
                borderRadius: '50%', background: '#fff', transition: 'left 0.2s',
                boxShadow: '0 1px 3px rgba(0,0,0,0.2)' }} />
            </div>
          </button>

          {advancedMode && (
            <div style={{ borderTop: `1px solid ${P.advBorder}`, padding: '12px 16px' }}>
              <p style={{ color: '#5B21B6', fontSize: 11, margin: '0 0 8px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>What's added</p>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
                {['Irritability & motivation','Perceived stress level','Sleep latency tracking','Alcohol & substance log','Hydration status','Exercise & movement','Sunlight exposure','Screen time','Social quality','Workload pressure','Coping strategies'].map(item => (
                  <div key={item} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '3px 0' }}>
                    <div style={{ width: 4, height: 4, borderRadius: '50%', background: '#7C3AED', flexShrink: 0 }} />
                    <span style={{ color: '#5B21B6', fontSize: 11 }}>{item}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
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
        <InkSlider
          label="Mood"
          hint="Overall emotional state — how good do you feel right now?"
          value={d.mood} onChange={v => set('mood', v)}
          lo="Barely functioning" hi="At my best"
          color={clr.fg} />
        <InkSlider
          label="Energy"
          hint="Physical and mental activation — body and mind combined"
          value={d.energy} onChange={v => set('energy', v)}
          lo="Completely depleted" hi="Fully energized"
          color={clr.fg} />
        <InkSlider
          label="Focus & Clarity"
          hint="Ability to think clearly and hold attention on a single task"
          value={d.focus} onChange={v => set('focus', v)}
          lo="Scattered / foggy" hi="Laser-focused, sharp"
          color={clr.fg} />
        <InkSlider
          label="Dissociation"
          hint="Sense of presence — are you 'in your body' and engaged with reality?"
          value={d.dissociation} onChange={v => set('dissociation', v)}
          lo="Fully grounded & present" hi="Detached / zoning out"
          color={clr.fg} />
        <InkSlider
          label="Anxiety"
          hint="Worry, tension, and nervous system activation right now"
          value={d.anxiety} onChange={v => set('anxiety', v)}
          lo="Completely calm" hi="Panicked / overwhelmed"
          color={clr.fg} />

        {advancedMode && (
          <AdvancedSection title="Mood nuance">
            <InkSlider
              label="Irritability"
              hint="How quickly are you getting triggered or frustrated? Early burnout indicator."
              value={d.irritability} onChange={v => set('irritability', v)}
              lo="Very patient, steady" hi="Hair-trigger reactive"
              color="#7C3AED" />
            <InkSlider
              label="Motivation"
              hint="Drive to initiate and complete tasks — tracks anhedonia and executive function"
              value={d.motivation} onChange={v => set('motivation', v)}
              lo="Can't start anything" hi="Highly driven"
              color="#7C3AED" />
            <InkSlider
              label="Perceived Stress"
              hint="External pressure you're carrying today, separate from your mood"
              value={d.perceivedStress} onChange={v => set('perceivedStress', v)}
              lo="No pressure at all" hi="Crushing load"
              color="#7C3AED" />
          </AdvancedSection>
        )}
      </div>
    ),

    sleep: (
      <div>
        {/* Total hours — custom slider with hours display */}
        <div style={{ marginBottom: 28 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 2 }}>
            <label style={{ color: P.inkMid, fontSize: 12, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase' }}>Total Hours Asleep</label>
            <span style={{ color: clr.fg, fontSize: 26, fontWeight: 700, fontFamily: 'DM Serif Display', lineHeight: 1 }}>{d.sleepHours.toFixed(1)}h</span>
          </div>
          <p style={{ color: P.inkFaint, fontSize: 11, margin: '0 0 8px', lineHeight: 1.4 }}>Total time actually asleep — directly affects cognitive function and crash risk</p>
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

        <InkSlider
          label="Sleep Quality"
          hint="Subjective feel of how restorative the sleep was — the strongest predictor of your stability"
          value={d.sleepQuality} onChange={v => set('sleepQuality', v)}
          lo="Terrible — woke exhausted" hi="Excellent — fully rested"
          color={clr.fg} />

        <PaperNumInput
          label="Minutes Awake During Night"
          hint="Total time you were awake between sleep onset and final waking"
          value={d.timeAwakeMinutes} onChange={v => set('timeAwakeMinutes', v)}
          min={0} max={240} step={5} unit=" min" color={clr.fg} />

        <PaperSelect
          label="Night Awakenings"
          value={String(d.nightAwakenings)}
          onChange={v => set('nightAwakenings', parseInt(v))}
          options={[{value:'0',label:'None — slept through'},{value:'1',label:'Once'},{value:'2',label:'Twice'},{value:'3',label:'3 or more times'}]} />

        <PaperNumInput
          label="Sleep Latency"
          hint="How long it took you to fall asleep — high latency often signals pre-sleep anxiety or stimulant disruption"
          value={d.sleepLatencyMinutes} onChange={v => set('sleepLatencyMinutes', v)}
          min={0} max={180} step={5} unit=" min" color={clr.fg} />

        {advancedMode && (
          <AdvancedSection title="Sleep detail">
            <div style={{ marginBottom: 20 }}>
              <label style={{ color: '#5B21B6', fontSize: 12, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', display: 'block', marginBottom: 4 }}>Wake-Up Time</label>
              <p style={{ color: '#7C3AED', fontSize: 11, margin: '0 0 6px', lineHeight: 1.4 }}>Actual time you woke up — tracks circadian rhythm consistency over time</p>
              <input type="time" value={d.wakeUpTime} onChange={e => set('wakeUpTime', e.target.value)}
                style={{ width: '100%', padding: '10px 12px', border: `1px solid ${P.advBorder}`,
                  background: P.surface, color: P.ink, fontSize: 13, fontFamily: 'DM Sans',
                  outline: 'none', boxSizing: 'border-box' }} />
            </div>
          </AdvancedSection>
        )}
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
            <p style={{ color: P.inkFaint, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.07em', margin: '0 0 6px' }}>Taken today</p>
            <p style={{ color: P.inkFaint, fontSize: 11, margin: '0 0 12px', lineHeight: 1.4 }}>Log each medication and the time you took it — timing relative to your check-in helps correlate peak/trough effects with your scores</p>
            {Object.entries(d.meds).map(([key, info]) => (
              <div key={key} style={{ display: 'flex', alignItems: isMobile ? 'stretch' : 'center',
                flexDirection: isMobile ? 'column' : 'row',
                gap: isMobile ? 6 : 10, marginBottom: 10,
                border: `1px solid ${P.borderLight}`, background: P.surface,
                padding: isMobile ? '10px 12px' : '6px 12px' }}>
                <div style={{ flex: 1 }}>
                  <PaperToggle
                    label={`${(info.name || key).charAt(0).toUpperCase() + (info.name || key).slice(1)} ${info.dose ? `(${info.dose})` : ''}`}
                    checked={info.taken} onChange={v => set('meds', { ...d.meds, [key]: { ...info, taken: v } })} color={clr.fg} />
                </div>
                <div style={{ display: 'flex', flexDirection: isMobile ? 'row' : 'column',
                  alignItems: isMobile ? 'center' : 'flex-end', gap: isMobile ? 8 : 2 }}>
                  <label style={{ fontSize: 10, color: P.inkFaint, textTransform: 'uppercase',
                    letterSpacing: '0.06em', whiteSpace: 'nowrap' }}>Time Taken</label>
                  <input
                    type="time"
                    value={info.timeTaken || ''}
                    onChange={e => set('meds', { ...d.meds, [key]: { ...info, timeTaken: e.target.value } })}
                    style={{ fontSize: 13, padding: '6px 8px', border: `1px solid ${info.timeTaken ? P.border : P.borderLight}`,
                      background: P.bg, color: P.ink, fontFamily: 'inherit', outline: 'none',
                      width: isMobile ? '100%' : 110, flex: isMobile ? 1 : undefined }}
                  />
                </div>
              </div>
            ))}
          </div>
        )}

        <p style={{ color: P.inkFaint, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.07em', margin: '0 0 6px' }}>Caffeine today</p>
        <p style={{ color: P.inkFaint, fontSize: 11, margin: '0 0 12px', lineHeight: 1.4 }}>Caffeine directly affects sleep latency, anxiety, and your nervous system load score</p>
        {[
          { key: 'coffee', label: 'Coffee',       unit: 'cups', mg: 95,  note: '~95mg per cup (8oz)' },
          { key: 'tea',    label: 'Tea',           unit: 'cups', mg: 47,  note: '~47mg per cup' },
          { key: 'soda',   label: 'Soda',          unit: 'cans', mg: 35,  note: '~35mg per can' },
          { key: 'energy', label: 'Energy Drink',  unit: 'cans', mg: 150, note: '~150mg per can' },
        ].map(bev => {
          const val = d.caffeine[bev.key] || 0;
          return (
            <div key={bev.key} style={{ display: 'flex', alignItems: 'center', marginBottom: 10,
              border: `1px solid ${P.borderLight}`, background: P.surface }}>
              <div style={{ flex: 1, padding: '10px 14px', borderRight: `1px solid ${P.borderLight}` }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: P.ink }}>{bev.label}</div>
                <div style={{ fontSize: 11, color: P.inkFaint }}>{bev.note}</div>
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

        {advancedMode && (
          <AdvancedSection title="Substances & hydration">
            <div style={{ marginBottom: 20 }}>
              <p style={{ color: '#5B21B6', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em', margin: '0 0 6px' }}>Alcohol / Substances</p>
              <p style={{ color: '#7C3AED', fontSize: 11, margin: '0 0 12px', lineHeight: 1.4 }}>Alcohol disrupts sleep architecture and amplifies depressive slumps the next day. Log standard drinks.</p>
              <div style={{ display: 'flex', alignItems: 'center', border: `1px solid ${P.advBorder}`, background: P.surface, marginBottom: 10 }}>
                <div style={{ flex: 1, padding: '10px 14px', borderRight: `1px solid ${P.advBorder}` }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: P.ink }}>Standard Drinks</div>
                  <div style={{ fontSize: 11, color: P.inkFaint }}>Beer (12oz), wine (5oz), or 1.5oz spirit</div>
                </div>
                <button onClick={() => set('alcoholUnits', Math.max(0, d.alcoholUnits - 1))}
                  style={{ width: 40, height: 52, border: 'none', borderRight: `1px solid ${P.advBorder}`,
                    background: 'transparent', fontSize: 18, cursor: 'pointer', color: P.inkMid }}>−</button>
                <div style={{ width: 44, textAlign: 'center', fontSize: 16, fontWeight: 700, color: P.ink }}>{d.alcoholUnits}</div>
                <button onClick={() => set('alcoholUnits', d.alcoholUnits + 1)}
                  style={{ width: 40, height: 52, border: 'none', borderLeft: `1px solid ${P.advBorder}`,
                    background: 'transparent', fontSize: 18, cursor: 'pointer', color: P.inkMid }}>+</button>
              </div>
            </div>

            <PaperToggle
              label="Well hydrated today"
              hint="Dehydration causes immediate cognitive fog and fatigue — even mild dehydration impacts focus"
              checked={d.hydrated}
              onChange={v => set('hydrated', v)}
              color="#7C3AED" />
          </AdvancedSection>
        )}

        {advancedMode && (
          <AdvancedSection title="Lifestyle factors">
            <InkSlider
              label="Physical Activity"
              hint="Total exercise or intentional movement today — endorphin and cortisol effects are tracked"
              value={d.exerciseMinutes} onChange={v => set('exerciseMinutes', v)}
              min={0} max={120} step={5}
              lo="None" hi="2+ hours"
              color="#7C3AED" />
            <InkSlider
              label="Sunlight Exposure"
              hint="Time outdoors in daylight — tracks circadian alignment and vitamin D impact on mood"
              value={d.sunlightHours} onChange={v => set('sunlightHours', v)}
              min={0} max={8} step={0.5}
              lo="None" hi="8 hours"
              color="#7C3AED" />
            <InkSlider
              label="Screen Time"
              hint="Total hours on screens today — high usage correlates with disrupted sleep and cognitive strain"
              value={d.screenTimeHours} onChange={v => set('screenTimeHours', v)}
              min={0} max={16} step={0.5}
              lo="0h" hi="16h"
              color="#7C3AED" />
            <InkSlider
              label="Social Connection Quality"
              hint="How meaningful and positive were your social interactions today?"
              value={d.socialQuality} onChange={v => set('socialQuality', v)}
              min={1} max={5} step={1}
              lo="Isolated / negative" hi="Deeply connected"
              color="#7C3AED" />
            <InkSlider
              label="Workload / Task Friction"
              hint="How much operational pressure or friction did you experience today?"
              value={d.workloadFriction} onChange={v => set('workloadFriction', v)}
              min={1} max={5} step={1}
              lo="Smooth, low pressure" hi="Overwhelming friction"
              color="#7C3AED" />
          </AdvancedSection>
        )}

        {advancedMode && (
          <AdvancedSection title="Coping & interventions">
            <p style={{ color: '#7C3AED', fontSize: 12, margin: '0 0 12px', lineHeight: 1.5 }}>
              Tracking coping strategies over time helps identify what actually works for your nervous system.
            </p>
            <PaperToggle
              label="Breathing exercises"
              hint="Box breathing, 4-7-8, diaphragmatic — any intentional breathwork"
              checked={d.didBreathing} onChange={v => set('didBreathing', v)} color="#7C3AED" />
            <PaperToggle
              label="Meditation or mindfulness"
              hint="Formal sitting practice, guided meditation, or mindful awareness periods"
              checked={d.didMeditation} onChange={v => set('didMeditation', v)} color="#7C3AED" />
            <PaperToggle
              label="Physical movement or stretching"
              hint="Light walks, yoga, stretching — physical release of tension beyond formal exercise"
              checked={d.didMovement} onChange={v => set('didMovement', v)} color="#7C3AED" />
          </AdvancedSection>
        )}

        <Divider />
        <div>
          <label style={{ color: P.inkMid, fontSize: 12, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', display: 'block', marginBottom: 4 }}>Anything else?</label>
          <p style={{ color: P.inkFaint, fontSize: 11, margin: '0 0 7px', lineHeight: 1.4 }}>Life events, unexpected stressors, or anything that felt different about today</p>
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
            <p style={{ color: P.inkMid, fontSize: 13, margin: '0 0 10px', lineHeight: 1.65 }}>{aiInsight}</p>
            {checkinId && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ color: P.inkFaint, fontSize: 11, letterSpacing: '0.04em' }}>Helpful?</span>
                {['up', 'down'].map(r => (
                  <button key={r} onClick={() => {
                    const next = insightFeedback === r ? null : r;
                    setInsightFeedback(next);
                    if (next) fetch('/api/feedback', {
                      method: 'POST', credentials: 'same-origin',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ content_type: 'checkin', content_id: String(checkinId), rating: r }),
                    }).catch(() => {});
                  }} style={{
                    background: insightFeedback === r ? (r === 'up' ? '#dcfce7' : '#fee2e2') : 'none',
                    border: `1px solid ${insightFeedback === r ? (r === 'up' ? '#86efac' : '#fca5a5') : P.borderLight}`,
                    borderRadius: 4, padding: '2px 8px', cursor: 'pointer', fontSize: 15,
                    transition: 'background .15s, border-color .15s',
                  }}>{r === 'up' ? '👍' : '👎'}</button>
                ))}
              </div>
            )}
          </div>
        )}

        {advancedMode && (
          <div style={{ marginBottom: 16, padding: '12px 14px', background: P.advBg, border: `1px solid ${P.advBorder}` }}>
            <p style={{ color: '#5B21B6', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', margin: '0 0 4px' }}>Advanced data recorded</p>
            <p style={{ color: '#7C3AED', fontSize: 12, margin: 0, lineHeight: 1.5 }}>
              Mood nuance, lifestyle factors, and coping strategies saved. These build your longitudinal profile over time.
            </p>
          </div>
        )}

        {saveErr && <p style={{ color: P.ink, fontSize: 13, marginBottom: 10, border: `1px solid ${P.border}`, padding: '8px 12px' }}>{saveErr}</p>}
        {saved && (
          <div style={{ padding: '10px 14px', background: P.accentLight, border: `1px solid ${P.border}`, marginBottom: 12 }}>
            <p style={{ color: P.ink, fontSize: 13, margin: 0 }}>✓ Check-in saved — your trends and summary have been updated</p>
          </div>
        )}

        <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: 10 }}>
          <button onClick={handleSave} disabled={saving || saved}
            style={{ padding: '14px 18px', border: `1px solid ${P.border}`, cursor: 'pointer',
              background: saved ? P.inkMid : P.ink, color: '#fff', fontSize: 14, fontWeight: 600, fontFamily: 'DM Sans',
              opacity: saving ? 0.65 : 1 }}>
            {saving ? 'Saving…' : saved ? '✓ Saved' : 'Save to Profile'}
          </button>
          <button onClick={() => { setCheckinType(null); setStepIdx(0); setSaved(false); setSaveErr(''); setAiInsight(''); }}
            style={{ padding: '13px 18px', border: `1px solid ${P.border}`,
              background: P.surface, color: P.inkMid, fontSize: 13, cursor: 'pointer', fontFamily: 'DM Sans' }}>
            New Check-In
          </button>
        </div>
        <a href="/" style={{ display: 'block', textAlign: 'center', marginTop: 14, color: P.inkFaint, fontSize: 12, textDecoration: 'none' }}>← Back to dashboard</a>
      </div>
    ),
  };

  // ── View a previously completed check-in ───────────────────────────
  if (viewingCompleted) {
    return (
      <div style={{ minHeight: 'calc(100vh - 52px)', background: P.bg, display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: isMobile ? 'flex-start' : 'center',
        fontFamily: 'DM Sans', padding: isMobile ? '24px 16px 40px' : '40px 48px', overflowY: 'auto' }}>
        <div style={{ width: '100%', maxWidth: 560 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24 }}>
            <div style={{ width: 32, height: 32, borderRadius: '50%', background: '#22c55e', flexShrink: 0,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: '0 2px 8px rgba(34,197,94,0.35)' }}>
              <span style={{ color: '#fff', fontSize: 18, fontWeight: 700, lineHeight: 1 }}>✓</span>
            </div>
            <div>
              <div style={{ fontSize: isMobile ? 18 : 22, fontWeight: 400, color: P.ink, fontFamily: 'DM Serif Display', letterSpacing: '-0.01em' }}>
                {viewingCompleted.label} Check-In
              </div>
              <div style={{ fontSize: 12, color: '#16a34a', fontWeight: 600, marginTop: 1 }}>Completed today</div>
            </div>
          </div>

          {viewingCompleted.ai_insight ? (
            <div style={{ padding: '16px 18px', background: P.surface, border: `1px solid ${P.border}`, marginBottom: 16 }}>
              <p style={{ color: P.inkFaint, fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', margin: '0 0 8px' }}>AI Observation</p>
              <p style={{ color: P.inkMid, fontSize: 14, margin: '0 0 12px', lineHeight: 1.7 }}>{viewingCompleted.ai_insight}</p>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ color: P.inkFaint, fontSize: 11, letterSpacing: '0.04em' }}>Helpful?</span>
                {['up', 'down'].map(r => (
                  <button key={r} onClick={() => {
                    const next = insightFeedback === r ? null : r;
                    setInsightFeedback(next);
                    if (next && viewingCompleted.id) fetch('/api/feedback', {
                      method: 'POST', credentials: 'same-origin',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ content_type: 'checkin', content_id: String(viewingCompleted.id), rating: r }),
                    }).catch(() => {});
                  }} style={{
                    background: insightFeedback === r ? (r === 'up' ? '#dcfce7' : '#fee2e2') : 'none',
                    border: `1px solid ${insightFeedback === r ? (r === 'up' ? '#86efac' : '#fca5a5') : P.borderLight}`,
                    borderRadius: 4, padding: '2px 8px', cursor: 'pointer', fontSize: 15,
                    transition: 'background .15s, border-color .15s',
                  }}>{r === 'up' ? '👍' : '👎'}</button>
                ))}
              </div>
            </div>
          ) : (
            <div style={{ padding: '16px 18px', background: P.surface, border: `1px solid ${P.borderLight}`, marginBottom: 16 }}>
              <p style={{ color: P.inkFaint, fontSize: 13, margin: 0 }}>No AI observation was recorded for this check-in.</p>
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: 10 }}>
            <a href="/" style={{ display: 'block', padding: '14px 18px', border: `1px solid ${P.border}`,
              background: P.ink, color: '#fff', fontSize: 14, fontWeight: 600, textAlign: 'center',
              textDecoration: 'none', fontFamily: 'DM Sans' }}>← Back to dashboard</a>
            <button onClick={() => { setViewingCompleted(null); setInsightFeedback(null); }}
              style={{ padding: '13px 18px', border: `1px solid ${P.border}`,
                background: P.surface, color: P.inkMid, fontSize: 13, cursor: 'pointer', fontFamily: 'DM Sans' }}>
              New Check-In
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ── Type selection screen ───────────────────────────────────────────
  if (!checkinType) {
    return (
      <div style={{ minHeight: 'calc(100vh - 52px)', background: P.bg, display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: isMobile ? 'flex-start' : 'center',
        fontFamily: 'DM Sans', padding: isMobile ? '24px 16px 40px' : '40px 48px', overflowY: 'auto' }}>
        <h1 style={{ fontFamily: 'DM Serif Display', fontWeight: 400, fontSize: isMobile ? 26 : 32,
          color: P.ink, margin: '0 0 6px', letterSpacing: '-0.02em' }}>Daily Check-In</h1>
        <p style={{ color: P.inkFaint, fontSize: 14, margin: isMobile ? '0 0 20px' : '0 0 36px' }}>Select the type of check-in for today</p>
        <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row',
          width: '100%', maxWidth: 960, border: `1px solid ${P.border}` }}>
          {CHECKIN_TYPES.map((t, i) => {
            const done = completedToday.includes(t.id);
            const doneBg = '#f0faf4';
            const isLast = i === CHECKIN_TYPES.length - 1;
            return (
              <button key={t.id} onClick={() => {
                if (done && t.id !== 'on_demand') {
                  setInsightFeedback(null);
                  setViewingCompleted({ type: t.id, label: t.label, ...(completedDetails[t.id] || {}) });
                } else {
                  setCheckinType(t.id);
                }
              }}
                style={{ flex: 1, padding: isMobile ? '18px 16px' : '28px 24px', background: done ? doneBg : P.surface,
                  border: 'none',
                  borderRight: isMobile ? 'none' : (i < 3 ? `1px solid ${P.border}` : 'none'),
                  borderBottom: isMobile ? (isLast ? 'none' : `1px solid ${P.border}`) : 'none',
                  cursor: 'pointer', textAlign: 'left', fontFamily: 'DM Sans',
                  transition: 'background 0.12s', position: 'relative' }}
                onMouseEnter={e => e.currentTarget.style.background = done ? '#e2f5ea' : P.accentLight}
                onMouseLeave={e => e.currentTarget.style.background = done ? doneBg : P.surface}>
                {done && (
                  <div style={{ position: 'absolute', top: 14, right: 16,
                    width: 28, height: 28, borderRadius: '50%',
                    background: '#22c55e', display: 'flex', alignItems: 'center', justifyContent: 'center',
                    boxShadow: '0 2px 8px rgba(34,197,94,0.35)' }}>
                    <span style={{ color: '#fff', fontSize: 16, fontWeight: 700, lineHeight: 1 }}>✓</span>
                  </div>
                )}
                <div style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em',
                  color: done ? '#16a34a' : P.inkFaint, marginBottom: 6 }}>
                  {done ? 'Completed today' : t.tag}
                </div>
                <div style={{ fontSize: isMobile ? 15 : 16, fontWeight: 600, color: P.ink, marginBottom: 4 }}>{t.label}</div>
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
    <div style={{ height: isMobile ? 'auto' : 'calc(100vh - 52px)', minHeight: isMobile ? 'calc(100vh - 52px)' : 'auto',
      background: P.bg, display: 'flex', flexDirection: 'column', fontFamily: 'DM Sans' }}>

      {/* Step progress bar */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: isMobile ? '0 14px' : '0 28px', borderBottom: `1px solid ${P.borderLight}`,
        background: P.surface, height: 40, flexShrink: 0 }}>
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
            {advancedMode && <span style={{ color: '#7C3AED', marginLeft: 6 }}>· Advanced</span>}
            {stepIdx > 0 && stepIdx < FLOW.length - 1 ? ` · ${stepIdx} of ${FLOW.length - 2}` : ''}
          </span>
        </div>
        {/* Caffeine running total — always visible */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 12px',
          border: `1px solid ${sc.caffeineMg > 400 ? P.border : P.borderLight}`,
          background: sc.caffeineMg > 400 ? P.accentLight : 'transparent' }}>
          <span style={{ fontSize: 11, color: P.inkFaint, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Caffeine</span>
          <span style={{ fontSize: 13, fontWeight: 700, color: sc.caffeineMg > 400 ? P.ink : P.inkMid }}>{sc.caffeineMg}mg</span>
        </div>
      </div>

      {/* Main split layout */}
      <div style={{ flex: 1, display: isMobile ? 'flex' : 'grid',
        flexDirection: isMobile ? 'column' : undefined,
        gridTemplateColumns: isMobile ? undefined : '340px 1fr',
        overflow: isMobile ? 'auto' : 'hidden' }}>

        {/* Left panel — context (desktop only) */}
        {!isMobile && (
          <div style={{ padding: '36px 32px', borderRight: `1px solid ${P.borderLight}`, background: P.surface, overflowY: 'auto' }}>
            {leftContent[stepId]}
            {stepIdx > 0 && (
              <button onClick={back}
                style={{ marginTop: 28, padding: '9px 16px', border: `1px solid ${P.borderLight}`,
                  background: 'transparent', color: P.inkFaint, fontSize: 12, cursor: 'pointer', fontFamily: 'DM Sans' }}>
                ← Back
              </button>
            )}
          </div>
        )}

        {/* Right panel — input */}
        <div style={{ padding: isMobile ? '20px 16px 48px' : '36px 36px 36px',
          overflowY: isMobile ? 'visible' : 'auto', background: P.bg, flex: isMobile ? 1 : undefined }}>
          <div style={{ maxWidth: isMobile ? '100%' : 520 }}>
            {rightContent[stepId]}
            {stepIdx < FLOW.length - 1 && (
              <button onClick={next}
                style={{ marginTop: 24, width: '100%', padding: '14px 20px', border: `1px solid ${P.border}`,
                  background: P.ink, color: '#fff', fontSize: 14, fontWeight: 600, cursor: 'pointer', fontFamily: 'DM Sans' }}>
                Continue →
              </button>
            )}
            {isMobile && stepIdx > 0 && (
              <button onClick={back}
                style={{ marginTop: 10, width: '100%', padding: '12px 20px', border: `1px solid ${P.borderLight}`,
                  background: 'transparent', color: P.inkFaint, fontSize: 13, cursor: 'pointer', fontFamily: 'DM Sans' }}>
                ← Back
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
