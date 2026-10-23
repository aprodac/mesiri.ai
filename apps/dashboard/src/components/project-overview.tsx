import * as React from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Building2,
  AlertTriangle,
  ExternalLink,
  ChevronRight,
  ClipboardList,
  Loader2,
  History,
} from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { fetchProject, fetchSitesFull, type Site, type Project } from '@/lib/projects'
import { api } from '@/lib/api'

interface ProjectOverviewProps {
  projectId: string
}

interface TimelineEntry {
  id: string
  event_type: string
  summary: string
  occurred_at: string
}

const STATUS_BADGES = {
  success: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/20',
  warning: 'bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/20',
  critical: 'bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-500/20',
  neutral: 'bg-muted text-muted-foreground border-border',
} as const

const SITE_STATUS_COLORS = {
  active: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/20',
  inactive: 'bg-muted text-muted-foreground border-border',
  pending: 'bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/20',
} as const

export function ProjectOverview({ projectId }: ProjectOverviewProps) {
  const navigate = useNavigate()

  // Fetch Project Details
  const { data: project, isLoading: isProjectLoading, isError: isProjectError } = useQuery<Project>({
    queryKey: ['project-overview-details', projectId],
    queryFn: () => fetchProject(projectId),
    staleTime: 30_000,
  })

  // Fetch Project Sites
  const { data: sites = [], isLoading: isSitesLoading } = useQuery<Site[]>({
    queryKey: ['project-overview-sites', projectId],
    queryFn: () => fetchSitesFull(projectId),
    staleTime: 30_000,
  })

  // Fetch Project Timeline logs
  const { data: timeline = [], isLoading: isTimelineLoading } = useQuery<TimelineEntry[]>({
    queryKey: ['project-overview-timeline', projectId],
    queryFn: async () => {
      const res = await api.get<{ items: TimelineEntry[] }>('/timeline', {
        params: { project_id: projectId, limit: 6 },
      })
      return res.data.items
    },
    staleTime: 30_000,
  })

  // Derive Attention Required items from site states or critical issues
  const attentionItems = React.useMemo(() => {
    if (!project) return []
    const items: Array<{
      id: string
      type: 'critical_site' | 'warning_site' | 'project_issues'
      title: string
      context: string
      severity: 'critical' | 'warning'
      action: () => void
    }> = []

    // 1. Critical sites
    sites.forEach((site) => {
      if (site.status === 'critical' || site.status === 'error') {
        items.push({
          id: `site-${site.id}`,
          type: 'critical_site',
          title: `Site Critical Status: ${site.name}`,
          context: `Operational dashboard reports critical alert. Open site logs to investigate.`,
          severity: 'critical',
          action: () => navigate(`/overview?project=${projectId}&site=${site.id}`),
        })
      } else if (site.status === 'warning') {
        items.push({
          id: `site-${site.id}`,
          type: 'warning_site',
          title: `Site Warning Alert: ${site.name}`,
          context: `Unresolved updates or delayed reports flags present on site.`,
          severity: 'warning',
          action: () => navigate(`/overview?project=${projectId}&site=${site.id}`),
        })
      }
    })

    // 2. Open project issues
    if (project.openIssues > 0) {
      items.push({
        id: 'issues-project',
        type: 'project_issues',
        title: `${project.openIssues} Active Project Issue(s)`,
        context: `Factual delays or blockers registered under project scope. Check issues tab.`,
        severity: project.openIssues > 2 ? 'critical' : 'warning',
        action: () => navigate(`/operations/issues?project=${projectId}&type=issues-delays`),
      })
    }

    return items.slice(0, 4)
  }, [project, sites, projectId, navigate])

  if (isProjectLoading) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-muted-foreground gap-2">
        <Loader2 className="size-4 animate-spin text-primary" />
        Loading operational project dashboard...
      </div>
    )
  }

  if (isProjectError || !project) {
    return (
      <div className="bg-destructive/10 border border-destructive text-destructive p-4 rounded text-center text-sm">
        Failed to load operational project overview. Please try again.
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Project Context Header */}
      <Card className="rounded-md border-border/70 shadow-xs overflow-hidden">
        <CardContent className="p-4 sm:p-5">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <Building2 className="size-5 text-blue-500 dark:text-blue-400" />
                <h1 className="text-lg font-bold text-foreground leading-tight">{project.name}</h1>
                <Badge variant="outline" className={`text-xs rounded-sm py-0.5 font-semibold ${STATUS_BADGES[project.status as keyof typeof STATUS_BADGES] || STATUS_BADGES.neutral}`}>
                  {project.statusLabel || project.status}
                </Badge>
              </div>
              <p className="text-xs text-muted-foreground font-semibold">
                {[project.code, project.client, project.location, `${sites.length} ${sites.length === 1 ? 'site' : 'sites'}`].filter(Boolean).join(' · ')}
              </p>
              <p className="text-xs text-muted-foreground italic font-medium pt-1">
                Monitoring operational field activity across all sites in this project.
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              asChild
              className="h-7 text-xs font-bold border border-blue-500/30 text-blue-600 hover:bg-blue-600 hover:text-white dark:text-blue-400 dark:hover:bg-blue-500 bg-transparent rounded-md px-3 transition-all shrink-0 w-fit"
            >
              <Link to={`/projects/${project.id}`}>
                <ExternalLink className="size-3 mr-1" />
                View Project Details
              </Link>
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Attention Required Section */}
      {attentionItems.length > 0 && (
        <Card className="rounded-md border-border/70 shadow-xs overflow-hidden border-l-4 border-l-rose-500">
          <CardHeader className="pb-2 border-b bg-rose-500/[0.01]">
            <CardTitle className="text-xs uppercase tracking-wider text-rose-600 dark:text-rose-400 font-bold flex items-center gap-1.5">
              <AlertTriangle className="size-4 animate-pulse" />
              Attention Required
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-3 divide-y divide-border/40 text-xs">
            {attentionItems.map((item) => (
              <div
                key={item.id}
                onClick={item.action}
                className="flex items-start justify-between py-2.5 first:pt-0 last:pb-0 cursor-pointer group hover:text-primary transition-all"
              >
                <div className="space-y-0.5">
                  <h4 className="font-bold text-foreground group-hover:text-primary transition-colors flex items-center gap-1">
                    {item.title}
                  </h4>
                  <p className="text-muted-foreground font-medium">{item.context}</p>
                </div>
                <ChevronRight className="size-4 text-muted-foreground/40 group-hover:text-primary transition-colors self-center" />
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Project Snapshot KPIs */}
      <div className="grid gap-4 sm:grid-cols-2 md:grid-cols-4">
        <Card className="rounded-md border-border/70 shadow-xs">
          <CardContent className="p-4">
            <span className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider">Total Sites</span>
            <div className="flex items-baseline gap-2 mt-1">
              <span className="text-2xl font-bold font-mono">{sites.length}</span>
              <span className="text-xs text-muted-foreground">registered</span>
            </div>
          </CardContent>
        </Card>
        <Card className="rounded-md border-border/70 shadow-xs">
          <CardContent className="p-4">
            <span className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider">Active Issues</span>
            <div className="flex items-baseline gap-2 mt-1">
              <span className="text-2xl font-bold font-mono text-rose-600 dark:text-rose-400">{project.openIssues}</span>
              <span className="text-xs text-muted-foreground">unresolved</span>
            </div>
          </CardContent>
        </Card>
        <Card className="rounded-md border-border/70 shadow-xs">
          <CardContent className="p-4">
            <span className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider">Reporting Cutoff</span>
            <div className="flex items-baseline gap-2 mt-1">
              <span className="text-xl font-bold font-mono">{project.reportingCutoffTime}</span>
              <span className="text-xs text-muted-foreground">daily cutoff</span>
            </div>
          </CardContent>
        </Card>
        <Card className="rounded-md border-border/70 shadow-xs">
          <CardContent className="p-4">
            <span className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider">Reporting Timezone</span>
            <div className="flex items-baseline gap-2 mt-1">
              <span className="text-base font-bold font-mono truncate max-w-[130px] block">{project.reportingTimezone}</span>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Primary Sites Section */}
      <Card className="rounded-md border-border/70 shadow-xs overflow-hidden">
        <CardHeader className="pb-3 border-b border-l-3 border-l-violet-500 bg-transparent flex flex-row items-center justify-between gap-4">
          <div>
            <CardTitle className="text-xs uppercase tracking-wider text-violet-600 dark:text-violet-400 font-bold">
              Project Sites
            </CardTitle>
            <CardDescription className="text-xs">
              Manage and monitor live daily reporting status per site.
            </CardDescription>
          </div>
          <Badge variant="outline" className="font-mono font-bold text-xs bg-violet-500/5 text-violet-700 dark:text-violet-400 border-violet-500/20">
            {sites.length} Active
          </Badge>
        </CardHeader>
        <CardContent className="pt-4 text-xs">
          {isSitesLoading ? (
            <div className="flex justify-center p-6"><Loader2 className="size-4 animate-spin text-primary" /></div>
          ) : sites.length === 0 ? (
            <div className="text-center py-6 text-muted-foreground italic">No sites registered.</div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="font-bold text-foreground">Site Name</TableHead>
                    <TableHead className="font-bold text-foreground">Status</TableHead>
                    <TableHead className="font-bold text-foreground text-right pr-4">Action</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sites.map((site) => (
                    <TableRow key={site.id} className="hover:bg-muted/30 transition-colors">
                      <TableCell className="font-semibold text-foreground text-sm py-2.5">
                        {site.name}
                      </TableCell>
                      <TableCell className="py-2.5">
                        <Badge variant="outline" className={`text-xs rounded-sm py-0.5 font-semibold ${SITE_STATUS_COLORS[site.status as keyof typeof SITE_STATUS_COLORS] || SITE_STATUS_COLORS.inactive}`}>
                          {site.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right pr-4 py-2.5">
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-6 text-[11px] font-bold border border-violet-500/30 text-violet-600 hover:bg-violet-600 hover:text-white dark:text-violet-400 dark:hover:bg-violet-500 transition-all rounded-md px-2.5"
                          onClick={() => navigate(`/overview?project=${projectId}&site=${site.id}`)}
                        >
                          Open Site
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Today's Field Activity Grid */}
      <Card className="rounded-md border-border/70 shadow-xs overflow-hidden">
        <CardHeader className="pb-3 border-b border-l-3 border-l-sky-500">
          <CardTitle className="text-xs uppercase tracking-wider text-sky-600 dark:text-sky-400 font-bold">
            Today's Field Activity
          </CardTitle>
          <CardDescription className="text-xs">
            Quick operational access to daily report categories.
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-4 text-xs">
          <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-4">
            <Link
              to={`/operations/daily-reports?project=${projectId}&type=work-progress`}
              className="flex items-center justify-between p-3 border border-border/50 rounded-md hover:border-sky-500/40 hover:bg-sky-500/[0.01] transition-all group"
            >
              <div className="flex items-center gap-2">
                <ClipboardList className="size-4 text-sky-500 shrink-0" />
                <span className="font-semibold text-foreground group-hover:text-sky-600 transition-colors">Work Progress</span>
              </div>
              <ChevronRight className="size-3.5 text-muted-foreground/50 group-hover:text-sky-500 transition-colors" />
            </Link>
            <Link
              to={`/operations/daily-reports?project=${projectId}&type=workforce`}
              className="flex items-center justify-between p-3 border border-border/50 rounded-md hover:border-sky-500/40 hover:bg-sky-500/[0.01] transition-all group"
            >
              <div className="flex items-center gap-2">
                <ClipboardList className="size-4 text-emerald-500 shrink-0" />
                <span className="font-semibold text-foreground group-hover:text-emerald-600 transition-colors">Workforce</span>
              </div>
              <ChevronRight className="size-3.5 text-muted-foreground/50 group-hover:text-emerald-500 transition-colors" />
            </Link>
            <Link
              to={`/operations/daily-reports?project=${projectId}&type=equipment`}
              className="flex items-center justify-between p-3 border border-border/50 rounded-md hover:border-sky-500/40 hover:bg-sky-500/[0.01] transition-all group"
            >
              <div className="flex items-center gap-2">
                <ClipboardList className="size-4 text-orange-500 shrink-0" />
                <span className="font-semibold text-foreground group-hover:text-orange-600 transition-colors">Equipment & Machinery</span>
              </div>
              <ChevronRight className="size-3.5 text-muted-foreground/50 group-hover:text-orange-500 transition-colors" />
            </Link>
            <Link
              to={`/operations/daily-reports?project=${projectId}&type=material-in`}
              className="flex items-center justify-between p-3 border border-border/50 rounded-md hover:border-sky-500/40 hover:bg-sky-500/[0.01] transition-all group"
            >
              <div className="flex items-center gap-2">
                <ClipboardList className="size-4 text-teal-500 shrink-0" />
                <span className="font-semibold text-foreground group-hover:text-teal-600 transition-colors">Material In</span>
              </div>
              <ChevronRight className="size-3.5 text-muted-foreground/50 group-hover:text-teal-500 transition-colors" />
            </Link>
          </div>

          <div className="flex justify-end mt-4">
            <Button
              variant="outline"
              size="sm"
              asChild
              className="h-7 text-xs font-bold border border-sky-500/30 text-sky-600 hover:bg-sky-600 hover:text-white dark:text-sky-400 dark:hover:bg-sky-500 transition-all rounded-md px-3"
            >
              <Link to={`/operations/daily-reports?project=${projectId}`}>
                View All Daily Reports
                <ChevronRight className="size-3 ml-0.5" />
              </Link>
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Recent Activity Section */}
      <Card className="rounded-md border-border/70 shadow-xs overflow-hidden">
        <CardHeader className="pb-3 border-b border-l-3 border-l-teal-500">
          <CardTitle className="text-xs uppercase tracking-wider text-teal-600 dark:text-teal-400 font-bold">
            Recent Timeline Activity
          </CardTitle>
          <CardDescription className="text-xs">
            Live cross-site event log feed.
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-4 text-xs">
          {isTimelineLoading ? (
            <div className="flex justify-center p-6"><Loader2 className="size-4 animate-spin text-primary" /></div>
          ) : timeline.length === 0 ? (
            <div className="text-center py-6 text-muted-foreground italic">No recent timeline events found.</div>
          ) : (
            <div className="space-y-3">
              {timeline.map((entry) => (
                <div key={entry.id} className="flex gap-2.5 items-start">
                  <div className="size-6 rounded-full border border-teal-500/20 bg-teal-500/5 flex items-center justify-center text-teal-600 shrink-0 mt-0.5">
                    <History className="size-3" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-foreground font-semibold leading-normal truncate">
                      {entry.summary || entry.event_type}
                    </p>
                    <span className="text-[10px] text-muted-foreground font-medium">
                      {new Date(entry.occurred_at).toLocaleString()}
                    </span>
                  </div>
                </div>
              ))}

              <div className="border-t border-border/40 pt-4 flex justify-end">
                <Button
                  variant="outline"
                  size="sm"
                  asChild
                  className="h-7 text-xs font-bold border border-teal-500/30 text-teal-600 hover:bg-teal-600 hover:text-white dark:text-teal-400 dark:hover:bg-teal-500 transition-all rounded-md px-3"
                >
                  <Link to={`/timeline?project=${projectId}`}>
                    View Timeline
                    <ChevronRight className="size-3 ml-0.5" />
                  </Link>
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
