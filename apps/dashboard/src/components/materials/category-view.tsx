import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Boxes, ChevronDown, ChevronRight, ClipboardList, MapPin, PackageX, Search, TrendingDown, TriangleAlert, Truck } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Sheet, SheetContent } from '@/components/ui/sheet'
import { Callout } from '@/components/dpr-page'
import { PeriodSelect } from '@/components/filter-select'
import { CategoryTile, FilterPill, type FilterOption } from '@/components/requests/parts'
import { NewRequestDialog, type RequestPrefill } from '@/components/requests/new-request-dialog'
import { NewOrderDialog, type OrderPrefill } from '@/components/orders/new-order-dialog'
import { CHIP, qty } from '@/lib/site-day'
import { useSiteNames } from '@/lib/site-names'
import { useUrlState } from '@/lib/url-state'
import { useAuth } from '@/lib/AuthContext'
import { useReadOnly } from '@/lib/trial'
import { useScope } from '@/lib/ScopeContext'
import { useIsMobile } from '@/hooks/use-mobile'
import { periodRange, type Period } from '@/lib/period'
import { cn, toLocalISODate } from '@/lib/utils'
import { categoryTree, fetchMaterialCategories, fetchStockSummary, formatMoney, type StockSummaryRow } from '@/lib/materials'
import { fetchRequests, swatch } from '@/lib/requests'
import { fetchOrders } from '@/lib/orders'
import { RecordInflowDialog } from './record-inflow-dialog'
import { RecordTransferDialog, type TransferPrefill } from './record-transfer-dialog'
import { StockItemPanel, type OtherSiteStock } from './stock-item-panel'
import { NO_FLOW, buildFlows, flowKey, lasts, type StockFlow } from '@/lib/stock-flow'

// Materials > Stock (PRC-17d, WEB-50, WEB-77). What each site held before the period, what came, what was used and
// what is left, by main category -- the client's "previous stock, consumption, current balance at a glance" -- now
// in the Requests / Purchase orders design and joined to them: four tiles say what needs doing (running low, out,
// coming on orders, asked for by the sites); categories are a row of chips; an item opens a panel with its orders,
// requests and stock book, and the buttons to ask, order or record what came. Money only for the roles that see
// spending: the API leaves it out for the rest.
// PRC-00 (Ilan, 7 Nov): with several sites on screen (project or company view), the same item at each site is one
// row with its total and where it is ("Green Villa 117 · Site B out"); a tap opens the per-site rows. The item
// panel lists the item at the other sites, with "Move here" (one transfer record, BE-32) before ordering more.

const NONE = '__none__'
const sum = (values: (string | null)[]) => values.reduce((n, v) => n + (v ? Number(v) : 0), 0)
const subOf = (r: StockSummaryRow) => (r.category?.includes(' › ') ? r.category.split(' › ')[1] : null)
const signed = (v: string, sign: '+' | '−') => (Number(v) ? `${sign}${qty(String(Math.abs(Number(v))))}` : '—')
const OFFICE = ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'PROJECT_MANAGER']

type Show = '' | 'low' | 'out' | 'coming' | 'asked' | 'all'

const add = (rows: StockSummaryRow[], field: 'opening' | 'received' | 'used' | 'adjusted' | 'closing' | 'on_order') =>
  String(rows.reduce((n, r) => n + Number(r[field] ?? 0), 0))

/** One item across the sites on screen: the rows of the same material next to each other (the list is sorted so). */
interface Bundle {
  key: string
  rows: StockSummaryRow[]
  total: StockSummaryRow
  low: number
}

function bundles(list: StockSummaryRow[]): Bundle[] {
  const out: Bundle[] = []
  for (const r of list) {
    const last = out[out.length - 1]
    if (last && last.key === r.material_id) last.rows.push(r)
    else out.push({ key: r.material_id, rows: [r], total: r, low: 0 })
  }
  for (const b of out) {
    b.low = b.rows.filter((r) => r.running_low).length
    if (b.rows.length === 1) continue
    const spends = b.rows.map((r) => r.spend)
    b.total = {
      ...b.rows[0],
      site_id: null,
      opening: add(b.rows, 'opening'),
      received: add(b.rows, 'received'),
      used: add(b.rows, 'used'),
      adjusted: add(b.rows, 'adjusted'),
      closing: add(b.rows, 'closing'),
      on_order: add(b.rows, 'on_order'),
      days_left: null,
      running_low: b.low > 0,
      spend: spends.every((v) => v === null) ? null : String(sum(spends)),
      spend_complete: b.rows.every((r) => r.spend_complete !== false),
      // One rate when every site paid the same; else none here (each site's row shows its own).
      last_rate: new Set(b.rows.map((r) => r.last_rate).filter(Boolean)).size === 1 ? b.rows.find((r) => r.last_rate)!.last_rate : null,
    }
  }
  return out
}

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

function daysIn(range: { date_from?: string; date_to?: string }): number {
  if (!range.date_from) return 0
  const end = range.date_to ? new Date(`${range.date_to}T00:00:00`) : new Date()
  return Math.max(1, Math.round((end.getTime() - new Date(`${range.date_from}T00:00:00`).getTime()) / 86_400_000) + 1)
}

export function CategoryView({ projectId, siteId, leading }: { projectId: string | null; siteId: string | null; leading?: React.ReactNode }) {
  const siteNames = useSiteNames()
  const { scope } = useScope()
  const { me } = useAuth()
  const readOnly = useReadOnly()
  const isMobile = useIsMobile()
  const [period, setPeriod] = useUrlState<Period>('stock_period', '7d')
  const [from, setFrom] = useUrlState<string>('stock_from', '')
  const [to, setTo] = useUrlState<string>('stock_to', '')
  const [category, setCategory] = useUrlState<string>('cat', 'all')
  const [rawShow, setShow] = useUrlState<Show>('show', '')
  const show: Show = rawShow === 'all' ? '' : rawShow
  const [site, setSite] = useUrlState<string>('at', '')
  const [q, setQ] = useUrlState<string>('q', '')
  const [opened, setOpened] = useUrlState<string>('item', '')
  const [dialog, setDialog] = React.useState<'ask' | 'order' | 'came' | 'move' | null>(null)
  const [movePrefill, setMovePrefill] = React.useState<TransferPrefill | null>(null)
  const [open, setOpen] = React.useState<Set<string>>(() => new Set())
  const toggle = (key: string) =>
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  const range = dates(period, from, to)
  const filters = { ...range, project_id: projectId ?? undefined, site_id: siteId ?? undefined }

  const role = (me?.role || '').toUpperCase()
  const canAsk = !!me && role !== 'FINANCE' && !readOnly
  const canOrder = OFFICE.includes(role) && !readOnly
  const canRecord = canAsk

  const { data: rows, isLoading, isError, refetch } = useQuery({
    queryKey: ['materials', 'stock-summary', filters],
    queryFn: () => fetchStockSummary(filters),
  })
  const { data: categoryList } = useQuery({ queryKey: ['materials', 'categories'], queryFn: fetchMaterialCategories, staleTime: 30_000 })
  // The same lists (and cache keys) as the Requests and Purchase orders pages; without Procurement they are empty.
  const requests = useQuery({
    queryKey: ['procurement', 'requests', projectId, siteId],
    queryFn: () => fetchRequests({ project_id: projectId, site_id: siteId }),
    retry: false,
    staleTime: 30_000,
  })
  const orders = useQuery({
    queryKey: ['procurement', 'orders', projectId, siteId],
    queryFn: () => fetchOrders({ project_id: projectId, site_id: siteId }),
    retry: false,
    staleTime: 30_000,
  })
  const flows = React.useMemo(() => buildFlows(requests.data?.items ?? [], orders.data?.items ?? []), [requests.data, orders.data])
  const flowOf = React.useCallback((r: StockSummaryRow): StockFlow => flows.get(flowKey(r.site_id, r.material_id)) ?? NO_FLOW, [flows])

  const all = React.useMemo(() => rows ?? [], [rows])
  const inSite = React.useMemo(() => all.filter((r) => !site || r.site_id === site), [all, site])
  const isOut = (r: StockSummaryRow) => Number(r.closing) <= 0 && (Number(r.used) > 0 || Number(r.received) > 0 || Number(r.opening) > 0)
  const matchesShow = React.useCallback(
    (r: StockSummaryRow, s: Show) =>
      s === 'low' ? r.running_low
        : s === 'out' ? isOut(r)
          : s === 'coming' ? Number(r.on_order ?? 0) > 0
            : s === 'asked' ? flowOf(r).asked > 0
              : true,
    [flowOf],
  )

  const order = React.useMemo(() => new Map(categoryTree(categoryList?.items ?? []).map(({ main }, i) => [main.name, i])), [categoryList])
  const groups = React.useMemo(() => {
    const byMain = new Map<string, StockSummaryRow[]>()
    for (const r of inSite) byMain.set(r.main_category ?? NONE, [...(byMain.get(r.main_category ?? NONE) ?? []), r])
    return [...byMain.entries()]
      .map(([key, list]) => ({
        key,
        name: key === NONE ? 'No category' : key,
        // Sub-category, then item, then site: the same item on two sites sits together.
        list: list.sort(
          (a, b) =>
            (subOf(a) ?? '').localeCompare(subOf(b) ?? '') ||
            a.material_name.localeCompare(b.material_name) ||
            (siteNames.get(a.site_id ?? '')?.name ?? '').localeCompare(siteNames.get(b.site_id ?? '')?.name ?? ''),
        ),
        items: new Set(list.map((r) => r.material_id)).size,
        low: list.filter((r) => r.running_low).length,
        spend: sum(list.map((r) => r.spend)),
      }))
      .sort((a, b) => (order.get(a.key) ?? 1e9) - (order.get(b.key) ?? 1e9))
  }, [inSite, order, siteNames])

  const needle = q.trim().toLowerCase()
  const shown = groups
    .filter((g) => category === 'all' || g.key === category)
    .map((g) => ({
      ...g,
      list: g.list.filter((r) => matchesShow(r, show) && (!needle || `${r.material_name} ${r.category ?? ''}`.toLowerCase().includes(needle))),
    }))
    .filter((g) => g.list.length > 0)
  const money = all.some((r) => r.spend !== null)
  const showSite = !siteId && new Set(inSite.map((r) => r.site_id)).size > 1
  const other = shown.some((g) => g.list.some((r) => Number(r.adjusted) !== 0))
  const coming = shown.some((g) => g.list.some((r) => Number(r.on_order) > 0))
  const asked = shown.some((g) => g.list.some((r) => flowOf(r).asked > 0))
  const filtered = category !== 'all' || !!show || !!needle || !!site

  const current = inSite.find((r) => `${r.site_id}:${r.material_id}` === opened) ?? null
  const currentSite = current ? siteNames.get(current.site_id ?? '') : undefined
  // The open item at every site this person can see (no project or site filter), for "At other sites".
  const elsewhere = useQuery({
    queryKey: ['materials', 'stock-summary', { ...range, material_id: current?.material_id }],
    queryFn: () => fetchStockSummary({ ...range, material_id: current!.material_id }),
    enabled: !!current,
  })
  const others: OtherSiteStock[] = React.useMemo(() => {
    if (!current) return []
    return (elsewhere.data ?? [])
      .filter((r) => r.site_id && r.site_id !== current.site_id && r.material_id === current.material_id)
      .map((r) => {
        const s = siteNames.get(r.site_id ?? '')
        return { row: r, siteName: s?.name ?? 'Site', projectName: s?.project ?? '', sameProject: r.project_id === current.project_id }
      })
      .sort((a, b) => Number(b.sameProject) - Number(a.sameProject) || Number(b.row.closing) - Number(a.row.closing))
  }, [current, elsewhere.data, siteNames])

  const tiles: { value: Exclude<Show, '' | 'all'>; label: string; count: number; icon: LucideIcon; iconTone: string; ring: string; numTone?: string }[] = [
    { value: 'low', label: 'Running low', count: inSite.filter((r) => r.running_low).length, icon: TrendingDown, iconTone: 'bg-orange-200 text-orange-950 dark:bg-orange-900 dark:text-orange-100', ring: 'ring-orange-500' },
    { value: 'out', label: 'Out of stock', count: inSite.filter(isOut).length, icon: PackageX, iconTone: 'bg-destructive text-white', ring: 'ring-destructive' },
    { value: 'coming', label: 'Coming on orders', count: inSite.filter((r) => Number(r.on_order ?? 0) > 0).length, icon: Truck, iconTone: 'bg-blue-100 text-blue-900 dark:bg-blue-950 dark:text-blue-100', ring: 'ring-blue-500' },
    { value: 'asked', label: 'Asked for', count: inSite.filter((r) => flowOf(r).asked > 0).length, icon: ClipboardList, iconTone: 'bg-yellow-100 text-yellow-900 dark:bg-yellow-950 dark:text-yellow-100', ring: 'ring-yellow-500' },
  ]
  for (const t of tiles) if (t.value === 'out' && t.count > 0) t.numTone = 'text-destructive'

  const siteOptions: FilterOption[] = React.useMemo(() => {
    const ids = [...new Set(all.map((r) => r.site_id).filter(Boolean))] as string[]
    return ids
      .map((id) => {
        const s = siteNames.get(id)
        return { value: id, label: s ? `${s.project} › ${s.name}` : 'Site', swatch: swatch(s?.projectId ?? id), count: all.filter((r) => r.site_id === id).length }
      })
      .sort((a, b) => a.label.localeCompare(b.label))
  }, [all, siteNames])

  const toolbar = (
    <div className="flex flex-wrap items-center gap-2">
      {leading}
      <div className="ml-auto flex flex-wrap items-center gap-2">
        {!siteId && siteOptions.length > 1 && <FilterPill icon={MapPin} label="Site" allLabel="All sites" value={site} options={siteOptions} onChange={setSite} />}
        <PeriodSelect value={period} onChange={setPeriod} from={from} to={to} onFrom={setFrom} onTo={setTo} />
        <label className="flex h-9 items-center gap-2 rounded-lg border bg-background px-2.5">
          <Search className="size-4 text-muted-foreground" />
          <span className="sr-only">Search items</span>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search" className="w-24 bg-transparent text-sm outline-none sm:w-32" />
        </label>
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

  const flow = current ? flowOf(current) : NO_FLOW
  const panel = current && (
    <StockItemPanel
      row={current}
      siteName={currentSite?.name}
      projectName={currentSite?.project}
      flow={flow}
      periodDays={daysIn(range)}
      money={money}
      canAsk={canAsk}
      canOrder={canOrder}
      canRecord={canRecord}
      onAsk={() => setDialog('ask')}
      onOrder={() => setDialog('order')}
      onRecord={() => setDialog('came')}
      others={others}
      othersLoading={elsewhere.isLoading}
      canMove={canRecord}
      onMove={(from) => {
        if (!from.site_id || !current.site_id) return
        setMovePrefill({ from_project_id: from.project_id, from_site_id: from.site_id, to_project_id: current.project_id, to_site_id: current.site_id, material_id: current.material_id })
        setDialog('move')
      }}
    />
  )
  // What to ask for or order: what the open requests still need to buy, else about two weeks' use, else nothing.
  const suggested = current
    ? (() => {
        const toBuy = flow.requests.reduce((n, x) => n + Number(x.line.to_buy), 0)
        if (toBuy > 0) return String(toBuy)
        const perDay = Number(current.used) / Math.max(1, daysIn(range))
        return perDay > 0 ? String(Math.ceil(perDay * 14)) : ''
      })()
    : ''
  const projectOf = current?.project_id ?? currentSite?.projectId ?? ''
  const askPrefill: RequestPrefill | null = current && current.site_id ? { project_id: projectOf, site_id: current.site_id, lines: [{ material_id: current.material_id, quantity: suggested }] } : null
  // From the waiting requests when there are some (the order then moves them on), else the item alone.
  const orderPrefill: OrderPrefill | null =
    current && current.site_id
      ? flow.requests.length === 1
        ? {
            project_id: projectOf,
            site_id: current.site_id,
            site_name: currentSite?.name,
            request_id: flow.requests[0].request.id,
            request_ref: flow.requests[0].request.ref,
            lines: flow.requests[0].request.lines.map((l) => ({ material_id: l.material_id, quantity: l.to_buy, request_line_id: l.id })).filter((l) => Number(l.quantity) > 0),
          }
        : { project_id: projectOf, site_id: current.site_id, site_name: currentSite?.name, lines: [{ material_id: current.material_id, quantity: suggested }] }
      : null

  return (
    <div className="flex flex-col gap-4">
      {toolbar}

      <div className="grid grid-cols-4 gap-2 sm:gap-3">
        {tiles.map((t) => {
          const on = show === t.value
          return (
            <button
              key={t.value}
              type="button"
              aria-pressed={on}
              onClick={() => setShow(on ? '' : t.value)}
              className={cn(
                'flex flex-col items-center gap-1 rounded-xl border bg-card p-2 text-center transition hover:-translate-y-px sm:flex-row sm:gap-3 sm:p-3.5 sm:text-left',
                on && cn('ring-2', t.ring),
              )}
            >
              <span className={cn('inline-flex size-8 shrink-0 items-center justify-center rounded-lg sm:size-11 sm:rounded-xl', t.iconTone)}>
                <t.icon className="size-4 sm:size-5" />
              </span>
              <span className="flex flex-col">
                <span className={cn('text-xl leading-none font-semibold tabular-nums sm:text-3xl', t.numTone)}>{isLoading ? '–' : t.count}</span>
                <span className="text-[11px] leading-tight text-muted-foreground sm:text-sm sm:text-foreground/80">{t.label}</span>
              </span>
            </button>
          )
        })}
      </div>

      {groups.length > 1 && (
        <div role="group" aria-label="Categories" className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
          {groups.map((g) => {
            const on = category === g.key
            return (
              <button
                key={g.key}
                type="button"
                aria-pressed={on}
                onClick={() => setCategory(on ? 'all' : g.key)}
                className={cn(
                  'flex shrink-0 items-center gap-2 rounded-xl border bg-card py-1.5 pr-3 pl-1.5 text-left transition hover:bg-muted/40',
                  on && 'border-yellow-500 bg-yellow-50 ring-1 ring-yellow-500 dark:bg-yellow-950',
                )}
              >
                <CategoryTile mainCategory={g.key === NONE ? null : g.key} size="sm" />
                <span className="flex flex-col leading-tight">
                  <span className="text-sm font-semibold whitespace-nowrap">{g.name}</span>
                  <span className="text-[11px] whitespace-nowrap text-muted-foreground">
                    {g.items} {g.items === 1 ? 'item' : 'items'}
                    {g.low > 0 && <span className="font-semibold text-draft"> · {g.low} low</span>}
                    {money && g.spend > 0 && <> · {formatMoney(String(g.spend))}</>}
                  </span>
                </span>
              </button>
            )
          })}
        </div>
      )}

      {isLoading ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-14 rounded-lg" />
          ))}
        </div>
      ) : groups.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center">
          <Boxes className="size-6 text-muted-foreground" aria-hidden="true" />
          <p className="text-sm font-medium">No stock in this period</p>
          <p className="max-w-sm text-sm text-muted-foreground">Record a delivery or opening stock, or import your list from Excel in Items.</p>
        </div>
      ) : shown.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-8 text-center">
          <p className="text-sm text-muted-foreground">Nothing matches these filters.</p>
          {filtered && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setCategory('all')
                setShow('')
                setQ('')
                setSite('')
              }}
            >
              Clear filters
            </Button>
          )}
        </div>
      ) : (
        <>
          {shown.map((g) => (
            <section key={g.key} className="flex flex-col gap-1.5">
              <h3 className="flex items-center gap-2 text-sm font-semibold">
                <CategoryTile mainCategory={g.key === NONE ? null : g.key} size="sm" />
                {g.name} <span className="font-normal text-muted-foreground">{g.list.length}</span>
              </h3>

              {/* Phone: one stacked row per item; an item at several sites is one row that opens to its sites */}
              <ul className="divide-y overflow-hidden rounded-xl border sm:hidden">
                {bundles(g.list).map((b, i, all) => {
                  const sub = subOf(b.total)
                  const heading = sub && sub !== (i > 0 ? subOf(all[i - 1].total) : null)
                  const many = b.rows.length > 1
                  const expanded = many && (open.has(b.key) || filtered)
                  return (
                    <React.Fragment key={b.key}>
                      {heading && <li className="bg-muted/30 px-3 py-1 text-xs font-semibold text-muted-foreground">{sub}</li>}
                      {many && (
                        <li>
                          <button
                            type="button"
                            aria-expanded={expanded}
                            onClick={() => toggle(b.key)}
                            className={cn('flex w-full flex-col gap-1 px-3 py-2.5 text-left', b.low > 0 && 'bg-draft-soft/40')}
                          >
                            <span className="flex items-baseline justify-between gap-2">
                              <span className="flex min-w-0 items-center gap-1 font-semibold">
                                {expanded ? <ChevronDown className="size-4 shrink-0 text-muted-foreground" /> : <ChevronRight className="size-4 shrink-0 text-muted-foreground" />}
                                <span className="truncate">{b.total.material_name}</span>
                              </span>
                              <span className={cn('shrink-0 font-semibold tabular-nums', Number(b.total.closing) < 0 && 'text-destructive')}>
                                {qty(b.total.closing)} <span className="font-normal text-muted-foreground">{b.total.unit}</span>
                              </span>
                            </span>
                            <span className="flex items-center justify-between gap-2 pl-5 text-xs text-muted-foreground">
                              <span className="min-w-0 truncate">{whereItIs(b, siteNames)}</span>
                              <SitesChip bundle={b} />
                            </span>
                          </button>
                        </li>
                      )}
                      {(!many || expanded) &&
                        b.rows.map((r) => {
                          const f = flowOf(r)
                          return (
                            <li key={`${r.site_id}:${r.material_id}`}>
                              <button
                                type="button"
                                onClick={() => setOpened(`${r.site_id}:${r.material_id}`)}
                                className={cn('flex w-full flex-col gap-1 px-3 py-2.5 text-left', many && 'bg-muted/10 pl-8', r.running_low && 'bg-draft-soft/40')}
                              >
                                <span className="flex items-baseline justify-between gap-2">
                                  <span className={cn('min-w-0 truncate', many ? 'text-sm font-medium' : 'font-semibold')}>
                                    {many ? siteNames.get(r.site_id ?? '')?.name ?? 'Site' : r.material_name}
                                  </span>
                                  <span className={cn('shrink-0 font-semibold tabular-nums', Number(r.closing) < 0 && 'text-destructive')}>
                                    {qty(r.closing)} <span className="font-normal text-muted-foreground">{r.unit}</span>
                                  </span>
                                </span>
                                <span className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                                  <span className="min-w-0 truncate">
                                    {[
                                      showSite && !many ? siteNames.get(r.site_id ?? '')?.name : null,
                                      Number(r.received) ? `${signed(r.received, '+')} in` : null,
                                      Number(r.used) ? `${signed(r.used, '−')} used` : null,
                                    ]
                                      .filter(Boolean)
                                      .join(' · ') || `before ${qty(r.opening)}`}
                                  </span>
                                  <StockChip row={r} />
                                </span>
                                {(Number(r.on_order) > 0 || f.asked > 0) && (
                                  <span className="flex flex-wrap gap-1.5 text-[11px] font-semibold">
                                    {Number(r.on_order) > 0 && <span className="rounded-md bg-blue-100 px-1.5 py-0.5 text-blue-950 dark:bg-blue-950 dark:text-blue-100">+{qty(r.on_order ?? '0')} coming</span>}
                                    {f.asked > 0 && <span className="rounded-md bg-yellow-100 px-1.5 py-0.5 text-yellow-950 dark:bg-yellow-950 dark:text-yellow-100">{qty(String(f.asked))} asked</span>}
                                  </span>
                                )}
                              </button>
                            </li>
                          )
                        })}
                    </React.Fragment>
                  )
                })}
              </ul>

              {/* Wider screens: a table; an item at several sites is a total row that opens to its sites */}
              <div className="hidden overflow-x-auto rounded-xl border sm:block">
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
                      {coming && <th className="px-3 py-2 text-right font-semibold" title="Still to come on open purchase orders">Coming</th>}
                      {asked && <th className="px-3 py-2 text-right font-semibold" title="Asked for on requests waiting for the office">Asked</th>}
                      <th className="px-3 py-2 font-semibold">Lasts</th>
                      {money && <th className="px-3 py-2 text-right font-semibold">Last rate</th>}
                      {money && <th className="px-3 py-2 text-right font-semibold">Spend</th>}
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {bundles(g.list).map((b, i, all) => {
                      const sub = subOf(b.total)
                      const heading = sub && sub !== (i > 0 ? subOf(all[i - 1].total) : null)
                      const many = b.rows.length > 1
                      const expanded = many && (open.has(b.key) || filtered)
                      const askedAll = b.rows.reduce((n, r) => n + flowOf(r).asked, 0)
                      return (
                        <React.Fragment key={b.key}>
                          {heading && (
                            <tr className="bg-muted/20">
                              <td colSpan={12} className="px-3 py-1.5 text-xs font-semibold text-muted-foreground">
                                {sub}
                              </td>
                            </tr>
                          )}
                          {many && (
                            <tr
                              className={cn('cursor-pointer hover:bg-muted/30', b.low > 0 && 'bg-draft-soft/40')}
                              onClick={() => toggle(b.key)}
                              aria-expanded={expanded}
                              title={whereItIs(b, siteNames)}
                            >
                              <td className="px-3 py-2 font-semibold">
                                <span className="flex items-center gap-1">
                                  {expanded ? <ChevronDown className="size-4 shrink-0 text-muted-foreground" /> : <ChevronRight className="size-4 shrink-0 text-muted-foreground" />}
                                  {b.total.material_name}
                                </span>
                              </td>
                              {showSite && (
                                <td className="max-w-56 px-3 py-2 text-muted-foreground">
                                  <span className="block truncate">{expanded ? `${b.rows.length} sites` : whereItIs(b, siteNames)}</span>
                                </td>
                              )}
                              <StockCells row={b.total} asked={askedAll} other={other} coming={coming} askedCol={asked} money={money} lastsCell={<SitesChip bundle={b} />} bold />
                            </tr>
                          )}
                          {(!many || expanded) &&
                            b.rows.map((r) => {
                              const key = `${r.site_id}:${r.material_id}`
                              return (
                                <tr
                                  key={key}
                                  className={cn('cursor-pointer hover:bg-muted/30', many && 'bg-muted/10', r.running_low && 'bg-draft-soft/40', opened === key && 'bg-yellow-50 dark:bg-yellow-950/40')}
                                  onClick={() => setOpened(key)}
                                >
                                  <td className={cn('px-3 py-2 font-medium', many && 'pl-9 font-normal text-muted-foreground')}>{many ? '└' : r.material_name}</td>
                                  {showSite && <td className={cn('px-3 py-2', many ? 'font-medium' : 'text-muted-foreground')}>{siteNames.get(r.site_id ?? '')?.name ?? 'Site'}</td>}
                                  <StockCells row={r} asked={flowOf(r).asked} other={other} coming={coming} askedCol={asked} money={money} lastsCell={<StockChip row={r} />} />
                                </tr>
                              )
                            })}
                        </React.Fragment>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          ))}
          {money && shown.some((g) => g.list.some((r) => r.spend_complete === false && Number(r.received) > 0)) && (
            <p className="text-xs text-muted-foreground">* Some deliveries in this period have no price, so the spend shown is less than paid.</p>
          )}
        </>
      )}

      <Sheet open={!!current} onOpenChange={(o) => !o && setOpened('')}>
        <SheetContent side={isMobile ? 'bottom' : 'right'} className={cn('gap-0 overflow-y-auto p-0', isMobile ? 'max-h-[92vh] rounded-t-2xl' : 'w-full sm:max-w-lg')}>
          {panel}
        </SheetContent>
      </Sheet>

      <NewRequestDialog open={dialog === 'ask'} onOpenChange={(o) => setDialog(o ? 'ask' : null)} scope={scope} prefill={askPrefill} />
      <NewOrderDialog open={dialog === 'order'} onOpenChange={(o) => setDialog(o ? 'order' : null)} scope={scope} prefill={orderPrefill} />
      <RecordTransferDialog open={dialog === 'move'} onOpenChange={(o) => setDialog(o ? 'move' : null)} scope={scope} prefill={movePrefill} />
      <RecordInflowDialog
        open={dialog === 'came'}
        onOpenChange={(o) => setDialog(o ? 'came' : null)}
        scope={scope}
        prefill={current && current.site_id ? { project_id: projectOf, site_id: current.site_id, material_id: current.material_id } : null}
      />
    </div>
  )
}

/** How long it lasts, as the row's one status: out, running low (orange), or the plain days. */
function StockChip({ row: r }: { row: StockSummaryRow }) {
  if (r.running_low) return <span className={cn(CHIP, 'shrink-0 bg-draft-soft text-draft')}>{Number(r.closing) <= 0 ? 'Out' : lasts(r.days_left ?? 0)}</span>
  return <span className="shrink-0 text-muted-foreground">{lasts(r.days_left) || '—'}</span>
}

/** Where an item is, site by site: "Green Villa 117 · Site B out". */
function whereItIs(b: Bundle, siteNames: Map<string, { name: string }>): string {
  return b.rows.map((r) => `${siteNames.get(r.site_id ?? '')?.name ?? 'Site'} ${Number(r.closing) <= 0 ? 'out' : qty(r.closing)}`).join(' · ')
}

/** An item's status across its sites: how many are low, else how many sites hold it. */
function SitesChip({ bundle: b }: { bundle: Bundle }) {
  if (b.low > 0) return <span className={cn(CHIP, 'shrink-0 bg-draft-soft text-draft')}>{b.low === 1 ? '1 site low' : `${b.low} sites low`}</span>
  return <span className="shrink-0 text-muted-foreground">{b.rows.length} sites</span>
}

/** The number cells of a stock row, shared by an item at one site and an item's total across sites. */
function StockCells({
  row: r,
  asked,
  other,
  coming,
  askedCol,
  money,
  lastsCell,
  bold,
}: {
  row: StockSummaryRow
  asked: number
  other: boolean
  coming: boolean
  askedCol: boolean
  money: boolean
  lastsCell: React.ReactNode
  bold?: boolean
}) {
  return (
    <>
      <td className="px-3 py-2 text-right tabular-nums">{qty(r.opening)}</td>
      <td className="px-3 py-2 text-right tabular-nums">{signed(r.received, '+')}</td>
      {other && <td className="px-3 py-2 text-right tabular-nums">{signed(r.adjusted, Number(r.adjusted) > 0 ? '+' : '−')}</td>}
      <td className="px-3 py-2 text-right tabular-nums">{signed(r.used, '−')}</td>
      <td className={cn('px-3 py-2 text-right tabular-nums', bold ? 'font-bold' : 'font-semibold', Number(r.closing) < 0 && 'text-destructive')}>
        {qty(r.closing)} <span className="font-normal text-muted-foreground">{r.unit}</span>
      </td>
      {coming && <td className="px-3 py-2 text-right tabular-nums text-info">{Number(r.on_order) > 0 ? `+${qty(r.on_order ?? '0')}` : <span className="text-muted-foreground">—</span>}</td>}
      {askedCol && <td className="px-3 py-2 text-right tabular-nums">{asked > 0 ? <span className="font-semibold">{qty(String(asked))}</span> : <span className="text-muted-foreground">—</span>}</td>}
      <td className="px-3 py-2">{lastsCell}</td>
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
    </>
  )
}
