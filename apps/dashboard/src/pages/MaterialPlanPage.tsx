import * as React from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Calculator, PackageSearch } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Callout, PageError, StatStrip, type Stat } from '@/components/dpr-page'
import { ProjectPickList, usePlanningProject } from '@/components/schedule/project-picker'
import { useAuth } from '@/lib/AuthContext'
import { maySeeBoq, formatQuantity } from '@/lib/boq'
import { fetchMaterialPlan, type MaterialPlan, type MaterialPlanRow } from '@/lib/material-plan'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'

// MP-02: Planning › Material plan. What the project needs of each material, week by week: the BOQ's work still to
// do × the materials per unit (MP-01), over the schedule's dates, against what is in stock and on order. Red from
// the week it runs short. Nothing is typed here: site's work updates shrink the need, the schedule moves it.

const NUM = 'text-right tabular-nums'

function dayLabel(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
}

function Heading() {
  return (
    <header className="flex min-w-0 items-center gap-3">
      <span className="inline-flex size-10 shrink-0 items-center justify-center rounded-xl bg-teal-100 text-teal-800 dark:bg-teal-950 dark:text-teal-200">
        <PackageSearch className="size-5" />
      </span>
      <div className="min-w-0">
        <div className="text-xs text-muted-foreground">Planning</div>
        <h1 className="text-2xl leading-tight font-semibold tracking-tight">Material plan</h1>
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
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 pb-8 sm:px-2">
        <Heading />
        <p className="text-sm text-muted-foreground">The material plan is read from the BOQ, so it shows to the people who see the BOQ: owner, admin, finance and project managers.</p>
      </div>
    )
  }
  if (!projectId) {
    return (
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 pb-8 sm:px-2">
        <Heading />
        <p className="text-sm text-muted-foreground">Pick a project to see what it needs, and when.</p>
        <ProjectPickList to={(id) => `/planning/materials?project=${id}`} empty="No projects yet. Add one in Projects & Sites." />
      </div>
    )
  }
  return <PlanView key={projectId} projectId={projectId} />
}

function shortText(row: MaterialPlanRow): string {
  if (!row.short_from) return 'Covered'
  return `Short from ${dayLabel(row.short_from)}`
}

function PlanView({ projectId }: { projectId: string }) {
  const [weeks, setWeeks] = React.useState(8)
  const query = useQuery<MaterialPlan>({ queryKey: ['material-plan', projectId, weeks], queryFn: () => fetchMaterialPlan(projectId, weeks) })
  const boqLink = `/projects/${projectId}/boq`

  if (query.isError) return <PageError message="The material plan did not load." onRetry={() => query.refetch()} back={{ to: '/planning/materials', label: 'All projects' }} />
  const plan = query.data
  const short = plan?.materials.filter((m) => m.short_from) ?? []
  const stats: Stat[] = plan
    ? [
        { label: 'Materials planned', value: plan.materials.length },
        { label: 'Short in these weeks', value: short.length, tone: short.length ? 'bad' : 'good' },
        { label: 'BOQ lines with materials', value: `${plan.lines_with_norms} of ${plan.lines_with_norms + plan.lines_without_norms}`, tone: plan.lines_without_norms ? 'warn' : 'good' },
      ]
    : []

  return (
    <div className="mx-auto flex w-full max-w-6xl min-w-0 flex-col gap-4 pb-8 sm:px-2">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Heading />
        <div className="flex items-center gap-2">
          <label className="text-xs text-muted-foreground" htmlFor="mp-weeks">Weeks</label>
          <select id="mp-weeks" className="h-9 rounded-md border bg-background px-2 text-sm" value={weeks} onChange={(e) => setWeeks(Number(e.target.value))}>
            {[4, 8, 12].map((w) => <option key={w} value={w}>{w}</option>)}
          </select>
          <Button asChild variant="outline" size="sm" className="gap-1.5"><Link to={boqLink}><Calculator className="size-3.5" /> BOQ</Link></Button>
        </div>
      </div>
      <p className="max-w-3xl text-sm text-muted-foreground">
        The BOQ's work still to do × the materials each unit uses, spread over the schedule's dates, against what is in stock and on order.
        It updates itself: work site records shrinks the need, and moving an activity moves it.
      </p>
      {!plan ? (
        <Skeleton className="h-64 w-full" />
      ) : plan.lines_with_norms === 0 ? (
        <Callout tone="info" icon={Calculator} action={<Button asChild size="sm"><Link to={boqLink}>Open the BOQ</Link></Button>}>
          No BOQ line says which materials it uses yet. On the BOQ, open a line's “Materials per unit” (e.g. 1 cum of M20 uses 8 bags of cement)
          and the plan fills itself in.
        </Callout>
      ) : (
        <>
          <StatStrip stats={stats} />
          {short.length > 0 && (
            <Callout tone="draft" icon={AlertTriangle}>
              {short.slice(0, 3).map((m) => `${m.material}: ${formatQuantity(m.short_by)} ${m.unit} short from ${dayLabel(m.short_from as string)}`).join(' · ')}
              {short.length > 3 ? ` · and ${short.length - 3} more` : ''}
            </Callout>
          )}
          <PlanTable plan={plan} />
          <PlanCards plan={plan} />
          {plan.lines_without_norms > 0 && (
            <p className="text-xs text-muted-foreground">
              {plan.lines_without_norms} BOQ line{plan.lines_without_norms > 1 ? 's have' : ' has'} no materials yet and {plan.lines_without_norms > 1 ? 'are' : 'is'} not in this plan.{' '}
              <Link to={boqLink} className="underline underline-offset-2">Add them on the BOQ</Link>.
            </p>
          )}
        </>
      )}
    </div>
  )
}

/** Weeks from the short week on are red; a week with no need is a dash. */
function weekCell(row: MaterialPlanRow, week: string, value: string) {
  const red = row.short_from !== null && week >= row.short_from && Number(value) > 0
  return <td key={week} className={cn('px-2 py-2', NUM, red ? 'bg-destructive/10 font-medium text-destructive' : Number(value) === 0 && 'text-muted-foreground')}>{Number(value) === 0 ? '—' : formatQuantity(value)}</td>
}

function Notes({ row }: { row: MaterialPlanRow }) {
  const notes = [
    Number(row.unscheduled) > 0 && `${formatQuantity(row.unscheduled)} for work with no dates`,
    Number(row.later) > 0 && `${formatQuantity(row.later)} after these weeks`,
    row.stock_unit_differs && 'stock is held in another unit, not counted',
    row.lines.some((l) => l.late) && 'late work needs it now',
  ].filter(Boolean)
  if (!notes.length) return null
  return <p className="text-xs text-muted-foreground">{notes.join(' · ')}</p>
}

function PlanTable({ plan }: { plan: MaterialPlan }) {
  return (
    <div className="hidden overflow-x-auto rounded-lg border [contain:inline-size] md:block">
      <table className="w-full text-sm">
        <thead className="bg-muted/50 text-xs text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left font-medium">Material</th>
            <th className={cn('px-2 py-2 font-medium', NUM)}>Still needed</th>
            <th className={cn('px-2 py-2 font-medium', NUM)}>In stock</th>
            <th className={cn('px-2 py-2 font-medium', NUM)}>On order</th>
            <th className="px-2 py-2 text-left font-medium">Status</th>
            {plan.weeks.map((w) => <th key={w} className={cn('px-2 py-2 font-medium whitespace-nowrap', NUM)}>w/c {dayLabel(w)}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y">
          {plan.materials.map((row) => (
            <tr key={row.material_id} className="align-top">
              <td className="px-3 py-2">
                <span className="font-medium">{row.material}</span> <span className="text-muted-foreground">{row.unit}</span>
                <p className="text-xs text-muted-foreground" title={row.lines.map((l) => `${l.work}: ${formatQuantity(l.need)}`).join('\n')}>
                  {row.lines.length ? `for ${row.lines.map((l) => l.work).slice(0, 2).join(', ')}${row.lines.length > 2 ? ` +${row.lines.length - 2}` : ''}` : 'BOQ work done'}
                </p>
                <Notes row={row} />
              </td>
              <td className={cn('px-2 py-2', NUM)}>{formatQuantity(row.still_needed)}</td>
              <td className={cn('px-2 py-2', NUM)}>{formatQuantity(row.on_hand)}</td>
              <td className={cn('px-2 py-2', NUM)}>{Number(row.on_order) ? formatQuantity(row.on_order) : '—'}</td>
              <td className={cn('px-2 py-2 whitespace-nowrap', row.short_from ? 'font-medium text-destructive' : 'text-success')}>
                {shortText(row)}
                {row.short_from && <span className="block text-xs font-normal">{formatQuantity(row.short_by)} {row.unit} more needed</span>}
              </td>
              {plan.weeks.map((w, i) => weekCell(row, w, row.weeks[i]))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function PlanCards({ plan }: { plan: MaterialPlan }) {
  return (
    <ul className="flex flex-col gap-2 md:hidden">
      {plan.materials.map((row) => {
        const next = plan.weeks.map((w, i) => ({ w, v: row.weeks[i] })).filter((x) => Number(x.v) > 0).slice(0, 3)
        return (
          <li key={row.material_id} className={cn('rounded-lg border p-3', row.short_from && 'border-destructive/40')}>
            <div className="flex items-baseline justify-between gap-2">
              <span className="font-medium">{row.material}</span>
              <span className={cn('text-sm', row.short_from ? 'font-medium text-destructive' : 'text-success')}>{shortText(row)}</span>
            </div>
            <p className="text-sm text-muted-foreground">
              Needs {formatQuantity(row.still_needed)} {row.unit} · in stock {formatQuantity(row.on_hand)}
              {Number(row.on_order) ? ` · on order ${formatQuantity(row.on_order)}` : ''}
            </p>
            {next.length > 0 && <p className="text-sm">{next.map((x) => `${dayLabel(x.w)} week: ${formatQuantity(x.v)}`).join(' · ')}</p>}
            {row.short_from && <p className="text-sm text-destructive">{formatQuantity(row.short_by)} {row.unit} more needed</p>}
            <Notes row={row} />
          </li>
        )
      })}
    </ul>
  )
}
