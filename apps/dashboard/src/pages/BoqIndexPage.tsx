import { Link, Navigate } from 'react-router-dom'
import { useQueries, useQuery } from '@tanstack/react-query'
import { ChevronRight, FileSpreadsheet } from 'lucide-react'
import { PageHeader, StatStrip, type Stat } from '@/components/dpr-page'
import { Hint } from '@/components/hint'
import { Skeleton } from '@/components/ui/skeleton'
import { NewProjectButton } from '@/components/new-project-button'
import { useAuth } from '@/lib/AuthContext'
import { fetchBoq, formatRupees, maySeeBoq, type BoqTotals } from '@/lib/boq'
import { fetchProjects } from '@/lib/projects'
import { useScope } from '@/lib/ScopeContext'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'

// WEB-72: /boq, the BOQ entry in the sidebar. A BOQ belongs to a project (CC-02, /projects/:id/boq): with a project
// picked in the top bar it opens that one; otherwise every project's BOQ at a glance (UX-28, 17 Nov: "/boq needs
// improvement"): the company's totals, then a card per project with its three numbers, how much is earned, and what
// needs doing (lines with no rate, no BOQ yet). Colour marks only a problem (UX-19).

const num = (v: string | null | undefined) => (v === null || v === undefined ? null : Number(v))

function marginTone(margin: number | null, contract: number | null): 'bad' | 'thin' | 'ok' | null {
  if (margin === null || !contract) return null
  const pct = (margin / contract) * 100
  return pct < 0 ? 'bad' : pct < 5 ? 'thin' : 'ok'
}

export default function BoqIndexPage() {
  const { me } = useAuth()
  const { scope } = useScope()
  usePageTitle('BOQ & budget')
  const allowed = maySeeBoq(me?.role)
  const projects = useQuery({ queryKey: ['scope-projects'], queryFn: fetchProjects, enabled: allowed })
  const boqs = useQueries({
    queries: (projects.data ?? []).map((p) => ({ queryKey: ['boq', p.id], queryFn: () => fetchBoq(p.id), enabled: allowed })),
  })

  if (!allowed) return <Navigate to="/today" replace />
  if (scope.mode === 'project' || scope.mode === 'site') return <Navigate to={`/projects/${scope.projectId}/boq`} replace />

  const list = projects.data ?? []
  const totals = boqs.map((b) => b.data?.totals).filter((t): t is BoqTotals => !!t && t.line_count > 0)
  const sum = (key: 'contract_value' | 'budget_cost' | 'margin' | 'earned') =>
    totals.reduce<number | null>((acc, t) => (num(t[key]) === null ? acc : (acc ?? 0) + (num(t[key]) as number)), null)
  const contract = sum('contract_value')
  const budget = sum('budget_cost')
  const margin = sum('margin')
  const tone = marginTone(margin, contract)
  const stats: Stat[] = [
    { label: 'Contract value', value: contract === null ? '—' : formatRupees(String(contract)), kind: 'money', explain: { term: 'contract value' }, hint: 'all projects' },
    { label: 'Budget cost', value: budget === null ? '—' : formatRupees(String(budget)), kind: 'bill', explain: { term: 'budget cost' }, share: contract && budget !== null ? budget / contract : undefined },
    {
      label: 'Margin', value: margin === null ? '—' : formatRupees(String(margin)), kind: 'margin', explain: { term: 'margin' },
      tone: tone === 'bad' ? 'bad' : tone === 'thin' ? 'attention' : 'default',
      hint: contract && margin !== null ? `${Math.round((margin / contract) * 100)}% of contract` : undefined,
    },
  ]

  return (
    <div className="mx-auto flex w-full flex-col gap-5 pb-8 sm:px-2">
      <PageHeader title="BOQ & budget" subtitle="Each project's work, what the client pays and what it costs you" actions={<NewProjectButton />} />
      {projects.isLoading ? (
        <Skeleton className="h-40 rounded-xl" />
      ) : list.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-14 text-center">
          <FileSpreadsheet className="size-6 text-muted-foreground" aria-hidden />
          <p className="m-0 font-medium">No projects yet</p>
          <NewProjectButton size="default" className="mt-2 gap-1.5" />
        </div>
      ) : (
        <>
          {totals.length > 1 && <StatStrip stats={stats} phoneCols={2} guide="boq.company" />}
          <ul className="grid gap-3 sm:grid-cols-2" data-guide="project.pick">
            {list.map((p, i) => (
              <ProjectCard key={p.id} id={p.id} name={p.name} totals={boqs[i]?.data?.totals} loading={boqs[i]?.isLoading} />
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

function ProjectCard({ id, name, totals, loading }: { id: string; name: string; totals?: BoqTotals; loading?: boolean }) {
  const to = `/projects/${id}/boq`
  if (loading || !totals) {
    return <li><Skeleton className="h-36 rounded-xl" /></li>
  }
  if (totals.line_count === 0) {
    return (
      <li>
        <Link to={to} className="flex h-full items-center gap-3 rounded-xl border border-dashed p-4 hover:bg-muted/40">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted"><FileSpreadsheet className="size-5" aria-hidden /></span>
          <span className="min-w-0 flex-1">
            <span className="block font-semibold">{name}</span>
            <span className="block text-sm text-muted-foreground">No BOQ yet: upload the estimate Excel</span>
          </span>
          <ChevronRight className="size-4 text-muted-foreground" aria-hidden />
        </Link>
      </li>
    )
  }
  const contract = num(totals.contract_value)
  const budget = num(totals.budget_cost)
  const margin = num(totals.margin)
  const earned = num(totals.earned)
  const tone = marginTone(margin, contract)
  const unpriced = Math.max(totals.lines_without_client_rate, totals.lines_without_budget_rate)
  const earnedPct = budget && earned !== null ? Math.min(100, Math.round((earned / budget) * 100)) : 0
  return (
    <li>
      <Link
        to={to}
        className={cn(
          'flex h-full flex-col gap-3 rounded-xl border bg-card p-4 transition-colors hover:border-foreground/30',
          tone === 'bad' && 'border-destructive/40',
        )}
      >
        <span className="flex items-center gap-2">
          <span className="min-w-0 flex-1 truncate text-base font-semibold">{name}</span>
          {unpriced > 0 && (
            <span className="shrink-0 rounded-full bg-draft-soft px-2 py-0.5 text-xs font-medium text-draft">{unpriced} unpriced</span>
          )}
          <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />
        </span>
        <span className="grid grid-cols-3 gap-2">
          <Figure label="Contract" value={formatRupees(totals.contract_value)} />
          <Figure label="Budget" value={formatRupees(totals.budget_cost)} />
          <Figure
            label="Margin"
            value={contract && margin !== null ? `${Math.round((margin / contract) * 100)}%` : '—'}
            className={tone === 'bad' ? 'text-destructive' : tone === 'thin' ? 'text-draft' : undefined}
          />
        </span>
        <span className="flex flex-col gap-1">
          <span className="flex items-center justify-between text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1">Earned so far <Hint term="earned so far" side="top" /></span>
            <span className="tabular-nums">{earned === null ? 'no work counted yet' : `${formatRupees(totals.earned)} · ${earnedPct}%`}</span>
          </span>
          <span className="block h-1.5 overflow-hidden rounded-full bg-muted" role="img" aria-label={`${earnedPct}% earned`}>
            <span className="block h-full rounded-full bg-info" style={{ width: `${earnedPct}%` }} />
          </span>
        </span>
        <span className="text-xs text-muted-foreground tabular-nums">{totals.line_count} lines</span>
      </Link>
    </li>
  )
}

function Figure({ label, value, className }: { label: string; value: string; className?: string }) {
  return (
    <span className="min-w-0">
      <span className="block text-xs text-muted-foreground">{label}</span>
      <span className={cn('block truncate text-base font-semibold tabular-nums', className)}>{value}</span>
    </span>
  )
}
