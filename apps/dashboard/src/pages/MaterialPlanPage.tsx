import * as React from 'react'
import { MONEY_PEOPLE } from '@/lib/permissions'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { LucideIcon } from 'lucide-react'
import {
  AlarmClock, Calculator, CalendarClock, CalendarOff, ChevronDown, ChevronRight, CircleCheck, ClipboardList, Clock, PackageCheck,
  PackageSearch, Ruler, Search, ShoppingCart, Truck, Wand2, X,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Callout, EmptyState, KpiStrip, Legend, NoAccess, PageError, Segmented, type KpiItem } from '@/components/page/page-kit'
import { ModuleHeader } from '@/components/page/module-header'
import { NewOrderDialog, type OrderPrefill } from '@/components/orders/new-order-dialog'
import { ProjectPickList, usePlanningProject } from '@/components/schedule/project-picker'
import { useAuth } from '@/lib/AuthContext'
import { applyStandardNorms, fetchStandardNorms, maySeeBoq } from '@/lib/boq'
import { fetchMaterialPlan, type MaterialPlan, type MaterialPlanRow } from '@/lib/material-plan'
import { usePageTitle } from '@/lib/page-title'
import { useUrlState } from '@/lib/url-state'
import { cn } from '@/lib/utils'

// MP-02: Planning › Material plan. What the project needs of each material, week by week: the BOQ's work still to
// do × the materials per unit (MP-01), over the schedule's dates, against what is in stock and on order. Red from
// the week it runs short. Nothing is typed here: site's work updates shrink the need, the schedule moves it.
// MP-03: the day to order by (the day it runs short less the supplier's delivery time), and an Order button that
// opens the purchase order form filled in.
// UX-46 (18 Nov): it reads by urgency, by colour and icon, not by sentences (docs/DESIGN.md "Cues, not words"). Four
// groups (Order now red, This week amber, Later blue, Covered green), most urgent first; a KPI strip whose figures
// filter; "To order" cards on laptops; each row's cover as one bar; the weeks as a heatmap that turns red from the
// week it runs short; the name column stays put; Covered folds away; search ("/"). The full figures and reasons are
// tooltips; what the page means is in its Help (lib/page-help.ts). No API change.

const NUM = 'text-right tabular-nums'
const SOON_DAYS = 7

/** A planned quantity as a person orders it: whole units from 10 up, one decimal below. ``up`` rounds a shortfall up
 * (481.26 bags short is 482 to order). The API keeps the exact figures. */
function qty(value: string | number, up = false): string {
  const n = Number(value)
  if (Number.isNaN(n)) return String(value)
  if (Math.abs(n) >= 10) return (up ? Math.ceil(n) : Math.round(n)).toLocaleString('en-IN')
  return (up ? Math.ceil(n * 10) / 10 : Math.round(n * 10) / 10).toLocaleString('en-IN')
}

function dayLabel(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
}

function daysBetween(from: string, to: string): number {
  return Math.round((new Date(`${to}T00:00:00`).getTime() - new Date(`${from}T00:00:00`).getTime()) / 86_400_000)
}

// ---- Urgency: the one thing the page is sorted and coloured by -------------------------------------------------

type Urgency = 'now' | 'soon' | 'later' | 'covered'
const URGENCY_ORDER: Urgency[] = ['now', 'soon', 'later', 'covered']

const URGENCY: Record<Urgency, { label: string; icon: LucideIcon; pill: string; edge: string; dot: string; text: string }> = {
  now: { label: 'Order now', icon: AlarmClock, pill: 'bg-destructive/10 text-destructive', edge: 'before:bg-destructive', dot: 'bg-destructive', text: 'text-destructive' },
  soon: { label: 'This week', icon: CalendarClock, pill: 'bg-draft-soft text-draft', edge: 'before:bg-draft', dot: 'bg-draft', text: 'text-draft' },
  later: { label: 'Later', icon: Clock, pill: 'bg-info-soft text-info', edge: 'before:bg-info', dot: 'bg-info', text: 'text-info' },
  covered: { label: 'Covered', icon: CircleCheck, pill: 'bg-success-soft text-success', edge: 'before:bg-success', dot: 'bg-success', text: 'text-success' },
}

function urgencyOf(row: MaterialPlanRow, today: string): Urgency {
  if (!row.order_by) return 'covered'
  if (row.order_now) return 'now'
  return daysBetween(today, row.order_by) <= SOON_DAYS ? 'soon' : 'later'
}

/** The order-by day in two or three words: "Today", "24 Nov · 6d". The full sentence is its tooltip. */
function byText(row: MaterialPlanRow, today: string): string {
  if (!row.order_by) return ''
  if (row.order_now) return 'Today'
  return `${dayLabel(row.order_by)} · ${daysBetween(today, row.order_by)}d`
}

function byTitle(row: MaterialPlanRow): string {
  if (!row.order_by) return ''
  const short = row.short_day ? `Runs short ${dayLabel(row.short_day)}. ` : ''
  return `${short}Order by ${dayLabel(row.order_by)}.`
}

function leadTitle(row: MaterialPlanRow): string {
  return row.supplier && row.lead_known ? `${row.supplier}: ${row.lead_days} days to deliver` : `${row.lead_days} days to deliver (assumed)`
}

function orderPrefill(projectId: string, row: MaterialPlanRow): OrderPrefill {
  return {
    project_id: projectId,
    site_id: row.lines.find((l) => l.site_id)?.site_id ?? '',
    lines: [{ material_id: row.material_id, quantity: String(Math.ceil(Number(row.short_by))) }],
    vendor_name: row.supplier ?? undefined,
  }
}

function UrgencyPill({ u }: { u: Urgency }) {
  const look = URGENCY[u]
  const Icon = look.icon
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap', look.pill)}>
      <Icon className="size-3" aria-hidden /> {look.label}
    </span>
  )
}

/** Order-by day and delivery time as two small icon chips. */
function When({ row, today, u }: { row: MaterialPlanRow; today: string; u: Urgency }) {
  if (!row.order_by) return null
  return (
    <span className="flex flex-wrap items-center gap-1.5 text-xs">
      <span className={cn('inline-flex items-center gap-1 font-semibold', URGENCY[u].text)} title={byTitle(row)}>
        <CalendarClock className="size-3.5" aria-hidden /> {byText(row, today)}
      </span>
      <span className="inline-flex items-center gap-1 text-muted-foreground" title={leadTitle(row)}>
        <Truck className="size-3.5" aria-hidden /> {row.lead_days}d{!row.lead_known && '?'}
      </span>
    </span>
  )
}

function OrderButton({ u, row, onOrder, className }: { u: Urgency; row: MaterialPlanRow; onOrder: (row: MaterialPlanRow) => void; className?: string }) {
  return (
    <Button size="sm" variant={u === 'now' ? 'default' : 'outline'} className={cn('gap-1', className)} onClick={() => onOrder(row)}>
      <ShoppingCart className="size-3.5" /> Order
    </Button>
  )
}

// ---- Page ------------------------------------------------------------------------------------------------------

function Heading({ controls }: { controls?: React.ReactNode }) {
  return <ModuleHeader icon={PackageSearch} title="Material plan">{controls}</ModuleHeader>
}

export default function MaterialPlanPage() {
  usePageTitle('Material plan')
  const projectId = usePlanningProject()
  const { me } = useAuth()
  if (!maySeeBoq(me?.role)) {
    return (
      <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
        <Heading />
        <NoAccess roles={MONEY_PEOPLE} />
      </div>
    )
  }
  if (!projectId) {
    return (
      <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
        <Heading />
        <ProjectPickList to={(id) => `/planning/materials?project=${id}`} empty="No projects yet. Add one in Projects & Sites." />
      </div>
    )
  }
  return <PlanView key={projectId} projectId={projectId} />
}

type Row = MaterialPlanRow & { u: Urgency }
type Filter = '' | Urgency

function PlanView({ projectId }: { projectId: string }) {
  const [weeksRaw, setWeeks] = useUrlState<string>('weeks', '8')
  const weeks = [4, 8, 12].includes(Number(weeksRaw)) ? Number(weeksRaw) : 8
  const [filter, setFilter] = useUrlState<Filter>('show', '')
  const [search, setSearch] = useUrlState<string>('q', '')
  const [ordering, setOrdering] = React.useState<OrderPrefill | null>(null)
  const order = (row: MaterialPlanRow) => setOrdering(orderPrefill(projectId, row))
  const query = useQuery<MaterialPlan>({ queryKey: ['material-plan', projectId, weeks], queryFn: () => fetchMaterialPlan(projectId, weeks) })
  const boqLink = `/projects/${projectId}/boq`
  // BOQ-04: the usual materials for the lines with none yet, put on in one tap (each stays editable on the BOQ).
  const qc = useQueryClient()
  const standard = useQuery({ queryKey: ['boq-standard-norms', projectId], queryFn: () => fetchStandardNorms(projectId) })
  const fill = useMutation({
    mutationFn: () => applyStandardNorms(projectId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['material-plan', projectId] })
      void qc.invalidateQueries({ queryKey: ['boq-standard-norms', projectId] })
    },
  })
  const searchRef = React.useRef<HTMLInputElement>(null)
  // "/" jumps to the search, as on Materials vs BOQ (never while typing in a field).
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey || t?.closest('input, textarea, select, [contenteditable="true"]')) return
      e.preventDefault()
      searchRef.current?.focus()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const plan = query.data
  const rows: Row[] = React.useMemo(() => {
    if (!plan) return []
    const out = plan.materials.map((m) => ({ ...m, u: urgencyOf(m, plan.today) }))
    // Most urgent first; within a group, the earliest order-by day, then the name.
    return out.sort(
      (a, b) =>
        URGENCY_ORDER.indexOf(a.u) - URGENCY_ORDER.indexOf(b.u) ||
        (a.order_by ?? '9999').localeCompare(b.order_by ?? '9999') ||
        a.material.localeCompare(b.material),
    )
  }, [plan])
  const needle = search.trim().toLowerCase()
  const shown = rows.filter((r) => (!filter || r.u === filter) && (!needle || r.material.toLowerCase().includes(needle)))
  const count = (u: Urgency) => rows.filter((r) => r.u === u).length

  const fits = standard.data ?? []
  const fillCallout = fits.length > 0 ? (
    <Callout
      tone="info"
      icon={Wand2}
      action={<Button size="sm" className="gap-1.5" disabled={fill.isPending} onClick={() => fill.mutate()}><Wand2 className="size-3.5" /> {fill.isPending ? 'Filling…' : `Fill ${fits.length} line${fits.length > 1 ? 's' : ''}`}</Button>}
    >
      {fits.length} BOQ line{fits.length > 1 ? 's' : ''} with no materials
      {fill.isError ? ' · did not work, try again' : ''}
    </Callout>
  ) : null

  const controls = (
    <div className="flex flex-wrap items-center gap-2" data-guide="matplan.weeks">
      <Segmented<string>
        label="Weeks to look ahead"
        value={String(weeks)}
        options={[4, 8, 12].map((w) => ({ value: String(w), label: `${w} wk` }))}
        onChange={setWeeks}
      />
      <Button asChild variant="outline" size="sm" className="h-8 gap-1.5 bg-card"><Link to={boqLink}><Calculator className="size-3.5" /> BOQ</Link></Button>
    </div>
  )

  if (query.isError) return <PageError message="The material plan did not load." onRetry={() => query.refetch()} back={{ to: '/planning/materials', label: 'All projects' }} />

  const total = plan ? plan.lines_with_norms + plan.lines_without_norms : 0
  const tap = (u: Urgency) => ({ onClick: () => setFilter(filter === u ? '' : u), pressed: filter === u })
  const stats: KpiItem[] = plan
    ? [
        { label: 'Order now', icon: AlarmClock, value: count('now'), tone: count('now') ? 'bad' : 'good', ...tap('now') },
        { label: 'This week', icon: CalendarClock, value: count('soon'), tone: count('soon') ? 'attention' : 'good', ...tap('soon') },
        { label: 'Later', icon: Clock, value: count('later'), tone: count('later') ? 'info' : 'default', ...tap('later') },
        { label: 'Covered', icon: PackageCheck, value: count('covered'), of: rows.length || undefined, tone: 'good', ...tap('covered') },
        { label: 'BOQ lines ready', icon: ClipboardList, value: plan.lines_with_norms, of: total || undefined, tone: plan.lines_without_norms ? 'attention' : 'good', to: boqLink },
      ]
    : []
  const due = rows.filter((r) => r.u === 'now' || r.u === 'soon')
  // Covered folds away only when something else is listed; alone, it is the whole table.
  const allCovered = filter === 'covered' || !!needle || shown.every((r) => r.u === 'covered')

  return (
    <div className="mx-auto flex w-full min-w-0 flex-col gap-4 pb-8 sm:px-2">
      <Heading controls={controls} />
      {!plan ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-20 rounded-xl" />
          <Skeleton className="h-64 rounded-xl" />
        </div>
      ) : plan.lines_with_norms === 0 ? (
        <div data-guide="matplan.empty">
          {fillCallout ?? (
            <EmptyState icon={Calculator} title="No BOQ line has its materials yet" action={<Button asChild size="sm"><Link to={boqLink}>Open the BOQ</Link></Button>} />
          )}
        </div>
      ) : (
        <>
          <KpiStrip stats={stats} guide="matplan.stats" />
          {fillCallout}
          {due.length > 0 && <ToOrder rows={due} today={plan.today} onOrder={order} />}

          <section className="flex flex-col gap-2" data-guide="matplan.table">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="flex items-center gap-2 text-[15px] font-semibold">
                <span aria-hidden className="h-4 w-1 shrink-0 rounded-full bg-primary" />
                Week by week
                <span className="text-xs font-normal text-muted-foreground tabular-nums">{filter || needle ? `${shown.length} of ${rows.length}` : rows.length}</span>
              </h2>
              <div className="ml-auto flex flex-wrap items-center gap-2">
                <Legend items={[{ tone: 'good', label: 'In stock' }, { tone: 'info', label: 'On order' }, { tone: 'bad', label: 'Short' }]} className="mr-2 hidden lg:flex" />
                {filter && (
                  <button type="button" onClick={() => setFilter('')} className={cn('inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold ring-2 ring-foreground/70', URGENCY[filter].pill)}>
                    {URGENCY[filter].label} <X className="size-3" aria-label="Show all" />
                  </button>
                )}
                <label className="flex h-8 items-center gap-2 rounded-lg border bg-card px-2.5">
                  <Search className="size-3.5 text-muted-foreground" aria-hidden />
                  <span className="sr-only">Search materials</span>
                  <input
                    ref={searchRef}
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    onKeyDown={(e) => e.key === 'Escape' && setSearch('')}
                    placeholder="Search"
                    className="w-28 bg-transparent text-sm outline-none"
                  />
                  <kbd className="hidden rounded border bg-muted px-1 text-[10px] text-muted-foreground sm:inline" title="Press / to search">/</kbd>
                </label>
              </div>
            </div>
            {shown.length === 0 ? (
              <EmptyState icon={Search} title="No material matches" action={<Button variant="outline" size="sm" onClick={() => { setFilter(''); setSearch('') }}>Show all</Button>} />
            ) : (
              <>
                <PlanTable plan={plan} rows={shown} onOrder={order} openCovered={allCovered} />
                <PlanCards plan={plan} rows={shown} onOrder={order} openCovered={allCovered} />
              </>
            )}
          </section>

          {plan.lines_without_norms > 0 && (
            <Link to={boqLink} className="group flex items-center gap-2.5 rounded-xl border bg-card px-3 py-2 transition-colors hover:bg-muted/40">
              <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-draft-soft text-draft" aria-hidden><ClipboardList className="size-3.5" /></span>
              <span className="min-w-0 flex-1 text-sm">
                <span className="font-semibold tabular-nums">{plan.lines_without_norms}</span> BOQ {plan.lines_without_norms === 1 ? 'line' : 'lines'} not in the plan
              </span>
              <span className="inline-flex shrink-0 items-center gap-1 text-xs font-semibold">Set materials <ChevronRight className="size-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden /></span>
            </Link>
          )}
        </>
      )}
      <NewOrderDialog open={!!ordering} onOpenChange={(o) => !o && setOrdering(null)} scope={{ mode: 'portfolio' }} prefill={ordering} />
    </div>
  )
}

// ---- To order: the materials to act on now, one card each (laptops; on a phone the cards below lead with them) ----

function ToOrder({ rows, today, onOrder }: { rows: Row[]; today: string; onOrder: (row: MaterialPlanRow) => void }) {
  return (
    <section className="hidden flex-col gap-2 md:flex" data-guide="matplan.toorder" aria-label="To order">
      <h2 className="flex items-center gap-2 text-[15px] font-semibold">
        <ShoppingCart className="size-4 text-destructive" aria-hidden /> To order
        <span className="text-xs font-normal text-muted-foreground tabular-nums">{rows.length}</span>
      </h2>
      <ul className="grid grid-cols-2 gap-2 xl:grid-cols-3">
        {rows.map((r) => (
          <li
            key={r.material_id}
            className={cn(
              "relative flex items-center justify-between gap-3 overflow-hidden rounded-xl border bg-card p-3 pl-4 before:absolute before:inset-y-0 before:left-0 before:w-1 before:content-['']",
              URGENCY[r.u].edge,
            )}
          >
            <div className="flex min-w-0 flex-col gap-1">
              <p className="truncate font-semibold">{r.material}</p>
              <p className="tabular-nums" title={`${qty(r.short_by, true)} ${r.unit} short`}>
                <span className="text-xl font-semibold">{qty(r.short_by, true)}</span> <span className="text-sm text-muted-foreground">{r.unit}</span>
              </p>
              <When row={r} today={today} u={r.u} />
            </div>
            <OrderButton u={r.u} row={r} onOrder={onOrder} className="h-8 shrink-0" />
          </li>
        ))}
      </ul>
    </section>
  )
}

// ---- Cover bar, week heatmap, flags --------------------------------------------------------------------------------

/** What the work still needs, as one bar: in stock (green), on order (blue), not covered (red). Figures on hover. */
function CoverBar({ row }: { row: MaterialPlanRow }) {
  const still = Number(row.still_needed)
  if (!(still > 0)) return <PackageCheck className="size-4 text-success" aria-label="Nothing left to need" />
  const hand = row.stock_unit_differs ? 0 : Math.min(Math.max(0, Number(row.on_hand)), still)
  const ordered = Math.min(Math.max(0, Number(row.on_order)), still - hand)
  const gap = Math.max(0, still - hand - ordered)
  const w = (v: number) => `${(v / still) * 100}%`
  const pct = Math.round(((hand + ordered) / still) * 100)
  const label = `Needs ${qty(still)} ${row.unit}: ${qty(hand)} in stock, ${qty(ordered)} on order, ${qty(gap, true)} not covered`
  return (
    <span className="flex w-full min-w-32 items-center gap-2" title={label}>
      <span className="flex h-2 flex-1 overflow-hidden rounded-full bg-muted" role="img" aria-label={label}>
        {hand > 0 && <span className="bg-success" style={{ width: w(hand) }} />}
        {ordered > 0 && <span className="bg-info" style={{ width: w(ordered) }} />}
        {gap > 0 && <span className="bg-destructive/80" style={{ width: w(gap) }} />}
      </span>
      <span className={cn('w-9 shrink-0 text-right text-xs font-semibold tabular-nums', pct >= 100 ? 'text-success' : pct < 50 ? 'text-destructive' : 'text-muted-foreground')}>{pct}%</span>
    </span>
  )
}

const HEAT = ['bg-info/5', 'bg-info/10', 'bg-info/15', 'bg-info/25']
const HEAT_SHORT = ['bg-destructive/[0.07]', 'bg-destructive/10', 'bg-destructive/15', 'bg-destructive/20']

function heatLevel(v: number, max: number): number {
  if (max <= 0) return 0
  return Math.min(3, Math.floor((v / max) * 4 - 0.0001))
}

/** One week: darker is more; red from the week it runs short; a dash when nothing is needed. */
function WeekCell({ row, week, value, max }: { row: MaterialPlanRow; week: string; value: string; max: number }) {
  const v = Number(value)
  if (!(v > 0)) return <td className={cn('px-2 py-2 text-muted-foreground/60', NUM)}>—</td>
  const short = row.short_from !== null && week >= row.short_from
  const starts = short && week === row.short_from
  return (
    <td
      className={cn(
        'px-2 py-2', NUM,
        short ? cn(HEAT_SHORT[heatLevel(v, max)], 'font-semibold text-destructive') : HEAT[heatLevel(v, max)],
        starts && 'shadow-[inset_3px_0_0_0_var(--destructive)]',
      )}
      title={starts ? `Runs short${row.short_day ? ` ${dayLabel(row.short_day)}` : ''}` : undefined}
    >
      {qty(value)}
    </td>
  )
}

/** What else to know about a material, as small icon chips; the full reason is the tooltip. */
function Flags({ row }: { row: MaterialPlanRow }) {
  const flags: { icon: LucideIcon; text: string; title: string; warn?: boolean }[] = []
  if (row.lines.some((l) => l.late)) flags.push({ icon: AlarmClock, text: 'Late work', title: 'Late work needs it now', warn: true })
  if (row.stock_unit_differs) flags.push({ icon: Ruler, text: 'Other unit', title: 'Stock is held in another unit, not counted', warn: true })
  if (Number(row.unscheduled) > 0) flags.push({ icon: CalendarOff, text: `${qty(row.unscheduled)} undated`, title: `${qty(row.unscheduled)} ${row.unit} for work with no dates` })
  if (Number(row.later) > 0) flags.push({ icon: Clock, text: `${qty(row.later)} later`, title: `${qty(row.later)} ${row.unit} after these weeks` })
  if (!flags.length) return null
  return (
    <span className="mt-1 flex flex-wrap gap-1">
      {flags.map((f) => (
        <span key={f.text} title={f.title} className={cn('inline-flex items-center gap-1 rounded px-1.5 py-px text-[10.5px] font-medium', f.warn ? 'bg-draft-soft text-draft' : 'bg-muted text-muted-foreground')}>
          <f.icon className="size-3" aria-hidden /> {f.text}
        </span>
      ))}
    </span>
  )
}

const linesTitle = (row: MaterialPlanRow) => row.lines.map((l) => `${l.work}: ${qty(l.need)}`).join('\n') || 'BOQ work done'

// ---- Table (laptop) and cards (phone) -----------------------------------------------------------------------------

function useCoveredOpen(force: boolean): [boolean, () => void] {
  const [open, setOpen] = React.useState(false)
  return [open || force, () => setOpen((o) => !o)]
}

function GroupLabel({ u, n, folded }: { u: Urgency; n: number; folded?: boolean }) {
  const look = URGENCY[u]
  return (
    <span className="inline-flex items-center gap-2 text-xs font-semibold">
      {folded !== undefined && (folded ? <ChevronRight className="size-3.5" aria-hidden /> : <ChevronDown className="size-3.5" aria-hidden />)}
      <span className={cn('size-2 rounded-full', look.dot)} aria-hidden />
      <span className={look.text}>{look.label}</span>
      <span className="font-normal text-muted-foreground tabular-nums">{n}</span>
    </span>
  )
}

function PlanTable({ plan, rows, onOrder, openCovered }: { plan: MaterialPlan; rows: Row[]; onOrder: (row: MaterialPlanRow) => void; openCovered: boolean }) {
  const [coveredOpen, toggleCovered] = useCoveredOpen(openCovered)
  const groups = URGENCY_ORDER.map((u) => ({ u, rows: rows.filter((r) => r.u === u) })).filter((g) => g.rows.length)
  const cols = 4 + plan.weeks.length
  const sticky = 'sticky left-0 z-10 bg-card'
  return (
    <div className="hidden overflow-x-auto rounded-xl border bg-card [contain:inline-size] md:block">
      <table className="w-full text-sm">
        <thead className="text-xs text-muted-foreground">
          <tr className="border-b bg-muted/40">
            <th className={cn('min-w-48 px-3 py-2 text-left font-medium', sticky, 'bg-muted')}>Material</th>
            <th className="min-w-40 px-3 py-2 text-left font-medium">Covered</th>
            <th className={cn('px-2 py-2 font-medium whitespace-nowrap', NUM)} title="In stock / on order">Stock / ordered</th>
            <th className="min-w-36 px-3 py-2 text-left font-medium">Order</th>
            {plan.weeks.map((w, i) => (
              <th key={w} className={cn('px-2 py-2 font-medium whitespace-nowrap', NUM, i === 0 && 'bg-primary/10 text-foreground')}>
                {i === 0 ? 'This week' : dayLabel(w)}
              </th>
            ))}
          </tr>
        </thead>
        {groups.map(({ u, rows: gr }) => {
          const look = URGENCY[u]
          const folded = u === 'covered' && !coveredOpen
          return (
            <tbody key={u} className="divide-y border-b last:border-b-0">
              <tr className={cn('bg-muted/25', u === 'covered' && 'cursor-pointer hover:bg-muted/50')} onClick={u === 'covered' ? toggleCovered : undefined} aria-expanded={u === 'covered' ? !folded : undefined}>
                <td colSpan={cols} className="px-3 py-1.5">
                  <span className="sticky left-3"><GroupLabel u={u} n={gr.length} folded={u === 'covered' ? folded : undefined} /></span>
                </td>
              </tr>
              {!folded &&
                gr.map((row) => {
                  const max = Math.max(0, ...row.weeks.map(Number))
                  return (
                    <tr key={row.material_id} className="group align-top hover:bg-muted/20">
                      <td className={cn("relative px-3 py-2 before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:content-['']", sticky, look.edge, 'group-hover:bg-muted')} title={linesTitle(row)}>
                        <span className="font-medium">{row.material}</span> <span className="text-xs text-muted-foreground">{row.unit}</span>
                        <Flags row={row} />
                      </td>
                      <td className="px-3 py-2.5"><CoverBar row={row} /></td>
                      <td className={cn('px-2 py-2 whitespace-nowrap', NUM)}>
                        <span className="text-success">{qty(row.on_hand)}</span>
                        <span className="text-muted-foreground"> / </span>
                        <span className={Number(row.on_order) ? 'text-info' : 'text-muted-foreground'}>{Number(row.on_order) ? qty(row.on_order) : '—'}</span>
                      </td>
                      <td className="px-3 py-2">
                        {row.order_by ? (
                          <div className="flex flex-col items-start gap-1">
                            <span className="text-sm font-semibold tabular-nums">{qty(row.short_by, true)} <span className="text-xs font-normal text-muted-foreground">{row.unit}</span></span>
                            <When row={row} today={plan.today} u={u} />
                            <OrderButton u={u} row={row} onOrder={onOrder} className="mt-0.5 h-7 px-2 text-xs" />
                          </div>
                        ) : (
                          <UrgencyPill u={u} />
                        )}
                      </td>
                      {plan.weeks.map((w, i) => <WeekCell key={w} row={row} week={w} value={row.weeks[i]} max={max} />)}
                    </tr>
                  )
                })}
            </tbody>
          )
        })}
      </table>
    </div>
  )
}

function PlanCards({ plan, rows, onOrder, openCovered }: { plan: MaterialPlan; rows: Row[]; onOrder: (row: MaterialPlanRow) => void; openCovered: boolean }) {
  const [coveredOpen, toggleCovered] = useCoveredOpen(openCovered)
  const groups = URGENCY_ORDER.map((u) => ({ u, rows: rows.filter((r) => r.u === u) })).filter((g) => g.rows.length)
  return (
    <div className="flex flex-col gap-3 md:hidden">
      {groups.map(({ u, rows: gr }) => {
        const look = URGENCY[u]
        const folded = u === 'covered' && !coveredOpen
        return (
          <div key={u} className="flex flex-col gap-2">
            <button type="button" disabled={u !== 'covered'} onClick={toggleCovered} aria-expanded={u === 'covered' ? !folded : undefined} className="text-left disabled:cursor-default">
              <GroupLabel u={u} n={gr.length} folded={u === 'covered' ? folded : undefined} />
            </button>
            {!folded && (
              <ul className="flex flex-col gap-2">
                {gr.map((row) => {
                  const next = plan.weeks.map((w, i) => ({ w, v: row.weeks[i] })).filter((x) => Number(x.v) > 0).slice(0, 3)
                  return (
                    <li key={row.material_id} className={cn("relative flex flex-col gap-2 overflow-hidden rounded-xl border bg-card p-3 pl-4 before:absolute before:inset-y-0 before:left-0 before:w-1 before:content-['']", look.edge)}>
                      <div className="flex items-start justify-between gap-2">
                        <p className="min-w-0 font-semibold" title={linesTitle(row)}>{row.material} <span className="text-xs font-normal text-muted-foreground">{row.unit}</span></p>
                        {row.order_by ? (
                          <span className="shrink-0 text-lg leading-none font-semibold tabular-nums">{qty(row.short_by, true)} <span className="text-xs font-normal text-muted-foreground">{row.unit}</span></span>
                        ) : (
                          <UrgencyPill u={u} />
                        )}
                      </div>
                      <CoverBar row={row} />
                      {next.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {next.map((x) => {
                            const short = row.short_from !== null && x.w >= row.short_from
                            return (
                              <span key={x.w} className={cn('rounded px-1.5 py-0.5 text-[11px] tabular-nums', short ? 'bg-destructive/10 font-semibold text-destructive' : 'bg-info-soft text-info')}>
                                {x.w === plan.weeks[0] ? 'This wk' : dayLabel(x.w)}: {qty(x.v)}
                              </span>
                            )
                          })}
                        </div>
                      )}
                      <Flags row={row} />
                      {row.order_by && (
                        <div className="flex items-center justify-between gap-2 border-t pt-2">
                          <When row={row} today={plan.today} u={u} />
                          <OrderButton u={u} row={row} onOrder={onOrder} className="h-8 shrink-0" />
                        </div>
                      )}
                    </li>
                  )
                })}
              </ul>
            )}
          </div>
        )
      })}
    </div>
  )
}
