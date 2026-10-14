import { lightColors, categoryPalette, type ColorTokens } from './colors';
import { spacing, minTouchTarget } from './spacing';
import { radii } from './radii';
import { shadows } from './shadows';
import { typography, fontFamily } from './typography';

export const theme = {
  colors: lightColors,
  categoryPalette,
  spacing,
  radii,
  shadows,
  typography,
  fontFamily,
  minTouchTarget,
} as const;

export type Theme = typeof theme;
export type { ColorTokens };

/**
 * The only way screens and components read design tokens.
 * Light mode is hardcoded for now. For dark mode, replace the body with a
 * context/appearance lookup. Callers do not change.
 */
export function useTheme(): Theme {
  return theme;
}
