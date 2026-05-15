import { colors, fonts } from './tokens';

/**
 * ScoreHero — the stability score "payoff" component (P-06 hero).
 *
 * Props:
 *   value:    number  (0–10, displayed to 1 decimal)
 *   max?:     number  (default 10)
 *   label?:   string  (default "Stability score")
 *   delta?:   string  (e.g. "+0.3 vs 7-day avg (6.8→7.8)")
 *   color?:   string  (override the value/bar color)
 */
export default function ScoreHero({
  value,
  max = 10,
  label = 'Stability score',
  delta,
  color = colors.teal[600],
  style,
}) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  const displayVal = typeof value === 'number' ? value.toFixed(1) : '—';

  return (
    <div style={{ textAlign: 'center', fontFamily: fonts.body, ...style }}>
      <div style={{
        fontSize: 11,
        fontWeight: 500,
        letterSpacing: '0.08em',
        textTransform: 'uppercase',
        color: colors.text.secondary,
        marginBottom: 6,
      }}>
        {label}
      </div>
      <div style={{
        fontFamily: fonts.display,
        fontSize: 64,
        lineHeight: 1,
        color,
      }}>
        {displayVal}
      </div>
      {delta && (
        <div style={{
          fontSize: 12,
          color: colors.text.secondary,
          marginTop: 6,
          fontFamily: fonts.mono,
        }}>
          {delta}
        </div>
      )}
      <div style={{
        height: 3,
        background: colors.bg.tertiary,
        borderRadius: 2,
        overflow: 'hidden',
        marginTop: 8,
        width: '80%',
        marginLeft: 'auto',
        marginRight: 'auto',
      }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 2 }} />
      </div>
    </div>
  );
}
