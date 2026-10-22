/**
 * Elevation tokens for selective neumorphic depth.
 * iOS uses shadow*, Android uses elevation.
 * Android requires backgroundColor on the elevated element to cast a shadow.
 */
export const shadows = {
  card: {
    shadowColor: '#172B4D',
    shadowOpacity: 0.12,
    shadowRadius: 16,
    shadowOffset: { width: 0, height: 6 },
    elevation: 4,
  },
  floating: {
    shadowColor: '#172B4D',
    shadowOpacity: 0.16,
    shadowRadius: 24,
    shadowOffset: { width: 0, height: 8 },
    elevation: 8,
  },
  button: {
    shadowColor: '#172B4D',
    shadowOpacity: 0.14,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 3 },
    elevation: 3,
  },
} as const;

export type ShadowTokens = typeof shadows;
