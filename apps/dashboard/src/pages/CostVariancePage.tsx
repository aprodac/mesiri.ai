import * as React from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import type { LucideIcon } from 'lucide-react'
import {
  ArrowDownWideNarrow, ArrowRight, CircleCheck, CircleDashed, Eye, HardHat, Package, Ruler, Search,
  ArrowDown, ArrowUpDown, Layers, TrafficCone, TriangleAlert, Wrench, X,
} from 'lucide-react'
import { FilterPill, type FilterOption } from '@/components/requests/parts'
import { ActionButton } from '@/components/page/page-kit'
import { exportCsv } from '@/lib/export'
import { MONEY_PEOPLE } from '@/lib/permissions'
import { KpiStrip, Legend, NoAccess } from '@/components/page/page-kit'
import { Pager } from '@/components/page/pager'
import { DprHeader, DprSection, PageError } from '@/components/dpr-page'
import { CostExportButton } from '@/components/cost/export-button'
import { Button } from '@/components/ui/button'
import { DatePicker } from '@/components/ui/date-picker'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { formatQuantity, formatRupees, maySeeBoq } from '@/lib/boq'
import { fetchProjectVariance, type VarianceColour, type VarianceDay, type VarianceLine, type VarianceReason } from '@/lib/cost'
import { compact } from '@/lib/expenses'
import { usePagedUrl } from '@/lib/paging'
import { usePageTitle } from '@/lib/page-title'
import { useScope } from '@/lib/ScopeContext'
import { COLOUR_DOT, COLOUR_TEXT, COLOUR_WORD } from '@/lib/cost-colours'
import { cn } from '@/lib/utils'
import { appNow } from '@/lib/clock'
import { ProjectPickList } from '@/components/schedule/project-picker'

// CC-07: green / amber / red per BOQ line. For a period, each line's labour budget earned by the work measured
// (done x labour rate) against the labour put on the line (CC-05): green when it earned at least what it cost,
// amber within 10%, red below. A line that cannot be judged is grey and says why, never coloured. Worst first.
// Backend: GET /cost/projects/{id}/variance (domains/costing/variance.py).

// UX-39 (18 Nov, "a full UI/UX upgrade"): the page reads by colour. A traffic light with labour earned against spent
// on one scale; a KPI strip; one bar of the lines by colour that filters the table; the days as coloured tiles to
// tap; the lines as a table with search, colour filter, sort and pages, each with its labour against what the work
// earned as a bar and the reason as a short chip with its fix. A site engineer still sees no money (D-CC4).
// UX-40: section and "need a fix" filters, header sort, export of the lines shown, "/" to search, a line opens in
// Budget vs actual, and each figure says what changed against the same number of days before.

const TONE = { green: 'good', amber: 'attention', red: 'bad', grey: 'default' } as const

/** The colours, worst first, with their icon and pill. */
const LOOK: Record<VarianceColour, { icon: LucideIcon; pill: string; soft: string; ring: string }> = {
  red: { icon: TriangleAlert, pill: 'bg-destructive/10 text-destructive', soft: 'bg-destructive/[0.07]', ring: 'ring-destructive/40' },
  amber: { icon: Eye, pill: 'bg-draft-soft text-draft', soft: 'bg-draft-soft/60', ring: 'ring-draft/40' },
  green: { icon: CircleCheck, pill: 'bg-success-soft text-success', soft: 'bg-success-soft/60', ring: 'ring-success/40' },
  grey: { icon: CircleDashed, pill: 'bg-muted text-muted-foreground', soft: 'bg-muted/60', ring: 'ring-foreground/15' },
}
const ORDER: VarianceColour[] = ['red', 'amber', 'green', 'grey']
/** Lines not judged because something is missing that a person can add. */
const NEEDS_FIX = new Set<VarianceReason>(['no_labour', 'no_labour_rate', 'no_wage'])

/** A column header that sorts; pressed again, back to worst first. */
function SortHead({ label, on, onClick, left }: { label: string; on: boolean; onClick: () => void; left?: boolean }) {
  return (
    <button type="button" onClick={onClick} className={cn('inline-flex items-center gap-1 rounded hover:text-foreground', !left && 'flex-row-reverse', on && 'font-semibold text-foreground')}>
      {label}
      {on ? <ArrowDown className="size-3" aria-hidden /> : <ArrowUpDown className="size-3 opacity-40" aria-hidden />}
    </button>
  )
}

/** Why a line is its colour, in two or three words (the full sentence is its tooltip). */
const REASON: Record<VarianceReason, string> = {
  over_budget: 'More labour than the work allows',
  near_budget: 'A little over, within 10%',
  within_budget: 'Within the labour allowed',
  labour_no_work: 'Labour, no work measured',
  no_labour: 'No labour on it',
  no_labour_rate: 'No labour rate',
  no_wage: 'No wage set',
}

function isoDay(d: Date): string {
  const off = d.getTimezoneOffset();
  return new Date(d.getTime() - off * 60000).toISOString().slice(0, 10);
}
function daysAgo(n: number): string {
  const d = appNow();
  d.setDate(d.getDate() - n);
  return isoDay(d);
}
function formatDay(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString('en-IN', {
        weekday: 'short',
        day: 'numeric',
        month: 'short',
      });
}

const PERIODS = [
  {
    key: 'yesterday',
    label: 'Yesterday',
    from: () => daysAgo(1),
    to: () => daysAgo(1),
  },
  {
    key: 'today',
    label: 'Today',
    from: () => daysAgo(0),
    to: () => daysAgo(0),
  },
  {
    key: '7d',
    label: 'Last 7 days',
    from: () => daysAgo(6),
    to: () => daysAgo(0),
  },
  {
    key: '30d',
    label: 'Last 30 days',
    from: () => daysAgo(29),
    to: () => daysAgo(0),
  },
] as const;

/** D-CC4: why a line is its colour for a site engineer: quantities and man-days, never rupees or rates. */
function siteReasonText(l: VarianceLine): string {
  const done = `${formatQuantity(l.done_quantity)} ${l.unit}`;
  const md = `${formatQuantity(l.labour_man_days)} man-days`;
  switch (l.reason) {
    case 'over_budget':
      return `${md} for ${done}: more labour than the BOQ allows for that work.`;
    case 'near_budget':
      return `${md} for ${done}: a little more labour than the BOQ allows, within 10%.`;
    case 'within_budget':
      return `${md} for ${done}: within what the BOQ allows.`;
    case 'labour_no_work':
      return `${md} on this line and no ${l.unit} measured.`;
    case 'no_labour':
      return `${done} measured, but no labour is put on this line yet.`;
    case 'no_labour_rate':
      return 'The BOQ has nothing to compare the labour with on this line yet.';
    case 'no_wage':
      return `${md}: the office has not set the wages, so it cannot be judged.`;
  }
}

/** Why a line is its colour, in the words the GM used ("₹6,400 of labour: was the work done?"). */
function reasonText(l: VarianceLine): string {
  const done = `${formatQuantity(l.done_quantity)} ${l.unit}`;
  const perUnit =
    l.cost_per_unit && l.labour_rate
      ? `${formatRupees(l.cost_per_unit)} per ${l.unit} against the budget ${formatRupees(l.labour_rate)}`
      : '';
  switch (l.reason) {
    case 'over_budget':
      return `${formatRupees(l.labour_cost)} of labour for ${done}: ${perUnit}.`;
    case 'near_budget':
      return `${formatRupees(l.labour_cost)} of labour for ${done}: ${perUnit}, within 10%.`;
    case 'within_budget':
      return `${formatRupees(l.earned_labour)} of work for ${formatRupees(l.labour_cost)} of labour: ${perUnit}.`;
    case 'labour_no_work':
      return `${formatRupees(l.labour_cost)} of labour (${formatQuantity(l.labour_man_days)} man-days) and no ${l.unit} measured on this line.`;
    case 'no_labour':
      return `${done} measured, but no labour is put on this line, so what it cost is not known.`;
    case 'no_labour_rate':
      return 'This BOQ line has no labour rate, so there is nothing to set the labour against.';
    case 'no_wage':
      return `${formatQuantity(l.labour_man_days)} man-days with no wage, so what they cost is not known.`;
  }
}


const num = (v: string | null | undefined) => (v === null || v === undefined ? null : Number(v))

/** Labour spent against what the work earned, on one scale: earned in blue, spent in its colour, a tick at earned. */
function EarnedSpent({ earned, spent, colour }: { earned: number | null; spent: number | null; colour: VarianceColour }) {
  const scale = Math.max(earned ?? 0, spent ?? 0)
  const pct = (v: number | null) => (v !== null && scale > 0 ? Math.min(100, (v / scale) * 100) : 0)
  const h = 'h-1.5'
  return (
    <span className="flex flex-col gap-1" aria-hidden>
      <span className={cn('block overflow-hidden rounded-full bg-muted', h)}>
        <span className={cn('block h-full rounded-full bg-info')} style={{ width: `${pct(earned)}%` }} />
      </span>
      <span className={cn('relative block overflow-visible rounded-full bg-muted', h)}>
        <span className={cn('block h-full rounded-full', COLOUR_DOT[colour])} style={{ width: `${pct(spent)}%` }} />
        {earned !== null && spent !== null && spent > earned && (
          <span className="absolute -top-0.5 -bottom-0.5 w-0.5 rounded bg-foreground/70" style={{ left: `${pct(earned)}%` }} />
        )}
      </span>
    </span>
  )
}

/** Under (green) or over (red); amber when within 10%. */
function GapPill({ line }: { line: Pick<VarianceLine, 'difference' | 'colour'> }) {
  const d = num(line.difference)
  if (d === null) return <span className="text-muted-foreground">—</span>
  const look = LOOK[line.colour === 'grey' ? (d < 0 ? 'red' : 'green') : line.colour]
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full px-1.5 py-px text-[11px] font-semibold whitespace-nowrap tabular-nums', look.pill)}>
      <look.icon className="size-3" aria-hidden />
      {compact(Math.abs(d))} {d < 0 ? 'over' : 'under'}
    </span>
  )
}

/** The reason as a chip; the full sentence on hover; the fix as a link. */
function ReasonChip({ line, projectId, siteView }: { line: VarianceLine; projectId: string; siteView: boolean }) {
  const fix =
    siteView ? null
    : line.reason === 'no_labour' ? { to: `/cost/budget?project=${projectId}#labour-to-lines`, label: 'Put labour on it' }
    : line.reason === 'no_labour_rate' ? { to: `/projects/${projectId}/boq`, label: 'Set the rate' }
    : line.reason === 'no_wage' ? { to: '/labour', label: 'Set wages' }
    : null
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <span
        className={cn('inline-flex items-center gap-1 rounded-md px-1.5 py-px text-[11px] font-medium', LOOK[line.colour].pill)}
        title={siteView ? siteReasonText(line) : reasonText(line)}
      >
        {React.createElement(LOOK[line.colour].icon, { className: 'size-3', 'aria-hidden': true })}
        {REASON[line.reason]}
      </span>
      {fix && (
        <Link to={fix.to} className="inline-flex items-center gap-0.5 text-[11px] font-semibold hover:underline" onClick={(e) => e.stopPropagation()}>
          {fix.label} <ArrowRight className="size-3" aria-hidden />
        </Link>
      )}
    </span>
  )
}

/** The days as tiles in their colour; one tapped shows only that day. */
function DayTiles({ days, picked, onPick, money }: { days: VarianceDay[]; picked: string | null; onPick: (d: string | null) => void; money: boolean }) {
  return (
    <ul className="flex gap-1.5 overflow-x-auto pb-1 [contain:inline-size]" aria-label="Each day">
      {days.map((d) => {
        const on = picked === d.date
        const earned = num(d.earned_labour)
        const spent = num(d.labour_cost)
        return (
          <li key={d.date} className="shrink-0">
            <button
              type="button"
              onClick={() => onPick(on ? null : d.date)}
              aria-pressed={on}
              title={`${formatDay(d.date)}: ${COLOUR_WORD[d.colour]}`}
              className={cn(
                'flex w-[5.5rem] flex-col gap-1 rounded-lg border bg-card px-2 py-1.5 text-left transition',
                LOOK[d.colour].soft,
                on ? 'ring-2 ring-foreground/70' : 'hover:ring-1 hover:ring-foreground/20',
              )}
            >
              <span className="flex items-center justify-between text-[11px] text-muted-foreground">
                {formatDay(d.date).split(' ').slice(0, 2).join(' ')}
                <span className={cn('size-2 rounded-full', COLOUR_DOT[d.colour])} aria-hidden />
              </span>
              <span className={cn('text-xs font-semibold', COLOUR_TEXT[d.colour])}>{COLOUR_WORD[d.colour]}</span>
              {money && spent !== null ? (
                <EarnedSpent earned={earned} spent={spent} colour={d.colour} />
              ) : money && Number(d.attendance_cost) > 0 ? (
                <span className="truncate text-[10px] text-draft">{compact(Number(d.attendance_cost))} off lines</span>
              ) : (
                <span className="text-[10px] text-muted-foreground">{d.lines.red + d.lines.amber + d.lines.green} lines</span>
              )}
            </button>
          </li>
        )
      })}
    </ul>
  )
}

function ProjectPicker() {
  // UX-35: the one project picker (cards, one project opens by itself).
  return <ProjectPickList to={(id) => `/cost/green-red?project=${id}`} empty="No projects yet." />
}

const SORTS: { value: string; label: string; key?: (l: VarianceLine) => number | string }[] = [
  { value: '', label: 'Worst first' },
  { value: 'over', label: 'Most over', key: (l) => num(l.difference) ?? Number.MAX_SAFE_INTEGER },
  { value: 'mandays', label: 'Most man-days', key: (l) => -Number(l.labour_man_days) },
  { value: 'spent', label: 'Most labour spent', key: (l) => -(num(l.labour_cost) ?? 0) },
  { value: 'code', label: 'BOQ order', key: (l) => `${l.boq_code ?? '~'} ${l.work}` },
]

export default function CostVariancePage() {
  const { me } = useAuth()
  const { scope } = useScope()
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  usePageTitle('Green / red')
  // D-CC4: a site engineer sees their own site's colours and quantities (the API takes the money out).
  const siteView = !maySeeBoq(me?.role) && String(me?.role ?? '').toUpperCase() === 'SITE_ENGINEER'
  const allowed = maySeeBoq(me?.role) || siteView
  const projectId = scope.mode !== 'portfolio' ? scope.projectId : null
  const siteId = scope.mode === 'site' ? scope.siteId : undefined
  const periodKey = params.get('period') ?? '7d'
  const preset = PERIODS.find((p) => p.key === periodKey)
  const dateFrom = params.get('from') ?? (preset ?? PERIODS[2]).from()
  const dateTo = params.get('to') ?? (preset ?? PERIODS[2]).to()
  const colour = (params.get('colour') ?? '') as VarianceColour | ''
  const search = params.get('q') ?? ''
  const sort = params.get('sort') ?? ''
  const section = params.get('section') ?? ''
  const fixOnly = params.get('fix') === '1'
  const q = useQuery({
    queryKey: ['cost', 'variance', projectId, siteId, dateFrom, dateTo],
    queryFn: () => fetchProjectVariance(projectId!, { date_from: dateFrom, date_to: dateTo, site_id: siteId }),
    enabled: allowed && !!projectId,
  })
  // UX-40: the same number of days just before, to say what changed ("▲ 2 vs the 7 days before").
  const span = Math.round((Date.parse(`${dateTo}T00:00:00`) - Date.parse(`${dateFrom}T00:00:00`)) / 86_400_000) + 1
  const shift = (iso: string, days: number) => {
    const d = new Date(`${iso}T00:00:00`)
    d.setDate(d.getDate() - days)
    return isoDay(d)
  }
  const prevFrom = shift(dateFrom, span)
  const prevTo = shift(dateFrom, 1)
  const prev = useQuery({
    queryKey: ['cost', 'variance', projectId, siteId, prevFrom, prevTo],
    queryFn: () => fetchProjectVariance(projectId!, { date_from: prevFrom, date_to: prevTo, site_id: siteId }),
    enabled: allowed && !!projectId && span > 0 && span <= 92,
    retry: false,
  })

  const set = (changes: Record<string, string | null>) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        for (const [k, v] of Object.entries(changes)) {
          if (v === null || v === '') next.delete(k)
          else next.set(k, v)
        }
        return next
      },
      { replace: true },
    )
  const setPeriod = (key: string) => set({ period: key, from: null, to: null })
  // A tapped day shows only that day; tapped again, back to the period it came from.
  const pickDay = (day: string | null) =>
    day ? set({ period: 'day', from: day, to: day, back: params.get('back') ?? periodKey }) : set({ period: params.get('back') ?? '7d', from: null, to: null, back: null })

  const needle = search.trim().toLowerCase()
  const listed = React.useMemo(() => {
    const out = (q.data?.lines ?? []).filter(
      (l) =>
        (!colour || l.colour === colour) &&
        (!section || (l.section ?? '') === section) &&
        (!fixOnly || NEEDS_FIX.has(l.reason)) &&
        (!needle || `${l.boq_code ?? ''} ${l.work} ${l.section ?? ''}`.toLowerCase().includes(needle)),
    )
    const key = SORTS.find((x) => x.value === sort)?.key
    if (!key) return out
    return [...out].sort((a, b) => {
      const ka = key(a)
      const kb = key(b)
      return typeof ka === 'string' ? ka.localeCompare(String(kb)) : ka - Number(kb)
    })
  }, [q.data, colour, section, fixOnly, needle, sort])
  const paged = usePagedUrl(listed)
  const searchRef = React.useRef<HTMLInputElement>(null)
  // "/" jumps to the search, as in most tools (never while typing in a field).
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

  if (!allowed) return <NoAccess roles={MONEY_PEOPLE} />
  const header = (
    <DprHeader
      back={siteView ? { to: '/today', label: 'Today' } : { to: '/cost', label: 'Overview' }}
      crumb="Cost control"
      title="Green / red"
      date={projectId ? (dateFrom === dateTo ? formatDay(dateFrom) : `${formatDay(dateFrom)} – ${formatDay(dateTo)}`) : 'Pick a project'}
      action={
        projectId && !siteView ? (
          <CostExportButton projectId={projectId} projectName={scope.mode !== 'portfolio' ? scope.projectName : undefined} period={{ date_from: dateFrom, date_to: dateTo }} />
        ) : undefined
      }
    />
  )
  if (!projectId) {
    return (
      <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
        {header}
        <ProjectPicker />
      </div>
    )
  }
  if (q.isError) {
    const status = (q.error as { response?: { status?: number } } | null)?.response?.status
    if (siteView && status === 422) {
      return (
        <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
          {header}
          <p className="rounded-xl border border-dashed bg-card px-4 py-6 text-sm text-muted-foreground">Pick a site in the top bar</p>
        </div>
      )
    }
    return <PageError message="Green / red could not be loaded." onRetry={() => q.refetch()} back={{ to: '/today', label: 'Today' }} />
  }
  const v = q.data
  const money = !siteView && !v?.money_hidden
  const lines = v?.lines ?? []
  const count = (c: VarianceColour) => v?.summary.lines[c] ?? 0
  const judged = ORDER.reduce((n, c) => n + count(c), 0)
  const earned = num(v?.summary.earned_labour)
  const spent = num(v?.summary.labour_cost)
  const diff = num(v?.summary.difference)
  const any = !!(colour || search || section || fixOnly)
  const clear = () => set({ colour: null, q: null, section: null, fix: null })
  const sections = [...new Set(lines.map((l) => l.section ?? ''))].filter(Boolean)
  const sectionOptions: FilterOption[] = sections.map((x) => ({ value: x, label: x, count: lines.filter((l) => l.section === x).length }))
  const fixCount = lines.filter((l) => NEEDS_FIX.has(l.reason)).length
  // What changed against the days before: an arrow, the amount, and good (green) or bad (red).
  const p = prev.data
  const before = span === 1 ? 'the day before' : `the ${span} days before`
  const delta = (now: number | null, then: number | null, upIsBad: boolean, fmt: (n: number) => string = (n) => String(n)) => {
    if (now === null || then === null || !p) return undefined
    const d = now - then
    if (Math.abs(d) < 1e-9) return <span className="text-muted-foreground">same as {before}</span>
    const bad = upIsBad ? d > 0 : d < 0
    return (
      <span className={cn('font-medium', bad ? 'text-destructive' : 'text-success')} title={`Against ${before}`}>
        {d > 0 ? '▲' : '▼'} {fmt(Math.abs(d))} <span className="font-normal text-muted-foreground">vs before</span>
      </span>
    )
  }
  const exportShown = () =>
    exportCsv(
      `green-red-${dateFrom}-to-${dateTo}.csv`,
      money
        ? ['Code', 'Work', 'Section', 'Colour', 'Why', 'Done', 'Unit', 'Man-days', 'Labour earned', 'Labour spent', 'Gap (earned − spent)']
        : ['Code', 'Work', 'Section', 'Colour', 'Why', 'Done', 'Unit', 'Man-days'],
      listed.map((l) => {
        const base = [l.boq_code ?? '', l.work, l.section ?? '', COLOUR_WORD[l.colour], REASON[l.reason], l.done_quantity, l.unit, l.labour_man_days]
        return money ? [...base, l.earned_labour ?? '', l.labour_cost ?? '', l.difference ?? ''] : base
      }),
    )
  const sortBy = (value: string) => set({ sort: sort === value ? null : value })

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      {header}

      {/* Which days: presets, a custom range, or one day tapped below. */}
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Period" data-guide="gr.period">
        <div className="inline-flex rounded-lg border bg-card p-0.5">
          {PERIODS.map((p) => (
            <button
              key={p.key}
              type="button"
              onClick={() => setPeriod(p.key)}
              aria-pressed={periodKey === p.key}
              className={cn('rounded-md px-3 py-1 text-sm transition', periodKey === p.key ? 'bg-foreground font-semibold text-background' : 'text-muted-foreground hover:text-foreground')}
            >
              {p.label}
            </button>
          ))}
        </div>
        {periodKey === 'day' && (
          <span className="inline-flex items-center gap-1 rounded-full bg-foreground py-1 pr-1 pl-3 text-sm font-semibold text-background">
            {formatDay(dateFrom)}
            <button type="button" className="rounded-full p-0.5 hover:bg-background/20" aria-label="Back to the period" onClick={() => pickDay(null)}>
              <X className="size-3.5" />
            </button>
          </span>
        )}
        <span className={cn('inline-flex items-center gap-1 rounded-lg', periodKey === 'custom' && 'ring-2 ring-foreground/70')} aria-label="Pick your own dates">
          <DatePicker className="h-8 w-[136px] bg-card" value={periodKey === 'custom' ? dateFrom : ''} max={dateTo} placeholder="From" onChange={(d) => d && set({ period: 'custom', from: d, to: periodKey === 'custom' ? dateTo : d })} />
          <span className="text-muted-foreground">–</span>
          <DatePicker className="h-8 w-[136px] bg-card" value={periodKey === 'custom' ? dateTo : ''} min={periodKey === 'custom' ? dateFrom : undefined} placeholder="To" onChange={(d) => d && set({ period: 'custom', from: periodKey === 'custom' ? dateFrom : d, to: d })} />
        </span>
      </div>

      {q.isLoading || !v ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-28 rounded-xl" />
          <Skeleton className="h-20 rounded-xl" />
          <Skeleton className="h-64 rounded-xl" />
        </div>
      ) : (
        <>
          {/* The verdict: a traffic light, and the labour the work earned against what it cost. */}
          <section className={cn('relative flex flex-col gap-4 overflow-hidden rounded-xl border bg-card p-4 sm:flex-row sm:items-center', LOOK[v.summary.colour].soft)} data-guide="gr.stats">
            <div className="flex items-center gap-3">
              <span className="flex flex-col gap-1 rounded-xl bg-foreground/90 p-1.5 shadow-sm" aria-hidden>
                {(['red', 'amber', 'green'] as const).map((c) => (
                  <span key={c} className={cn('size-4 rounded-full transition', v.summary.colour === c ? cn(COLOUR_DOT[c], 'ring-2 ring-background/60') : 'bg-background/15')} />
                ))}
              </span>
              <div>
                <p className={cn('text-2xl leading-tight font-semibold', COLOUR_TEXT[v.summary.colour])}>{COLOUR_WORD[v.summary.colour]}</p>
                <p className="text-xs text-muted-foreground">
                  {judged} {judged === 1 ? 'line' : 'lines'} · {formatQuantity(v.labour.man_days)} man-days
                </p>
              </div>
            </div>
            {money && earned !== null && spent !== null ? (
              <div className="flex min-w-0 flex-1 flex-col gap-1.5 sm:max-w-xl sm:pl-4">
                <span className="grid grid-cols-[3.5rem_1fr_auto] items-center gap-2 text-xs">
                  <span className="text-muted-foreground">Earned</span>
                  <span className="block h-2.5 rounded-full bg-muted">
                    <span className="block h-full rounded-full bg-info" style={{ width: `${Math.min(100, (earned / Math.max(earned, spent || 1)) * 100)}%` }} />
                  </span>
                  <span className="min-w-16 text-right font-semibold tabular-nums text-info">{compact(earned)}</span>
                </span>
                <span className="grid grid-cols-[3.5rem_1fr_auto] items-center gap-2 text-xs">
                  <span className="text-muted-foreground">Spent</span>
                  <span className="relative block h-2.5 rounded-full bg-muted">
                    <span className={cn('block h-full rounded-full', COLOUR_DOT[v.summary.colour])} style={{ width: `${Math.min(100, (spent / Math.max(earned, spent || 1)) * 100)}%` }} />
                  </span>
                  <span className={cn('min-w-16 text-right font-semibold tabular-nums', COLOUR_TEXT[v.summary.colour])}>{compact(spent)}</span>
                </span>
              </div>
            ) : null}
            {money && diff !== null && (
              <span className={cn('inline-flex w-fit items-center gap-1.5 rounded-full px-3 py-1 text-sm font-semibold tabular-nums sm:ml-auto', diff < 0 ? LOOK.red.pill : LOOK.green.pill)}>
                {diff < 0 ? <TriangleAlert className="size-4" aria-hidden /> : <CircleCheck className="size-4" aria-hidden />}
                {compact(Math.abs(diff))} {diff < 0 ? 'over' : 'under'}
              </span>
            )}
          </section>

          <KpiStrip
            stats={[
              ...(money
                ? [
                    { label: 'Labour earned', icon: Ruler, tone: 'info' as const, value: earned === null ? '—' : compact(earned), hint: delta(earned, num(p?.summary.earned_labour), false, compact) },
                    { label: 'Labour spent', kind: 'workers' as const, tone: TONE[v.summary.colour], value: spent === null ? '—' : compact(spent), hint: delta(spent, num(p?.summary.labour_cost), true, compact) },
                  ]
                : [{ label: 'Man-days', kind: 'workers' as const, value: formatQuantity(v.labour.man_days), hint: delta(Number(v.labour.man_days), p ? Number(p.labour.man_days) : null, false, (n) => formatQuantity(String(n))) }]),
              { label: 'Red lines', icon: TriangleAlert, tone: count('red') > 0 ? ('bad' as const) : ('default' as const), value: count('red'), of: judged || undefined, hint: delta(count('red'), p ? p.summary.lines.red : null, true) },
              { label: 'Amber lines', icon: Eye, tone: count('amber') > 0 ? ('attention' as const) : ('default' as const), value: count('amber'), of: judged || undefined, hint: delta(count('amber'), p ? p.summary.lines.amber : null, true) },
              { label: 'Off the lines', icon: HardHat, tone: Number(v.labour.not_on_a_line.man_days) > 0 ? ('attention' as const) : ('good' as const), value: `${formatQuantity(v.labour.not_on_a_line.man_days)} md`, hint: money && v.labour.not_on_a_line.cost ? compact(Number(v.labour.not_on_a_line.cost)) : undefined },
            ]}
          />

          {money && Number(v.labour.not_on_a_line.cost ?? 0) > 0 && (
            <Link to={`/cost/budget?project=${projectId}#labour-to-lines`} className="group flex items-center gap-2.5 rounded-xl border bg-card px-3 py-2 transition-colors hover:bg-muted/40">
              <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-draft-soft text-draft" aria-hidden>
                <HardHat className="size-3.5" />
              </span>
              <span className="min-w-0 flex-1 text-sm">
                <span className="font-semibold tabular-nums">{compact(Number(v.labour.not_on_a_line.cost))}</span> labour not on a BOQ line
                <span className="text-muted-foreground tabular-nums"> · {formatQuantity(v.labour.not_on_a_line.man_days)} man-days, not judged</span>
              </span>
              <span className="inline-flex shrink-0 items-center gap-1 text-xs font-semibold">
                Put on lines <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden />
              </span>
            </Link>
          )}

          {v.days.length > 1 && (
            <div data-guide="gr.days">
              <DprSection icon={TrafficCone} title="Each day" meta={v.days.length}>
                <DayTiles days={v.days} picked={periodKey === 'day' ? dateFrom : null} onPick={pickDay} money={money} />
              </DprSection>
            </div>
          )}

          <div data-guide="gr.lines">
            <DprSection icon={Ruler} title="BOQ lines" meta={any ? `${listed.length} of ${lines.length}` : lines.length || undefined}>
              {lines.length === 0 ? (
                <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed bg-card px-4 py-10 text-center">
                  <Ruler className="size-5 text-muted-foreground" aria-hidden />
                  <p className="font-medium">Nothing measured in these days</p>
                  {!siteView && (
                    <Button asChild variant="outline" size="sm">
                      <Link to={`/cost/budget?project=${projectId}#labour-to-lines`}>Put work and labour on their lines</Link>
                    </Button>
                  )}
                </div>
              ) : (
                <>
                  {/* The lines by colour: one bar, each colour a filter. */}
                  <div className="mb-2 flex flex-col gap-2 rounded-xl border bg-card p-3">
                    <div className="flex h-2.5 overflow-hidden rounded-full bg-muted" role="img" aria-label={ORDER.map((c) => `${count(c)} ${COLOUR_WORD[c]}`).join(', ')}>
                      {ORDER.map((c) => count(c) > 0 && <span key={c} className={COLOUR_DOT[c]} style={{ width: `${(count(c) / Math.max(judged, 1)) * 100}%` }} />)}
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                      {ORDER.filter((c) => count(c) > 0).map((c) => {
                        const on = colour === c
                        return (
                          <button
                            key={c}
                            type="button"
                            aria-pressed={on}
                            onClick={() => set({ colour: on ? null : c })}
                            className={cn('inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold transition', LOOK[c].pill, on ? 'ring-2 ring-foreground/70' : 'hover:ring-1 hover:ring-foreground/20')}
                          >
                            {React.createElement(LOOK[c].icon, { className: 'size-3.5', 'aria-hidden': true })}
                            <span className="tabular-nums">{count(c)}</span> {COLOUR_WORD[c]}
                          </button>
                        )
                      })}
                      {fixCount > 0 && !siteView && (
                        <button
                          type="button"
                          aria-pressed={fixOnly}
                          onClick={() => set({ fix: fixOnly ? null : '1' })}
                          className={cn('inline-flex items-center gap-1.5 rounded-full border border-dashed px-2.5 py-1 text-xs font-semibold transition', fixOnly ? 'border-foreground bg-foreground text-background' : 'hover:border-foreground/40')}
                          title="Lines that are not judged because labour, a rate or a wage is missing"
                        >
                          <Wrench className="size-3.5" aria-hidden />
                          <span className="tabular-nums">{fixCount}</span> need a fix
                        </button>
                      )}
                      <span className="ml-auto flex flex-wrap items-center gap-2">
                        {sections.length > 1 && <FilterPill icon={Layers} label="Section" allLabel="All sections" value={section} options={sectionOptions} onChange={(x) => set({ section: x })} />}
                        <label className="flex h-8 items-center gap-2 rounded-lg border bg-card px-2.5">
                          <Search className="size-3.5 text-muted-foreground" aria-hidden />
                          <span className="sr-only">Search BOQ lines</span>
                          <input
                            ref={searchRef}
                            value={search}
                            onChange={(e) => set({ q: e.target.value })}
                            onKeyDown={(e) => e.key === 'Escape' && set({ q: null })}
                            placeholder="Search work or code"
                            className="w-36 bg-transparent text-sm outline-none"
                          />
                          <kbd className="hidden rounded border bg-muted px-1 text-[10px] text-muted-foreground sm:inline" title="Press / to search">/</kbd>
                        </label>
                        <label className="flex h-8 items-center gap-1.5 rounded-lg border bg-card px-2 text-sm">
                          <ArrowDownWideNarrow className="size-3.5 text-muted-foreground" aria-hidden />
                          <select value={sort} onChange={(e) => set({ sort: e.target.value })} className="bg-transparent outline-none" aria-label="Sort the lines">
                            {SORTS.filter((x) => money || (x.value !== 'over' && x.value !== 'spent')).map((x) => (
                              <option key={x.value} value={x.value}>
                                {x.label}
                              </option>
                            ))}
                          </select>
                        </label>
                        {any && (
                          <Button variant="ghost" size="sm" className="h-8 gap-1" onClick={clear}>
                            <X className="size-3.5" aria-hidden /> Clear
                          </Button>
                        )}
                        <ActionButton kind="export-excel" size="sm" className="h-8" disabled={listed.length === 0} onClick={exportShown} title="The lines shown, as a CSV file (opens in Excel)">
                          <span className="hidden sm:inline">{any ? 'Export shown' : 'Export lines'}</span>
                        </ActionButton>
                      </span>
                    </div>
                  </div>

                  {listed.length === 0 ? (
                    <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed bg-card py-10 text-center">
                      <Search className="size-5 text-muted-foreground" aria-hidden />
                      <p className="text-sm font-medium">No line matches</p>
                      <Button variant="outline" size="sm" onClick={clear}>
                        Clear filters
                      </Button>
                    </div>
                  ) : (
                    <div className="overflow-hidden rounded-xl border bg-card">
                      <table className="w-full text-sm">
                        <thead className="bg-muted/50 text-xs text-muted-foreground">
                          <tr>
                            <th className="px-3 py-2 text-left font-medium">Work</th>
                            <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">Done</th>
                            <th className="hidden px-3 py-2 text-right font-medium md:table-cell" aria-sort={sort === 'mandays' ? 'descending' : undefined}>
                              <SortHead label="Man-days" on={sort === 'mandays'} onClick={() => sortBy('mandays')} />
                            </th>
                            {money && (
                              <th className="hidden w-56 px-3 py-2 text-left font-medium lg:table-cell" aria-sort={sort === 'spent' ? 'descending' : undefined}>
                                <SortHead label="Labour earned vs spent" on={sort === 'spent'} onClick={() => sortBy('spent')} left />
                              </th>
                            )}
                            {money && (
                              <th className="px-3 py-2 text-right font-medium" aria-sort={sort === 'over' ? 'ascending' : undefined}>
                                <SortHead label="Gap" on={sort === 'over'} onClick={() => sortBy('over')} />
                              </th>
                            )}
                          </tr>
                        </thead>
                        <tbody className="divide-y">
                          {paged.shown.map((l) => (
                            <tr
                              key={l.line_id}
                              className={cn('align-top hover:bg-muted/30', !siteView && 'cursor-pointer')}
                              onClick={siteView ? undefined : () => navigate(`/cost/budget?project=${projectId}&q=${encodeURIComponent(l.boq_code ?? l.work)}`)}
                              title={siteView ? undefined : 'Open this line in Budget vs actual'}
                            >
                              <td className="relative px-3 py-2.5 pl-4">
                                <span className={cn('absolute top-2 bottom-2 left-1.5 w-1 rounded-full', COLOUR_DOT[l.colour])} aria-hidden />
                                <span className="flex flex-col gap-1">
                                  <span className="flex items-baseline gap-1.5">
                                    {l.boq_code && <span className="shrink-0 rounded bg-muted px-1 text-[11px] font-medium text-muted-foreground tabular-nums">{l.boq_code}</span>}
                                    <span className="font-medium">{l.work}</span>
                                  </span>
                                  {l.section && <span className="text-[11px] text-muted-foreground">{l.section}</span>}
                                  <ReasonChip line={l} projectId={projectId} siteView={!money} />
                                  {/* Phones and tablets: the figures fold under the name. */}
                                  <span className="flex flex-wrap gap-x-3 text-xs text-muted-foreground tabular-nums sm:hidden">
                                    <span>
                                      <span className="font-semibold text-foreground">{formatQuantity(l.done_quantity)}</span> {l.unit}
                                    </span>
                                    <span>
                                      <span className="font-semibold text-foreground">{formatQuantity(l.labour_man_days)}</span> md
                                    </span>
                                  </span>
                                  {money && (num(l.earned_labour) !== null || num(l.labour_cost) !== null) && (
                                    <span className="max-w-64 lg:hidden">
                                      <EarnedSpent earned={num(l.earned_labour)} spent={num(l.labour_cost)} colour={l.colour} />
                                    </span>
                                  )}
                                </span>
                              </td>
                              <td className="hidden px-3 py-2.5 text-right whitespace-nowrap tabular-nums sm:table-cell">
                                {Number(l.done_quantity) > 0 ? (
                                  <>
                                    {formatQuantity(l.done_quantity)} <span className="text-xs text-muted-foreground">{l.unit}</span>
                                  </>
                                ) : (
                                  <span className="text-muted-foreground">—</span>
                                )}
                              </td>
                              <td className="hidden px-3 py-2.5 text-right tabular-nums md:table-cell">
                                {Number(l.labour_man_days) > 0 ? formatQuantity(l.labour_man_days) : <span className="text-muted-foreground">—</span>}
                              </td>
                              {money && (
                                <td className="hidden px-3 py-2.5 lg:table-cell">
                                  {num(l.earned_labour) !== null || num(l.labour_cost) !== null ? (
                                    <span className="grid grid-cols-[1fr_auto] items-center gap-x-2 text-[11px] tabular-nums">
                                      <EarnedSpent earned={num(l.earned_labour)} spent={num(l.labour_cost)} colour={l.colour} />
                                      <span className="flex flex-col text-right leading-[0.85rem]">
                                        <span className="text-info">{l.earned_labour ? compact(Number(l.earned_labour)) : '—'}</span>
                                        <span className={COLOUR_TEXT[l.colour]}>{l.labour_cost ? compact(Number(l.labour_cost)) : '—'}</span>
                                      </span>
                                    </span>
                                  ) : (
                                    <span className="text-muted-foreground">—</span>
                                  )}
                                </td>
                              )}
                              {money && (
                                <td className="px-3 py-2.5 text-right">
                                  <GapPill line={l} />
                                </td>
                              )}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  <Pager {...paged.pager} noun="lines" className="mt-2" />
                </>
              )}
              <Legend
                className="mt-2"
                items={[
                  { tone: 'good', label: money ? 'Earned its labour' : 'Within the BOQ' },
                  { tone: 'attention', label: 'Up to 10% over' },
                  { tone: 'bad', label: 'Over, or no work measured' },
                ]}
              />
            </DprSection>
          </div>

          {(v.materials || v.work_in_other_unit > 0) && (
            <div className="flex flex-wrap items-center gap-1.5 text-xs">
              {v.materials && money && (
                <span className="inline-flex items-center gap-1.5 rounded-full border bg-card px-2.5 py-1 tabular-nums">
                  <Package className="size-3.5 text-emerald-600" aria-hidden />
                  Materials <span className="font-semibold text-info">{compact(Number(v.materials.earned))}</span> earned ·{' '}
                  <span className="font-semibold">{compact(Number(v.materials.bought))}</span> bought
                </span>
              )}
              {v.work_in_other_unit > 0 && (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-draft-soft px-2.5 py-1 font-medium text-draft" title="Work recorded in another unit than its BOQ line is not added in">
                  <TriangleAlert className="size-3.5" aria-hidden /> {v.work_in_other_unit} in another unit, not counted
                </span>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}
