import * as React from 'react'
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native'
import { useRouter } from 'expo-router'
import { useQuery } from '@tanstack/react-query'
import { Plus } from 'lucide-react-native'
import { useWords } from '../../src/lib/i18n'
import { fetchRequests, type MaterialRequest } from '../../src/lib/mesiri'
import { useSite } from '../../src/lib/session'
import { ApiError } from '../../src/lib/api'
import { kept } from '../../src/lib/kept'
import { Button, Card, Label, Loading, Notice, Screen, TopBar } from '../../src/components/ui'
import { colors, family, font, space } from '../../src/theme'

// What this site asked for, and the office's answer. Asking is by voice (Mesiri's ask_for_material).

/** A request's state as a small square and a word: yellow while it waits, ink when it is on its way, green when it came. */
const TONE: Record<string, { mark: string; fg: string }> = {
  waiting: { mark: colors.brand, fg: colors.brandInk },
  ordered: { mark: colors.ink, fg: colors.ink },
  sent: { mark: colors.ink, fg: colors.ink },
  done: { mark: colors.done, fg: colors.done },
  rejected: { mark: colors.warn, fg: colors.warn },
  cancelled: { mark: colors.faint, fg: colors.muted },
}

const qty = (v: string) => {
  const n = Number(v)
  return Number.isFinite(n) ? (Number.isInteger(n) ? String(n) : String(+n.toFixed(2))) : v
}

export default function Requests() {
  const { t, lang } = useWords()
  const router = useRouter()
  const { current } = useSite()
  const siteId = current?.site.id
  const projectId = current?.project.id
  const list = useQuery({ queryKey: ['requests', siteId], queryFn: kept(`requests:${siteId}`, () => fetchRequests(projectId as string, siteId as string)), enabled: !!siteId })
  const items = list.data?.items ?? []

  const date = (d: string) => new Date(d.length === 10 ? `${d}T12:00:00` : d).toLocaleDateString(lang === 'ml' ? 'ml-IN' : 'en-IN', { day: 'numeric', month: 'short' })

  const detail = (r: MaterialRequest) =>
    [r.needed_by ? t.neededBy(date(r.needed_by)) : null, r.orders[0] ? `${r.orders[0].ref} · ${r.orders[0].vendor_name}` : null, r.decision_note]
      .filter(Boolean)
      .join(' · ')

  return (
    <Screen>
      <TopBar />
      <ScrollView contentContainerStyle={styles.body} refreshControl={<RefreshControl refreshing={list.isRefetching} onRefresh={() => list.refetch()} />}>
        <View style={styles.hero}>
          <Label>{items.length ? String(items.length) : t.site}</Label>
          <Text style={font.display}>{t.requests}</Text>
        </View>
        {list.isLoading ? <Loading label={t.loading} /> : null}
        {list.isError ? <Notice text={list.error instanceof ApiError ? list.error.message : t.couldNotLoad} /> : null}
        {list.isSuccess && items.length === 0 ? <Notice tone="info" text={t.noRequests} /> : null}
        {items.length ? (
          <Card>
            {items.map((r, i) => {
              const tone = TONE[r.status] ?? TONE.waiting
              return (
                <View key={r.id} style={[styles.row, i > 0 && styles.line]}>
                  <View style={styles.rowTop}>
                    <Label>
                      {r.ref} · {date(r.created_at)}
                      {r.requested_by_name ? ` · ${r.requested_by_name}` : ''}
                    </Label>
                    <View style={styles.status}>
                      <View style={[styles.statusMark, { backgroundColor: tone.mark }]} />
                      <Label style={{ color: tone.fg }}>{t.status[r.status] ?? r.status}</Label>
                    </View>
                  </View>
                  <Text style={styles.what}>{r.lines.map((l) => `${qty(l.quantity)} ${l.unit_name || l.unit} ${l.material}`).join(', ')}</Text>
                  {detail(r) ? <Text style={font.small}>{detail(r)}</Text> : null}
                </View>
              )
            })}
          </Card>
        ) : null}
        <Button label={t.askForMaterial} icon={<Plus size={20} color={colors.brand} strokeWidth={2.4} />} onPress={() => router.push('/speak')} />
      </ScrollView>
    </Screen>
  )
}

const styles = StyleSheet.create({
  body: { paddingHorizontal: space.lg, paddingBottom: 48, gap: space.lg },
  hero: { gap: 4, paddingTop: space.sm },
  row: { gap: 6, paddingHorizontal: space.lg, paddingVertical: 14 },
  rowTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: space.md },
  line: { borderTopWidth: 1, borderTopColor: colors.lineSoft },
  what: { fontFamily: family.displaySemi, fontSize: 16, lineHeight: 21, letterSpacing: -0.2, color: colors.ink },
  status: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  statusMark: { width: 8, height: 8, borderRadius: 1 },
})
