import { statusToColor, fonts } from './tokens';

/**
 * Badge — small status pill.
 * Props:
 *   status?: 'stable' | 'watch' | 'decline' | 'neutral'
 *   children: label text
 */
export default function Badge({ status = 'neutral', children, style }) {
  const c = statusToColor(status);
  return (
    <span style={{
      display: 'inline-block',
      padding: '3px 9px',
      borderRadius: 20,
      fontSize: 11,
      fontFamily: fonts.body,
      fontWeight: 500,
      background: c.bg,
      color: c.fg,
      ...style,
    }}>
      {children}
    </span>
  );
}
