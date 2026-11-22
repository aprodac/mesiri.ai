import * as React from 'react'
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native'
import { useRouter } from 'expo-router'
import { useQuery } from '@tanstack/react-query'
import { Plus } from 'lucide-react-native'
import { useWords } from '../../src/lib/i18n'
import { fetchStock, type StockRow } from '../../src/lib/mesiri'
import { useSite } from '../../src/lib/session'
import { ApiError } from '../../src/lib/api'
import { kept } from '../../src/lib/kept'
import { Button, Card, CategoryTile, Label, Loading, Notice, PageHero, Screen, SectionHead, StateMark, TimeChip } from '../../src/components/ui'
import { category, colors, family, font, space } from '../../src/theme'

// The site's stock: running low first (it counts what is on order), days left at this week's use.

const num = (v: string | undefined | null) => Number(v ?? 0) || 0
const show = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/0+$/, '').replace(/\.$/, ''))

export default function SiteStock() {
  const { t } = useWords()
  const router = useRouter()
  const { current } = useSite()
  const siteId = current?.site.id
  const projectId = current?.project.id
  const stock = useQuery({ queryKey: ['stock', siteId], queryFn: kept(`stock:${siteId}`, () => fetchStock(projectId as string, siteId as string)), enabled: !!siteId })

  const rows = [...(stock.data ?? [])]
    .filter((r) => r.site_id === siteId || r.site_id === null)
    .sort((a, b) => Number(b.running_low) - Number(a.running_low) || (a.days_left ?? 1e9) - (b.days_left ?? 1e9))
  const low = rows.filter((r) => r.running_low)

  const note = (r: StockRow) => {
    const parts: string[] = []
    if (r.running_low) parts.push(t.low)
    if (r.days_left !== null && r.days_left !== undefined) parts.push(t.daysLeft(Math.round(r.days_left)))
    else if (num(r.used) === 0) parts.push(t.notUsedThisWeek)
    if (num(r.on_order) > 0) parts.push(t.onOrder(show(num(r.on_order))))
    return parts.join(' · ')
  }

  return (
    <Screen>
      <ScrollView contentContainerStyle={styles.body} refreshControl={<RefreshControl refreshing={stock.isRefetching} onRefresh={() => stock.refetch()} />}>
        <PageHero title={t.stock} figure={rows.length || null} figureLabel={t.materialsWord}>
          {low.length ? (
            <View style={styles.heroNote}>
              <StateMark state="warn" size={20} />
              <Text style={styles.heroNoteText} numberOfLines={2}>
                {t.runningLow(low.length)} {low.slice(0, 2).map((r) => r.material_name).join(', ')}
              </Text>
            </View>
          ) : null}
        </PageHero>
        {stock.isLoading ? <Loading label={t.loading} /> : null}
        {stock.isError ? <Notice text={stock.error instanceof ApiError ? stock.error.message : t.couldNotLoad} /> : null}
        {stock.isSuccess && rows.length === 0 ? <Notice tone="info" text={t.noStock} /> : null}
        {rows.length ? (
          <View style={{ gap: space.sm }}>
            <SectionHead label={t.atThisSite} count={rows.length} />
            <Card>
              {rows.map((r, i) => {
                // How long it lasts at this week's use, against two weeks: a gauge, brick when running low.
                const days = r.days_left ?? null
                const fill = days === null ? 0 : Math.max(0.04, Math.min(1, days / GAUGE_DAYS))
                return (
                  <View key={r.material_id} style={[styles.row, i > 0 && styles.line]} accessible accessibilityLabel={`${r.material_name}, ${show(num(r.closing))} ${r.unit}. ${note(r)}`}>
                    <CategoryTile cat="material" size={36} />
                    <View style={{ flex: 1, minWidth: 0, gap: 5 }}>
                      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                        <Text style={styles.name} numberOfLines={1}>
                          {r.material_name}
                        </Text>
                        {r.running_low ? <TimeChip urgency="overdue" label={t.low.toUpperCase()} /> : null}
                      </View>
                      <View style={styles.gauge}>
                        <View style={[styles.gaugeFill, { width: `${fill * 100}%`, backgroundColor: r.running_low ? colors.danger : category.material.fg }]} />
                      </View>
                      <Text style={[font.tiny, r.running_low && { color: colors.warn }]} numberOfLines={1}>
                        {note(r)}
                      </Text>
                    </View>
                    <View style={styles.qty}>
                      <Text style={styles.figure}>{show(num(r.closing))}</Text>
                      <Label>{r.unit}</Label>
                    </View>
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

/** The gauge's full length: two weeks of stock. */
const GAUGE_DAYS = 14

const styles = StyleSheet.create({
  body: { paddingHorizontal: 12, paddingBottom: 24, gap: space.lg },
  heroNote: { flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: 'rgba(255,255,255,0.1)', borderRadius: 14, padding: 10 },
  heroNoteText: { flex: 1, fontFamily: family.body, fontSize: 13, color: '#fff' },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.md, minHeight: 76, paddingHorizontal: space.md, paddingVertical: 12 },
  line: { borderTopWidth: 1, borderTopColor: colors.lineSoft },
  name: { fontFamily: family.display, fontSize: 17, letterSpacing: 0.2, color: colors.ink, flexShrink: 1 },
  gauge: { height: 4, backgroundColor: colors.lineSoft, borderRadius: 2, overflow: 'hidden' },
  gaugeFill: { height: 4, borderRadius: 2 },
  qty: { alignItems: 'flex-end', minWidth: 56 },
  figure: { fontFamily: family.mono, fontSize: 18, color: colors.ink },
})
