import * as React from 'react'
import { MONEY_PEOPLE } from '@/lib/permissions'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { LucideIcon } from 'lucide-react'
import {
  AlarmClock, Calculator, CalendarClock, CalendarOff, ChevronDown, ChevronRight, CircleCheck, ClipboardList, Clock, PackageCheck,
  PackageSearch, Search, ShoppingCart, Truck, Wand2, X,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Callout, KpiStrip, Legend, ModuleTitle, NoAccess, PageError, Segmented, type KpiItem } from '@/components/page/page-kit'
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
// UX-45 (18 Nov, asked in session: "the material plan page is very mid"): it reads by urgency. Every material is in
// one of four groups (Order now red, This week amber, Later blue, Covered green), shown in that order, each with an
// icon so the colour is never the only cue; a header with the plan in one line; a KPI strip whose figures filter;
// a "To order" list with one Order button per material; each row's cover as one bar (in stock, on order, not
// covered); the weeks as a heatmap that turns red from the week it runs short; the name column stays put while the
// weeks scroll; Covered folds away; search ("/"). No API change: the groups come from order_now / order_by / today.

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

const URGENCY: Record<Urgency, { label: string; icon: LucideIcon; pill: string; edge: string; dot: string; text: string; tone: KpiItem['tone'] }> = {
  now: { label: 'Order now', icon: AlarmClock, pill: 'bg-destructive/10 text-destructive', edge: 'before:bg-destructive', dot: 'bg-destructive', text: 'text-destructive', tone: 'bad' },
  soon: { label: 'This week', icon: CalendarClock, pill: 'bg-draft-soft text-draft', edge: 'before:bg-draft', dot: 'bg-draft', text: 'text-draft', tone: 'attention' },
  later: { label: 'Later', icon: Clock, pill: 'bg-info-soft text-info', edge: 'before:bg-info', dot: 'bg-info', text: 'text-info', tone: 'info' },
  covered: { label: 'Covered', icon: CircleCheck, pill: 'bg-success-soft text-success', edge: 'before:bg-success', dot: 'bg-success', text: 'text-success', tone: 'good' },
}

function urgencyOf(row: MaterialPlanRow, today: string): Urgency {
  if (!row.order_by) return 'covered'
  if (row.order_now) return 'now'
  return daysBetween(today, row.order_by) <= SOON_DAYS ? 'soon' : 'later'
}

/** "Order by 24 Nov · in 5 days", in words a buyer reads. */
function whenText(row: MaterialPlanRow, today: string): string {
  if (!row.order_by) return 'Enough for these weeks'
  if (row.order_now) return daysBetween(row.order_by, today) > 0 ? `Order today · was due ${dayLabel(row.order_by)}` : 'Order today'
  const d = daysBetween(today, row.order_by)
  return `Order by ${dayLabel(row.order_by)} · in ${d} day${d === 1 ? '' : 's'}`
}

function leadText(row: MaterialPlanRow): string {
  return row.supplier && row.lead_known ? `${row.supplier} · ${row.lead_days} days to deliver` : `${row.lead_days} days to deliver (assumed)`
}

function orderPrefill(projectId: string, row: MaterialPlanRow): OrderPrefill {
  return {
    project_id: projectId,
    site_id: row.lines.find((l) => l.site_id)?.site_id ?? '',
    lines: [{ material_id: row.material_id, quantity: String(Math.ceil(Number(row.short_by))) }],
    vendor_name: row.supplier ?? undefined,
  }
}

function UrgencyPill({ u, className }: { u: Urgency; className?: string }) {
  const look = URGENCY[u]
  const Icon = look.icon
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap', look.pill, className)}>
      <Icon className="size-3" aria-hidden /> {look.label}
    </span>
  )
}

// ---- Page ------------------------------------------------------------------------------------------------------

function Heading({ summary, controls }: { summary?: React.ReactNode; controls?: React.ReactNode }) {
  return (
    <header className="relative overflow-hidden rounded-2xl border bg-gradient-to-br from-primary/10 via-card to-card px-4 py-3.5 sm:px-5 sm:py-4">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3">
        <div className="flex min-w-0 flex-col gap-1.5">
          <ModuleTitle icon={PackageSearch} title="Material plan" />
          {summary && <div className="text-sm text-muted-foreground sm:pl-[52px]">{summary}</div>}
        </div>
        {controls}
      </div>
    </header>
  )
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
        <Heading summary="Pick a project to see what it needs, and when." />
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
      {fits.length} BOQ line{fits.length > 1 ? 's' : ''} with no materials: Mesiri knows the usual ones.
      {fill.isError ? ' That did not work; try again.' : ''}
    </Callout>
  ) : null

  const controls = (
    <div className="flex flex-wrap items-center gap-2" data-guide="matplan.weeks">
      <span className="text-xs text-muted-foreground">Look ahead</span>
      <Segmented<string>
        label="Weeks to look ahead"
        value={String(weeks)}
        options={[4, 8, 12].map((w) => ({ value: String(w), label: `${w} weeks` }))}
        onChange={setWeeks}
      />
      <Button asChild variant="outline" size="sm" className="h-8 gap-1.5 bg-card"><Link to={boqLink}><Calculator className="size-3.5" /> BOQ</Link></Button>
    </div>
  )

  if (query.isError) return <PageError message="The material plan did not load." onRetry={() => query.refetch()} back={{ to: '/planning/materials', label: 'All projects' }} />

  const now = count('now')
  const soon = count('soon')
  const summary = !plan ? (
    'Working out what this project needs…'
  ) : plan.lines_with_norms === 0 ? (
    'No BOQ line has its materials yet, so there is nothing to plan.'
  ) : now + soon === 0 ? (
    <span className="inline-flex items-center gap-1.5"><CircleCheck className="size-4 text-success" aria-hidden /> Nothing to order in the next {weeks} weeks.</span>
  ) : (
    <span>
      {now > 0 && <><span className="font-semibold text-destructive">{now} to order today</span>{soon > 0 ? ' · ' : ''}</>}
      {soon > 0 && <span className="font-semibold text-draft">{soon} by the end of this week</span>}
      <span> · {rows.length} materials over the next {weeks} weeks</span>
    </span>
  )

  const total = plan ? plan.lines_with_norms + plan.lines_without_norms : 0
  const stats: KpiItem[] = plan
    ? [
        { label: 'Order now', icon: AlarmClock, value: now, tone: now ? 'bad' : 'good', hint: 'short before it can arrive', onClick: () => setFilter(filter === 'now' ? '' : 'now'), pressed: filter === 'now' },
        { label: 'Order this week', icon: CalendarClock, value: soon, tone: soon ? 'attention' : 'good', hint: `order-by in ${SOON_DAYS} days`, onClick: () => setFilter(filter === 'soon' ? '' : 'soon'), pressed: filter === 'soon' },
        { label: 'Later', icon: Clock, value: count('later'), tone: count('later') ? 'info' : 'default', hint: 'short later in these weeks', onClick: () => setFilter(filter === 'later' ? '' : 'later'), pressed: filter === 'later' },
        { label: 'Covered', icon: PackageCheck, value: count('covered'), of: rows.length || undefined, tone: 'good', onClick: () => setFilter(filter === 'covered' ? '' : 'covered'), pressed: filter === 'covered' },
        { label: 'BOQ lines with materials', icon: ClipboardList, value: plan.lines_with_norms, of: total || undefined, tone: plan.lines_without_norms ? 'attention' : 'good', to: boqLink },
      ]
    : []
  const due = rows.filter((r) => r.u === 'now' || r.u === 'soon')

  return (
    <div className="mx-auto flex w-full min-w-0 flex-col gap-4 pb-8 sm:px-2">
      <Heading summary={summary} controls={controls} />
      {!plan ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-20 rounded-xl" />
          <Skeleton className="h-64 rounded-xl" />
        </div>
      ) : plan.lines_with_norms === 0 ? (
        <div data-guide="matplan.empty">
          {fillCallout ?? (
            <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed bg-card px-4 py-10 text-center">
              <span className="flex size-10 items-center justify-center rounded-xl bg-primary/20 text-primary-ink" aria-hidden><Calculator className="size-5" /></span>
              <p className="font-medium">No BOQ line has its materials yet</p>
              <p className="max-w-sm text-sm text-muted-foreground">Set what each line uses (bags of cement per m³ and so on) and the plan works itself out from the schedule.</p>
              <Button asChild size="sm"><Link to={boqLink}>Open the BOQ</Link></Button>
            </div>
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
                    placeholder="Search materials"
                    className="w-32 bg-transparent text-sm outline-none"
                  />
                  <kbd className="hidden rounded border bg-muted px-1 text-[10px] text-muted-foreground sm:inline" title="Press / to search">/</kbd>
                </label>
              </div>
            </div>
            {shown.length === 0 ? (
              <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed bg-card py-10 text-center">
                <Search className="size-5 text-muted-foreground" aria-hidden />
                <p className="text-sm font-medium">No material matches</p>
                <Button variant="outline" size="sm" onClick={() => { setFilter(''); setSearch('') }}>Show all</Button>
              </div>
            ) : (
              <>
                <PlanTable plan={plan} rows={shown} onOrder={order} openCovered={filter === 'covered' || !!needle} />
                <PlanCards plan={plan} rows={shown} onOrder={order} openCovered={filter === 'covered' || !!needle} />
              </>
            )}
            <Legend
              className="pt-1"
              items={[
                { tone: 'bad', label: 'Order now' },
                { tone: 'attention', label: 'Order this week' },
                { tone: 'info', label: 'Order later' },
                { tone: 'good', label: 'Covered' },
              ]}
            />
            <p className="text-xs text-muted-foreground">
              Bars: <span className="font-medium text-success">in stock</span> · <span className="font-medium text-info">on order</span> · <span className="font-medium text-destructive">not covered yet</span>, of what the work still needs. Weeks: darker is more; red from the week it runs short.
            </p>
          </section>

          {plan.lines_without_norms > 0 && (
            <Link to={boqLink} className="group flex items-center gap-2.5 rounded-xl border bg-card px-3 py-2 transition-colors hover:bg-muted/40">
              <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-draft-soft text-draft" aria-hidden><ClipboardList className="size-3.5" /></span>
              <span className="min-w-0 flex-1 text-sm">
                <span className="font-semibold tabular-nums">{plan.lines_without_norms}</span> BOQ {plan.lines_without_norms === 1 ? 'line has' : 'lines have'} no materials yet
                <span className="text-muted-foreground"> · not in this plan</span>
              </span>
              <span className="inline-flex shrink-0 items-center gap-1 text-xs font-semibold">Set them <ChevronRight className="size-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden /></span>
            </Link>
          )}
        </>
      )}
      <NewOrderDialog open={!!ordering} onOpenChange={(o) => !o && setOrdering(null)} scope={{ mode: 'portfolio' }} prefill={ordering} />
    </div>
  )
}

// ---- To order: the materials to act on now, one card each --------------------------------------------------------

function ToOrder({ rows, today, onOrder }: { rows: Row[]; today: string; onOrder: (row: MaterialPlanRow) => void }) {
  return (
    // On a phone the cards below already lead with the urgent materials and their Order button: no second list.
    <section className="hidden flex-col gap-2 md:flex" data-guide="matplan.toorder" aria-label="To order">
      <h2 className="flex items-center gap-2 text-[15px] font-semibold">
        <ShoppingCart className="size-4 text-destructive" aria-hidden /> To order
        <span className="text-xs font-normal text-muted-foreground">{rows.length} material{rows.length === 1 ? '' : 's'} due within {SOON_DAYS} days</span>
      </h2>
      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {rows.map((r) => {
          const look = URGENCY[r.u]
          return (
            <li
              key={r.material_id}
              className={cn(
                "relative flex flex-col gap-2 overflow-hidden rounded-xl border bg-card p-3 pl-4 before:absolute before:inset-y-0 before:left-0 before:w-1 before:content-['']",
                look.edge,
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate font-semibold">{r.material}</p>
                  <p className={cn('text-xs font-medium', look.text)}>{whenText(r, today)}</p>
                </div>
                <UrgencyPill u={r.u} />
              </div>
              <div className="flex items-end justify-between gap-2">
                <div className="min-w-0 text-xs text-muted-foreground">
                  <p>
                    <span className="text-lg font-semibold text-foreground tabular-nums">{qty(r.short_by, true)}</span> {r.unit} short from {r.short_day ? dayLabel(r.short_day) : '—'}
                  </p>
                  <p className="flex items-center gap-1 truncate"><Truck className="size-3 shrink-0" aria-hidden /> {leadText(r)}</p>
                </div>
                <Button size="sm" variant={r.u === 'now' ? 'default' : 'outline'} className="h-8 shrink-0 gap-1" onClick={() => onOrder(r)}>
                  <ShoppingCart className="size-3.5" /> Order
                </Button>
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

// ---- Cover bar and week heatmap ---------------------------------------------------------------------------------

/** What the work still needs, as one bar: in stock (green), on order (blue), not covered (red). */
function CoverBar({ row }: { row: MaterialPlanRow }) {
  const still = Number(row.still_needed)
  if (!(still > 0)) return <span className="inline-flex items-center gap-1 text-xs font-medium text-success"><PackageCheck className="size-3.5" aria-hidden /> Nothing left to need</span>
  const hand = row.stock_unit_differs ? 0 : Math.min(Math.max(0, Number(row.on_hand)), still)
  const ordered = Math.min(Math.max(0, Number(row.on_order)), still - hand)
  const gap = Math.max(0, still - hand - ordered)
  const w = (v: number) => `${(v / still) * 100}%`
  const pct = Math.round(((hand + ordered) / still) * 100)
  return (
    <span className="flex w-full min-w-36 flex-col gap-1">
      <span
        className="flex h-2 overflow-hidden rounded-full bg-muted"
        role="img"
        aria-label={`${qty(still)} ${row.unit} still needed: ${qty(hand)} in stock, ${qty(ordered)} on order, ${qty(gap, true)} not covered`}
      >
        {hand > 0 && <span className="bg-success" style={{ width: w(hand) }} />}
        {ordered > 0 && <span className="bg-info" style={{ width: w(ordered) }} />}
        {gap > 0 && <span className="bg-destructive/80" style={{ width: w(gap) }} />}
      </span>
      <span className="flex justify-between gap-2 text-[11px] whitespace-nowrap text-muted-foreground tabular-nums">
        <span><span className="font-semibold text-foreground">{qty(still)}</span> {row.unit} to go</span>
        <span>{pct}% covered</span>
      </span>
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
  const lvl = heatLevel(v, max)
  return (
    <td
      className={cn(
        'px-2 py-2', NUM,
        short ? cn(HEAT_SHORT[lvl], 'font-semibold text-destructive') : HEAT[lvl],
        starts && 'shadow-[inset_3px_0_0_0_var(--destructive)]',
      )}
      title={starts ? `Runs short this week${row.short_day ? ` (${dayLabel(row.short_day)})` : ''}` : undefined}
    >
      {qty(value)}
    </td>
  )
}

function Notes({ row }: { row: MaterialPlanRow }) {
  const notes: { icon: LucideIcon; text: string; warn?: boolean }[] = []
  if (row.lines.some((l) => l.late)) notes.push({ icon: AlarmClock, text: 'late work needs it now', warn: true })
  if (row.stock_unit_differs) notes.push({ icon: PackageSearch, text: 'stock held in another unit, not counted', warn: true })
  if (Number(row.unscheduled) > 0) notes.push({ icon: CalendarOff, text: `${qty(row.unscheduled)} for work with no dates` })
  if (Number(row.later) > 0) notes.push({ icon: Clock, text: `${qty(row.later)} after these weeks` })
  if (!notes.length) return null
  return (
    <span className="mt-1 flex flex-wrap gap-1">
      {notes.map((n) => (
        <span key={n.text} className={cn('inline-flex items-center gap-1 rounded px-1.5 py-px text-[10.5px]', n.warn ? 'bg-draft-soft text-draft' : 'bg-muted text-muted-foreground')}>
          <n.icon className="size-3" aria-hidden /> {n.text}
        </span>
      ))}
    </span>
  )
}

function forWhat(row: MaterialPlanRow): string {
  if (!row.lines.length) return 'BOQ work done'
  return `for ${row.lines.map((l) => l.work).slice(0, 2).join(', ')}${row.lines.length > 2 ? ` +${row.lines.length - 2}` : ''}`
}

// ---- Table (laptop) and cards (phone) -----------------------------------------------------------------------------

function useCoveredOpen(force: boolean): [boolean, () => void] {
  const [open, setOpen] = React.useState(false)
  return [open || force, () => setOpen((o) => !o)]
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
            <th className={cn('min-w-52 px-3 py-2 text-left font-medium', sticky, 'bg-muted')}>Material</th>
            <th className="min-w-40 px-3 py-2 text-left font-medium">Cover</th>
            <th className={cn('px-2 py-2 font-medium whitespace-nowrap', NUM)}>Stock / on order</th>
            <th className="min-w-44 px-3 py-2 text-left font-medium">Order</th>
            {plan.weeks.map((w, i) => (
              <th key={w} className={cn('px-2 py-2 font-medium whitespace-nowrap', NUM, i === 0 && 'bg-primary/10 text-foreground')}>
                {i === 0 ? 'This week' : <><span className="block text-[10px] font-normal opacity-70">w/c</span>{dayLabel(w)}</>}
              </th>
            ))}
          </tr>
        </thead>
        {groups.map(({ u, rows: gr }) => {
          const look = URGENCY[u]
          const folded = u === 'covered' && !coveredOpen
          return (
            <tbody key={u} className="divide-y border-b last:border-b-0">
              <tr className={cn('bg-muted/25', u === 'covered' && 'cursor-pointer hover:bg-muted/50')} onClick={u === 'covered' ? toggleCovered : undefined}>
                <td colSpan={cols} className="px-3 py-1.5">
                  <span className="sticky left-3 inline-flex items-center gap-2 text-xs font-semibold">
                    {u === 'covered' && (folded ? <ChevronRight className="size-3.5" aria-hidden /> : <ChevronDown className="size-3.5" aria-hidden />)}
                    <span className={cn('size-2 rounded-full', look.dot)} aria-hidden />
                    <span className={look.text}>{look.label}</span>
                    <span className="font-normal text-muted-foreground tabular-nums">{gr.length}</span>
                    {u === 'covered' && (
                      <button type="button" className="font-normal text-muted-foreground underline-offset-2 hover:underline" aria-expanded={!folded}>
                        {folded ? 'show' : 'hide'}
                      </button>
                    )}
                  </span>
                </td>
              </tr>
              {!folded &&
                gr.map((row) => {
                  const max = Math.max(0, ...row.weeks.map(Number))
                  return (
                    <tr key={row.material_id} className="group align-top hover:bg-muted/20">
                      <td className={cn("relative px-3 py-2 before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:content-['']", sticky, look.edge, 'group-hover:bg-muted')}>
                        <span className="font-medium">{row.material}</span> <span className="text-xs text-muted-foreground">{row.unit}</span>
                        <p className="max-w-60 truncate text-xs text-muted-foreground" title={row.lines.map((l) => `${l.work}: ${qty(l.need)}`).join('\n')}>{forWhat(row)}</p>
                        <Notes row={row} />
                      </td>
                      <td className="px-3 py-2.5"><CoverBar row={row} /></td>
                      <td className={cn('px-2 py-2 whitespace-nowrap', NUM)}>
                        <span className="text-success">{qty(row.on_hand)}</span>
                        <span className="text-muted-foreground"> / </span>
                        <span className={Number(row.on_order) ? 'text-info' : 'text-muted-foreground'}>{Number(row.on_order) ? qty(row.on_order) : '—'}</span>
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex flex-col items-start gap-1">
                          <UrgencyPill u={u} />
                          {row.order_by && (
                            <>
                              <span className="text-xs text-muted-foreground">{whenText(row, plan.today)} · <span className="font-medium text-foreground">{qty(row.short_by, true)} {row.unit}</span></span>
                              <span className="max-w-52 truncate text-[11px] text-muted-foreground" title={leadText(row)}>{leadText(row)}</span>
                              <Button size="sm" variant={u === 'now' ? 'default' : 'outline'} className="mt-0.5 h-7 gap-1 px-2 text-xs" onClick={() => onOrder(row)}>
                                <ShoppingCart className="size-3" /> Order
                              </Button>
                            </>
                          )}
                        </div>
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
            <button
              type="button"
              disabled={u !== 'covered'}
              onClick={toggleCovered}
              aria-expanded={u === 'covered' ? !folded : undefined}
              className="flex items-center gap-2 text-left text-xs font-semibold disabled:cursor-default"
            >
              {u === 'covered' && (folded ? <ChevronRight className="size-3.5" aria-hidden /> : <ChevronDown className="size-3.5" aria-hidden />)}
              <span className={cn('size-2 rounded-full', look.dot)} aria-hidden />
              <span className={look.text}>{look.label}</span>
              <span className="font-normal text-muted-foreground tabular-nums">{gr.length}</span>
            </button>
            {!folded && (
              <ul className="flex flex-col gap-2">
                {gr.map((row) => {
                  const next = plan.weeks.map((w, i) => ({ w, v: row.weeks[i] })).filter((x) => Number(x.v) > 0).slice(0, 3)
                  return (
                    <li key={row.material_id} className={cn("relative flex flex-col gap-2 overflow-hidden rounded-xl border bg-card p-3 pl-4 before:absolute before:inset-y-0 before:left-0 before:w-1 before:content-['']", look.edge)}>
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="font-semibold">{row.material} <span className="text-xs font-normal text-muted-foreground">{row.unit}</span></p>
                          <p className="truncate text-xs text-muted-foreground">{forWhat(row)}</p>
                        </div>
                        <UrgencyPill u={u} />
                      </div>
                      <CoverBar row={row} />
                      {next.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {next.map((x) => {
                            const short = row.short_from !== null && x.w >= row.short_from
                            return (
                              <span key={x.w} className={cn('rounded px-1.5 py-0.5 text-[11px] tabular-nums', short ? 'bg-destructive/10 font-semibold text-destructive' : 'bg-info-soft text-info')}>
                                {x.w === plan.weeks[0] ? 'This week' : dayLabel(x.w)}: {qty(x.v)}
                              </span>
                            )
                          })}
                        </div>
                      )}
                      {row.order_by && (
                        <div className="flex items-center justify-between gap-2 border-t pt-2">
                          <div className="min-w-0 text-xs">
                            <p className={cn('font-medium', look.text)}>{whenText(row, plan.today)}</p>
                            <p className="truncate text-muted-foreground">{qty(row.short_by, true)} {row.unit} short · {leadText(row)}</p>
                          </div>
                          <Button size="sm" variant={u === 'now' ? 'default' : 'outline'} className="h-8 shrink-0 gap-1" onClick={() => onOrder(row)}>
                            <ShoppingCart className="size-3.5" /> Order
                          </Button>
                        </div>
                      )}
                      <Notes row={row} />
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
