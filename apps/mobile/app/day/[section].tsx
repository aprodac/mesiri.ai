import * as React from 'react'
import { ScrollView, StyleSheet, Text, View } from 'react-native'
import { useLocalSearchParams, useRouter } from 'expo-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ClipboardPen, Keyboard, Mic } from 'lucide-react-native'
import { useWords } from '../../src/lib/i18n'
import { fetchSiteDay, setConditions, type Weather } from '../../src/lib/mesiri'
import { todayFor, useSession, useSite } from '../../src/lib/session'
import { amount, reportOf, SECTION_CATEGORY, sectionTitle, SECTIONS, words, type Section } from '../../src/lib/day'
import { ApiError } from '../../src/lib/api'
import { kept } from '../../src/lib/kept'
import { BackHeader, Button, Card, Chip, Loading, Notice, Screen, Label } from '../../src/components/ui'
import { colors, family, font, space } from '../../src/theme'

// One row of Today opened: what was told for it today, and the way to tell more (speak or type).
// Weather is a direct tap, saved through the site day's own route (PATCH conditions).

/** MOB-05: the rows with a form of their own (the rest are told by voice or typed to Mesiri). */
const FORMS: Partial<Record<Section, 'received' | 'used' | 'problem'>> = { received: 'received', used: 'used', issues: 'problem' }

const num = (v: string | null | undefined) => Number(v ?? 0) || 0
const show = (n: number) => (Number.isInteger(n) ? String(n) : String(+n.toFixed(2)))

const WEATHERS: { id: Weather; en: string; ml: string }[] = [
  { id: 'sunny', en: 'Sunny', ml: 'വെയിൽ' },
  { id: 'cloudy', en: 'Cloudy', ml: 'മേഘം' },
  { id: 'rainy', en: 'Rain', ml: 'മഴ' },
  { id: 'windy', en: 'Windy', ml: 'കാറ്റ്' },
  { id: 'extreme_heat', en: 'Very hot', ml: 'കടുത്ത ചൂട്' },
]
const WORKING: { id: 'full' | 'half' | 'none'; en: string; ml: string }[] = [
  { id: 'full', en: 'Full day', ml: 'മുഴുവൻ ദിവസം' },
  { id: 'half', en: 'Half day', ml: 'അര ദിവസം' },
  { id: 'none', en: 'No work', ml: 'പണിയില്ല' },
]

export default function DaySection() {
  const { t, lang } = useWords()
  const router = useRouter()
  const client = useQueryClient()
  const { me } = useSession()
  const { current } = useSite()
  const params = useLocalSearchParams<{ section: string }>()
  const section = (SECTIONS as string[]).includes(params.section ?? '') ? (params.section as Section) : 'labour'
  const date = todayFor(me)
  const siteId = current?.site.id
  const day = useQuery({ queryKey: ['site-day', siteId, date], queryFn: kept(`site-day:${siteId}:${date}`, () => fetchSiteDay(siteId as string, date)), enabled: !!siteId })

  const conditions = useMutation({
    mutationFn: (body: { weather?: Weather; site_working?: 'full' | 'half' | 'none' }) => setConditions(siteId as string, date, body),
    onSuccess: () => client.invalidateQueries({ queryKey: ['site-day'] }),
  })

  const lines: { title: string; detail?: string | null; draft?: boolean }[] = []
  if (day.data) {
    const report = reportOf(day.data)
    if (section === 'labour') {
      for (const trade of report.labour.trades) lines.push({ title: `${trade.headcount} ${trade.trade}` })
      for (const item of day.data.items.filter((i) => i.section === 'labour')) lines.push({ title: item.title ?? '', detail: item.detail, draft: item.review === 'draft' })
    } else if (section === 'work' || section === 'issues') {
      for (const item of day.data.items.filter((i) => i.section === section)) {
        const q = item.quantities?.map((x) => `${amount(x.quantity)} ${x.unit}`).join(', ')
        lines.push({ title: words(item.title), detail: [q, item.detail, words(item.status)].filter(Boolean).join(' · '), draft: item.review === 'draft' })
      }
    } else if (section === 'received' || section === 'used') {
      for (const m of report.materials.filter((x) => num(x[section]) > 0)) {
        lines.push({ title: `${show(num(m[section]))} ${m.unit ?? ''} ${m.material_name ?? ''}`, detail: m.closing !== null ? `Stock ${show(num(m.closing))} ${m.unit ?? ''}` : null })
      }
    } else if (section === 'photos') {
      const n = day.data.day?.photos ?? report.evidence_count
      if (n) lines.push({ title: t.photosToday(n) })
    }
  }
  const report = day.data ? reportOf(day.data) : null

  return (
    <Screen>
      <BackHeader cat={SECTION_CATEGORY[section]} title={sectionTitle(section, t)} subtitle={current ? `${current.project.name} · ${current.site.name}` : undefined} />
      <ScrollView contentContainerStyle={styles.body}>
        {day.isLoading ? <Loading label={t.loading} /> : null}
        {day.isError ? <Notice text={day.error instanceof ApiError ? day.error.message : t.couldNotLoad} /> : null}

        {section === 'conditions' && report ? (
          <Card style={{ padding: space.lg, gap: space.md }}>
            <View style={styles.chips}>
              {WEATHERS.map((w) => (
                <Chip key={w.id} label={lang === 'ml' ? w.ml : w.en} selected={report.conditions.weather === w.id} onPress={() => conditions.mutate({ weather: w.id })} />
              ))}
            </View>
            <View style={styles.chips}>
              {WORKING.map((w) => (
                <Chip key={w.id} label={lang === 'ml' ? w.ml : w.en} selected={report.conditions.site_working === w.id} onPress={() => conditions.mutate({ site_working: w.id })} />
              ))}
            </View>
            {conditions.isError ? <Text style={{ color: colors.danger }}>{conditions.error instanceof ApiError ? conditions.error.message : t.couldNotLoad}</Text> : null}
            {report.conditions.tomorrow_plan ? <Text style={font.small}>Tomorrow: {report.conditions.tomorrow_plan}</Text> : null}
          </Card>
        ) : null}

        {section !== 'conditions' && day.isSuccess ? (
          lines.length ? (
            <Card>
              {lines.map((line, i) => (
                <View key={i} style={[styles.row, i > 0 && styles.line]}>
                  <View style={{ flex: 1, gap: 2 }}>
                    <Text style={styles.title}>{line.title}</Text>
                    {line.detail ? <Text style={font.tiny}>{line.detail}</Text> : null}
                  </View>
                  {line.draft ? <Label style={{ color: colors.todo }}>{t.draftMark}</Label> : null}
                </View>
              ))}
            </Card>
          ) : (
            <Notice tone="info" text={t.notToldYet} />
          )
        ) : null}

        {FORMS[section] ? (
          <Button
            kind="accent"
            label={t.fillForm}
            icon={<ClipboardPen size={20} color={colors.ink} strokeWidth={2} />}
            onPress={() => router.push({ pathname: '/form/[kind]', params: { kind: FORMS[section] as string } })}
          />
        ) : null}
        <Button
          kind={FORMS[section] ? 'secondary' : 'accent'}
          label={t.speakToMesiri}
          icon={<Mic size={20} color={colors.ink} strokeWidth={2} />}
          onPress={() => router.push('/speak')}
        />
        <Button kind="secondary" label={t.typeInstead} icon={<Keyboard size={20} color={colors.ink} />} onPress={() => router.push({ pathname: '/speak', params: { typing: '1' } })} />
      </ScrollView>
    </Screen>
  )
}

const styles = StyleSheet.create({
  body: { paddingHorizontal: space.lg, paddingBottom: 48, gap: space.md },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.md, minHeight: 60, paddingHorizontal: space.lg, paddingVertical: 10 },
  title: { fontFamily: family.displaySemi, fontSize: 16, lineHeight: 21, letterSpacing: -0.2, color: colors.ink },
  line: { borderTopWidth: 1, borderTopColor: colors.lineSoft },
})
