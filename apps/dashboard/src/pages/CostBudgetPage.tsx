import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Calculator, ChevronRight, ClipboardCheck, Scale } from 'lucide-react'
import { Callout, DprHeader, DprSection, PageError } from '@/components/dpr-page'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { formatQuantity, formatRupees, maySeeBoq } from '@/lib/boq'
import { fetchProjectBudget, type BudgetKind } from '@/lib/cost'
import { usePageTitle } from '@/lib/page-title'
import { fetchProjects } from '@/lib/projects'
import { useScope } from '@/lib/ScopeContext'
import { cn } from '@/lib/utils'

// CC-04: budget against actual for a project, to date. Per kind (labour, materials, subcontract): the BOQ's budget,
// the budget earned by the work done (work put on a BOQ line), and what was spent in that cost centre. Earned less
// spent is the gap; a kind with no BOQ rate or no work on a line yet shows a dash, never a made-up figure. Per BOQ
// line: planned, done, left and earned. Backend: GET /cost/projects/{id}/budget.

function KindCard({ k }: { k: BudgetKind }) {
  const diff = k.difference === null ? null : Number(k.difference)
  const used = k.budget && Number(k.budget) > 0 ? (Number(k.actual) / Number(k.budget)) * 100 : null
  return (
    <div className="flex flex-col gap-2 rounded-lg border p-4">
      <div className="flex items-baseline justify-between gap-2">
        <p className="font-semibold">{k.label}</p>
        {diff !== null && (
          <span className={cn('text-sm font-semibold tabular-nums', diff < 0 ? 'text-destructive' : 'text-success')}>
            {diff < 0 ? `${formatRupees(String(-diff))} over` : `${formatRupees(String(diff))} under`}
          </span>
        )}
      </div>
      <dl className="grid grid-cols-3 gap-2 text-sm">
        <div>
          <dt className="text-xs text-muted-foreground">Budget</dt>
          <dd className="font-medium tabular-nums">{formatRupees(k.budget)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Earned</dt>
          <dd className="font-medium tabular-nums">{formatRupees(k.earned)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Spent</dt>
          <dd className="font-medium tabular-nums">{formatRupees(k.actual)}</dd>
        </div>
      </dl>
      {used !== null && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted" aria-hidden="true">
            <div className={cn('h-full rounded-full', used > 100 ? 'bg-destructive' : 'bg-primary')} style={{ width: `${Math.min(used, 100)}%` }} />
          </div>
          {Math.round(used)}% of budget spent
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        {k.budget === null
          ? 'No BOQ line has this rate, so there is nothing to set the spending against.'
          : k.earned === null
            ? 'No work is on a priced line yet, so nothing is earned.'
            : 'Earned − spent: what the work done was worth against what it cost.'}
      </p>
    </div>
  )
}

function ProjectPicker() {
  const projects = useQuery({ queryKey: ['scope-projects'], queryFn: fetchProjects })
  if (projects.isLoading) return <Skeleton className="h-32 rounded-lg" />
  if ((projects.data ?? []).length === 0) return <p className="text-sm text-muted-foreground">No projects yet.</p>
  return (
    <ul className="divide-y rounded-lg border">
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

  if (!allowed) {
    return (
      <div className="mx-auto flex w-full max-w-md flex-col items-center gap-3 py-16 text-center">
        <p className="font-medium">Budget vs actual shows the company's rates and spending.</p>
        <p className="text-sm text-muted-foreground">Only owners, admins, finance and project managers can open it.</p>
      </div>
    )
  }
  const header = (
    <DprHeader back={{ to: '/today', label: 'Today' }} crumb="Cost control" title="Budget vs actual" date={projectId ? scope.mode !== 'portfolio' ? scope.projectName : '' : 'Pick a project'} />
  )
  if (!projectId) {
    return (
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 pb-8 sm:px-2">
        {header}
        <ProjectPicker />
      </div>
    )
  }
  if (q.isError) return <PageError message="Budget vs actual could not be loaded." onRetry={() => q.refetch()} back={{ to: '/today', label: 'Today' }} />
  const b = q.data
  const lines = b ? b.boq.sections.flatMap((s) => s.lines.map((l) => ({ ...l, section: s.name }))) : []

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 pb-8 sm:px-2">
      {header}
      {q.isLoading || !b ? (
        <Skeleton className="h-48 rounded-lg" />
      ) : lines.length === 0 ? (
        <div className="flex flex-col items-start gap-3 rounded-lg border border-dashed px-4 py-6">
          <p className="font-medium">This project has no BOQ yet.</p>
          <p className="text-sm text-muted-foreground">Budget vs actual sets spending against the BOQ's budget rates. Add the BOQ first.</p>
          <Link to={`/projects/${projectId}/boq`} className="text-sm font-medium underline underline-offset-2">
            Open the BOQ
          </Link>
        </div>
      ) : (
        <>
          <p className="text-sm text-muted-foreground">
            From {b.date_from} to {b.date_to}: everything recorded on this project. Total spent {formatRupees(b.total_spent)}.
          </p>
          {b.work_not_on_a_line > 0 && (
            <Callout tone="muted" icon={ClipboardCheck}>
              {b.work_not_on_a_line} {b.work_not_on_a_line === 1 ? 'piece of work is' : 'pieces of work are'} not on a BOQ line yet, so
              {b.work_not_on_a_line === 1 ? ' it earns' : ' they earn'} nothing here.{' '}
              <Link to={`/projects/${projectId}/boq`} className="font-medium underline underline-offset-2">
                Put them on their lines
              </Link>
            </Callout>
          )}
          <div className="grid gap-3 md:grid-cols-3">
            {b.kinds.map((k) => (
              <KindCard key={k.kind} k={k} />
            ))}
          </div>
          {(b.other_spending.length > 0 || Number(b.not_set) > 0) && (
            <p className="text-xs text-muted-foreground">
              Also spent, with no BOQ rate to set it against:{' '}
              {[...b.other_spending.map((o) => `${o.label} ${formatRupees(o.amount)}`), ...(Number(b.not_set) > 0 ? [`not set ${formatRupees(b.not_set)}`] : [])].join(' · ')}.{' '}
              <Link to="/cost/centres" className="underline underline-offset-2">
                Cost centres
              </Link>
            </p>
          )}

          <DprSection icon={Calculator} title="BOQ lines" meta={lines.length}>
            <div className="overflow-x-auto rounded-lg border [contain:inline-size]">
              <table className="w-full min-w-[760px] text-sm">
                <thead className="bg-muted/50 text-xs text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">Work</th>
                    <th className="px-3 py-2 text-right font-medium">Planned</th>
                    <th className="px-3 py-2 text-right font-medium">Done</th>
                    <th className="px-3 py-2 text-right font-medium">Left</th>
                    <th className="px-3 py-2 text-right font-medium">Budget</th>
                    <th className="px-3 py-2 text-right font-medium">Earned</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {lines.map((l) => (
                    <tr key={l.id}>
                      <td className="px-3 py-2">
                        <span className="font-medium">{l.boq_code ? `${l.boq_code} · ` : ''}{l.work}</span>
                        <span className="block text-xs text-muted-foreground">{l.section}</span>
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {formatQuantity(l.planned_quantity)} <span className="text-muted-foreground">{l.unit}</span>
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {Number(l.done_quantity) > 0 ? `${formatQuantity(l.done_quantity)} · ${l.percent_done}%` : <span className="text-muted-foreground">—</span>}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">{formatQuantity(l.remaining_quantity)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{formatRupees(l.budget_cost)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{Number(l.done_quantity) > 0 ? formatRupees(l.earned) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              Spending per line comes with labour allocation (next): a day's labour is put on the lines it worked on.
            </p>
          </DprSection>
        </>
      )}
    </div>
  )
}
