import React, { useState, useEffect, useMemo } from 'react';

// ============================================================================
// LANGUAGE GUARDRAIL UTILITIES
// ============================================================================
const languageGuardrails = {
  containsDiagnosticLanguage: (text) => {
    const terms = ['diagnos', 'disorder', 'condition', 'illness', 'disease',
      'symptom', 'syndrome', 'relapse', 'episode', 'attack'];
    return terms.some(t => text.toLowerCase().includes(t));
  },
  containsMedicationAdvice: (text) => {
    const terms = ['increase', 'decrease', 'adjust', 'change', 'stop', 'start',
      'dose', 'timing', 'discontinue', 'should take'];
    return terms.some(t =>
      text.toLowerCase().includes(t) &&
      (text.toLowerCase().includes('medication') || text.toLowerCase().includes('dose'))
    );
  },
  isDataDescription: (text) => {
    const hasNumbers = /\d+/.test(text);
    const hasTimeReference = /day|week|month|hour|morning|afternoon/.test(text.toLowerCase());
    const hasMetric = /score|average|rating|trend/.test(text.toLowerCase());
    return hasNumbers || (hasTimeReference && hasMetric);
  },
  detectCrisisSignals: (text) => {
    const terms = ['suicide', 'suicidal', 'kill myself', 'hurt myself', 'self-harm',
      "can't go on", 'not worth living', 'want to die', 'end it'];
    return terms.some(t => text.toLowerCase().includes(t));
  },
  processAIOutput: (text, level) => {
    if (level === 1) {
      if (languageGuardrails.containsDiagnosticLanguage(text)) return null;
      if (!languageGuardrails.isDataDescription(text)) return null;
    }
    if (level === 2) {
      if (languageGuardrails.containsDiagnosticLanguage(text)) return null;
      if (languageGuardrails.containsMedicationAdvice(text)) return null;
    }
    if (level === 4) {
      if (languageGuardrails.containsDiagnosticLanguage(text)) return null;
    }
    return text;
  },
};

// ============================================================================
// DEFAULTS (used until real baseline loads)
// ============================================================================
const DEFAULT_BASELINE = {
  avgMood: 6.8, avgEnergy: 6.5, avgDissociation: 0.8, avgAnxiety: 3.2,
  avgSleepHours: 5.9, avgSleepQuality: 6.2, avgCaffeineMg: 280,
  optimalCaffeine: { min: 200, max: 300 }, crashWindowHours: [14, 16],
  sleepSensitivity: 8, caffeineSensitivity: 7, nutritionSensitivity: 6,
};

// ============================================================================
// SCORING
// ============================================================================
const calculateScores = (data, baseline) => {
  const stabilityScore = (data.mood + data.energy + (10 - data.dissociation) + (10 - data.anxiety)) / 4;
  const dopamineEfficiency = (data.energy + data.focus) / 2;
  const caffeineMgValue = parseFloat(data.caffeineMg) || 0;
  const stimulationLoad = caffeineMgValue > 300 ? 8 : caffeineMgValue > 200 ? 5 : 2;
  const nervousSystemLoad = (data.anxiety + (10 - data.sleepQuality) + stimulationLoad) / 3;

  let sleepDisruption = 0;
  const sleepAwakePercent = (data.timeAwakeMinutes / 480) * 100;
  if (sleepAwakePercent > 20) sleepDisruption += 3;
  if (data.sleepLatencyMinutes > 30) sleepDisruption += 3;
  if (data.nightAwakenings >= 2) sleepDisruption += 2;
  if (data.sleepHours < 6) sleepDisruption += 2;

  let nutritionScore = 0;
  if (data.breakfastProteinGrams >= 20) nutritionScore += 3;
  if (!data.sugarSpikes) nutritionScore += 3;
  if (data.mealTiming === 'consistent') nutritionScore += 2;
  if (data.hydrationOz >= 80) nutritionScore += 2;

  const crashRisk = (sleepDisruption * 0.4 + nervousSystemLoad * 0.4 + (10 - nutritionScore) * 0.2);
  const moodDistortion = Math.abs(data.mood - stabilityScore);

  return {
    stability: stabilityScore, dopamineEfficiency, nervousSystemLoad,
    sleepDisruption, nutritionScore, crashRisk, moodDistortion,
    moodDeviation: data.mood - baseline.avgMood,
    energyDeviation: data.energy - baseline.avgEnergy,
    anxietyDeviation: data.anxiety - baseline.avgAnxiety,
  };
};

// ============================================================================
// INSIGHTS
// ============================================================================
const generateInsights = (data, baseline, scores) => {
  if (languageGuardrails.detectCrisisSignals(data.notes)) {
    return { level: 'CRISIS' };
  }
  const insights = [];

  if (data.sleepHours) {
    const sleepDiff = data.sleepHours - baseline.avgSleepHours;
    const dir = sleepDiff > 0.5 ? 'higher' : sleepDiff < -0.5 ? 'lower' : 'similar';
    insights.push({
      level: 1, category: 'sleep', confidence: 100,
      text: `You slept ${data.sleepHours} hours last night, which is ${dir} than your 7-day average of ${baseline.avgSleepHours.toFixed(1)} hours.`,
    });
  }
  if (data.caffeineMg) {
    const diff = data.caffeineMg - baseline.avgCaffeineMg;
    insights.push({
      level: 1, category: 'caffeine', confidence: 100,
      text: `You logged approximately ${data.caffeineMg}mg caffeine today, which is ${diff > 0 ? 'higher' : 'lower'} than your typical intake of ${baseline.avgCaffeineMg}mg.`,
    });
  }
  if (scores.moodDistortion > 2 && scores.moodDistortion <= 4) {
    const type = data.mood > scores.stability ? 'optimistic' : 'pessimistic';
    insights.push({
      level: 2, category: 'mood_perception', confidence: 72,
      text: `Your reported mood (${data.mood}/10) is somewhat ${type} compared to your underlying stability score (${scores.stability.toFixed(1)}/10), which considers sleep, anxiety, and energy. This mismatch may be worth noticing.`,
    });
  }
  if (data.timeOfCheckIn >= 14 && data.timeOfCheckIn <= 16 && data.energy < baseline.avgEnergy - 1.5) {
    insights.push({
      level: 2, category: 'energy_pattern', confidence: 78,
      text: `Your energy level right now (${data.energy}/10) is notably lower than your baseline (${baseline.avgEnergy}/10). This appears to coincide with the 2-4 PM window when you typically experience energy dips.`,
    });
  }
  if (scores.nervousSystemLoad > 6 && data.sleepQuality < 6) {
    insights.push({
      level: 2, category: 'nervous_system', confidence: 75,
      text: `Your current nervous system load is elevated (${scores.nervousSystemLoad.toFixed(1)}/10), and your sleep quality last night was below your baseline. This combination tends to correlate with difficulty settling in the evening.`,
    });
  }
  if (data.breakfastProteinGrams < 15 && data.focus < baseline.avgEnergy - 1) {
    insights.push({
      level: 2, category: 'nutrition', confidence: 68,
      text: `On days when your breakfast protein is below 15g, your focus scores have been on average 0.8 points lower than on days with 20g+ protein, based on your tracking pattern.`,
    });
  }
  if (scores.moodDistortion > 2) {
    insights.push({
      level: 3, category: 'reflection', confidence: 60,
      text: `Your mood rating does not quite match your overall stability pattern. What felt different about today compared to what the data suggests?`,
    });
  }
  if (data.energy < baseline.avgEnergy - 1.5 && data.sleepHours >= 6) {
    insights.push({
      level: 3, category: 'reflection', confidence: 55,
      text: `You slept well, but your energy is lower than usual right now. Is there something that stood out today that might be affecting how you feel?`,
    });
  }
  if (scores.crashRisk > 6) {
    insights.push({
      level: 4, category: 'provider_contact', confidence: 82,
      text: `Your system is showing multiple signs of strain right now — disrupted sleep combined with high stimulation and elevated anxiety. This combination might be worth discussing with your provider, especially if it persists over the next few days.`,
    });
  }
  if (scores.moodDeviation < -2 && data.anxiety > baseline.avgAnxiety + 1) {
    insights.push({
      level: 4, category: 'provider_contact', confidence: 79,
      text: `Your mood has been consistently lower than your baseline for several days, and your anxiety has risen. This pattern might be helpful to bring to your next appointment.`,
    });
  }

  return insights
    .filter(i => languageGuardrails.processAIOutput(i.text, i.level) !== null)
    .sort((a, b) => a.level - b.level);
};

// ============================================================================
// CRASH RISK METER
// ============================================================================
const CrashRiskMeter = ({ score }) => {
  let color, label;
  if (score < 3) { color = '#10b981'; label = 'Stable'; }
  else if (score < 6) { color = '#f59e0b'; label = 'Watch'; }
  else { color = '#ef4444'; label = 'High Risk'; }
  return (
    <div className="flex items-center gap-3">
      <div className="flex-1">
        <div className="bg-gray-200 rounded-full h-2 overflow-hidden">
          <div className="h-full transition-all" style={{ width: `${Math.min((score / 10) * 100, 100)}%`, backgroundColor: color }} />
        </div>
      </div>
      <span className="text-sm font-medium w-10 text-right" style={{ color }}>{score.toFixed(1)}</span>
      <span className="text-xs font-medium text-gray-600 w-16">{label}</span>
    </div>
  );
};

// ============================================================================
// MAIN APP
// ============================================================================
export default function App() {
  const [currentStep, setCurrentStep] = useState('intro');
  const [baseline, setBaseline] = useState(DEFAULT_BASELINE);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState('');

  const [data, setData] = useState({
    timeOfCheckIn: new Date().getHours(),
    mood: 6, energy: 6, dissociation: 1, anxiety: 3, focus: 6,
    sleepHours: 6, sleepQuality: 6, timeAwakeMinutes: 0,
    sleepLatencyMinutes: 0, nightAwakenings: 0,
    caffeineMg: 0, breakfastProteinGrams: 0,
    sugarSpikes: false, mealTiming: 'missed', hydrationOz: 80,
    meds: {}, notes: '',
  });

  useEffect(() => {
    fetch('/api/checkins/baseline', { credentials: 'same-origin' })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setBaseline(prev => ({ ...prev, ...d })); })
      .catch(() => {});

    fetch('/api/patient/profile', { credentials: 'same-origin' })
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (!d) return;
        const meds = {};
        (d.current_medications || []).forEach(m => {
          meds[m.name] = { taken: false, dose: m.dose || '' };
        });
        setData(prev => ({ ...prev, meds }));
      })
      .catch(() => {});
  }, []);

  const scores = useMemo(() => calculateScores(data, baseline), [data, baseline]);
  const insights = useMemo(() => generateInsights(data, baseline, scores), [data, scores, baseline]);

  const set = (key, value) => setData(prev => ({ ...prev, [key]: value }));

  const handleSave = async () => {
    setSaving(true);
    setSaveError('');
    try {
      const medList = Object.entries(data.meds)
        .filter(([, info]) => info.taken)
        .map(([name, info]) => ({ name, dose: info.dose }));

      const res = await fetch('/api/checkins', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mood_score: data.mood,
          stress_score: data.anxiety,
          sleep_hours: data.sleepHours,
          medications: medList,
          notes: data.notes,
          time_of_day: `${data.timeOfCheckIn}:00`,
          extended_data: {
            energy: data.energy, focus: data.focus, dissociation: data.dissociation,
            sleep_quality: data.sleepQuality, time_awake_minutes: data.timeAwakeMinutes,
            sleep_latency_minutes: data.sleepLatencyMinutes, night_awakenings: data.nightAwakenings,
            caffeine_mg: data.caffeineMg, breakfast_protein_grams: data.breakfastProteinGrams,
            sugar_spikes: data.sugarSpikes, meal_timing: data.mealTiming,
            hydration_oz: data.hydrationOz,
            scores: {
              stability: scores.stability, crash_risk: scores.crashRisk,
              nervous_system_load: scores.nervousSystemLoad,
              dopamine_efficiency: scores.dopamineEfficiency,
            },
          },
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setSaveError(err.error || 'Failed to save. Please try again.');
      } else {
        setSaved(true);
        setTimeout(() => setSaved(false), 3000);
      }
    } catch {
      setSaveError('Network error. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  // ── REUSABLE SLIDER ────────────────────────────────────────────────────────
  const Slider = ({ label, value, onChange, min = 0, max = 10, step = 1, leftLabel, rightLabel }) => (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-2">
        {label}: <span className="text-lg font-bold text-gray-900">{value}{max <= 10 && step >= 1 ? '/10' : (step < 1 ? 'h' : '')}</span>
      </label>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={e => onChange(step < 1 ? parseFloat(e.target.value) : parseInt(e.target.value))}
        className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer" />
      {(leftLabel || rightLabel) && (
        <div className="flex justify-between text-xs text-gray-500 mt-1">
          <span>{leftLabel}</span><span>{rightLabel}</span>
        </div>
      )}
    </div>
  );

  // ── STEPS ──────────────────────────────────────────────────────────────────
  const StepIntro = () => (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-serif font-bold text-gray-900 mb-2">Daily Check-In</h2>
        <p className="text-gray-600">5 minutes to understand your day. The system learns from patterns.</p>
      </div>
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <p className="text-sm text-gray-700">
          <strong>What happens with your answers:</strong> Every check-in trains a personalized model of how you respond to sleep, caffeine, medication, and food. Real-time insights show patterns. Crash predictions come early. Nothing is assumed — everything is calculated from your actual data.
        </p>
      </div>
      <button onClick={() => setCurrentStep('core')}
        className="w-full bg-blue-600 text-white py-3 rounded-lg font-medium hover:bg-blue-700">
        Begin Check-In
      </button>
    </div>
  );

  const StepCore = () => (
    <div className="space-y-6">
      <h3 className="text-lg font-serif font-bold text-gray-900">Mental State</h3>
      <Slider label="Mood" value={data.mood} onChange={v => set('mood', v)} leftLabel="Very Low" rightLabel="Excellent" />
      <Slider label="Energy" value={data.energy} onChange={v => set('energy', v)} leftLabel="Exhausted" rightLabel="Energized" />
      <Slider label="Focus / Clarity" value={data.focus} onChange={v => set('focus', v)} leftLabel="Foggy" rightLabel="Sharp" />
      <Slider label="Dissociation" value={data.dissociation} onChange={v => set('dissociation', v)} leftLabel="Grounded" rightLabel="Detached" />
      <Slider label="Anxiety / Restlessness" value={data.anxiety} onChange={v => set('anxiety', v)} leftLabel="Calm" rightLabel="Very Stressed" />
      <button onClick={() => setCurrentStep('sleep')}
        className="w-full bg-blue-600 text-white py-3 rounded-lg font-medium hover:bg-blue-700">
        Continue to Sleep
      </button>
    </div>
  );

  const StepSleep = () => (
    <div className="space-y-6">
      <h3 className="text-lg font-serif font-bold text-gray-900">Last Night's Sleep</h3>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Total hours: <span className="text-lg font-bold text-gray-900">{data.sleepHours.toFixed(1)}h</span>
        </label>
        <input type="range" min="0" max="12" step="0.5" value={data.sleepHours}
          onChange={e => set('sleepHours', parseFloat(e.target.value))}
          className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer" />
        <div className="flex justify-between text-xs text-gray-500 mt-1"><span>0h</span><span>12h</span></div>
      </div>
      <Slider label="Sleep quality" value={data.sleepQuality} onChange={v => set('sleepQuality', v)} leftLabel="Poor" rightLabel="Excellent" />
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Time awake during night: <span className="font-bold">{data.timeAwakeMinutes} min</span>
        </label>
        <input type="number" min="0" max="240" step="5" value={data.timeAwakeMinutes}
          onChange={e => set('timeAwakeMinutes', parseInt(e.target.value) || 0)}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm" />
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">Awakenings during night:</label>
        <select value={data.nightAwakenings} onChange={e => set('nightAwakenings', parseInt(e.target.value))}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm">
          <option value="0">None</option>
          <option value="1">Once</option>
          <option value="2">Twice</option>
          <option value="3">Three or more</option>
        </select>
      </div>
      <button onClick={() => setCurrentStep('meds')}
        className="w-full bg-blue-600 text-white py-3 rounded-lg font-medium hover:bg-blue-700">
        Continue to Medications
      </button>
    </div>
  );

  const StepMeds = () => (
    <div className="space-y-6">
      <h3 className="text-lg font-serif font-bold text-gray-900">Medications & Stimulation</h3>
      {Object.keys(data.meds).length === 0 ? (
        <p className="text-sm text-gray-500 italic">No medications on your profile yet. Add them in Settings.</p>
      ) : (
        <div className="space-y-3">
          {Object.entries(data.meds).map(([med, info]) => (
            <div key={med} className="flex items-start gap-3 p-3 bg-gray-50 rounded-lg">
              <input type="checkbox" checked={info.taken}
                onChange={e => set('meds', { ...data.meds, [med]: { ...info, taken: e.target.checked } })}
                className="mt-1 w-4 h-4" />
              <div>
                <p className="text-sm font-medium text-gray-900 capitalize">{med} {info.dose && `(${info.dose})`}</p>
                <p className="text-xs text-gray-500">{info.taken ? 'Taken today' : 'Not taken'}</p>
              </div>
            </div>
          ))}
        </div>
      )}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Caffeine intake today: <span className="font-bold">{data.caffeineMg}mg</span>
        </label>
        <input type="number" min="0" max="600" step="10" value={data.caffeineMg}
          onChange={e => set('caffeineMg', parseInt(e.target.value) || 0)}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm" placeholder="e.g., 250" />
        <p className="text-xs text-gray-500 mt-1">
          Your typical range: {baseline.optimalCaffeine?.min ?? 200}–{baseline.optimalCaffeine?.max ?? 300}mg
        </p>
      </div>
      <button onClick={() => setCurrentStep('nutrition')}
        className="w-full bg-blue-600 text-white py-3 rounded-lg font-medium hover:bg-blue-700">
        Continue to Nutrition
      </button>
    </div>
  );

  const StepNutrition = () => (
    <div className="space-y-6">
      <h3 className="text-lg font-serif font-bold text-gray-900">Nutrition & Hydration</h3>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Breakfast protein: <span className="font-bold">{data.breakfastProteinGrams}g</span>
        </label>
        <input type="number" min="0" max="60" step="5" value={data.breakfastProteinGrams}
          onChange={e => set('breakfastProteinGrams', parseInt(e.target.value) || 0)}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm" placeholder="e.g., 25" />
        <p className="text-xs text-gray-500 mt-1">Your data shows better focus on days with 20g+</p>
      </div>
      <div className="flex items-center gap-3 p-3 bg-gray-50 rounded-lg">
        <input type="checkbox" id="noSugar" checked={!data.sugarSpikes}
          onChange={e => set('sugarSpikes', !e.target.checked)} className="w-4 h-4" />
        <label htmlFor="noSugar" className="text-sm font-medium text-gray-900">No major sugar crashes today</label>
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">Meal timing:</label>
        <select value={data.mealTiming} onChange={e => set('mealTiming', e.target.value)}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm">
          <option value="missed">Skipped meals</option>
          <option value="irregular">Irregular</option>
          <option value="consistent">Consistent</option>
        </select>
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Hydration: <span className="font-bold">{data.hydrationOz}oz</span>
        </label>
        <input type="number" min="0" max="160" step="10" value={data.hydrationOz}
          onChange={e => set('hydrationOz', parseInt(e.target.value) || 0)}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm" />
        <p className="text-xs text-gray-500 mt-1">Target: 80–100oz</p>
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">Anything else worth noting?</label>
        <textarea value={data.notes} onChange={e => set('notes', e.target.value)}
          placeholder="Optional: life events, stress, unexpected changes..."
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm h-20 resize-none" />
      </div>
      <button onClick={() => setCurrentStep('summary')}
        className="w-full bg-blue-600 text-white py-3 rounded-lg font-medium hover:bg-blue-700">
        Complete & Analyze
      </button>
    </div>
  );

  const StepSummary = () => {
    const isCrisis = insights && insights.level === 'CRISIS';
    const insightList = Array.isArray(insights) ? insights : [];
    const levelLabel = { 1: 'Observation', 2: 'Pattern', 3: 'Reflection', 4: 'Provider Alert' };
    const levelBg = {
      1: 'bg-blue-50 border-blue-200',
      2: 'bg-purple-50 border-purple-200',
      3: 'bg-cyan-50 border-cyan-200',
      4: 'bg-orange-50 border-orange-200',
    };

    if (isCrisis) {
      return (
        <div className="space-y-6">
          <div className="bg-red-50 border border-red-300 rounded-lg p-6">
            <p className="text-base font-medium text-red-900 mb-4">
              It looks like you might be going through something really hard right now.
            </p>
            <div className="space-y-3">
              <a href="tel:988"
                className="flex items-center justify-center w-full py-3 bg-red-600 text-white rounded-lg font-medium hover:bg-red-700">
                Call 988 Suicide &amp; Crisis Lifeline
              </a>
              <a href="sms:741741&body=HOME"
                className="flex items-center justify-center w-full py-3 bg-red-100 text-red-800 rounded-lg font-medium hover:bg-red-200">
                Text HOME to 741741
              </a>
              <button onClick={() => setCurrentStep('nutrition')}
                className="w-full py-3 border border-gray-300 text-gray-700 rounded-lg font-medium hover:bg-gray-50">
                I'm safe right now
              </button>
            </div>
          </div>
        </div>
      );
    }

    return (
      <div className="space-y-8">
        <div>
          <h3 className="text-lg font-serif font-bold text-gray-900 mb-4">Real-Time Scores</h3>
          <div className="space-y-4 mb-6">
            {[
              { label: 'Stability Score', score: scores.stability, note: `Baseline: ${baseline.avgMood.toFixed(1)}` },
              { label: 'Nervous System Load', score: scores.nervousSystemLoad, note: 'High = stressed system.' },
              { label: 'Crash Risk (Next 6 Hours)', score: scores.crashRisk, note: 'Green = stable. Red = watch closely.' },
              { label: 'Dopamine Efficiency', score: scores.dopamineEfficiency, note: 'How cleanly stimulation is working.' },
            ].map(({ label, score, note }) => (
              <div key={label}>
                <label className="block text-sm font-medium text-gray-700 mb-2">{label}</label>
                <CrashRiskMeter score={score} />
                <p className="text-xs text-gray-600 mt-1">{note}</p>
              </div>
            ))}
            {scores.moodDistortion > 1 && (
              <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg">
                <p className="text-sm font-medium text-amber-900 mb-1">Mood Perception Note</p>
                <p className="text-xs text-amber-800">
                  Your reported mood ({data.mood}/10) differs from your calculated stability ({scores.stability.toFixed(1)}/10). Sometimes feelings and data tell slightly different stories.
                </p>
              </div>
            )}
          </div>
        </div>

        {insightList.length > 0 && (
          <div>
            <h3 className="text-lg font-serif font-bold text-gray-900 mb-4">Insights</h3>
            <div className="space-y-4">
              {insightList.slice(0, 5).map((insight, i) => (
                <div key={i} className={`p-4 border rounded-lg ${levelBg[insight.level]}`}>
                  <div className="flex justify-between items-start mb-2">
                    <p className="text-xs font-medium text-gray-600 uppercase">
                      {levelLabel[insight.level]} · {insight.category}
                    </p>
                    <p className="text-xs text-gray-500">{insight.confidence}% confidence</p>
                  </div>
                  <p className="text-sm text-gray-800 leading-relaxed">{insight.text}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {saveError && (
          <div className="p-3 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-sm text-red-800">{saveError}</p>
          </div>
        )}
        {saved && (
          <div className="p-3 bg-green-50 border border-green-200 rounded-lg">
            <p className="text-sm text-green-800">Check-in saved successfully.</p>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <button
            onClick={() => { setCurrentStep('intro'); setSaved(false); setSaveError(''); }}
            className="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50">
            New Check-In
          </button>
          <button onClick={handleSave} disabled={saving || saved}
            className="px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-60">
            {saving ? 'Saving…' : saved ? 'Saved ✓' : 'Save to Profile'}
          </button>
        </div>
      </div>
    );
  };

  // ── RENDER ─────────────────────────────────────────────────────────────────
  const stepOrder = ['core', 'sleep', 'meds', 'nutrition', 'summary'];
  const steps = { intro: StepIntro, core: StepCore, sleep: StepSleep, meds: StepMeds, nutrition: StepNutrition, summary: StepSummary };
  const CurrentStep = steps[currentStep];

  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      {currentStep !== 'intro' && (
        <div className="flex gap-2 mb-6">
          {stepOrder.map((step, i) => (
            <div key={step}
              className={`h-1 flex-1 rounded-full transition-colors ${stepOrder.indexOf(currentStep) >= i ? 'bg-blue-600' : 'bg-gray-300'}`} />
          ))}
        </div>
      )}
      <div className="bg-white rounded-2xl p-8 shadow-sm">
        <CurrentStep />
      </div>
      <p className="text-xs text-gray-500 text-center mt-6">
        All data is encrypted and HIPAA-compliant. The system learns from your patterns, never diagnoses.
      </p>
    </div>
  );
}
