import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { BadgePercent, CalendarDays, Download, IndianRupee, LayoutGrid, MapPin, Search, Store, Tags, TrendingDown, TrendingUp } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Sheet, SheetContent } from '@/components/ui/sheet'
import { Callout } from '@/components/dpr-page'
import { FilterSelect } from '@/components/filter-select'
import { CategoryTile, FilterPill, type FilterOption } from '@/components/requests/parts'
import { NewOrderDialog, type OrderPrefill } from '@/components/orders/new-order-dialog'
import { RateDetail } from '@/components/rates/rate-detail'
import { Sparkline, TrendChip } from '@/components/rates/parts'
import { useScope } from '@/lib/ScopeContext'
import { useAuth } from '@/lib/AuthContext'
import { usePageTitle } from '@/lib/page-title'
import { useUrlState } from '@/lib/url-state'
import { useReadOnly } from '@/lib/trial'
import { useIsMobile } from '@/hooks/use-mobile'
import { useSiteNames } from '@/lib/site-names'
import { swatch } from '@/lib/requests'
import { rupees } from '@/lib/orders'
import { exportCsv } from '@/lib/export'
import { qty } from '@/lib/site-day'
import { cn } from '@/lib/utils'
import { MONEY_ROLES } from '@/lib/module-map'
import { RATE_PERIODS, fetchRates, rate, ratePeriodRange, shortDate, type RateItem, type RatePeriod, type RatePurchase, vendorColour } from '@/lib/rates'

// PRC-14 / PRC-16: Procurement > Rates. What each item cost, from which supplier, over time: four tiles for what
// needs a look (rates that went up, went down, cheaper elsewhere, spend), filters, one row per item with its trend
// line and change, and beside it (a sheet on a phone) the item's chart, suppliers cheapest first and every purchase.
// "Order from the cheapest" and "Order again" open the order form filled in. Only the roles that see spending.

type Tile = '' | 'up' | 'down' | 'cheaper'
type Sort = 'spend' | 'change' | 'saving' | 'name'

const SORTS: { value: Sort; label: string }[] = [
  { value: 'spend', label: 'Most spent' },
  { value: 'change', label: 'Biggest change' },
  { value: 'saving', label: 'Most to save' },
  { value: 'name', label: 'A to Z' },
]

const OFFICE = ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'PROJECT_MANAGER']

function exportRates(items: RateItem[], from: string, to: string): void {
  const rows = items.map((i) => [
    i.material_name, i.category ?? '', i.unit, Number(i.last.rate), i.last.date, i.last.vendor_name, i.previous ? Number(i.previous.rate) : '',
    i.change_pct === null ? '' : Number(i.change_pct), Number(i.avg_rate), Number(i.min_rate), Number(i.max_rate), i.best?.vendor_name ?? '',
    i.best ? Number(i.best.avg_rate) : '', Number(i.above_best), i.purchases, Number(i.quantity), Number(i.spend),
  ])
  exportCsv(`rates-${from}-to-${to}.csv`, ['Item', 'Category', 'Unit', 'Last rate', 'Last bought', 'Last supplier', 'Rate before', 'Change %', 'Average',
    'Lowest', 'Highest', 'Cheapest supplier', 'Cheapest average', 'Paid above cheapest', 'Purchases', 'Quantity', 'Spent'], rows)
}

export default function RatesPage() {
  usePageTitle('Rates')
  const { scope } = useScope()
  const { me } = useAuth()
  const readOnly = useReadOnly()
  const isMobile = useIsMobile()
  const siteNames = useSiteNames()
  const role = (me?.role || '').toUpperCase()
  const office = OFFICE.includes(role) && !readOnly
  const projectId = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : null
  const siteId = scope.mode === 'site' ? scope.siteId : null

  const [period, setPeriod] = useUrlState<RatePeriod>('period', '90d')
  const [from, setFrom] = useUrlState<string>('from', '')
  const [to, setTo] = useUrlState<string>('to', '')
  const [tile, setTile] = useUrlState<Tile>('show', '')
  const [sort, setSort] = useUrlState<Sort>('sort', 'spend')
  const [site, setSite] = useUrlState<string>('at', '')
  const [vendor, setVendor] = useUrlState<string>('vendor', '')
  const [category, setCategory] = useUrlState<string>('category', '')
  const [selected, setSelected] = useUrlState<string>('item', '')
  const [search, setSearch] = React.useState('')
  const [ordering, setOrdering] = React.useState<OrderPrefill | null | false>(false)

  const filters = { ...ratePeriodRange(period, from, to), project_id: projectId ?? undefined, site_id: siteId ?? (site || undefined) }
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['procurement', 'rates', filters],
    queryFn: () => fetchRates(filters),
    retry: (n, e: unknown) => n < 2 && (e as { response?: { status?: number } })?.response?.status !== 403,
  })
  const forbidden = (error as { response?: { status?: number } } | null)?.response?.status === 403
  const all = React.useMemo(() => data?.items ?? [], [data])

  const pass = React.useCallback(
    (i: RateItem, skip?: string) => {
      if (skip !== 'vendor' && vendor && !i.vendors.some((v) => v.key === vendor)) return false
      if (skip !== 'category' && category && (i.main_category ?? '—') !== category) return false
      if (search && !`${i.material_name} ${i.category ?? ''} ${i.vendors.map((v) => v.name).join(' ')}`.toLowerCase().includes(search.toLowerCase())) return false
      return true
    },
    [vendor, category, search],
  )
  const filtered = React.useMemo(() => all.filter((i) => pass(i)), [all, pass])
  const inTile = (i: RateItem, t: Tile) => (t === 'up' ? i.trend === 'up' : t === 'down' ? i.trend === 'down' : t === 'cheaper' ? Number(i.above_best) > 0 : true)
  const list = React.useMemo(() => {
    const shown = filtered.filter((i) => inTile(i, tile))
    const by: Record<Sort, (a: RateItem, b: RateItem) => number> = {
      spend: (a, b) => Number(b.spend) - Number(a.spend),
      change: (a, b) => Math.abs(Number(b.change_pct ?? 0)) - Math.abs(Number(a.change_pct ?? 0)),
      saving: (a, b) => Number(b.above_best) - Number(a.above_best) || Number(b.spend) - Number(a.spend),
      name: (a, b) => a.material_name.localeCompare(b.material_name),
    }
    return shown.sort(by[sort])
  }, [filtered, tile, sort])

  const current = all.find((i) => i.material_id === selected) ?? (isMobile ? undefined : list[0])

  const options = React.useMemo(() => {
    const count = (skip: string, test: (i: RateItem) => boolean) => all.filter((i) => pass(i, skip) && test(i)).length
    const vendors = new Map<string, string>()
    for (const i of all) for (const v of i.vendors) vendors.set(v.key, v.name)
    const vendorOptions: FilterOption[] = [...vendors.entries()]
      .map(([key, name]) => ({ value: key, label: name, swatch: vendorColour(key), count: count('vendor', (i) => i.vendors.some((v) => v.key === key)) }))
      .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
    const mains = [...new Set(all.map((i) => i.main_category ?? '—'))].sort()
    const categories: FilterOption[] = mains.map((m) => ({ value: m, label: m === '—' ? 'No category' : m, category: m === '—' ? null : m, count: count('category', (i) => (i.main_category ?? '—') === m) }))
    const sites: FilterOption[] = [...siteNames.entries()]
      .filter(([, s]) => !projectId || s.projectId === projectId)
      .map(([id, s]) => ({ value: id, label: `${s.project} › ${s.name}`, swatch: swatch(s.projectId), count: 0 }))
      .sort((a, b) => a.label.localeCompare(b.label))
    return { vendors: vendorOptions, categories, sites }
  }, [all, pass, siteNames, projectId])

  const sum = (xs: RateItem[], f: (i: RateItem) => number) => xs.reduce((n, i) => n + f(i), 0)
  const saving = sum(filtered.filter((i) => Number(i.above_best) > 0), (i) => Number(i.above_best))
  const tiles: { value: Exclude<Tile, ''> | 'spend'; label: string; value2: string; icon: LucideIcon; tone: string; ring: string; num?: string }[] = [
    { value: 'up', label: 'Rates went up', value2: String(filtered.filter((i) => i.trend === 'up').length), icon: TrendingUp, tone: 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200', ring: 'ring-red-500', num: 'text-red-700 dark:text-red-400' },
    { value: 'down', label: 'Rates went down', value2: String(filtered.filter((i) => i.trend === 'down').length), icon: TrendingDown, tone: 'bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-200', ring: 'ring-green-600' },
    { value: 'cheaper', label: 'Cheaper elsewhere', value2: saving > 0 ? rupees(Math.round(saving)) : '0', icon: BadgePercent, tone: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100', ring: 'ring-emerald-500' },
    { value: 'spend', label: `${filtered.length} ${filtered.length === 1 ? 'item' : 'items'} bought`, value2: rupees(Math.round(sum(filtered, (i) => Number(i.spend)))), icon: IndianRupee, tone: 'bg-yellow-100 text-yellow-900 dark:bg-yellow-950 dark:text-yellow-100', ring: 'ring-yellow-500' },
  ]

  const order = (item: RateItem) => (vendorName: string, lastRate: string, at: RatePurchase | undefined) => {
    const where = at?.site_id ? { project_id: at.project_id, site_id: at.site_id, site_name: at.site_name } : siteId && projectId ? { project_id: projectId, site_id: siteId } : null
    setOrdering(where ? { ...where, vendor_name: vendorName, lines: [{ material_id: item.material_id, quantity: '', rate: String(Number(lastRate)) }] } : null)
  }

  if (!(MONEY_ROLES as readonly string[]).includes(role) || forbidden) {
    return (
      <div className="mx-auto w-full max-w-3xl py-12">
        <Callout tone="draft" icon={Tags}>Rates are shown to the people who see the company's spending. Ask an admin if you need them.</Callout>
      </div>
    )
  }

  const detail = current && (
    <RateDetail item={current} filters={filters} inSheet={isMobile} canOrder={office} onOrder={order(current)} />
  )

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <header className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="inline-flex size-10 items-center justify-center rounded-xl bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200"><Tags className="size-5" /></span>
          <div>
            <div className="text-xs text-muted-foreground">Procurement</div>
            <h1 className="text-2xl leading-tight font-semibold tracking-tight">Rates</h1>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {data && <span className="hidden text-sm text-muted-foreground lg:inline">{shortDate(data.date_from)} – {shortDate(data.date_to)} · {sum(filtered, (i) => i.purchases)} purchases</span>}
          <Button variant="outline" className="gap-2" disabled={!list.length} onClick={() => data && exportRates(list, data.date_from, data.date_to)} title="The items shown, as a CSV file (opens in Excel)">
            <Download className="size-4" /> <span className="hidden sm:inline">Export</span>
          </Button>
        </div>
      </header>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 sm:gap-3">
        {tiles.map((t) => {
          const on = tile === t.value
          const clickable = t.value !== 'spend'
          return (
            <button
              key={t.value}
              type="button"
              aria-pressed={clickable ? on : undefined}
              disabled={!clickable}
              onClick={() => clickable && setTile(on ? '' : (t.value as Tile))}
              className={cn('flex items-center gap-3 rounded-xl border bg-card p-3 text-left transition sm:p-3.5', clickable && 'hover:-translate-y-px', on && cn('ring-2', t.ring), !clickable && 'cursor-default')}
            >
              <span className={cn('inline-flex size-9 shrink-0 items-center justify-center rounded-lg sm:size-11 sm:rounded-xl', t.tone)}><t.icon className="size-4 sm:size-5" /></span>
              <span className="flex min-w-0 flex-col">
                <span className={cn('truncate text-xl leading-none font-semibold tabular-nums sm:text-2xl', t.value2 !== '0' && t.num)}>{isLoading ? '–' : t.value2}</span>
                <span className="truncate text-xs text-muted-foreground sm:text-sm sm:text-foreground/80">{t.label}</span>
              </span>
            </button>
          )
        })}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div role="tablist" aria-label="Sort" className="flex max-w-full gap-0.5 overflow-x-auto rounded-xl bg-muted p-1">
          {SORTS.map((s) => (
            <button key={s.value} role="tab" type="button" aria-selected={sort === s.value} onClick={() => setSort(s.value)} className={cn('inline-flex h-8 shrink-0 items-center rounded-lg px-3 text-sm whitespace-nowrap', sort === s.value ? 'bg-background font-semibold shadow-sm' : 'text-foreground/75 hover:text-foreground')}>
              {s.label}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!siteId && options.sites.length > 1 && <FilterPill icon={MapPin} label="Site" allLabel="All sites" value={site} options={options.sites} onChange={setSite} />}
          <FilterPill icon={Store} label="Supplier" allLabel="Every supplier" value={vendor} options={options.vendors} onChange={setVendor} />
          <FilterPill icon={LayoutGrid} label="Category" allLabel="All categories" value={category} options={options.categories} onChange={setCategory} />
          <FilterSelect label="Period" value={period} onChange={setPeriod} options={RATE_PERIODS} icon={CalendarDays} className="h-9 w-[160px] rounded-lg" />
          {period === 'custom' && (
            <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <Input type="date" aria-label="From" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} className="h-9 w-[140px] dark:[color-scheme:dark]" />
              to
              <Input type="date" aria-label="To" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} className="h-9 w-[140px] dark:[color-scheme:dark]" />
            </span>
          )}
          <label className="flex h-9 items-center gap-2 rounded-lg border bg-background px-2.5">
            <Search className="size-4 text-muted-foreground" />
            <span className="sr-only">Search items</span>
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Item or supplier" className="w-28 bg-transparent text-sm outline-none sm:w-36" />
          </label>
        </div>
      </div>

      <div className="flex flex-col items-start gap-5 lg:flex-row">
        <section aria-label="Items and their rates" className="w-full min-w-0 flex-1 overflow-hidden rounded-xl border">
          {isLoading && <div className="flex flex-col">{[0, 1, 2, 3].map((i) => <div key={i} className="h-[72px] animate-pulse border-b bg-muted/40" />)}</div>}
          {isError && !forbidden && (
            <div className="flex flex-col items-center gap-3 p-6 text-center text-sm">
              <p className="text-destructive">Rates did not load.</p>
              <Button size="sm" variant="outline" onClick={() => refetch()}>Try again</Button>
            </div>
          )}
          {!isLoading && !isError && list.length === 0 && (
            <div className="flex flex-col items-center gap-2 px-4 py-12 text-center text-sm text-muted-foreground">
              <Tags className="size-8 opacity-40" />
              {all.length === 0 ? (
                <>
                  <span className="font-medium text-foreground">No rates in this period yet</span>
                  <span className="max-w-sm">A rate appears here when a delivery is recorded with its price: on WhatsApp ("200 bags cement came from Malabar at 410"), from a bill photo, or against an order.</span>
                </>
              ) : (
                'No items with these filters.'
              )}
            </div>
          )}
          {list.length > 0 && (
            <div className="hidden grid-cols-[minmax(0,1.6fr)_104px_minmax(0,1fr)_minmax(0,1fr)_90px] gap-3 border-b bg-muted/40 px-4 py-2 text-xs font-semibold text-muted-foreground xl:grid">
              <span>Item</span>
              <span>Trend</span>
              <span className="text-right">Last rate</span>
              <span>Cheapest</span>
              <span className="text-right">Spent</span>
            </div>
          )}
          {list.map((i) => (
            <RateRow key={i.material_id} item={i} selected={current?.material_id === i.material_id} onPick={() => setSelected(i.material_id)} />
          ))}
        </section>
        {!isMobile && current && (
          <aside aria-label="Item rates" className="sticky top-4 max-h-[calc(100vh-2rem)] w-full shrink-0 overflow-y-auto rounded-xl border lg:w-[440px]">{detail}</aside>
        )}
      </div>

      {isMobile && (
        <Sheet open={!!current} onOpenChange={(o) => !o && setSelected('')}>
          <SheetContent side="bottom" className="max-h-[92vh] gap-0 overflow-y-auto rounded-t-2xl p-0">{detail}</SheetContent>
        </Sheet>
      )}
      <NewOrderDialog open={ordering !== false} onOpenChange={(o) => !o && setOrdering(false)} scope={scope} prefill={ordering || null} />
    </div>
  )
}

function RateRow({ item: i, selected, onPick }: { item: RateItem; selected: boolean; onPick: () => void }) {
  const lastIsBest = i.best && i.last.vendor_key === i.best.vendor_key
  return (
    <button
      type="button"
      onClick={onPick}
      aria-current={selected || undefined}
      className={cn(
        'grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 border-b px-3 py-3 text-left transition hover:bg-muted/40 sm:px-4 xl:grid-cols-[minmax(0,1.6fr)_104px_minmax(0,1fr)_minmax(0,1fr)_90px]',
        selected && 'bg-yellow-50 shadow-[inset_0_0_0_2px_theme(colors.yellow.300)] dark:bg-yellow-950/40',
      )}
    >
      <span className="flex min-w-0 items-center gap-3">
        <CategoryTile mainCategory={i.main_category} size="sm" />
        <span className="flex min-w-0 flex-col">
          <span className="truncate font-semibold">{i.material_name}</span>
          <span className="truncate text-xs text-muted-foreground">
            {i.purchases} {i.purchases === 1 ? 'purchase' : 'purchases'} · {i.vendors.length} {i.vendors.length === 1 ? 'supplier' : 'suppliers'} · {rate(i.min_rate)}
            {i.min_rate !== i.max_rate && <>–{rate(i.max_rate)}</>}
          </span>
        </span>
      </span>
      <Sparkline item={i} className="hidden xl:block" />
      <span className="flex flex-col items-end gap-0.5">
        <span className="flex items-center gap-1.5">
          <TrendChip item={i} />
          <span className="font-semibold tabular-nums">{rate(i.last.rate)}</span>
          <span className="text-xs text-muted-foreground">/{i.unit}</span>
        </span>
        <span className="max-w-full truncate text-xs text-muted-foreground">
          {i.last.vendor_name} · {shortDate(i.last.date)}
        </span>
      </span>
      <span className="col-span-2 flex min-w-0 items-center gap-1.5 text-xs xl:col-span-1 xl:flex-col xl:items-start xl:gap-0.5">
        {i.best ? (
          <>
            <span className="inline-flex min-w-0 items-center gap-1.5 font-medium">
              <span className="size-2 shrink-0 rounded-full" style={{ background: vendorColour(i.best.vendor_key) }} />
              <span className="truncate">{i.best.vendor_name}</span>
              <span className="tabular-nums text-muted-foreground">{rate(i.best.avg_rate)}</span>
            </span>
            {Number(i.above_best) > 0 ? (
              <span className="font-semibold text-emerald-700 dark:text-emerald-400">Save {rupees(Math.round(Number(i.above_best)))}</span>
            ) : (
              lastIsBest && <span className="text-muted-foreground">Bought at the best</span>
            )}
          </>
        ) : (
          <span className="text-muted-foreground">One supplier</span>
        )}
        <span className="ml-auto font-semibold tabular-nums xl:hidden">{rupees(Math.round(Number(i.spend)))}</span>
      </span>
      <span className="hidden text-right text-sm font-semibold tabular-nums xl:block">
        {rupees(Math.round(Number(i.spend)))}
        <span className="block text-xs font-normal text-muted-foreground">{qty(i.quantity)} {i.unit}</span>
      </span>
    </button>
  )
}
