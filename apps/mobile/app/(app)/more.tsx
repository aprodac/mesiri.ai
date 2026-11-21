import * as React from 'react'
import { ScrollView, StyleSheet, Text, View } from 'react-native'
import { useRouter } from 'expo-router'
import { Building2, LogOut } from 'lucide-react-native'
import { LANGS, useWords } from '../../src/lib/i18n'
import { personName, useSession, useSite } from '../../src/lib/session'
import { Button, Card, Chip, Screen, TopBar } from '../../src/components/ui'
import { colors, font, space } from '../../src/theme'

export default function More() {
  const { t, lang, setLang } = useWords()
  const { me, signOut } = useSession()
  const { current } = useSite()
  const router = useRouter()
  return (
    <Screen>
      <TopBar />
      <ScrollView contentContainerStyle={styles.body}>
        <Text style={font.title}>{t.more}</Text>
        <Card style={{ padding: space.lg, gap: space.md }}>
          <Text style={font.heading}>{t.switchSite}</Text>
          <Text style={font.body}>{current ? `${current.project.name} · ${current.site.name}` : '—'}</Text>
          <Button kind="secondary" label={t.switchSite} icon={<Building2 size={18} color={colors.ink} />} onPress={() => router.push('/switch-site')} />
        </Card>
        <Card style={{ padding: space.lg, gap: space.md }}>
          <Text style={font.heading}>{t.language}</Text>
          <View style={styles.chips}>
            {LANGS.map((l) => (
              <Chip key={l.id} label={l.name} selected={lang === l.id} onPress={() => setLang(l.id)} />
            ))}
          </View>
          <Text style={font.small}>{t.languageNote}</Text>
        </Card>
        <Card style={{ padding: space.lg, gap: space.md }}>
          <Text style={font.small}>{t.signedInAs}</Text>
          <Text style={font.heading}>{personName(me)}</Text>
          <Text style={font.small}>{me?.org_name ?? me?.organization_name ?? ''}</Text>
          <Button kind="secondary" label={t.signOut} icon={<LogOut size={18} color={colors.ink} />} onPress={() => void signOut()} />
        </Card>
      </ScrollView>
    </Screen>
  )
}

const styles = StyleSheet.create({
  body: { paddingHorizontal: space.lg, paddingBottom: 40, gap: space.md },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
})
