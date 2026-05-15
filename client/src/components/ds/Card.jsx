import { colors, radii } from './tokens';

/**
 * Card — elevated surface (bg-primary on bg-secondary page).
 *
 * Props:
 *   size?: 'sm' | 'md' (default 'md')
 *   children
 */
export default function Card({ size = 'md', children, style, ...rest }) {
  const padding = size === 'sm' ? '14px' : '20px';
  const borderRadius = size === 'sm' ? radii.md : radii.lg;
  return (
    <div
      style={{
        background: colors.bg.primary,
        border: `0.5px solid ${colors.border.default}`,
        borderRadius,
        padding,
        ...style,
      }}
      {...rest}
    >
      {children}
    </div>
  );
}
