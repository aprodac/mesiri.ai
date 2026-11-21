// The dashboard's brand (WEB-76, docs/DESIGN.md), sized for a site: one hand, gloves, sunlight.
// Yellow is a fill under dark ink, never text on white.

export const colors = {
  ground: '#f6f3ed',
  card: '#ffffff',
  ink: '#1a1d21',
  inkSoft: '#3e3c3d',
  muted: '#5f5a52',
  faint: '#8a847a',
  line: '#e7e1d6',
  lineSoft: '#efe9de',
  field: '#d6cfc2',
  sand: '#efe9de',
  brand: '#facc15',
  brandSoft: '#fef9c3',
  brandWash: '#fffbeb',
  brandInk: '#854d0e',
  charcoal: '#3e3c3d',
  night: '#1a1d21',
  nightCard: '#24272c',
  nightRaised: '#2a2d32',
  nightText: '#e5e2dc',
  nightMuted: '#b9b5ad',
  done: '#15803d',
  doneSoft: '#dcfce7',
  todo: '#92400e',
  todoSoft: '#fef3c7',
  warn: '#9a3412',
  warnSoft: '#ffedd5',
  danger: '#b91c1c',
} as const

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24 } as const
export const radius = { sm: 10, md: 14, lg: 18, pill: 999 } as const

/** Smallest touch target on a site screen; main actions and the mic are larger. */
export const TOUCH = 48
export const MAIN_ACTION = 56
export const MIC = 72

export const font = {
  // Noto Sans covers Malayalam, Devanagari and Tamil on Android; the system font does on iPhone.
  title: { fontSize: 24, fontWeight: '700' as const, color: colors.ink },
  heading: { fontSize: 17, fontWeight: '700' as const, color: colors.ink },
  body: { fontSize: 15, color: colors.ink },
  strong: { fontSize: 15, fontWeight: '600' as const, color: colors.ink },
  small: { fontSize: 13, color: colors.muted },
  tiny: { fontSize: 12, color: colors.muted },
}
