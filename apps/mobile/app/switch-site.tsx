import * as React from 'react'
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native'
import { useRouter } from 'expo-router'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { useWords } from '../src/lib/i18n'
import { useSite } from '../src/lib/session'
import { Label, StatusMark } from '../src/components/ui'
import { colors, family, font, space } from '../src/theme'

// The sheet to change the working site: every site of every project this person is on, grouped by project.

export default function SwitchSite() {
  const { t } = useWords()
  const router = useRouter()
  const insets = useSafeAreaInsets()
  const { places, current, choose } = useSite()
  const close = () => (router.canGoBack() ? router.back() : router.replace('/'))
  const projects = [...new Map(places.map((p) => [p.project.id, p.project])).values()]
  return (
    <View style={styles.shade}>
      <Pressable accessibilityRole="button" accessibilityLabel={t.close} style={{ flex: 1 }} onPress={close} />
      <View style={[styles.sheet, { paddingBottom: Math.max(insets.bottom, 24) }]}>
        <View style={styles.handle} />
        <Text style={font.title}>{t.switchSite}</Text>
        <ScrollView style={{ maxHeight: 460 }} contentContainerStyle={{ gap: space.lg }}>
          {projects.map((project) => (
            <View key={project.id} style={{ gap: 4 }}>
              <Label>{project.name}</Label>
              {places
                .filter((p) => p.project.id === project.id)
                .map((p) => {
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
                      style={({ pressed }) => [styles.place, pressed && { backgroundColor: colors.sand }]}
                    >
                      <Text style={[styles.name, on && { color: colors.ink }]}>{p.site.name}</Text>
                      {on ? <StatusMark tone="done" /> : null}
                    </Pressable>
                  )
                })}
            </View>
          ))}
          {places.length === 0 ? <Text style={font.body}>{t.noSites}</Text> : null}
        </ScrollView>
      </View>
    </View>
  )
}

const styles = StyleSheet.create({
  shade: { flex: 1, backgroundColor: 'rgba(20,21,24,0.45)' },
  sheet: { backgroundColor: colors.ground, borderTopLeftRadius: 16, borderTopRightRadius: 16, padding: space.lg, gap: space.lg },
  handle: { width: 36, height: 4, borderRadius: 2, backgroundColor: colors.field, alignSelf: 'center' },
  place: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', minHeight: 56, borderBottomWidth: 1, borderBottomColor: colors.line },
  name: { fontFamily: family.displaySemi, fontSize: 18, letterSpacing: -0.2, color: colors.inkSoft },
})
