import { colors, fonts } from './tokens';

/**
 * SliderInput — canonical check-in slider (mood, energy, focus, anxiety, etc).
 *
 * Props:
 *   label:     string
 *   context?:  string  (the question prompt, e.g. "How are you feeling emotionally right now?")
 *   value:     number
 *   onChange:  (n) => void
 *   min?:      number  (default 0)
 *   max?:      number  (default 10)
 *   step?:     number  (default 1)
 *   loLabel?:  string  (default "Very low")
 *   hiLabel?:  string  (default "Very high")
 *   color?:    string  (override accent — defaults to teal-600)
 */
export default function SliderInput({
  label,
  context,
  value,
  onChange,
  min = 0,
  max = 10,
  step = 1,
  loLabel = 'Very low',
  hiLabel = 'Very high',
  color = colors.teal[600],
  style,
}) {
  const displayVal = step < 1 ? value.toFixed(1) : value;

  return (
    <div style={{ marginBottom: 18, fontFamily: fonts.body, ...style }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
        <span style={{ fontSize: 13, fontWeight: 500, color: colors.text.primary }}>{label}</span>
        <span style={{ fontFamily: fonts.mono, fontSize: 15, fontWeight: 500, color }}>{displayVal}</span>
      </div>
      {context && (
        <div style={{ fontSize: 11, color: colors.text.secondary, marginBottom: 6 }}>{context}</div>
      )}
      <input
        type="range"
        className="cs-range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(step < 1 ? parseFloat(e.target.value) : parseInt(e.target.value, 10))}
        style={{ width: '100%' }}
      />
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
        <span style={{ fontSize: 10, color: colors.text.tertiary }}>{loLabel}</span>
        <span style={{ fontSize: 10, color: colors.text.tertiary }}>{hiLabel}</span>
      </div>
    </div>
  );
}
