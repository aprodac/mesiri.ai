import * as React from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { AlarmClock, CalendarDays, CircleCheck, ClipboardList, Copy, Gauge, Inbox, LayoutGrid, ListChecks, MapPin, Plus, Search, ShoppingCart, Timer, User } from 'lucide-react'
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
import {
  URGENCY_LOOK,
  ago,
  fetchRequests,
  hoursWords,
  officeSpeed,
  qty,
  swatch,
  waitTone,
  waitedHours,
  type MaterialRequest,
  type Urgency,
} from '@/lib/requests'
import { Avatar, CategoryTile, CoverBar, FilterPill, ProjectDot, StatusChip, UrgencyChip, WhatsAppMark, type FilterOption } from '@/components/requests/parts'
import { RequestDetail } from '@/components/requests/request-detail'
import { NewRequestDialog } from '@/components/requests/new-request-dialog'
import { BulkBar, EmptyState, KpiStrip, ModuleTitle, Pill, SayOnWhatsApp, StateBar, type KpiItem, type StateItem } from '@/components/page/page-kit'
import { NewOrderDialog, type OrderPrefill } from '@/components/orders/new-order-dialog'
import { fetchMaterialPlan, type MaterialPlanRow } from '@/lib/material-plan'
import type { Tone } from '@/lib/list-kit'
import { ActionIcon } from '@/components/page/action-button'
import { appNow } from '@/lib/clock'
import { Pager } from '@/components/page/pager'
import { usePagedUrl } from '@/lib/paging'

// PRC-22 (design approved by Ilan, 7 Nov 2026): Materials > Requests. What the sites need and what is happening
// to it. UX-65 (18 Nov): the figures as a KpiStrip with the office's speed (asked to ordered); the status tabs and the
// filters in one StateBar box; it opens on a tab with work ("All clear" when nothing waits); each waiting row shows how
// long it has waited (amber after a day, red after two) and whether it is in the project's material plan; the office
// ticks several waiting requests at one site and orders them together in one purchase order.

type Tab = 'waiting' | 'ordered' | 'done' | 'rejected' | 'all'
type Tile = '' | 'waiting' | 'late' | 'soon' | 'dup'

// UX-65: the status tabs as the list kit's StateBar: a tone per status (the same colours as the chips).
const TABS: { value: Exclude<Tab, 'all'>; label: string; icon: typeof Inbox; tone: Tone }[] = [
  { value: 'waiting', label: 'Waiting', icon: Inbox, tone: 'attention' },
  { value: 'ordered', label: 'Ordered', icon: ShoppingCart, tone: 'info' },
  { value: 'done', label: 'Received', icon: CircleCheck, tone: 'good' },
  { value: 'rejected', label: 'Not ordered', icon: Copy, tone: 'bad' },
]

function inTab(r: MaterialRequest, tab: Tab): boolean {
  if (tab === 'waiting') return r.status === 'waiting'
  if (tab === 'ordered') return r.status === 'ordered' || r.status === 'sent'
  if (tab === 'done') return r.status === 'done'
  if (tab === 'rejected') return r.status === 'rejected'
  return true
}

function inTile(r: MaterialRequest, tile: Tile): boolean {
  if (tile === 'waiting') return r.status === 'waiting'
  if (tile === 'late') return r.urgency === 'late'
  if (tile === 'soon') return r.urgency === 'soon'
  if (tile === 'dup') return r.duplicates.length > 0 && r.status === 'waiting'
  return true
}

const URGENCY_ORDER: Record<Urgency, number> = { late: 0, soon: 1, later: 2, closed: 3 }

/** PRC-31: the requests shown (tab and filters applied), one row per item, for Excel. */
function exportRequests(items: MaterialRequest[]): void {
  const rows = items.flatMap((r) => r.lines.map((l) => [
    r.ref, r.status, r.project_name, r.site_name, r.requested_by_name ?? '', r.created_at.slice(0, 10), r.needed_by ?? '',
    l.material, l.category ?? '', Number(l.quantity), l.unit, Number(l.at_site), Number(l.on_order), Number(l.to_buy),
    r.orders.filter((o) => o.status !== 'cancelled').map((o) => o.ref).join(' '), r.purpose ?? '', r.decision_note ?? '',
  ]))
  exportCsv(`material-requests-${appNow().toISOString().slice(0, 10)}.csv`,
    ['Request', 'Status', 'Project', 'Site', 'Asked by', 'Asked on', 'Needed by', 'Item', 'Category', 'Quantity', 'Unit',
      'At site', 'On order', 'To buy', 'Orders', 'Purpose', 'Office note'], rows)
}

export default function RequestsPage() {
  usePageTitle('Requests')
  const { scope } = useScope()
  const { me } = useAuth()
  const readOnly = useReadOnly()
  const isMobile = useIsMobile()
  const projectId = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : null
  const siteId = scope.mode === 'site' ? scope.siteId : null

  const [tabAsked, setTab] = useUrlState<Tab | ''>('tab', '')
  const [tile, setTile] = useUrlState<Tile>('show', '')
  const [site, setSite] = useUrlState<string>('at', '')  // PRC-27: not 'site' (the scope's own key, as WEB-34)
  const [by, setBy] = useUrlState<string>('by', '')
  const [category, setCategory] = useUrlState<string>('category', '')
  const [due, setDue] = useUrlState<string>('due', '')
  const [search, setSearch] = React.useState('')
  const [selected, setSelected] = useUrlState<string>('id', '')
  const [creating, setCreating] = React.useState(false)
  // UX-65: ticked waiting requests (one site), ordered together.
  const [picked, setPicked] = React.useState<string[]>([])
  const [ordering, setOrdering] = React.useState<OrderPrefill | null>(null)
  const searchRef = React.useRef<HTMLInputElement>(null)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['procurement', 'requests', projectId, siteId],
    queryFn: () => fetchRequests({ project_id: projectId, site_id: siteId }),
    refetchInterval: 60_000,
  })
  const all = React.useMemo(() => data?.items ?? [], [data])

  // Keyboard: N for a new request, / to search (not while typing).
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)
      if (typing || e.metaKey || e.ctrlKey || e.altKey) return
      if (e.key === 'n' && !readOnly) { e.preventDefault(); setCreating(true) }
      if (e.key === '/') { e.preventDefault(); searchRef.current?.focus() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [readOnly])

  const passFilters = React.useCallback((r: MaterialRequest, skip?: string) => {
    if (skip !== 'site' && site && r.site_id !== site) return false
    if (skip !== 'by' && by && r.requested_by !== by) return false
    if (skip !== 'category' && category && !r.lines.some((l) => (l.main_category ?? '—') === category)) return false
    if (skip !== 'due' && due && r.urgency !== due) return false
    if (search) {
      const q = search.toLowerCase()
      if (!r.ref.toLowerCase().includes(q) && !r.lines.some((l) => l.material.toLowerCase().includes(q))) return false
    }
    return true
  }, [site, by, category, due, search])

  const filtered = React.useMemo(() => all.filter((r) => passFilters(r)), [all, passFilters])
  // UX-65: open on a tab with work: Waiting when something waits, else Ordered (never an empty first screen).
  const waitingCount = filtered.filter((r) => r.status === 'waiting').length
  const tab: Tab = tabAsked || (isLoading || waitingCount > 0 || !filtered.some((r) => inTab(r, 'ordered')) ? 'waiting' : 'ordered')
  const list = React.useMemo(
    () =>
      filtered
        .filter((r) => (tile ? inTile(r, tile) : inTab(r, tab)))
        .sort((a, b) => URGENCY_ORDER[a.urgency] - URGENCY_ORDER[b.urgency] || (a.needed_by ?? '9999').localeCompare(b.needed_by ?? '9999') || b.number - a.number),
    [filtered, tab, tile],
  )
  // UX-37: numbered pages, kept in the address.
  const pagedList = usePagedUrl(list)

  // The one being worked on stays open when acting on it moves it to another tab (ordered, received); a tab change or
  // a pick of another row lets it go.
  const [kept, setKept] = React.useState('')
  React.useEffect(() => setKept(''), [tab])
  const current = all.find((r) => r.id === selected) ?? (isMobile ? undefined : all.find((r) => r.id === kept) ?? list[0])
  React.useEffect(() => {
    if (!selected && current && current.id !== kept) setKept(current.id)
  }, [selected, current, kept])

  const options = React.useMemo(() => {
    const count = (skip: string, test: (r: MaterialRequest) => boolean) => all.filter((r) => passFilters(r, skip) && test(r)).length
    const unique = <T,>(items: T[], key: (t: T) => string) => [...new Map(items.map((t) => [key(t), t])).values()]
    const sites: FilterOption[] = unique(all, (r) => r.site_id).map((r) => ({
      value: r.site_id, label: `${r.project_name} › ${r.site_name}`, swatch: swatch(r.project_id), count: count('site', (x) => x.site_id === r.site_id),
    }))
    const people: FilterOption[] = unique(all.filter((r) => r.requested_by), (r) => r.requested_by!).map((r) => ({
      value: r.requested_by!, label: r.requested_by_name ?? 'Someone', avatar: { id: r.requested_by!, name: r.requested_by_name ?? '?' }, count: count('by', (x) => x.requested_by === r.requested_by),
    }))
    const mains = [...new Set(all.flatMap((r) => r.lines.map((l) => l.main_category ?? '—')))].sort()
    const categories: FilterOption[] = mains.map((m) => ({
      value: m, label: m === '—' ? 'No category' : m, category: m === '—' ? null : m, count: count('category', (x) => x.lines.some((l) => (l.main_category ?? '—') === m)),
    }))
    const dues: FilterOption[] = (['late', 'soon', 'later', 'closed'] as Urgency[]).map((u) => ({
      value: u, label: { late: 'Late', soon: 'Due in 2 days', later: 'Later', closed: 'Closed' }[u], dot: URGENCY_LOOK[u].dot, count: count('due', (x) => x.urgency === u),
    }))
    return { sites, people, categories, dues }
  }, [all, passFilters])

  const counts = {
    waiting: filtered.filter((r) => r.status === 'waiting').length,
    late: filtered.filter((r) => r.urgency === 'late').length,
    soon: filtered.filter((r) => r.urgency === 'soon').length,
    dup: filtered.filter((r) => r.duplicates.length > 0 && r.status === 'waiting').length,
  }
  const speed = officeSpeed(all)
  const longWait = filtered.filter((r) => waitedHours(r) >= 24).length
  const toggleTile = (t: Exclude<Tile, ''>) => setTile(tile === t ? '' : t)
  const tiles: KpiItem[] = ([
    { key: 'waiting', label: 'Waiting', value: counts.waiting || '—', icon: Inbox, tone: counts.waiting ? 'attention' : 'default', hint: longWait ? `${longWait} over a day` : undefined, pressed: tile === 'waiting', onClick: () => toggleTile('waiting') },
    { key: 'late', label: 'Late', value: counts.late || '—', icon: AlarmClock, tone: counts.late ? 'bad' : 'default', pressed: tile === 'late', onClick: () => toggleTile('late') },
    { key: 'soon', label: 'Due in 2 days', value: counts.soon || '—', icon: CalendarDays, tone: counts.soon ? 'attention' : 'default', pressed: tile === 'soon', onClick: () => toggleTile('soon') },
    { key: 'dup', label: 'Duplicates', value: counts.dup || '—', icon: Copy, tone: counts.dup ? 'attention' : 'default', pressed: tile === 'dup', onClick: () => toggleTile('dup') },
    { key: 'speed', label: 'Office orders in', value: speed ? hoursWords(speed.hours) : '—', icon: Gauge, tone: !speed ? 'default' : speed.hours <= 8 ? 'good' : speed.hours <= 24 ? 'default' : 'attention', hint: speed ? `avg of ${speed.count} · 30 days` : undefined },
  ] as KpiItem[]).map((k) => ({ ...k, loading: isLoading }))

  // UX-65: is each waiting line in its project's material plan (and within what the work still needs)? Asked once
  // per project with waiting requests; a role that may not see the BOQ gets no plan chip.
  const planProjects = React.useMemo(() => [...new Set(all.filter((r) => r.status === 'waiting').map((r) => r.project_id))].slice(0, 8), [all])
  const plans = useQueries({
    queries: planProjects.map((pid) => ({ queryKey: ['material-plan', pid, 8, ''], queryFn: () => fetchMaterialPlan(pid, 8), retry: false, staleTime: 5 * 60_000 })),
  })
  const planOf = React.useMemo(() => {
    const out = new Map<string, Map<string, MaterialPlanRow>>()
    planProjects.forEach((pid, i) => { const d = plans[i]?.data; if (d) out.set(pid, new Map(d.materials.map((row) => [row.material_id, row]))) })
    return out
  }, [planProjects, plans])

  const pickedRequests = all.filter((r) => picked.includes(r.id))
  const pickSite = pickedRequests[0]?.site_id
  const togglePick = (r: MaterialRequest) => setPicked((p) => (p.includes(r.id) ? p.filter((x) => x !== r.id) : [...p, r.id]))
  const orderTogether = () => {
    const first = pickedRequests[0]
    if (!first) return
    setOrdering({
      project_id: first.project_id, site_id: first.site_id, site_name: first.site_name, request_id: first.id,
      request_ref: pickedRequests.map((r) => r.ref).join(', '),
      lines: pickedRequests.flatMap((r) => r.lines.filter((l) => Number(l.to_buy) > 0 || r.status === 'waiting').map((l) => ({
        material_id: l.material_id, quantity: Number(l.to_buy) > 0 ? l.to_buy : l.quantity, request_line_id: l.id, request_ref: r.ref,
      }))),
    })
  }
  React.useEffect(() => setPicked([]), [tab, tile])

  const canAsk = !!me && me.role !== 'FINANCE' && !readOnly
  const pickTab = (t: Tab) => { setTile(''); setTab(t) }

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <header className="flex items-center justify-between gap-3">
        <ModuleTitle icon={ClipboardList} title="Requests" />
        <div className="flex items-center gap-2">
        <Button variant="outline" className="gap-2" disabled={!list.length} onClick={() => exportRequests(list)} title="The requests shown, as a CSV file (opens in Excel)">
          <ActionIcon kind="export-excel" className="size-4" /> <span className="hidden sm:inline">Export</span>
        </Button>
        {canAsk && (
          <Button className="hidden gap-2 font-semibold md:inline-flex" onClick={() => setCreating(true)} data-guide="req.add">
            <Plus className="size-4" strokeWidth={2.6} /> New request
            <kbd className="rounded bg-primary-foreground/20 px-1.5 text-[11px]">N</kbd>
          </Button>
        )}
        </div>
      </header>

      <KpiStrip guide="req.tiles" stats={tiles} />

      <div data-guide="req.tabs">
        <StateBar
          strip={false}
          items={TABS.map((t): StateItem => ({ value: t.value, label: t.label, icon: t.icon, tone: t.tone, count: all.filter((r) => passFilters(r) && inTab(r, t.value)).length }))}
          value={tile ? '' : tab === 'all' ? '' : tab}
          onChange={(v) => pickTab((v || 'all') as Tab)}
          extra={<button type="button" onClick={() => pickTab('all')} aria-pressed={!tile && tab === 'all'} className={cn('rounded-full px-2.5 py-1 text-xs font-semibold', !tile && tab === 'all' ? 'bg-foreground text-background' : 'text-muted-foreground hover:text-foreground')}>All <span className="tabular-nums">{all.filter((r) => passFilters(r)).length}</span></button>}
        >
          <div className="flex flex-wrap items-center gap-2" data-guide="req.filters">
            {!siteId && <FilterPill icon={MapPin} label="Site" allLabel="All sites" value={site} options={options.sites} onChange={setSite} />}
            <FilterPill icon={User} label="Asked by" allLabel="Anyone" value={by} options={options.people} onChange={setBy} />
            <FilterPill icon={LayoutGrid} label="Category" allLabel="All categories" value={category} options={options.categories} onChange={setCategory} />
            <FilterPill icon={CalendarDays} label="Needed by" allLabel="Any date" value={due} options={options.dues} onChange={setDue} />
            <label className="flex h-9 items-center gap-2 rounded-lg border bg-background px-2.5">
              <Search className="size-4 text-muted-foreground" />
              <span className="sr-only">Search requests</span>
              <input ref={searchRef} value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search" className="w-24 bg-transparent text-sm outline-none sm:w-32" />
              <kbd className="hidden rounded border px-1 text-[11px] text-muted-foreground sm:inline">/</kbd>
            </label>
          </div>
        </StateBar>
      </div>

      <BulkBar count={picked.length} onClear={() => setPicked([])}>
        <span className="text-xs opacity-80">{pickedRequests.map((r) => r.ref).join(', ')}</span>
        <Button size="sm" className="h-8 gap-1.5" onClick={orderTogether}><ShoppingCart className="size-4" />Order together</Button>
      </BulkBar>

      <div className="flex flex-col items-start gap-5 lg:flex-row">
        <div className="flex w-full min-w-0 flex-1 flex-col gap-2">
        <section aria-label="Requests" className="w-full overflow-hidden rounded-xl border bg-card" data-guide={isLoading ? undefined : 'req.list'}>
          {isLoading && <div className="flex flex-col">{[0, 1, 2, 3].map((i) => <div key={i} className="h-24 animate-pulse border-b bg-muted/40" />)}</div>}
          {isError && <p className="p-6 text-sm text-destructive">Requests did not load. Refresh to try again.</p>}
          {!isLoading && !isError && list.length === 0 && (
            <div className="flex flex-col items-center gap-2 px-4 py-12 text-center text-sm text-muted-foreground">
              <ClipboardList className="size-8 opacity-40" />
              {all.length === 0 ? <><span className="font-medium text-foreground">No requests yet</span><SayOnWhatsApp text="Need 50 bags cement tomorrow" /></> : tab === 'waiting' && !tile ? <AllClear onOrdered={() => pickTab('ordered')} ordered={all.filter((r) => passFilters(r) && inTab(r, 'ordered')).length} /> : 'No requests here with these filters.'}
            </div>
          )}
          {pagedList.shown.map((r) => (
            <RequestRow key={r.id} request={r} selected={current?.id === r.id} onPick={() => setSelected(r.id)}
              plan={planOf.get(r.project_id)} tick={r.status === 'waiting' && r.may_act && !readOnly && (!pickSite || pickSite === r.site_id) ? { on: picked.includes(r.id), toggle: () => togglePick(r) } : undefined} />
          ))}
        </section>
          <Pager {...pagedList.pager} noun="requests" />
        </div>

        {!isMobile && current && (
          <aside aria-label="Request detail" className="sticky top-4 w-full shrink-0 overflow-hidden rounded-xl border lg:w-[420px]">
            <RequestDetail request={current} />
          </aside>
        )}
      </div>

      {isMobile && (
        <Sheet open={!!current} onOpenChange={(o) => !o && setSelected('')}>
          <SheetContent side="bottom" className="max-h-[92vh] gap-0 overflow-y-auto rounded-t-2xl p-0">
            <SheetTitle className="sr-only">{current ? `${current.ref} request` : 'Request'}</SheetTitle>
            {current && <RequestDetail request={current} inSheet />}
          </SheetContent>
        </Sheet>
      )}

      {canAsk && (
        <Button className="fixed right-4 bottom-5 z-30 h-12 gap-2 rounded-full px-5 font-semibold shadow-lg md:hidden" onClick={() => setCreating(true)} data-guide="req.add">
          <Plus className="size-5" strokeWidth={2.6} /> Request
        </Button>
      )}
      <NewRequestDialog open={creating} onOpenChange={setCreating} scope={scope} />
      <NewOrderDialog open={!!ordering} onOpenChange={(o) => { if (!o) { setOrdering(null); setPicked([]) } }} prefill={ordering} scope={scope} />
    </div>
  )
}

/** "All clear" when nothing waits for the office, and the way to what is on order. */
function AllClear({ ordered, onOrdered }: { ordered: number; onOrdered: () => void }) {
  return (
    <EmptyState icon={CircleCheck} title="All clear" className="border-0"
      action={ordered > 0 ? <Button variant="outline" size="sm" className="gap-1.5" onClick={onOrdered}><ShoppingCart className="size-4" />{ordered} on order</Button> : undefined} />
  )
}

/** UX-65: is the waiting line in the project's material plan, and within what the work still needs? */
function PlanChip({ line, plan }: { line: MaterialRequest['lines'][number]; plan: Map<string, MaterialPlanRow> }) {
  const row = plan.get(line.material_id)
  if (!row || Number(row.required) <= 0) return <Pill tone="muted" size="xs" icon={ListChecks} title="This material is not in the project's material plan (BOQ)">Not in plan</Pill>
  const still = Number(row.still_needed)
  if (row.unit === line.unit && Number(line.quantity) > still + Number(row.on_hand)) {
    return <Pill tone="attention" size="xs" icon={ListChecks} title={`The work still to do needs ${qty(String(still), row.unit)}`}>Above plan</Pill>
  }
  return <Pill tone="info" size="xs" icon={ListChecks} title={`In the plan · ${qty(String(still), row.unit)} still needed`}>In plan</Pill>
}

function RequestRow({ request: r, selected, onPick, plan, tick }: {
  request: MaterialRequest
  selected: boolean
  onPick: () => void
  plan?: Map<string, MaterialPlanRow>
  tick?: { on: boolean; toggle: () => void }
}) {
  const first = r.lines[0]
  const more = r.lines.length - 1
  const waiting = r.status === 'waiting'
  const hours = waitedHours(r)
  return (
    <div className={cn('flex w-full border-b transition hover:bg-muted/40', selected && 'bg-yellow-50 shadow-[inset_0_0_0_2px_theme(colors.yellow.300)] dark:bg-yellow-950/40')}>
    {tick && (
      <label className="flex shrink-0 cursor-pointer items-start pt-4 pl-3 sm:pl-4" title="Tick to order together">
        <input type="checkbox" checked={tick.on} onChange={tick.toggle} className="size-4 accent-primary" aria-label={`Pick ${r.ref}`} />
      </label>
    )}
    <button
      type="button"
      onClick={onPick}
      data-record-id={r.id}
      aria-current={selected || undefined}
      className="flex min-w-0 flex-1 gap-3 px-3 py-3 text-left sm:px-4"
    >
      <CategoryTile mainCategory={first?.main_category ?? null} />
      <span className="flex min-w-0 flex-1 flex-col gap-1.5">
        <span className="flex items-center justify-between gap-2">
          <span className="line-clamp-2 min-w-0">
            <span className="font-semibold">{first?.material}</span>
            {first && <span className="ml-1.5 font-semibold text-foreground/75 tabular-nums">{qty(first.quantity, first.unit)}</span>}
            {more > 0 && <span className="ml-1.5 rounded-full bg-muted px-1.5 text-xs font-semibold">+{more}</span>}
          </span>
          {r.urgency !== 'closed' && <UrgencyChip request={r} />}
        </span>
        <span className="flex items-center justify-between gap-2 text-sm text-muted-foreground">
          <span className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1">
            <span className="inline-flex items-center gap-1.5"><ProjectDot id={r.project_id} />{r.site_name}</span>
            <span className="inline-flex items-center gap-1.5"><Avatar id={r.requested_by} name={r.requested_by_name} />{(r.requested_by_name ?? 'Someone').split(' ')[0]}</span>
            {r.source === 'whatsapp' && <WhatsAppMark />}
            {waiting ? <Pill tone={waitTone(hours)} size="xs" icon={Timer} title="Waiting for the office">{hoursWords(hours)}</Pill> : <span className="text-xs tabular-nums">{ago(r.created_at)}</span>}
          </span>
          <span className="hidden sm:inline-flex"><StatusChip status={r.status} /></span>
        </span>
        {waiting && first && (
          <span className="flex flex-wrap items-center gap-2 text-xs">
            <CoverBar line={first} className="w-32 sm:w-48" />
            {Number(first.to_buy) > 0 ? (
              <span className="inline-flex items-center gap-1 font-bold"><ShoppingCart className="size-3.5" />{qty(first.to_buy, first.unit)}</span>
            ) : (
              <span className="font-semibold text-success">Covered</span>
            )}
            {r.duplicates.length > 0 && (
              <span className="inline-flex items-center gap-1 rounded-md bg-orange-100 px-1.5 py-0.5 font-semibold text-orange-950 dark:bg-orange-950 dark:text-orange-100"><Copy className="size-3" />{r.duplicates[0].ref}</span>
            )}
            {plan && <PlanChip line={first} plan={plan} />}
            {first.elsewhere.length > 0 && (
              <span className="rounded-md bg-fuchsia-100 px-1.5 py-0.5 font-semibold text-fuchsia-900 dark:bg-fuchsia-950 dark:text-fuchsia-100">→ {qty(first.elsewhere[0].quantity, first.unit)} at {first.elsewhere[0].site_name}</span>
            )}
          </span>
        )}
        {!waiting && r.decision_note && <span className="truncate text-xs text-muted-foreground">{r.status === 'rejected' ? '✕ ' : ''}{r.decision_note}</span>}
        <span className="sm:hidden"><StatusChip status={r.status} /></span>
      </span>
    </button>
    </div>
  )
}
