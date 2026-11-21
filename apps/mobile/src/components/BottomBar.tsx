import * as React from 'react'
import { Pressable, StyleSheet, Text, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import type { BottomTabBarProps } from '@react-navigation/bottom-tabs'
import { CalendarDays, ListChecks, Menu, Mic, Package } from 'lucide-react-native'
import { useRouter } from 'expo-router'
import { colors, MIC } from '../theme'
import { useWords } from '../lib/i18n'

// Today · Site · [mic] · Requests · More. The mic is in the same place on every screen.

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
    const tint = focused ? colors.ink : colors.muted
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
        <Icon size={24} color={tint} strokeWidth={focused ? 2.4 : 2} />
        <Text style={[styles.label, { color: tint, fontWeight: focused ? '700' : '500' }]}>{labels[route.name]}</Text>
      </Pressable>
    )
  }

  return (
    <View style={[styles.bar, { paddingBottom: Math.max(insets.bottom, 10) }]}>
      {tabs.slice(0, 2).map(tab)}
      <View style={styles.micSlot}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={t.speakToMesiri}
          onPress={() => router.push('/speak')}
          style={({ pressed }) => [styles.mic, pressed && { transform: [{ scale: 0.96 }] }]}
        >
          <Mic size={30} color={colors.ink} strokeWidth={2.2} />
        </Pressable>
      </View>
      {tabs.slice(2).map(tab)}
    </View>
  )
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    backgroundColor: colors.card,
    borderTopWidth: 1,
    borderTopColor: colors.line,
    paddingTop: 8,
  },
  tab: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 4, minHeight: 52 },
  label: { fontSize: 12 },
  micSlot: { flex: 1, alignItems: 'center' },
  mic: {
    width: MIC,
    height: MIC,
    marginTop: -34,
    borderRadius: MIC / 2,
    backgroundColor: colors.brand,
    borderWidth: 4,
    borderColor: colors.ground,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: colors.ink,
    shadowOpacity: 0.22,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 6 },
    elevation: 6,
  },
})
