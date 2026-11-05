import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Boxes, Filter, Search, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Callout } from '@/components/dpr-page'
import { FilterSelect, PeriodSelect } from '@/components/filter-select'
import { CHIP, qty } from '@/lib/site-day'
import { useSiteNames } from '@/lib/site-names'
import { useUrlState } from '@/lib/url-state'
import { periodRange, type Period } from '@/lib/period'
import { cn, toLocalISODate } from '@/lib/utils'
import { categoryTree, fetchMaterialCategories, fetchStockSummary, formatMoney, type StockSummaryRow } from '@/lib/materials'
import { MaterialLedgerSheet } from './material-ledger-sheet'

// Materials > Stock (PRC-17d, WEB-50; mockup 5). What each site held before the period, what came, what was used and
// what is left, by main category -- the client's "previous stock, consumption, current balance at a glance". The
// filters are dropdowns on one toolbar row with the view switch (DESIGN.md, WEB-40): category, all / running low,
// period, search; a category card is a shortcut to the same filter. On a phone each item is a stacked row, on a
// wider screen a table. Money only for the roles that see spending: the API leaves it out for the rest.

const NONE = '__none__'
const sum = (values: (string | null)[]) => values.reduce((n, v) => n + (v ? Number(v) : 0), 0)
// How long the stock lasts, in words: 0 whole days is "under 1 day", not "~0 days".
const lasts = (days: number | null) => (days === null ? '' : days < 1 ? 'under 1 day' : `~${days} ${days === 1 ? 'day' : 'days'}`)
const subOf = (r: StockSummaryRow) => (r.category?.includes(' › ') ? r.category.split(' › ')[1] : null)
const signed = (v: string, sign: '+' | '−') => (Number(v) ? `${sign}${qty(String(Math.abs(Number(v))))}` : '—')

function dates(period: Period, from: string, to: string): { date_from?: string; date_to?: string } {
  if (period === 'all') {
    // The API takes at most a year: "All time" is the last 12 months.
    const start = new Date()
    start.setFullYear(start.getFullYear() - 1)
    return { date_from: toLocalISODate(start), date_to: toLocalISODate() }
  }
  const range = periodRange(period, from, to)
  return { date_from: range.from, date_to: range.to }
}

export function CategoryView({
  projectId,
  siteId,
  leading,
}: {
  projectId: string | null
  siteId: string | null
  leading?: React.ReactNode
}) {
  const siteNames = useSiteNames()
  const [period, setPeriod] = useUrlState<Period>('stock_period', '7d')
  const [from, setFrom] = useUrlState<string>('stock_from', '')
  const [to, setTo] = useUrlState<string>('stock_to', '')
  const [category, setCategory] = useUrlState<string>('cat', 'all')
  const [show, setShow] = useUrlState<'all' | 'low'>('show', 'all')
  const [q, setQ] = useUrlState<string>('q', '')
  const [opened, setOpened] = React.useState<StockSummaryRow | null>(null)
  const filters = { ...dates(period, from, to), project_id: projectId ?? undefined, site_id: siteId ?? undefined }

  const { data: rows, isLoading, isError, refetch } = useQuery({
    queryKey: ['materials', 'stock-summary', filters],
    queryFn: () => fetchStockSummary(filters),
  })
  const { data: categoryList } = useQuery({
    queryKey: ['materials', 'categories'],
    queryFn: fetchMaterialCategories,
    staleTime: 30_000,
  })

  const order = React.useMemo(
    () => new Map(categoryTree(categoryList?.items ?? []).map(({ main }, i) => [main.name, i])),
    [categoryList],
  )
  const groups = React.useMemo(() => {
    const byMain = new Map<string, StockSummaryRow[]>()
    for (const r of rows ?? []) byMain.set(r.main_category ?? NONE, [...(byMain.get(r.main_category ?? NONE) ?? []), r])
    return [...byMain.entries()]
      .map(([key, list]) => ({
        key,
        name: key === NONE ? 'No category' : key,
        list: list.sort((a, b) => (subOf(a) ?? '').localeCompare(subOf(b) ?? '') || a.material_name.localeCompare(b.material_name)),
        items: new Set(list.map((r) => r.material_id)).size,
        low: list.filter((r) => r.running_low).length,
        spend: sum(list.map((r) => r.spend)),
      }))
      .sort((a, b) => (order.get(a.key) ?? 1e9) - (order.get(b.key) ?? 1e9))
  }, [rows, order])

  const needle = q.trim().toLowerCase()
  const shown = groups
    .filter((g) => category === 'all' || g.key === category)
    .map((g) => ({
      ...g,
      list: g.list.filter((r) => (show === 'all' || r.running_low) && (!needle || `${r.material_name} ${r.category ?? ''}`.toLowerCase().includes(needle))),
    }))
    .filter((g) => g.list.length > 0)
  const money = (rows ?? []).some((r) => r.spend !== null)
  const showSite = !siteId && new Set((rows ?? []).map((r) => r.site_id)).size > 1
  const low = (rows ?? []).filter((r) => r.running_low)
  const other = shown.some((g) => g.list.some((r) => Number(r.adjusted) !== 0))
  const filtered = category !== 'all' || show !== 'all' || !!needle

  const toolbar = (
    <div className="flex flex-wrap items-center gap-2">
      {leading}
      <div className="ml-auto flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-2 size-4 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search items" aria-label="Search items" className="h-8 w-[160px] pl-8" />
        </div>
        <FilterSelect
          label="Category"
          value={category}
          onChange={setCategory}
          icon={Filter}
          className="w-[160px]"
          options={[{ value: 'all', label: 'All categories' }, ...groups.map((g) => ({ value: g.key, label: g.name }))]}
        />
        <FilterSelect
          label="Show"
          value={show}
          onChange={setShow}
          className="w-[140px]"
          options={[
            { value: 'all', label: 'All items' },
            { value: 'low', label: `Running low${low.length ? ` (${low.length})` : ''}` },
          ]}
        />
        <PeriodSelect value={period} onChange={setPeriod} from={from} to={to} onFrom={setFrom} onTo={setTo} />
      </div>
    </div>
  )

  if (isError) {
    return (
      <div className="flex flex-col gap-4">
        {toolbar}
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
      {toolbar}

      {isLoading ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-20 rounded-lg" />
          ))}
        </div>
      ) : groups.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center">
          <Boxes className="size-6 text-muted-foreground" aria-hidden="true" />
          <p className="text-sm font-medium">No stock in this period</p>
          <p className="max-w-sm text-sm text-muted-foreground">Record a delivery or opening stock, or import your list from Excel in Items.</p>
        </div>
      ) : (
        <>
          {low.length > 0 && show === 'all' && (
            <Callout
              tone="draft"
              icon={TriangleAlert}
              action={
                <Button variant="outline" size="sm" className="bg-background" onClick={() => setShow('low')}>
                  Show them
                </Button>
              }
            >
              <strong className="font-semibold">{low.length === 1 ? '1 item running low' : `${low.length} items running low`}:</strong>{' '}
              {low
                .slice(0, 3)
                .map((r) => `${r.material_name} ${qty(r.closing)} ${r.unit}${r.days_left !== null ? ` (${lasts(r.days_left)})` : Number(r.closing) <= 0 ? ' (out)' : ''}`)
                .join(' · ')}
              {low.length > 3 && ` · +${low.length - 3} more`}
            </Callout>
          )}

          <div className="grid grid-cols-2 gap-2 sm:gap-3 lg:grid-cols-4" role="group" aria-label="Categories">
            {groups.map((g) => (
              <button
                key={g.key}
                type="button"
                aria-pressed={category === g.key}
                onClick={() => setCategory(category === g.key ? 'all' : g.key)}
                className={cn(
                  'flex min-w-0 flex-col gap-0.5 rounded-lg border bg-card px-3 py-2 text-left transition-colors hover:bg-muted/40',
                  category === g.key && 'border-primary ring-1 ring-primary',
                )}
              >
                <span className="truncate text-sm font-semibold">{g.name}</span>
                {money && <span className="text-base font-semibold tabular-nums">{formatMoney(String(g.spend))}</span>}
                <span className="text-xs text-muted-foreground">
                  {g.items} {g.items === 1 ? 'item' : 'items'}
                  {g.low > 0 && <span className="font-semibold text-draft"> · {g.low} low</span>}
                </span>
              </button>
            ))}
          </div>

          {shown.length === 0 ? (
            <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-8 text-center">
              <p className="text-sm text-muted-foreground">Nothing matches these filters.</p>
              {filtered && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setCategory('all')
                    setShow('all')
                    setQ('')
                  }}
                >
                  Clear filters
                </Button>
              )}
            </div>
          ) : (
            shown.map((g) => (
              <section key={g.key} className="flex flex-col gap-1.5">
                <h3 className="text-sm font-semibold">
                  {g.name} <span className="font-normal text-muted-foreground">{g.list.length}</span>
                </h3>

                {/* Phone: one stacked row per item */}
                <ul className="divide-y rounded-lg border sm:hidden">
                  {g.list.map((r, i) => {
                    const sub = subOf(r)
                    const heading = sub && sub !== (i > 0 ? subOf(g.list[i - 1]) : null)
                    return (
                      <React.Fragment key={`${r.site_id}:${r.material_id}`}>
                        {heading && <li className="bg-muted/30 px-3 py-1 text-xs font-semibold text-muted-foreground">{sub}</li>}
                        <li>
                          <button
                            type="button"
                            onClick={() => setOpened(r)}
                            className={cn('flex w-full flex-col gap-0.5 px-3 py-2 text-left', r.running_low && 'bg-draft-soft/40')}
                          >
                            <span className="flex items-baseline justify-between gap-2">
                              <span className="min-w-0 truncate font-medium">{r.material_name}</span>
                              <span className={cn('shrink-0 font-semibold tabular-nums', Number(r.closing) < 0 && 'text-destructive')}>
                                {qty(r.closing)} <span className="font-normal text-muted-foreground">{r.unit}</span>
                              </span>
                            </span>
                            <span className="flex items-baseline justify-between gap-2 text-xs text-muted-foreground">
                              <span className="min-w-0">
                                {[
                                  showSite ? siteNames.get(r.site_id ?? '')?.name : null,
                                  `before ${qty(r.opening)}`,
                                  Number(r.received) ? `${signed(r.received, '+')} in` : null,
                                  Number(r.used) ? `${signed(r.used, '−')} used` : null,
                                  Number(r.adjusted) ? `${signed(r.adjusted, Number(r.adjusted) > 0 ? '+' : '−')} other` : null,
                                ]
                                  .filter(Boolean)
                                  .join(' · ')}
                              </span>
                              {r.running_low ? (
                                <span className={cn(CHIP, 'shrink-0 bg-draft-soft text-draft')}>{Number(r.closing) <= 0 ? 'Out' : lasts(r.days_left ?? 0)}</span>
                              ) : (
                                r.days_left !== null && <span className="shrink-0">{lasts(r.days_left)}</span>
                              )}
                            </span>
                            {money && (Number(r.spend) > 0 || r.last_rate) && (
                              <span className="text-xs text-muted-foreground">
                                {[r.last_rate ? `last rate ${formatMoney(r.last_rate)}` : null, Number(r.spend) ? `spent ${formatMoney(r.spend)}` : null]
                                  .filter(Boolean)
                                  .join(' · ')}
                              </span>
                            )}
                          </button>
                        </li>
                      </React.Fragment>
                    )
                  })}
                </ul>

                {/* Wider screens: a table */}
                <div className="hidden overflow-x-auto rounded-lg border sm:block">
                  <table className="w-full text-sm">
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
                      {g.list.map((r, i) => {
                        const sub = subOf(r)
                        const heading = sub && sub !== (i > 0 ? subOf(g.list[i - 1]) : null)
                        return (
                          <React.Fragment key={`${r.site_id}:${r.material_id}`}>
                            {heading && (
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
                              <td className="px-3 py-2 text-right tabular-nums">{signed(r.received, '+')}</td>
                              {other && <td className="px-3 py-2 text-right tabular-nums">{signed(r.adjusted, Number(r.adjusted) > 0 ? '+' : '−')}</td>}
                              <td className="px-3 py-2 text-right tabular-nums">{signed(r.used, '−')}</td>
                              <td className={cn('px-3 py-2 text-right font-semibold tabular-nums', Number(r.closing) < 0 && 'text-destructive')}>
                                {qty(r.closing)} <span className="font-normal text-muted-foreground">{r.unit}</span>
                              </td>
                              <td className="px-3 py-2">
                                {r.running_low ? (
                                  <span className={cn(CHIP, 'bg-draft-soft text-draft')}>{Number(r.closing) <= 0 ? 'Out' : lasts(r.days_left ?? 0)}</span>
                                ) : (
                                  <span className="text-muted-foreground">{lasts(r.days_left) || '—'}</span>
                                )}
                              </td>
                              {money && <td className="px-3 py-2 text-right tabular-nums">{r.last_rate ? formatMoney(r.last_rate) : '—'}</td>}
                              {money && (
                                <td className="px-3 py-2 text-right tabular-nums">
                                  {Number(r.spend) ? formatMoney(r.spend) : '—'}
                                  {r.spend_complete === false && Number(r.received) > 0 && (
                                    <span className="ml-1 text-xs text-muted-foreground" title="Some deliveries in this period have no price">
                                      *
                                    </span>
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
              </section>
            ))
          )}
          {money && shown.some((g) => g.list.some((r) => r.spend_complete === false && Number(r.received) > 0)) && (
            <p className="text-xs text-muted-foreground">* Some deliveries in this period have no price, so the spend shown is less than paid.</p>
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
