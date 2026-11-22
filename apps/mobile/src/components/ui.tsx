import * as React from 'react'
import { ActivityIndicator, Pressable, StyleSheet, Text, View, type StyleProp, type TextStyle, type ViewStyle } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { useRouter } from 'expo-router'
import { ArrowLeft, Check, ChevronDown, ChevronRight, Plus } from 'lucide-react-native'
import { colors, family, font, HAIRLINE, MAIN_ACTION, radius, space, TOUCH } from '../theme'
import { useSite } from '../lib/session'
import { useWords } from '../lib/i18n'

// The app's parts, in its Swiss-on-site look (src/theme.ts): paper, ink, hairlines, one yellow.

/** The hazard-tape line at the top of the main screens: thin, the one loud construction mark. */
export function HazardStripe() {
  return (
    <View style={styles.stripe} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      {Array.from({ length: 40 }, (_, i) => (
        <View key={i} style={[styles.stripeBlock, { backgroundColor: i % 2 ? colors.ink : colors.brand }]} />
      ))}
    </View>
  )
}

export function Screen({ children, dark, style }: { children: React.ReactNode; dark?: boolean; style?: StyleProp<ViewStyle> }) {
  const insets = useSafeAreaInsets()
  return <View style={[{ flex: 1, paddingTop: insets.top, backgroundColor: dark ? colors.night : colors.ground }, style]}>{children}</View>
}

/** Drawing capitals: "SITE", "01", "REQ-0012". */
export function Label({ children, style, tone }: { children: React.ReactNode; style?: StyleProp<TextStyle>; tone?: 'ink' | 'muted' | 'light' }) {
  const color = tone === 'ink' ? colors.ink : tone === 'light' ? colors.nightMuted : colors.muted
  return <Text style={[font.label, { color }, style]}>{children}</Text>
}

/** A section's head: its label, a hairline, and what is on the right ("6 / 7", an action). */
export function SectionHead({ label, right, style }: { label: string; right?: React.ReactNode; style?: StyleProp<ViewStyle> }) {
  return (
    <View style={[styles.sectionHead, style]}>
      <Label>{label}</Label>
      <View style={styles.sectionRule} />
      {right}
    </View>
  )
}

/** The site this person is reporting for, always at the top; tapping it changes site. */
export function SiteButton() {
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
      <Label>{current?.project.name ?? '—'}</Label>
      <View style={styles.siteRow}>
        <Text style={styles.siteName} numberOfLines={1}>
          {current?.site.name ?? ''}
        </Text>
        <ChevronDown size={18} color={colors.ink} strokeWidth={2.2} />
      </View>
    </Pressable>
  )
}

export function TopBar({ right }: { right?: React.ReactNode }) {
  return (
    <View>
      <HazardStripe />
      <View style={styles.topBar}>
        <SiteButton />
        {right}
      </View>
    </View>
  )
}

/** A dot and a word: "● ONLINE" / "● NO SIGNAL". */
export function Status({ ok, label }: { ok: boolean; label: string }) {
  return (
    <View style={styles.status} accessibilityLabel={label}>
      <View style={[styles.statusDot, { backgroundColor: ok ? colors.done : colors.warn }]} />
      <Label style={{ color: ok ? colors.done : colors.warn }}>{label}</Label>
    </View>
  )
}

export function BackHeader({ title, subtitle, dark }: { title: string; subtitle?: string; dark?: boolean }) {
  const router = useRouter()
  const { t } = useWords()
  return (
    <View style={styles.backHeader}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={t.back}
        onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))}
        style={({ pressed }) => [styles.back, dark && { borderColor: colors.nightRaised }, pressed && styles.pressed]}
      >
        <ArrowLeft size={20} color={dark ? '#fff' : colors.ink} strokeWidth={2} />
      </Pressable>
      <View style={{ flexShrink: 1, gap: 2 }}>
        {subtitle ? <Label tone={dark ? 'light' : 'muted'}>{subtitle}</Label> : null}
        <Text style={[font.title, dark && { color: '#fff' }]}>{title}</Text>
      </View>
    </View>
  )
}

/** A flat panel: the card colour on the paper, a hairline edge, no shadow. */
export function Card({ children, style }: { children: React.ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[styles.card, style]}>{children}</View>
}

type Tone = 'done' | 'todo' | 'warn'

/** A row's state as a small square: done (ink, a tick), to tell (an empty outline, a plus), attention (brick, !). */
export function StatusMark({ tone }: { tone: Tone }) {
  if (tone === 'done')
    return (
      <View style={[styles.mark, { borderColor: colors.ink }]}>
        <Check size={14} color={colors.ink} strokeWidth={2.6} />
      </View>
    )
  if (tone === 'warn')
    return (
      <View style={[styles.mark, { backgroundColor: colors.warn, borderColor: colors.warn }]}>
        <Text style={{ color: '#fff', fontFamily: family.display, fontSize: 14, lineHeight: 16 }}>!</Text>
      </View>
    )
  return (
    <View style={[styles.mark, { borderStyle: 'dashed', borderColor: colors.faint }]}>
      <Plus size={13} color={colors.muted} strokeWidth={2.4} />
    </View>
  )
}

/** One line of the site's day: its number, what, what was told, and its state. */
export function DayRow({
  index,
  title,
  detail,
  tone,
  first,
  onPress,
}: {
  index?: number
  title: string
  detail: string
  tone: Tone
  first?: boolean
  onPress: () => void
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${title}. ${detail}`}
      onPress={onPress}
      style={({ pressed }) => [styles.row, !first && styles.rowLine, pressed && { backgroundColor: colors.sand }]}
    >
      {index !== undefined ? <Label style={styles.rowIndex}>{String(index).padStart(2, '0')}</Label> : null}
      <View style={{ flex: 1, minWidth: 0, gap: 2 }}>
        <Text style={styles.rowTitle}>{title}</Text>
        <Text style={[font.small, tone === 'todo' && { color: colors.faint }, tone === 'warn' && { color: colors.warn }]} numberOfLines={1}>
          {detail}
        </Text>
      </View>
      <StatusMark tone={tone} />
      <ChevronRight size={16} color={colors.faint} />
    </Pressable>
  )
}

/** Progress as a tape: one segment per part of the day, filled when told. */
export function Tape({ done, total, dark }: { done: number; total: number; dark?: boolean }) {
  return (
    <View style={styles.tape} accessibilityLabel={`${done} / ${total}`}>
      {Array.from({ length: total }, (_, i) => (
        <View key={i} style={[styles.tapeCell, { backgroundColor: i < done ? colors.brand : dark ? colors.nightRaised : colors.lineSoft }]}>
          <View style={[styles.tapeTick, { backgroundColor: i < done ? colors.ink : dark ? colors.charcoal : colors.line }]} />
        </View>
      ))}
    </View>
  )
}

type Kind = 'primary' | 'secondary' | 'dark' | 'accent'

export function Button({
  label,
  onPress,
  kind = 'primary',
  icon,
  busy,
  disabled,
  style,
}: {
  label: string
  onPress: () => void
  kind?: Kind
  icon?: React.ReactNode
  busy?: boolean
  disabled?: boolean
  style?: StyleProp<ViewStyle>
}) {
  // Primary is ink (calm in sunlight, never cheap); the yellow accent is kept for the one action on a dark screen.
  const look = kind === 'secondary' ? styles.secondary : kind === 'accent' ? styles.accent : styles.primary
  const text = kind === 'secondary' || kind === 'accent' ? colors.ink : colors.card
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: !!disabled || !!busy, busy: !!busy }}
      disabled={disabled || busy}
      onPress={onPress}
      style={({ pressed }) => [styles.button, look, pressed && styles.pressed, disabled && !busy && { opacity: 0.3 }, style]}
    >
      {busy ? <ActivityIndicator color={text} /> : icon}
      <Text style={[font.button, { color: text }]}>{label}</Text>
    </Pressable>
  )
}

export function Chip({ label, selected, onPress }: { label: string; selected?: boolean; onPress: () => void }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected: !!selected }}
      onPress={onPress}
      style={({ pressed }) => [styles.chip, selected && styles.chipOn, pressed && styles.pressed]}
    >
      <Text style={{ fontFamily: family.semi, fontSize: 15, color: selected ? colors.card : colors.ink }}>{label}</Text>
    </Pressable>
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

export const styles = StyleSheet.create({
  stripe: { height: 3, flexDirection: 'row', overflow: 'hidden' },
  stripeBlock: { width: 12, height: 3, transform: [{ skewX: '-45deg' }] },
  topBar: { flexDirection: 'row', alignItems: 'flex-end', justifyContent: 'space-between', paddingHorizontal: space.lg, paddingTop: space.md, paddingBottom: space.sm, gap: space.md },
  siteButton: { minHeight: TOUCH, justifyContent: 'center', gap: 2, flexShrink: 1, paddingRight: space.sm },
  siteRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  siteName: { fontFamily: family.displaySemi, fontSize: 20, lineHeight: 24, letterSpacing: -0.3, color: colors.ink, flexShrink: 1 },
  status: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingBottom: 6 },
  statusDot: { width: 7, height: 7, borderRadius: 1 },
  sectionHead: { flexDirection: 'row', alignItems: 'center', gap: space.md, minHeight: 20 },
  sectionRule: { flex: 1, height: HAIRLINE, backgroundColor: colors.line },
  backHeader: { flexDirection: 'row', alignItems: 'center', gap: space.md, paddingHorizontal: space.lg, paddingTop: space.md, paddingBottom: space.md },
  back: { width: 44, height: 44, borderRadius: radius.md, borderWidth: HAIRLINE, borderColor: colors.line, alignItems: 'center', justifyContent: 'center' },
  card: { backgroundColor: colors.card, borderRadius: radius.md, borderWidth: HAIRLINE, borderColor: colors.line, overflow: 'hidden' },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.md, minHeight: 64, paddingHorizontal: space.lg, paddingVertical: 10 },
  rowLine: { borderTopWidth: HAIRLINE, borderTopColor: colors.lineSoft },
  rowIndex: { width: 20, color: colors.faint },
  rowTitle: { fontFamily: family.displaySemi, fontSize: 16, lineHeight: 21, letterSpacing: -0.2, color: colors.ink },
  mark: { width: 22, height: 22, borderRadius: 4, borderWidth: 1.5, alignItems: 'center', justifyContent: 'center' },
  tape: { flexDirection: 'row', gap: 3, height: 10 },
  tapeCell: { flex: 1, borderRadius: 1, justifyContent: 'flex-end' },
  tapeTick: { width: 1, height: 4, alignSelf: 'center' },
  button: { minHeight: MAIN_ACTION, borderRadius: radius.md, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10, paddingHorizontal: space.lg },
  primary: { backgroundColor: colors.ink },
  accent: { backgroundColor: colors.brand },
  secondary: { backgroundColor: 'transparent', borderWidth: HAIRLINE, borderColor: colors.ink, minHeight: TOUCH + 2 },
  chip: { minHeight: TOUCH - 4, paddingHorizontal: 14, borderRadius: radius.sm, borderWidth: HAIRLINE, borderColor: colors.field, backgroundColor: colors.card, justifyContent: 'center' },
  chipOn: { borderColor: colors.ink, backgroundColor: colors.ink },
  notice: { flexDirection: 'row', alignItems: 'center', gap: space.md, padding: 14, borderRadius: radius.md, backgroundColor: colors.warnSoft, borderWidth: HAIRLINE, borderColor: colors.warnSoft },
  pressed: { opacity: 0.6 },
})
