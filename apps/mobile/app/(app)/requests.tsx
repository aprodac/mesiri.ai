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
import { Button, Card, CategoryTile, Label, Loading, Notice, PageHero, Screen, SectionHead, StateMark, TimeChip } from '../../src/components/ui'
import { colors, family, font, space } from '../../src/theme'

// What this site asked for, and the office's answer. Asking is by voice (Mesiri's ask_for_material).

/** A request's status in the cue system: waiting = the waiting mark; ordered / sent = ANSWERED (solid blueprint);
 * received = done; not approved = brick; cancelled = outlined. */
const STATUS: Record<string, { mark?: 'waiting' | 'done'; chip?: 'answered' | 'overdue' | 'tomorrow' }> = {
  waiting: { mark: 'waiting' },
  ordered: { chip: 'answered' },
  sent: { chip: 'answered' },
  done: { mark: 'done' },
  rejected: { chip: 'overdue' },
  cancelled: { chip: 'tomorrow' },
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

  const open = items.filter((r) => r.status === 'waiting' || r.status === 'ordered' || r.status === 'sent').length

  return (
    <Screen>
      <ScrollView contentContainerStyle={styles.body} refreshControl={<RefreshControl refreshing={list.isRefetching} onRefresh={() => list.refetch()} />}>
        <PageHero title={t.requests} figure={items.length ? open : null} figureLabel={t.openWord} />
        {list.isLoading ? <Loading label={t.loading} /> : null}
        {list.isError ? <Notice text={list.error instanceof ApiError ? list.error.message : t.couldNotLoad} /> : null}
        {list.isSuccess && items.length === 0 ? <Notice tone="info" text={t.noRequests} /> : null}
        {items.length ? (
          <View style={{ gap: space.sm }}>
            <SectionHead label={t.fromThisSite} count={items.length} />
            <Card>
              {items.map((r, i) => {
                const st = STATUS[r.status] ?? STATUS.waiting
                const word = (t.status[r.status] ?? r.status).toUpperCase()
                return (
                  <View key={r.id} style={[styles.row, i > 0 && styles.line]}>
                    <CategoryTile cat="material" size={36} />
                    <View style={{ flex: 1, minWidth: 0, gap: 4 }}>
                      <Text style={styles.ref}>
                        {r.ref} · {date(r.created_at)}
                        {r.requested_by_name ? ` · ${r.requested_by_name}` : ''}
                      </Text>
                      <Text style={styles.what}>{r.lines.map((l) => `${qty(l.quantity)} ${l.unit_name || l.unit} ${l.material}`).join(', ')}</Text>
                      {detail(r) ? <Text style={font.tiny}>{detail(r)}</Text> : null}
                      {st.chip ? <TimeChip urgency={st.chip} label={word} /> : <Label style={{ color: st.mark === 'done' ? colors.done : colors.blueprint }}>{word}</Label>}
                    </View>
                    {st.mark ? <StateMark state={st.mark} /> : null}
                  </View>
                )
              })}
            </Card>
          </View>
        ) : null}
        <Button kind="accent" label={t.askForMaterial} icon={<Plus size={20} color={colors.ink} strokeWidth={2.4} />} onPress={() => router.push('/speak')} />
      </ScrollView>
    </Screen>
  )
}

const styles = StyleSheet.create({
  body: { paddingHorizontal: 12, paddingBottom: 24, gap: space.lg },
  row: { flexDirection: 'row', alignItems: 'flex-start', gap: space.md, paddingHorizontal: space.md, paddingVertical: 14 },
  line: { borderTopWidth: 1, borderTopColor: colors.lineSoft },
  ref: { fontFamily: family.mono, fontSize: 11, color: colors.muted },
  what: { fontFamily: family.display, fontSize: 17, lineHeight: 21, letterSpacing: 0.2, color: colors.ink },
})
