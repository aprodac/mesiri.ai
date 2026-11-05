import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Boxes, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Callout, Segmented } from '@/components/dpr-page'
import { CHIP, qty } from '@/lib/site-day'
import { useSiteNames } from '@/lib/site-names'
import { cn, toLocalISODate } from '@/lib/utils'
import {
  categoryTree,
  fetchMaterialCategories,
  fetchStockSummary,
  formatMoney,
  type StockSummaryRow,
} from '@/lib/materials'
import { MaterialLedgerSheet } from './material-ledger-sheet'

// PRC-17d (mockup 5): materials by category. A card per main category -- how many items, how many are running low,
// what was spent -- then the chosen category's items with what the site held before the period, what came, what was
// used and what is left, and how long it lasts at this week's use. Money is shown only to the roles that see the
// company's spending; the API leaves it out for the rest. Built on GET /materials/stock-summary (PRC-17).

type Period = 'week' | 'month' | 'last_month' | 'custom'
const NONE = '__none__'

function periodDates(period: Period, from: string, to: string): { date_from?: string; date_to?: string } {
  const today = new Date()
  if (period === 'week') return {}
  if (period === 'month') return { date_from: toLocalISODate(new Date(today.getFullYear(), today.getMonth(), 1)), date_to: toLocalISODate(today) }
  if (period === 'last_month') {
    return {
      date_from: toLocalISODate(new Date(today.getFullYear(), today.getMonth() - 1, 1)),
      date_to: toLocalISODate(new Date(today.getFullYear(), today.getMonth(), 0)),
    }
  }
  return from && to ? { date_from: from, date_to: to } : {}
}

const sum = (values: (string | null)[]) => values.reduce((n, v) => n + (v ? Number(v) : 0), 0)
// How long the stock lasts, in words: 0 whole days is "under 1 day", not "~0 days".
const lasts = (days: number | null) => (days === null ? '' : days < 1 ? 'under 1 day' : `~${days} ${days === 1 ? 'day' : 'days'}`)

export function CategoryView({ projectId, siteId }: { projectId: string | null; siteId: string | null }) {
  const siteNames = useSiteNames()
  const [period, setPeriod] = React.useState<Period>('week')
  const [from, setFrom] = React.useState('')
  const [to, setTo] = React.useState('')
  const [chosen, setChosen] = React.useState<string | null>(null)
  const [opened, setOpened] = React.useState<StockSummaryRow | null>(null)
  const dates = periodDates(period, from, to)
  const filters = { ...dates, project_id: projectId ?? undefined, site_id: siteId ?? undefined }

  const { data: rows, isLoading, isError, refetch } = useQuery({
    queryKey: ['materials', 'stock-summary', filters],
    queryFn: () => fetchStockSummary(filters),
  })
  const { data: categoryList } = useQuery({
    queryKey: ['materials', 'categories'],
    queryFn: fetchMaterialCategories,
    staleTime: 30_000,
  })

  const groups = React.useMemo(() => {
    const order = new Map(categoryTree(categoryList?.items ?? []).map(({ main }, i) => [main.name, i]))
    const byMain = new Map<string, StockSummaryRow[]>()
    for (const r of rows ?? []) {
      const key = r.main_category ?? NONE
      byMain.set(key, [...(byMain.get(key) ?? []), r])
    }
    return [...byMain.entries()]
      .map(([key, list]) => ({
        key,
        name: key === NONE ? 'No category' : key,
        list: list.sort((a, b) => (a.category ?? '').localeCompare(b.category ?? '') || a.material_name.localeCompare(b.material_name)),
        items: new Set(list.map((r) => r.material_id)).size,
        low: list.filter((r) => r.running_low).length,
        spend: sum(list.map((r) => r.spend)),
      }))
      .sort((a, b) => (order.get(a.key) ?? 1e9) - (order.get(b.key) ?? 1e9))
  }, [rows, categoryList])

  const money = (rows ?? []).some((r) => r.spend !== null)
  const sites = new Set((rows ?? []).map((r) => r.site_id)).size
  const showSite = !siteId && sites > 1
  const current = groups.find((g) => g.key === chosen) ?? groups[0]
  // Opening stock entered, adjustments and corrections in the period: shown when any row has them, so every row adds
  // up (before + received + other - used = in stock).
  const other = !!current?.list.some((r) => Number(r.adjusted) !== 0)
  const low = (rows ?? []).filter((r) => r.running_low)

  const controls = (
    <div className="flex flex-wrap items-end gap-3">
      <Segmented<Period>
        label="Period"
        value={period}
        onChange={setPeriod}
        options={[
          { value: 'week', label: 'Last 7 days' },
          { value: 'month', label: 'This month' },
          { value: 'last_month', label: 'Last month' },
          { value: 'custom', label: 'Dates' },
        ]}
      />
      {period === 'custom' && (
        <div className="flex flex-wrap items-end gap-2">
          <div className="grid gap-1">
            <Label htmlFor="stockFrom" className="text-xs">
              From
            </Label>
            <Input id="stockFrom" type="date" className="h-8" value={from} onChange={(e) => setFrom(e.target.value)} />
          </div>
          <div className="grid gap-1">
            <Label htmlFor="stockTo" className="text-xs">
              To
            </Label>
            <Input id="stockTo" type="date" className="h-8" value={to} onChange={(e) => setTo(e.target.value)} />
          </div>
        </div>
      )}
    </div>
  )

  if (isError) {
    return (
      <div className="flex flex-col gap-4">
        {controls}
        <Callout
          tone="draft"
          icon={TriangleAlert}
          action={
            <Button variant="outline" size="sm" className="bg-background" onClick={() => refetch()}>
              Try again
            </Button>
          }
        >
          The stock could not be loaded.
        </Callout>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {controls}

      {isLoading ? (
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-lg" />
          ))}
        </div>
      ) : groups.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center">
          <Boxes className="size-6 text-muted-foreground" aria-hidden="true" />
          <p className="text-sm font-medium">No stock in this period</p>
          <p className="max-w-sm text-sm text-muted-foreground">Record a delivery or opening stock, or import your list from Excel in the Catalogue.</p>
        </div>
      ) : (
        <>
          {low.length > 0 && (
            <Callout tone="draft" icon={TriangleAlert}>
              <strong className="font-semibold">Running low:</strong>{' '}
              {low
                .slice(0, 4)
                .map((r) => `${r.material_name} ${qty(r.closing)} ${r.unit}${r.days_left !== null ? ` (${lasts(r.days_left)})` : Number(r.closing) <= 0 ? ' (out)' : ''}`)
                .join(' · ')}
              {low.length > 4 && ` · +${low.length - 4} more`}
            </Callout>
          )}

          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-4" role="group" aria-label="Categories">
            {groups.map((g) => (
              <button
                key={g.key}
                type="button"
                aria-pressed={current?.key === g.key}
                onClick={() => setChosen(g.key)}
                className={cn(
                  'flex flex-col gap-1 rounded-lg border bg-card p-3 text-left transition-colors hover:bg-muted/40',
                  current?.key === g.key && 'border-primary ring-1 ring-primary',
                )}
              >
                <span className="text-sm font-semibold">{g.name}</span>
                {money && <span className="text-lg font-bold tabular-nums">{formatMoney(String(g.spend))}</span>}
                <span className="text-xs text-muted-foreground">
                  {g.items} {g.items === 1 ? 'item' : 'items'}
                  {g.low > 0 && <span className="font-semibold text-draft"> · {g.low} low</span>}
                </span>
              </button>
            ))}
            {money && (
              <div className="flex flex-col gap-1 rounded-lg bg-foreground p-3 text-background">
                <span className="text-sm font-semibold">All categories</span>
                <span className="text-lg font-bold tabular-nums">{formatMoney(String(sum((rows ?? []).map((r) => r.spend))))}</span>
                <span className="text-xs opacity-80">{new Set((rows ?? []).map((r) => r.material_id)).size} items</span>
              </div>
            )}
          </div>

          {current && (
            <section className="flex flex-col gap-2">
              <h3 className="text-sm font-semibold">
                {current.name} <span className="font-normal text-muted-foreground">{current.items}</span>
              </h3>
              <div className="overflow-x-auto rounded-lg border">
                <table className="w-full min-w-[720px] text-sm">
                  <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 font-semibold">Item</th>
                      {showSite && <th className="px-3 py-2 font-semibold">Site</th>}
                      <th className="px-3 py-2 text-right font-semibold">Before</th>
                      <th className="px-3 py-2 text-right font-semibold">Received</th>
                      {other && (
                        <th className="px-3 py-2 text-right font-semibold" title="Opening stock entered, adjustments and corrections in this period">
                          Opening / other
                        </th>
                      )}
                      <th className="px-3 py-2 text-right font-semibold">Used</th>
                      <th className="px-3 py-2 text-right font-semibold">In stock</th>
                      <th className="px-3 py-2 font-semibold">Lasts</th>
                      {money && <th className="px-3 py-2 text-right font-semibold">Last rate</th>}
                      {money && <th className="px-3 py-2 text-right font-semibold">Spend</th>}
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {current.list.map((r, i) => {
                      const sub = r.category?.includes(' › ') ? r.category.split(' › ')[1] : null
                      const prevSub = i > 0 && current.list[i - 1].category?.includes(' › ') ? current.list[i - 1].category!.split(' › ')[1] : null
                      return (
                        <React.Fragment key={`${r.site_id}:${r.material_id}`}>
                          {sub && sub !== prevSub && (
                            <tr className="bg-muted/20">
                              <td colSpan={10} className="px-3 py-1.5 text-xs font-semibold text-muted-foreground">
                                {sub}
                              </td>
                            </tr>
                          )}
                          <tr className={cn('cursor-pointer hover:bg-muted/30', r.running_low && 'bg-draft-soft/40')} onClick={() => setOpened(r)}>
                            <td className="px-3 py-2 font-medium">{r.material_name}</td>
                            {showSite && <td className="px-3 py-2 text-muted-foreground">{siteNames.get(r.site_id ?? '')?.name ?? 'Site'}</td>}
                            <td className="px-3 py-2 text-right tabular-nums">{qty(r.opening)}</td>
                            <td className="px-3 py-2 text-right tabular-nums">{Number(r.received) ? `+${qty(r.received)}` : '—'}</td>
                            {other && (
                              <td className="px-3 py-2 text-right tabular-nums">
                                {Number(r.adjusted) ? `${Number(r.adjusted) > 0 ? '+' : ''}${qty(r.adjusted)}` : '—'}
                              </td>
                            )}
                            <td className="px-3 py-2 text-right tabular-nums">{Number(r.used) ? `−${qty(r.used)}` : '—'}</td>
                            <td className={cn('px-3 py-2 text-right font-semibold tabular-nums', Number(r.closing) < 0 && 'text-destructive')}>
                              {qty(r.closing)} <span className="font-normal text-muted-foreground">{r.unit}</span>
                            </td>
                            <td className="px-3 py-2">
                              {r.running_low ? (
                                <span className={cn(CHIP, 'bg-draft-soft text-draft')}>{Number(r.closing) <= 0 ? 'Out' : lasts(r.days_left ?? 0)}</span>
                              ) : r.days_left !== null ? (
                                <span className="text-muted-foreground">{lasts(r.days_left)}</span>
                              ) : (
                                <span className="text-muted-foreground">—</span>
                              )}
                            </td>
                            {money && <td className="px-3 py-2 text-right tabular-nums">{r.last_rate ? formatMoney(r.last_rate) : '—'}</td>}
                            {money && (
                              <td className="px-3 py-2 text-right tabular-nums">
                                {Number(r.spend) ? formatMoney(r.spend) : '—'}
                                {r.spend_complete === false && Number(r.received) > 0 && (
                                  <span className="ml-1 text-xs text-muted-foreground" title="Some deliveries in this period have no price">*</span>
                                )}
                              </td>
                            )}
                          </tr>
                        </React.Fragment>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              {money && current.list.some((r) => r.spend_complete === false && Number(r.received) > 0) && (
                <p className="text-xs text-muted-foreground">* Some deliveries in this period have no price, so the spend shown is less than paid.</p>
              )}
            </section>
          )}
        </>
      )}

      {opened && (
        <MaterialLedgerSheet
          siteId={opened.site_id}
          materialId={opened.material_id}
          materialName={opened.material_name}
          siteName={siteNames.get(opened.site_id ?? '')?.name}
          stockState={Number(opened.closing) < 0 ? 'NEGATIVE_STOCK' : Number(opened.closing) === 0 ? 'OUT_OF_STOCK' : 'AVAILABLE'}
          open={opened !== null}
          onOpenChange={(o) => !o && setOpened(null)}
        />
      )}
    </div>
  )
}
