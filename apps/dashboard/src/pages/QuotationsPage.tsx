import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlarmClock, Hourglass, MapPin, PackageCheck, Plus, Scale, Search, Sparkles, Store } from 'lucide-react'
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
import { rupees } from '@/lib/orders'
import { swatch } from '@/lib/requests'
import { RFQ_LOOK, dueWords, fetchRfqs, type Rfq, type RfqStatus } from '@/lib/rfqs'
import { CategoryTile, FilterPill, ProjectDot, type FilterOption } from '@/components/requests/parts'
import { RfqDetail } from '@/components/quotations/rfq-detail'
import { NewRfqDialog } from '@/components/quotations/new-rfq-dialog'
import { ModuleTitle } from '@/components/page/page-kit'

// PRC-44: Procurement › Quotations, in the Requests / Purchase orders design: tiles for what needs doing (waiting for
// quotes, ready to compare, quotes overdue, saved by comparing), status tabs, a list beside the chosen RFQ (a sheet
// on a phone). Ask three shops before a big order; the comparison and the ordering are on the RFQ.

type Tab = 'live' | 'ready' | 'awarded' | 'closed' | 'all'
type Tile = '' | 'open' | 'ready' | 'overdue'

const TABS: { value: Tab; label: string; dot: string }[] = [
  { value: 'live', label: 'Open', dot: RFQ_LOOK.open.dot },
  { value: 'ready', label: 'Ready to compare', dot: RFQ_LOOK.ready.dot },
  { value: 'awarded', label: 'Ordered', dot: RFQ_LOOK.awarded.dot },
  { value: 'closed', label: 'Closed', dot: RFQ_LOOK.closed.dot },
  { value: 'all', label: 'All', dot: 'bg-muted-foreground/50' },
]

function inTab(r: Rfq, tab: Tab): boolean {
  if (tab === 'live') return r.status === 'open' || r.status === 'ready'
  if (tab === 'closed') return r.status === 'closed' || r.status === 'cancelled'
  if (tab === 'all') return true
  return r.status === tab
}

function inTile(r: Rfq, tile: Tile): boolean {
  if (tile === 'open') return r.status === 'open'
  if (tile === 'ready') return r.status === 'ready'
  if (tile === 'overdue') return r.status === 'open' && r.due_days !== null && r.due_days < 0
  return true
}

const ORDER: Record<RfqStatus, number> = { ready: 0, open: 1, awarded: 2, closed: 3, cancelled: 4 }

/** What comparing saved on the RFQs ordered: the dearest complete quote's total minus what was ordered. */
function saved(r: Rfq): number {
  if (r.status !== 'awarded') return 0
  const totals = r.suppliers.filter((s) => s.complete && s.total).map((s) => Number(s.total))
  if (totals.length < 2) return 0
  const paid = r.lines.reduce((sum, l) => sum + Number(l.quotes.find((q) => q.quote_line_id && q.quote_line_id === l.awarded_quote_line_id)?.amount ?? 0), 0)
  return paid ? Math.max(0, Math.max(...totals) - paid) : 0
}

export default function QuotationsPage() {
  usePageTitle('Quotations')
  const { scope } = useScope()
  const { me } = useAuth()
  const readOnly = useReadOnly()
  const isMobile = useIsMobile()
  const projectId = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : null
  const siteId = scope.mode === 'site' ? scope.siteId : null
  const office = ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'PROJECT_MANAGER'].includes((me?.role || '').toUpperCase())

  const [tab, setTab] = useUrlState<Tab>('tab', 'live')
  const [tile, setTile] = useUrlState<Tile>('show', '')
  const [site, setSite] = useUrlState<string>('at', '')
  const [vendor, setVendor] = useUrlState<string>('vendor', '')
  const [selected, setSelected] = useUrlState<string>('id', '')
  const [search, setSearch] = React.useState('')
  const [creating, setCreating] = React.useState(false)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['procurement', 'rfqs', projectId, siteId],
    queryFn: () => fetchRfqs({ project_id: projectId, site_id: siteId }),
    refetchInterval: 60_000,
  })
  const all = React.useMemo(() => data?.items ?? [], [data])

  const pass = React.useCallback((r: Rfq, skip?: string) => {
    if (skip !== 'site' && site && r.site_id !== site) return false
    if (skip !== 'vendor' && vendor && !r.suppliers.some((s) => s.vendor_id === vendor)) return false
    if (search) {
      const q = search.toLowerCase()
      if (!r.ref.toLowerCase().includes(q) && !r.lines.some((l) => l.material.toLowerCase().includes(q)) && !r.suppliers.some((s) => s.name.toLowerCase().includes(q))) return false
    }
    return true
  }, [site, vendor, search])
  const filtered = React.useMemo(() => all.filter((r) => pass(r)), [all, pass])
  const list = React.useMemo(
    () => filtered.filter((r) => (tile ? inTile(r, tile) : inTab(r, tab))).sort((a, b) => ORDER[a.status] - ORDER[b.status] || (a.due_days ?? 999) - (b.due_days ?? 999) || b.number - a.number),
    [filtered, tab, tile],
  )
  const current = all.find((r) => r.id === selected) ?? (isMobile ? undefined : list[0])

  const options = React.useMemo(() => {
    const count = (skip: string, test: (r: Rfq) => boolean) => all.filter((r) => pass(r, skip) && test(r)).length
    const uniq = <T,>(xs: T[], key: (t: T) => string) => [...new Map(xs.map((x) => [key(x), x])).values()]
    const sites: FilterOption[] = uniq(all, (r) => r.site_id).map((r) => ({ value: r.site_id, label: `${r.project_name} › ${r.site_name}`, swatch: swatch(r.project_id), count: count('site', (x) => x.site_id === r.site_id) }))
    const vendors: FilterOption[] = uniq(all.flatMap((r) => r.suppliers), (s) => s.vendor_id).map((s) => ({ value: s.vendor_id, label: s.name, swatch: swatch(s.vendor_id), count: count('vendor', (x) => x.suppliers.some((y) => y.vendor_id === s.vendor_id)) }))
    return { sites, vendors }
  }, [all, pass])

  const savedTotal = filtered.reduce((s, r) => s + saved(r), 0)
  const tiles: { value: Exclude<Tile, ''>; label: string; count: number; icon: LucideIcon; tone: string; ring: string; num?: string }[] = [
    { value: 'open', label: 'Waiting for quotes', count: filtered.filter((r) => inTile(r, 'open')).length, icon: Hourglass, tone: 'bg-info-soft text-info', ring: 'ring-blue-500' },
    { value: 'ready', label: 'Ready to compare', count: filtered.filter((r) => inTile(r, 'ready')).length, icon: Scale, tone: 'bg-yellow-200 text-yellow-950 dark:bg-yellow-900 dark:text-yellow-100', ring: 'ring-yellow-500' },
    { value: 'overdue', label: 'Quotes overdue', count: filtered.filter((r) => inTile(r, 'overdue')).length, icon: AlarmClock, tone: 'bg-destructive text-white', ring: 'ring-destructive', num: 'text-destructive' },
  ]

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <header className="flex items-center justify-between gap-3">
        <ModuleTitle icon={Scale} title="Quotations" />
        {office && !readOnly && <Button className="hidden gap-2 font-semibold md:inline-flex" onClick={() => setCreating(true)}><Plus className="size-4" strokeWidth={2.6} /> Ask for quotes</Button>}
      </header>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 sm:gap-3">
        {tiles.map((t) => {
          const on = tile === t.value
          return (
            <button key={t.value} type="button" aria-pressed={on} onClick={() => setTile(on ? '' : t.value)} className={cn('flex items-center gap-3 rounded-xl border bg-card p-3 text-left transition hover:-translate-y-px sm:p-3.5', on && cn('ring-2', t.ring))}>
              <span className={cn('inline-flex size-9 shrink-0 items-center justify-center rounded-lg sm:size-11 sm:rounded-xl', t.tone)}><t.icon className="size-4 sm:size-5" /></span>
              <span className="flex flex-col">
                <span className={cn('text-2xl leading-none font-semibold tabular-nums sm:text-3xl', t.count ? t.num : undefined)}>{t.count}</span>
                <span className="text-xs leading-tight text-muted-foreground sm:text-sm sm:text-foreground/80">{t.label}</span>
              </span>
            </button>
          )
        })}
        <div className="flex items-center gap-3 rounded-xl border bg-card p-3 sm:p-3.5" title="On the RFQs ordered: the dearest full quote minus what was ordered">
          <span className="inline-flex size-9 shrink-0 items-center justify-center rounded-lg bg-emerald-100 text-emerald-800 sm:size-11 sm:rounded-xl dark:bg-emerald-950 dark:text-emerald-200"><Sparkles className="size-4 sm:size-5" /></span>
          <span className="flex flex-col">
            <span className="text-2xl leading-none font-semibold tabular-nums text-emerald-700 sm:text-3xl dark:text-emerald-400">{savedTotal ? rupees(savedTotal) : '—'}</span>
            <span className="text-xs leading-tight text-muted-foreground sm:text-sm sm:text-foreground/80">Saved by comparing</span>
          </span>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div role="tablist" aria-label="Status" className="flex max-w-full gap-0.5 overflow-x-auto rounded-xl bg-muted p-1">
          {TABS.map((t) => {
            const on = !tile && tab === t.value
            const n = filtered.filter((r) => inTab(r, t.value)).length
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
          <label className="flex h-9 items-center gap-2 rounded-lg border bg-background px-2.5">
            <Search className="size-4 text-muted-foreground" />
            <span className="sr-only">Search quotations</span>
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="RFQ, item, supplier" className="w-28 bg-transparent text-sm outline-none sm:w-36" />
          </label>
        </div>
      </div>

      <div className="flex flex-col items-start gap-5 lg:flex-row">
        <section aria-label="Quotations" className="w-full min-w-0 flex-1 overflow-hidden rounded-xl border lg:max-w-[440px]">
          {isLoading && <div className="flex flex-col">{[0, 1, 2].map((i) => <div key={i} className="h-24 animate-pulse border-b bg-muted/40" />)}</div>}
          {isError && <p className="p-6 text-sm text-destructive">Quotations did not load. Refresh to try again.</p>}
          {!isLoading && !isError && list.length === 0 && (
            <div className="flex flex-col items-center gap-2 px-4 py-12 text-center text-sm text-muted-foreground">
              <PackageCheck className="size-8 opacity-40" />
              {all.length === 0 ? <><strong className="text-foreground">Ask three shops before a big order.</strong>Send them the RFQ on WhatsApp, record their rates, and Mesiri shows who is really cheapest, GST and all.</> : 'No RFQs here with these filters.'}
              {all.length === 0 && office && !readOnly && <Button className="mt-2 gap-2" onClick={() => setCreating(true)}><Plus className="size-4" />Ask for quotes</Button>}
            </div>
          )}
          {list.map((r) => <RfqRow key={r.id} rfq={r} selected={current?.id === r.id} onPick={() => setSelected(r.id)} />)}
        </section>
        {!isMobile && current && (
          <aside aria-label="RFQ detail" className="sticky top-4 w-full min-w-0 flex-[1.6] overflow-hidden rounded-xl border"><RfqDetail key={current.id} rfq={current} /></aside>
        )}
      </div>

      {isMobile && (
        <Sheet open={!!current} onOpenChange={(o) => !o && setSelected('')}>
          <SheetContent side="bottom" className="max-h-[92vh] gap-0 overflow-y-auto rounded-t-2xl p-0">
            <SheetTitle className="sr-only">{current ? `${current.ref} quotations` : 'Quotations'}</SheetTitle>
            {current && <RfqDetail key={current.id} rfq={current} inSheet />}
          </SheetContent>
        </Sheet>
      )}
      {office && !readOnly && (
        <Button className="fixed right-4 bottom-5 z-30 h-12 gap-2 rounded-full px-5 font-semibold shadow-lg md:hidden" onClick={() => setCreating(true)}><Plus className="size-5" strokeWidth={2.6} /> Quotes</Button>
      )}
      <NewRfqDialog open={creating} onOpenChange={setCreating} scope={scope} onCreated={(r) => setSelected(r.id)} />
    </div>
  )
}

function RfqRow({ rfq: r, selected, onPick }: { rfq: Rfq; selected: boolean; onPick: () => void }) {
  const first = r.lines[0]
  const more = r.lines.length - 1
  const look = RFQ_LOOK[r.status]
  const due = dueWords(r)
  const asked = r.suppliers.length
  return (
    <button type="button" onClick={onPick} aria-current={selected || undefined} className={cn('flex w-full gap-3 border-b px-3 py-3 text-left transition hover:bg-muted/40 sm:px-4', selected && 'bg-yellow-50 shadow-[inset_0_0_0_2px_theme(colors.yellow.300)] dark:bg-yellow-950/40')}>
      {first && <CategoryTile mainCategory={first.main_category} />}
      <span className="flex min-w-0 flex-1 flex-col gap-1.5">
        <span className="flex items-center justify-between gap-2">
          <span className="min-w-0 truncate font-semibold">{first?.material}{more > 0 && <span className="ml-1.5 rounded-full bg-muted px-1.5 text-xs font-semibold">+{more}</span>}</span>
          <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{r.ref}</span>
        </span>
        <span className="flex items-center gap-1.5" aria-label={`${r.counts.quoted} of ${asked} quoted`}>
          {r.suppliers.map((s) => <span key={s.rfq_vendor_id} title={`${s.name}: ${s.status}`} className={cn('h-1.5 flex-1 rounded-full', s.status === 'quoted' ? (s.best_total ? 'bg-emerald-500' : 'bg-teal-400') : s.status === 'declined' ? 'bg-destructive/40' : 'bg-muted')} />)}
          <span className="ml-1 text-xs text-muted-foreground tabular-nums">{r.counts.quoted}/{asked} quoted</span>
        </span>
        <span className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1"><ProjectDot id={r.project_id} />{r.site_name}</span>
          {r.lowest_total && <span>best <strong className="text-foreground tabular-nums">{rupees(r.lowest_total.total)}</strong> · {r.lowest_total.name}</span>}
          {due && <span className={cn(r.due_days !== null && r.due_days < 0 && 'font-semibold text-destructive')}>{due}</span>}
          <span className={cn('ml-auto inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-semibold', look.chip)}><span className={cn('size-1.5 rounded-full', look.dot)} />{look.label}</span>
        </span>
      </span>
    </button>
  )
}
