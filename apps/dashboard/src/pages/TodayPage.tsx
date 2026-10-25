import * as React from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Building2, ChevronLeft, ChevronRight, CircleCheck, CircleDashed, CircleDot, Radio, RefreshCw, Send, TriangleAlert } from 'lucide-react'
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
import { FirstReportMoment } from '@/components/first-report-moment'
import { TimeSaved } from '@/components/time-saved'
import { TellMesiri } from '@/components/tell-mesiri/tell-mesiri'
import { useReadOnly } from '@/lib/trial'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Callout, DprAside, DprSection, PageHeader, StatStrip } from '@/components/dpr-page'
import { cn, formatClock } from '@/lib/utils'
import {
  CHIP,
  FROZEN,
  MISSING_LABELS,
  errorDetail,
  hasUpdates,
  localIsoDate,
  longDate,
  missingText,
  plural,
  projectDayPath,
  siteDayPath,
  severityChip,
  siteStatus,
} from '@/lib/site-day'

// Today page (WEB-03): every site's working day, grouped by project, with
// what is missing and where each project's DPR stands. Data comes from
// GET /dpr/site-days (BE-08), live counts included; "no work today" is the
// BE-14 site condition and "Send now" the BE-16 send.

const SEVERITY_RANK: Record<string, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 }

function formatTime(iso: string | null): string | null {
  if (!iso) return null
  return new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
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

function SiteRow({
  site,
  date,
  busy,
  onNoWork,
}: {
  site: SiteDayItem
  date: string
  busy: boolean
  onNoWork: (site: SiteDayItem) => void
}) {
  const status = siteStatus(site)
  const missing = missingText(site)
  const lastAt = formatTime(site.last_update_at)
  const drafts = site.drafts ?? 0
  // Hidden once the free trial has ended: the save would be refused (SS-15).
  const readOnly = useReadOnly()
  const canMarkNoWork =
    !readOnly && !hasUpdates(site) && !FROZEN.includes(site.status) && site.status !== 'in_review'
  const done = FROZEN.includes(site.status)
  const quiet = !hasUpdates(site)

  return (
    <li className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:gap-4">
      <div className="flex min-w-0 flex-1 items-start gap-3">
        <span className="mt-0.5 shrink-0" title={status.label}>
          {done ? (
            <CircleCheck className="size-5 text-success" />
          ) : drafts > 0 || site.status === 'needs_details' ? (
            <CircleDashed className="size-5 text-draft" />
          ) : quiet ? (
            <CircleDashed className="size-5 text-muted-foreground" />
          ) : (
            <CircleDot className="size-5 text-info" />
          )}
        </span>
        <div className="flex min-w-0 flex-col gap-0.5">
          <div className="flex flex-wrap items-center gap-2">
            <Link to={siteDayPath(site.site_id, date)} className="font-medium hover:underline">
              {site.site_name}
            </Link>
            <span className={cn(CHIP, status.className)}>{status.label}</span>
          </div>
          <p className="text-xs text-muted-foreground">
            {[
              site.workers ? plural(site.workers, 'worker') : null,
              site.work_items ? plural(site.work_items, 'work item') : null,
              site.progress_updates ? plural(site.progress_updates, 'progress update') : null,
              site.materials ? plural(site.materials, 'material entry', 'material entries') : null,
              site.photos ? plural(site.photos, 'photo') : null,
              site.open_issues ? plural(site.open_issues, 'open issue') : null,
            ]
              .filter(Boolean)
              .join(' · ') || 'Nothing received yet'}
            {lastAt && ` · last ${lastAt}${site.last_update_by ? ` by ${site.last_update_by}` : ''}`}
          </p>
          {site.site_working === 'none' ? (
            <p className="text-xs text-muted-foreground">Marked as no work today.</p>
          ) : drafts > 0 ? (
            <p className="text-xs font-semibold text-draft">{plural(drafts, 'item')} still to confirm</p>
          ) : missing && !done ? (
            // Orange only when something the report needs is missing; optional gaps stay quiet.
            <p className={cn('text-xs', site.missing_sections?.blocking.length ? 'text-draft' : 'text-muted-foreground')}>{missing}</p>
          ) : site.latest_update ? (
            <p className="line-clamp-1 text-xs text-foreground/70">“{site.latest_update}”</p>
          ) : null}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2 pl-8 sm:pl-0">
        {canMarkNoWork && (
          <Button variant="ghost" size="sm" className="text-muted-foreground" disabled={busy} onClick={() => onNoWork(site)}>
            No work today
          </Button>
        )}
        <Button asChild size="sm" variant={drafts > 0 ? 'default' : 'outline'} className="min-w-[96px]">
          <Link to={siteDayPath(site.site_id, date)}>
            {drafts > 0 ? 'Review' : 'Open'} <ChevronRight />
          </Link>
        </Button>
      </div>
    </li>
  )
}

// DSH-10: every open issue, not just the latest 100 of all statuses: the server
// filters by status, and each status is read page by page (the API caps a page
// at 100) so the most severe ones are ranked from the whole list.
const ISSUE_PAGE = 100
async function fetchAllOpenIssues(projectId: string | undefined): Promise<SiteIssueItem[]> {
  const all: SiteIssueItem[] = []
  for (const status of ['OPEN', 'ACKNOWLEDGED']) {
    for (let offset = 0; ; offset += ISSUE_PAGE) {
      const page = await fetchSiteIssuesApi({ projectId, status, limit: ISSUE_PAGE, offset })
      all.push(...page.items)
      if (page.items.length < ISSUE_PAGE || offset + ISSUE_PAGE >= page.total) break
    }
  }
  return all
}

export default function TodayPage() {
  const toast = useToast()
  const queryClient = useQueryClient()
  const { scope } = useScope()
  const [searchParams, setSearchParams] = useSearchParams()
  // Read the clock once (a lazy initial state), not on every render.
  const [today] = React.useState(() => localIsoDate(new Date()))
  const date = searchParams.get('date') || today
  const projectFilter = scope.mode === 'portfolio' ? undefined : scope.projectId
  const [busySite, setBusySite] = React.useState<string | null>(null)
  const [busyProject, setBusyProject] = React.useState<string | null>(null)
  const readOnly = useReadOnly()

  const daysQuery = useQuery({
    queryKey: ['site-days', date, projectFilter],
    queryFn: () => fetchSiteDaysApi(date, projectFilter),
    refetchInterval: 60_000,
  })
  const issuesQuery = useQuery({
    queryKey: ['today-open-issues', projectFilter],
    queryFn: () => fetchAllOpenIssues(projectFilter),
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
    const items: SiteIssueItem[] = issuesQuery.data ?? []
    return items
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

  const isToday = date === today
  const shiftDay = (delta: number) => {
    const d = new Date(`${date}T00:00:00`)
    d.setDate(d.getDate() + delta)
    const next = localIsoDate(d)
    setSearchParams(
      (prev) => {
        if (next === today) prev.delete('date')
        else prev.set('date', next)
        return prev
      },
      { replace: true },
    )
  }
  const cutoffs = [...new Set(projects.map((p) => p.reporting_cutoff_time).filter(Boolean))]
  const cutoffLabel = cutoffs.length === 1 ? ` · Cutoff ${formatClock(cutoffs[0])}` : ''

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 pb-8 sm:px-2">
      <PageHeader
        title={isToday ? 'Today' : longDate(date)}
        subtitle={
          <>
            {isToday ? longDate(date) : 'A past day'}
            {cutoffLabel}
          </>
        }
        actions={
          <>
            {isToday && projects.length > 0 && (
              <Button asChild variant="outline" size="sm" className="h-8 gap-1.5">
                <Link to="/live" title="Watch today's report write itself as updates come in">
                  <Radio className="size-4 text-primary" /> Live
                </Link>
              </Button>
            )}
            <div className="flex items-center rounded-lg border">
              <Button variant="ghost" size="icon" className="size-8" onClick={() => shiftDay(-1)} title="Previous day" aria-label="Previous day">
                <ChevronLeft className="size-4" />
              </Button>
              {!isToday && (
                <Button variant="ghost" size="sm" className="h-8 px-2" onClick={() => shiftDay(Math.round((new Date(`${today}T00:00:00`).getTime() - new Date(`${date}T00:00:00`).getTime()) / 86_400_000))}>
                  Today
                </Button>
              )}
              <Button variant="ghost" size="icon" className="size-8" onClick={() => shiftDay(1)} disabled={isToday} title="Next day" aria-label="Next day">
                <ChevronRight className="size-4" />
              </Button>
            </div>
            <Button variant="ghost" size="icon" className="size-8" onClick={refresh} disabled={daysQuery.isFetching} title="Refresh" aria-label="Refresh">
              <RefreshCw className={cn('size-4', daysQuery.isFetching && 'animate-spin')} />
            </Button>
          </>
        }
      />

      {isToday && <TimeSaved />}
      {isToday && <FirstReportMoment />}
      {isToday && <GettingStartedCard />}
      {isToday && <TellMesiri className="rounded-xl border px-4 py-3" />}

      {daysQuery.isError ? (
        <Callout tone="draft" icon={TriangleAlert} action={<Button variant="outline" size="sm" className="bg-background" onClick={refresh}>Try again</Button>}>
          Today's sites could not be loaded.
        </Callout>
      ) : daysQuery.isLoading ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-16 rounded-xl" />
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-14 rounded-lg" />
          ))}
        </div>
      ) : projects.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center">
          <p className="text-sm font-medium">No active sites yet</p>
          <p className="text-sm text-muted-foreground">Add a project and its sites, and each day's updates show here.</p>
          <Button asChild variant="outline" size="sm">
            <Link to="/projects">Projects & Sites</Link>
          </Button>
        </div>
      ) : (
        <>
          {attention.length > 0 && (
            <Callout tone="draft" icon={TriangleAlert}>
              <p className="font-semibold">Needs your attention</p>
              <ul className="mt-1 flex flex-col gap-0.5">
                {attention.map((line) => (
                  <li key={line.key}>
                    {line.text}
                    {line.note && <span className="opacity-75"> · {line.note}</span>}
                  </li>
                ))}
              </ul>
            </Callout>
          )}

          <StatStrip
            stats={[
              {
                label: 'Reported',
                value: (
                  <>
                    {totals.reported}
                    <span className="text-sm font-normal text-muted-foreground"> of {sites.length}</span>
                  </>
                ),
                tone: totals.reported < sites.length ? 'warn' : 'default',
              },
              { label: 'Workers', value: totals.workers || '—' },
              { label: 'Work items', value: totals.workItems || '—' },
              { label: 'Open issues', value: totals.openIssues || '—', tone: totals.openIssues > 0 ? 'warn' : 'default' },
            ]}
          />

          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
            <div className="flex min-w-0 flex-col">
              {projects.map((project) => {
                const projectSites = sites.filter((s) => s.project_id === project.project_id)
                const confirmed = projectSites.filter((s) => FROZEN.includes(s.status)).length
                const singleSite = projectSites.length === 1
                const canSend = !project.sent && !project.send_requested && !readOnly
                return (
                  <DprSection
                    key={project.project_id}
                    icon={Building2}
                    title={project.project_name}
                    meta={singleSite ? '1 site' : `${confirmed} of ${projectSites.length} sites confirmed`}
                    action={
                      <div className="flex items-center gap-2">
                        <span className={cn(CHIP, 'hidden sm:inline-flex', project.sent ? 'bg-success-soft text-success' : 'bg-muted text-muted-foreground')}>
                          {projectDprLabel(project, projectSites)}
                        </span>
                        <Button asChild variant="ghost" size="sm" className="gap-1 text-primary">
                          <Link to={projectDayPath(project.project_id, date)}>
                            Project DPR <ChevronRight />
                          </Link>
                        </Button>
                        {canSend && (
                          <Button variant="outline" size="sm" className="gap-1.5" disabled={busyProject === project.project_id} onClick={() => sendNow(project)}>
                            <Send className="size-3.5" /> Send now
                          </Button>
                        )}
                      </div>
                    }
                  >
                    <ul className="flex flex-col divide-y">
                      {projectSites.map((site) => (
                        <SiteRow
                          key={site.site_id}
                          site={site}
                          date={date}
                          busy={busySite === site.site_id}
                          onNoWork={markNoWork}
                        />
                      ))}
                    </ul>
                  </DprSection>
                )
              })}
            </div>

            <DprAside>
              <div className="flex flex-col gap-3">
                <div className="flex items-center justify-between gap-2">
                  <h2 className="text-sm font-semibold">Open issues</h2>
                  <Link to="/issues" className="inline-flex items-center gap-0.5 text-xs font-medium text-primary hover:underline">
                    All issues <ChevronRight className="size-3.5" />
                  </Link>
                </div>
                {issuesQuery.isError ? (
                  <p className="text-sm text-muted-foreground">
                    Could not load issues.{' '}
                    <button type="button" className="font-medium text-primary hover:underline" onClick={() => issuesQuery.refetch()}>
                      Try again
                    </button>
                  </p>
                ) : openIssues.length === 0 ? (
                  <p className="text-sm text-muted-foreground">{issuesQuery.isLoading ? 'Loading…' : 'No open issues.'}</p>
                ) : (
                  <ul className="flex flex-col divide-y">
                    {openIssues.map((issue) => {
                      const sev = severityChip(issue.severity)
                      return (
                        <li key={issue.id} className="flex items-start justify-between gap-3 py-2">
                          <div className="flex min-w-0 flex-col">
                            <span className="line-clamp-2 text-sm">
                              {issue.narrative || issue.issue_type.toLowerCase().replace(/_/g, ' ')}
                            </span>
                            <span className="text-xs text-muted-foreground">
                              {siteNames.get(issue.site_id) ?? '—'} · open {openFor(issue.occurred_at).toLowerCase()}
                              {issue.delay_duration_minutes ? ` · ${timeLost(issue.delay_duration_minutes)} lost` : ''}
                            </span>
                          </div>
                          {sev && <span className={cn(CHIP, 'shrink-0', sev.className)}>{sev.label}</span>}
                        </li>
                      )
                    })}
                  </ul>
                )}
              </div>
            </DprAside>
          </div>
        </>
      )}
    </div>
  )
}
