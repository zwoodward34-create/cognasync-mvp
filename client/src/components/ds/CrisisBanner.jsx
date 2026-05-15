import { colors, radii, fonts } from './tokens';

/**
 * CrisisBanner — hard override per spec section 04.
 * Rendered when crisis signals are detected. When this is shown,
 * no insights, scores, or AI analysis may be rendered on the same screen.
 *
 * Default copy is canonical from the design system. Override only with care.
 */
export default function CrisisBanner({
  label = "If you're in crisis, please reach out",
  lines,
  style,
}) {
  const defaultLines = (
    <>
      988 Suicide &amp; Crisis Lifeline — call or text <strong>988</strong>
      &nbsp;·&nbsp;
      Crisis Text Line — text <strong>HOME</strong> to 741741
    </>
  );

  return (
    <div style={{
      background: colors.red[50],
      border: `1.5px solid ${colors.red[400]}`,
      borderRadius: radii.md,
      padding: '14px 16px',
      fontFamily: fonts.body,
      ...style,
    }}>
      <div style={{
        fontSize: 11,
        fontWeight: 500,
        color: colors.red[800],
        textTransform: 'uppercase',
        letterSpacing: '0.08em',
        marginBottom: 4,
      }}>
        {label}
      </div>
      <div style={{
        fontSize: 13,
        color: colors.red[800],
        lineHeight: 1.5,
      }}>
        {lines || defaultLines}
      </div>
    </div>
  );
}
