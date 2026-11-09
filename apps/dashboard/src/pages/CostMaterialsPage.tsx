import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ChevronRight, Package, PackageSearch } from 'lucide-react'
import { Callout, DprHeader, DprSection, PageError, StatStrip } from '@/components/dpr-page'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { formatQuantity, maySeeBoq } from '@/lib/boq'
import { fetchProjectMaterials, type MaterialReconciliation } from '@/lib/cost'
import { COLOUR_DOT, COLOUR_TEXT, COLOUR_WORD } from '@/lib/cost-colours'
import { usePageTitle } from '@/lib/page-title'
import { fetchProjects } from '@/lib/projects'
import { useScope } from '@/lib/ScopeContext'
import { cn } from '@/lib/utils'

// CC-08: materials against the BOQ. Per material with a norm on a BOQ line (MP-01): what the work done so far should
// have used against what was used, and what is still needed to finish against what is on hand and coming, so a
// shortage is seen before closeout ("4 loads of metal short"). Backend: GET /cost/projects/{id}/materials.

function why(m: MaterialReconciliation): string {
  const u = m.unit
  switch (m.reason) {
    case 'over_norm':
    case 'near_norm':
      return `${formatQuantity(m.used)} ${u} used; the work done needed ${formatQuantity(m.should_have_used)} ${u}: ${formatQuantity(m.used_over_work ?? '0')} ${u} more than the work accounts for.`
    case 'within_norm':
      return `${formatQuantity(m.used)} ${u} used; the work done needed ${formatQuantity(m.should_have_used)} ${u}.`
    case 'used_no_work':
      return `${formatQuantity(m.used)} ${u} used and no work measured on the lines that use it.`
    case 'no_usage_recorded':
      return `The work done needed ${formatQuantity(m.should_have_used)} ${u}, but no use of it is recorded on site.`
    case 'nothing_yet':
      return 'No work on its lines and nothing used yet.'
    case 'unit_differs':
      return `The stock is kept in ${m.stock_unit} and the BOQ norm in ${u}, so they are not compared.`
  }
}

function Row({ m }: { m: MaterialReconciliation }) {
  const short = m.short_by !== null && Number(m.short_by) > 0
  return (
    <li className="flex gap-3 px-3 py-3">
      <span className={cn('mt-1 w-1 shrink-0 rounded-full', COLOUR_DOT[m.colour])} aria-hidden="true" />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex flex-col gap-0.5 sm:flex-row sm:items-baseline sm:justify-between sm:gap-3">
          <p className="font-medium">
            <span className={cn('mr-2 text-xs font-semibold uppercase tracking-wide', COLOUR_TEXT[m.colour])}>{COLOUR_WORD[m.colour]}</span>
            {m.material}
          </p>
          {short ? (
            <span className="text-sm font-semibold tabular-nums text-destructive">
              {formatQuantity(m.short_by!)} {m.unit} short to finish
            </span>
          ) : m.short_by !== null ? (
            <span className="text-sm tabular-nums text-success">Enough to finish</span>
          ) : null}
        </div>
        <p className="text-sm text-muted-foreground">{why(m)}</p>
        <dl className="grid grid-cols-3 gap-2 text-xs sm:grid-cols-6">
          {[
            ['BOQ needs', m.required_total],
            ['Still needed', m.still_needed],
            ['Received', m.received],
            ['Used', m.used],
            ['On hand', m.on_hand],
            ['On order', m.on_order],
          ].map(([label, value]) => (
            <div key={label}>
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="font-medium tabular-nums">
                {formatQuantity(value!)} <span className="font-normal text-muted-foreground">{m.unit}</span>
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </li>
  )
}

function ProjectPicker() {
  const projects = useQuery({ queryKey: ['scope-projects'], queryFn: fetchProjects })
  if (projects.isLoading) return <Skeleton className="h-32 rounded-lg" />
  return (
    <ul className="divide-y rounded-lg border">
      {(projects.data ?? []).map((p) => (
        <li key={p.id}>
          <Link to={`/cost/materials?project=${p.id}`} className="flex items-center gap-3 px-4 py-3 hover:bg-muted/60">
            <span className="flex size-8 items-center justify-center rounded-md bg-muted">
              <Package className="size-4" />
            </span>
            <span className="flex-1 font-medium">{p.name}</span>
            <ChevronRight className="size-4 text-muted-foreground" />
          </Link>
        </li>
      ))}
    </ul>
  )
}

export default function CostMaterialsPage() {
  const { me } = useAuth()
  const { scope } = useScope()
  usePageTitle('Materials vs BOQ')
  const allowed = maySeeBoq(me?.role)
  const projectId = scope.mode !== 'portfolio' ? scope.projectId : null
  const q = useQuery({
    queryKey: ['cost', 'materials', projectId],
    queryFn: () => fetchProjectMaterials(projectId!),
    enabled: allowed && !!projectId,
  })
  if (!allowed) {
    return (
      <div className="mx-auto flex w-full max-w-md flex-col items-center gap-3 py-16 text-center">
        <p className="font-medium">Materials vs BOQ is read from the BOQ and its rates.</p>
        <p className="text-sm text-muted-foreground">Only owners, admins, finance and project managers can open it.</p>
      </div>
    )
  }
  const header = (
    <DprHeader back={{ to: '/cost', label: 'Overview' }} crumb="Cost control" title="Materials vs BOQ" date={projectId && scope.mode !== 'portfolio' ? scope.projectName : 'Pick a project'} />
  )
  if (!projectId) {
    return (
      <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
        {header}
        <ProjectPicker />
      </div>
    )
  }
  if (q.isError) return <PageError message="Materials vs BOQ could not be loaded." onRetry={() => q.refetch()} back={{ to: '/cost', label: 'Overview' }} />
  const d = q.data
  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      {header}
      {q.isLoading || !d ? (
        <Skeleton className="h-64 rounded-lg" />
      ) : d.materials.length === 0 ? (
        <div className="flex flex-col items-start gap-2 rounded-lg border border-dashed px-4 py-6">
          <p className="font-medium">No BOQ line says what materials it uses yet.</p>
          <p className="text-sm text-muted-foreground">
            Set each line's materials per unit (cement bags per cum, sand cft per sq ft) on the BOQ, and this page sets what was used against
            what the work needed.{' '}
            <Link to={`/projects/${projectId}/boq`} className="font-medium underline underline-offset-2">
              Open the BOQ
            </Link>
          </p>
        </div>
      ) : (
        <>
          <StatStrip
            stats={[
              { label: 'Used beyond the work', value: `${d.summary.red} red · ${d.summary.amber} amber`, tone: d.summary.red > 0 ? 'bad' : d.summary.amber > 0 ? 'warn' : 'good' },
              { label: 'Within the norm', value: String(d.summary.green), tone: 'good' },
              { label: 'Short to finish', value: String(d.short_at_completion), tone: d.short_at_completion > 0 ? 'bad' : 'good', hint: 'beyond stock and open orders' },
              { label: 'Not judged', value: String(d.summary.grey) },
            ]}
          />
          {d.lines_without_norms > 0 && (
            <Callout tone="muted" icon={PackageSearch}>
              {d.lines_without_norms} BOQ {d.lines_without_norms === 1 ? 'line has' : 'lines have'} no materials set, so what they use is not
              counted here.{' '}
              <Link to={`/projects/${projectId}/boq`} className="font-medium underline underline-offset-2">
                Set them on the BOQ
              </Link>
            </Callout>
          )}
          <DprSection icon={Package} title="Materials, worst first" meta={d.materials.length}>
            <ul className="divide-y rounded-lg border">
              {d.materials.map((m) => (
                <Row key={m.material_id} m={m} />
              ))}
            </ul>
            <p className="mt-2 text-xs text-muted-foreground">
              Needed by the work done: work measured on each BOQ line × the line's materials per unit, with wastage. Green: what was used is within
              it; amber: up to 10% more; red: more. Short to finish: what the rest of the BOQ needs beyond what is on hand and on open orders. When
              to order it is on Planning › Material plan.
            </p>
          </DprSection>
        </>
      )}
    </div>
  )
}
