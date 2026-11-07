import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlarmClock, CalendarDays, Download, LayoutGrid, MapPin, PackageOpen, Plus, Search, ShoppingCart, Store, Truck } from 'lucide-react'
import { exportCsv } from '@/lib/export'
import type { LucideIcon } from 'lucide-react'
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

// PRC-10: Procurement > Purchase orders, in the Requests page's visual language (approved 7 Nov): tiles for what
// needs attention, status tabs, filter dropdowns with the row cues, a list beside the chosen order (a sheet on a
// phone). Late first. What came and what is still to come are read from deliveries.

type Tab = 'open' | 'part' | 'received' | 'closed' | 'all'
type Tile = '' | 'open' | 'late' | 'soon' | 'part'

const TABS: { value: Tab; label: string; dot: string }[] = [
  { value: 'open', label: 'To come', dot: ORDER_LOOK.open.dot },
  { value: 'part', label: 'Part received', dot: ORDER_LOOK.part.dot },
  { value: 'received', label: 'Received', dot: ORDER_LOOK.received.dot },
  { value: 'closed', label: 'Closed', dot: ORDER_LOOK.closed.dot },
  { value: 'all', label: 'All', dot: 'bg-muted-foreground/50' },
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
  exportCsv(`purchase-orders-${new Date().toISOString().slice(0, 10)}.csv`,
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
  const [site, setSite] = useUrlState<string>('site', '')
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
    () => filtered.filter((o) => (tile ? inTile(o, tile) : inTab(o, tab)))
      .sort((a, b) => ORDER[a.urgency] - ORDER[b.urgency] || (a.expected_date ?? '9999').localeCompare(b.expected_date ?? '9999') || b.number - a.number),
    [filtered, tab, tile],
  )
  const current = all.find((o) => o.id === selected) ?? (isMobile ? undefined : list[0])

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

  const tiles: { value: Exclude<Tile, ''>; label: string; count: number; icon: LucideIcon; tone: string; ring: string; num?: string }[] = [
    { value: 'open', label: 'Still to come', count: filtered.filter((o) => inTile(o, 'open')).length, icon: ShoppingCart, tone: 'bg-info-soft text-info', ring: 'ring-blue-500' },
    { value: 'late', label: 'Late', count: filtered.filter((o) => o.urgency === 'late').length, icon: AlarmClock, tone: 'bg-destructive text-white', ring: 'ring-destructive', num: 'text-destructive' },
    { value: 'soon', label: 'Due in 2 days', count: filtered.filter((o) => o.urgency === 'soon').length, icon: CalendarDays, tone: 'bg-orange-200 text-orange-950 dark:bg-orange-900 dark:text-orange-100', ring: 'ring-orange-500' },
    { value: 'part', label: 'Part received', count: filtered.filter((o) => o.status === 'part').length, icon: Truck, tone: 'bg-teal-100 text-teal-900 dark:bg-teal-950 dark:text-teal-100', ring: 'ring-teal-500' },
  ]
  const openValue = filtered.filter((o) => inTile(o, 'open') && o.value).reduce((n, o) => n + Number(o.value) - Number(o.value_received ?? 0), 0)

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <header className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="inline-flex size-10 items-center justify-center rounded-xl bg-yellow-100 text-yellow-800 dark:bg-yellow-950 dark:text-yellow-200"><ShoppingCart className="size-5" /></span>
          <div>
            <div className="text-xs text-muted-foreground">Procurement</div>
            <h1 className="text-2xl leading-tight font-semibold tracking-tight">Purchase orders</h1>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {openValue > 0 && <span className="hidden text-sm text-muted-foreground sm:inline">Still to come: <strong className="text-foreground tabular-nums">{rupees(openValue)}</strong></span>}
          <Button variant="outline" className="gap-2" disabled={!list.length} onClick={() => exportOrders(list)} title="The orders shown, as a CSV file (opens in Excel)"><Download className="size-4" /> <span className="hidden sm:inline">Export</span></Button>
          {office && !readOnly && <Button className="hidden gap-2 font-semibold md:inline-flex" onClick={() => setCreating(true)}><Plus className="size-4" strokeWidth={2.6} /> New order</Button>}
        </div>
      </header>

      <div className="grid grid-cols-4 gap-2 sm:gap-3">
        {tiles.map((t) => {
          const on = tile === t.value
          return (
            <button key={t.value} type="button" aria-pressed={on} onClick={() => setTile(on ? '' : t.value)} className={cn('flex flex-col items-center gap-1 rounded-xl border bg-card p-2 text-center transition hover:-translate-y-px sm:flex-row sm:gap-3 sm:p-3.5 sm:text-left', on && cn('ring-2', t.ring))}>
              <span className={cn('inline-flex size-8 shrink-0 items-center justify-center rounded-lg sm:size-11 sm:rounded-xl', t.tone)}><t.icon className="size-4 sm:size-5" /></span>
              <span className="flex flex-col">
                <span className={cn('text-xl leading-none font-semibold tabular-nums sm:text-3xl', t.count ? t.num : undefined)}>{t.count}</span>
                <span className="text-[11px] leading-tight text-muted-foreground sm:text-sm sm:text-foreground/80">{t.label}</span>
              </span>
            </button>
          )
        })}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div role="tablist" aria-label="Status" className="flex max-w-full gap-0.5 overflow-x-auto rounded-xl bg-muted p-1">
          {TABS.map((t) => {
            const on = !tile && tab === t.value
            const n = filtered.filter((o) => inTab(o, t.value)).length
            return (
              <button key={t.value} role="tab" type="button" aria-selected={on} onClick={() => { setTile(''); setTab(t.value) }} className={cn('inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-3 text-sm whitespace-nowrap', on ? 'bg-background font-semibold shadow-sm' : 'text-foreground/75 hover:text-foreground')}>
                <span className={cn('size-2 rounded-full', t.dot)} />{t.label}
                <span className={cn('rounded-full px-1.5 text-[11px] font-semibold tabular-nums', on ? 'bg-foreground text-background' : 'bg-background/70')}>{n}</span>
              </button>
            )
          })}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!siteId && <FilterPill icon={MapPin} label="Site" allLabel="All sites" value={site} options={options.sites} onChange={setSite} />}
          <FilterPill icon={Store} label="Supplier" allLabel="Every supplier" value={vendor} options={options.vendors} onChange={setVendor} />
          <FilterPill icon={LayoutGrid} label="Category" allLabel="All categories" value={category} options={options.categories} onChange={setCategory} />
          <FilterPill icon={CalendarDays} label="Due" allLabel="Any date" value={due} options={options.dues} onChange={setDue} />
          <label className="flex h-9 items-center gap-2 rounded-lg border bg-background px-2.5">
            <Search className="size-4 text-muted-foreground" />
            <span className="sr-only">Search orders</span>
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="PO, their no., supplier, item" className="w-28 bg-transparent text-sm outline-none sm:w-36" />
          </label>
        </div>
      </div>

      <div className="flex flex-col items-start gap-5 lg:flex-row">
        <section aria-label="Purchase orders" className="w-full min-w-0 flex-1 overflow-hidden rounded-xl border">
          {isLoading && <div className="flex flex-col">{[0, 1, 2].map((i) => <div key={i} className="h-24 animate-pulse border-b bg-muted/40" />)}</div>}
          {isError && <p className="p-6 text-sm text-destructive">Orders did not load. Refresh to try again.</p>}
          {!isLoading && !isError && list.length === 0 && (
            <div className="flex flex-col items-center gap-2 px-4 py-12 text-center text-sm text-muted-foreground">
              <PackageOpen className="size-8 opacity-40" />
              {all.length === 0 ? 'No orders yet. Place one here, or from a request in Materials › Requests.' : 'Nothing here.'}
            </div>
          )}
          {list.map((o) => <OrderRow key={o.id} order={o} selected={current?.id === o.id} onPick={() => setSelected(o.id)} />)}
        </section>
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
        <Button className="fixed right-4 bottom-5 z-30 h-12 gap-2 rounded-full px-5 font-semibold shadow-lg md:hidden" onClick={() => setCreating(true)}><Plus className="size-5" strokeWidth={2.6} /> Order</Button>
      )}
      <NewOrderDialog open={creating} onOpenChange={setCreating} scope={scope} />
    </div>
  )
}

function OrderRow({ order: o, selected, onPick }: { order: PurchaseOrder; selected: boolean; onPick: () => void }) {
  const first = o.lines[0]
  const more = o.lines.length - 1
  const look = ORDER_LOOK[o.status as OrderStatus]
  return (
    <button type="button" onClick={onPick} aria-current={selected || undefined} className={cn('flex w-full gap-3 border-b px-3 py-3 text-left transition hover:bg-muted/40 sm:px-4', selected && 'bg-yellow-50 shadow-[inset_0_0_0_2px_theme(colors.yellow.300)] dark:bg-yellow-950/40')}>
      <VendorTile id={o.vendor_id} name={o.vendor_name} />
      <span className="flex min-w-0 flex-1 flex-col gap-1.5">
        <span className="flex items-center justify-between gap-2">
          <span className="min-w-0 truncate"><span className="font-semibold">{o.vendor_name}</span><span className="ml-2 text-xs text-muted-foreground tabular-nums">{o.ref}{o.their_ref ? ` · ${o.their_ref}` : ''}</span></span>
          {o.urgency !== 'closed' && <span className={cn('inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-semibold whitespace-nowrap', URGENCY_LOOK[o.urgency].chip)}>{dueWords(o)}</span>}
        </span>
        <span className="flex items-center gap-2 text-sm">
          {first && <CategoryTile mainCategory={first.main_category} size="sm" />}
          <span className="min-w-0 truncate">{first?.material} <span className="text-foreground/70 tabular-nums">{first && qty(first.quantity, first.unit)}</span>{more > 0 && <span className="ml-1.5 rounded-full bg-muted px-1.5 text-xs font-semibold">+{more}</span>}</span>
        </span>
        <span className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <OrderProgress order={o} className="w-28 sm:w-40" />
          <span className="tabular-nums">{Math.round(o.progress * 100)}% came</span>
          <span className="inline-flex items-center gap-1"><ProjectDot id={o.project_id} />{o.site_name}</span>
          {o.value && <span className="font-semibold text-foreground tabular-nums">{rupees(o.value)}</span>}
          <span className={cn('ml-auto inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-semibold', look.chip)}><span className={cn('size-1.5 rounded-full', look.dot)} />{look.label}</span>
        </span>
      </span>
    </button>
  )
}
