import * as React from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, Send } from 'lucide-react'
import { useScope } from '@/lib/ScopeContext'
import {
  fetchSiteDaysApi,
  fetchSiteIssuesApi,
  sendProjectDprNowApi,
  setSiteDayConditionsApi,
  type ProjectDayItem,
  type SiteDayItem,
  type SiteIssueItem,
} from '@/lib/api'
import { useToast } from '@/components/ui/toast-notification'
import { GettingStartedCard } from '@/components/getting-started-card'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn, formatClock } from '@/lib/utils'

// Today page (WEB-03): every site's working day, grouped by project, with
// what is missing and where each project's DPR stands. Data comes from
// GET /dpr/site-days (BE-08), live counts included; "no work today" is the
// BE-14 site condition and "Send now" the BE-16 send.

const CHIP = 'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold whitespace-nowrap'

const MISSING_LABELS: Record<string, string> = {
  work_done: 'work done',
  labour: 'labour count',
  photos: 'photos',
  materials: 'materials',
  weather: 'weather',
  tomorrow_plan: "tomorrow's plan",
}

const SEVERITY_RANK: Record<string, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 }
const FROZEN = ['approved', 'published']

function localIsoDate(d: Date): string {
  const offset = d.getTimezoneOffset() * 60_000
  return new Date(d.getTime() - offset).toISOString().slice(0, 10)
}

function formatTime(iso: string | null): string | null {
  if (!iso) return null
  return new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

// The API's own reason ("today's DPR ... has already been sent"), which
// reaches the page since BE-28 stopped turning such errors into 500s.
function errorDetail(err: unknown): string | null {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail !== 'string' || !detail) return null
  return detail.charAt(0).toUpperCase() + detail.slice(1)
}

function hasUpdates(site: SiteDayItem): boolean {
  return site.work_items > 0 || site.workers > 0 || site.site_working === 'none'
}

function siteStatus(site: SiteDayItem): { label: string; className: string } {
  switch (site.status) {
    case 'needs_details':
      return { label: 'Needs details', className: 'bg-draft-soft text-draft' }
    case 'ready':
      return { label: 'Ready', className: 'bg-info-soft text-info' }
    case 'in_review':
      return { label: 'With engineer', className: 'bg-info-soft text-info' }
    case 'approved':
      return { label: 'Confirmed', className: 'bg-success-soft text-success' }
    case 'published':
      return { label: 'Sent', className: 'bg-success-soft text-success' }
    case 'not_reported':
      return { label: 'Not reported', className: 'bg-muted text-muted-foreground' }
    default:
      return hasUpdates(site)
        ? { label: 'Collecting', className: 'bg-info-soft text-info' }
        : { label: 'No updates', className: 'bg-muted text-muted-foreground' }
  }
}

function missingText(site: SiteDayItem): string | null {
  const missing = site.missing_sections
  if (!missing) return null
  const parts = [...missing.blocking, ...missing.optional].map((key) => MISSING_LABELS[key] ?? key)
  return parts.length ? `Missing: ${parts.join(', ')}` : null
}

function projectDprLabel(project: ProjectDayItem, sites: SiteDayItem[]): string {
  if (project.sent) return 'DPR sent'
  if (project.send_requested) return 'Sending…'
  const waiting = sites.filter((s) => !FROZEN.includes(s.status)).map((s) => s.site_name)
  if (waiting.length === 0) return 'All sites confirmed'
  if (waiting.length === 1) return `Waiting for ${waiting[0]}`
  return `Waiting for ${waiting.length} sites`
}

function openFor(occurredAt: string): string {
  const days = Math.floor((Date.now() - new Date(occurredAt).getTime()) / 86_400_000)
  if (days <= 0) return 'Today'
  return days === 1 ? '1 day' : `${days} days`
}

function timeLost(minutes: number | null | undefined): string {
  if (!minutes) return '—'
  if (minutes < 60) return `${minutes} min`
  const hours = Math.round((minutes / 60) * 10) / 10
  return `${hours} hr${hours === 1 ? '' : 's'}`
}

function Stat({ value, label }: { value: number; label: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className={cn('text-xl font-bold', value === 0 && 'text-muted-foreground')}>{value || '—'}</span>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  )
}

function SiteCard({
  site,
  singleSite,
  busy,
  onNoWork,
}: {
  site: SiteDayItem
  singleSite: boolean
  busy: boolean
  onNoWork: (site: SiteDayItem) => void
}) {
  const status = siteStatus(site)
  const missing = missingText(site)
  const lastAt = formatTime(site.last_update_at)
  const canMarkNoWork = !hasUpdates(site) && !FROZEN.includes(site.status) && site.status !== 'in_review'

  return (
    <article className="rounded-2xl border bg-card p-5 flex flex-col gap-4">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-0.5 min-w-0">
          <span className="text-base font-semibold truncate">{site.site_name}</span>
          <span className="text-sm text-muted-foreground truncate">
            {singleSite ? 'Whole project' : site.project_name}
          </span>
        </div>
        <span className={cn(CHIP, status.className)}>{status.label}</span>
      </div>

      <div className="grid grid-cols-3 gap-2 border-y py-3">
        <Stat value={site.workers} label="workers" />
        <Stat value={site.work_items} label="work items" />
        <Stat value={site.photos} label="photos" />
      </div>

      {site.site_working === 'none' ? (
        <p className="text-sm text-muted-foreground">Marked as no work today.</p>
      ) : missing ? (
        <p className="text-sm rounded-lg bg-draft-soft text-draft px-3 py-2">{missing}</p>
      ) : site.latest_update ? (
        <p className="text-sm text-foreground/80 line-clamp-3">{site.latest_update}</p>
      ) : (
        <p className="text-sm text-muted-foreground">Nothing received today.</p>
      )}

      <p className="text-xs text-muted-foreground">
        {lastAt
          ? `Last update ${lastAt}${site.last_update_by ? ` · ${site.last_update_by}` : ''}`
          : 'No updates yet today'}
        {site.open_issues > 0 && ` · ${site.open_issues} open issue${site.open_issues === 1 ? '' : 's'}`}
      </p>

      {(site.drafts ?? 0) > 0 && (
        <p className="text-xs font-semibold text-draft">
          {site.drafts} item{site.drafts === 1 ? '' : 's'} still to confirm
        </p>
      )}

      <div className="mt-auto flex flex-col gap-2">
        {canMarkNoWork && (
          <Button variant="outline" className="h-11 font-semibold" disabled={busy} onClick={() => onNoWork(site)}>
            Mark as no work today
          </Button>
        )}
        <Button asChild variant="outline" className="h-11 font-semibold">
          <Link to={`/operations/daily-reports?project=${site.project_id}`}>
            {site.daily_report_id ? 'Open daily reports' : 'Daily reports'}
          </Link>
        </Button>
      </div>
    </article>
  )
}

export default function TodayPage() {
  const toast = useToast()
  const queryClient = useQueryClient()
  const { scope } = useScope()
  const [searchParams] = useSearchParams()
  const date = searchParams.get('date') || localIsoDate(new Date())
  const projectFilter = scope.mode === 'portfolio' ? undefined : scope.projectId
  const [busySite, setBusySite] = React.useState<string | null>(null)
  const [busyProject, setBusyProject] = React.useState<string | null>(null)

  const daysQuery = useQuery({
    queryKey: ['site-days', date, projectFilter],
    queryFn: () => fetchSiteDaysApi(date, projectFilter),
    refetchInterval: 60_000,
  })
  const issuesQuery = useQuery({
    queryKey: ['today-open-issues', projectFilter],
    queryFn: () => fetchSiteIssuesApi({ projectId: projectFilter, limit: 100 }),
    refetchInterval: 120_000,
  })

  const sites = React.useMemo(() => daysQuery.data?.items ?? [], [daysQuery.data])
  const projects = React.useMemo(() => daysQuery.data?.projects ?? [], [daysQuery.data])
  const siteNames = React.useMemo(() => new Map(sites.map((s) => [s.site_id, s.site_name])), [sites])

  const totals = React.useMemo(
    () => ({
      reported: sites.filter(hasUpdates).length,
      workers: sites.reduce((n, s) => n + s.workers, 0),
      workItems: sites.reduce((n, s) => n + s.work_items, 0),
      openIssues: sites.reduce((n, s) => n + s.open_issues, 0),
    }),
    [sites],
  )

  const openIssues = React.useMemo(() => {
    const items: SiteIssueItem[] = issuesQuery.data?.items ?? []
    return items
      .filter((i) => ['OPEN', 'ACKNOWLEDGED'].includes(i.status.toUpperCase()))
      .sort(
        (a, b) =>
          (SEVERITY_RANK[a.severity.toUpperCase()] ?? 9) - (SEVERITY_RANK[b.severity.toUpperCase()] ?? 9) ||
          new Date(a.occurred_at).getTime() - new Date(b.occurred_at).getTime(),
      )
      .slice(0, 8)
  }, [issuesQuery.data])

  const attention = React.useMemo(() => {
    const lines: { key: string; text: string; note: string }[] = []
    for (const project of projects) {
      const projectSites = sites.filter((s) => s.project_id === project.project_id)
      const waiting = projectSites.filter((s) => !FROZEN.includes(s.status))
      if (!project.sent && projectSites.length > 1 && waiting.length > 0 && waiting.length < projectSites.length) {
        lines.push({
          key: `p-${project.project_id}`,
          text: `${project.project_name} DPR is waiting for ${waiting.map((s) => s.site_name).join(', ')}`,
          note: project.dpr_send_deadline ? `Sends at ${formatClock(project.dpr_send_deadline)}` : '',
        })
      }
    }
    for (const site of sites) {
      if (!hasUpdates(site) && !FROZEN.includes(site.status)) {
        lines.push({ key: `n-${site.site_id}`, text: `${site.site_name} hasn't reported today`, note: site.project_name })
      } else if (site.status === 'needs_details' && site.missing_sections?.blocking.length) {
        const parts = site.missing_sections.blocking.map((k) => MISSING_LABELS[k] ?? k).join(' and ')
        lines.push({ key: `m-${site.site_id}`, text: `${site.site_name} is missing ${parts}`, note: site.project_name })
      }
    }
    return lines
  }, [projects, sites])

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['site-days'] })
    queryClient.invalidateQueries({ queryKey: ['today-open-issues'] })
  }

  const markNoWork = async (site: SiteDayItem) => {
    setBusySite(site.site_id)
    try {
      await setSiteDayConditionsApi(site.site_id, date, { site_working: 'none' })
      toast.success('Marked as no work', `${site.site_name} has nothing to report today.`)
      refresh()
    } catch (err) {
      toast.error('Could not update', errorDetail(err) ?? `${site.site_name} could not be marked.`)
    } finally {
      setBusySite(null)
    }
  }

  const sendNow = async (project: ProjectDayItem) => {
    setBusyProject(project.project_id)
    try {
      await sendProjectDprNowApi(project.project_id)
      toast.success('Sending the DPR', `${project.project_name}'s DPR goes out within a minute.`)
      refresh()
    } catch (err) {
      toast.error('Could not send', errorDetail(err) ?? `${project.project_name}'s DPR could not be sent.`)
    } finally {
      setBusyProject(null)
    }
  }

  const dateLabel = new Date(`${date}T00:00:00`).toLocaleDateString([], {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })
  const cutoffs = [...new Set(projects.map((p) => p.reporting_cutoff_time).filter(Boolean))]
  const cutoffLabel = cutoffs.length === 1 ? ` · Cutoff ${formatClock(cutoffs[0])}` : ''

  return (
    <div className="flex flex-col gap-7 w-full max-w-6xl mx-auto pb-12">
      <header className="flex flex-col sm:flex-row sm:items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <p className="text-sm text-muted-foreground">
            {dateLabel}
            {cutoffLabel}
          </p>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">Today across your sites</h1>
        </div>
        <Button variant="outline" size="sm" onClick={refresh} className="h-9 gap-1.5 self-start sm:self-auto">
          <RefreshCw className={cn('size-4', daysQuery.isFetching && 'animate-spin')} />
          Refresh
        </Button>
      </header>

      <GettingStartedCard />

      <section aria-label="Summary" className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="rounded-xl border bg-card px-5 py-4 flex flex-col gap-1">
          <span className="text-sm text-muted-foreground">Sites reported</span>
          <span className="text-3xl font-bold">
            {totals.reported} <span className="text-base font-medium text-muted-foreground">of {sites.length}</span>
          </span>
        </div>
        <div className="rounded-xl border bg-card px-5 py-4 flex flex-col gap-1">
          <span className="text-sm text-muted-foreground">Workers on site</span>
          <span className="text-3xl font-bold">{totals.workers}</span>
        </div>
        <div className="rounded-xl border bg-card px-5 py-4 flex flex-col gap-1">
          <span className="text-sm text-muted-foreground">Work items logged</span>
          <span className="text-3xl font-bold">{totals.workItems}</span>
        </div>
        <div className="rounded-xl border bg-card px-5 py-4 flex flex-col gap-1">
          <span className="text-sm text-muted-foreground">Open issues</span>
          <span className={cn('text-3xl font-bold', totals.openIssues > 0 && 'text-draft')}>{totals.openIssues}</span>
        </div>
      </section>

      {daysQuery.isLoading ? (
        <p className="text-sm text-muted-foreground">Loading today's sites…</p>
      ) : daysQuery.isError ? (
        <p className="text-sm text-destructive">Could not load today's sites. Try Refresh.</p>
      ) : projects.length === 0 ? (
        <p className="text-sm text-muted-foreground">No active sites yet. Add a project and its sites to see them here.</p>
      ) : (
        <section aria-label="Projects" className="flex flex-col gap-8">
          {projects.map((project) => {
            const projectSites = sites.filter((s) => s.project_id === project.project_id)
            const confirmed = projectSites.filter((s) => FROZEN.includes(s.status)).length
            const workers = projectSites.reduce((n, s) => n + s.workers, 0)
            const singleSite = projectSites.length === 1
            const canSend = !project.sent && !project.send_requested
            return (
              <div key={project.project_id} className="flex flex-col gap-3">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b pb-2">
                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    <h2 className="text-lg font-bold">{project.project_name}</h2>
                    <span className="text-sm text-muted-foreground">
                      {singleSite
                        ? 'Single-site project · its site DPR is the project DPR'
                        : `${projectSites.length} sites · ${confirmed} of ${projectSites.length} confirmed · ${workers} workers`}
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={cn(CHIP, project.sent ? 'bg-success-soft text-success' : 'bg-muted text-muted-foreground')}>
                      {projectDprLabel(project, projectSites)}
                    </span>
                    {canSend && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-9 gap-1.5 font-semibold"
                        disabled={busyProject === project.project_id}
                        onClick={() => sendNow(project)}
                      >
                        <Send className="size-3.5" />
                        Send now
                      </Button>
                    )}
                  </div>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  {projectSites.map((site) => (
                    <SiteCard
                      key={site.site_id}
                      site={site}
                      singleSite={singleSite}
                      busy={busySite === site.site_id}
                      onNoWork={markNoWork}
                    />
                  ))}
                </div>
              </div>
            )
          })}
        </section>
      )}

      <div className="flex flex-col lg:flex-row gap-4 items-start">
        <section aria-labelledby="attention-h" className="w-full lg:flex-1 rounded-2xl border bg-card p-5 flex flex-col gap-3">
          <h2 id="attention-h" className="text-base font-semibold">Needs your attention</h2>
          {attention.length === 0 ? (
            <p className="text-sm text-muted-foreground">Nothing waiting on you right now.</p>
          ) : (
            attention.map((line) => (
              <div key={line.key} className="flex justify-between gap-3 rounded-lg bg-muted/40 px-3 py-2.5 text-sm">
                <span>{line.text}</span>
                <span className="text-muted-foreground shrink-0">{line.note}</span>
              </div>
            ))
          )}
        </section>

        <section aria-labelledby="issues-h" className="w-full lg:flex-[1.4] rounded-2xl border bg-card p-5 flex flex-col gap-3 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <h2 id="issues-h" className="text-base font-semibold">Open issues</h2>
            <Link to="/operations/issues" className="text-sm font-semibold text-primary hover:underline">
              All issues
            </Link>
          </div>
          {openIssues.length === 0 ? (
            <p className="text-sm text-muted-foreground">No open issues.</p>
          ) : (
            <div className="overflow-x-auto">
              <Table className="min-w-[420px]">
                <TableHeader>
                  <TableRow>
                    <TableHead>Issue</TableHead>
                    <TableHead>Site</TableHead>
                    <TableHead>Severity</TableHead>
                    <TableHead>Open for</TableHead>
                    <TableHead>Time lost</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {openIssues.map((issue) => (
                    <TableRow key={issue.id}>
                      <TableCell className="max-w-[220px] truncate">
                        {issue.narrative || issue.issue_type.toLowerCase().replace(/_/g, ' ')}
                      </TableCell>
                      <TableCell>{siteNames.get(issue.site_id) ?? '—'}</TableCell>
                      <TableCell
                        className={cn(
                          ['CRITICAL', 'HIGH'].includes(issue.severity.toUpperCase()) && 'font-semibold text-draft',
                        )}
                      >
                        {issue.severity.charAt(0) + issue.severity.slice(1).toLowerCase()}
                      </TableCell>
                      <TableCell>{openFor(issue.occurred_at)}</TableCell>
                      <TableCell>{timeLost(issue.delay_duration_minutes)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
