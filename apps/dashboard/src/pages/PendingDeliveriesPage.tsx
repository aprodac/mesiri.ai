import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlarmClock, CalendarClock, CalendarDays, Download, LayoutGrid, MapPin, MessageCircle, PackageCheck, Phone, Store, Truck } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { useScope } from '@/lib/ScopeContext'
import { useAuth } from '@/lib/AuthContext'
import { usePageTitle } from '@/lib/page-title'
import { useUrlState } from '@/lib/url-state'
import { useIsMobile } from '@/hooks/use-mobile'
import { exportCsv } from '@/lib/export'
import { cn } from '@/lib/utils'
import { qty, swatch } from '@/lib/requests'
import { fetchOrders, rupees, whatsappUrl, type PurchaseOrder } from '@/lib/orders'
import { chaseMessage, lateWords, pendingLines, type Bucket, type GroupBy, type PendingLine } from '@/lib/pending'

type Tile = '' | Bucket
import { CategoryTile, FilterPill, ProjectDot, type FilterOption } from '@/components/requests/parts'
import { OrderDetail, VendorTile } from '@/components/orders/order-detail'
import { ModuleTitle } from '@/components/page/page-kit'

// PRC-45: Procurement › Pending deliveries. Every order line still to come, as a board grouped by when it is due
// (Late · Today · This week · Later · No date) or by supplier, so the office chases the right shop in one message.
// Read from the same order list as Purchase orders (what came is read from deliveries); "Material came", "Move date"
// and "Close short" open that order's own sheet, so there is one receiving path.

const BUCKETS: { value: Bucket; label: string; hint: string; tone: string; dot: string }[] = [
  { value: 'late', label: 'Late', hint: 'Past the date the supplier gave', tone: 'text-destructive', dot: 'bg-destructive' },
  { value: 'today', label: 'Due today', hint: 'Should reach the site today', tone: 'text-orange-700 dark:text-orange-400', dot: 'bg-orange-500' },
  { value: 'week', label: 'This week', hint: 'In the next 7 days', tone: 'text-info', dot: 'bg-blue-500' },
  { value: 'later', label: 'Later', hint: 'More than a week away', tone: 'text-foreground/80', dot: 'bg-muted-foreground/60' },
  { value: 'none', label: 'No date', hint: 'Ask the supplier when, and put the date on the order', tone: 'text-muted-foreground', dot: 'bg-muted-foreground/30' },
]

function exportPending(items: PendingLine[]): void {
  exportCsv(`pending-deliveries-${new Date().toISOString().slice(0, 10)}.csv`,
    ['Order', 'Their number', 'Supplier', 'Supplier phone', 'Project', 'Site', 'Item', 'Ordered', 'Came', 'Still to come', 'Unit', 'Expected', 'Days late', 'Value still to come'],
    items.map((p) => [p.order.ref, p.order.their_ref ?? '', p.order.vendor_name, p.order.vendor_phone ?? '', p.order.project_name, p.order.site_name, p.line.material,
      Number(p.line.quantity), Number(p.line.received), p.pending, p.line.unit, p.order.expected_date ?? '', p.days !== null && p.days < 0 ? -p.days : '', p.value ?? '']))
}

export default function PendingDeliveriesPage() {
  usePageTitle('Pending deliveries')
  const { scope } = useScope()
  const { me } = useAuth()
  const isMobile = useIsMobile()
  const projectId = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : null
  const siteId = scope.mode === 'site' ? scope.siteId : null
  const company = me?.org_name || me?.organization_name

  const [tile, setTile] = useUrlState<Tile>('show', '')
  const [groupBy, setGroupBy] = useUrlState<GroupBy>('by', 'date')
  const [site, setSite] = useUrlState<string>('at', '')
  const [vendor, setVendor] = useUrlState<string>('vendor', '')
  const [category, setCategory] = useUrlState<string>('category', '')
  const [selected, setSelected] = useUrlState<string>('id', '')

  const { data, isLoading, isError } = useQuery({
    queryKey: ['procurement', 'orders', projectId, siteId],
    queryFn: () => fetchOrders({ project_id: projectId, site_id: siteId }),
    refetchInterval: 60_000,
  })
  const all = React.useMemo(() => pendingLines(data?.items ?? []), [data])

  const pass = React.useCallback((p: PendingLine, skip?: string) => {
    if (skip !== 'site' && site && p.order.site_id !== site) return false
    if (skip !== 'vendor' && vendor && p.order.vendor_id !== vendor) return false
    if (skip !== 'category' && category && (p.line.main_category ?? '—') !== category) return false
    return true
  }, [site, vendor, category])
  const filtered = React.useMemo(() => all.filter((p) => pass(p)), [all, pass])
  const shown = React.useMemo(() => (tile ? filtered.filter((p) => p.bucket === tile) : filtered), [filtered, tile])

  const options = React.useMemo(() => {
    const count = (skip: string, test: (p: PendingLine) => boolean) => all.filter((p) => pass(p, skip) && test(p)).length
    const uniq = <T,>(xs: T[], key: (t: T) => string) => [...new Map(xs.map((x) => [key(x), x])).values()]
    const sites: FilterOption[] = uniq(all, (p) => p.order.site_id).map((p) => ({ value: p.order.site_id, label: `${p.order.project_name} › ${p.order.site_name}`, swatch: swatch(p.order.project_id), count: count('site', (x) => x.order.site_id === p.order.site_id) }))
    const vendors: FilterOption[] = uniq(all, (p) => p.order.vendor_id).map((p) => ({ value: p.order.vendor_id, label: p.order.vendor_name, swatch: swatch(p.order.vendor_id), count: count('vendor', (x) => x.order.vendor_id === p.order.vendor_id) }))
    const mains = [...new Set(all.map((p) => p.line.main_category ?? '—'))].sort()
    const categories: FilterOption[] = mains.map((m) => ({ value: m, label: m === '—' ? 'No category' : m, category: m === '—' ? null : m, count: count('category', (x) => (x.line.main_category ?? '—') === m) }))
    return { sites, vendors, categories }
  }, [all, pass])

  const value = filtered.reduce((sum, p) => sum + (p.value ?? 0), 0)
  const lateSuppliers = new Set(filtered.filter((p) => p.bucket === 'late').map((p) => p.order.vendor_id)).size
  const tiles: { value: Bucket; label: string; icon: LucideIcon; tone: string; ring: string; num?: string; sub?: string }[] = [
    { value: 'late', label: 'Late', icon: AlarmClock, tone: 'bg-destructive text-white', ring: 'ring-destructive', num: 'text-destructive', sub: lateSuppliers ? `${lateSuppliers} supplier${lateSuppliers === 1 ? '' : 's'} to chase` : undefined },
    { value: 'today', label: 'Due today', icon: Truck, tone: 'bg-orange-200 text-orange-950 dark:bg-orange-900 dark:text-orange-100', ring: 'ring-orange-500' },
    { value: 'week', label: 'This week', icon: CalendarDays, tone: 'bg-info-soft text-info', ring: 'ring-blue-500' },
    { value: 'none', label: 'No date', icon: CalendarClock, tone: 'bg-muted text-foreground/70', ring: 'ring-foreground/40' },
  ]

  const groups = React.useMemo(() => {
    if (groupBy === 'supplier') {
      const by = new Map<string, PendingLine[]>()
      for (const p of shown) by.set(p.order.vendor_id, [...(by.get(p.order.vendor_id) ?? []), p])
      return [...by.values()]
        .sort((a, b) => (a[0].days ?? 9999) - (b[0].days ?? 9999))
        .map((ps) => ({ key: ps[0].order.vendor_id, supplier: ps[0].order, title: ps[0].order.vendor_name, hint: '', tone: '', dot: '', items: ps }))
    }
    return BUCKETS.map((b) => ({ key: b.value, supplier: null as PurchaseOrder | null, title: b.label, hint: b.hint, tone: b.tone, dot: b.dot, items: shown.filter((p) => p.bucket === b.value) }))
      .filter((g) => g.items.length)
  }, [shown, groupBy])

  const current = (data?.items ?? []).find((o) => o.id === selected)

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <ModuleTitle icon={Truck} title="Pending deliveries" />
        <div className="flex items-center gap-3">
          {value > 0 && <span className="hidden text-sm text-muted-foreground sm:inline">Still to come: <strong className="text-foreground tabular-nums">{rupees(value)}</strong></span>}
          <Button variant="outline" className="gap-2" disabled={!shown.length} onClick={() => exportPending(shown)} title="The lines shown, as a CSV file (opens in Excel)"><Download className="size-4" /> <span className="hidden sm:inline">Export</span></Button>
        </div>
      </header>

      <div className="grid grid-cols-4 gap-2 sm:gap-3">
        {tiles.map((t) => {
          const on = tile === t.value
          const count = filtered.filter((p) => p.bucket === t.value).length
          return (
            <button key={t.value} type="button" aria-pressed={on} onClick={() => setTile(on ? '' : t.value)} className={cn('flex flex-col items-center gap-1 rounded-xl border bg-card p-2 text-center transition hover:-translate-y-px sm:flex-row sm:gap-3 sm:p-3.5 sm:text-left', on && cn('ring-2', t.ring))}>
              <span className={cn('inline-flex size-8 shrink-0 items-center justify-center rounded-lg sm:size-11 sm:rounded-xl', t.tone)}><t.icon className="size-4 sm:size-5" /></span>
              <span className="flex min-w-0 flex-col">
                <span className={cn('text-xl leading-none font-semibold tabular-nums sm:text-3xl', count ? t.num : undefined)}>{count}</span>
                <span className="text-[11px] leading-tight text-muted-foreground sm:text-sm sm:text-foreground/80">{t.label}</span>
                {t.sub && <span className="hidden truncate text-xs text-muted-foreground sm:block">{t.sub}</span>}
              </span>
            </button>
          )
        })}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div role="tablist" aria-label="Group by" className="flex gap-0.5 rounded-xl bg-muted p-1">
          {([['date', 'By date'], ['supplier', 'By supplier']] as [GroupBy, string][]).map(([v, label]) => (
            <button key={v} role="tab" type="button" aria-selected={groupBy === v} onClick={() => setGroupBy(v)} className={cn('h-8 rounded-lg px-3 text-sm whitespace-nowrap', groupBy === v ? 'bg-background font-semibold shadow-sm' : 'text-foreground/75 hover:text-foreground')}>{label}</button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!siteId && <FilterPill icon={MapPin} label="Site" allLabel="All sites" value={site} options={options.sites} onChange={setSite} />}
          <FilterPill icon={Store} label="Supplier" allLabel="Every supplier" value={vendor} options={options.vendors} onChange={setVendor} />
          <FilterPill icon={LayoutGrid} label="Category" allLabel="All categories" value={category} options={options.categories} onChange={setCategory} />
        </div>
      </div>

      {isLoading && <div className="flex flex-col gap-2">{[0, 1, 2].map((i) => <div key={i} className="h-20 animate-pulse rounded-xl bg-muted/40" />)}</div>}
      {isError && <p className="rounded-xl border p-6 text-sm text-destructive">Orders did not load. Refresh to try again.</p>}
      {!isLoading && !isError && shown.length === 0 && (
        <div className="flex flex-col items-center gap-2 rounded-xl border px-4 py-12 text-center text-sm text-muted-foreground">
          <PackageCheck className="size-8 opacity-40" />
          {all.length === 0 ? 'Nothing is waiting: every order has come in full. New orders show here until their material reaches the site.' : 'Nothing here with these filters.'}
        </div>
      )}

      <div className="flex flex-col gap-5">
        {groups.map((g) => (
          <section key={g.key} aria-label={g.title} className="flex flex-col gap-2">
            {g.supplier ? (
              <SupplierHeader order={g.supplier} items={g.items} company={company} />
            ) : (
              <div className="flex items-baseline gap-2 px-1">
                <span className={cn('size-2 shrink-0 translate-y-[-1px] rounded-full', g.dot)} />
                <h2 className={cn('text-sm font-semibold', g.tone)}>{g.title}</h2>
                <span className="rounded-full bg-muted px-1.5 text-[11px] font-semibold tabular-nums">{g.items.length}</span>
                <span className="hidden text-xs text-muted-foreground sm:inline">{g.hint}</span>
              </div>
            )}
            <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
              {g.items.map((p) => <PendingCard key={p.key} p={p} company={company} showSupplier={!g.supplier} onOpen={() => setSelected(p.order.id)} />)}
            </div>
          </section>
        ))}
      </div>

      <Sheet open={!!current} onOpenChange={(o) => !o && setSelected('')}>
        <SheetContent side={isMobile ? 'bottom' : 'right'} className={cn('gap-0 overflow-y-auto p-0', isMobile ? 'max-h-[92vh] rounded-t-2xl' : 'w-full sm:max-w-[460px]')}>
          <SheetTitle className="sr-only">{current ? `${current.ref} order` : 'Order'}</SheetTitle>
          {current && <OrderDetail order={current} inSheet />}
        </SheetContent>
      </Sheet>
    </div>
  )
}

function SupplierHeader({ order: o, items, company }: { order: PurchaseOrder; items: PendingLine[]; company?: string | null }) {
  const late = items.filter((p) => p.bucket === 'late').length
  const value = items.reduce((s, p) => s + (p.value ?? 0), 0)
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border bg-card px-3 py-2.5">
      <VendorTile id={o.vendor_id} name={o.vendor_name} />
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate font-semibold">{o.vendor_name}</span>
        <span className="text-xs text-muted-foreground tabular-nums">
          {items.length} item{items.length === 1 ? '' : 's'} to come{late ? <span className="font-semibold text-destructive"> · {late} late</span> : ''}{value ? ` · ${rupees(value)}` : ''}
        </span>
      </span>
      <ChaseButtons phone={o.vendor_phone} message={chaseMessage(items, company)} label="Chase all" />
    </div>
  )
}

function ChaseButtons({ phone, message, label }: { phone: string | null; message: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      {phone && (
        <Button asChild size="icon" variant="outline" className="size-8" title={`Call ${phone}`}>
          <a href={`tel:${phone}`} aria-label={`Call ${phone}`}><Phone className="size-3.5" /></a>
        </Button>
      )}
      <Button asChild size="sm" variant="outline" className="h-8 gap-1.5" title={phone ? 'Opens WhatsApp with the message written; you send it' : 'No phone on this supplier: WhatsApp opens to pick the chat'}>
        <a href={whatsappUrl(phone, message)} target="_blank" rel="noreferrer"><MessageCircle className="size-3.5" /> {label}</a>
      </Button>
    </span>
  )
}

function PendingCard({ p, company, showSupplier, onOpen }: { p: PendingLine; company?: string | null; showSupplier: boolean; onOpen: () => void }) {
  const ordered = Number(p.line.quantity)
  const came = Math.max(0, ordered - p.pending)
  const pct = ordered > 0 ? Math.min(100, (came / ordered) * 100) : 0
  const late = p.bucket === 'late'
  return (
    <article className={cn('flex flex-col gap-2 rounded-xl border bg-card p-3', late && 'border-destructive/40 bg-destructive/[0.03]')}>
      <button type="button" onClick={onOpen} className="flex items-start gap-2.5 text-left" aria-label={`Open ${p.order.ref}`}>
        <CategoryTile mainCategory={p.line.main_category} size="sm" />
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="flex items-baseline justify-between gap-2">
            <span className="min-w-0 truncate font-semibold">{p.line.material}</span>
            <span className={cn('shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap', late ? 'bg-destructive text-white' : p.bucket === 'today' ? 'bg-orange-200 text-orange-950 dark:bg-orange-900 dark:text-orange-100' : 'bg-muted text-foreground/80')}>{lateWords(p)}</span>
          </span>
          <span className="text-sm tabular-nums"><strong>{qty(String(p.pending), p.line.unit)}</strong> <span className="text-muted-foreground">still to come{came > 0 ? ` of ${qty(p.line.quantity, p.line.unit)}` : ''}</span></span>
        </span>
      </button>
      {came > 0 && (
        <div className="h-1.5 overflow-hidden rounded-full bg-muted" aria-label={`${Math.round(pct)}% came`}><div className="h-full rounded-full bg-teal-500" style={{ width: `${pct}%` }} /></div>
      )}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        {showSupplier && <span className="font-medium text-foreground/90">{p.order.vendor_name}</span>}
        <span className="tabular-nums">{p.order.ref}{p.order.their_ref ? ` · ${p.order.their_ref}` : ''}</span>
        <span className="inline-flex items-center gap-1"><ProjectDot id={p.order.project_id} />{p.order.site_name}</span>
        {p.value !== null && <span className="font-semibold text-foreground tabular-nums">{rupees(p.value)}</span>}
        {p.line.request && <span className="rounded-md bg-muted px-1.5 py-0.5">for {p.line.request.ref}</span>}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-2">
        {p.order.may_receive ? (
          <Button size="sm" className="h-8 gap-1.5 font-semibold" onClick={onOpen}><PackageCheck className="size-3.5" /> Material came</Button>
        ) : (
          <Button size="sm" variant="ghost" className="h-8" onClick={onOpen}>Open order</Button>
        )}
        {showSupplier && <ChaseButtons phone={p.order.vendor_phone} message={chaseMessage([p], company)} label="Chase" />}
      </div>
    </article>
  )
}
