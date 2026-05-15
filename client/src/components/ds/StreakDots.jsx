import { colors, fonts } from './tokens';

/**
 * StreakDots — N-day check-in streak indicator.
 *
 * Props:
 *   days:   Array<'logged' | 'missed' | 'skipped'>
 *   legend? : boolean (default true)
 *   size?:  number    (dot diameter, default 6)
 */
const DOT_COLOR = {
  logged:  colors.teal[600],
  missed:  colors.red[400],
  skipped: colors.gray[200],
};

export default function StreakDots({ days = [], legend = true, size = 6, style }) {
  return (
    <div style={{ fontFamily: fonts.body, ...style }}>
      <div style={{ display: 'flex', gap: 3, alignItems: 'center' }}>
        {days.map((s, i) => (
          <div key={i} style={{
            width: size,
            height: size,
            borderRadius: '50%',
            background: DOT_COLOR[s] || colors.gray[200],
          }} />
        ))}
      </div>
      {legend && (
        <div style={{ display: 'flex', gap: 10, marginTop: 4 }}>
          {['logged', 'missed', 'skipped'].map((k) => (
            <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
              <div style={{ width: size, height: size, borderRadius: '50%', background: DOT_COLOR[k] }} />
              <span style={{ fontSize: 10, color: colors.text.secondary }}>{k}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
