import * as React from 'react'
import { Pressable, StyleSheet, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import type { BottomTabBarProps } from '@react-navigation/bottom-tabs'
import { House, LayoutGrid, Menu, Mic, Package } from 'lucide-react-native'
import { useRouter } from 'expo-router'
import { colors, MIC, radius } from '../theme'
import { useWords } from '../lib/i18n'

// The floating drawing-ink pill (canvas V4): round tab buttons, the one you are on sits on paper; the yellow mic in
// the middle, the same place on every screen. A small yellow dot on a tab means something there needs you.

const ICONS: Record<string, typeof House> = {
  index: House,
  site: Package,
  requests: LayoutGrid,
  more: Menu,
}

export function BottomBar({ state, navigation, descriptors }: BottomTabBarProps) {
  const insets = useSafeAreaInsets()
  const router = useRouter()
  const { t } = useWords()
  const labels: Record<string, string> = { index: t.today, site: t.site, requests: t.requests, more: t.more }
  const tabs = state.routes.filter((r) => r.name in ICONS)

  const tab = (route: (typeof tabs)[number]) => {
    const focused = state.routes[state.index]?.key === route.key
    const Icon = ICONS[route.name]
    const badge = (descriptors[route.key]?.options as { tabBarBadge?: unknown } | undefined)?.tabBarBadge
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
        style={styles.slot}
      >
        <View style={[styles.tab, focused && styles.tabOn]}>
          <Icon size={22} color={focused ? colors.ink : colors.blueprintMid} strokeWidth={2} />
          {badge ? <View style={styles.badge} /> : null}
        </View>
      </Pressable>
    )
  }

  return (
    <View style={[styles.wrap, { paddingBottom: Math.max(insets.bottom, 12) }]}>
      <View style={styles.pill}>
        {tabs.slice(0, 2).map(tab)}
        <View style={styles.slot}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={t.speakToMesiri}
            onPress={() => router.push('/speak')}
            style={({ pressed }) => [styles.mic, pressed && { transform: [{ scale: 0.94 }] }]}
          >
            <Mic size={24} color={colors.ink} strokeWidth={2.3} />
          </Pressable>
        </View>
        {tabs.slice(2).map(tab)}
      </View>
    </View>
  )
}

const styles = StyleSheet.create({
  wrap: { backgroundColor: colors.ground, paddingHorizontal: 14, paddingTop: 8 },
  pill: { height: 68, borderRadius: radius.pill, backgroundColor: colors.ink, flexDirection: 'row', alignItems: 'center', paddingHorizontal: 6 },
  slot: { flex: 1, alignItems: 'center', justifyContent: 'center', height: 68 },
  tab: { width: 48, height: 48, borderRadius: 24, alignItems: 'center', justifyContent: 'center' },
  tabOn: { backgroundColor: colors.ground },
  badge: { position: 'absolute', top: 8, right: 9, width: 10, height: 10, borderRadius: 5, backgroundColor: colors.brand, borderWidth: 2, borderColor: colors.ink },
  mic: { width: MIC, height: MIC, borderRadius: MIC / 2, backgroundColor: colors.brand, alignItems: 'center', justifyContent: 'center' },
})
