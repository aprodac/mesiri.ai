import * as React from 'react'
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native'
import { useRouter } from 'expo-router'
import { Building2, ChevronRight, Languages, LogOut } from 'lucide-react-native'
import { LANGS, useWords } from '../../src/lib/i18n'
import { personName, useSession, useSite } from '../../src/lib/session'
import { Button, Card, CategoryTile, Chip, Label, PageHero, Screen, SectionHead } from '../../src/components/ui'
import { colors, family, font, radius, space } from '../../src/theme'

// More: the same hero as every tab, then plain grouped cards (site, language, the person). Site and language are
// settings, not kinds of site work, so they carry a neutral blueprint icon, not a category tile.

function SettingIcon({ children }: { children: React.ReactNode }) {
  return <View style={styles.settingIcon}>{children}</View>
}

export default function More() {
  const { t, lang, setLang } = useWords()
  const { me, signOut } = useSession()
  const { current } = useSite()
  const router = useRouter()
  return (
    <Screen>
      <ScrollView contentContainerStyle={styles.body}>
        <PageHero title={t.more} />

        <View style={styles.section}>
          <SectionHead label={t.switchSite} />
          <Card>
            <Pressable accessibilityRole="button" onPress={() => router.push('/switch-site')} style={({ pressed }) => [styles.row, pressed && { backgroundColor: colors.sand }]}>
              <SettingIcon>
                <Building2 size={18} color={colors.blueprint} strokeWidth={1.9} />
              </SettingIcon>
              <View style={{ flex: 1, gap: 2 }}>
                <Label>{current?.project.name ?? '—'}</Label>
                <Text style={styles.big}>{current?.site.name ?? '—'}</Text>
              </View>
              <ChevronRight size={20} color={colors.ink} />
            </Pressable>
          </Card>
        </View>

        <View style={styles.section}>
          <SectionHead label={t.language} />
          <Card style={{ padding: space.md, gap: space.md }}>
            <View style={styles.rowPlain}>
              <SettingIcon>
                <Languages size={18} color={colors.blueprint} strokeWidth={1.9} />
              </SettingIcon>
              <View style={styles.chips}>
                {LANGS.map((l) => (
                  <Chip key={l.id} label={l.name} selected={lang === l.id} onPress={() => setLang(l.id)} />
                ))}
              </View>
            </View>
            <Text style={font.small}>{t.languageNote}</Text>
          </Card>
        </View>

        <View style={styles.section}>
          <SectionHead label={t.signedInAs} />
          <Card style={{ padding: space.md, gap: space.md }}>
            <View style={styles.rowPlain}>
              <CategoryTile cat="people" size={40} />
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={styles.big}>{personName(me)}</Text>
                <Label>{me?.org_name ?? me?.organization_name ?? ''}</Label>
              </View>
            </View>
            <Button kind="secondary" label={t.signOut} icon={<LogOut size={18} color={colors.ink} />} onPress={() => void signOut()} />
          </Card>
        </View>
      </ScrollView>
    </Screen>
  )
}

const styles = StyleSheet.create({
  body: { paddingHorizontal: 12, paddingBottom: 24, gap: space.xl },
  section: { gap: space.sm },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.md, minHeight: 64, paddingHorizontal: space.md },
  rowPlain: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  settingIcon: { width: 40, height: 40, borderRadius: 13, backgroundColor: colors.blueprintPale, alignItems: 'center', justifyContent: 'center' },
  big: { fontFamily: family.display, fontSize: 20, lineHeight: 24, letterSpacing: 0.2, color: colors.ink },
  chips: { flex: 1, flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
})
