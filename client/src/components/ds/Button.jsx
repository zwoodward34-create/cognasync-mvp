import { colors, fonts, radii } from './tokens';

/**
 * Button — primary | secondary | ghost | danger
 * Props:
 *   variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
 *   size?:    'sm' | 'md'
 *   onClick, disabled, children, style, ...rest
 */
export default function Button({
  variant = 'primary',
  size    = 'md',
  onClick,
  disabled,
  children,
  style,
  type: btnType = 'button',
  ...rest
}) {
  const base = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    fontFamily: fonts.body,
    fontWeight: 500,
    cursor: disabled ? 'not-allowed' : 'pointer',
    border: 'none',
    transition: 'opacity 0.15s',
    opacity: disabled ? 0.5 : 1,
    textDecoration: 'none',
    whiteSpace: 'nowrap',
  };

  const sizing = size === 'sm'
    ? { padding: '7px 13px', fontSize: 12, borderRadius: radii.sm }
    : { padding: '10px 18px', fontSize: 13, borderRadius: radii.md };

  const variants = {
    primary:   { background: colors.teal[600], color: '#fff' },
    secondary: { background: 'transparent', color: colors.teal[600], border: `1px solid ${colors.teal[600]}` },
    ghost:     { background: colors.bg.secondary, color: colors.text.secondary, border: `0.5px solid ${colors.border.default}` },
    danger:    { background: colors.red[50], color: colors.red[800], border: `1px solid ${colors.red[400]}` },
  };

  return (
    <button
      type={btnType}
      onClick={onClick}
      disabled={disabled}
      style={{ ...base, ...sizing, ...variants[variant], ...style }}
      {...rest}
    >
      {children}
    </button>
  );
}
