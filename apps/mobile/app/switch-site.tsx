import * as React from 'react'
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native'
import { useRouter } from 'expo-router'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { Check } from 'lucide-react-native'
import { useWords } from '../src/lib/i18n'
import { useSite } from '../src/lib/session'
import { colors, font, radius, space } from '../src/theme'

// The sheet to change the working site: every site of every project this person is on.

export default function SwitchSite() {
  const { t } = useWords()
  const router = useRouter()
  const insets = useSafeAreaInsets()
  const { places, current, choose } = useSite()
  const close = () => (router.canGoBack() ? router.back() : router.replace('/'))
  return (
    <View style={styles.shade}>
      <Pressable accessibilityRole="button" accessibilityLabel={t.close} style={{ flex: 1 }} onPress={close} />
      <View style={[styles.sheet, { paddingBottom: Math.max(insets.bottom, 24) }]}>
        <View style={styles.handle} />
        <Text style={[font.heading, { fontSize: 20 }]}>{t.switchSite}</Text>
        <ScrollView style={{ maxHeight: 420 }} contentContainerStyle={{ gap: space.sm }}>
          {places.map((p) => {
            const on = p.site.id === current?.site.id
            return (
              <Pressable
                key={p.site.id}
                accessibilityRole="button"
                accessibilityState={{ selected: on }}
                onPress={() => {
                  choose(p.site.id)
                  close()
                }}
                style={({ pressed }) => [styles.place, on && styles.placeOn, pressed && { opacity: 0.7 }]}
              >
                <View style={{ flex: 1 }}>
                  <Text style={font.strong}>{p.site.name}</Text>
                  <Text style={font.tiny}>{p.project.name}</Text>
                </View>
                {on ? <Check size={22} color={colors.ink} strokeWidth={2.6} /> : null}
              </Pressable>
            )
          })}
          {places.length === 0 ? <Text style={font.body}>{t.noSites}</Text> : null}
        </ScrollView>
      </View>
    </View>
  )
}

const styles = StyleSheet.create({
  shade: { flex: 1, backgroundColor: 'rgba(26,29,33,0.55)' },
  sheet: { backgroundColor: colors.card, borderTopLeftRadius: 26, borderTopRightRadius: 26, padding: space.lg, gap: space.md },
  handle: { width: 44, height: 5, borderRadius: 3, backgroundColor: colors.field, alignSelf: 'center' },
  place: { flexDirection: 'row', alignItems: 'center', gap: space.md, minHeight: 60, paddingHorizontal: 14, paddingVertical: 8, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.line },
  placeOn: { borderWidth: 2, borderColor: colors.ink, backgroundColor: colors.brandSoft },
})
