import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlarmClock, CalendarDays, ClipboardList, Copy, Download, Inbox, LayoutGrid, MapPin, Plus, Search, ShoppingCart, User } from 'lucide-react'
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
import {
  STATUS_LOOK,
  URGENCY_LOOK,
  ago,
  fetchRequests,
  qty,
  swatch,
  type MaterialRequest,
  type Urgency,
} from '@/lib/requests'
import { Avatar, CategoryTile, CoverBar, FilterPill, ProjectDot, StatusChip, UrgencyChip, WhatsAppMark, type FilterOption } from '@/components/requests/parts'
import { RequestDetail } from '@/components/requests/request-detail'
import { NewRequestDialog } from '@/components/requests/new-request-dialog'

// PRC-22 (design approved by Ilan, 7 Nov 2026): Materials > Requests. What the sites need and what is happening
// to it. Four tiles say what needs attention; tabs by status; filters as dropdowns with the same cues as the rows;
// a list on the left and the chosen request on the right (a sheet on a phone). Most urgent first.

type Tab = 'waiting' | 'ordered' | 'done' | 'rejected' | 'all'
type Tile = '' | 'waiting' | 'late' | 'soon' | 'dup'

const TABS: { value: Tab; label: string; dot: string }[] = [
  { value: 'waiting', label: 'Waiting', dot: STATUS_LOOK.waiting.dot },
  { value: 'ordered', label: 'Ordered', dot: STATUS_LOOK.ordered.dot },
  { value: 'done', label: 'Received', dot: STATUS_LOOK.done.dot },
  { value: 'rejected', label: 'Not ordered', dot: STATUS_LOOK.rejected.dot },
  { value: 'all', label: 'All', dot: 'bg-muted-foreground/50' },
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
  exportCsv(`material-requests-${new Date().toISOString().slice(0, 10)}.csv`,
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

  const [tab, setTab] = useUrlState<Tab>('tab', 'waiting')
  const [tile, setTile] = useUrlState<Tile>('show', '')
  const [site, setSite] = useUrlState<string>('at', '')  // PRC-27: not 'site' (the scope's own key, as WEB-34)
  const [by, setBy] = useUrlState<string>('by', '')
  const [category, setCategory] = useUrlState<string>('category', '')
  const [due, setDue] = useUrlState<string>('due', '')
  const [search, setSearch] = React.useState('')
  const [selected, setSelected] = useUrlState<string>('id', '')
  const [creating, setCreating] = React.useState(false)
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
  const list = React.useMemo(
    () =>
      filtered
        .filter((r) => (tile ? inTile(r, tile) : inTab(r, tab)))
        .sort((a, b) => URGENCY_ORDER[a.urgency] - URGENCY_ORDER[b.urgency] || (a.needed_by ?? '9999').localeCompare(b.needed_by ?? '9999') || b.number - a.number),
    [filtered, tab, tile],
  )

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
  const tiles: { value: Exclude<Tile, ''>; label: string; count: number; icon: LucideIcon; iconTone: string; ring: string; numTone?: string }[] = [
    { value: 'waiting', label: 'Waiting for the office', count: counts.waiting, icon: Inbox, iconTone: 'bg-stone-200 text-stone-800 dark:bg-stone-700 dark:text-stone-100', ring: 'ring-stone-500' },
    { value: 'late', label: 'Late', count: counts.late, icon: AlarmClock, iconTone: 'bg-destructive text-white', ring: 'ring-destructive', numTone: counts.late ? 'text-destructive' : undefined },
    { value: 'soon', label: 'Due in 2 days', count: counts.soon, icon: CalendarDays, iconTone: 'bg-orange-200 text-orange-950 dark:bg-orange-900 dark:text-orange-100', ring: 'ring-orange-500' },
    { value: 'dup', label: 'Possible duplicates', count: counts.dup, icon: Copy, iconTone: 'bg-orange-100 text-orange-900 dark:bg-orange-950 dark:text-orange-100', ring: 'ring-orange-500' },
  ]

  const canAsk = !!me && me.role !== 'FINANCE' && !readOnly
  const pickTab = (t: Tab) => { setTile(''); setTab(t) }

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <header className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="inline-flex size-10 items-center justify-center rounded-xl bg-yellow-100 text-yellow-800 dark:bg-yellow-950 dark:text-yellow-200">
            <ClipboardList className="size-5" />
          </span>
          <div>
            <div className="text-xs text-muted-foreground">Materials</div>
            <h1 className="text-2xl leading-tight font-semibold tracking-tight">Requests</h1>
          </div>
        </div>
        <div className="flex items-center gap-2">
        <Button variant="outline" className="gap-2" disabled={!list.length} onClick={() => exportRequests(list)} title="The requests shown, as a CSV file (opens in Excel)">
          <Download className="size-4" /> <span className="hidden sm:inline">Export</span>
        </Button>
        {canAsk && (
          <Button className="hidden gap-2 font-semibold md:inline-flex" onClick={() => setCreating(true)}>
            <Plus className="size-4" strokeWidth={2.6} /> New request
            <kbd className="rounded bg-primary-foreground/20 px-1.5 text-[11px]">N</kbd>
          </Button>
        )}
        </div>
      </header>

      <div className="grid grid-cols-4 gap-2 sm:gap-3 lg:grid-cols-4">
        {tiles.map((t) => {
          const on = tile === t.value
          return (
            <button
              key={t.value}
              type="button"
              aria-pressed={on}
              onClick={() => setTile(on ? '' : t.value)}
              className={cn(
                'flex flex-col items-center gap-1 rounded-xl border bg-card p-2 text-center transition hover:-translate-y-px sm:flex-row sm:gap-3 sm:p-3.5 sm:text-left',
                on && cn('ring-2', t.ring),
              )}
            >
              <span className={cn('inline-flex size-8 shrink-0 items-center justify-center rounded-lg sm:size-11 sm:rounded-xl', t.iconTone)}>
                <t.icon className="size-4 sm:size-5" />
              </span>
              <span className="flex flex-col">
                <span className={cn('text-xl leading-none font-semibold tabular-nums sm:text-3xl', t.numTone)}>{t.count}</span>
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
            const n = all.filter((r) => passFilters(r) && inTab(r, t.value)).length
            return (
              <button
                key={t.value}
                role="tab"
                type="button"
                aria-selected={on}
                onClick={() => pickTab(t.value)}
                className={cn('inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-3 text-sm whitespace-nowrap', on ? 'bg-background font-semibold shadow-sm' : 'text-foreground/75 hover:text-foreground')}
              >
                <span className={cn('size-2 rounded-full', t.dot)} />
                {t.label}
                <span className={cn('rounded-full px-1.5 text-[11px] font-semibold tabular-nums', on ? 'bg-foreground text-background' : 'bg-background/70')}>{n}</span>
              </button>
            )
          })}
        </div>
        <div className="flex flex-wrap items-center gap-2">
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
      </div>

      <div className="flex flex-col items-start gap-5 lg:flex-row">
        <section aria-label="Requests" className="w-full min-w-0 flex-1 overflow-hidden rounded-xl border">
          {isLoading && <div className="flex flex-col">{[0, 1, 2, 3].map((i) => <div key={i} className="h-24 animate-pulse border-b bg-muted/40" />)}</div>}
          {isError && <p className="p-6 text-sm text-destructive">Requests did not load. Refresh to try again.</p>}
          {!isLoading && !isError && list.length === 0 && (
            <div className="flex flex-col items-center gap-2 px-4 py-12 text-center text-sm text-muted-foreground">
              <ClipboardList className="size-8 opacity-40" />
              {all.length === 0 ? 'No requests yet. Engineers can also ask on WhatsApp: “need 50 bags cement tomorrow”.' : tab === 'waiting' ? 'Nothing waiting for the office.' : 'No requests here with these filters.'}
            </div>
          )}
          {list.map((r) => (
            <RequestRow key={r.id} request={r} selected={current?.id === r.id} onPick={() => setSelected(r.id)} />
          ))}
        </section>

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
        <Button className="fixed right-4 bottom-5 z-30 h-12 gap-2 rounded-full px-5 font-semibold shadow-lg md:hidden" onClick={() => setCreating(true)}>
          <Plus className="size-5" strokeWidth={2.6} /> Request
        </Button>
      )}
      <NewRequestDialog open={creating} onOpenChange={setCreating} scope={scope} />
    </div>
  )
}

function RequestRow({ request: r, selected, onPick }: { request: MaterialRequest; selected: boolean; onPick: () => void }) {
  const first = r.lines[0]
  const more = r.lines.length - 1
  const waiting = r.status === 'waiting'
  return (
    <button
      type="button"
      onClick={onPick}
      aria-current={selected || undefined}
      className={cn('flex w-full gap-3 border-b px-3 py-3 text-left transition hover:bg-muted/40 sm:px-4', selected && 'bg-yellow-50 shadow-[inset_0_0_0_2px_theme(colors.yellow.300)] dark:bg-yellow-950/40')}
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
            <span className="text-xs tabular-nums">{ago(r.created_at)}</span>
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
            {first.elsewhere.length > 0 && (
              <span className="rounded-md bg-fuchsia-100 px-1.5 py-0.5 font-semibold text-fuchsia-900 dark:bg-fuchsia-950 dark:text-fuchsia-100">→ {qty(first.elsewhere[0].quantity, first.unit)} at {first.elsewhere[0].site_name}</span>
            )}
          </span>
        )}
        {!waiting && r.decision_note && <span className="truncate text-xs text-muted-foreground">{r.status === 'rejected' ? '✕ ' : ''}{r.decision_note}</span>}
        <span className="sm:hidden"><StatusChip status={r.status} /></span>
      </span>
    </button>
  )
}
