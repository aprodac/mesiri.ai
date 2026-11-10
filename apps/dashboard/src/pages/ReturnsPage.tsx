import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { CalendarDays, IndianRupee, MapPin, PackageX, Search, Store, Truck } from 'lucide-react'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { useScope } from '@/lib/ScopeContext'
import { usePageTitle } from '@/lib/page-title'
import { useUrlState } from '@/lib/url-state'
import { useIsMobile } from '@/hooks/use-mobile'
import { cn } from '@/lib/utils'
import { rupees } from '@/lib/orders'
import { swatch } from '@/lib/requests'
import { RETURN_LOOK, fetchReturns, type MaterialReturn, type ReturnStatus } from '@/lib/returns'
import { CategoryTile, FilterPill, ProjectDot, type FilterOption } from '@/components/requests/parts'
import { ReturnDetail } from '@/components/returns/return-detail'
import { ModuleTitle } from '@/components/page/page-kit'

// PRC-46: Procurement › Returns, in the Requests / Purchase orders design: tiles (waiting for pickup, what suppliers
// owe back, returns this month), status tabs, a list beside the chosen return (a sheet on a phone). A return is
// started where the bad material is seen: a GRN's rejected quantity, a delivery in Movements, the supplier's page,
// or WhatsApp ("12 steel bars bent, returning to KSL").

type Tab = 'open' | 'waiting' | 'sent' | 'settled' | 'all'

const TABS: { value: Tab; label: string; dot: string }[] = [
  { value: 'open', label: 'Open', dot: RETURN_LOOK.waiting.dot },
  { value: 'waiting', label: 'Waiting for pickup', dot: RETURN_LOOK.waiting.dot },
  { value: 'sent', label: 'Sent back', dot: RETURN_LOOK.sent.dot },
  { value: 'settled', label: 'Settled', dot: RETURN_LOOK.settled.dot },
  { value: 'all', label: 'All', dot: 'bg-muted-foreground/50' },
]

function inTab(r: MaterialReturn, tab: Tab): boolean {
  if (tab === 'open') return r.status === 'waiting' || r.status === 'sent'
  if (tab === 'all') return true
  return r.status === tab
}

const ORDER: Record<ReturnStatus, number> = { waiting: 0, sent: 1, settled: 2, cancelled: 3 }

export default function ReturnsPage() {
  usePageTitle('Returns')
  const { scope } = useScope()
  const isMobile = useIsMobile()
  const projectId = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : null
  const siteId = scope.mode === 'site' ? scope.siteId : null
  const [tab, setTab] = useUrlState<Tab>('tab', 'open')
  const [site, setSite] = useUrlState<string>('at', '')
  const [vendor, setVendor] = useUrlState<string>('vendor', '')
  const [selected, setSelected] = useUrlState<string>('id', '')
  const [search, setSearch] = React.useState('')

  const { data, isLoading, isError } = useQuery({
    queryKey: ['procurement', 'returns', projectId, siteId],
    queryFn: () => fetchReturns({ project_id: projectId, site_id: siteId }),
    refetchInterval: 60_000,
  })
  const all = React.useMemo(() => data?.items ?? [], [data])
  const pass = React.useCallback((r: MaterialReturn, skip?: string) => {
    if (skip !== 'site' && site && r.site_id !== site) return false
    if (skip !== 'vendor' && vendor && r.vendor_id !== vendor) return false
    if (search) {
      const q = search.toLowerCase()
      if (!r.ref.toLowerCase().includes(q) && !r.what.toLowerCase().includes(q) && !r.vendor_name.toLowerCase().includes(q)) return false
    }
    return true
  }, [site, vendor, search])
  const filtered = React.useMemo(() => all.filter((r) => pass(r)), [all, pass])
  const list = React.useMemo(() => filtered.filter((r) => inTab(r, tab)).sort((a, b) => ORDER[a.status] - ORDER[b.status] || b.returned_on.localeCompare(a.returned_on) || b.number - a.number), [filtered, tab])
  const current = all.find((r) => r.id === selected) ?? (isMobile ? undefined : list[0])
  const options = React.useMemo(() => {
    const count = (skip: string, test: (r: MaterialReturn) => boolean) => all.filter((r) => pass(r, skip) && test(r)).length
    const uniq = <T,>(xs: T[], key: (t: T) => string) => [...new Map(xs.map((x) => [key(x), x])).values()]
    const sites: FilterOption[] = uniq(all, (r) => r.site_id).map((r) => ({ value: r.site_id, label: `${r.project_name} › ${r.site_name}`, swatch: swatch(r.project_id), count: count('site', (x) => x.site_id === r.site_id) }))
    const vendors: FilterOption[] = uniq(all, (r) => r.vendor_id).map((r) => ({ value: r.vendor_id, label: r.vendor_name, swatch: swatch(r.vendor_id), count: count('vendor', (x) => x.vendor_id === r.vendor_id) }))
    return { sites, vendors }
  }, [all, pass])
  const counts = data?.counts
  const money = counts?.owed_to_you !== undefined

  const tiles = [
    { label: 'Waiting for pickup', value: String(counts?.waiting ?? '–'), icon: Truck, tone: 'bg-orange-100 text-orange-900 dark:bg-orange-950 dark:text-orange-100', go: 'waiting' as Tab },
    ...(money ? [{ label: 'Suppliers owe you', value: Number(counts?.owed_to_you) ? rupees(counts?.owed_to_you) : '₹0', icon: IndianRupee, tone: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100', go: 'open' as Tab }] : []),
    { label: 'Returns this month', value: String(counts?.this_month ?? '–'), icon: CalendarDays, tone: 'bg-info-soft text-info', go: 'all' as Tab },
  ]

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <header className="flex items-center justify-between gap-3">
        <ModuleTitle icon={PackageX} title="Returns" />
      </header>

      <div className={cn('grid gap-2 sm:gap-3', money ? 'grid-cols-3' : 'grid-cols-2')}>
        {tiles.map((t) => (
          <button key={t.label} type="button" onClick={() => setTab(t.go)} className="flex flex-col items-start gap-2 rounded-xl border bg-card p-3 text-left transition hover:-translate-y-px sm:flex-row sm:items-center sm:gap-3 sm:p-3.5">
            <span className={cn('inline-flex size-9 shrink-0 items-center justify-center rounded-lg sm:size-11 sm:rounded-xl', t.tone)}><t.icon className="size-4 sm:size-5" /></span>
            <span className="flex flex-col">
              <span className="text-xl leading-none font-semibold tabular-nums sm:text-3xl">{isLoading ? '–' : t.value}</span>
              <span className="text-xs leading-tight text-muted-foreground sm:text-sm sm:text-foreground/80">{t.label}</span>
            </span>
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div role="tablist" aria-label="Status" className="flex max-w-full gap-0.5 overflow-x-auto rounded-xl bg-muted p-1">
          {TABS.map((t) => {
            const on = tab === t.value
            const n = filtered.filter((r) => inTab(r, t.value)).length
            return (
              <button key={t.value} role="tab" type="button" aria-selected={on} onClick={() => setTab(t.value)} className={cn('inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-3 text-sm whitespace-nowrap', on ? 'bg-background font-semibold shadow-sm' : 'text-foreground/75 hover:text-foreground')}>
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
            <span className="sr-only">Search returns</span>
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="DN, item, supplier" className="w-28 bg-transparent text-sm outline-none sm:w-36" />
          </label>
        </div>
      </div>

      <div className="flex flex-col items-start gap-5 lg:flex-row">
        <section aria-label="Returns" className="w-full min-w-0 flex-1 overflow-hidden rounded-xl border lg:max-w-[440px]">
          {isLoading && <div className="flex flex-col">{[0, 1, 2].map((i) => <div key={i} className="h-20 animate-pulse border-b bg-muted/40" />)}</div>}
          {isError && <p className="p-6 text-sm text-destructive">Returns did not load. Refresh to try again.</p>}
          {!isLoading && !isError && list.length === 0 && (
            <div className="flex flex-col items-center gap-2 px-4 py-12 text-center text-sm text-muted-foreground">
              <PackageX className="size-8 opacity-40" />
              {all.length === 0 ? (
                <><strong className="text-foreground">Don't pay for bent steel.</strong>When material is bad, start a return from the GRN, the delivery in Movements or the supplier's page, or say it on WhatsApp ("12 bars bent, returning to KSL"). The debit note lowers what you owe them.</>
              ) : 'No returns here with these filters.'}
            </div>
          )}
          {list.map((r) => <ReturnRow key={r.id} ret={r} money={money} selected={current?.id === r.id} onPick={() => setSelected(r.id)} />)}
        </section>
        {!isMobile && current && (
          <aside aria-label="Return detail" className="sticky top-4 w-full min-w-0 flex-[1.4] overflow-hidden rounded-xl border"><ReturnDetail key={current.id} ret={current} /></aside>
        )}
      </div>

      {isMobile && (
        <Sheet open={!!current} onOpenChange={(o) => !o && setSelected('')}>
          <SheetContent side="bottom" className="max-h-[92vh] gap-0 overflow-y-auto rounded-t-2xl p-0">
            <SheetTitle className="sr-only">{current ? `${current.ref} return` : 'Return'}</SheetTitle>
            {current && <ReturnDetail key={current.id} ret={current} inSheet />}
          </SheetContent>
        </Sheet>
      )}
    </div>
  )
}

function ReturnRow({ ret: r, money, selected, onPick }: { ret: MaterialReturn; money: boolean; selected: boolean; onPick: () => void }) {
  const first = r.lines[0]
  const more = r.lines.length - 1
  const look = RETURN_LOOK[r.status]
  return (
    <button type="button" onClick={onPick} aria-current={selected || undefined} className={cn('flex w-full gap-3 border-b px-3 py-3 text-left transition hover:bg-muted/40 sm:px-4', selected && 'bg-yellow-50 shadow-[inset_0_0_0_2px_theme(colors.yellow.300)] dark:bg-yellow-950/40', r.status === 'cancelled' && 'opacity-60')}>
      {first && <CategoryTile mainCategory={first.main_category} />}
      <span className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="flex items-center justify-between gap-2">
          <span className="min-w-0 truncate font-semibold">{first?.material}{more > 0 && <span className="ml-1.5 rounded-full bg-muted px-1.5 text-xs font-semibold">+{more}</span>}</span>
          <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{r.ref}</span>
        </span>
        <span className="truncate text-sm text-muted-foreground">{first ? `${qty(first.quantity)} ${first.unit} · ${first.reason_label.toLowerCase()}` : ''} · to {r.vendor_name}</span>
        <span className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1"><ProjectDot id={r.project_id} />{r.site_name}</span>
          {money && r.total && <strong className="text-foreground tabular-nums">{rupees(r.total)}</strong>}
          <span className={cn('ml-auto inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-semibold', look.chip)}><span className={cn('size-1.5 rounded-full', look.dot)} />{look.label}</span>
        </span>
      </span>
    </button>
  )
}

function qty(v: string): string {
  return Number(v).toLocaleString('en-IN', { maximumFractionDigits: 3 })
}
