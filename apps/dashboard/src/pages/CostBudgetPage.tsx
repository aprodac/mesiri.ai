import * as React from 'react'
import { Link } from 'react-router-dom'
import { MONEY_PEOPLE } from '@/lib/permissions'
import { KpiStrip, NoAccess } from '@/components/page/page-kit'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { LucideIcon } from 'lucide-react'
import {
  ArrowRight, Boxes, Calculator, ChevronRight, CircleCheck, CircleDashed, ClipboardCheck, Gauge, Handshake, HardHat, Scale,
  ShoppingCart, TrendingDown, TrendingUp, TriangleAlert,
} from 'lucide-react'
import { DprHeader, DprSection, PageError } from '@/components/dpr-page'
import { CostExportButton } from '@/components/cost/export-button'
import { LabourGroupRow } from '@/components/cost/labour-to-lines'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast-notification'
import { useAuth } from '@/lib/AuthContext'
import { formatQuantity, formatRupees, maySeeBoq } from '@/lib/boq'
import { CENTRE_COLOURS, fetchProjectBudget, fetchProjectLabour, putLabourOnLines, type BudgetKind, type BudgetLine, type LabourGroup } from '@/lib/cost'
import { compact } from '@/lib/expenses'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import { fetchProjects } from '@/lib/projects'
import { useScope } from '@/lib/ScopeContext'
import { cn } from '@/lib/utils'

// CC-04: budget against actual for a project, to date. Per kind (labour, materials, subcontract): the BOQ's budget,
// the budget earned by the work done (work put on a BOQ line), and what was spent in that cost centre. Earned less
// spent is the gap; a kind with no BOQ rate or no work on a line yet shows a dash, never a made-up figure. Per BOQ
// line: planned, done, left and earned. Backend: GET /cost/projects/{id}/budget.
// CC-05: each line also shows the labour put on it (a site's day of one trade, from attendance, by man-days) against
// the labour budget it earned; the last 30 days' labour not on a line is listed to put on its line.
// Backend: GET / PUT /cost/projects/{id}/labour.
// UX-32 (17 Nov, "less description, more visual cues"): the page reads by colour and shape, not sentences. One KPI
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

/** A short note with one thing to do: an icon, the figure, a few words, the link. */
function Nudge({ icon: Icon, tone, children, to, action }: { icon: LucideIcon; tone: 'attention' | 'muted'; children: React.ReactNode; to: string; action: string }) {
  const body = (
    <>
      <span className={cn('flex size-7 shrink-0 items-center justify-center rounded-md', tone === 'attention' ? 'bg-draft-soft text-draft' : 'bg-muted text-muted-foreground')} aria-hidden>
        <Icon className="size-3.5" />
      </span>
      <span className="min-w-0 flex-1 text-sm">{children}</span>
      <span className="inline-flex shrink-0 items-center gap-1 text-xs font-semibold text-foreground">
        {action} <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden />
      </span>
    </>
  )
  const cls = 'group flex items-center gap-2.5 rounded-xl border bg-card px-3 py-2 transition-colors hover:bg-muted/40'
  return to.startsWith('#') ? <a href={to} className={cls}>{body}</a> : <Link to={to} className={cls}>{body}</Link>
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

function ProjectPicker() {
  const projects = useQuery({ queryKey: ['scope-projects'], queryFn: fetchProjects })
  if (projects.isLoading) return <Skeleton className="h-32 rounded-lg" />
  if ((projects.data ?? []).length === 0) return <p className="text-sm text-muted-foreground">No projects yet.</p>
  return (
    <ul className="divide-y rounded-lg border" data-guide="project.pick">
      {(projects.data ?? []).map((p) => (
        <li key={p.id}>
          <Link to={`/cost/budget?project=${p.id}`} className="flex items-center gap-3 px-4 py-3 hover:bg-muted/60">
            <span className="flex size-8 items-center justify-center rounded-md bg-muted">
              <Scale className="size-4" />
            </span>
            <span className="flex-1 font-medium">{p.name}</span>
            <ChevronRight className="size-4 text-muted-foreground" />
          </Link>
        </li>
      ))}
    </ul>
  )
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
  const lines = b ? b.boq.sections.flatMap((s) => s.lines) : []
  const kinds = b?.kinds ?? []
  const budget = sumOf(kinds.map((k) => num(k.budget)))
  const earned = sumOf(kinds.map((k) => num(k.earned)))
  const spent = kinds.reduce((n, k) => n + Number(k.actual), 0)
  const gap = sumOf(kinds.map((k) => num(k.difference)))
  const forecast = sumOf(kinds.map((k) => num(k.forecast)))
  const forecastGap = sumOf(kinds.map((k) => num(k.forecast_difference)))
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
      hint: forecastGap === null ? 'too early' : `${compact(Math.abs(forecastGap))} ${forecastGap < 0 ? 'over' : 'under'} budget`,
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
                <Nudge icon={ClipboardCheck} tone="attention" to={`/projects/${projectId}/boq`} action="Put on lines">
                  <span className="font-semibold tabular-nums">{b.work_not_on_a_line}</span> {b.work_not_on_a_line === 1 ? 'piece of work' : 'pieces of work'} not on a BOQ line
                  <span className="text-muted-foreground"> · earns nothing</span>
                </Nudge>
              )}
              {Number(b.labour_not_on_a_line.man_days) > 0 && (
                <Nudge icon={HardHat} tone="attention" to="#labour-to-lines" action="Check">
                  <span className="font-semibold tabular-nums">{compact(Number(b.labour_not_on_a_line.cost))}</span> labour not on a line
                  <span className="text-muted-foreground tabular-nums"> · {formatQuantity(b.labour_not_on_a_line.man_days)} man-days</span>
                </Nudge>
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

          <DprSection icon={Calculator} title="BOQ lines" meta={lines.length}>
            <div className="overflow-x-auto rounded-xl border bg-card [contain:inline-size]" data-guide="budget.lines">
              <table className="w-full text-sm md:min-w-[820px]">
                <thead className="bg-muted/50 text-xs text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">Work</th>
                    <th className="w-32 px-3 py-2 text-left font-medium md:w-48">Done</th>
                    <th className="hidden px-3 py-2 text-right font-medium md:table-cell">Budget</th>
                    <th className="hidden px-3 py-2 text-right font-medium md:table-cell">Earned</th>
                    <th className="hidden px-3 py-2 text-right font-medium md:table-cell">Labour spent</th>
                    <th className="hidden px-3 py-2 text-right font-medium md:table-cell">Labour vs earned</th>
                  </tr>
                </thead>
                {b.boq.sections.filter((sec) => sec.lines.length > 0).map((sec) => {
                  const secBudget = sumOf(sec.lines.map((l) => num(l.budget_cost)))
                  const secEarned = sumOf(sec.lines.map((l) => (Number(l.done_quantity) > 0 ? num(l.earned) : null)))
                  return (
                    <tbody key={sec.id} className="divide-y border-t">
                      {b.boq.sections.filter((x) => x.lines.length > 0).length > 1 && (
                        <tr className="bg-muted/40">
                          <th scope="rowgroup" colSpan={2} className="px-3 py-1.5 text-left text-xs font-semibold">
                            {sec.name} <span className="font-normal text-muted-foreground">· {sec.lines.length}</span>
                          </th>
                          <td className="hidden px-3 py-1.5 text-right text-xs font-semibold tabular-nums md:table-cell">{secBudget === null ? '—' : compact(secBudget)}</td>
                          <td className="hidden px-3 py-1.5 text-right text-xs font-semibold tabular-nums text-info md:table-cell">{secEarned === null ? '—' : compact(secEarned)}</td>
                          <td colSpan={2} className="hidden md:table-cell" />
                        </tr>
                      )}
                      {sec.lines.map((l) => {
                        const started = Number(l.done_quantity) > 0
                        return (
                          <tr key={l.id} className="hover:bg-muted/30">
                            <td className="px-3 py-2">
                              <span className="flex items-baseline gap-1.5">
                                {l.boq_code && <span className="shrink-0 rounded bg-muted px-1 text-[11px] font-medium text-muted-foreground tabular-nums">{l.boq_code}</span>}
                                <span className={cn('font-medium', !started && 'text-muted-foreground')}>{l.work}</span>
                              </span>
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
                            <td className="hidden px-3 py-2 text-right font-medium tabular-nums text-info md:table-cell">{started && l.earned !== null ? formatRupees(l.earned) : <span className="font-normal text-muted-foreground">—</span>}</td>
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
                        )
                      })}
                    </tbody>
                  )
                })}
              </table>
            </div>
          </DprSection>

          <div id="labour-to-lines" className="scroll-mt-20" data-guide="budget.labour">
            <DprSection icon={HardHat} title="Labour to check" meta={labour.data?.groups.length || undefined}>
              {labour.isLoading ? (
                <Skeleton className="h-24 rounded-lg" />
              ) : labour.isError ? (
                <p className="text-sm text-muted-foreground">The labour list could not be loaded.</p>
              ) : (labour.data?.groups.length ?? 0) === 0 ? (
                <p className="text-sm text-muted-foreground">All labour is on its BOQ lines.</p>
              ) : (
                <>
                  <ul className="divide-y rounded-xl border bg-card text-sm">
                    {labour.data!.groups.map((g) => (
                      <LabourGroupRow
                        key={`${g.site_id}|${g.date}|${g.trade_key}|${g.not_on_a_line.man_days}|${g.suggested_line_id}`}
                        group={g}
                        lines={lines}
                        readOnly={false}
                        saving={putLabour.isPending}
                        onSave={(next) => putLabour.mutate({ group: g, lines: next })}
                      />
                    ))}
                  </ul>
                </>
              )}
            </DprSection>
          </div>
        </>
      )}
    </div>
  )
}
