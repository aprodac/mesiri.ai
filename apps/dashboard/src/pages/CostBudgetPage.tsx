import * as React from 'react'
import { Link } from 'react-router-dom'
import { MONEY_PEOPLE } from '@/lib/permissions'
import { ActionButton, ActionChip, ClearButton, KpiStrip, ListToolbar, NoAccess, NoMatch, SearchBox, SortSelect } from '@/components/page/page-kit'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { LucideIcon } from 'lucide-react'
import {
  ArrowDown, ArrowRight, ArrowUpDown, Boxes, Calculator, CircleCheck, CircleDashed, ClipboardCheck, Gauge, Handshake, HardHat, Layers, MapPin, ShoppingCart, Sparkles, TrendingDown, TrendingUp, TriangleAlert, X,
} from 'lucide-react'
import { DprHeader, DprSection, PageError } from '@/components/dpr-page'
import { Pager } from '@/components/page/pager'
import { PAGE_SIZES, usePaged } from '@/lib/paging'
import { FilterPill, type FilterOption } from '@/components/requests/parts'
import { Button } from '@/components/ui/button'
import { useUrlState } from '@/lib/url-state'
import { exportCsv } from '@/lib/export'
import { appNow } from '@/lib/clock'
import { CostExportButton } from '@/components/cost/export-button'
import { LineDetailSheet } from '@/components/cost/line-detail'
import { LabourGroupRow } from '@/components/cost/labour-to-lines'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast-notification'
import { useAuth } from '@/lib/AuthContext'
import { formatQuantity, formatRupees, maySeeBoq } from '@/lib/boq'
import { CENTRE_COLOURS, fetchProjectBudget, fetchProjectLabour, putLabourOnLines, putLabourOnSuggestions, type BudgetKind, type BudgetLine, type LabourGroup } from '@/lib/cost'
import { compact } from '@/lib/expenses'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import { useScope } from '@/lib/ScopeContext'
import { cn } from '@/lib/utils'
import { ProjectPickList } from '@/components/schedule/project-picker'

// CC-04: budget against actual for a project, to date. Per kind (labour, materials, subcontract): the BOQ's budget,
// the budget earned by the work done (work put on a BOQ line), and what was spent in that cost centre. Earned less
// spent is the gap; a kind with no BOQ rate or no work on a line yet shows a dash, never a made-up figure. Per BOQ
// line: planned, done, left and earned. Backend: GET /cost/projects/{id}/budget.
// CC-05: each line also shows the labour put on it (a site's day of one trade, from attendance, by man-days) against
// the labour budget it earned; the last 30 days' labour not on a line is listed to put on its line.
// Backend: GET / PUT /cost/projects/{id}/labour.
// UX-35 (17 Nov, "less description, more visual cues"): the page reads by colour and shape, not sentences. One KPI
// strip for the project; a card per kind in its cost-centre colour with an under / over pill and two bars (earned,
// spent); the notes are action chips; the BOQ table is grouped by section with a progress bar per line and coloured
// over / under pills. Green is under the budget earned, red is over, grey is "not known yet" (never a made-up figure).



const num = (v: string | null | undefined) => (v === null || v === undefined ? null : Number(v))
const sumOf = (xs: (number | null)[]) => (xs.some((x) => x !== null) ? xs.reduce<number>((n, x) => n + (x ?? 0), 0) : null)
const shortDay = (iso: string) => {
  const d = new Date(`${iso}T00:00:00`)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
}

/** Each kind in its cost-centre colour (lib/cost.ts CENTRE_COLOURS), so it matches Cost centres. */
const KIND_LOOK: Record<BudgetKind['kind'], { icon: LucideIcon; tile: string; bar: string }> = {
  labour: { icon: HardHat, tile: 'bg-amber-500/15 text-amber-700 dark:text-amber-400', bar: CENTRE_COLOURS.labour },
  material: { icon: Boxes, tile: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400', bar: CENTRE_COLOURS.materials },
  subcontract: { icon: Handshake, tile: 'bg-violet-500/15 text-violet-700 dark:text-violet-400', bar: CENTRE_COLOURS.subcontract },
}

/** Under (green, a tick) or over (red, a warning) the budget; grey when it is not known. */
function GapPill({ diff, unknown, size = 'sm' }: { diff: number | null; unknown?: string; size?: 'sm' | 'xs' }) {
  const cls = cn('inline-flex shrink-0 items-center gap-1 rounded-full font-semibold whitespace-nowrap tabular-nums', size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-1.5 py-px text-[11px]')
  if (diff === null) {
    return unknown ? (
      <span className={cn(cls, 'bg-muted font-medium text-muted-foreground')}>
        <CircleDashed className="size-3" aria-hidden /> {unknown}
      </span>
    ) : (
      <span className="text-muted-foreground">—</span>
    )
  }
  const over = diff < 0
  return (
    <span className={cn(cls, over ? 'bg-destructive/10 text-destructive' : 'bg-success-soft text-success')}>
      {over ? <TriangleAlert className="size-3" aria-hidden /> : <CircleCheck className="size-3" aria-hidden />}
      {compact(Math.abs(diff))} {over ? 'over' : 'under'}
    </span>
  )
}

/** A labelled bar on a shared scale. */
function Bar({ label, value, scale, fill }: { label: string; value: number | null; scale: number; fill: string }) {
  const pct = value !== null && scale > 0 ? Math.min(100, (value / scale) * 100) : 0
  return (
    <div className="grid grid-cols-[4rem_1fr_auto] items-center gap-2 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className="h-2 overflow-hidden rounded-full bg-muted" aria-hidden>
        <span className={cn('block h-full rounded-full', fill)} style={{ width: `${value ? Math.max(pct, 2) : 0}%` }} />
      </span>
      <span className="min-w-14 text-right font-semibold tabular-nums">{value === null ? '—' : compact(value)}</span>
    </div>
  )
}

function KindCard({ k }: { k: BudgetKind }) {
  const look = KIND_LOOK[k.kind] ?? KIND_LOOK.labour
  const budget = num(k.budget)
  const earned = num(k.earned)
  const spent = Number(k.actual)
  const diff = num(k.difference)
  const scale = Math.max(budget ?? 0, earned ?? 0, spent)
  const forecastDiff = num(k.forecast_difference)
  const over = diff !== null && diff < 0
  return (
    <div
      className={cn(
        'relative flex flex-col gap-3 overflow-hidden rounded-xl border bg-card p-4',
        diff !== null && "before:absolute before:inset-x-0 before:top-0 before:h-[3px] before:content-['']",
        diff !== null && (over ? 'before:bg-destructive' : 'before:bg-success'),
      )}
    >
      <div className="flex items-center gap-2">
        <span className={cn('flex size-8 shrink-0 items-center justify-center rounded-lg', look.tile)} aria-hidden>
          <look.icon className="size-4" />
        </span>
        <span className="min-w-0 flex-1 truncate font-semibold">{k.label}</span>
        <GapPill diff={diff} unknown={budget === null ? 'No rate' : earned === null ? 'No work yet' : undefined} />
      </div>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs text-muted-foreground">Budget</span>
        <span className="text-lg font-semibold tabular-nums">{budget === null ? '—' : compact(budget)}</span>
      </div>
      <div className="flex flex-col gap-1.5">
        <Bar label="Earned" value={earned} scale={scale} fill="bg-info" />
        <Bar label="Spent" value={spent} scale={scale} fill={over ? 'bg-destructive' : diff === null ? look.bar : 'bg-success'} />
      </div>
      {(k.committed !== null || k.forecast !== null) && (
        <div className="flex flex-wrap gap-1.5 border-t pt-2.5 text-xs">
          {k.committed !== null && (
            <span className="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-1 tabular-nums" title="Ordered or agreed, not yet delivered or billed">
              <ShoppingCart className="size-3 text-muted-foreground" aria-hidden />
              <span className="text-muted-foreground">Committed</span> <span className="font-semibold">{compact(Number(k.committed))}</span>
              {k.committed_detail?.unpriced_lines ? (
                <span className="rounded bg-draft-soft px-1 text-[10px] font-semibold text-draft" title={`${k.committed_detail.unpriced_lines} order lines with no rate`}>
                  +{k.committed_detail.unpriced_lines} no rate
                </span>
              ) : null}
            </span>
          )}
          {k.forecast !== null && (
            <span
              className={cn(
                'inline-flex items-center gap-1 rounded-md px-2 py-1 tabular-nums',
                forecastDiff === null ? 'bg-muted' : forecastDiff < 0 ? 'bg-destructive/10 text-destructive' : 'bg-success-soft text-success',
              )}
              title="Forecast at completion, at the rate so far"
            >
              {forecastDiff !== null && forecastDiff < 0 ? <TrendingUp className="size-3" aria-hidden /> : <TrendingDown className="size-3" aria-hidden />}
              <span className="opacity-80">At finish</span> <span className="font-semibold">{compact(Number(k.forecast))}</span>
            </span>
          )}
        </div>
      )}
    </div>
  )
}

/** How much of a line is done: a bar (amber past the plan) and "done / planned unit". */
function Progress({ l }: { l: BudgetLine }) {
  const pct = Math.max(0, Number(l.percent_done ?? 0))
  const done = Number(l.done_quantity)
  return (
    <div className="flex min-w-36 flex-col gap-1">
      <span className="flex items-baseline justify-between gap-2 text-xs tabular-nums">
        <span>
          <span className={cn('font-semibold', done === 0 && 'text-muted-foreground')}>{formatQuantity(l.done_quantity)}</span>
          <span className="text-muted-foreground"> / {formatQuantity(l.planned_quantity)} {l.unit}</span>
        </span>
        <span className={cn('font-semibold', l.over_planned ? 'text-draft' : done === 0 ? 'text-muted-foreground' : 'text-info')}>{done > 0 ? `${Math.round(pct)}%` : '—'}</span>
      </span>
      <span className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
        <span className={cn('block h-full rounded-full', l.over_planned ? 'bg-draft' : pct >= 100 ? 'bg-success' : 'bg-info')} style={{ width: `${Math.min(100, pct)}%` }} />
      </span>
    </div>
  )
}

type Line = BudgetLine & { section: string; sectionId: string }

// UX-36: the BOQ lines can be searched ("/" jumps there), sorted by a column header or the sort menu, exported as
// shown, and filtered (section, how far done, labour), sorted and paged; all of it is kept
// in the address, so a link or the back button keeps the view. In BOQ order the lines stay under their section bands.
const PROGRESS: { value: string; label: string; dot: string; test: (l: Line) => boolean }[] = [
  { value: 'none', label: 'Not started', dot: 'bg-muted-foreground/40', test: (l) => Number(l.done_quantity) <= 0 },
  { value: 'going', label: 'In progress', dot: 'bg-info', test: (l) => Number(l.done_quantity) > 0 && Number(l.percent_done ?? 0) < 100 && !l.over_planned },
  { value: 'done', label: 'Done', dot: 'bg-success', test: (l) => Number(l.percent_done ?? 0) >= 100 && !l.over_planned },
  { value: 'past', label: 'Past the plan', dot: 'bg-draft', test: (l) => l.over_planned },
]
const LABOUR: { value: string; label: string; dot: string; test: (l: Line) => boolean }[] = [
  { value: 'over', label: 'Labour over', dot: 'bg-destructive', test: (l) => num(l.labour_difference) !== null && num(l.labour_difference)! < 0 },
  { value: 'under', label: 'Labour under', dot: 'bg-success', test: (l) => num(l.labour_difference) !== null && num(l.labour_difference)! >= 0 },
  { value: 'nowage', label: 'No wage', dot: 'bg-draft', test: (l) => Number(l.labour_man_days) > 0 && l.labour_cost === null },
  { value: 'nolabour', label: 'No labour yet', dot: 'bg-muted-foreground/40', test: (l) => Number(l.labour_man_days) <= 0 },
]
const SORTS: { value: string; label: string; key?: (l: Line) => number }[] = [
  { value: '', label: 'BOQ order' },
  { value: 'budget', label: 'Biggest budget', key: (l) => -(num(l.budget_cost) ?? 0) },
  { value: 'earned', label: 'Most earned', key: (l) => -(Number(l.done_quantity) > 0 ? num(l.earned) ?? 0 : 0) },
  { value: 'left', label: 'Most budget left', key: (l) => -((num(l.budget_cost) ?? 0) - (Number(l.done_quantity) > 0 ? num(l.earned) ?? 0 : 0)) },
  { value: 'done', label: 'Most done', key: (l) => -Number(l.percent_done ?? 0) },
  { value: 'over', label: 'Labour most over', key: (l) => num(l.labour_difference) ?? Number.MAX_SAFE_INTEGER },
]

/** A column header that sorts the table; pressed again, back to BOQ order. */
function SortHead({ label, value, sort, onSort, right }: { label: string; value: string; sort: string; onSort: (v: string) => void; right?: boolean }) {
  const on = sort === value
  return (
    <button type="button" onClick={() => onSort(on ? '' : value)} className={cn('inline-flex items-center gap-1 rounded hover:text-foreground', right && 'flex-row-reverse', on && 'font-semibold text-foreground')}>
      {label}
      {on ? <ArrowDown className="size-3" aria-hidden /> : <ArrowUpDown className="size-3 opacity-40" aria-hidden />}
    </button>
  )
}

function BoqLinesTable({ lines, projectId }: { lines: Line[]; projectId: string }) {
  // UX-95: a line opens its entries (the work counted on it, the labour put on it).
  const [opened, setOpened] = React.useState<Line | null>(null)
  // From Green / red: `line` names the line the owner tapped, opened at once (one tap from the red line to its entries).
  const [lineParam, setLineParam] = useUrlState<string>('line', '')
  React.useEffect(() => {
    const hit = lineParam ? lines.find((l) => l.id === lineParam) : undefined
    if (hit) setOpened(hit)
  }, [lineParam, lines])
  const [q, setQ] = useUrlState<string>('q', '')
  const [sec, setSec] = useUrlState<string>('section', '')
  const [prog, setProg] = useUrlState<string>('done', '')
  const [lab, setLab] = useUrlState<string>('labour', '')
  const [sort, setSort] = useUrlState<string>('sort', '')
  const [pageS, setPage] = useUrlState<string>('page', '1')
  const [sizeS, setSize] = useUrlState<string>('size', '25')
  const size = PAGE_SIZES.includes(Number(sizeS) as (typeof PAGE_SIZES)[number]) ? Number(sizeS) : 25
  // A changed filter starts from the first page.
  const reset = <T,>(set: (v: T) => void) => (v: T) => {
    set(v)
    setPage('1')
  }
  const needle = q.trim().toLowerCase()
  const pass = (l: Line, skip?: string) =>
    (skip === 'section' || !sec || l.sectionId === sec) &&
    (skip === 'done' || !prog || !!PROGRESS.find((p) => p.value === prog)?.test(l)) &&
    (skip === 'labour' || !lab || !!LABOUR.find((x) => x.value === lab)?.test(l)) &&
    (!needle || `${l.boq_code ?? ''} ${l.work} ${l.section}`.toLowerCase().includes(needle))
  const filtered = lines.filter((l) => pass(l))
  const sorter = SORTS.find((x) => x.value === sort)?.key
  const rows = sorter ? [...filtered].sort((a, b) => sorter(a) - sorter(b)) : filtered
  const paged = usePaged(rows, Number(pageS) || 1, size)
  const any = !!(q || sec || prog || lab)

  const sections = [...new Map(lines.map((l) => [l.sectionId, l.section])).entries()]
  const secOptions: FilterOption[] = sections.map(([id, name]) => ({ value: id, label: name, count: lines.filter((l) => l.sectionId === id && pass(l, 'section')).length }))
  const progOptions: FilterOption[] = PROGRESS.map((p) => ({ value: p.value, label: p.label, dot: p.dot, count: lines.filter((l) => p.test(l) && pass(l, 'done')).length }))
  const labOptions: FilterOption[] = LABOUR.map((x) => ({ value: x.value, label: x.label, dot: x.dot, count: lines.filter((l) => x.test(l) && pass(l, 'labour')).length }))
  const clear = () => {
    setQ('')
    setSec('')
    setProg('')
    setLab('')
    setPage('1')
  }
  const totalBudget = sumOf(rows.map((l) => num(l.budget_cost)))
  const totalEarned = sumOf(rows.map((l) => (Number(l.done_quantity) > 0 ? num(l.earned) : null)))
  const bands = !sorter && sections.length > 1
  const exportShown = () =>
    exportCsv(
      `boq-budget-${appNow().toISOString().slice(0, 10)}.csv`,
      ['Code', 'Work', 'Section', 'Unit', 'Planned', 'Done', '% done', 'Budget', 'Earned', 'Labour man-days', 'Labour spent', 'Labour vs earned'],
      rows.map((l) => [
        l.boq_code ?? '', l.work, l.section, l.unit, l.planned_quantity, l.done_quantity, l.percent_done ?? '', l.budget_cost ?? '',
        Number(l.done_quantity) > 0 ? l.earned ?? '' : '', l.labour_man_days, l.labour_cost ?? '', l.labour_difference ?? '',
      ]),
    )
  const goTo = (p: number) => {
    setPage(String(p))
    document.getElementById('boq-lines')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <DprSection icon={Calculator} title="BOQ lines" meta={any ? `${rows.length} of ${lines.length}` : lines.length} id="boq-lines">
      <ListToolbar
        guide="budget.filters"
        right={
          <>
            <ActionButton kind="export-excel" size="default" disabled={rows.length === 0} onClick={exportShown} title="The lines shown, as a CSV file (opens in Excel)">
              <span className="hidden sm:inline">{any ? 'Export shown' : 'Export lines'}</span>
            </ActionButton>
            <SortSelect value={sort} options={SORTS} onChange={reset(setSort)} label="Sort the lines" />
          </>
        }
      >
        <SearchBox value={q} onChange={reset(setQ)} placeholder="Search work or code" label="Search BOQ lines" />
        {sections.length > 1 && <FilterPill icon={Layers} label="Section" allLabel="All sections" value={sec} options={secOptions} onChange={reset(setSec)} />}
        <FilterPill icon={Gauge} label="Done" allLabel="However far" value={prog} options={progOptions} onChange={reset(setProg)} />
        <FilterPill icon={HardHat} label="Labour" allLabel="Any labour" value={lab} options={labOptions} onChange={reset(setLab)} />
        <ClearButton show={any} onClick={clear} />
      </ListToolbar>

      {rows.length === 0 ? (
        <NoMatch noun="BOQ line" onClear={clear} />
      ) : (
        <div className="overflow-x-auto rounded-xl border bg-card [contain:inline-size]" data-guide="budget.lines">
          <table className="w-full text-sm md:min-w-[820px]">
            <thead className="bg-muted/50 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Work</th>
                <th className="w-32 px-3 py-2 text-left font-medium md:w-48" aria-sort={sort === 'done' ? 'descending' : undefined}>
                  <SortHead label="Done" value="done" sort={sort} onSort={reset(setSort)} />
                </th>
                <th className="hidden px-3 py-2 text-right font-medium md:table-cell" aria-sort={sort === 'budget' ? 'descending' : undefined}>
                  <SortHead label="Budget" value="budget" sort={sort} onSort={reset(setSort)} right />
                </th>
                <th className="hidden px-3 py-2 text-right font-medium md:table-cell" aria-sort={sort === 'earned' ? 'descending' : undefined}>
                  <SortHead label="Earned" value="earned" sort={sort} onSort={reset(setSort)} right />
                </th>
                <th className="hidden px-3 py-2 text-right font-medium md:table-cell">Labour spent</th>
                <th className="hidden px-3 py-2 text-right font-medium md:table-cell" aria-sort={sort === 'over' ? 'ascending' : undefined}>
                  <SortHead label="Labour vs earned" value="over" sort={sort} onSort={reset(setSort)} right />
                </th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {paged.shown.map((l, i) => {
                const started = Number(l.done_quantity) > 0
                const newSection = bands && (i === 0 || paged.shown[i - 1].sectionId !== l.sectionId)
                const inSection = newSection ? rows.filter((x) => x.sectionId === l.sectionId) : []
                const secBudget = newSection ? sumOf(inSection.map((x) => num(x.budget_cost))) : null
                const secEarned = newSection ? sumOf(inSection.map((x) => (Number(x.done_quantity) > 0 ? num(x.earned) : null))) : null
                return (
                  <React.Fragment key={l.id}>
                    {newSection && (
                      <tr className="bg-muted/40">
                        <th scope="rowgroup" colSpan={2} className="px-3 py-1.5 text-left text-xs font-semibold">
                          {l.section} <span className="font-normal text-muted-foreground">· {inSection.length}</span>
                        </th>
                        <td className="hidden px-3 py-1.5 text-right text-xs font-semibold tabular-nums md:table-cell">{secBudget === null ? '—' : compact(secBudget)}</td>
                        <td className="hidden px-3 py-1.5 text-right text-xs font-semibold tabular-nums text-info md:table-cell">{secEarned === null ? '—' : compact(secEarned)}</td>
                        <td colSpan={2} className="hidden md:table-cell" />
                      </tr>
                    )}
                    <tr className="hover:bg-muted/30">
                      <td className="px-3 py-2">
                        <span className="flex items-baseline gap-1.5">
                          {l.boq_code && <span className="shrink-0 rounded bg-muted px-1 text-[11px] font-medium text-muted-foreground tabular-nums">{l.boq_code}</span>}
                          <button type="button" onClick={() => setOpened(l)} title="What made this line's figures"
                            className={cn('text-left font-medium underline-offset-2 hover:underline', !started && 'text-muted-foreground')}>{l.work}</button>
                        </span>
                        {!bands && sections.length > 1 && <span className="mt-0.5 block text-[11px] text-muted-foreground">{l.section}</span>}
                        {/* Phones: the money folds under the name (docs/DESIGN.md section 8). */}
                        <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs tabular-nums md:hidden">
                          <span className="text-muted-foreground">
                            {started && l.earned !== null ? <span className="font-semibold text-info">{compact(Number(l.earned))}</span> : '—'} / {l.budget_cost === null ? '—' : compact(Number(l.budget_cost))}
                          </span>
                          {num(l.labour_difference) !== null && <GapPill diff={num(l.labour_difference)} size="xs" />}
                        </span>
                      </td>
                      <td className="px-3 py-2">
                        <Progress l={l} />
                      </td>
                      <td className="hidden px-3 py-2 text-right tabular-nums md:table-cell">{l.budget_cost === null ? <span className="text-muted-foreground">—</span> : formatRupees(l.budget_cost)}</td>
                      <td className="hidden px-3 py-2 text-right font-medium tabular-nums text-info md:table-cell">
                        {started && l.earned !== null ? formatRupees(l.earned) : <span className="font-normal text-muted-foreground">—</span>}
                      </td>
                      <td className="hidden px-3 py-2 text-right tabular-nums md:table-cell">
                        {Number(l.labour_man_days) > 0 ? (
                          <>
                            {l.labour_cost ? formatRupees(l.labour_cost) : <span className="text-draft">no wage</span>}
                            <span className="block text-[11px] text-muted-foreground">
                              <HardHat className="mr-0.5 inline size-3 align-[-2px]" aria-hidden />
                              {formatQuantity(l.labour_man_days)} md
                            </span>
                          </>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </td>
                      <td className="hidden px-3 py-2 text-right md:table-cell">
                        <GapPill diff={num(l.labour_difference)} size="xs" />
                      </td>
                    </tr>
                  </React.Fragment>
                )
              })}
            </tbody>
            <tfoot className="border-t bg-muted/40 text-xs font-semibold">
              <tr>
                <td className="px-3 py-2" colSpan={2}>
                  {any ? `Total of the ${rows.length} shown` : `Total of ${rows.length} lines`}
                  <span className="ml-2 font-semibold tabular-nums md:hidden">
                    <span className="text-info">{totalEarned === null ? '—' : compact(totalEarned)}</span> / {totalBudget === null ? '—' : compact(totalBudget)}
                  </span>
                </td>
                <td className="hidden px-3 py-2 text-right tabular-nums md:table-cell">{totalBudget === null ? '—' : compact(totalBudget)}</td>
                <td className="hidden px-3 py-2 text-right tabular-nums text-info md:table-cell">{totalEarned === null ? '—' : compact(totalEarned)}</td>
                <td colSpan={2} className="hidden md:table-cell" />
              </tr>
            </tfoot>
          </table>
        </div>
      )}
      <Pager className="mt-2" {...paged} noun="lines" size={size} onPage={goTo} onSize={(n) => { setSize(String(n)); setPage('1') }} />
      <LineDetailSheet projectId={projectId} line={opened} onOpenChange={(o) => { if (!o) { setOpened(null); setLineParam('') } }} />
    </DprSection>
  )
}

/** The nudge (21 Nov 2026): the days of labour on no line that Mesiri has a line for, put on them in one tap. The
 *  suggestion follows the trade (masons to masonry, concrete, plaster; never the conduits), so a tap never puts a
 *  day where its trade did not work; days with no suggestion stay below for a person to pick. */
function SuggestedBar({ groups, saving, onPut }: { groups: LabourGroup[]; saving: boolean; onPut: () => void }) {
  const ready = groups.filter((g) => g.suggested_line_id && Number(g.not_on_a_line.man_days) > 0 && !g.over_allocated)
  if (!ready.length) return null
  const cost = ready.reduce((sum, g) => sum + Number(g.not_on_a_line.cost ?? 0), 0)
  return (
    <div className="mb-2 flex flex-wrap items-center gap-3 rounded-xl border border-info/30 bg-info-soft px-3 py-2.5 text-sm" data-guide="budget.suggested">
      <Sparkles className="size-4 shrink-0 text-info" aria-hidden />
      <span className="min-w-0 flex-1">
        <span className="font-semibold tabular-nums">{ready.length}</span> {ready.length === 1 ? 'day' : 'days'} of labour
        {cost > 0 && <> (<span className="tabular-nums">{formatRupees(String(Math.round(cost)))}</span>)</>} have a line Mesiri suggests
      </span>
      <Button size="sm" className="gap-1.5" disabled={saving} onClick={onPut}>
        <Sparkles className="size-3.5" aria-hidden /> Put on suggested lines
      </Button>
    </div>
  )
}

/** Labour to check, ten to a page (UX-36). */
function LabourList({ groups, lines, saving, onSave }: { groups: LabourGroup[]; lines: Line[]; saving: boolean; onSave: (g: LabourGroup, next: { line_id: string; man_days: string }[]) => void }) {
  const [pageS, setPage] = useUrlState<string>('lpage', '1')
  const [site, setSite] = useUrlState<string>('lsite', '')
  const [trade, setTrade] = useUrlState<string>('ltrade', '')
  const pass = (g: LabourGroup, skip?: string) => (skip === 'site' || !site || (g.site_id ?? '') === site) && (skip === 'trade' || !trade || g.trade_key === trade)
  const shownGroups = groups.filter((g) => pass(g))
  const paged = usePaged(shownGroups, Number(pageS) || 1, 10)
  const uniq = (key: (g: LabourGroup) => string, label: (g: LabourGroup) => string, skip: string): FilterOption[] =>
    [...new Map(groups.map((g) => [key(g), label(g)])).entries()].map(([value, l]) => ({ value, label: l, count: groups.filter((g) => key(g) === value && pass(g, skip)).length }))
  const sites = uniq((g) => g.site_id ?? '', (g) => g.site_name ?? 'No site', 'site')
  const trades = uniq((g) => g.trade_key, (g) => (g.trade ? g.trade[0].toUpperCase() + g.trade.slice(1) : 'No trade said'), 'trade')
  const pick = (set: (v: string) => void) => (v: string) => {
    set(v)
    setPage('1')
  }
  return (
    <>
      {(sites.length > 1 || trades.length > 1) && (
        <div className="mb-2 flex flex-wrap items-center gap-2">
          {sites.length > 1 && <FilterPill icon={MapPin} label="Site" allLabel="All sites" value={site} options={sites} onChange={pick(setSite)} />}
          {trades.length > 1 && <FilterPill icon={HardHat} label="Trade" allLabel="Every trade" value={trade} options={trades} onChange={pick(setTrade)} />}
          {(site || trade) && (
            <Button variant="ghost" size="sm" className="h-9 gap-1" onClick={() => { setSite(''); setTrade(''); setPage('1') }}>
              <X className="size-3.5" aria-hidden /> Clear
            </Button>
          )}
        </div>
      )}
      <ul className="divide-y rounded-xl border bg-card text-sm">
        {paged.shown.map((g) => (
          <LabourGroupRow
            key={`${g.site_id}|${g.date}|${g.trade_key}|${g.not_on_a_line.man_days}|${g.suggested_line_id}`}
            group={g}
            lines={lines}
            readOnly={false}
            saving={saving}
            onSave={(next) => onSave(g, next)}
          />
        ))}
      </ul>
      <Pager
        className="mt-2"
        {...paged}
        noun={site || trade ? `of ${groups.length} days of labour` : 'days of labour'}
        onPage={(p) => {
          setPage(String(p))
          document.getElementById('labour-to-lines')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
        }}
      />
    </>
  )
}

function ProjectPicker() {
  // UX-35: the one project picker (cards, one project opens by itself).
  return <ProjectPickList to={(id) => `/cost/budget?project=${id}`} empty="No projects yet." />
}

export default function CostBudgetPage() {
  const { me } = useAuth()
  const { scope } = useScope()
  usePageTitle('Budget vs actual')
  const allowed = maySeeBoq(me?.role)
  const projectId = scope.mode !== 'portfolio' ? scope.projectId : null
  const q = useQuery({
    queryKey: ['cost', 'budget', projectId],
    queryFn: () => fetchProjectBudget(projectId!),
    enabled: allowed && !!projectId,
  })
  const labour = useQuery({
    queryKey: ['cost', 'labour', projectId, 'unallocated'],
    queryFn: () => fetchProjectLabour(projectId!, { to_confirm: true }),
    enabled: allowed && !!projectId,
  })
  const qc = useQueryClient()
  const toast = useToast()
  const putLabour = useMutation({
    mutationFn: ({ group, lines }: { group: LabourGroup; lines: { line_id: string; man_days: string }[] }) =>
      putLabourOnLines(projectId!, group, lines),
    onSuccess: () => {
      toast.success('Labour put on the BOQ line')
      qc.invalidateQueries({ queryKey: ['cost'] })
    },
    onError: (err: unknown) => toast.error('Could not put the labour on the line', apiErrorMessage(err)),
  })
  const putSuggested = useMutation({
    mutationFn: () => putLabourOnSuggestions(projectId!),
    onSuccess: (r) => {
      toast.success(
        `${r.rows} ${r.rows === 1 ? 'day' : 'days'} of labour put on their lines (${formatRupees(r.cost)})`,
        r.still_off.rows ? `${r.still_off.rows} still need a line picked` : undefined,
      )
      qc.invalidateQueries({ queryKey: ['cost'] })
    },
    onError: (err: unknown) => toast.error('Could not put the labour on its lines', apiErrorMessage(err)),
  })

  if (!allowed) {
    return (
      <NoAccess roles={MONEY_PEOPLE} />
    )
  }
  const header = (
    <DprHeader back={{ to: '/cost', label: 'Overview' }} crumb="Cost control" title="Budget vs actual" date={projectId ? (q.data ? `${shortDay(q.data.date_from)} – ${shortDay(q.data.date_to)}` : undefined) : 'Pick a project'} action={projectId ? <CostExportButton projectId={projectId} projectName={scope.mode !== 'portfolio' ? scope.projectName : undefined} /> : undefined} />
  )
  if (!projectId) {
    return (
      <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
        {header}
        <ProjectPicker />
      </div>
    )
  }
  if (q.isError) return <PageError message="Budget vs actual could not be loaded." onRetry={() => q.refetch()} back={{ to: '/today', label: 'Today' }} />
  const b = q.data
  const lines: Line[] = b ? b.boq.sections.flatMap((s) => s.lines.map((l) => ({ ...l, section: s.name, sectionId: s.id }))) : []
  const kinds = b?.kinds ?? []
  const budget = sumOf(kinds.map((k) => num(k.budget)))
  const earned = sumOf(kinds.map((k) => num(k.earned)))
  const spent = kinds.reduce((n, k) => n + Number(k.actual), 0)
  const gap = sumOf(kinds.map((k) => num(k.difference)))
  // UX-93: the project's one forecast (all its cost, the part on no line included), as every page shows it.
  const forecast = num(b?.project.forecast ?? null)
  const forecastGap = num(b?.project.forecast_difference ?? null)
  const outside = num(b?.project.not_on_a_kind ?? null)
  const ratio = (a: number | null, z: number | null) => (a !== null && z ? a / z : undefined)
  const totals = [
    { label: 'Budget', kind: 'money' as const, value: budget === null ? '—' : compact(budget) },
    { label: 'Earned', icon: Gauge, tone: 'info' as const, value: earned === null ? '—' : compact(earned), share: ratio(earned, budget), hint: budget && earned !== null ? `${Math.round((earned / budget) * 100)}% of budget` : undefined },
    {
      label: 'Spent', kind: 'money' as const, value: compact(spent), share: ratio(spent, budget),
      tone: gap !== null && gap < 0 ? ('bad' as const) : ('default' as const),
      hint: Number(b?.total_spent ?? 0) > spent ? `+ ${compact(Number(b!.total_spent) - spent)} elsewhere` : undefined,
    },
    {
      label: gap !== null && gap < 0 ? 'Over' : 'Under', icon: gap !== null && gap < 0 ? TriangleAlert : CircleCheck,
      tone: gap === null ? ('default' as const) : gap < 0 ? ('bad' as const) : ('good' as const),
      value: gap === null ? '—' : compact(Math.abs(gap)), hint: 'earned − spent',
    },
    {
      label: 'At finish', icon: forecastGap !== null && forecastGap < 0 ? TrendingUp : TrendingDown,
      tone: forecastGap === null ? ('default' as const) : forecastGap < 0 ? ('bad' as const) : ('good' as const),
      value: forecast === null ? '—' : compact(forecast),
      hint: forecastGap === null ? 'too early to tell'
        : `${compact(Math.abs(forecastGap))} ${forecastGap < 0 ? 'over' : 'under'} budget${outside ? ` · with ${compact(outside)} not on a line` : ''}`,
    },
  ]

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      {header}
      {q.isLoading || !b ? (
        <Skeleton className="h-48 rounded-lg" />
      ) : lines.length === 0 ? (
        <div className="flex flex-col items-start gap-3 rounded-lg border border-dashed px-4 py-6" data-guide="budget.empty">
          <p className="font-medium">This project has no BOQ yet.</p>
          <Link to={`/projects/${projectId}/boq`} className="text-sm font-medium underline underline-offset-2">
            Open the BOQ
          </Link>
        </div>
      ) : (
        <>
          <KpiStrip guide="budget.totals" stats={totals} />

          {(b.work_not_on_a_line > 0 || Number(b.labour_not_on_a_line.man_days) > 0) && (
            <div className="grid gap-2 md:grid-cols-2">
              {b.work_not_on_a_line > 0 && (
                <ActionChip icon={ClipboardCheck} to={`/projects/${projectId}/boq`} action="Put on lines">
                  <span className="font-semibold tabular-nums">{b.work_not_on_a_line}</span> {b.work_not_on_a_line === 1 ? 'piece of work' : 'pieces of work'} not on a BOQ line
                  <span className="text-muted-foreground"> · earns nothing</span>
                </ActionChip>
              )}
              {Number(b.labour_not_on_a_line.man_days) > 0 && (
                <ActionChip icon={HardHat} to="#labour-to-lines" action="Check">
                  <span className="font-semibold tabular-nums">{compact(Number(b.labour_not_on_a_line.cost))}</span> labour not on a line
                  <span className="text-muted-foreground tabular-nums"> · {formatQuantity(b.labour_not_on_a_line.man_days)} man-days</span>
                </ActionChip>
              )}
            </div>
          )}

          <div className="grid gap-3 md:grid-cols-3" data-guide="budget.kinds">
            {b.kinds.map((k) => (
              <KindCard key={k.kind} k={k} />
            ))}
          </div>

          {(b.other_spending.length > 0 || Number(b.not_set) > 0) && (
            <div className="flex flex-wrap items-center gap-1.5 text-xs">
              <span className="text-muted-foreground">Also spent, no BOQ rate:</span>
              {b.other_spending.map((o) => (
                <span key={o.key} className="inline-flex items-center gap-1.5 rounded-full border bg-card px-2 py-0.5 tabular-nums">
                  <span className={cn('size-2 rounded-full', CENTRE_COLOURS[o.key] ?? CENTRE_COLOURS.other)} aria-hidden />
                  {o.label} <span className="font-semibold">{compact(Number(o.amount))}</span>
                </span>
              ))}
              {Number(b.not_set) > 0 && (
                <span className="inline-flex items-center gap-1.5 rounded-full border border-dashed bg-card px-2 py-0.5 tabular-nums">
                  <span className={cn('size-2 rounded-full', CENTRE_COLOURS.not_set)} aria-hidden />
                  Not set <span className="font-semibold">{compact(Number(b.not_set))}</span>
                </span>
              )}
              <Link to="/cost/centres" className="inline-flex items-center gap-0.5 font-semibold hover:underline">
                Cost centres <ArrowRight className="size-3" aria-hidden />
              </Link>
            </div>
          )}

          <BoqLinesTable lines={lines} projectId={b!.project_id} />

          <div id="labour-to-lines" className="scroll-mt-20" data-guide="budget.labour">
            <DprSection icon={HardHat} title="Labour to check" meta={labour.data?.groups.length || undefined}>
              {labour.isLoading ? (
                <Skeleton className="h-24 rounded-lg" />
              ) : labour.isError ? (
                <div className="flex items-center gap-3 rounded-xl border bg-card px-3 py-2.5 text-sm">
                  <TriangleAlert className="size-4 text-draft" aria-hidden />
                  <span className="flex-1">The labour list could not be loaded.</span>
                  <Button variant="outline" size="sm" onClick={() => labour.refetch()}>
                    Try again
                  </Button>
                </div>
              ) : (labour.data?.groups.length ?? 0) === 0 ? (
                <p className="flex items-center gap-2 rounded-xl border bg-card px-3 py-2.5 text-sm">
                  <CircleCheck className="size-4 text-success" aria-hidden /> All labour is on its BOQ lines.
                </p>
              ) : (
                <>
                  <SuggestedBar groups={labour.data!.groups} saving={putSuggested.isPending} onPut={() => putSuggested.mutate()} />
                  <LabourList groups={labour.data!.groups} lines={lines} saving={putLabour.isPending || putSuggested.isPending} onSave={(g, next) => putLabour.mutate({ group: g, lines: next })} />
                </>
              )}
            </DprSection>
          </div>
        </>
      )}
    </div>
  )
}
