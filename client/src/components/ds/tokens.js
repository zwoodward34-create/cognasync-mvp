// ============================================================
// CognaSync Design System — Tokens v1.0 (May 2026)
// Mirror of /static/css/tokens.css for use in React inline styles.
// If you change a value here, change it there too.
// ============================================================

export const colors = {
  teal: {
    50:  '#E1F5EE',
    100: '#9FE1CB',
    400: '#1D9E75',
    600: '#0F6E56', // primary
    800: '#085041',
    900: '#04342C',
  },
  amber: {
    50:  '#FAEEDA',
    400: '#BA7517',
    600: '#854F0B',
    800: '#633806',
  },
  red: {
    50:  '#FCEBEB',
    400: '#E24B4A',
    600: '#A32D2D',
    800: '#791F1F',
  },
  blue: {
    600: '#185FA5', // L2 insight only
  },
  gray: {
    50:  '#F7F5F1',
    100: '#EDEBE6',
    200: '#D3D1C7',
    400: '#888780',
    600: '#5F5E5A',
    800: '#2C2C2A',
    900: '#1A1A18',
  },
  // — Semantic —
  bg: {
    primary:   '#FAFAF8',
    secondary: '#F4F2ED',
    tertiary:  '#EDEBE6',
  },
  text: {
    primary:   '#1A1A18',
    secondary: '#5F5E5A',
    tertiary:  '#888780',
  },
  border: {
    subtle:  'rgba(0,0,0,0.08)',
    default: 'rgba(0,0,0,0.12)',
    strong:  'rgba(0,0,0,0.20)',
  },
};

export const fonts = {
  display: "'DM Serif Display', Georgia, serif",
  body:    "'DM Sans', system-ui, -apple-system, BlinkMacSystemFont, sans-serif",
  mono:    "'JetBrains Mono', 'SF Mono', 'Courier New', monospace",
};

export const radii = {
  sm: 6,
  md: 10,
  lg: 16,
  xl: 22,
};

export const space = {
  1: 4, 2: 8, 3: 12, 4: 16, 5: 20, 6: 24, 8: 32, 10: 40, 12: 48,
};

// Pre-composed type styles — use as spread, e.g.  <div style={{ ...type.display }}>
export const type = {
  display:    { fontFamily: fonts.display, fontSize: 40, lineHeight: 1.1,  letterSpacing: '-0.02em' },
  displaySm:  { fontFamily: fonts.display, fontSize: 28, lineHeight: 1.15, letterSpacing: '-0.01em' },
  heading:    { fontFamily: fonts.display, fontSize: 20, lineHeight: 1.2 },
  subheading: { fontFamily: fonts.body,    fontSize: 15, lineHeight: 1.3, fontWeight: 500 },
  body:       { fontFamily: fonts.body,    fontSize: 14, lineHeight: 1.6 },
  small:      { fontFamily: fonts.body,    fontSize: 12, lineHeight: 1.5 },
  micro:      { fontFamily: fonts.body,    fontSize: 10, fontWeight: 500, letterSpacing: '0.08em', textTransform: 'uppercase' },
  mono:       { fontFamily: fonts.mono,    fontSize: 13 },
};

// Status helpers used by Badge, Insight, etc.
export const statusToColor = (status) => {
  // status: 'stable' | 'watch' | 'decline' | 'neutral' | 'rising' | 'erratic'
  switch (status) {
    case 'stable':
    case 'rising':
      return { bg: colors.teal[50],  fg: colors.teal[800],  line: colors.teal[600] };
    case 'watch':
    case 'erratic':
      return { bg: colors.amber[50], fg: colors.amber[800], line: colors.amber[600] };
    case 'decline':
      return { bg: colors.red[50],   fg: colors.red[800],   line: colors.red[600] };
    case 'neutral':
    default:
      return { bg: colors.bg.tertiary, fg: colors.text.secondary, line: colors.gray[200] };
  }
};

export const insightLevelColor = (level) => {
  switch (level) {
    case 1: return colors.teal[600];   // observation
    case 2: return colors.blue[600];   // pattern
    case 3: return colors.amber[600];  // reflection
    case 4: return colors.red[600];    // provider prompt
    default: return colors.gray[400];
  }
};

export default { colors, fonts, radii, space, type, statusToColor, insightLevelColor };
