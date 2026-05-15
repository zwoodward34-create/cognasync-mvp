import { colors, fonts } from './tokens';

/**
 * StepProgress — segmented progress bar.
 *
 * Props:
 *   total:     number (number of segments)
 *   current:   number (zero-indexed; segments < current are 'done', == current is 'active')
 *   label?:    string (right-aligned label, e.g. "How you're feeling")
 *   countText?: string (left label, defaults to "Step N of M")
 */
export default function StepProgress({ total, current, label, countText, style }) {
  const left = countText || `Step ${current + 1} of ${total}`;

  return (
    <div style={{ fontFamily: fonts.body, ...style }}>
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: 6,
      }}>
        <div style={{
          fontSize: 10,
          fontWeight: 500,
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
          color: colors.text.secondary,
        }}>{left}</div>
        {label && (
          <div style={{ fontSize: 12, color: colors.text.secondary }}>{label}</div>
        )}
      </div>
      <div style={{ display: 'flex', gap: 4 }}>
        {Array.from({ length: total }).map((_, i) => {
          let bg = colors.bg.tertiary;
          if (i < current)      bg = colors.teal[600];
          else if (i === current) bg = colors.teal[100];
          return (
            <div key={i} style={{ height: 3, flex: 1, borderRadius: 2, background: bg }} />
          );
        })}
      </div>
    </div>
  );
}
