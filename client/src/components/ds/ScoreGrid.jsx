import { colors, fonts, radii } from './tokens';

/**
 * ScoreGrid — 2×2 supporting-scores grid below the ScoreHero.
 *
 * Props:
 *   cells: Array<{ label, value, max?, color? }>
 *          - value can be number or string ("0 pts")
 *          - max defaults to 10
 */
export default function ScoreGrid({ cells = [], style }) {
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '1fr 1fr',
      gap: 8,
      fontFamily: fonts.body,
      ...style,
    }}>
      {cells.map((cell, i) => {
        const numericVal = typeof cell.value === 'number' ? cell.value : parseFloat(cell.value);
        const max = cell.max || 10;
        const pct = isNaN(numericVal) ? 0 : Math.max(0, Math.min(100, (numericVal / max) * 100));
        const color = cell.color || colors.teal[600];
        const displayVal = typeof cell.value === 'number' ? cell.value.toFixed(1) : cell.value;

        return (
          <div key={i} style={{
            background: colors.bg.primary,
            border: `0.5px solid ${colors.border.default}`,
            borderRadius: radii.md,
            padding: '10px 12px',
          }}>
            <div style={{ fontSize: 10, color: colors.text.secondary, marginBottom: 3 }}>
              {cell.label}
            </div>
            <div style={{
              fontFamily: fonts.mono,
              fontSize: 18,
              fontWeight: 500,
              color,
            }}>
              {displayVal}
            </div>
            <div style={{
              height: 2,
              background: colors.bg.tertiary,
              borderRadius: 1,
              overflow: 'hidden',
              marginTop: 6,
            }}>
              <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 1 }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}
