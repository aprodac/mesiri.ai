import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ChevronRight, ClipboardCheck, HardHat, Landmark, Package, PieChart, Scale, TrafficCone } from 'lucide-react'
import { Callout, DprHeader, DprSection, PageError, StatStrip } from '@/components/dpr-page'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { formatRupees, maySeeBoq } from '@/lib/boq'
import { fetchPortfolio, type PortfolioRow, type VarianceColour } from '@/lib/cost'
import { usePageTitle } from '@/lib/page-title'
import { COLOUR_DOT, COLOUR_TEXT } from '@/lib/cost-colours'
import { cn } from '@/lib/utils'

// CC-22: the Cost control home. Every project with a BOQ, worst forecast first (CC-19): budget, % done against
// % spent, committed, the forecast at completion against the budget, and the last 7 days' green / red; then what
// needs a person (labour and work not on a BOQ line). Each row opens the project's Green / red; the other pages are
// one tap away. Backend: GET /cost/portfolio (the same reads as Budget vs actual and Green / red).

const FORECAST_WORD: Record<VarianceColour, string> = {
  green: 'On budget',
  amber: 'Watch',
  red: 'Over budget',
  grey: 'No forecast yet',
}

function Bar({ done, spent }: { done: number | null; spent: number | null }) {
  // % done (earned) against % spent: spending running ahead of the work is what to look at.
  return (
    <div className="flex flex-col gap-1" aria-hidden="true">
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-primary" style={{ width: `${Math.min(done ?? 0, 100)}%` }} />
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div className={cn('h-full rounded-full', (spent ?? 0) > (done ?? 0) + 5 ? 'bg-destructive' : 'bg-muted-foreground/60')} style={{ width: `${Math.min(spent ?? 0, 100)}%` }} />
      </div>
    </div>
  )
}

function ProjectRow({ p }: { p: PortfolioRow }) {
  const diff = p.forecast_difference === null ? null : Number(p.forecast_difference)
  return (
    <li>
      <Link to={`/cost/green-red?project=${p.project_id}`} className="flex flex-col gap-2 px-4 py-3 hover:bg-muted/60 sm:flex-row sm:items-center sm:gap-4">
        <div className="flex min-w-0 flex-1 items-start gap-3">
          <span className={cn('mt-1.5 size-2.5 shrink-0 rounded-full', COLOUR_DOT[p.colour])} aria-hidden="true" />
          <div className="min-w-0">
            <p className="truncate font-medium">{p.name}</p>
            <p className={cn('text-xs font-medium', COLOUR_TEXT[p.colour])}>
              {FORECAST_WORD[p.colour]}
              {diff !== null && <> · {diff < 0 ? `${formatRupees(String(-diff))} over` : `${formatRupees(String(diff))} under`} at completion</>}
              {p.forecast_kinds.length > 0 && p.forecast_kinds.length < 3 && (
                <span className="font-normal text-muted-foreground"> ({p.forecast_kinds.join(', ')})</span>
              )}
            </p>
          </div>
        </div>
        <div className="grid grid-cols-3 gap-3 text-xs sm:w-[420px]">
          <div>
            <p className="text-muted-foreground">Budget</p>
            <p className="font-medium tabular-nums">{formatRupees(p.budget)}</p>
          </div>
          <div>
            <p className="text-muted-foreground">Done / spent</p>
            <p className="font-medium tabular-nums">
              {p.percent_done ?? '—'}% / {p.percent_spent ?? '—'}%
            </p>
            <Bar done={p.percent_done === null ? null : Number(p.percent_done)} spent={p.percent_spent === null ? null : Number(p.percent_spent)} />
          </div>
          <div>
            <p className="text-muted-foreground">Last 7 days</p>
            <p className={cn('flex items-center gap-1.5 font-medium', COLOUR_TEXT[p.week.colour])}>
              <span className={cn('size-2 rounded-full', COLOUR_DOT[p.week.colour])} aria-hidden="true" />
              {p.week.colour === 'grey' ? 'Not judged' : p.week.colour === 'red' ? `${p.week.red_lines} red` : p.week.colour === 'amber' ? 'Amber' : 'Green'}
            </p>
          </div>
        </div>
        <ChevronRight className="hidden size-4 shrink-0 text-muted-foreground sm:block" />
      </Link>
    </li>
  )
}

const PAGES = [
  { to: '/cost/green-red', icon: TrafficCone, title: 'Green / red', about: "Each BOQ line's labour against the work it earned, by day." },
  { to: '/cost/budget', icon: Scale, title: 'Budget vs actual', about: 'Budget, earned, spent, committed and forecast; put labour on lines.' },
  { to: '/cost/materials', icon: Package, title: 'Materials vs BOQ', about: 'Used against what the work needed; what is short to finish.' },
  { to: '/cost/centres', icon: PieChart, title: 'Cost centres', about: 'Where the money went: materials, labour, subcontract, fuel.' },
  { to: '/boq', icon: ClipboardCheck, title: 'BOQ & budget', about: "Each project's BOQ, rates and work done per line." },
]

export default function CostHomePage() {
  const { me } = useAuth()
  usePageTitle('Cost control')
  const allowed = maySeeBoq(me?.role)
  const q = useQuery({ queryKey: ['cost', 'portfolio'], queryFn: fetchPortfolio, enabled: allowed })

  if (!allowed) {
    return (
      <div className="mx-auto flex w-full max-w-md flex-col items-center gap-3 py-16 text-center">
        <p className="font-medium">Cost control shows the company's rates and spending.</p>
        <p className="text-sm text-muted-foreground">Only owners, admins, finance and project managers can open it.</p>
      </div>
    )
  }
  if (q.isError) return <PageError message="Cost control could not be loaded." onRetry={() => q.refetch()} back={{ to: '/today', label: 'Today' }} />
  const rows = q.data?.projects ?? []
  const sum = (pick: (r: PortfolioRow) => string | null) => rows.reduce((t, r) => t + Number(pick(r) ?? 0), 0)
  const over = rows.filter((r) => r.colour === 'red').length
  const labourLeft = sum((r) => r.labour_not_on_a_line)
  const workLeft = rows.reduce((t, r) => t + r.work_not_on_a_line, 0)

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader back={{ to: '/today', label: 'Today' }} crumb="Cost control" title="Cost control" date={q.data ? `${rows.length} projects with a BOQ` : ''} />
      {q.isLoading ? (
        <Skeleton className="h-64 rounded-lg" />
      ) : rows.length === 0 ? (
        <div className="flex flex-col items-start gap-2 rounded-lg border border-dashed px-4 py-6">
          <p className="font-medium">No project has a BOQ yet.</p>
          <p className="text-sm text-muted-foreground">
            Cost control sets what is spent against each project's BOQ budget.{' '}
            <Link to="/boq" className="font-medium underline underline-offset-2">
              Add a BOQ
            </Link>
          </p>
        </div>
      ) : (
        <>
          <StatStrip
            stats={[
              { label: 'Budget', value: formatRupees(String(sum((r) => r.budget))), icon: Landmark },
              { label: 'Earned', value: formatRupees(String(sum((r) => r.earned))), hint: 'work done × BOQ rates' },
              { label: 'Spent', value: formatRupees(String(sum((r) => r.spent))) },
              { label: 'Committed', value: formatRupees(String(sum((r) => r.committed))), hint: 'ordered, not delivered or billed' },
              { label: 'Over budget', value: `${over} of ${rows.length}`, tone: over > 0 ? 'bad' : 'good', hint: 'by forecast at completion' },
            ]}
          />
          {(labourLeft > 0 || workLeft > 0) && (
            <Callout tone="draft" icon={HardHat}>
              {labourLeft > 0 && <>{formatRupees(String(labourLeft))} of labour is not on a BOQ line. </>}
              {workLeft > 0 && <>{workLeft} pieces of measured work are not on a line. </>}
              Until they are, no line is coloured by them. Open a project's Budget vs actual to put them on their lines.
            </Callout>
          )}
          <DprSection icon={TrafficCone} title="Projects, worst first" meta={rows.length}>
            <ul className="divide-y rounded-lg border">
              {rows.map((p) => (
                <ProjectRow key={p.project_id} p={p} />
              ))}
            </ul>
            <p className="mt-2 text-xs text-muted-foreground">
              Forecast at completion: what is spent, plus the work left at the rate it has cost so far, for the kinds (labour, materials,
              subcontract) with enough work done and paid. Done / spent: the budget earned and the money spent, as a share of the budget.
            </p>
          </DprSection>
        </>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        {PAGES.map((pg) => (
          <Link key={pg.to} to={pg.to} className="flex items-start gap-3 rounded-lg border p-4 hover:bg-muted/60">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted">
              <pg.icon className="size-4" />
            </span>
            <span className="min-w-0">
              <span className="block font-medium">{pg.title}</span>
              <span className="block text-sm text-muted-foreground">{pg.about}</span>
            </span>
          </Link>
        ))}
      </div>
    </div>
  )
}
