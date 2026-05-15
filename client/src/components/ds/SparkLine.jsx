import { colors } from './tokens';

/**
 * SparkLine — tiny trend chart. 80×28 by default.
 *
 * Props:
 *   data:    number[]   (y-values; normalized to fit viewBox)
 *   status?: 'stable' | 'rising' | 'declining' | 'erratic' | 'none'
 *            (picks the stroke color; 'none' renders dashed gray)
 *   width?:  number   (default 80)
 *   height?: number   (default 28)
 *   color?:  string   (override; takes precedence over status)
 *   min?, max?: number (override auto-range)
 */
const STATUS_COLOR = {
  stable:    colors.teal[600],
  rising:    colors.teal[600],
  declining: colors.red[600],
  erratic:   colors.amber[600],
  none:      colors.gray[200],
};

export default function SparkLine({
  data = [],
  status = 'stable',
  width = 80,
  height = 28,
  color,
  min,
  max,
  style,
}) {
  if (!data.length) return null;

  const stroke = color || STATUS_COLOR[status] || colors.teal[600];
  const dashed = status === 'none';
  const padTop = 4, padBot = 4;
  const vmin = min ?? Math.min(...data);
  const vmax = max ?? Math.max(...data);
  const range = vmax - vmin || 1;
  const innerH = height - padTop - padBot;
  const step = data.length > 1 ? width / (data.length - 1) : 0;

  const points = data.map((v, i) => {
    const x = i * step;
    const y = padTop + innerH - ((v - vmin) / range) * innerH;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  const lastX = (data.length - 1) * step;
  const lastY = padTop + innerH - ((data[data.length - 1] - vmin) / range) * innerH;

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{ display: 'block', ...style }}>
      <polyline
        points={points.join(' ')}
        fill="none"
        stroke={stroke}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
        strokeDasharray={dashed ? '3 2' : undefined}
      />
      <circle cx={lastX} cy={lastY} r="3" fill={stroke} />
    </svg>
  );
}
