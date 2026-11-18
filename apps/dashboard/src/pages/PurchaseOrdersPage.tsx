import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlarmClock, CalendarDays, CircleX, LayoutGrid, MapPin, PackageCheck, PackageOpen, Plus, ReceiptText, Search, ShoppingCart, Store, Truck } from 'lucide-react'
import { exportCsv } from '@/lib/export'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { useScope } from '@/lib/ScopeContext'
import { useAuth } from '@/lib/AuthContext'
import { usePageTitle } from '@/lib/page-title'
import { useUrlState } from '@/lib/url-state'
import { useReadOnly } from '@/lib/trial'
import { useIsMobile } from '@/hooks/use-mobile'
import { cn } from '@/lib/utils'
import { URGENCY_LOOK, qty, swatch, type Urgency } from '@/lib/requests'
import { ORDER_LOOK, dueWords, fetchOrders, rupees, type OrderStatus, type PurchaseOrder } from '@/lib/orders'
import { CategoryTile, FilterPill, ProjectDot, type FilterOption } from '@/components/requests/parts'
import { OrderDetail, OrderProgress, VendorTile } from '@/components/orders/order-detail'
import { NewOrderDialog } from '@/components/orders/new-order-dialog'
import { KpiStrip, ModuleTitle, Pill, StateBar, type KpiItem, type StateItem } from '@/components/page/page-kit'
import { ScoreChip } from '@/components/vendors/supplier-score'
import { useSupplierScores, type SupplierPerformance } from '@/lib/supplier-performance'
import { fetchRates, type RateItem } from '@/lib/rates'
import { fetchUnbilled } from '@/lib/vendors'
import { compact, mayManageMoney } from '@/lib/expenses'
import type { Tone } from '@/lib/list-kit'
import { ActionIcon } from '@/components/page/action-button'
import { appNow } from '@/lib/clock'
import { Pager } from '@/components/page/pager'
import { usePagedUrl } from '@/lib/paging'

// PRC-10: Procurement > Purchase orders, in the Requests page's visual language (approved 7 Nov): tiles for what
// needs attention, status tabs, filter dropdowns with the row cues, a list beside the chosen order (a sheet on a
// phone). Late first. What came and what is still to come are read from deliveries.
// UX-65 (18 Nov): figures in rupees (to come, late, ordered this month, delivered but not billed); the tabs and filters
// in one StateBar box; on each row the supplier's score, the rate against the best rate paid for that material
// (GET /procurement/rates), and three steps Ordered · Came · Billed (not billed: GET /finance/vendors/unbilled).

type Tab = 'open' | 'part' | 'received' | 'closed' | 'all'
type Tile = '' | 'open' | 'late' | 'soon' | 'part' | 'unbilled'

// UX-65: the status tabs as the list kit's StateBar, one tone each.
const TABS: { value: Exclude<Tab, 'all'>; label: string; icon: typeof Truck; tone: Tone }[] = [
  { value: 'open', label: 'To come', icon: Truck, tone: 'info' },
  { value: 'part', label: 'Part received', icon: PackageOpen, tone: 'attention' },
  { value: 'received', label: 'Received', icon: PackageCheck, tone: 'good' },
  { value: 'closed', label: 'Closed', icon: CircleX, tone: 'muted' },
]

function inTab(o: PurchaseOrder, tab: Tab): boolean {
  if (tab === 'open') return o.status === 'open' || o.status === 'part'
  if (tab === 'closed') return o.status === 'closed' || o.status === 'cancelled'
  if (tab === 'all') return true
  return o.status === tab
}

function inTile(o: PurchaseOrder, tile: Tile): boolean {
  if (tile === 'open') return o.status === 'open' || o.status === 'part'
  if (tile === 'late') return o.urgency === 'late'
  if (tile === 'soon') return o.urgency === 'soon'
  if (tile === 'part') return o.status === 'part'
  return true
}

const ORDER: Record<Urgency, number> = { late: 0, soon: 1, later: 2, closed: 3 }

/** PRC-31: the orders shown (tab and filters applied), one row per item, for Excel. Rates only when the API sent them. */
function exportOrders(items: PurchaseOrder[]): void {
  const rows = items.flatMap((o) => o.lines.map((l) => [
    o.ref, o.their_ref ?? '', ORDER_LOOK[o.status].label, o.vendor_name, o.project_name, o.site_name, o.created_by_name ?? '', o.created_at.slice(0, 10),
    o.expected_date ?? '', l.material, Number(l.quantity), l.unit, l.rate === null ? '' : Number(l.rate), l.amount === null ? '' : Number(l.amount),
    Number(l.received), Number(l.pending), l.request?.ref ?? '', o.notes ?? '', o.status_note ?? '',
  ]))
  exportCsv(`purchase-orders-${appNow().toISOString().slice(0, 10)}.csv`,
    ['Order', 'Their number', 'Status', 'Supplier', 'Project', 'Site', 'Ordered by', 'Ordered on', 'Expected', 'Item', 'Quantity', 'Unit', 'Rate',
      'Amount', 'Received', 'Still to come', 'Request', 'Notes', 'Closed / cancelled because'], rows)
}

export default function PurchaseOrdersPage() {
  usePageTitle('Purchase orders')
  const { scope } = useScope()
  const { me } = useAuth()
  const readOnly = useReadOnly()
  const isMobile = useIsMobile()
  const projectId = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : null
  const siteId = scope.mode === 'site' ? scope.siteId : null
  const office = ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'PROJECT_MANAGER'].includes((me?.role || '').toUpperCase())

  const [tab, setTab] = useUrlState<Tab>('tab', 'open')
  const [tile, setTile] = useUrlState<Tile>('show', '')
  const [site, setSite] = useUrlState<string>('at', '')  // PRC-27: not 'site' (the scope's own key, as WEB-34)
  const [vendor, setVendor] = useUrlState<string>('vendor', '')
  const [category, setCategory] = useUrlState<string>('category', '')
  const [due, setDue] = useUrlState<string>('due', '')
  const [selected, setSelected] = useUrlState<string>('id', '')
  const [search, setSearch] = React.useState('')
  const [creating, setCreating] = React.useState(false)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['procurement', 'orders', projectId, siteId],
    queryFn: () => fetchOrders({ project_id: projectId, site_id: siteId }),
    refetchInterval: 60_000,
  })
  const all = React.useMemo(() => data?.items ?? [], [data])
  // UX-65: the money roles see rates, scores and what came but is not billed.
  const money = mayManageMoney(me?.role) || (me?.role || '').toUpperCase() === 'PROJECT_MANAGER'
  const scores = useSupplierScores()
  const rates = useQuery({ queryKey: ['procurement', 'rates', 'all'], queryFn: () => fetchRates(), enabled: money, staleTime: 5 * 60_000, retry: false })
  const bestRate = React.useMemo(() => new Map((rates.data?.items ?? []).map((r) => [r.material_id, r])), [rates.data])
  const unbilled = useQuery({ queryKey: ['finance', 'unbilled', projectId ?? ''], queryFn: () => fetchUnbilled(projectId ? { project_id: projectId } : {}), enabled: money, staleTime: 60_000, retry: false })
  const unbilledBy = React.useMemo(() => {
    const m = new Map<string, number>()
    for (const d of unbilled.data?.deliveries ?? []) if (d.order_id) m.set(d.order_id, (m.get(d.order_id) ?? 0) + Number(d.amount ?? 0))
    return m
  }, [unbilled.data])

  const pass = React.useCallback((o: PurchaseOrder, skip?: string) => {
    if (skip !== 'site' && site && o.site_id !== site) return false
    if (skip !== 'vendor' && vendor && o.vendor_id !== vendor) return false
    if (skip !== 'category' && category && !o.lines.some((l) => (l.main_category ?? '—') === category)) return false
    if (skip !== 'due' && due && o.urgency !== due) return false
    if (search) {
      const q = search.toLowerCase()
      if (!o.ref.toLowerCase().includes(q) && !(o.their_ref ?? '').toLowerCase().includes(q) && !o.vendor_name.toLowerCase().includes(q) && !o.lines.some((l) => l.material.toLowerCase().includes(q))) return false
    }
    return true
  }, [site, vendor, category, due, search])

  const filtered = React.useMemo(() => all.filter((o) => pass(o)), [all, pass])
  const list = React.useMemo(
    () => filtered.filter((o) => (tile === 'unbilled' ? unbilledBy.has(o.id) : tile ? inTile(o, tile) : inTab(o, tab)))
      .sort((a, b) => ORDER[a.urgency] - ORDER[b.urgency] || (a.expected_date ?? '9999').localeCompare(b.expected_date ?? '9999') || b.number - a.number),
    [filtered, tab, tile, unbilledBy],
  )
  // UX-37: numbered pages, kept in the address.
  const pagedList = usePagedUrl(list)
  // The one being worked on stays open when acting on it moves it to another tab (ordered, received); a tab change or
  // a pick of another row lets it go.
  const [kept, setKept] = React.useState('')
  React.useEffect(() => setKept(''), [tab])
  const current = all.find((o) => o.id === selected) ?? (isMobile ? undefined : all.find((o) => o.id === kept) ?? list[0])
  React.useEffect(() => {
    if (!selected && current && current.id !== kept) setKept(current.id)
  }, [selected, current, kept])

  const options = React.useMemo(() => {
    const count = (skip: string, test: (o: PurchaseOrder) => boolean) => all.filter((o) => pass(o, skip) && test(o)).length
    const uniq = <T,>(xs: T[], key: (t: T) => string) => [...new Map(xs.map((x) => [key(x), x])).values()]
    const sites: FilterOption[] = uniq(all, (o) => o.site_id).map((o) => ({ value: o.site_id, label: `${o.project_name} › ${o.site_name}`, swatch: swatch(o.project_id), count: count('site', (x) => x.site_id === o.site_id) }))
    const vendors: FilterOption[] = uniq(all, (o) => o.vendor_id).map((o) => ({ value: o.vendor_id, label: o.vendor_name, swatch: swatch(o.vendor_id), count: count('vendor', (x) => x.vendor_id === o.vendor_id) }))
    const mains = [...new Set(all.flatMap((o) => o.lines.map((l) => l.main_category ?? '—')))].sort()
    const categories: FilterOption[] = mains.map((m) => ({ value: m, label: m === '—' ? 'No category' : m, category: m === '—' ? null : m, count: count('category', (x) => x.lines.some((l) => (l.main_category ?? '—') === m)) }))
    const dues: FilterOption[] = (['late', 'soon', 'later', 'closed'] as Urgency[]).map((u) => ({ value: u, label: { late: 'Late', soon: 'Due in 2 days', later: 'Later', closed: 'Done' }[u], dot: URGENCY_LOOK[u].dot, count: count('due', (x) => x.urgency === u) }))
    return { sites, vendors, categories, dues }
  }, [all, pass])

  const openValue = filtered.filter((o) => inTile(o, 'open') && o.value).reduce((n, o) => n + Number(o.value) - Number(o.value_received ?? 0), 0)
  const late = filtered.filter((o) => o.urgency === 'late')
  const lateValue = late.reduce((n, o) => n + Number(o.value ?? 0) - Number(o.value_received ?? 0), 0)
  const month = appNow().toISOString().slice(0, 7)
  const thisMonth = filtered.filter((o) => o.created_at.slice(0, 7) === month && o.status !== 'cancelled')
  const monthValue = thisMonth.reduce((n, o) => n + Number(o.value ?? 0), 0)
  const unbilledValue = filtered.reduce((n, o) => n + (unbilledBy.get(o.id) ?? 0), 0)
  const unbilledCount = filtered.filter((o) => unbilledBy.has(o.id)).length
  const toggle = (t: Exclude<Tile, ''>) => setTile(tile === t ? '' : t)
  const openCount = filtered.filter((o) => inTile(o, 'open')).length
  const tiles = ([
    { key: 'open', label: 'To come', value: money && openValue ? compact(openValue) : openCount || '—', icon: Truck, tone: 'info', hint: money ? `${openCount} orders` : undefined, pressed: tile === 'open', onClick: () => toggle('open') },
    { key: 'late', label: 'Late', value: late.length || '—', icon: AlarmClock, tone: late.length ? 'bad' : 'default', hint: money && lateValue ? compact(lateValue) : undefined, pressed: tile === 'late', onClick: () => toggle('late') },
    { key: 'soon', label: 'Due in 2 days', value: filtered.filter((o) => o.urgency === 'soon').length || '—', icon: CalendarDays, tone: 'default', pressed: tile === 'soon', onClick: () => toggle('soon') },
    ...(money ? [
      { key: 'month', label: 'Ordered this month', value: monthValue ? compact(monthValue) : '—', kind: 'money', hint: `${thisMonth.length} orders` },
      { key: 'unbilled', label: 'Came, not billed', value: unbilledValue ? compact(unbilledValue) : '—', icon: ReceiptText, tone: unbilledValue ? 'attention' : 'default', hint: unbilledCount ? `${unbilledCount} orders` : undefined, pressed: tile === 'unbilled', onClick: () => toggle('unbilled') },
    ] : [
      { key: 'part', label: 'Part received', value: filtered.filter((o) => o.status === 'part').length || '—', icon: PackageOpen, pressed: tile === 'part', onClick: () => toggle('part') },
    ]),
  ] as KpiItem[]).map((k) => ({ ...k, loading: isLoading }))

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <header className="flex items-center justify-between gap-3">
        <ModuleTitle icon={ShoppingCart} title="Purchase orders" />
        <div className="flex items-center gap-3">
          <Button variant="outline" className="gap-2" disabled={!list.length} onClick={() => exportOrders(list)} title="The orders shown, as a CSV file (opens in Excel)"><ActionIcon kind="export-excel" className="size-4" /> <span className="hidden sm:inline">Export</span></Button>
          {office && !readOnly && <Button className="hidden gap-2 font-semibold md:inline-flex" onClick={() => setCreating(true)} data-guide="po.add"><Plus className="size-4" strokeWidth={2.6} /> New order</Button>}
        </div>
      </header>

      <KpiStrip guide="po.tiles" stats={tiles} />

      <div data-guide="po.tabs">
        <StateBar
          strip={false}
          items={TABS.map((t): StateItem => ({ value: t.value, label: t.label, icon: t.icon, tone: t.tone, count: filtered.filter((o) => inTab(o, t.value)).length }))}
          value={tile || tab === 'all' ? '' : tab}
          onChange={(v) => { setTile(''); setTab((v || 'all') as Tab) }}
          extra={<button type="button" onClick={() => { setTile(''); setTab('all') }} aria-pressed={!tile && tab === 'all'} className={cn('rounded-full px-2.5 py-1 text-xs font-semibold', !tile && tab === 'all' ? 'bg-foreground text-background' : 'text-muted-foreground hover:text-foreground')}>All <span className="tabular-nums">{filtered.length}</span></button>}
        >
          <div className="flex flex-wrap items-center gap-2" data-guide="po.filters">
            {!siteId && <FilterPill icon={MapPin} label="Site" allLabel="All sites" value={site} options={options.sites} onChange={setSite} />}
            <FilterPill icon={Store} label="Supplier" allLabel="Every supplier" value={vendor} options={options.vendors} onChange={setVendor} />
            <FilterPill icon={LayoutGrid} label="Category" allLabel="All categories" value={category} options={options.categories} onChange={setCategory} />
            <FilterPill icon={CalendarDays} label="Due" allLabel="Any date" value={due} options={options.dues} onChange={setDue} />
            <label className="flex h-9 items-center gap-2 rounded-lg border bg-background px-2.5">
              <Search className="size-4 text-muted-foreground" />
              <span className="sr-only">Search orders</span>
              <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="PO, supplier, item" className="w-28 bg-transparent text-sm outline-none sm:w-36" />
            </label>
          </div>
        </StateBar>
      </div>

      <div className="flex flex-col items-start gap-5 lg:flex-row">
        <div className="flex w-full min-w-0 flex-1 flex-col gap-2">
        <section aria-label="Purchase orders" className="w-full overflow-hidden rounded-xl border bg-card" data-guide={isLoading ? undefined : 'po.list'}>
          {isLoading && <div className="flex flex-col">{[0, 1, 2].map((i) => <div key={i} className="h-24 animate-pulse border-b bg-muted/40" />)}</div>}
          {isError && <p className="p-6 text-sm text-destructive">Orders did not load. Refresh to try again.</p>}
          {!isLoading && !isError && list.length === 0 && (
            <div className="flex flex-col items-center gap-2 px-4 py-12 text-center text-sm text-muted-foreground">
              <PackageOpen className="size-8 opacity-40" />
              {all.length === 0 ? 'No orders yet' : tab === 'open' ? 'Nothing still to come.' : 'No orders here with these filters.'}
            </div>
          )}
          {pagedList.shown.map((o) => <OrderRow key={o.id} order={o} selected={current?.id === o.id} onPick={() => setSelected(o.id)} score={scores.get(o.vendor_id)} best={bestRate} unbilled={money ? unbilledBy.get(o.id) ?? 0 : null} />)}
        </section>
          <Pager {...pagedList.pager} noun="orders" />
        </div>
        {!isMobile && current && (
          <aside aria-label="Order detail" className="sticky top-4 w-full shrink-0 overflow-hidden rounded-xl border lg:w-[420px]"><OrderDetail order={current} /></aside>
        )}
      </div>

      {isMobile && (
        <Sheet open={!!current} onOpenChange={(o) => !o && setSelected('')}>
          <SheetContent side="bottom" className="max-h-[92vh] gap-0 overflow-y-auto rounded-t-2xl p-0">
            <SheetTitle className="sr-only">{current ? `${current.ref} order` : 'Order'}</SheetTitle>
            {current && <OrderDetail order={current} inSheet />}
          </SheetContent>
        </Sheet>
      )}
      {office && !readOnly && (
        <Button className="fixed right-4 bottom-5 z-30 h-12 gap-2 rounded-full px-5 font-semibold shadow-lg md:hidden" onClick={() => setCreating(true)} data-guide="po.add"><Plus className="size-5" strokeWidth={2.6} /> Order</Button>
      )}
      <NewOrderDialog open={creating} onOpenChange={setCreating} scope={scope} />
    </div>
  )
}

/** UX-65: the order's rate against the best average paid for its first priced line's material: a chip when dearer. */
function RateCheck({ order, best }: { order: PurchaseOrder; best: Map<string, RateItem> }) {
  const line = order.lines.find((l) => l.rate && best.get(l.material_id)?.best)
  if (!line) return null
  const item = best.get(line.material_id)!
  const top = Number(item.best!.avg_rate)
  const pct = top > 0 ? Math.round((Number(line.rate) / top - 1) * 100) : 0
  const title = `₹${Number(line.rate).toLocaleString('en-IN')}/${line.unit} · best ₹${top.toLocaleString('en-IN')} (${item.best!.vendor_name})`
  if (pct >= 2) return <Pill tone={pct >= 8 ? 'bad' : 'attention'} size="xs" title={title}>{pct}% dearer</Pill>
  if (pct <= 0) return <Pill tone="good" size="xs" title={title}>Best rate</Pill>
  return null
}

/** UX-65: Ordered · Came · Billed, three dots (green done, amber part or not billed, grey not yet). */
function Steps({ order, unbilled }: { order: PurchaseOrder; unbilled: number }) {
  const came = order.progress > 0
  const billed = came && unbilled <= 0
  const dot = (on: boolean, good: boolean) => cn('size-2 rounded-full', !on ? 'bg-muted-foreground/25' : good ? 'bg-success' : 'bg-draft')
  return (
    <span className="inline-flex items-center gap-1" title={`Ordered · ${came ? `came ${Math.round(order.progress * 100)}%` : 'nothing came yet'} · ${!came ? 'not billed' : billed ? 'billed' : `₹${Math.round(unbilled).toLocaleString('en-IN')} not billed`}`}>
      <span className={dot(true, true)} /><span className="h-px w-2 bg-border" />
      <span className={dot(came, order.progress >= 1)} /><span className="h-px w-2 bg-border" />
      <span className={dot(came, billed)} />
    </span>
  )
}

function OrderRow({ order: o, selected, onPick, score, best, unbilled }: { order: PurchaseOrder; selected: boolean; onPick: () => void; score?: SupplierPerformance; best: Map<string, RateItem>; unbilled: number | null }) {
  const first = o.lines[0]
  const more = o.lines.length - 1
  const look = ORDER_LOOK[o.status as OrderStatus]
  return (
    <button type="button" onClick={onPick} aria-current={selected || undefined} className={cn('flex w-full gap-3 border-b px-3 py-3 text-left transition hover:bg-muted/40 sm:px-4', selected && 'bg-yellow-50 shadow-[inset_0_0_0_2px_theme(colors.yellow.300)] dark:bg-yellow-950/40')}>
      <VendorTile id={o.vendor_id} name={o.vendor_name} />
      <span className="flex min-w-0 flex-1 flex-col gap-1.5">
        <span className="flex items-center justify-between gap-2">
          <span className="flex min-w-0 items-center gap-1.5"><span className="truncate font-semibold">{o.vendor_name}</span><ScoreChip p={score} /><span className="shrink-0 text-xs text-muted-foreground tabular-nums">{o.ref}{o.their_ref ? ` · ${o.their_ref}` : ''}</span></span>
          {o.urgency !== 'closed' && <span className={cn('inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-semibold whitespace-nowrap', URGENCY_LOOK[o.urgency].chip)}>{dueWords(o)}</span>}
        </span>
        <span className="flex items-center gap-2 text-sm">
          {first && <CategoryTile mainCategory={first.main_category} size="sm" />}
          <span className="min-w-0 truncate">{first?.material} <span className="text-foreground/70 tabular-nums">{first && qty(first.quantity, first.unit)}</span>{more > 0 && <span className="ml-1.5 rounded-full bg-muted px-1.5 text-xs font-semibold">+{more}</span>}</span>
        </span>
        <span className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          {o.progress > 0 ? (
            <><OrderProgress order={o} className="w-28 sm:w-40" /><span className="tabular-nums">{Math.round(o.progress * 100)}% came</span></>
          ) : o.status !== 'cancelled' && o.status !== 'closed' && <span className="inline-flex items-center gap-1"><Truck className="size-3.5" />to come</span>}
          {unbilled !== null && o.status !== 'cancelled' && <Steps order={o} unbilled={unbilled} />}
          <RateCheck order={o} best={best} />
          <span className="inline-flex items-center gap-1"><ProjectDot id={o.project_id} />{o.site_name}</span>
          {o.value && <span className="font-semibold text-foreground tabular-nums">{rupees(o.value)}</span>}
          <span className={cn('ml-auto inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-semibold', look.chip)}><span className={cn('size-1.5 rounded-full', look.dot)} />{look.label}</span>
        </span>
      </span>
    </button>
  )
}
