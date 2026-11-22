// The app's look: the blueprint system (22 Nov 2026, docs/plans/mobile-ux-v2-plan.md §4c–4d; canvas page V4).
//
// Colours keep one job each:
//   paper (the ground) · drawing ink (words, structure, the bottom bar, navy actions) · blueprint (the one hero per
//   screen; its drawing grid only on Today's title block) · highlighter yellow (do this now: the one main button,
//   TODAY, the mic) · brick (something is wrong).
// Four kinds of cue, the same on every screen: a category tile (what kind of thing), a round state mark (what state,
// by shape as well as colour), a time chip (how urgent), and the action / voice rules (one yellow button per screen;
// Mesiri speaks from a pale-blueprint panel).
// Soft shapes: rounded cards, pill buttons and chips. Type: Archivo Narrow headings, Archivo text, JetBrains Mono for
// figures and references. Site sizes: 48 px targets, 54 px main actions, 56 px mic in the bar.

export const colors = {
  // Ground and surfaces
  ground: '#f8f7f3',
  card: '#ffffff',
  sand: '#f0eee8',
  // Drawing ink
  ink: '#15233f',
  inkSoft: '#2c3a57',
  muted: '#5b6478',
  faint: '#8a93a6',
  // Lines
  line: '#e4e0d7',
  lineSoft: '#ece9e2',
  field: '#d8d3c8',
  // Highlighter yellow (fills only) and its ink for words
  brand: '#ffd23f',
  brandSoft: '#fff6d1',
  brandWash: '#fffaea',
  brandInk: '#7a5a00',
  brandEdge: '#d9a900',
  // Blueprint
  blueprint: '#1e3a6e',
  blueprintPale: '#dfe6f3',
  blueprintSoft: '#b9c8e6',
  blueprintMid: '#9fb3da',
  charcoal: '#2c3a57',
  // The blueprint screens (Speak): kept under the old names so every screen reads one set
  night: '#1e3a6e',
  nightCard: '#2a4778',
  nightRaised: '#3a5688',
  nightText: '#e6ecf7',
  nightMuted: '#b9c8e6',
  // Status
  done: '#1f6b52',
  doneSoft: '#d9ede3',
  todo: '#7a5a00',
  todoSoft: '#f8ecc4',
  warn: '#b2412b',
  warnSoft: '#f6dcd4',
  danger: '#c4472f',
} as const

/** What kind of thing: one tile colour and icon per kind, everywhere (Today, Needs you, TO SAVE, Quick add). */
export const category = {
  people: { tint: '#dfe6f3', fg: '#1e3a6e', light: '#9fb8ec' },
  work: { tint: '#d9ede3', fg: '#1f6b52', light: '#7fd1a8' },
  material: { tint: '#f8ecc4', fg: '#7a5a00', light: '#ffd23f' },
  machine: { tint: '#e6e2f2', fg: '#4a3f88', light: '#b7acf0' },
  problem: { tint: '#f6dcd4', fg: '#b2412b', light: '#ff8a72' },
  photo: { tint: '#ebe8e1', fg: '#3a3d41', light: '#e0dbd0' },
  weather: { tint: '#dcecf3', fg: '#23617a', light: '#8fd0e8' },
} as const
export type Category = keyof typeof category

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 } as const
export const radius = { sm: 10, md: 14, lg: 18, xl: 22, pill: 999 } as const

/** Smallest touch target on a site screen; main actions and the mic are larger. */
export const TOUCH = 48
export const MAIN_ACTION = 54
export const MIC = 56
export const HAIRLINE = 1

/** The font files loaded at start (app/_layout.tsx). */
export const family = {
  display: 'ArchivoNarrow_700Bold',
  displaySemi: 'ArchivoNarrow_600SemiBold',
  body: 'Archivo_400Regular',
  medium: 'Archivo_500Medium',
  semi: 'Archivo_600SemiBold',
  mono: 'JetBrainsMono_400Regular',
  monoMedium: 'JetBrainsMono_500Medium',
} as const

const tabular = { fontVariant: ['tabular-nums' as const] }

export const font = {
  /** The page's one big word: "TODAY". */
  display: { fontFamily: family.display, fontSize: 40, lineHeight: 42, letterSpacing: 0.4, color: colors.ink },
  title: { fontFamily: family.display, fontSize: 26, lineHeight: 30, letterSpacing: 0.2, color: colors.ink },
  heading: { fontFamily: family.display, fontSize: 18, lineHeight: 22, letterSpacing: 0.2, color: colors.ink },
  body: { fontFamily: family.body, fontSize: 15, lineHeight: 22, color: colors.ink },
  strong: { fontFamily: family.semi, fontSize: 15, lineHeight: 21, color: colors.ink },
  small: { fontFamily: family.body, fontSize: 13, lineHeight: 18, color: colors.muted },
  tiny: { fontFamily: family.body, fontSize: 12, lineHeight: 16, color: colors.muted },
  /** Labels and references, in drawing capitals: "NEEDS YOU", "PO-0005". */
  label: { fontFamily: family.monoMedium, fontSize: 10, lineHeight: 14, letterSpacing: 1.1, textTransform: 'uppercase' as const, color: colors.muted },
  /** A figure: a count, a quantity, a reference. */
  figure: { fontFamily: family.mono, fontSize: 14, lineHeight: 18, color: colors.ink, ...tabular },
  bigFigure: { fontFamily: family.display, fontSize: 30, lineHeight: 32, color: colors.ink, ...tabular },
  button: { fontFamily: family.display, fontSize: 16, letterSpacing: 0.3 },
}
