import * as React from 'react'
import { ActivityIndicator, Pressable, StyleSheet, Text, View, type StyleProp, type ViewStyle } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { useRouter } from 'expo-router'
import { ArrowLeft, Building2, ChevronDown, ChevronRight } from 'lucide-react-native'
import { colors, font, MAIN_ACTION, radius, space, TOUCH } from '../theme'
import { useSite } from '../lib/session'
import { useWords } from '../lib/i18n'

/** The hazard-tape line at the top of every main screen (the dashboard's top bar). */
export function HazardStripe() {
  return (
    <View style={styles.stripe} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      {Array.from({ length: 30 }, (_, i) => (
        <View key={i} style={[styles.stripeBlock, { backgroundColor: i % 2 ? colors.ink : colors.brand }]} />
      ))}
    </View>
  )
}

export function Screen({ children, dark, style }: { children: React.ReactNode; dark?: boolean; style?: StyleProp<ViewStyle> }) {
  const insets = useSafeAreaInsets()
  return (
    <View style={[{ flex: 1, paddingTop: insets.top, backgroundColor: dark ? colors.night : colors.ground }, style]}>
      {children}
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
      <View style={styles.siteIcon}>
        <Building2 size={18} color={colors.ink} />
      </View>
      <View style={{ flexShrink: 1 }}>
        <Text style={font.strong} numberOfLines={1}>
          {current?.project.name ?? '—'}
        </Text>
        <Text style={font.tiny} numberOfLines={1}>
          {current?.site.name ?? ''}
        </Text>
      </View>
      <ChevronDown size={16} color={colors.muted} />
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

export function BackHeader({ title, subtitle, dark }: { title: string; subtitle?: string; dark?: boolean }) {
  const router = useRouter()
  const { t } = useWords()
  return (
    <View style={styles.backHeader}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={t.back}
        onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))}
        style={[styles.round, dark && { backgroundColor: colors.nightRaised, borderColor: colors.nightRaised }]}
      >
        <ArrowLeft size={20} color={dark ? '#fff' : colors.ink} />
      </Pressable>
      <View style={{ flexShrink: 1 }}>
        <Text style={[font.heading, dark && { color: '#fff' }]}>{title}</Text>
        {subtitle ? <Text style={[font.tiny, dark && { color: colors.nightMuted }]}>{subtitle}</Text> : null}
      </View>
    </View>
  )
}

export function Card({ children, style }: { children: React.ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[styles.card, style]}>{children}</View>
}

type Tone = 'done' | 'todo' | 'warn'
const TONES: Record<Tone, { bg: string; fg: string; mark: string }> = {
  done: { bg: colors.doneSoft, fg: colors.done, mark: '✓' },
  todo: { bg: colors.todoSoft, fg: colors.todo, mark: '+' },
  warn: { bg: colors.warnSoft, fg: colors.warn, mark: '!' },
}

/** One line of the site's day: a mark (done / to tell / attention), what, and what was told. */
export function DayRow({ title, detail, tone, first, onPress }: { title: string; detail: string; tone: Tone; first?: boolean; onPress: () => void }) {
  const t = TONES[tone]
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${title}. ${detail}`}
      onPress={onPress}
      style={({ pressed }) => [styles.row, !first && styles.rowLine, pressed && styles.pressed]}
    >
      <View style={[styles.mark, { backgroundColor: t.bg }]}>
        <Text style={{ color: t.fg, fontWeight: '800', fontSize: 16 }}>{t.mark}</Text>
      </View>
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text style={font.strong}>{title}</Text>
        <Text style={[font.tiny, tone !== 'done' && { color: t.fg }]} numberOfLines={1}>
          {detail}
        </Text>
      </View>
      <ChevronRight size={18} color={colors.faint} />
    </Pressable>
  )
}

type Kind = 'primary' | 'secondary' | 'dark'

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
  const look = kind === 'primary' ? styles.primary : kind === 'dark' ? styles.dark : styles.secondary
  const text = kind === 'dark' ? '#fff' : colors.ink
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: !!disabled || !!busy, busy: !!busy }}
      disabled={disabled || busy}
      onPress={onPress}
      style={({ pressed }) => [styles.button, look, (pressed || disabled) && styles.pressed, style]}
    >
      {busy ? <ActivityIndicator color={text} /> : icon}
      <Text style={{ color: text, fontSize: kind === 'primary' ? 17 : 15, fontWeight: '700' }}>{label}</Text>
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
      <Text style={{ fontSize: 15, fontWeight: '600', color: colors.ink }}>{label}</Text>
    </Pressable>
  )
}

export function Notice({ text, tone = 'warn', icon }: { text: string; tone?: 'warn' | 'info'; icon?: React.ReactNode }) {
  return (
    <View style={[styles.notice, tone === 'info' && { backgroundColor: colors.sand }]}>
      {icon}
      <Text style={{ flex: 1, fontSize: 14, color: tone === 'warn' ? '#7c2d12' : colors.inkSoft }}>{text}</Text>
    </View>
  )
}

export function Loading({ label }: { label: string }) {
  return (
    <View style={{ padding: space.xl, alignItems: 'center', gap: space.sm }}>
      <ActivityIndicator color={colors.ink} />
      <Text style={font.small}>{label}</Text>
    </View>
  )
}

export const styles = StyleSheet.create({
  stripe: { height: 4, flexDirection: 'row', overflow: 'hidden' },
  stripeBlock: { width: 14, height: 4, transform: [{ skewX: '-45deg' }], marginRight: 0 },
  topBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: space.lg,
    paddingVertical: 10,
    gap: space.md,
  },
  siteButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    minHeight: TOUCH,
    paddingVertical: 6,
    paddingLeft: 10,
    paddingRight: 14,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.card,
    flexShrink: 1,
  },
  siteIcon: { width: 32, height: 32, borderRadius: 10, backgroundColor: colors.brand, alignItems: 'center', justifyContent: 'center' },
  backHeader: { flexDirection: 'row', alignItems: 'center', gap: space.md, paddingHorizontal: space.lg, paddingTop: 14, paddingBottom: 8 },
  round: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.line,
    alignItems: 'center',
    justifyContent: 'center',
  },
  card: { backgroundColor: colors.card, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.line, overflow: 'hidden' },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.md, minHeight: 60, paddingHorizontal: 14, paddingVertical: 8 },
  rowLine: { borderTopWidth: 1, borderTopColor: colors.lineSoft },
  mark: { width: 36, height: 36, borderRadius: 11, alignItems: 'center', justifyContent: 'center' },
  button: {
    minHeight: MAIN_ACTION,
    borderRadius: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
    paddingHorizontal: space.lg,
  },
  primary: { backgroundColor: colors.brand },
  dark: { backgroundColor: colors.night },
  secondary: { backgroundColor: colors.card, borderWidth: 1, borderColor: colors.field, minHeight: TOUCH },
  chip: {
    minHeight: TOUCH,
    paddingHorizontal: space.lg,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.field,
    backgroundColor: colors.card,
    justifyContent: 'center',
  },
  chipOn: { borderWidth: 2, borderColor: colors.ink, backgroundColor: colors.brandSoft },
  notice: { flexDirection: 'row', alignItems: 'center', gap: space.md, padding: 14, borderRadius: 16, backgroundColor: colors.warnSoft },
  pressed: { opacity: 0.7 },
})
