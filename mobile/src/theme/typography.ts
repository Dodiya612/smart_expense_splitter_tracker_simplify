/** Inter via @expo-google-fonts/inter. Keys must match the font names loaded at app start. */
export const fontFamily = {
  regular: 'Inter_400Regular',
  medium: 'Inter_500Medium',
  semibold: 'Inter_600SemiBold',
  bold: 'Inter_700Bold',
} as const;

/** Type scale. Minimum size is 12. Use the `money*` styles for every financial figure. */
export const typography = {
  display: { fontFamily: fontFamily.bold, fontSize: 32, lineHeight: 40 },
  title: { fontFamily: fontFamily.bold, fontSize: 22, lineHeight: 28 },
  heading: { fontFamily: fontFamily.semibold, fontSize: 18, lineHeight: 24 },
  body: { fontFamily: fontFamily.regular, fontSize: 16, lineHeight: 22 },
  bodyStrong: { fontFamily: fontFamily.semibold, fontSize: 16, lineHeight: 22 },
  small: { fontFamily: fontFamily.regular, fontSize: 14, lineHeight: 20 },
  caption: { fontFamily: fontFamily.medium, fontSize: 12, lineHeight: 16 },
  // Tabular numerals keep amounts aligned in lists.
  moneyLarge: { fontFamily: fontFamily.bold, fontSize: 32, lineHeight: 40, fontVariant: ['tabular-nums'] },
  money: { fontFamily: fontFamily.semibold, fontSize: 16, lineHeight: 22, fontVariant: ['tabular-nums'] },
} as const;
