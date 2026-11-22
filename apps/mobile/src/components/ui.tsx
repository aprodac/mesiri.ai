import * as React from 'react'
import { ActivityIndicator, Pressable, StyleSheet, Text, View, type StyleProp, type TextStyle, type ViewStyle } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { useRouter } from 'expo-router'
import Svg, { Defs, Path, Pattern, Rect } from 'react-native-svg'
import {
  ArrowLeft,
  Camera,
  ChevronDown,
  CloudRain,
  Hammer,
  Settings,
  TriangleAlert,
  Truck,
  Users,
  type LucideIcon,
} from 'lucide-react-native'
import { category as CAT, colors, family, font, HAIRLINE, MAIN_ACTION, radius, space, TOUCH, type Category } from '../theme'
import { useSite } from '../lib/session'
import { useWords } from '../lib/i18n'

// The app's parts in the blueprint system (src/theme.ts; docs/plans/mobile-ux-v2-plan.md §4d). Each cue has one
// meaning everywhere: CategoryTile = what kind of thing, StateMark = what state, TimeChip = how urgent, Button kinds =
// what to do (one "accent" yellow per screen), MesiriPanel = Mesiri talking.

export function Screen({ children, dark, style }: { children: React.ReactNode; dark?: boolean; style?: StyleProp<ViewStyle> }) {
  const insets = useSafeAreaInsets()
  return <View style={[{ flex: 1, paddingTop: insets.top, backgroundColor: dark ? colors.blueprint : colors.ground }, style]}>{children}</View>
}

/** Kept for the sign-in screen's top edge: a thin blueprint line (the hazard stripe is gone in this system). */
export function HazardStripe() {
  return <View style={{ height: 3, backgroundColor: colors.blueprint }} accessibilityElementsHidden importantForAccessibility="no-hide-descendants" />
}

/** Drawing capitals: "NEEDS YOU", "PO-0005". */
export function Label({ children, style, tone }: { children: React.ReactNode; style?: StyleProp<TextStyle>; tone?: 'ink' | 'muted' | 'light' | 'yellow' }) {
  const color = tone === 'ink' ? colors.ink : tone === 'light' ? colors.blueprintMid : tone === 'yellow' ? colors.brand : colors.muted
  return <Text style={[font.label, { color }, style]}>{children}</Text>
}

/** A section's head: its label, a count badge when it has one, a hairline, and what is on the right. */
export function SectionHead({ label, count, right, style }: { label: string; count?: number; right?: React.ReactNode; style?: StyleProp<ViewStyle> }) {
  return (
    <View style={[styles.sectionHead, style]}>
      <Label>{label}</Label>
      {count ? (
        <View style={styles.countBadge}>
          <Text style={styles.countText}>{count}</Text>
        </View>
      ) : null}
      <View style={styles.sectionRule} />
      {right}
    </View>
  )
}

// ── The blueprint ──────────────────────────────────────────────────────────

/** The drawing grid, drawn once (only behind Today's title block). */
function DrawingGrid() {
  return (
    <Svg style={StyleSheet.absoluteFill} pointerEvents="none">
      <Defs>
        <Pattern id="drawing-grid" width={16} height={16} patternUnits="userSpaceOnUse">
          <Path d="M16 0H0V16" fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth={1} />
        </Pattern>
      </Defs>
      <Rect width="100%" height="100%" fill="url(#drawing-grid)" />
    </Svg>
  )
}

/** The one hero of a screen: a rounded blueprint panel; with ``grid`` its drawing grid (Today only). */
export function TitleBlock({ children, grid, style }: { children: React.ReactNode; grid?: boolean; style?: StyleProp<ViewStyle> }) {
  return (
    <View style={[styles.titleBlock, style]}>
      {grid ? <DrawingGrid /> : null}
      {children}
    </View>
  )
}

/** The site this person is reporting for; tapping it changes site. ``light`` on the blueprint. */
export function SiteButton({ light, sub }: { light?: boolean; sub?: string }) {
  const { current } = useSite()
  const router = useRouter()
  const { t } = useWords()
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={t.switchSite}
      onPress={() => router.push('/switch-site')}
      style={({ pressed }) => [styles.siteButton, pressed && styles.pressed]}
    >
      <Label tone={light ? 'light' : 'muted'}>{sub ?? current?.project.name ?? '—'}</Label>
      <View style={styles.siteRow}>
        <Text style={[styles.siteName, light && { color: '#fff' }]} numberOfLines={1}>
          {current?.site.name ?? ''}
        </Text>
        <View style={[styles.siteChevron, light ? { backgroundColor: 'rgba(255,255,255,0.16)' } : { backgroundColor: colors.sand }]}>
          <ChevronDown size={12} color={light ? '#fff' : colors.ink} strokeWidth={3} />
        </View>
      </View>
    </Pressable>
  )
}

/** The top of a tab that is not Today: the site, and what is on the right. */
export function TopBar({ right }: { right?: React.ReactNode }) {
  return (
    <View style={styles.topBar}>
      <SiteButton />
      {right}
    </View>
  )
}

/** A dot and a word: "● ONLINE" / "● NO SIGNAL". */
export function Status({ ok, label, light }: { ok: boolean; label: string; light?: boolean }) {
  return (
    <View style={styles.status} accessibilityLabel={label}>
      <View style={[styles.statusDot, { backgroundColor: ok ? (light ? '#7fd1a8' : colors.done) : colors.danger }]} />
      <Label style={{ color: ok ? (light ? colors.blueprintSoft : colors.done) : light ? '#ffb3a3' : colors.warn }}>{label}</Label>
    </View>
  )
}

export function BackHeader({ title, subtitle, dark, cat }: { title: string; subtitle?: string; dark?: boolean; cat?: Category }) {
  const router = useRouter()
  const { t } = useWords()
  return (
    <View style={styles.backHeader}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={t.back}
        onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))}
        style={({ pressed }) => [styles.back, dark && { borderColor: 'rgba(255,255,255,0.4)' }, pressed && styles.pressed]}
      >
        <ArrowLeft size={20} color={dark ? '#fff' : colors.ink} strokeWidth={2} />
      </Pressable>
      {cat ? <CategoryTile cat={cat} size={40} /> : null}
      <View style={{ flexShrink: 1, gap: 2 }}>
        {subtitle ? <Label tone={dark ? 'light' : 'muted'}>{subtitle}</Label> : null}
        <Text style={[font.title, dark && { color: '#fff' }]}>{title}</Text>
      </View>
    </View>
  )
}

/** A white panel on the paper, rounded, a hairline edge. */
export function Card({ children, style }: { children: React.ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[styles.card, style]}>{children}</View>
}

// ── Cue 1: what kind of thing ──────────────────────────────────────────────

export const CATEGORY_ICON: Record<Category, LucideIcon> = {
  people: Users,
  work: Hammer,
  material: Truck,
  machine: Settings,
  problem: TriangleAlert,
  photo: Camera,
  weather: CloudRain,
}

export function CategoryTile({ cat, size = 36, dim }: { cat: Category; size?: number; dim?: boolean }) {
  const c = CAT[cat]
  const Icon = CATEGORY_ICON[cat]
  return (
    <View style={{ width: size, height: size, borderRadius: Math.round(size * 0.32), backgroundColor: c.tint, alignItems: 'center', justifyContent: 'center', opacity: dim ? 0.55 : 1 }}>
      <Icon size={Math.round(size * 0.5)} color={c.fg} strokeWidth={1.9} />
    </View>
  )
}

// ── Cue 2: what state ──────────────────────────────────────────────────────

export type State = 'done' | 'todo' | 'warn' | 'waiting' | 'pending' | 'voice' | 'question'

/** A round mark; the shape differs as well as the colour, so it reads without colour too. */
export function StateMark({ state, size = 24 }: { state: State; size?: number }) {
  const s = MARKS[state]
  return (
    <View
      accessibilityLabel={s.label}
      style={{ width: size, height: size, borderRadius: size / 2, backgroundColor: s.bg, borderWidth: 2, borderStyle: s.dashed ? 'dashed' : 'solid', borderColor: s.border, alignItems: 'center', justifyContent: 'center' }}
    >
      <Text style={{ color: s.fg, fontFamily: family.display, fontSize: size * 0.5, lineHeight: size * 0.62 }}>{s.mark}</Text>
    </View>
  )
}
const MARKS: Record<State, { bg: string; border: string; fg: string; mark: string; dashed?: boolean; label: string }> = {
  done: { bg: colors.ink, border: colors.ink, fg: '#fff', mark: '✓', label: 'done' },
  todo: { bg: 'transparent', border: colors.faint, fg: colors.muted, mark: '', dashed: true, label: 'to tell' },
  warn: { bg: colors.danger, border: colors.danger, fg: '#fff', mark: '!', label: 'needs attention' },
  waiting: { bg: '#fff', border: colors.blueprint, fg: colors.blueprint, mark: '◔', label: 'waiting' },
  pending: { bg: colors.brandSoft, border: colors.brandEdge, fg: colors.brandInk, mark: '', dashed: true, label: 'not saved yet' },
  voice: { bg: colors.brand, border: colors.brand, fg: colors.ink, mark: '◉', label: 'from your voice' },
  question: { bg: colors.blueprintPale, border: colors.blueprint, fg: colors.blueprint, mark: '?', dashed: true, label: 'Mesiri asks' },
}
/** The old name, kept for the screens that use it. */
export const StatusMark = ({ tone }: { tone: 'done' | 'todo' | 'warn' }) => <StateMark state={tone} />

// ── Cue 3: how urgent ──────────────────────────────────────────────────────

export type Urgency = 'overdue' | 'today' | 'answered' | 'tomorrow' | 'open'
const CHIPS: Record<Urgency, { bg: string; fg: string; border: string }> = {
  overdue: { bg: colors.danger, fg: '#fff', border: colors.danger },
  today: { bg: colors.brand, fg: colors.ink, border: colors.brand },
  answered: { bg: colors.blueprint, fg: '#fff', border: colors.blueprint },
  tomorrow: { bg: 'transparent', fg: colors.blueprint, border: colors.blueprint },
  open: { bg: 'transparent', fg: colors.warn, border: colors.danger },
}
/** Solid = act now; outlined = know it. */
export function TimeChip({ urgency, label }: { urgency: Urgency; label: string }) {
  const c = CHIPS[urgency]
  return (
    <View style={[styles.chipTime, { backgroundColor: c.bg, borderColor: c.border }]}>
      <Text style={[styles.chipTimeText, { color: c.fg }]}>{label}</Text>
    </View>
  )
}

// ── Cue 4: what to do, who is talking ──────────────────────────────────────

type Kind = 'accent' | 'primary' | 'secondary' | 'light' | 'text'

/** accent: the one yellow "do this now" per screen. primary: navy, an action on a card. secondary: outline, the
 * other way. light: outline on the blueprint. text: go and look. */
export function Button({
  label,
  onPress,
  kind = 'primary',
  icon,
  busy,
  disabled,
  small,
  style,
}: {
  label: string
  onPress: () => void
  kind?: Kind
  icon?: React.ReactNode
  busy?: boolean
  disabled?: boolean
  small?: boolean
  style?: StyleProp<ViewStyle>
}) {
  const look = { accent: styles.accent, primary: styles.primary, secondary: styles.secondary, light: styles.lightBtn, text: styles.textBtn }[kind]
  const text = kind === 'primary' || kind === 'light' ? '#fff' : kind === 'text' ? colors.blueprint : colors.ink
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: !!disabled || !!busy, busy: !!busy }}
      disabled={disabled || busy}
      onPress={onPress}
      style={({ pressed }) => [styles.button, small && styles.buttonSmall, look, pressed && styles.pressed, disabled && !busy && { opacity: 0.35 }, style]}
    >
      {busy ? <ActivityIndicator color={text} /> : icon}
      <Text style={[font.button, { color: text }, small && { fontSize: 14 }]}>{label}</Text>
    </Pressable>
  )
}

/** A choice: a pill; chosen = drawing ink. */
export function Chip({ label, selected, onPress }: { label: string; selected?: boolean; onPress: () => void }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected: !!selected }}
      onPress={onPress}
      style={({ pressed }) => [styles.chip, selected && styles.chipOn, pressed && styles.pressed]}
    >
      <Text style={{ fontFamily: family.semi, fontSize: 15, color: selected ? '#fff' : colors.ink }}>{label}</Text>
    </Pressable>
  )
}

/** Mesiri talking: a pale-blueprint panel with its mark. */
export function MesiriPanel({ children, style }: { children: React.ReactNode; style?: StyleProp<ViewStyle> }) {
  return (
    <View style={[styles.mesiri, style]}>
      <View style={styles.mesiriMark}>
        <Text style={{ fontFamily: family.display, fontSize: 14, color: colors.brand }}>M</Text>
      </View>
      <View style={{ flex: 1, gap: 8 }}>{children}</View>
    </View>
  )
}

export function Notice({ text, tone = 'warn', icon }: { text: string; tone?: 'warn' | 'info'; icon?: React.ReactNode }) {
  return (
    <View style={[styles.notice, tone === 'info' && { backgroundColor: colors.card, borderColor: colors.line }]}>
      {icon}
      <Text style={[font.body, { flex: 1, color: tone === 'warn' ? colors.warn : colors.inkSoft }]}>{text}</Text>
    </View>
  )
}

export function Loading({ label }: { label: string }) {
  return (
    <View style={{ paddingVertical: space.xl, alignItems: 'center', gap: space.sm }}>
      <ActivityIndicator color={colors.ink} />
      <Label>{label}</Label>
    </View>
  )
}

// ── Today's parts ──────────────────────────────────────────────────────────

/** One part of the day: its kind, what was told, its figure (or "+ Tell"), its state. */
export function DayRow({
  cat,
  title,
  detail,
  figure,
  state,
  last,
  tellLabel,
  onPress,
}: {
  cat: Category
  title: string
  detail: string
  figure?: string | null
  state: 'done' | 'todo' | 'warn'
  last?: boolean
  tellLabel: string
  onPress: () => void
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${title}. ${detail}`}
      onPress={onPress}
      style={({ pressed }) => [styles.row, !last && styles.rowLine, pressed && { backgroundColor: colors.sand }]}
    >
      <CategoryTile cat={cat} size={36} dim={state === 'todo'} />
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text style={styles.rowTitle}>{title}</Text>
        <Text style={[font.tiny, state === 'todo' && { color: colors.faint }, state === 'warn' && { color: colors.warn }]} numberOfLines={1}>
          {detail}
        </Text>
      </View>
      {state === 'todo' ? (
        <View style={styles.tell}>
          <Text style={styles.tellText}>{tellLabel}</Text>
        </View>
      ) : figure ? (
        <Text style={[styles.figure, state === 'warn' && { backgroundColor: colors.warnSoft, color: colors.warn }]}>{figure}</Text>
      ) : null}
      <StateMark state={state} />
    </Pressable>
  )
}

/** The day as a scale bar: one segment per part, in its kind's colour when told, dashed when not, brick when it
 * needs attention, with the kind's icon under it. On the blueprint. */
export function ScaleBar({ parts }: { parts: { cat: Category; state: 'done' | 'todo' | 'warn' }[] }) {
  return (
    <View style={styles.scale} accessibilityLabel={`${parts.filter((p) => p.state !== 'todo').length} / ${parts.length}`}>
      {parts.map((p, i) => {
        const c = CAT[p.cat]
        const Icon = CATEGORY_ICON[p.cat]
        const fill = p.state === 'todo' ? 'transparent' : p.state === 'warn' ? '#ff8a72' : c.light
        const edge = p.state === 'todo' ? 'rgba(255,255,255,0.55)' : fill
        return (
          <View key={i} style={{ flex: 1, alignItems: 'center', gap: 5 }}>
            <View style={{ alignSelf: 'stretch', height: 10, borderRadius: 3, backgroundColor: fill, borderWidth: 1.5, borderColor: edge, borderStyle: p.state === 'todo' ? 'dashed' : 'solid' }} />
            <Icon size={12} color={p.state === 'todo' ? 'rgba(255,255,255,0.45)' : fill} strokeWidth={2.4} />
          </View>
        )
      })}
    </View>
  )
}

/** The old progress tape's name, kept for any screen still using it. */
export const Tape = ({ done, total }: { done: number; total: number }) => (
  <ScaleBar parts={Array.from({ length: total }, (_, i) => ({ cat: 'work' as Category, state: i < done ? ('done' as const) : ('todo' as const) }))} />
)

export const styles = StyleSheet.create({
  topBar: { flexDirection: 'row', alignItems: 'flex-end', justifyContent: 'space-between', paddingHorizontal: space.lg, paddingTop: space.md, paddingBottom: space.sm, gap: space.md },
  titleBlock: { backgroundColor: colors.blueprint, borderRadius: radius.xl, padding: space.lg, gap: space.md, overflow: 'hidden' },
  siteButton: { minHeight: TOUCH, justifyContent: 'center', gap: 2, flexShrink: 1, paddingRight: space.sm },
  siteRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  siteName: { fontFamily: family.display, fontSize: 24, lineHeight: 28, letterSpacing: 0.2, color: colors.ink, flexShrink: 1 },
  siteChevron: { width: 22, height: 22, borderRadius: 11, alignItems: 'center', justifyContent: 'center' },
  status: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  statusDot: { width: 7, height: 7, borderRadius: 4 },
  sectionHead: { flexDirection: 'row', alignItems: 'center', gap: space.sm, minHeight: 20 },
  sectionRule: { flex: 1, height: HAIRLINE, backgroundColor: colors.line },
  countBadge: { minWidth: 18, height: 18, borderRadius: 9, backgroundColor: colors.ink, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 5 },
  countText: { color: '#fff', fontFamily: family.semi, fontSize: 11 },
  backHeader: { flexDirection: 'row', alignItems: 'center', gap: space.md, paddingHorizontal: space.lg, paddingTop: space.md, paddingBottom: space.md },
  back: { width: 44, height: 44, borderRadius: 22, borderWidth: HAIRLINE, borderColor: colors.line, alignItems: 'center', justifyContent: 'center' },
  card: { backgroundColor: colors.card, borderRadius: radius.lg, borderWidth: HAIRLINE, borderColor: colors.line, overflow: 'hidden' },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.md, minHeight: 58, paddingHorizontal: space.md, paddingVertical: 8 },
  rowLine: { borderBottomWidth: HAIRLINE, borderBottomColor: colors.lineSoft },
  rowTitle: { fontFamily: family.display, fontSize: 17, lineHeight: 21, letterSpacing: 0.2, color: colors.ink },
  figure: { fontFamily: family.mono, fontSize: 13, color: colors.ink, paddingHorizontal: 7, paddingVertical: 2, borderRadius: 6, overflow: 'hidden' },
  tell: { minHeight: 34, paddingHorizontal: 12, borderRadius: 17, borderWidth: 1.5, borderStyle: 'dashed', borderColor: colors.faint, justifyContent: 'center' },
  tellText: { fontFamily: family.display, fontSize: 14, color: colors.ink },
  scale: { flexDirection: 'row', gap: 4 },
  chipTime: { alignSelf: 'flex-start', borderRadius: radius.pill, borderWidth: 1.5, paddingHorizontal: 7, paddingVertical: 1 },
  chipTimeText: { fontFamily: family.monoMedium, fontSize: 9, letterSpacing: 0.8 },
  button: { minHeight: MAIN_ACTION, borderRadius: radius.pill, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, paddingHorizontal: 20 },
  buttonSmall: { minHeight: 40, paddingHorizontal: 14 },
  accent: { backgroundColor: colors.brand },
  primary: { backgroundColor: colors.ink },
  secondary: { backgroundColor: 'transparent', borderWidth: 1.5, borderColor: colors.ink, minHeight: TOUCH + 2 },
  lightBtn: { backgroundColor: 'transparent', borderWidth: 1.5, borderColor: 'rgba(255,255,255,0.7)', minHeight: TOUCH },
  textBtn: { backgroundColor: 'transparent', minHeight: TOUCH, paddingHorizontal: 8 },
  chip: { minHeight: 44, paddingHorizontal: 16, borderRadius: radius.pill, borderWidth: 1.5, borderColor: colors.field, backgroundColor: colors.card, justifyContent: 'center' },
  chipOn: { borderColor: colors.ink, backgroundColor: colors.ink },
  mesiri: { flexDirection: 'row', gap: 10, alignItems: 'flex-start', backgroundColor: colors.blueprintPale, borderRadius: radius.lg, padding: space.md },
  mesiriMark: { width: 26, height: 26, borderRadius: 8, backgroundColor: colors.blueprint, alignItems: 'center', justifyContent: 'center' },
  notice: { flexDirection: 'row', alignItems: 'center', gap: space.md, padding: 14, borderRadius: radius.md, backgroundColor: colors.warnSoft, borderWidth: HAIRLINE, borderColor: colors.warnSoft },
  pressed: { opacity: 0.6 },
})
