import * as React from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchAllOpenIssues } from '@/lib/issues'
import { AlertTriangle, Building2, Camera, ChevronRight, CircleCheck, CircleDashed, CircleDot, Hammer, Package, TriangleAlert, Users } from 'lucide-react'
import { useScope } from '@/lib/ScopeContext'
import {
  fetchSiteDaysApi,
  sendProjectDprNowApi,
  setSiteDayConditionsApi,
  type ProjectDayItem,
  type SiteDayItem,
  type SiteIssueItem,
} from '@/lib/api'
import { useToast } from '@/components/ui/toast-notification'
import { FirstReportMoment } from '@/components/first-report-moment'
import { RecordDayButton } from '@/components/site-day-form'
import { useReadOnly } from '@/lib/trial'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Callout } from '@/components/dpr-page'
import { TodayHero } from '@/components/home/today-hero'
import { cn, formatClock } from '@/lib/utils'
import { ActionButton, EmptyState } from '@/components/page/page-kit'
import { useAuth } from '@/lib/AuthContext'
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
import { appNow } from '@/lib/clock'

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

// An open issue turns amber after a day and red after three (WEB-37).
function issueAgeClass(occurredAt: string): string {
  const days = (Date.now() - new Date(occurredAt).getTime()) / 86_400_000
  return days >= 3 ? 'font-medium text-destructive' : days >= 1 ? 'font-medium text-draft' : ''
}

const SITE_LOOK = {
  done: { bar: 'bg-success', icon: CircleCheck, iconClass: 'text-success' },
  draft: { bar: 'bg-draft', icon: CircleDashed, iconClass: 'text-draft' },
  live: { bar: 'bg-info', icon: CircleDot, iconClass: 'text-info' },
  quiet: { bar: 'bg-border', icon: CircleDashed, iconClass: 'text-muted-foreground' },
} as const

/** UX-66: one site's day as a card: its state as a coloured edge and chip, its figures with icons, the last thing it
 *  sent as a quote, and the one thing to do (Review, or No work today). The whole card opens the site's day. */
function SiteCard({
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
  const look = done ? SITE_LOOK.done : drafts > 0 || site.status === 'needs_details' ? SITE_LOOK.draft : quiet ? SITE_LOOK.quiet : SITE_LOOK.live
  const figures = [
    { icon: Users, n: site.workers, label: 'workers' },
    { icon: Hammer, n: site.work_items + site.progress_updates, label: 'work' },
    { icon: Package, n: site.materials, label: 'material' },
    { icon: Camera, n: site.photos, label: 'photos' },
  ]
  // UX-75: one row per site (a status list scans faster than a grid of cards when there are many sites): its state,
  // who sent the last update and when, the day's figures inline (zeros faded), the latest words, and its action.
  const line =
    site.site_working === 'none' ? (
      <span className="text-muted-foreground">Marked as no work today</span>
    ) : drafts > 0 ? (
      <span className="font-semibold text-draft">{plural(drafts, 'item')} still to confirm</span>
    ) : missing && !done ? (
      <span className={cn(site.missing_sections?.blocking.length ? 'text-draft' : 'text-muted-foreground')}>{missing}</span>
    ) : site.latest_update ? (
      <span className="text-foreground/75 italic">“{site.latest_update}”</span>
    ) : site.open_issues ? (
      <span className="text-destructive">{plural(site.open_issues, 'open issue')}</span>
    ) : quiet ? (
      <span className="text-muted-foreground">Waiting for the first update</span>
    ) : (
      <span className="text-muted-foreground">{done ? 'Day confirmed' : 'Updates coming in'}</span>
    )
  return (
    <li className="group relative flex flex-col gap-2 py-3 pr-3 pl-4 transition-colors hover:bg-muted/30 sm:flex-row sm:items-center sm:gap-4" data-record-id={site.site_id}>
      <span aria-hidden className={cn('absolute inset-y-2 left-0 w-1 rounded-r', look.bar)} />
      <div className="flex min-w-0 flex-1 items-start gap-2.5">
        <look.icon className={cn('mt-0.5 size-4.5 shrink-0', look.iconClass)} aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <Link to={siteDayPath(site.site_id, date)} className="truncate text-[15px] font-semibold after:absolute after:inset-0 hover:underline">
              {site.site_name}
            </Link>
            <span className={cn(CHIP, 'shrink-0', status.className)}>{status.label}</span>
            <span className="text-xs text-muted-foreground">
              {lastAt ? `${lastAt}${site.last_update_by ? ` · ${site.last_update_by}` : ''}` : 'Nothing yet'}
            </span>
          </div>
          <p className="mt-0.5 line-clamp-1 text-xs">{line}</p>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-3 pl-7 sm:pl-0">
        <div className="flex items-center gap-3 text-xs">
          {figures.map((f) => (
            <span key={f.label} className={cn('inline-flex items-center gap-1 tabular-nums', f.n ? 'text-foreground' : 'text-muted-foreground/45')} title={`${f.n} ${f.label}`}>
              <f.icon className="size-3.5" aria-hidden />
              <span className="font-semibold">{f.n || '–'}</span>
              <span className="hidden text-muted-foreground lg:inline">{f.label}</span>
            </span>
          ))}
        </div>
        <div className="relative z-10 flex items-center gap-1.5 empty:hidden">
          {canMarkNoWork && (
            <Button variant="ghost" size="sm" className="h-7 px-2 text-xs text-muted-foreground" disabled={busy} onClick={() => onNoWork(site)}>
              No work today
            </Button>
          )}
          {drafts > 0 ? (
            <Button asChild size="sm" className="h-7">
              <Link to={siteDayPath(site.site_id, date)}>
                Review <ChevronRight />
              </Link>
            </Button>
          ) : (
            <ChevronRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
          )}
        </div>
      </div>
    </li>
  )
}

export default function TodayPage() {
  const toast = useToast()
  const queryClient = useQueryClient()
  const { scope } = useScope()
  const [searchParams, setSearchParams] = useSearchParams()
  // Read the clock once (a lazy initial state), not on every render.
  const [today] = React.useState(() => localIsoDate(appNow()))
  const date = searchParams.get('date') || today
  const projectFilter = scope.mode === 'portfolio' ? undefined : scope.projectId
  const [busySite, setBusySite] = React.useState<string | null>(null)
  const [busyProject, setBusyProject] = React.useState<string | null>(null)
  const { me } = useAuth()
  const isAdmin = (me?.role || '').toUpperCase() === 'ADMIN'
  // Finance works from the books, not sites: no "you have no sites" box for them (UX-11).
  const isFinance = (me?.role || '').toUpperCase() === 'FINANCE'
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

  // SCP-03: with a site picked, that site's card and figures only (the request is per project).
  const pickedSite = scope.mode === 'site' ? scope.siteId : null
  const sites = React.useMemo(
    () => (daysQuery.data?.items ?? []).filter((s) => !pickedSite || s.site_id === pickedSite),
    [daysQuery.data, pickedSite],
  )
  const projects = React.useMemo(() => daysQuery.data?.projects ?? [], [daysQuery.data])
  const siteNames = React.useMemo(() => new Map(sites.map((s) => [s.site_id, s.site_name])), [sites])

  const totals = React.useMemo(
    () => ({
      reported: sites.filter(hasUpdates).length,
      workers: sites.reduce((n, s) => n + s.workers, 0),
      workItems: sites.reduce((n, s) => n + s.work_items, 0),
      openIssues: sites.reduce((n, s) => n + s.open_issues, 0),
      photos: sites.reduce((n, s) => n + s.photos, 0),
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

  const scopeLabel = scope.mode === 'site' ? scope.siteName : scope.mode === 'project' ? scope.projectName : projects.length > 1 ? 'All projects' : null
  const daysBack = Math.round((new Date(`${today}T00:00:00`).getTime() - new Date(`${date}T00:00:00`).getTime()) / 86_400_000)

  return (
    <div className="mx-auto flex w-full flex-col gap-5 pb-8 sm:px-2">
      <TodayHero
        isToday={isToday}
        dateLabel={longDate(date)}
        scopeLabel={scopeLabel}
        reported={totals.reported}
        sites={sites.length}
        figures={[
          { label: 'Workers', value: totals.workers, icon: Users },
          { label: 'Work done', value: totals.workItems, icon: Hammer },
          { label: 'Photos', value: totals.photos, icon: Camera },
          { label: 'Open issues', value: totals.openIssues, icon: AlertTriangle, bad: true },
        ]}
        cutoff={cutoffs.length === 1 ? cutoffs[0] : null}
        lines={attention.map((l) => ({ key: l.key, text: l.text, note: l.note }))}
        onDay={shiftDay}
        onToday={() => shiftDay(daysBack)}
        onRefresh={refresh}
        refreshing={daysQuery.isFetching}
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px] xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="flex min-w-0 flex-col gap-5">
          {isToday && <FirstReportMoment />}
      {daysQuery.isError ? (
        <Callout tone="draft" icon={TriangleAlert} action={<Button variant="outline" size="sm" className="bg-background" onClick={refresh}>Try again</Button>}>
          Today's sites could not be loaded.
        </Callout>
      ) : daysQuery.isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-40 rounded-xl" />
          ))}
        </div>
      ) : projects.length === 0 ? (
        // UX-06/07: an empty company is the next step, not a dead end.
        isAdmin ? (
          <EmptyState
            icon={Building2}
            title="Start your first project"
            about="Sites, BOQ and who reports"
            action={
              <Button asChild size="sm">
                <Link to="/planning/setup">Start a project</Link>
              </Button>
            }
          />
        ) : isFinance ? null : (
          <EmptyState
            icon={Building2}
            title="No sites for you yet"
            about="Your company admin adds you to a site."
          />
        )
      ) : (
          <div className="flex min-w-0 flex-col gap-5" data-guide="today.sites">
            {/* UX-104: the site's day on a form, beside WhatsApp and Tell Mesiri. */}
            {!readOnly && !isFinance && (
              <div className="flex justify-end">
                <RecordDayButton
                  date={date}
                  sites={sites.map((s) => ({ site_id: s.site_id, site_name: s.site_name, project_id: s.project_id, project_name: projects.find((p) => p.project_id === s.project_id)?.project_name }))}
                />
              </div>
            )}
            {projects.map((project) => {
              const projectSites = sites.filter((s) => s.project_id === project.project_id)
              const confirmed = projectSites.filter((s) => FROZEN.includes(s.status)).length
              const canSend = !project.sent && !project.send_requested && !readOnly
              return (
                <section key={project.project_id} aria-label={project.project_name} className="flex flex-col gap-3">
                  <header className="flex flex-wrap items-center gap-x-3 gap-y-2">
                    <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary-ink" aria-hidden>
                      <Building2 className="size-4" />
                    </span>
                    <div className="min-w-0">
                      <h2 className="truncate text-[15px] font-semibold">{project.project_name}</h2>
                      <p className="text-xs text-muted-foreground">
                        {projectSites.length === 1 ? '1 site' : `${confirmed} of ${projectSites.length} sites confirmed`}
                        {project.dpr_send_deadline && !project.sent ? ` · report goes at ${formatClock(project.dpr_send_deadline)}` : ''}
                      </p>
                    </div>
                    <div className="ml-auto flex items-center gap-2">
                      <span className={cn(CHIP, 'hidden sm:inline-flex', project.sent ? 'bg-success-soft text-success' : 'bg-muted text-muted-foreground')}>
                        {projectDprLabel(project, projectSites)}
                      </span>
                      <Button asChild variant="ghost" size="sm" className="gap-1 text-primary-ink">
                        <Link to={projectDayPath(project.project_id, date)}>
                          Project DPR <ChevronRight />
                        </Link>
                      </Button>
                      {canSend && (
                        <ActionButton kind="whatsapp" disabled={busyProject === project.project_id} onClick={() => sendNow(project)} data-guide="today.send">
                          Send now
                        </ActionButton>
                      )}
                    </div>
                  </header>
                  <ul className="divide-y overflow-hidden rounded-xl border bg-card shadow-xs">
                    {projectSites.map((site) => (
                      <SiteCard key={site.site_id} site={site} date={date} busy={busySite === site.site_id} onNoWork={markNoWork} />
                    ))}
                  </ul>
                </section>
              )
            })}
          </div>
      )}
        </div>

          <aside className="flex min-w-0 flex-col gap-5">
            <div data-guide="today.issues">
            <section className="overflow-hidden rounded-xl border bg-card shadow-xs" aria-label="Open issues">
              <header className="flex items-center gap-2.5 border-b px-4 py-3">
                <span className={cn('flex size-8 items-center justify-center rounded-lg', openIssues.length ? 'bg-destructive/10 text-destructive' : 'bg-success-soft text-success')} aria-hidden>
                  {openIssues.length ? <AlertTriangle className="size-4" /> : <CircleCheck className="size-4" />}
                </span>
                <div className="min-w-0 flex-1">
                  <h2 className="text-sm font-semibold">Open issues</h2>
                  <p className="text-xs text-muted-foreground">
                    {issuesQuery.isLoading ? 'Loading…' : issuesQuery.isError ? 'Could not load' : openIssues.length ? 'Worst first' : 'Nothing stuck'}
                  </p>
                </div>
                <Link to="/issues" className="inline-flex items-center gap-0.5 text-xs font-medium text-primary-ink hover:underline">
                  All <ChevronRight className="size-3.5" />
                </Link>
              </header>
              {issuesQuery.isError ? (
                <p className="px-4 py-3 text-sm text-muted-foreground">
                  <button type="button" className="font-medium text-primary-ink hover:underline" onClick={() => issuesQuery.refetch()}>
                    Try again
                  </button>
                </p>
              ) : openIssues.length === 0 ? null : (
                <ul className="flex flex-col divide-y">
                  {openIssues.map((issue) => {
                    const sev = severityChip(issue.severity)
                    const level = issue.severity.toUpperCase()
                    return (
                      <li key={issue.id}>
                        <Link to={`/issues?id=${issue.id}`} className="flex items-start gap-3 px-4 py-2.5 transition-colors hover:bg-muted/40">
                          <span
                            aria-hidden
                            className={cn('mt-1.5 size-2 shrink-0 rounded-full', level === 'CRITICAL' ? 'bg-destructive ring-4 ring-destructive/15' : level === 'HIGH' ? 'bg-draft' : 'bg-muted-foreground/40')}
                          />
                          <span className="flex min-w-0 flex-1 flex-col">
                            <span className="line-clamp-2 text-sm">{issue.narrative || issue.issue_type.toLowerCase().replace(/_/g, ' ')}</span>
                            <span className="text-xs text-muted-foreground">
                              {siteNames.get(issue.site_id) ?? '—'} · <span className={issueAgeClass(issue.occurred_at)}>open {openFor(issue.occurred_at).toLowerCase()}</span>
                              {issue.delay_duration_minutes ? ` · ${timeLost(issue.delay_duration_minutes)} lost` : ''}
                            </span>
                          </span>
                          {sev && <span className={cn(CHIP, 'shrink-0', sev.className)}>{sev.label}</span>}
                        </Link>
                      </li>
                    )
                  })}
                </ul>
              )}
            </section>
            </div>
          </aside>
      </div>
    </div>
  )
}
