import * as React from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CircleOff, ClipboardPen, Construction, Download, LayoutGrid, MapPin, Plus, Search, Store, Truck, Wrench, type LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { FilterPill, type FilterOption } from '@/components/requests/parts'
import { DayBar, FuelFigure, Legend, MachineAvatar, OwnershipChip, ServiceChip, Spark, StateChip } from '@/components/equipment/parts'
import { MachinePanel } from '@/components/equipment/machine-panel'
import { MachineDialog } from '@/components/equipment/machine-dialog'
import { useScope } from '@/lib/ScopeContext'
import { useAuth } from '@/lib/AuthContext'
import { usePageTitle } from '@/lib/page-title'
import { useUrlState } from '@/lib/url-state'
import { useReadOnly } from '@/lib/trial'
import { useIsMobile } from '@/hooks/use-mobile'
import { exportCsv } from '@/lib/export'
import { swatch } from '@/lib/requests'
import { cn } from '@/lib/utils'
import { STATE_LOOK, fetchMachines, hrs, type Kind, type Machine, type MachineState, inr } from '@/lib/equipment'

// NXT-11 / NXT-15: Equipment > Machines (and Vehicles, the same page for kind=vehicle), in the Purchase orders page's
// visual language: tiles for what needs attention today, tabs, filter pills, the list beside the chosen machine (a
// sheet on a phone). Broken down and not logged first: what the site still has to tell.

type Tab = 'site' | 'off' | 'all'
type Tile = '' | 'working' | 'breakdown' | 'not_logged' | 'service'

const TABS: { value: Tab; label: string; dot: string }[] = [
  { value: 'site', label: 'On hire', dot: STATE_LOOK.working.dot },
  { value: 'off', label: 'Off hire', dot: STATE_LOOK.off_hire.dot },
  { value: 'all', label: 'All', dot: 'bg-muted-foreground/50' },
]
const ORDER: Record<MachineState, number> = { breakdown: 0, not_logged: 1, idle: 2, working: 3, no_site: 4, off_hire: 5, retired: 6 }

function inTab(m: Machine, tab: Tab): boolean {
  if (tab === 'site') return m.status === 'active'
  if (tab === 'off') return m.status !== 'active'
  return true
}
function inTile(m: Machine, tile: Tile): boolean {
  if (!tile) return true
  if (m.status !== 'active') return false
  if (tile === 'service') return !!m.service && m.service.status !== 'ok'
  return m.state === tile
}

function exportMachines(items: Machine[]): void {
  exportCsv(`machines-${new Date().toISOString().slice(0, 10)}.csv`,
    ['Ref', 'Name', 'Type', 'Kind', 'Owned / hired', 'Hire company', 'Rate', 'Per', 'Project', 'Site', 'State', 'Today worked', 'Today idle', 'Today breakdown',
      'Today diesel (L)', 'Month worked', 'Month idle', 'Month breakdown', 'Month diesel (L)', 'Month hire', 'Month diesel cost', 'Operator'],
    items.map((m) => [m.ref, m.name, m.type ?? '', m.kind, m.ownership, m.vendor_name ?? '', m.rate ?? '', m.rate_unit ?? '', m.project_name ?? '', m.site_name ?? '',
      STATE_LOOK[m.state].label, m.today?.worked_hours ?? '', m.today?.idle_hours ?? '', m.today?.breakdown_hours ?? '', m.today?.fuel_litres ?? '',
      Number(m.month.worked), Number(m.month.idle), Number(m.month.breakdown), Number(m.month.fuel_litres), m.month.hire_cost ?? '', m.month.fuel_cost ?? '', m.operator_name ?? '']))
}

export default function EquipmentPage({ kind = 'machine' }: { kind?: Kind }) {
  const vehicles = kind === 'vehicle'
  usePageTitle(vehicles ? 'Vehicles' : 'Machines')
  const { scope } = useScope()
  const { me } = useAuth()
  const readOnly = useReadOnly()
  const isMobile = useIsMobile()
  const projectId = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : null
  const siteScope = scope.mode === 'site' ? scope.siteId : null
  const role = (me?.role || '').toUpperCase()
  const seesMoney = ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE', 'PROJECT_MANAGER'].includes(role)

  const [tab, setTab] = useUrlState<Tab>('tab', 'site')
  const [tile, setTile] = useUrlState<Tile>('show', '')
  const [site, setSite] = useUrlState<string>('at', '')
  const [type, setType] = useUrlState<string>('type', '')
  const [owner, setOwner] = useUrlState<string>('owner', '')
  const [vendor, setVendor] = useUrlState<string>('from', '')
  const [selected, setSelected] = useUrlState<string>('id', '')
  const [search, setSearch] = React.useState('')
  const [adding, setAdding] = React.useState(false)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['equipment', 'machines', projectId, siteScope, kind],
    queryFn: () => fetchMachines({ project_id: projectId, site_id: siteScope, kind, status: 'current' }),
    refetchInterval: 60_000,
  })
  const all = React.useMemo(() => data?.items ?? [], [data])

  const pass = React.useCallback((m: Machine, skip?: string) => {
    if (skip !== 'site' && site && m.site_id !== site) return false
    if (skip !== 'type' && type && (m.type ?? '—') !== type) return false
    if (skip !== 'owner' && owner && m.ownership !== owner) return false
    if (skip !== 'vendor' && vendor && m.vendor_id !== vendor) return false
    if (search) {
      const q = search.toLowerCase()
      if (![m.name, m.ref, m.type, m.vendor_name, m.site_name, m.operator_name, m.registration_no].some((x) => (x ?? '').toLowerCase().includes(q))) return false
    }
    return true
  }, [site, type, owner, vendor, search])

  const filtered = React.useMemo(() => all.filter((m) => pass(m)), [all, pass])
  const list = React.useMemo(() => filtered.filter((m) => (tile ? inTile(m, tile) : inTab(m, tab)))
    .sort((a, b) => ORDER[a.state] - ORDER[b.state] || (a.site_name ?? '').localeCompare(b.site_name ?? '') || a.name.localeCompare(b.name)), [filtered, tab, tile])
  const current = all.find((m) => m.id === selected) ?? (isMobile ? undefined : list[0])

  const options = React.useMemo(() => {
    const count = (skip: string, test: (m: Machine) => boolean) => all.filter((m) => pass(m, skip) && test(m)).length
    const uniq = <T,>(xs: T[], key: (t: T) => string) => [...new Map(xs.map((x) => [key(x), x])).values()]
    const sites: FilterOption[] = uniq(all.filter((m) => m.site_id), (m) => m.site_id!).map((m) => ({ value: m.site_id!, label: `${m.project_name} › ${m.site_name}`, swatch: swatch(m.project_id!), count: count('site', (x) => x.site_id === m.site_id) }))
    const types: FilterOption[] = [...new Set(all.map((m) => m.type ?? '—'))].sort().map((t) => ({ value: t, label: t === '—' ? 'No type' : t, count: count('type', (x) => (x.type ?? '—') === t) }))
    const owners: FilterOption[] = (['hired', 'owned'] as const).map((o) => ({ value: o, label: o === 'hired' ? 'Hired' : 'Our own', dot: o === 'hired' ? 'bg-teal-500' : 'bg-slate-400', count: count('owner', (x) => x.ownership === o) }))
    const vendors: FilterOption[] = uniq(all.filter((m) => m.vendor_id), (m) => m.vendor_id!).map((m) => ({ value: m.vendor_id!, label: m.vendor_name ?? '', swatch: swatch(m.vendor_id!), count: count('vendor', (x) => x.vendor_id === m.vendor_id) }))
    return { sites, types, owners, vendors }
  }, [all, pass])

  const live = filtered.filter((m) => m.status === 'active')
  const tiles: { value: Exclude<Tile, ''>; label: string; count: number; icon: LucideIcon; tone: string; ring: string; num?: string }[] = [
    { value: 'working', label: 'Working today', count: live.filter((m) => m.state === 'working').length, icon: Construction, tone: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100', ring: 'ring-emerald-500' },
    { value: 'breakdown', label: 'Broken down', count: live.filter((m) => m.state === 'breakdown').length, icon: AlertTriangle, tone: 'bg-destructive text-white', ring: 'ring-destructive', num: 'text-destructive' },
    { value: 'not_logged', label: 'Not logged today', count: live.filter((m) => m.state === 'not_logged').length, icon: ClipboardPen, tone: 'bg-orange-200 text-orange-950 dark:bg-orange-900 dark:text-orange-100', ring: 'ring-orange-500', num: 'text-orange-700 dark:text-orange-300' },
    { value: 'service', label: 'Service due', count: live.filter((m) => m.service && m.service.status !== 'ok').length, icon: Wrench, tone: 'bg-slate-200 text-slate-900 dark:bg-slate-800 dark:text-slate-100', ring: 'ring-slate-500' },
  ]
  const monthCost = seesMoney ? filtered.reduce((n, m) => n + Number(m.month.cost ?? 0), 0) : 0
  const todayHours = live.reduce((n, m) => n + Number(m.today?.worked_hours ?? 0), 0)
  const todayFuel = live.reduce((n, m) => n + Number(m.today?.fuel_litres ?? 0), 0)
  const Icon = vehicles ? Truck : Construction

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <header className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="inline-flex size-10 items-center justify-center rounded-xl bg-teal-100 text-teal-800 dark:bg-teal-950 dark:text-teal-200"><Icon className="size-5" /></span>
          <div>
            <div className="text-xs text-muted-foreground">Equipment</div>
            <h1 className="text-2xl leading-tight font-semibold tracking-tight">{vehicles ? 'Vehicles' : 'Machines'}</h1>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="hidden text-sm text-muted-foreground lg:inline">Today: <strong className="text-foreground tabular-nums">{hrs(String(todayHours))}</strong>{todayFuel ? <> · <strong className="text-foreground tabular-nums">{todayFuel} L</strong> diesel</> : null}</span>
          {monthCost > 0 && <span className="hidden text-sm text-muted-foreground sm:inline">This month: <strong className="text-foreground tabular-nums">{inr(monthCost)}</strong></span>}
          <Button variant="outline" className="gap-2" asChild><Link to="/equipment/log"><ClipboardPen className="size-4" /> <span className="hidden sm:inline">Daily log</span></Link></Button>
          <Button variant="outline" className="gap-2" disabled={!list.length} onClick={() => exportMachines(list)} title="The machines shown, as a CSV file (opens in Excel)"><Download className="size-4" /> <span className="hidden sm:inline">Export</span></Button>
          {!readOnly && <Button className="hidden gap-2 font-semibold md:inline-flex" onClick={() => setAdding(true)}><Plus className="size-4" strokeWidth={2.6} /> {vehicles ? 'Vehicle' : 'Machine'}</Button>}
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
            const n = filtered.filter((m) => inTab(m, t.value)).length
            return (
              <button key={t.value} role="tab" type="button" aria-selected={on} onClick={() => { setTile(''); setTab(t.value) }} className={cn('inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-3 text-sm whitespace-nowrap', on ? 'bg-background font-semibold shadow-sm' : 'text-foreground/75 hover:text-foreground')}>
                <span className={cn('size-2 rounded-full', t.dot)} />{t.label}
                <span className={cn('rounded-full px-1.5 text-[11px] font-semibold tabular-nums', on ? 'bg-foreground text-background' : 'bg-background/70')}>{n}</span>
              </button>
            )
          })}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!siteScope && <FilterPill icon={MapPin} label="Site" allLabel="All sites" value={site} options={options.sites} onChange={setSite} />}
          <FilterPill icon={LayoutGrid} label="Type" allLabel="Every type" value={type} options={options.types} onChange={setType} />
          <FilterPill icon={CircleOff} label="Owned / hired" allLabel="Owned and hired" value={owner} options={options.owners} onChange={setOwner} />
          {options.vendors.length > 0 && <FilterPill icon={Store} label="Hire company" allLabel="Every hire company" value={vendor} options={options.vendors} onChange={setVendor} />}
          <label className="flex h-9 items-center gap-2 rounded-lg border bg-background px-2.5">
            <Search className="size-4 text-muted-foreground" />
            <span className="sr-only">Search machines</span>
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Name, type, operator" className="w-28 bg-transparent text-sm outline-none sm:w-36" />
          </label>
        </div>
      </div>

      <div className="flex flex-col items-start gap-5 lg:flex-row">
        <section aria-label={vehicles ? 'Vehicles' : 'Machines'} className="w-full min-w-0 flex-1 overflow-hidden rounded-xl border">
          <div className="flex items-center justify-between border-b bg-muted/30 px-3 py-1.5 sm:px-4"><Legend /><span className="text-[11px] text-muted-foreground">last 14 days</span></div>
          {isLoading && <div className="flex flex-col">{[0, 1, 2].map((i) => <div key={i} className="h-20 animate-pulse border-b bg-muted/40" />)}</div>}
          {isError && <p className="p-6 text-sm text-destructive">Machines did not load. Refresh to try again.</p>}
          {!isLoading && !isError && list.length === 0 && (
            <div className="flex flex-col items-center gap-3 px-4 py-12 text-center text-sm text-muted-foreground">
              <Icon className="size-9 opacity-40" />
              {all.length === 0 ? (
                <>
                  <span className="max-w-sm">No {vehicles ? 'vehicles' : 'machines'} yet. Add the JCB, mixer or crane on each site, owned or hired, with its rate; then the site logs its day here or on WhatsApp: <em>"JCB 6 hrs, 2 hrs breakdown, 30 L diesel"</em>.</span>
                  {!readOnly && <Button className="gap-2" onClick={() => setAdding(true)}><Plus className="size-4" />Add the first one</Button>}
                </>
              ) : tile ? 'None right now.' : 'None here with these filters.'}
            </div>
          )}
          {list.map((m) => <MachineRow key={m.id} machine={m} selected={current?.id === m.id} onPick={() => setSelected(m.id)} seesMoney={seesMoney} />)}
        </section>
        {!isMobile && current && (
          <aside aria-label="Machine" className="sticky top-4 w-full shrink-0 overflow-hidden rounded-xl border lg:w-[440px]"><MachinePanel key={current.id} machine={current} /></aside>
        )}
      </div>

      {isMobile && (
        <Sheet open={!!current} onOpenChange={(o) => !o && setSelected('')}>
          <SheetContent side="bottom" className="max-h-[92vh] gap-0 overflow-y-auto rounded-t-2xl p-0">
            <SheetTitle className="sr-only">{current?.name ?? 'Machine'}</SheetTitle>
            {current && <MachinePanel machine={current} inSheet />}
          </SheetContent>
        </Sheet>
      )}
      {!readOnly && (
        <Button className="fixed right-4 bottom-5 z-30 h-12 gap-2 rounded-full px-5 font-semibold shadow-lg md:hidden" onClick={() => setAdding(true)}><Plus className="size-5" strokeWidth={2.6} /> {vehicles ? 'Vehicle' : 'Machine'}</Button>
      )}
      <MachineDialog open={adding} onOpenChange={setAdding} defaultKind={kind} defaultSiteId={siteScope ?? undefined} onSaved={(m) => setSelected(m.id)} />
    </div>
  )
}

function MachineRow({ machine: m, selected, onPick, seesMoney }: { machine: Machine; selected: boolean; onPick: () => void; seesMoney: boolean }) {
  const t = m.today
  return (
    <button type="button" onClick={onPick} aria-current={selected || undefined} className={cn('flex w-full gap-3 border-b px-3 py-3 text-left transition hover:bg-muted/40 sm:px-4', selected && 'bg-teal-50 shadow-[inset_0_0_0_2px_theme(colors.teal.300)] dark:bg-teal-950/40')}>
      <MachineAvatar machine={m} />
      <span className="flex min-w-0 flex-1 flex-col gap-1.5">
        <span className="flex items-center justify-between gap-2">
          <span className="min-w-0 truncate"><span className="font-semibold">{m.name}</span><span className="ml-2 text-xs text-muted-foreground">{m.type ?? m.ref}</span></span>
          <StateChip state={m.state} />
        </span>
        <span className="flex items-center gap-3">
          <span className="flex min-w-0 flex-1 flex-col gap-1">
            <DayBar worked={t?.worked_hours ?? null} idle={t?.idle_hours ?? null} breakdown={t?.breakdown_hours ?? null} />
            <span className="flex flex-wrap items-center gap-x-2.5 gap-y-0.5 text-xs text-muted-foreground">
              {t ? <span className="font-semibold text-foreground tabular-nums">{hrs(t.worked_hours)} today</span> : m.status === 'active' && m.site_id ? <span>not logged today</span> : null}
              {t && Number(t.breakdown_hours) > 0 && <span className="text-red-700 dark:text-red-300">{hrs(t.breakdown_hours)} broken{t.breakdown_reason ? `: ${t.breakdown_reason}` : ''}</span>}
              <FuelFigure litres={t?.fuel_litres} />
              {m.site_name && <span className="inline-flex items-center gap-1"><MapPin className="size-3" />{m.site_name}</span>}
            </span>
          </span>
          <Spark recent={m.recent} className="hidden w-28 sm:flex" />
        </span>
        <span className="flex flex-wrap items-center gap-1.5 text-xs">
          <OwnershipChip machine={m} />
          <ServiceChip service={m.service} />
          <span className="text-muted-foreground tabular-nums">month {hrs(m.month.worked)}{Number(m.month.fuel_litres) ? ` · ${Number(m.month.fuel_litres)} L` : ''}</span>
          {seesMoney && m.month.cost && Number(m.month.cost) > 0 && <span className="ml-auto font-semibold tabular-nums">{inr(m.month.cost)}</span>}
        </span>
      </span>
    </button>
  )
}
