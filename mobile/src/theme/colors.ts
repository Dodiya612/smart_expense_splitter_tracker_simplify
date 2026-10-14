/**
 * Color tokens: light mode only (dark mode is a later phase).
 * Screens must NEVER import this file directly. Use `useTheme()` from `src/theme`.
 *
 * Contrast rule (checked against WCAG AA, 4.5:1 for small text):
 *  - `text`  variants are dark enough for small text on white AND on `background`.
 *  - `fill`  variants are bright. Use for chart segments, icons, bars, badges.
 *            NEVER use `fill` colors for small text, and never put white text on them.
 *  - `soft`  variants are tinted backgrounds for chips/badges. Pair with the `text` variant.
 */
export const lightColors = {
  background: '#F5F7FB',
  surface: '#FFFFFF',
  surfaceMuted: '#EEF2F8',

  border: '#E6EAF1', // decorative dividers and card edges only
  borderStrong: '#818B9E', // input outlines and interactive edges (>= 3:1 on white and on background)

  textPrimary: '#172B4D',
  textSecondary: '#5B667A',
  textOnPrimary: '#FFFFFF',

  primary: '#172B4D',
  primaryPressed: '#0F1E38',

  // Financial status. Always pair color with a sign, label or icon (never color alone).
  positive: { text: '#0E7A5A', fill: '#20B486', soft: '#E3F6EF' }, // you're owed / under budget
  negative: { text: '#B83232', fill: '#F07878', soft: '#FDEBEA' }, // you owe / over budget
  warning: { text: '#A85A00', fill: '#FF9B42', soft: '#FFF0E0' }, // near budget limit
  info: { text: '#2A5BD7', fill: '#4F86F7', soft: '#E8EFFE' },

  overlay: 'rgba(23, 43, 77, 0.4)',
} as const;

export type ColorTokens = typeof lightColors;

/**
 * PROPOSAL: category / chart palette. Assignment of categories to entries is done in
 * feature code, keyed by category id. Category ids are PROVISIONAL until the backend agrees.
 * Every chart segment must also be identifiable by label and amount, not by color alone.
 */
export const categoryPalette = [
  { fill: '#FF9B42', soft: '#FFF0E0' }, // orange
  { fill: '#4F86F7', soft: '#E8EFFE' }, // blue
  { fill: '#20B486', soft: '#E3F6EF' }, // green
  { fill: '#F07878', soft: '#FDEBEA' }, // coral
  { fill: '#8B6CF0', soft: '#F0ECFE' }, // violet
  { fill: '#2BB5C9', soft: '#E2F5F8' }, // teal
  { fill: '#EC6FA6', soft: '#FDEAF3' }, // pink
  { fill: '#E3B341', soft: '#FBF3DC' }, // amber
  { fill: '#8A94A6', soft: '#EEF1F6' }, // slate (use for "Other")
] as const;
