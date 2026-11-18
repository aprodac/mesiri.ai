import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlarmClock, CalendarClock, CalendarDays, LayoutGrid, MapPin, MessageCircle, PackageCheck, Phone, Store, Truck } from 'lucide-react'
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
import { chaseMessage, lateWords, pendingLines, tellSiteMessage, weekDays, type Bucket, type GroupBy, type PendingLine } from '@/lib/pending'
import { appNow } from '@/lib/clock'

type Tile = '' | Bucket
import { CategoryTile, FilterPill, ProjectDot, type FilterOption } from '@/components/requests/parts'
import { OrderDetail, VendorTile } from '@/components/orders/order-detail'
import { KpiStrip, ModuleTitle, Pill, Segmented, type KpiItem } from '@/components/page/page-kit'
import { useSupplierScores, type SupplierPerformance } from '@/lib/supplier-performance'
import { compact } from '@/lib/expenses'
import { TONE, type Tone } from '@/lib/list-kit'
import { ActionIcon } from '@/components/page/action-button'
import { Pager } from '@/components/page/pager'
import { usePagedUrl } from '@/lib/paging'

// PRC-45: Procurement › Pending deliveries. Every order line still to come, as a board grouped by when it is due
// (Late · Today · This week · Later · No date) or by supplier, so the office chases the right shop in one message.
// Read from the same order list as Purchase orders (what came is read from deliveries); "Material came", "Move date"
// and "Close short" open that order's own sheet, so there is one receiving path.
// UX-67 (18 Nov): figures as a KpiStrip; a Week board (late, then the next seven days, a column each) with "Tell site"
// per day (one WhatsApp message of that day's deliveries); due chips by tone; a supplier often late carries its on-time
// share (the supplier score, PRC-50).

const BUCKET_TONE: Record<Bucket, Tone> = { late: 'bad', today: 'attention', week: 'info', later: 'muted', none: 'muted' }

const BUCKETS: { value: Bucket; label: string; hint: string; tone: string; dot: string }[] = [
  { value: 'late', label: 'Late', hint: 'Past the date the supplier gave', tone: 'text-destructive', dot: 'bg-destructive' },
  { value: 'today', label: 'Due today', hint: 'Should reach the site today', tone: 'text-orange-700 dark:text-orange-400', dot: 'bg-orange-500' },
  { value: 'week', label: 'This week', hint: 'In the next 7 days', tone: 'text-info', dot: 'bg-blue-500' },
  { value: 'later', label: 'Later', hint: 'More than a week away', tone: 'text-foreground/80', dot: 'bg-muted-foreground/60' },
  { value: 'none', label: 'No date', hint: 'Ask the supplier when, and put the date on the order', tone: 'text-muted-foreground', dot: 'bg-muted-foreground/30' },
]

function exportPending(items: PendingLine[]): void {
  exportCsv(`pending-deliveries-${appNow().toISOString().slice(0, 10)}.csv`,
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
  const toggle = (b: Bucket) => setTile(tile === b ? '' : b)
  const countOf = (b: Bucket) => filtered.filter((p) => p.bucket === b).length
  const tiles = ([
    { key: 'late', label: 'Late', value: countOf('late') || '—', icon: AlarmClock, tone: countOf('late') ? 'bad' : 'default', hint: lateSuppliers ? `${lateSuppliers} to chase` : undefined, pressed: tile === 'late', onClick: () => toggle('late') },
    { key: 'today', label: 'Due today', value: countOf('today') || '—', icon: Truck, tone: countOf('today') ? 'attention' : 'default', pressed: tile === 'today', onClick: () => toggle('today') },
    { key: 'week', label: 'This week', value: countOf('week') || '—', icon: CalendarDays, tone: countOf('week') ? 'info' : 'default', pressed: tile === 'week', onClick: () => toggle('week') },
    { key: 'none', label: 'No date', value: countOf('none') || '—', icon: CalendarClock, tone: countOf('none') ? 'attention' : 'default', pressed: tile === 'none', onClick: () => toggle('none') },
    ...(value > 0 ? [{ key: 'value', label: 'Still to come', value: compact(value), kind: 'money' }] : []),
  ] as KpiItem[]).map((k) => ({ ...k, loading: isLoading }))
  const scores = useSupplierScores()

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
  // UX-37: numbered pages, kept in the address.
  const pagedGroups = usePagedUrl<(typeof groups)[number]>(groups)

  const current = (data?.items ?? []).find((o) => o.id === selected)

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <ModuleTitle icon={Truck} title="Pending deliveries" />
        <div className="flex items-center gap-3">
          <Button variant="outline" className="gap-2" disabled={!shown.length} onClick={() => exportPending(shown)} title="The lines shown, as a CSV file (opens in Excel)"><ActionIcon kind="export-excel" className="size-4" /> <span className="hidden sm:inline">Export</span></Button>
        </div>
      </header>

      <KpiStrip guide="pending.tiles" stats={tiles} />

      <div className="flex flex-wrap items-center justify-between gap-2">
        <Segmented label="Group by" guide="pending.group" value={groupBy} onChange={setGroupBy} options={[{ value: 'date', label: 'By date' }, { value: 'week', label: 'Week' }, { value: 'supplier', label: 'By supplier' }]} />
        <div className="flex flex-wrap items-center gap-2">
          {!siteId && <FilterPill icon={MapPin} label="Site" allLabel="All sites" value={site} options={options.sites} onChange={setSite} />}
          <FilterPill icon={Store} label="Supplier" allLabel="Every supplier" value={vendor} options={options.vendors} onChange={setVendor} />
          <FilterPill icon={LayoutGrid} label="Category" allLabel="All categories" value={category} options={options.categories} onChange={setCategory} />
        </div>
      </div>

      {isLoading && <div className="flex flex-col gap-2">{[0, 1, 2].map((i) => <div key={i} className="h-20 animate-pulse rounded-xl bg-muted/40" />)}</div>}
      {isError && <p className="rounded-xl border p-6 text-sm text-destructive">Orders did not load. Refresh to try again.</p>}
      {!isLoading && !isError && shown.length === 0 && (
        <div className="flex flex-col items-center gap-2 rounded-xl border px-4 py-12 text-center text-sm text-muted-foreground" data-guide="pending.empty">
          <PackageCheck className="size-8 opacity-40" />
          {all.length === 0 ? 'Nothing waiting: every order came in full' : 'Nothing here with these filters.'}
        </div>
      )}

      {groupBy === 'week' && shown.length > 0 && <WeekBoard lines={shown} scores={scores} onOpen={(id) => setSelected(id)} />}
      {groupBy !== 'week' && <>
      <div className="flex flex-col gap-5" data-guide="pending.list">
        {pagedGroups.shown.map((g) => (
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
              {g.items.map((p) => <PendingCard key={p.key} p={p} company={company} showSupplier={!g.supplier} score={scores.get(p.order.vendor_id)} onOpen={() => setSelected(p.order.id)} />)}
            </div>
          </section>
        ))}
      </div>
        <Pager {...pagedGroups.pager} noun="groups" className="mt-2" />
      </>}

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
    <span className="flex items-center gap-1.5" data-guide="pending.chase">
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

function PendingCard({ p, company, showSupplier, score, onOpen }: { p: PendingLine; company?: string | null; showSupplier: boolean; score?: SupplierPerformance; onOpen: () => void }) {
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
            <Pill tone={BUCKET_TONE[p.bucket]} size="xs" icon={late ? AlarmClock : CalendarDays}>{lateWords(p)}</Pill>
          </span>
          <span className="text-sm tabular-nums"><strong>{qty(String(p.pending), p.line.unit)}</strong> <span className="text-muted-foreground">still to come{came > 0 ? ` of ${qty(p.line.quantity, p.line.unit)}` : ''}</span></span>
        </span>
      </button>
      {came > 0 && (
        <div className="h-1.5 overflow-hidden rounded-full bg-muted" aria-label={`${Math.round(pct)}% came`}><div className="h-full rounded-full bg-teal-500" style={{ width: `${pct}%` }} /></div>
      )}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        {showSupplier && <span className="font-medium text-foreground/90">{p.order.vendor_name}</span>}
        <OnTimeChip p={score} />
        <span className="tabular-nums">{p.order.ref}{p.order.their_ref ? ` · ${p.order.their_ref}` : ''}</span>
        <span className="inline-flex items-center gap-1"><ProjectDot id={p.order.project_id} />{p.order.site_name}</span>
        {p.value !== null && <span className="font-semibold text-foreground tabular-nums">{rupees(p.value)}</span>}
        {p.line.request && <span className="rounded-md bg-muted px-1.5 py-0.5">for {p.line.request.ref}</span>}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-2">
        {p.order.may_receive ? (
          <Button size="sm" className="h-8 gap-1.5 font-semibold" onClick={onOpen} data-guide="pending.came"><PackageCheck className="size-3.5" /> Material came</Button>
        ) : (
          <Button size="sm" variant="ghost" className="h-8" onClick={onOpen}>Open order</Button>
        )}
        {showSupplier && <ChaseButtons phone={p.order.vendor_phone} message={chaseMessage([p], company)} label="Chase" />}
      </div>
    </article>
  )
}

/** UX-67: a supplier that is often late, by its on-time share over the last 12 months (the supplier score). */
function OnTimeChip({ p }: { p?: SupplierPerformance }) {
  const pct = p?.measures.on_time.pct
  if (!p || pct === null || pct === undefined || p.measures.on_time.of < 2 || Number(pct) >= 80) return null
  return <Pill tone={Number(pct) < 50 ? 'bad' : 'attention'} size="xs" icon={AlarmClock} title={`On time in ${Math.round(Number(pct))}% of ${p.measures.on_time.of} deliveries`}>{Math.round(Number(pct))}% on time</Pill>
}

/** UX-67: what comes when: late first, then the next seven days, a column each, with "Tell site" for the day. */
function WeekBoard({ lines, scores, onOpen }: { lines: PendingLine[]; scores: Map<string, SupplierPerformance>; onOpen: (orderId: string) => void }) {
  const days = weekDays()
  const late = lines.filter((p) => p.bucket === 'late')
  const cols = [
    ...(late.length ? [{ key: 'late', title: 'Late', sub: '', tone: 'bad' as Tone, items: late, words: 'late' }] : []),
    ...days.map((d, i) => {
      const date = new Date(`${d}T00:00:00`)
      return {
        key: d,
        title: i === 0 ? 'Today' : i === 1 ? 'Tomorrow' : date.toLocaleDateString('en-IN', { weekday: 'short' }),
        sub: date.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }),
        tone: (i === 0 ? 'attention' : 'info') as Tone,
        items: lines.filter((p) => p.order.expected_date === d && p.bucket !== 'late'),
        words: i === 0 ? 'today' : i === 1 ? 'tomorrow' : `on ${date.toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'short' })}`,
      }
    }),
  ]
  const later = lines.filter((p) => p.bucket === 'later' || p.bucket === 'none').length
  return (
    <div className="flex min-w-0 flex-col gap-2 [contain:inline-size]" data-guide="pending.list">
      <div className="grid auto-cols-[minmax(170px,1fr)] grid-flow-col gap-2 overflow-x-auto pb-1" data-guide="pending.week">
        {cols.map((c) => (
          <section key={c.key} className={cn('flex min-h-40 flex-col gap-2 rounded-xl border bg-card p-2', c.key === 'late' && 'border-destructive/40')}>
            <header className="flex items-center gap-2 px-1">
              <span className={cn('size-2 rounded-full', c.items.length ? TONE[c.tone].dot : 'bg-muted-foreground/25')} />
              <span className={cn('text-sm font-semibold', c.items.length ? TONE[c.tone].text : 'text-muted-foreground')}>{c.title}</span>
              <span className="text-xs text-muted-foreground">{c.sub}</span>
              {c.items.length > 0 && (
                <a href={whatsappUrl(null, tellSiteMessage(c.items, c.words))} target="_blank" rel="noreferrer" className="ml-auto inline-flex size-7 items-center justify-center rounded-md text-success hover:bg-muted" title="Tell site on WhatsApp" aria-label={`Tell site what comes ${c.words}`}>
                  <MessageCircle className="size-4" />
                </a>
              )}
            </header>
            {c.items.map((p) => (
              <button key={p.key} type="button" onClick={() => onOpen(p.order.id)} className="flex flex-col gap-1 rounded-lg border bg-background p-2 text-left text-xs hover:border-foreground/30">
                <span className="flex items-center gap-1.5"><CategoryTile mainCategory={p.line.main_category} size="sm" /><span className="min-w-0 truncate text-sm font-semibold">{p.line.material}</span></span>
                <span className="font-semibold tabular-nums">{qty(String(p.pending), p.line.unit)}</span>
                <span className="flex min-w-0 items-center gap-1 text-muted-foreground"><ProjectDot id={p.order.project_id} /><span className="truncate">{p.order.site_name}</span></span>
                <span className="flex min-w-0 items-center gap-1 text-muted-foreground"><Store className="size-3 shrink-0" /><span className="truncate">{p.order.vendor_name}</span><OnTimeChip p={scores.get(p.order.vendor_id)} /></span>
              </button>
            ))}
            {!c.items.length && <span className="m-auto text-xs text-muted-foreground/60">—</span>}
          </section>
        ))}
      </div>
      {later > 0 && <span className="text-xs text-muted-foreground">+{later} later or with no date</span>}
    </div>
  )
}
