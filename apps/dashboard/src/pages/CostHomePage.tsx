import * as React from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import type { LucideIcon } from 'lucide-react'
import {
  ArrowDownWideNarrow, ArrowRight, ChevronRight, CircleCheck, CircleDashed, ClipboardCheck, Eye, Gauge, HardHat, Landmark, Package,
  PieChart, Scale, Search, ShoppingCart, TrafficCone, TriangleAlert, X,
} from 'lucide-react'
import { MONEY_PEOPLE } from '@/lib/permissions'
import { KpiStrip, NoAccess } from '@/components/page/page-kit'
import { Pager } from '@/components/page/pager'
import { NumbersTable, ShowSwitch, type NumberColumn } from '@/components/page/numbers-view'
import { sortByColumn, useColumnSort, useShowMode } from '@/lib/numbers-view'
import { DprHeader, DprSection, PageError } from '@/components/dpr-page'
import { FilterPill, type FilterOption } from '@/components/requests/parts'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { maySeeBoq } from '@/lib/boq'
import { fetchPortfolio, type PortfolioRow, type VarianceColour } from '@/lib/cost'
import { COLOUR_DOT, COLOUR_TEXT } from '@/lib/cost-colours'
import { compact } from '@/lib/expenses'
import { usePagedUrl } from '@/lib/paging'
import { usePageTitle } from '@/lib/page-title'
import { useScope } from '@/lib/ScopeContext'
import { useUrlState } from '@/lib/url-state'
import { cn } from '@/lib/utils'

// CC-22: the Cost control home. Every project with a BOQ, worst forecast first (CC-19): budget, % done against
// % spent, committed, the forecast at completion against the budget, and the last 7 days' green / red; then what
// needs a person (labour and work not on a BOQ line). Backend: GET /cost/portfolio (the same reads as Budget vs
// actual and Green / red).
// UX-38 (17 Nov, "improve the cost control overview fully"): it reads by colour, not sentences. One KPI strip; a bar
// of the projects by forecast colour that filters the list; the two to-dos as action chips; the projects as a table
// with search, colour filter, sort and pages, each with a forecast pill, done against spent as two bars and the last
// 7 days as a chip, and links to its deeper pages; the deeper pages as coloured tiles.
// UX-44: a Bars / Numbers switch (components/page/numbers-view.tsx): every figure of a project in its own column.

const num = (v: string | null | undefined) => (v === null || v === undefined ? null : Number(v))

/** The forecast colours, in the order a person worries about them. */
const LOOK: Record<VarianceColour, { word: string; icon: LucideIcon; pill: string }> = {
  red: { word: 'Over budget', icon: TriangleAlert, pill: 'bg-destructive/10 text-destructive' },
  amber: { word: 'Watch', icon: Eye, pill: 'bg-draft-soft text-draft' },
  green: { word: 'On budget', icon: CircleCheck, pill: 'bg-success-soft text-success' },
  grey: { word: 'Too early', icon: CircleDashed, pill: 'bg-muted text-muted-foreground' },
}
const ORDER: VarianceColour[] = ['red', 'amber', 'green', 'grey']

const SORTS: { value: string; label: string; key?: (r: PortfolioRow) => number | string }[] = [
  { value: '', label: 'Worst first' },
  { value: 'over', label: 'Most over at finish', key: (r) => num(r.forecast_difference) ?? Number.MAX_SAFE_INTEGER },
  { value: 'ahead', label: 'Spending ahead of work', key: (r) => -((num(r.percent_spent) ?? 0) - (num(r.percent_done) ?? 0)) },
  { value: 'budget', label: 'Biggest budget', key: (r) => -(num(r.budget) ?? 0) },
  { value: 'name', label: 'Name', key: (r) => r.name.toLowerCase() },
]

/** Where a project finishes against its budget: a pill in its colour. */
function ForecastPill({ p }: { p: PortfolioRow }) {
  const look = LOOK[p.colour]
  const diff = num(p.forecast_difference)
  return (
    <span className={cn('inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold whitespace-nowrap tabular-nums', look.pill)}>
      <look.icon className="size-3" aria-hidden />
      {diff === null ? look.word : `${compact(Math.abs(diff))} ${diff < 0 ? 'over' : 'under'}`}
    </span>
  )
}

/** % done (blue) against % spent (green, or red when spending runs more than 5 points ahead of the work). */
function DoneSpent({ p }: { p: PortfolioRow }) {
  const done = num(p.percent_done)
  const spent = num(p.percent_spent)
  const ahead = (spent ?? 0) > (done ?? 0) + 5
  const row = (label: string, v: number | null, fill: string) => (
    <span className="grid grid-cols-[2.6rem_1fr_2.4rem] items-center gap-1.5 text-[11px]">
      <span className="text-muted-foreground">{label}</span>
      <span className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
        <span className={cn('block h-full rounded-full', fill)} style={{ width: `${Math.min(v ?? 0, 100)}%` }} />
      </span>
      <span className="text-right font-semibold tabular-nums">{v === null ? '—' : `${Math.round(v)}%`}</span>
    </span>
  )
  return (
    <span className="flex min-w-40 flex-col gap-1" title={ahead ? 'Spending is running ahead of the work done' : undefined}>
      {row('Done', done, 'bg-info')}
      {row('Spent', spent, ahead ? 'bg-destructive' : 'bg-success')}
    </span>
  )
}

/** The last 7 days' green / red as a chip. */
function WeekChip({ p }: { p: PortfolioRow }) {
  const c = p.week.colour
  return (
    <span className={cn('inline-flex items-center gap-1.5 text-xs font-medium whitespace-nowrap', COLOUR_TEXT[c])}>
      <span className={cn('size-2 rounded-full', COLOUR_DOT[c])} aria-hidden />
      {c === 'grey' ? 'Not judged' : c === 'red' ? `${p.week.red_lines} red ${p.week.red_lines === 1 ? 'line' : 'lines'}` : c === 'amber' ? 'Amber' : 'Green'}
    </span>
  )
}

/** A to-do with one thing to do: an icon, the figure, a few words, the link. */
function Nudge({ icon: Icon, to, action, children }: { icon: LucideIcon; to: string; action: string; children: React.ReactNode }) {
  return (
    <Link to={to} className="group flex items-center gap-2.5 rounded-xl border bg-card px-3 py-2 transition-colors hover:bg-muted/40">
      <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-draft-soft text-draft" aria-hidden>
        <Icon className="size-3.5" />
      </span>
      <span className="min-w-0 flex-1 text-sm">{children}</span>
      <span className="inline-flex shrink-0 items-center gap-1 text-xs font-semibold">
        {action} <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden />
      </span>
    </Link>
  )
}

/** UX-44: the Numbers view's columns: every figure of a project in its own column. */
const money = (v: string | null) => (v === null || num(v) === null ? null : compact(Number(v)))
const pct = (v: string | null) => (v === null ? null : `${Math.round(Number(v))}%`)
const PROJECT_NAME: NumberColumn<PortfolioRow> = {
  key: 'name',
  label: 'Project',
  sortValue: (p) => p.name.toLowerCase(),
  cell: (p) => (
    <span className="flex items-center gap-1.5 whitespace-nowrap">
      {React.createElement(LOOK[p.colour].icon, { className: cn('size-3.5 shrink-0', COLOUR_TEXT[p.colour]), 'aria-hidden': true })}
      <span className="max-w-60 truncate font-medium">{p.name}</span>
    </span>
  ),
}
const ahead = (p: PortfolioRow) => (p.percent_spent === null || p.percent_done === null ? null : Number(p.percent_spent) - Number(p.percent_done))
const PROJECT_COLUMNS: NumberColumn<PortfolioRow>[] = [
  { key: 'budget', label: 'Budget', sortValue: (p) => num(p.budget), cell: (p) => money(p.budget) },
  { key: 'earned', label: 'Earned', title: 'Work done × BOQ rates', sortValue: (p) => num(p.earned), cell: (p) => money(p.earned), tone: () => 'text-info' },
  { key: 'spent', label: 'Spent', sortValue: (p) => Number(p.spent), cell: (p) => money(p.spent) },
  { key: 'committed', label: 'Committed', title: 'Ordered, not in yet', sortValue: (p) => Number(p.committed), cell: (p) => (Number(p.committed) > 0 ? money(p.committed) : null) },
  { key: 'done', label: '% done', sortValue: (p) => num(p.percent_done), cell: (p) => pct(p.percent_done), tone: () => 'text-info' },
  { key: 'pspent', label: '% spent', sortValue: (p) => num(p.percent_spent), cell: (p) => pct(p.percent_spent) },
  {
    key: 'ahead', label: 'Spent ahead', title: '% spent − % done, in points', sortValue: ahead,
    cell: (p) => { const a = ahead(p); return a === null ? null : `${a > 0 ? '+' : ''}${Math.round(a)} pts` },
    tone: (p) => { const a = ahead(p) ?? 0; return a > 5 ? 'font-semibold text-destructive' : a < 0 ? 'text-success' : undefined },
  },
  { key: 'forecast', label: 'At finish', title: 'Forecast at completion', sortValue: (p) => num(p.forecast), cell: (p) => money(p.forecast) },
  {
    key: 'gap', label: 'Vs budget', title: 'Budget − forecast: − is over', sortValue: (p) => num(p.forecast_difference),
    cell: (p) => { const d = num(p.forecast_difference); return d === null ? null : `${d > 0 ? '+' : d < 0 ? '−' : ''}${compact(Math.abs(d))}` },
    tone: (p) => { const d = num(p.forecast_difference) ?? 0; return d < 0 ? 'font-semibold text-destructive' : d > 0 ? 'font-semibold text-success' : undefined },
  },
  {
    key: 'week', label: 'Last 7 days', text: true, sortValue: (p) => (p.week.colour === 'grey' ? null : p.week.red_lines),
    cell: (p) => <WeekChip p={p} />,
  },
  { key: 'labour', label: 'Labour off lines', sortValue: (p) => Number(p.labour_not_on_a_line), cell: (p) => (Number(p.labour_not_on_a_line) > 0 ? money(p.labour_not_on_a_line) : null), tone: () => 'text-draft' },
  { key: 'work', label: 'Work off lines', sortValue: (p) => p.work_not_on_a_line, cell: (p) => (p.work_not_on_a_line > 0 ? p.work_not_on_a_line : null), tone: () => 'text-draft' },
]

const PAGES: { to: string; icon: LucideIcon; tile: string; title: string; about: string }[] = [
  { to: '/cost/green-red', icon: TrafficCone, tile: 'bg-destructive/10 text-destructive', title: 'Green / red', about: 'Labour against work, by day' },
  { to: '/cost/budget', icon: Scale, tile: 'bg-info-soft text-info', title: 'Budget vs actual', about: 'Earned, spent, forecast' },
  { to: '/cost/materials', icon: Package, tile: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400', title: 'Materials vs BOQ', about: 'Used against needed' },
  { to: '/cost/centres', icon: PieChart, tile: 'bg-violet-500/15 text-violet-700 dark:text-violet-400', title: 'Cost centres', about: 'Where the money went' },
  { to: '/boq', icon: ClipboardCheck, tile: 'bg-amber-500/15 text-amber-700 dark:text-amber-400', title: 'BOQ & budget', about: 'Rates and work per line' },
]

export default function CostHomePage() {
  const { me } = useAuth()
  usePageTitle('Cost control')
  const allowed = maySeeBoq(me?.role)
  const q = useQuery({ queryKey: ['cost', 'portfolio'], queryFn: fetchPortfolio, enabled: allowed })
  const { scope } = useScope()
  const navigate = useNavigate()
  const [search, setSearch] = useUrlState<string>('q', '')
  const [colour, setColour] = useUrlState<string>('colour', '')
  const [sort, setSort] = useUrlState<string>('sort', '')
  // UX-44: Bars (a glance) or Numbers (every figure in its own column, any column sorts).
  const [show, setShow] = useShowMode('cost')
  const { col, dir, onSort: sortCol, clear: clearCol } = useColumnSort()

  // SCP-03: with a project picked, that project's row and totals.
  const rows = React.useMemo(
    () => (q.data?.projects ?? []).filter((r) => scope.mode === 'portfolio' || r.project_id === scope.projectId),
    [q.data, scope],
  )
  const needle = search.trim().toLowerCase()
  const listed = React.useMemo(() => {
    const out = rows.filter((r) => (!colour || r.colour === colour) && (!needle || r.name.toLowerCase().includes(needle)))
    const byColumn = show === 'numbers' ? sortByColumn(out, [PROJECT_NAME, ...PROJECT_COLUMNS], col, dir) : null
    if (byColumn) return byColumn
    const key = SORTS.find((x) => x.value === sort)?.key
    if (!key) return out
    return [...out].sort((a, b) => {
      const ka = key(a)
      const kb = key(b)
      return typeof ka === 'string' ? ka.localeCompare(String(kb)) : ka - Number(kb)
    })
  }, [rows, colour, needle, sort, show, col, dir])
  const paged = usePagedUrl(listed)

  if (!allowed) return <NoAccess roles={MONEY_PEOPLE} />
  if (q.isError) return <PageError message="Cost control could not be loaded." onRetry={() => q.refetch()} back={{ to: '/today', label: 'Today' }} />

  const sum = (pick: (r: PortfolioRow) => string | null) => rows.reduce((t, r) => t + Number(pick(r) ?? 0), 0)
  const budget = sum((r) => r.budget)
  const earned = sum((r) => r.earned)
  const spent = sum((r) => r.spent)
  const committed = sum((r) => r.committed)
  const count = (c: VarianceColour) => rows.filter((r) => r.colour === c).length
  const over = count('red')
  const overBy = rows.reduce((t, r) => t + Math.max(0, -(num(r.forecast_difference) ?? 0)), 0)
  const labourLeft = sum((r) => r.labour_not_on_a_line)
  const workLeft = rows.reduce((t, r) => t + r.work_not_on_a_line, 0)
  const one = scope.mode !== 'portfolio'
  const budgetLink = one ? `/cost/budget?project=${scope.projectId}` : '/cost/budget'
  const colourOptions: FilterOption[] = ORDER.map((c) => ({ value: c, label: LOOK[c].word, dot: COLOUR_DOT[c], count: count(c) }))
  const any = !!(search || colour)

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader
        back={{ to: '/today', label: 'Today' }}
        crumb="Cost control"
        title="Cost control"
        date={q.data ? (one ? undefined : `${rows.length} ${rows.length === 1 ? 'project' : 'projects'} with a BOQ`) : ''}
      />
      {q.isLoading ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-24 rounded-xl" />
          <Skeleton className="h-10 rounded-xl" />
          <Skeleton className="h-64 rounded-xl" />
        </div>
      ) : rows.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed bg-card px-4 py-10 text-center" data-guide="cost.empty">
          <span className="flex size-10 items-center justify-center rounded-xl bg-amber-500/15 text-amber-700 dark:text-amber-400" aria-hidden>
            <ClipboardCheck className="size-5" />
          </span>
          <p className="font-medium">{one ? `${scope.projectName} has no BOQ yet` : 'No project has a BOQ yet'}</p>
          <Button asChild size="sm">
            <Link to="/boq">Add a BOQ</Link>
          </Button>
        </div>
      ) : (
        <>
          <KpiStrip
            guide="cost.stats"
            stats={[
              { label: 'Budget', icon: Landmark, value: compact(budget) },
              { label: 'Earned', icon: Gauge, tone: 'info', value: compact(earned), share: budget ? earned / budget : undefined, hint: budget ? `${Math.round((earned / budget) * 100)}% of budget` : undefined },
              { label: 'Spent', kind: 'money', tone: spent > earned ? 'bad' : 'default', value: compact(spent), share: budget ? spent / budget : undefined, hint: spent > earned ? `${compact(spent - earned)} ahead of the work` : undefined },
              { label: 'Committed', icon: ShoppingCart, value: compact(committed), hint: 'ordered, not in yet' },
              { label: 'Heading over', icon: TriangleAlert, tone: over > 0 ? 'bad' : 'good', value: over, of: rows.length, hint: over > 0 ? `by ${compact(overBy)}` : 'none' },
            ]}
          />

          {/* The projects by forecast colour: one bar, each colour a filter. */}
          {rows.length > 1 && (
            <div className="flex flex-col gap-2 rounded-xl border bg-card p-3" data-guide="cost.health">
              <div className="flex h-2.5 overflow-hidden rounded-full bg-muted" role="img" aria-label={ORDER.map((c) => `${count(c)} ${LOOK[c].word}`).join(', ')}>
                {ORDER.map((c) => count(c) > 0 && <span key={c} className={COLOUR_DOT[c]} style={{ width: `${(count(c) / rows.length) * 100}%` }} />)}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {ORDER.filter((c) => count(c) > 0).map((c) => {
                  const on = colour === c
                  const Icon = LOOK[c].icon
                  return (
                    <button
                      key={c}
                      type="button"
                      aria-pressed={on}
                      onClick={() => setColour(on ? '' : c)}
                      className={cn(
                        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold transition',
                        LOOK[c].pill,
                        on ? 'ring-2 ring-foreground/70' : 'hover:ring-1 hover:ring-foreground/20',
                      )}
                    >
                      <Icon className="size-3.5" aria-hidden />
                      <span className="tabular-nums">{count(c)}</span> {LOOK[c].word}
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          {(labourLeft > 0 || workLeft > 0) && (
            <div className="grid gap-2 md:grid-cols-2">
              {labourLeft > 0 && (
                <Nudge icon={HardHat} to={`${budgetLink}#labour-to-lines`} action="Put on lines">
                  <span className="font-semibold tabular-nums">{compact(labourLeft)}</span> labour not on a BOQ line
                </Nudge>
              )}
              {workLeft > 0 && (
                <Nudge icon={ClipboardCheck} to="/boq" action="Put on lines">
                  <span className="font-semibold tabular-nums">{workLeft}</span> {workLeft === 1 ? 'piece' : 'pieces'} of measured work not on a line
                </Nudge>
              )}
            </div>
          )}

          <DprSection icon={TrafficCone} title="Projects" meta={any ? `${listed.length} of ${rows.length}` : rows.length}>
            {rows.length > 1 && (
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <label className="flex h-9 items-center gap-2 rounded-lg border bg-card px-2.5">
                  <Search className="size-4 text-muted-foreground" aria-hidden />
                  <span className="sr-only">Search projects</span>
                  <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search projects" className="w-36 bg-transparent text-sm outline-none sm:w-48" />
                </label>
                <FilterPill icon={TrafficCone} label="Forecast" allLabel="Any forecast" value={colour} options={colourOptions} onChange={setColour} />
                {any && (
                  <Button variant="ghost" size="sm" className="h-9 gap-1" onClick={() => { setSearch(''); setColour('') }}>
                    <X className="size-3.5" aria-hidden /> Clear
                  </Button>
                )}
                <span className="ml-auto flex items-center gap-2">
                  <label className="flex h-9 items-center gap-1.5 rounded-lg border bg-card px-2.5 text-sm">
                    <ArrowDownWideNarrow className="size-4 text-muted-foreground" aria-hidden />
                    <select value={col && show === 'numbers' ? '' : sort} onChange={(e) => { setSort(e.target.value); clearCol() }} className="bg-transparent outline-none" aria-label="Sort the projects">
                      {SORTS.map((x) => (
                        <option key={x.value} value={x.value}>
                          {x.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <ShowSwitch show={show} onShow={setShow} label="How to show the projects" />
                </span>
              </div>
            )}
            {listed.length === 0 ? (
              <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed bg-card py-10 text-center">
                <Search className="size-5 text-muted-foreground" aria-hidden />
                <p className="text-sm font-medium">No project matches</p>
                <Button variant="outline" size="sm" onClick={() => { setSearch(''); setColour('') }}>
                  Clear filters
                </Button>
              </div>
            ) : show === 'numbers' ? (
              <NumbersTable
                rows={paged.shown}
                rowKey={(p) => p.project_id}
                first={PROJECT_NAME}
                columns={PROJECT_COLUMNS}
                edge={(p) => COLOUR_DOT[p.colour]}
                col={col}
                dir={dir}
                onSort={sortCol}
                onOpen={(p) => navigate(`/cost/green-red?project=${p.project_id}`)}
                openTitle="Open its Green / red"
                guide="cost.projects"
                minWidth={1240}
                footer="Spent ahead: % spent − % done, in points · Off lines: labour and measured work not on a BOQ line"
              />
            ) : (
              <div className="overflow-hidden rounded-xl border bg-card" data-guide="cost.projects">
                <table className="w-full text-sm">
                  <thead className="bg-muted/50 text-xs text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium">Project</th>
                      <th className="hidden px-3 py-2 text-right font-medium md:table-cell">Budget</th>
                      <th className="hidden px-3 py-2 text-left font-medium lg:table-cell">Done vs spent</th>
                      <th className="hidden px-3 py-2 text-right font-medium xl:table-cell">Committed</th>
                      <th className="hidden px-3 py-2 text-left font-medium md:table-cell">Last 7 days</th>
                      <th className="w-8 px-2 py-2"><span className="sr-only">Open</span></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {paged.shown.map((p) => {
                      const open = () => navigate(`/cost/green-red?project=${p.project_id}`)
                      return (
                        <tr key={p.project_id} className="cursor-pointer align-top hover:bg-muted/30" onClick={open}>
                          <td className="px-3 py-2.5">
                            <div className="flex items-start gap-2.5">
                              <span className={cn('mt-1.5 size-2.5 shrink-0 rounded-full', COLOUR_DOT[p.colour])} aria-hidden />
                              <div className="flex min-w-0 flex-col gap-1">
                                <span className="flex flex-wrap items-center gap-2">
                                  <Link to={`/cost/green-red?project=${p.project_id}`} className="font-medium hover:underline" onClick={(e) => e.stopPropagation()}>
                                    {p.name}
                                  </Link>
                                  <ForecastPill p={p} />
                                </span>
                                {p.forecast_kinds.length > 0 && p.forecast_kinds.length < 3 && (
                                  <span className="text-[11px] text-muted-foreground">from {p.forecast_kinds.join(', ')}</span>
                                )}
                                {/* Below a laptop the figures fold under the name (docs/DESIGN.md section 8). */}
                                <span className="lg:hidden">
                                  <DoneSpent p={p} />
                                </span>
                                <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground md:hidden">
                                  <span className="tabular-nums">Budget <span className="font-semibold text-foreground">{num(p.budget) === null ? '—' : compact(Number(p.budget))}</span></span>
                                  <WeekChip p={p} />
                                </span>
                                <span className="flex flex-wrap gap-x-3 text-[11px] font-medium" onClick={(e) => e.stopPropagation()}>
                                  <Link to={`/cost/budget?project=${p.project_id}`} className="text-muted-foreground hover:text-foreground hover:underline">Budget</Link>
                                  <Link to={`/cost/materials?project=${p.project_id}`} className="text-muted-foreground hover:text-foreground hover:underline">Materials</Link>
                                  <Link to={`/cost/centres?project=${p.project_id}`} className="text-muted-foreground hover:text-foreground hover:underline">Cost centres</Link>
                                </span>
                              </div>
                            </div>
                          </td>
                          <td className="hidden px-3 py-2.5 text-right font-medium tabular-nums md:table-cell">{num(p.budget) === null ? '—' : compact(Number(p.budget))}</td>
                          <td className="hidden px-3 py-2.5 lg:table-cell">
                            <DoneSpent p={p} />
                          </td>
                          <td className="hidden px-3 py-2.5 text-right tabular-nums xl:table-cell">{Number(p.committed) > 0 ? compact(Number(p.committed)) : <span className="text-muted-foreground">—</span>}</td>
                          <td className="hidden px-3 py-2.5 md:table-cell">
                            <WeekChip p={p} />
                          </td>
                          <td className="px-2 py-2.5 text-muted-foreground">
                            <ChevronRight className="size-4" aria-hidden />
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
            <Pager {...paged.pager} noun="projects" className="mt-2" />
          </DprSection>
        </>
      )}

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5" data-guide="cost.pages">
        {PAGES.map((pg) => (
          <Link key={pg.to} to={one && pg.to.startsWith('/cost/') ? `${pg.to}?project=${scope.projectId}` : pg.to} className="group flex flex-col gap-2 rounded-xl border bg-card p-3 transition-colors hover:border-foreground/25">
            <span className="flex items-center justify-between">
              <span className={cn('flex size-8 items-center justify-center rounded-lg', pg.tile)} aria-hidden>
                <pg.icon className="size-4" />
              </span>
              <ArrowRight className="size-3.5 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" aria-hidden />
            </span>
            <span className="min-w-0">
              <span className="block text-sm font-semibold">{pg.title}</span>
              <span className="block truncate text-xs text-muted-foreground">{pg.about}</span>
            </span>
          </Link>
        ))}
      </div>
    </div>
  )
}
