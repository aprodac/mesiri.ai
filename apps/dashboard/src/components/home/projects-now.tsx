import * as React from 'react'
import { Link } from 'react-router-dom'
import { useQueries, useQuery } from '@tanstack/react-query'
import { AlertTriangle, Building2, CalendarX, ChevronRight, CircleCheck, Send, Users } from 'lucide-react'
import { useAuth } from '@/lib/AuthContext'
import { useScope } from '@/lib/ScopeContext'
import { useModuleEnabled } from '@/lib/modules'
import { fetchSiteDaysApi } from '@/lib/api'
import { maySeeBoq } from '@/lib/boq'
import { fetchPortfolio, type VarianceColour } from '@/lib/cost'
import { fetchSchedule } from '@/lib/schedule'
import { localIsoDate, plural } from '@/lib/site-day'
import { appNow } from '@/lib/clock'
import { cn } from '@/lib/utils'

// UX-68 (asked 18 Nov 2026: Home separate from Today): the owner's and the project manager's projects, one line each,
// so twenty sites never become twenty cards: how far it is, on budget or not, late work, its sites reported today,
// people on site, open issues, its daily report. A line opens that project's Today. Every figure comes from a query
// the dashboard already has (the same keys as Today, This week and Cost control), asked only when the role may read it.

const BUDGET: Record<VarianceColour, { label: string; className: string }> = {
  green: { label: 'On budget', className: 'bg-success-soft text-success' },
  amber: { label: 'Watch cost', className: 'bg-draft-soft text-draft' },
  red: { label: 'Over budget', className: 'bg-destructive/10 text-destructive' },
  grey: { label: 'No budget yet', className: 'bg-muted text-muted-foreground' },
}

const n = (v: string | number | null | undefined) => Number(v ?? 0) || 0

export function ProjectsNow() {
  const { me } = useAuth()
  const { scope } = useScope()
  const on = useModuleEnabled()
  const role = (me?.role || '').toUpperCase()
  const show = ['OWNER', 'ADMIN', 'SUPER_ADMIN', 'PROJECT_MANAGER'].includes(role)
  const projectId = scope.mode === 'portfolio' ? undefined : scope.projectId
  const [today] = React.useState(() => localIsoDate(appNow()))
  const opts = { retry: false, staleTime: 60_000 } as const
  const days = useQuery({ queryKey: ['site-days', today, projectId], queryFn: () => fetchSiteDaysApi(today, projectId), enabled: show, ...opts })
  const portfolio = useQuery({ queryKey: ['home', 'portfolio'], queryFn: fetchPortfolio, enabled: show && maySeeBoq(role) && on('cost'), ...opts })
  const projects = days.data?.projects ?? []
  const schedules = useQueries({
    queries: projects.slice(0, 12).map((p) => ({ queryKey: ['schedule', p.project_id], queryFn: () => fetchSchedule(p.project_id), enabled: show, ...opts })),
  })
  if (!show || days.isError || (!days.isLoading && projects.length === 0)) return null

  const cost = new Map((portfolio.data?.projects ?? []).map((p) => [p.project_id, p]))
  return (
    <section className="overflow-hidden rounded-xl border bg-card shadow-xs" aria-label="Your projects" data-guide="home.projects">
      <header className="flex items-center gap-2 border-b px-4 py-2.5">
        <h2 className="text-[15px] font-semibold">Your projects</h2>
        {projects.length > 0 && <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-semibold tabular-nums">{projects.length}</span>}
        <Link to="/today" className="ml-auto inline-flex items-center gap-0.5 text-xs font-medium text-primary-ink hover:underline" data-guide="home.today">
          Today on site <ChevronRight className="size-3.5" aria-hidden />
        </Link>
      </header>
      {days.isLoading ? (
        <div className="flex flex-col gap-2 p-4">
          {[0, 1].map((i) => <div key={i} className="h-12 animate-pulse rounded-lg bg-muted" />)}
        </div>
      ) : (
        <ul className="divide-y">
          {projects.map((p, i) => {
            const sites = (days.data?.items ?? []).filter((s) => s.project_id === p.project_id)
            const reported = sites.filter((s) => s.last_update_at || s.workers || s.work_items).length
            const workers = sites.reduce((t, s) => t + s.workers, 0)
            const issues = sites.reduce((t, s) => t + s.open_issues, 0)
            const c = cost.get(p.project_id)
            const done = c?.percent_done != null ? Math.round(n(c.percent_done)) : null
            const budget = c ? BUDGET[c.colour] : null
            const late = (schedules[i]?.data?.activities ?? []).filter((a) => a.state === 'late')
            const all = sites.length > 0 && reported >= sites.length
            return (
              <li key={p.project_id}>
                <Link to={`/today?project=${p.project_id}`} className="group flex flex-col gap-2 px-4 py-3 transition-colors hover:bg-muted/40 sm:flex-row sm:items-center sm:gap-4">
                  <div className="flex min-w-0 flex-1 items-center gap-3">
                    <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary-ink" aria-hidden>
                      <Building2 className="size-4" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <span className="truncate text-sm font-semibold">{p.project_name}</span>
                        {budget && <span className={cn('rounded-full px-2 py-px text-[11px] font-semibold', budget.className)}>{budget.label}</span>}
                        {late.length > 0 && (
                          <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-px text-[11px] font-semibold', late.some((a) => a.critical) ? 'bg-destructive/10 text-destructive' : 'bg-draft-soft text-draft')}>
                            <CalendarX className="size-3" aria-hidden /> {late.length} late
                          </span>
                        )}
                      </div>
                      {done != null ? (
                        <div className="mt-1.5 flex items-center gap-2">
                          <div className="h-1.5 max-w-48 flex-1 overflow-hidden rounded-full bg-muted">
                            <div className="h-full rounded-full bg-primary" style={{ width: `${Math.min(100, done)}%` }} />
                          </div>
                          <span className="text-xs text-muted-foreground tabular-nums">{done}% done</span>
                        </div>
                      ) : (
                        <p className="text-xs text-muted-foreground">{plural(sites.length, 'site')}</p>
                      )}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2 pl-12 text-xs sm:pl-0">
                    <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-1 font-medium tabular-nums', all ? 'bg-success-soft text-success' : reported ? 'bg-info-soft text-info' : 'bg-muted text-muted-foreground')} title="Sites reported today">
                      {all ? <CircleCheck className="size-3.5" aria-hidden /> : null}
                      {reported}/{sites.length} reported
                    </span>
                    <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-1 tabular-nums text-muted-foreground" title="People on site today">
                      <Users className="size-3.5" aria-hidden /> {workers}
                    </span>
                    <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-1 tabular-nums', issues ? 'bg-destructive/10 font-medium text-destructive' : 'bg-muted text-muted-foreground')} title="Open issues">
                      <AlertTriangle className="size-3.5" aria-hidden /> {issues}
                    </span>
                    {p.sent && (
                      <span className="hidden items-center gap-1 rounded-full bg-success-soft px-2 py-1 font-medium text-success md:inline-flex" title="Today's report went out">
                        <Send className="size-3.5" aria-hidden /> Sent
                      </span>
                    )}
                    <ChevronRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" aria-hidden />
                  </div>
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
