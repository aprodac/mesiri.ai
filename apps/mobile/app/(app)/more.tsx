import * as React from 'react'
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native'
import { useRouter } from 'expo-router'
import { ChevronRight, LogOut } from 'lucide-react-native'
import { LANGS, useWords } from '../../src/lib/i18n'
import { personName, useSession, useSite } from '../../src/lib/session'
import { Button, Chip, Label, Screen, SectionHead, TopBar } from '../../src/components/ui'
import { colors, family, font, space } from '../../src/theme'

export default function More() {
  const { t, lang, setLang } = useWords()
  const { me, signOut } = useSession()
  const { current } = useSite()
  const router = useRouter()
  return (
    <Screen>
      <TopBar />
      <ScrollView contentContainerStyle={styles.body}>
        <View style={styles.hero}>
          <Label>{me?.org_name ?? me?.organization_name ?? ''}</Label>
          <Text style={font.display}>{t.more}</Text>
        </View>

        <View style={styles.section}>
          <SectionHead label={t.switchSite} />
          <Pressable
            accessibilityRole="button"
            onPress={() => router.push('/switch-site')}
            style={({ pressed }) => [styles.link, pressed && { opacity: 0.6 }]}
          >
            <View style={{ flex: 1, gap: 2 }}>
              <Label>{current?.project.name ?? '—'}</Label>
              <Text style={styles.big}>{current?.site.name ?? '—'}</Text>
            </View>
            <ChevronRight size={20} color={colors.ink} />
          </Pressable>
        </View>

        <View style={styles.section}>
          <SectionHead label={t.language} />
          <View style={styles.chips}>
            {LANGS.map((l) => (
              <Chip key={l.id} label={l.name} selected={lang === l.id} onPress={() => setLang(l.id)} />
            ))}
          </View>
          <Text style={font.small}>{t.languageNote}</Text>
        </View>

        <View style={styles.section}>
          <SectionHead label={t.signedInAs} />
          <Text style={styles.big}>{personName(me)}</Text>
          <Button kind="secondary" label={t.signOut} icon={<LogOut size={18} color={colors.ink} />} onPress={() => void signOut()} />
        </View>
      </ScrollView>
    </Screen>
  )
}

const styles = StyleSheet.create({
  body: { paddingHorizontal: space.lg, paddingBottom: 48, gap: space.xxl },
  hero: { gap: 4, paddingTop: space.sm },
  section: { gap: space.md },
  link: { flexDirection: 'row', alignItems: 'center', minHeight: 56 },
  big: { fontFamily: family.displaySemi, fontSize: 20, lineHeight: 25, letterSpacing: -0.3, color: colors.ink },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
})
