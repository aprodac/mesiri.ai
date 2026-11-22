import * as React from 'react'
import { Alert, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native'
import { useRouter } from 'expo-router'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useWords } from '../../src/lib/i18n'
import { fetchMaterials, fetchRequests, fetchSiteDay, fetchUnits, sendDprNow, type MaterialRequest } from '../../src/lib/mesiri'
import { kept } from '../../src/lib/kept'
import { personName, todayFor, useSession, useSite } from '../../src/lib/session'
import { dayLines, reportOf } from '../../src/lib/day'
import { useSignal } from '../../src/lib/outbox'
import { ApiError } from '../../src/lib/api'
import { ArrowUpRight } from 'lucide-react-native'
import { Button, CategoryTile, DayRow, Label, Loading, Notice, ScaleBar, Screen, SectionHead, SiteButton, Status, TimeChip, TitleBlock } from '../../src/components/ui'
import { OutboxPanel } from '../../src/components/OutboxPanel'
import { category, colors, family, font, radius, space, type Category } from '../../src/theme'

export default function Today() {
  const { t, lang } = useWords()
  const router = useRouter()
  const { me } = useSession()
  const { current, places, loading: placesLoading, error: placesError, reload } = useSite()
  const online = useSignal()
  const date = todayFor(me)
  const siteId = current?.site.id

  const day = useQuery({
    queryKey: ['site-day', siteId, date],
    queryFn: kept(`site-day:${siteId}:${date}`, () => fetchSiteDay(siteId as string, date)),
    enabled: !!siteId,
    refetchInterval: 60_000,
  })

  // MOB-07: what the forms need, loaded while there is signal (and kept), so a form opened on site without it works.
  const signedIn = !!me
  useQuery({ queryKey: ['materials'], queryFn: kept('materials', fetchMaterials), staleTime: 10 * 60_000, enabled: signedIn })
  useQuery({ queryKey: ['units'], queryFn: kept('units', fetchUnits), staleTime: 60 * 60_000, enabled: signedIn })

  const send = useMutation({
    mutationFn: () => sendDprNow(current!.project.id),
    onError: (e) => Alert.alert(t.todaysReport, e instanceof ApiError ? e.message : String(e)),
  })

  const confirmSend = () =>
    Alert.alert(t.todaysReport, t.reportGoes, [
      { text: t.close, style: 'cancel' },
      { text: t.sendNow, onPress: () => send.mutate() },
    ])

  // Needs you: the office answered a request, or a problem is still open (more kinds come with MOB-15).
  const requests = useQuery({
    queryKey: ['requests', siteId],
    queryFn: kept(`requests:${siteId}`, () => fetchRequests(current!.project.id, siteId as string)),
    enabled: !!siteId,
  })

  const lines = day.data ? dayLines(day.data, t) : []
  const done = lines.filter((l) => l.tone !== 'todo').length
  const drafts = day.data?.drafts ?? 0
  const dateLabel = new Date(`${date}T12:00:00`).toLocaleDateString(lang === 'ml' ? 'ml-IN' : 'en-IN', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  })
  const weather = day.data ? reportOf(day.data).conditions.weather : null

  type Need = { key: string; cat: Category; urgency: 'answered' | 'open' | 'overdue'; chip: string; what: string; ref: string; act: string; go: () => void }
  const needs: Need[] = []
  const answered = (requests.data?.items ?? []).filter((r: MaterialRequest) => r.status === 'ordered' || r.status === 'sent' || r.status === 'rejected').slice(0, 2)
  for (const r of answered) {
    const line = r.lines[0]
    needs.push({
      key: r.id,
      cat: 'material',
      urgency: r.status === 'rejected' ? 'open' : 'answered',
      chip: (t.status[r.status] ?? r.status).toUpperCase(),
      what: line ? `${line.material} ${Number(line.quantity) || line.quantity} ${line.unit_name || line.unit}` : r.ref,
      ref: [r.ref, r.orders[0]?.vendor_name, r.decision_note].filter(Boolean).join(' · '),
      act: t.see,
      go: () => router.push('/requests'),
    })
  }
  const openIssues = day.data?.day?.open_issues ?? 0
  if (openIssues) {
    const first = day.data?.items.find((i) => i.section === 'issues')
    needs.push({
      key: 'issues',
      cat: 'problem',
      urgency: 'open',
      chip: t.openProblems(openIssues).toUpperCase(),
      what: first?.detail || first?.title || t.problems,
      ref: t.problems,
      act: t.update,
      go: () => router.push({ pathname: '/day/[section]', params: { section: 'issues' } }),
    })
  }

  return (
    <Screen>
      <ScrollView
        contentContainerStyle={styles.body}
        refreshControl={<RefreshControl refreshing={day.isRefetching} onRefresh={() => (siteId ? day.refetch() : reload())} />}
      >
        <TitleBlock grid style={{ marginTop: space.sm }}>
          <View style={styles.titleTop}>
            <SiteButton light sub={[current?.project.name, dateLabel].filter(Boolean).join(' · ')} />
            <Pressable
              accessibilityRole="button"
              onPress={() => router.push({ pathname: '/day/[section]', params: { section: 'conditions' } })}
              style={styles.weather}
            >
              <CategoryTile cat="weather" size={28} />
              <View>
                <Text style={styles.weatherTop}>{weather ? t.weatherWord[weather] ?? weather : t.weatherAsk}</Text>
                <Status ok={online} label={online ? t.online : t.offline} light />
              </View>
            </Pressable>
          </View>
          <View style={styles.todayRow}>
            <Text style={styles.today}>{t.today.toUpperCase()}</Text>
            <View style={{ alignItems: 'flex-end' }}>
              <Text style={styles.count}>
                {lines.length ? done : '–'}
                <Text style={{ color: colors.blueprintMid }}>/{lines.length || '–'}</Text>
              </Text>
              <Label tone="light">{t.partsTold}</Label>
            </View>
          </View>
          {lines.length ? <ScaleBar parts={lines.map((l) => ({ cat: l.cat, state: l.tone }))} /> : null}
          <Pressable accessibilityRole="button" onPress={confirmSend} disabled={send.isPending || send.isSuccess} style={styles.sendRow}>
            <Text style={styles.sendNote} numberOfLines={1}>
              {drafts ? t.toCheck(drafts) : t.reportGoes}
            </Text>
            <Text style={styles.sendLink}>{send.isSuccess ? t.sent : t.sendNow}</Text>
            {send.isSuccess ? null : <ArrowUpRight size={14} color={colors.brand} strokeWidth={2.4} />}
          </Pressable>
        </TitleBlock>

        <OutboxPanel />
        {placesLoading ? <Loading label={t.loading} /> : null}
        {!placesLoading && placesError ? <Notice text={t.couldNotLoad} /> : null}
        {!placesLoading && !placesError && places.length === 0 ? <Notice tone="info" text={t.noSites} /> : null}

        {needs.length ? (
          <View style={{ gap: space.sm }}>
            <SectionHead label={t.needsYou} count={needs.length} />
            {needs.map((n) => (
              <Pressable key={n.key} accessibilityRole="button" onPress={n.go} style={({ pressed }) => [styles.need, pressed && { opacity: 0.7 }]}>
                <CategoryTile cat={n.cat} size={40} />
                <View style={{ flex: 1, minWidth: 0, gap: 3 }}>
                  <TimeChip urgency={n.urgency} label={n.chip} />
                  <Text style={font.strong} numberOfLines={1}>
                    {n.what}
                  </Text>
                  <Text style={styles.ref} numberOfLines={1}>
                    {n.ref}
                  </Text>
                </View>
                <Button small kind={n.urgency === 'answered' ? 'secondary' : 'primary'} label={n.act} onPress={n.go} />
              </Pressable>
            ))}
          </View>
        ) : null}

        {siteId ? (
          <>
            {day.isLoading ? <Loading label={t.loading} /> : null}
            {day.isError ? <Notice text={day.error instanceof ApiError ? day.error.message : t.couldNotLoad} /> : null}
            {lines.length ? (
              <View style={{ gap: space.sm }}>
                <SectionHead label={t.theDay} />
                <View style={styles.day}>
                  {lines.map((line, i) => (
                    <DayRow
                      key={line.section}
                      cat={line.cat}
                      last={i === lines.length - 1}
                      title={line.title}
                      detail={line.tone === 'todo' ? t.notToldShort : line.detail}
                      figure={line.figure}
                      state={line.tone}
                      tellLabel={t.tell}
                      onPress={() => router.push({ pathname: '/day/[section]', params: { section: line.section } })}
                    />
                  ))}
                </View>
              </View>
            ) : null}
          </>
        ) : null}
      </ScrollView>
    </Screen>
  )
}

const styles = StyleSheet.create({
  body: { paddingHorizontal: 12, paddingBottom: 24, gap: space.lg },
  titleTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', gap: space.sm },
  weather: { flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: 'rgba(255,255,255,0.12)', borderRadius: 14, paddingVertical: 6, paddingLeft: 6, paddingRight: 10 },
  weatherTop: { fontFamily: family.display, fontSize: 15, color: '#fff' },
  todayRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-end' },
  today: { fontFamily: family.display, fontSize: 44, lineHeight: 44, letterSpacing: 0.5, color: '#fff' },
  count: { fontFamily: family.display, fontSize: 28, lineHeight: 30, color: colors.brand },
  sendRow: { flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 32 },
  sendNote: { flex: 1, fontFamily: family.body, fontSize: 12, color: colors.blueprintSoft },
  sendLink: { fontFamily: family.display, fontSize: 14, color: colors.brand },
  need: { flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.line, borderRadius: radius.lg, padding: 10 },
  ref: { fontFamily: family.mono, fontSize: 11, color: colors.muted },
  day: { backgroundColor: colors.card, borderWidth: 1, borderColor: colors.line, borderRadius: radius.lg, paddingHorizontal: 2 },
})
