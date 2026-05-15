import { insightLevelColor, fonts, colors } from './tokens';

const LEVEL_TAGS = {
  1: 'L1 · Observation',
  2: 'L2 · Pattern',
  3: 'L3 · Reflection',
  4: 'L4 · Provider prompt',
};

/**
 * InsightCard — 4-level insight surface.
 * Renders a colored left rule, an uppercase tag, and the insight text.
 *
 * Props:
 *   level: 1 | 2 | 3 | 4         (required — picks color + tag)
 *   tag?:  string                (override of LEVEL_TAGS[level])
 *   text:  string                (the observation — must be guardrail-compliant)
 *   style?: object
 */
export default function InsightCard({ level = 1, tag, text, children, style }) {
  const color = insightLevelColor(level);
  return (
    <div style={{
      borderLeft: `2.5px solid ${color}`,
      padding: '8px 0 8px 12px',
      ...style,
    }}>
      <div style={{
        fontFamily: fonts.body,
        fontSize: 10,
        fontWeight: 500,
        letterSpacing: '0.07em',
        textTransform: 'uppercase',
        color,
        marginBottom: 3,
      }}>
        {tag || LEVEL_TAGS[level]}
      </div>
      <div style={{
        fontFamily: fonts.body,
        fontSize: 13,
        color: colors.text.primary,
        lineHeight: 1.5,
      }}>
        {text || children}
      </div>
    </div>
  );
}
