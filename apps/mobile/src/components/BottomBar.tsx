import * as React from 'react'
import { Pressable, StyleSheet, Text, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import type { BottomTabBarProps } from '@react-navigation/bottom-tabs'
import { CalendarDays, ListChecks, Menu, Mic, Package } from 'lucide-react-native'
import { useRouter } from 'expo-router'
import { colors, family, HAIRLINE, MIC } from '../theme'
import { useWords } from '../lib/i18n'

// Today · Site · [mic] · Requests · More. The mic is in the same place on every screen: an ink disc with the
// yellow mic, the app's one loud thing. The tab you are on is ink with a yellow bar above it.

const ICONS: Record<string, typeof CalendarDays> = {
  index: CalendarDays,
  site: Package,
  requests: ListChecks,
  more: Menu,
}

export function BottomBar({ state, navigation }: BottomTabBarProps) {
  const insets = useSafeAreaInsets()
  const router = useRouter()
  const { t } = useWords()
  const labels: Record<string, string> = { index: t.today, site: t.site, requests: t.requests, more: t.more }
  const tabs = state.routes.filter((r) => r.name in ICONS)

  const tab = (route: (typeof tabs)[number]) => {
    const focused = state.routes[state.index]?.key === route.key
    const Icon = ICONS[route.name]
    const tint = focused ? colors.ink : colors.faint
    return (
      <Pressable
        key={route.key}
        accessibilityRole="tab"
        accessibilityState={{ selected: focused }}
        accessibilityLabel={labels[route.name]}
        onPress={() => {
          const event = navigation.emit({ type: 'tabPress', target: route.key, canPreventDefault: true })
          if (!focused && !event.defaultPrevented) navigation.navigate(route.name)
        }}
        style={styles.tab}
      >
        <View style={[styles.marker, focused && { backgroundColor: colors.brand }]} />
        <Icon size={22} color={tint} strokeWidth={focused ? 2.2 : 1.8} />
        <Text style={[styles.label, { color: tint }]} numberOfLines={1}>
          {labels[route.name]}
        </Text>
      </Pressable>
    )
  }

  return (
    <View style={[styles.bar, { paddingBottom: Math.max(insets.bottom, 8) }]}>
      {tabs.slice(0, 2).map(tab)}
      <View style={styles.micSlot}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={t.speakToMesiri}
          onPress={() => router.push('/speak')}
          style={({ pressed }) => [styles.mic, pressed && { transform: [{ scale: 0.95 }] }]}
        >
          <Mic size={26} color={colors.brand} strokeWidth={2.2} />
        </Pressable>
      </View>
      {tabs.slice(2).map(tab)}
    </View>
  )
}

const styles = StyleSheet.create({
  bar: { flexDirection: 'row', alignItems: 'flex-end', backgroundColor: colors.card, borderTopWidth: HAIRLINE, borderTopColor: colors.line },
  tab: { flex: 1, alignItems: 'center', justifyContent: 'flex-end', gap: 4, minHeight: 56, paddingBottom: 4 },
  marker: { position: 'absolute', top: 0, width: 28, height: 2 },
  label: { fontFamily: family.monoMedium, fontSize: 10, letterSpacing: 0.8, textTransform: 'uppercase' },
  micSlot: { flex: 1, alignItems: 'center' },
  mic: {
    width: MIC,
    height: MIC,
    marginTop: -26,
    marginBottom: 4,
    borderRadius: MIC / 2,
    backgroundColor: colors.ink,
    borderWidth: 4,
    borderColor: colors.ground,
    alignItems: 'center',
    justifyContent: 'center',
  },
})
