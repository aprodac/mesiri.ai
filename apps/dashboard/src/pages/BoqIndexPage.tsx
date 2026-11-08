import { Link, Navigate } from 'react-router-dom'
import { useQueries, useQuery } from '@tanstack/react-query'
import { Calculator, ChevronRight } from 'lucide-react'
import { DprHeader } from '@/components/dpr-page'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { fetchBoq, formatRupees, maySeeBoq } from '@/lib/boq'
import { fetchProjects } from '@/lib/projects'
import { useScope } from '@/lib/ScopeContext'
import { usePageTitle } from '@/lib/page-title'

// WEB-72: /boq, the BOQ entry in the sidebar. A BOQ belongs to a project (CC-02,
// /projects/:id/boq): with a project picked in the top bar it opens that one; otherwise it
// lists the projects with their totals.
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

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 pb-8 sm:px-2">
      <DprHeader back={{ to: '/today', label: 'Today' }} crumb="Cost control" title="BOQ & budget" date="Pick a project" />
      {projects.isLoading ? (
        <Skeleton className="h-32 rounded-lg" />
      ) : (projects.data ?? []).length === 0 ? (
        <p className="text-sm text-muted-foreground">No projects yet. Add one in Projects & Sites, then its BOQ.</p>
      ) : (
        <ul className="divide-y rounded-lg border">
          {(projects.data ?? []).map((p, i) => {
            const t = boqs[i]?.data?.totals
            return (
              <li key={p.id}>
                <Link to={`/projects/${p.id}/boq`} className="flex items-center gap-3 px-4 py-3 hover:bg-muted/60">
                  <span className="flex size-8 items-center justify-center rounded-md bg-muted">
                    <Calculator className="size-4" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium">{p.name}</span>
                    <span className="block text-xs text-muted-foreground tabular-nums">
                      {!t
                        ? 'Loading…'
                        : t.line_count === 0
                          ? 'No BOQ yet'
                          : `${t.line_count} lines · Contract ${formatRupees(t.contract_value)} · Budget ${formatRupees(t.budget_cost)}`}
                    </span>
                  </span>
                  <ChevronRight className="size-4 text-muted-foreground" />
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
