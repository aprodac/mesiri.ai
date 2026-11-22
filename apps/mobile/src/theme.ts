// The app's look (21–22 Nov 2026): Swiss minimal, built for a construction site.
//
// - Paper, not white: a warm off-white ground and near-black ink, so it is easy on the eye in sun and at dusk.
// - One accent: safety yellow, used sparingly (the mic, progress, what came from your voice), never as text.
// - Type does the work: tight grotesk headings (Inter Tight), plain body (Inter), and small monospaced capitals
//   for labels and references (IBM Plex Mono), like the labels on a drawing. Figures are tabular.
// - Hairlines, not boxes and shadows; small radii; a strict left edge.
// - Sized for the site: 48 px touch targets, 54 px main actions, a 64 px mic.

export const colors = {
  // Ground and surfaces
  ground: '#f2f0eb',
  card: '#faf9f6',
  sand: '#e9e5dd',
  // Ink
  ink: '#17191c',
  inkSoft: '#3a3d41',
  muted: '#68645c',
  faint: '#9a958c',
  // Lines
  line: '#dcd7cd',
  lineSoft: '#e7e3db',
  field: '#cdc7bb',
  // Safety yellow (fills only) and its ink for words
  brand: '#f2c230',
  brandSoft: '#f8edc8',
  brandWash: '#fcf6e2',
  brandInk: '#755600',
  // Dark (the Speak screen)
  charcoal: '#2b2d30',
  night: '#141518',
  nightCard: '#1f2124',
  nightRaised: '#2a2c30',
  nightText: '#e8e5df',
  nightMuted: '#a8a39a',
  // Status, toned down
  done: '#2e6b4e',
  doneSoft: '#e1ece5',
  todo: '#86600a',
  todoSoft: '#f4ecd6',
  warn: '#a9432a',
  warnSoft: '#f5e2db',
  danger: '#a3321f',
} as const

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 } as const
export const radius = { sm: 6, md: 8, lg: 12, pill: 999 } as const

/** Smallest touch target on a site screen; main actions and the mic are larger. */
export const TOUCH = 48
export const MAIN_ACTION = 54
export const MIC = 64
export const HAIRLINE = 1

/** The font files loaded at start (app/_layout.tsx). */
export const family = {
  display: 'InterTight_700Bold',
  displaySemi: 'InterTight_600SemiBold',
  body: 'Inter_400Regular',
  medium: 'Inter_500Medium',
  semi: 'Inter_600SemiBold',
  mono: 'IBMPlexMono_400Regular',
  monoMedium: 'IBMPlexMono_500Medium',
} as const

const tabular = { fontVariant: ['tabular-nums' as const] }

export const font = {
  /** The page's one big word: "Today". */
  display: { fontFamily: family.display, fontSize: 34, lineHeight: 38, letterSpacing: -0.9, color: colors.ink },
  title: { fontFamily: family.display, fontSize: 24, lineHeight: 29, letterSpacing: -0.5, color: colors.ink },
  heading: { fontFamily: family.displaySemi, fontSize: 17, lineHeight: 22, letterSpacing: -0.2, color: colors.ink },
  body: { fontFamily: family.body, fontSize: 15, lineHeight: 22, color: colors.ink },
  strong: { fontFamily: family.semi, fontSize: 15, lineHeight: 21, color: colors.ink },
  small: { fontFamily: family.body, fontSize: 13, lineHeight: 18, color: colors.muted },
  tiny: { fontFamily: family.body, fontSize: 12, lineHeight: 16, color: colors.muted },
  /** Labels and references, in drawing capitals: "01", "SITE", "REQ-0012". */
  label: { fontFamily: family.monoMedium, fontSize: 11, lineHeight: 14, letterSpacing: 1.1, textTransform: 'uppercase' as const, color: colors.muted },
  /** A figure that matters: a count, a quantity. */
  figure: { fontFamily: family.display, fontSize: 22, lineHeight: 26, letterSpacing: -0.4, color: colors.ink, ...tabular },
  bigFigure: { fontFamily: family.display, fontSize: 40, lineHeight: 42, letterSpacing: -1.2, color: colors.ink, ...tabular },
  button: { fontFamily: family.displaySemi, fontSize: 16, letterSpacing: -0.1 },
}
