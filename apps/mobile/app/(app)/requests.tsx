import * as React from 'react'
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native'
import { useRouter } from 'expo-router'
import { useQuery } from '@tanstack/react-query'
import { Plus } from 'lucide-react-native'
import { useWords } from '../../src/lib/i18n'
import { fetchRequests, type MaterialRequest } from '../../src/lib/mesiri'
import { useSite } from '../../src/lib/session'
import { ApiError } from '../../src/lib/api'
import { Button, Card, Loading, Notice, Screen, TopBar } from '../../src/components/ui'
import { colors, font, space } from '../../src/theme'

// What this site asked for, and the office's answer. Asking is by voice (Mesiri's ask_for_material).

const TONE: Record<string, { bg: string; fg: string }> = {
  waiting: { bg: colors.todoSoft, fg: colors.todo },
  ordered: { bg: colors.brandSoft, fg: colors.brandInk },
  sent: { bg: colors.brandSoft, fg: colors.brandInk },
  done: { bg: colors.doneSoft, fg: colors.done },
  rejected: { bg: colors.warnSoft, fg: colors.warn },
  cancelled: { bg: colors.sand, fg: colors.muted },
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
  const list = useQuery({ queryKey: ['requests', siteId], queryFn: () => fetchRequests(projectId as string, siteId as string), enabled: !!siteId })
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
        <Text style={font.title}>{t.requests}</Text>
        {list.isLoading ? <Loading label={t.loading} /> : null}
        {list.isError ? <Notice text={list.error instanceof ApiError ? list.error.message : t.couldNotLoad} /> : null}
        {list.isSuccess && items.length === 0 ? <Notice tone="info" text={t.noRequests} /> : null}
        {items.length ? (
          <Card>
            {items.map((r, i) => {
              const tone = TONE[r.status] ?? TONE.waiting
              return (
                <View key={r.id} style={[styles.row, i > 0 && styles.line]}>
                  <View style={{ flex: 1, minWidth: 0, gap: 3 }}>
                    <Text style={font.tiny}>
                      {r.ref} · {date(r.created_at)}
                      {r.requested_by_name ? ` · ${r.requested_by_name}` : ''}
                    </Text>
                    <Text style={font.strong}>{r.lines.map((l) => `${qty(l.quantity)} ${l.unit_name || l.unit} ${l.material}`).join(', ')}</Text>
                    {detail(r) ? <Text style={font.tiny}>{detail(r)}</Text> : null}
                  </View>
                  <View style={[styles.status, { backgroundColor: tone.bg }]}>
                    <Text style={{ color: tone.fg, fontSize: 12, fontWeight: '700' }}>{t.status[r.status] ?? r.status}</Text>
                  </View>
                </View>
              )
            })}
          </Card>
        ) : null}
        <Button kind="dark" label={t.askForMaterial} icon={<Plus size={20} color={colors.brand} />} onPress={() => router.push('/speak')} />
      </ScrollView>
    </Screen>
  )
}

const styles = StyleSheet.create({
  body: { paddingHorizontal: space.lg, paddingBottom: 40, gap: space.md },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.md, minHeight: 64, paddingHorizontal: 14, paddingVertical: 10 },
  line: { borderTopWidth: 1, borderTopColor: colors.lineSoft },
  status: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999 },
})
