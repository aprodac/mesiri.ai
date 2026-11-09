import * as React from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Calculator, PackageSearch, ShoppingCart } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Callout, PageError, StatStrip, type Stat } from '@/components/dpr-page'
import { NewOrderDialog, type OrderPrefill } from '@/components/orders/new-order-dialog'
import { ProjectPickList, usePlanningProject } from '@/components/schedule/project-picker'
import { useAuth } from '@/lib/AuthContext'
import { maySeeBoq } from '@/lib/boq'
import { fetchMaterialPlan, type MaterialPlan, type MaterialPlanRow } from '@/lib/material-plan'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'
import { ModuleTitle } from '@/components/page/page-kit'

// MP-02: Planning › Material plan. What the project needs of each material, week by week: the BOQ's work still to
// do × the materials per unit (MP-01), over the schedule's dates, against what is in stock and on order. Red from
// the week it runs short. Nothing is typed here: site's work updates shrink the need, the schedule moves it.
// MP-03: the day to order by (the day it runs short less the supplier's delivery time), and an Order button that
// opens the purchase order form filled in.

const NUM = 'text-right tabular-nums'

/** A planned quantity as a person orders it: whole units from 10 up, one decimal below. ``up`` rounds a shortfall up
 * (481.26 bags short is 482 to order). The API keeps the exact figures. */
function qty(value: string, up = false): string {
  const n = Number(value)
  if (Number.isNaN(n)) return value
  if (Math.abs(n) >= 10) return (up ? Math.ceil(n) : Math.round(n)).toLocaleString('en-IN')
  return (up ? Math.ceil(n * 10) / 10 : Math.round(n * 10) / 10).toLocaleString('en-IN')
}

function dayLabel(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
}

function Heading() {
  return (
    <header className="flex min-w-0 items-center gap-3">
      <ModuleTitle icon={PackageSearch} title="Material plan" />
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
        <p className="text-sm text-muted-foreground">The material plan is read from the BOQ, so it shows to the people who see the BOQ: owner, admin, finance and project managers.</p>
      </div>
    )
  }
  if (!projectId) {
    return (
      <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
        <Heading />
        <p className="text-sm text-muted-foreground">Pick a project to see what it needs, and when.</p>
        <ProjectPickList to={(id) => `/planning/materials?project=${id}`} empty="No projects yet. Add one in Projects & Sites." />
      </div>
    )
  }
  return <PlanView key={projectId} projectId={projectId} />
}

function shortText(row: MaterialPlanRow): string {
  if (!row.order_by) return 'Covered'
  return row.order_now ? 'Order now' : `Order by ${dayLabel(row.order_by)}`
}

function shortDetail(row: MaterialPlanRow): string {
  if (!row.short_day) return ''
  const lead = row.supplier && row.lead_known ? `${row.supplier} delivers in ${row.lead_days} days` : `${row.lead_days} days to deliver assumed`
  return `${qty(row.short_by, true)} ${row.unit} more needed · runs short ${dayLabel(row.short_day)} · ${lead}`
}

function orderPrefill(projectId: string, row: MaterialPlanRow): OrderPrefill {
  return {
    project_id: projectId,
    site_id: row.lines.find((l) => l.site_id)?.site_id ?? '',
    lines: [{ material_id: row.material_id, quantity: String(Math.ceil(Number(row.short_by))) }],
    vendor_name: row.supplier ?? undefined,
  }
}

function PlanView({ projectId }: { projectId: string }) {
  const [weeks, setWeeks] = React.useState(8)
  const [ordering, setOrdering] = React.useState<OrderPrefill | null>(null)
  const order = (row: MaterialPlanRow) => setOrdering(orderPrefill(projectId, row))
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
    <div className="mx-auto flex w-full min-w-0 flex-col gap-4 pb-8 sm:px-2">
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
              {short.slice(0, 3).map((m) => `${m.material}: ${qty(m.short_by, true)} ${m.unit} short from ${dayLabel(m.short_day as string)}, ${m.order_now ? 'order now' : `order by ${dayLabel(m.order_by as string)}`}`).join(' · ')}
              {short.length > 3 ? ` · and ${short.length - 3} more` : ''}
            </Callout>
          )}
          <PlanTable plan={plan} onOrder={order} />
          <PlanCards plan={plan} onOrder={order} />
          {plan.lines_without_norms > 0 && (
            <p className="text-xs text-muted-foreground">
              {plan.lines_without_norms} BOQ line{plan.lines_without_norms > 1 ? 's have' : ' has'} no materials yet and {plan.lines_without_norms > 1 ? 'are' : 'is'} not in this plan.{' '}
              <Link to={boqLink} className="underline underline-offset-2">Add them on the BOQ</Link>.
            </p>
          )}
        </>
      )}
      <NewOrderDialog open={!!ordering} onOpenChange={(o) => !o && setOrdering(null)} scope={{ mode: 'portfolio' }} prefill={ordering} />
    </div>
  )
}

function StatusCell({ row, onOrder }: { row: MaterialPlanRow; onOrder: (row: MaterialPlanRow) => void }) {
  return (
    <div className="flex flex-col items-start gap-1">
      <span className={cn('whitespace-nowrap', row.order_by ? 'font-medium text-destructive' : 'text-success')}>{shortText(row)}</span>
      {row.short_day && <span className="max-w-56 text-xs text-muted-foreground">{shortDetail(row)}</span>}
      {row.short_day && (
        <Button size="sm" variant={row.order_now ? 'default' : 'outline'} className="h-7 gap-1 px-2 text-xs" onClick={() => onOrder(row)}>
          <ShoppingCart className="size-3" /> Order
        </Button>
      )}
    </div>
  )
}

/** Weeks from the short week on are red; a week with no need is a dash. */
function weekCell(row: MaterialPlanRow, week: string, value: string) {
  const red = row.short_from !== null && week >= row.short_from && Number(value) > 0
  return <td key={week} className={cn('px-2 py-2', NUM, red ? 'bg-destructive/10 font-medium text-destructive' : Number(value) === 0 && 'text-muted-foreground')}>{Number(value) === 0 ? '—' : qty(value)}</td>
}

function Notes({ row }: { row: MaterialPlanRow }) {
  const notes = [
    Number(row.unscheduled) > 0 && `${qty(row.unscheduled)} for work with no dates`,
    Number(row.later) > 0 && `${qty(row.later)} after these weeks`,
    row.stock_unit_differs && 'stock is held in another unit, not counted',
    row.lines.some((l) => l.late) && 'late work needs it now',
  ].filter(Boolean)
  if (!notes.length) return null
  return <p className="text-xs text-muted-foreground">{notes.join(' · ')}</p>
}

function PlanTable({ plan, onOrder }: { plan: MaterialPlan; onOrder: (row: MaterialPlanRow) => void }) {
  return (
    <div className="hidden overflow-x-auto rounded-lg border [contain:inline-size] md:block">
      <table className="w-full text-sm">
        <thead className="bg-muted/50 text-xs text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left font-medium">Material</th>
            <th className={cn('px-2 py-2 font-medium', NUM)}>Still needed</th>
            <th className={cn('px-2 py-2 font-medium', NUM)}>In stock</th>
            <th className={cn('px-2 py-2 font-medium', NUM)}>On order</th>
            <th className="px-2 py-2 text-left font-medium">Order</th>
            {plan.weeks.map((w, i) => <th key={w} className={cn('px-2 py-2 font-medium whitespace-nowrap', NUM)}>{i === 0 ? 'This week' : `w/c ${dayLabel(w)}`}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y">
          {plan.materials.map((row) => (
            <tr key={row.material_id} className="align-top">
              <td className="px-3 py-2">
                <span className="font-medium">{row.material}</span> <span className="text-muted-foreground">{row.unit}</span>
                <p className="text-xs text-muted-foreground" title={row.lines.map((l) => `${l.work}: ${qty(l.need)}`).join('\n')}>
                  {row.lines.length ? `for ${row.lines.map((l) => l.work).slice(0, 2).join(', ')}${row.lines.length > 2 ? ` +${row.lines.length - 2}` : ''}` : 'BOQ work done'}
                </p>
                <Notes row={row} />
              </td>
              <td className={cn('px-2 py-2', NUM)}>{qty(row.still_needed)}</td>
              <td className={cn('px-2 py-2', NUM)}>{qty(row.on_hand)}</td>
              <td className={cn('px-2 py-2', NUM)}>{Number(row.on_order) ? qty(row.on_order) : '—'}</td>
              <td className="px-2 py-2"><StatusCell row={row} onOrder={onOrder} /></td>
              {plan.weeks.map((w, i) => weekCell(row, w, row.weeks[i]))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function PlanCards({ plan, onOrder }: { plan: MaterialPlan; onOrder: (row: MaterialPlanRow) => void }) {
  return (
    <ul className="flex flex-col gap-2 md:hidden">
      {plan.materials.map((row) => {
        const next = plan.weeks.map((w, i) => ({ w, v: row.weeks[i] })).filter((x) => Number(x.v) > 0).slice(0, 3)
        return (
          <li key={row.material_id} className={cn('rounded-lg border p-3', row.short_from && 'border-destructive/40')}>
            <div className="flex items-baseline justify-between gap-2">
              <span className="font-medium">{row.material}</span>
              <span className={cn('text-sm', row.order_by ? 'font-medium text-destructive' : 'text-success')}>{shortText(row)}</span>
            </div>
            <p className="text-sm text-muted-foreground">
              Needs {qty(row.still_needed)} {row.unit} · in stock {qty(row.on_hand)}
              {Number(row.on_order) ? ` · on order ${qty(row.on_order)}` : ''}
            </p>
            {next.length > 0 && <p className="text-sm">{next.map((x) => `${x.w === plan.weeks[0] ? 'This week' : `${dayLabel(x.w)} week`}: ${qty(x.v)}`).join(' · ')}</p>}
            {row.short_day && (
              <div className="mt-1 flex items-center justify-between gap-2">
                <p className="text-xs text-muted-foreground">{shortDetail(row)}</p>
                <Button size="sm" variant={row.order_now ? 'default' : 'outline'} className="h-8 shrink-0 gap-1" onClick={() => onOrder(row)}>
                  <ShoppingCart className="size-3.5" /> Order
                </Button>
              </div>
            )}
            <Notes row={row} />
          </li>
        )
      })}
    </ul>
  )
}
