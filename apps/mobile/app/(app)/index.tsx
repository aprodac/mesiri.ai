import * as React from 'react'
import { Alert, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native'
import { useRouter } from 'expo-router'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useWords } from '../../src/lib/i18n'
import { fetchSiteDay, sendDprNow } from '../../src/lib/mesiri'
import { personName, todayFor, useSession, useSite } from '../../src/lib/session'
import { dayLines } from '../../src/lib/day'
import { useOnline } from '../../src/lib/online'
import { ApiError } from '../../src/lib/api'
import { Card, DayRow, Loading, Notice, Screen, TopBar } from '../../src/components/ui'
import { colors, font, space } from '../../src/theme'

export default function Today() {
  const { t, lang } = useWords()
  const router = useRouter()
  const { me } = useSession()
  const { current, places, loading: placesLoading, error: placesError, reload } = useSite()
  const online = useOnline()
  const date = todayFor(me)
  const siteId = current?.site.id

  const day = useQuery({
    queryKey: ['site-day', siteId, date],
    queryFn: () => fetchSiteDay(siteId as string, date),
    enabled: !!siteId,
    refetchInterval: 60_000,
  })

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
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  })

  return (
    <Screen>
      <TopBar
        right={
          <View style={styles.online}>
            <View style={[styles.dot, { backgroundColor: online ? '#16a34a' : colors.warn }]} />
            <Text style={{ fontSize: 12, fontWeight: '600', color: online ? colors.done : colors.warn }}>
              {online ? t.online : t.offline}
            </Text>
          </View>
        }
      />
      <ScrollView
        contentContainerStyle={styles.body}
        refreshControl={<RefreshControl refreshing={day.isRefetching} onRefresh={() => (siteId ? day.refetch() : reload())} />}
      >
        <View>
          <Text style={font.small}>{dateLabel}</Text>
          <Text style={font.title}>{t.todayOnSite}</Text>
          {me ? <Text style={font.tiny}>{personName(me)}</Text> : null}
        </View>

        {placesLoading ? <Loading label={t.loading} /> : null}
        {!placesLoading && placesError ? <Notice text={t.couldNotLoad} /> : null}
        {!placesLoading && !placesError && places.length === 0 ? <Notice tone="info" text={t.noSites} /> : null}

        {siteId ? (
          <>
            <View style={styles.report}>
              <View style={styles.reportTop}>
                <Text style={{ color: '#fff', fontSize: 15, fontWeight: '600' }}>{t.todaysReport}</Text>
                <Text style={{ color: colors.brand, fontSize: 13, fontWeight: '700' }}>{lines.length ? t.doneOf(done, lines.length) : ''}</Text>
              </View>
              <View style={styles.track}>
                <View style={[styles.fill, { width: `${lines.length ? (done / lines.length) * 100 : 0}%` }]} />
              </View>
              <View style={styles.reportTop}>
                <Text style={{ color: '#d6d3cd', fontSize: 12, flex: 1 }}>{drafts ? t.toCheck(drafts) : t.reportGoes}</Text>
                <Pressable
                  accessibilityRole="button"
                  onPress={confirmSend}
                  disabled={send.isPending || send.isSuccess}
                  style={({ pressed }) => [styles.sendNow, pressed && { opacity: 0.7 }]}
                >
                  <Text style={{ color: '#fff', fontSize: 13, fontWeight: '700' }}>{send.isSuccess ? t.sent : t.sendNow}</Text>
                </Pressable>
              </View>
            </View>

            {day.isLoading ? <Loading label={t.loading} /> : null}
            {day.isError ? <Notice text={day.error instanceof ApiError ? day.error.message : t.couldNotLoad} /> : null}
            {lines.length ? (
              <Card>
                {lines.map((line, i) => (
                  <DayRow
                    key={line.section}
                    first={i === 0}
                    title={line.title}
                    detail={line.detail}
                    tone={line.tone}
                    onPress={() => router.push({ pathname: '/day/[section]', params: { section: line.section } })}
                  />
                ))}
              </Card>
            ) : null}
          </>
        ) : null}
      </ScrollView>
    </Screen>
  )
}

const styles = StyleSheet.create({
  body: { paddingHorizontal: space.lg, paddingBottom: 40, gap: space.md },
  online: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  report: { backgroundColor: colors.night, borderRadius: 18, padding: space.lg, gap: 10 },
  reportTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: space.md },
  track: { height: 8, borderRadius: 4, backgroundColor: colors.charcoal, overflow: 'hidden' },
  fill: { height: 8, backgroundColor: colors.brand },
  sendNow: { minHeight: 40, paddingHorizontal: 14, borderRadius: 12, borderWidth: 1, borderColor: '#5c5a5b', justifyContent: 'center' },
})
