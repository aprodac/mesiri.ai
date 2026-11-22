import * as React from 'react'
import { Alert, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native'
import { useRouter } from 'expo-router'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useWords } from '../../src/lib/i18n'
import { fetchMaterials, fetchSiteDay, fetchUnits, sendDprNow } from '../../src/lib/mesiri'
import { kept } from '../../src/lib/kept'
import { personName, todayFor, useSession, useSite } from '../../src/lib/session'
import { dayLines } from '../../src/lib/day'
import { useSignal } from '../../src/lib/outbox'
import { ApiError } from '../../src/lib/api'
import { ArrowUpRight } from 'lucide-react-native'
import { Card, DayRow, Label, Loading, Notice, Screen, SectionHead, Status, Tape, TopBar } from '../../src/components/ui'
import { OutboxPanel } from '../../src/components/OutboxPanel'
import { colors, family, font, space } from '../../src/theme'

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

  const lines = day.data ? dayLines(day.data, t) : []
  const done = lines.filter((l) => l.tone !== 'todo').length
  const drafts = day.data?.drafts ?? 0
  const dateLabel = new Date(`${date}T12:00:00`).toLocaleDateString(lang === 'ml' ? 'ml-IN' : 'en-IN', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  })

  return (
    <Screen>
      <TopBar right={<Status ok={online} label={online ? t.online : t.offline} />} />
      <ScrollView
        contentContainerStyle={styles.body}
        refreshControl={<RefreshControl refreshing={day.isRefetching} onRefresh={() => (siteId ? day.refetch() : reload())} />}
      >
        <View style={styles.hero}>
          <Label>{dateLabel}</Label>
          <Text style={font.display}>{t.today}</Text>
          {me ? <Text style={font.small}>{personName(me)}</Text> : null}
        </View>

        <OutboxPanel />
        {placesLoading ? <Loading label={t.loading} /> : null}
        {!placesLoading && placesError ? <Notice text={t.couldNotLoad} /> : null}
        {!placesLoading && !placesError && places.length === 0 ? <Notice tone="info" text={t.noSites} /> : null}

        {siteId ? (
          <>
            <View style={styles.report}>
              <SectionHead label={t.todaysReport} />
              <View style={styles.reportRow}>
                <View style={styles.count} accessibilityLabel={lines.length ? t.doneOf(done, lines.length) : ''}>
                  <Text style={font.bigFigure}>{lines.length ? done : '–'}</Text>
                  <Text style={[font.figure, { color: colors.faint }]}>/ {lines.length || '–'}</Text>
                </View>
                <Pressable
                  accessibilityRole="button"
                  onPress={confirmSend}
                  disabled={send.isPending || send.isSuccess}
                  style={({ pressed }) => [styles.sendNow, pressed && { opacity: 0.6 }]}
                >
                  <Text style={styles.sendNowText}>{send.isSuccess ? t.sent : t.sendNow}</Text>
                  {send.isSuccess ? null : <ArrowUpRight size={16} color={colors.ink} strokeWidth={2.2} />}
                </Pressable>
              </View>
              <Tape done={done} total={lines.length || 7} />
              <Text style={font.small}>{drafts ? t.toCheck(drafts) : t.reportGoes}</Text>
            </View>

            {day.isLoading ? <Loading label={t.loading} /> : null}
            {day.isError ? <Notice text={day.error instanceof ApiError ? day.error.message : t.couldNotLoad} /> : null}
            {lines.length ? (
              <View style={{ gap: space.md }}>
                <SectionHead label={t.theDay} />
                <Card>
                  {lines.map((line, i) => (
                    <DayRow
                      key={line.section}
                      index={i + 1}
                      first={i === 0}
                      title={line.title}
                      detail={line.detail}
                      tone={line.tone}
                      onPress={() => router.push({ pathname: '/day/[section]', params: { section: line.section } })}
                    />
                  ))}
                </Card>
              </View>
            ) : null}
          </>
        ) : null}
      </ScrollView>
    </Screen>
  )
}

const styles = StyleSheet.create({
  body: { paddingHorizontal: space.lg, paddingBottom: 48, gap: space.xl },
  hero: { gap: 4, paddingTop: space.sm },
  report: { gap: space.md },
  reportRow: { flexDirection: 'row', alignItems: 'flex-end', justifyContent: 'space-between' },
  count: { flexDirection: 'row', alignItems: 'baseline', gap: 6 },
  sendNow: { flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 44, paddingHorizontal: 14, borderRadius: 8, borderWidth: 1, borderColor: colors.ink },
  sendNowText: { fontFamily: family.displaySemi, fontSize: 15, color: colors.ink },
})
