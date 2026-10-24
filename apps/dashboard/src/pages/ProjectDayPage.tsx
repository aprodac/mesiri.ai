import * as React from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronRight, CircleCheck, CircleDashed, Eye, MapPin, Package, Send, TriangleAlert } from 'lucide-react'
import {
  fetchDailyReportPdfApi,
  fetchProjectDayDocumentApi,
  fetchProjectDayApi,
  sendProjectDprNowApi,
  type DprVersion,
  type ProjectDayDetail,
  type ProjectReportSite,
  type SiteDayItem,
} from '@/lib/api'
import {
  CHIP,
  FROZEN,
  errorDetail,
  localIsoDate,
  hasUpdates,
  longDate,
  missingText,
  plural,
  qty,
  severityChip,
  siteDayPath,
  siteStatus,
} from '@/lib/site-day'
import { useReadOnly } from '@/lib/trial'
import { usePageTitle } from '@/lib/page-title'
import { cn, formatClock } from '@/lib/utils'
import { useToast } from '@/components/ui/toast-notification'
import { DprSummaryCard } from '@/components/dpr-summary-card'
import { DprVersionsCard } from '@/components/dpr-versions-card'
import { Button } from '@/components/ui/button'
import { DprDocument, DprViewToggle, LIVE_REFRESH_MS, type DprView } from '@/components/dpr-document'
import { useUrlState } from '@/lib/url-state'
import { Callout, DprAside, DprHeader, DprPageSkeleton, DprSection, DprSteps, PageError, StatStrip, type StepState } from '@/components/dpr-page'

// Project DPR page (WEB-05): one project's day. Every site's day as it stands
// (opened from here to review and confirm), and the project DPR -- the
// roll-up of the confirmed site DPRs (BE-16, P8) -- as it would go out now or,
// once sent, as it went out. Reads GET /dpr/projects/{id}/day; "Send now" is
// the BE-16 send, the PDF the existing /dpr/daily-reports/{id}/pdf.

function money(value: string | null | undefined): string {
  const n = Number(value ?? 0)
  return n > 0 ? `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—'
}

function dprState(detail: ProjectDayDetail): { label: string; className: string; note: string } {
  const { project, sites } = detail
  const deadline = project.dpr_send_deadline ? ` at ${formatClock(project.dpr_send_deadline)}` : ''
  if (project.sent) {
    return { label: 'DPR sent', className: 'bg-success-soft text-success', note: 'This is the DPR as it was sent.' }
  }
  if (project.send_requested) {
    return { label: 'Sending…', className: 'bg-info-soft text-info', note: 'The DPR goes out within a minute.' }
  }
  const waiting = sites.filter((s) => !FROZEN.includes(s.status))
  if (waiting.length === 0) {
    return {
      label: 'All sites confirmed',
      className: 'bg-success-soft text-success',
      note: 'Everything is confirmed. The DPR goes out shortly.',
    }
  }
  return {
    label: waiting.length === 1 ? `Waiting for ${waiting[0].site_name}` : `Waiting for ${waiting.length} sites`,
    className: 'bg-muted text-muted-foreground',
    note: `Preview of the DPR as it would go out now. It sends when every site is confirmed, or${deadline || ' at the deadline'}; a site not confirmed by then shows as "Not reported".`,
  }
}

function SiteRow({
  site,
  date,
  line,
  sent,
}: {
  site: SiteDayItem
  date: string
  line: ProjectReportSite | undefined
  sent: boolean
}) {
  const status = siteStatus(site)
  const missing = missingText(site)
  const drafts = site.drafts ?? 0
  const inReport = Boolean(line?.reported)
  return (
    <li className="grid grid-cols-[auto_1fr_auto] items-center gap-x-3 gap-y-1 py-2.5 md:grid-cols-[auto_minmax(0,1.6fr)_repeat(4,minmax(0,0.6fr))_auto]">
      <span title={inReport ? 'In the DPR' : sent ? 'Not in the sent DPR' : 'Not in the DPR yet'}>
        {inReport ? <CircleCheck className="size-5 text-success" /> : <CircleDashed className="size-5 text-muted-foreground" />}
      </span>
      <div className="flex min-w-0 flex-col gap-0.5">
        <div className="flex flex-wrap items-center gap-2">
          <Link to={siteDayPath(site.site_id, date)} className="font-medium hover:underline">
            {site.site_name}
          </Link>
          <span className={cn(CHIP, status.className)}>{status.label}</span>
        </div>
        {site.site_working === 'none' ? (
          <span className="text-xs text-muted-foreground">Marked as no work today.</span>
        ) : drafts > 0 ? (
          <span className="text-xs font-semibold text-draft">{plural(drafts, 'item')} still to confirm</span>
        ) : missing && !FROZEN.includes(site.status) ? (
          <span className="text-xs text-muted-foreground">{missing}</span>
        ) : (
          <span className="text-xs text-muted-foreground">
            {inReport ? 'In the DPR' : sent ? 'Not in the sent DPR' : 'Not in the DPR yet'}
          </span>
        )}
        {/* Phone: the numbers sit under the name instead of in columns. */}
        <span className="text-xs text-muted-foreground md:hidden">
          {plural(site.workers, 'worker')} · {plural(site.work_items, 'work item')}
          {site.open_issues > 0 && ` · ${plural(site.open_issues, 'open issue')}`}
        </span>
      </div>
      <Num value={site.workers} />
      <Num value={site.work_items} />
      <Num value={site.photos} />
      <Num value={site.open_issues} tone={site.open_issues > 0 ? 'warn' : undefined} />
      <Button asChild variant={drafts > 0 ? 'default' : 'outline'} size="sm" className="shrink-0 md:w-[88px]">
        <Link to={siteDayPath(site.site_id, date)}>
          {drafts > 0 ? 'Review' : 'Open'} <ChevronRight />
        </Link>
      </Button>
    </li>
  )
}

function Num({ value, tone }: { value: number; tone?: 'warn' }) {
  return (
    <span className={cn('hidden text-right text-sm tabular-nums md:block', !value && 'text-muted-foreground', tone === 'warn' && 'font-semibold text-draft')}>
      {value || '—'}
    </span>
  )
}

export default function ProjectDayPage() {
  const { projectId = '', date = '' } = useParams()
  const toast = useToast()
  const queryClient = useQueryClient()
  const readOnly = useReadOnly()
  const [busy, setBusy] = React.useState(false)
  const [view, setView] = useUrlState<DprView>('view', 'review')

  const query = useQuery({
    queryKey: ['project-day', projectId, date],
    queryFn: () => fetchProjectDayApi(projectId, date),
    enabled: Boolean(projectId && date),
    refetchInterval: LIVE_REFRESH_MS,
  })
  const detail = query.data
  usePageTitle(`${detail?.project.project_name ?? 'Project'} · Project DPR`)

  if (query.isLoading) return <DprPageSkeleton />
  if (query.isError || !detail) {
    return (
      <PageError
        message="This project's day could not be loaded."
        onRetry={() => query.refetch()}
        back={date === localIsoDate(new Date()) ? { to: '/today', label: 'Back to Today' } : { to: '/reports', label: 'Back to Reports' }}
      />
    )
  }

  const { project, report, sites } = detail
  const singleSite = sites.length === 1
  const state = dprState(detail)
  const reportId = project.project_report_id
  const canSend = !readOnly && !project.sent && !project.send_requested

  const sendNow = async () => {
    setBusy(true)
    try {
      await sendProjectDprNowApi(project.project_id)
      toast.success('Sending the DPR', `${project.project_name}'s DPR goes out within a minute.`)
      queryClient.invalidateQueries({ queryKey: ['project-day', projectId, date] })
      queryClient.invalidateQueries({ queryKey: ['project-day-document', projectId, date] })
      queryClient.invalidateQueries({ queryKey: ['site-days'] })
    } catch (err) {
      toast.error('Could not send', errorDetail(err) ?? `${project.project_name}'s DPR could not be sent.`)
    } finally {
      setBusy(false)
    }
  }

  const openPdf = async (version: DprVersion) => {
    if (!reportId) return
    try {
      const blob = await fetchDailyReportPdfApi(reportId, version.is_current ? undefined : version.id)
      window.open(URL.createObjectURL(blob), '_blank', 'noopener')
    } catch (err) {
      toast.error('Could not open the PDF', errorDetail(err) ?? 'Please try again.')
    }
  }

  const sentVersion = detail.versions.find((v) => v.is_current)
  const confirmedCount = sites.filter((s) => FROZEN.includes(s.status)).length
  const anyUpdates = sites.some(hasUpdates)
  const steps: { label: string; short?: string; hint?: string; state: StepState }[] = [
    {
      label: 'Updates from sites',
      short: 'Updates',
      hint: `${sites.filter(hasUpdates).length} of ${plural(sites.length, 'site')}`,
      state: anyUpdates ? 'done' : 'current',
    },
    {
      label: 'Engineers confirm',
      short: 'Confirm',
      hint: `${confirmedCount} of ${sites.length} confirmed`,
      state: confirmedCount === sites.length && sites.length > 0 ? 'done' : anyUpdates ? 'current' : 'todo',
    },
    {
      label: 'DPR sent',
      short: 'Sent',
      hint: project.sent
        ? 'Sent'
        : project.send_requested
          ? 'Sending…'
          : project.dpr_send_deadline
            ? `By ${formatClock(project.dpr_send_deadline)}`
            : undefined,
      state: project.sent ? 'done' : confirmedCount === sites.length || project.send_requested ? 'current' : 'todo',
    },
  ]
  const lineFor = (site: SiteDayItem) => report.sites.find((s) => s.site_name === site.site_name)
  const severe = report.issues.filter((i) => ['CRITICAL', 'HIGH'].includes((i.severity ?? '').toUpperCase())).length

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 pb-4 sm:px-2">
      <div className="flex flex-col gap-3">
        <DprHeader
          back={date === localIsoDate(new Date()) ? { to: '/today', label: 'Today' } : { to: '/reports', label: 'Reports' }}
          crumb="Project DPR"
          title={project.project_name}
          chip={<span className={cn(CHIP, state.className)}>{state.label}</span>}
          date={longDate(date)}
          action={
            <div className="flex flex-wrap items-center gap-2">
              <DprViewToggle value={view} onChange={setView} />
              {canSend && (
                <Button className="h-10 px-4 font-semibold" disabled={busy} onClick={sendNow}>
                  <Send /> Send now
                </Button>
              )}
            </div>
          }
        />
        <DprSteps steps={steps} />
      </div>

      {view === 'document' ? (
        <DprDocument
          queryKey={['project-day-document', projectId, date]}
          fetchHtml={() => fetchProjectDayDocumentApi(projectId, date)}
          live={detail.report_source !== 'sent'}
          title={`${project.project_name} daily progress report`}
          onDownload={sentVersion ? () => openPdf(sentVersion) : undefined}
        />
      ) : (
        <>
          <Callout
            tone={detail.report_source === 'sent' ? 'success' : project.send_requested ? 'info' : 'muted'}
            icon={detail.report_source === 'sent' ? CircleCheck : Eye}
            action={
              singleSite ? (
                <Button asChild variant="outline" size="sm" className="bg-background">
                  <Link to={siteDayPath(sites[0].site_id, date)}>Open the site DPR</Link>
                </Button>
              ) : undefined
            }
          >
            {/* Phone: the first sentence only; the steps above carry the rest. */}
            <span className="sm:hidden">{state.note.split('. ')[0].replace(/\.$/, '')}.</span>
            <span className="hidden sm:inline">
              {state.note}
              {singleSite && ' Single-site project: its site DPR is what gets sent.'}
            </span>
          </Callout>

          <StatStrip
            stats={[
              {
                label: 'Sites in DPR',
                value: (
                  <>
                    {report.reported_site_count}
                    <span className="text-sm font-normal text-muted-foreground"> of {report.total_site_count}</span>
                  </>
                ),
                tone: report.reported_site_count < report.total_site_count ? 'warn' : 'default',
              },
              { label: 'Workers', value: report.labour.headcount || '—' },
              { label: 'Work items', value: report.activity_count || '—' },
              { label: 'Labour cost', value: money(report.labour.total_cost) },
            ]}
          />

          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
            <div className="flex min-w-0 flex-col">
              <DprSection icon={MapPin} title="Sites" meta={sites.length}>
                <div className="hidden grid-cols-[auto_minmax(0,1.6fr)_repeat(4,minmax(0,0.6fr))_auto] gap-x-3 border-b pb-2 text-xs text-muted-foreground md:grid">
                  <span className="w-5" />
                  <span>Site</span>
                  <span className="text-right">Workers</span>
                  <span className="text-right">Work items</span>
                  <span className="text-right">Photos</span>
                  <span className="text-right">Open issues</span>
                  <span className="w-[88px]" />
                </div>
                <ul className="flex flex-col divide-y">
                  {sites.map((site) => (
                    <SiteRow key={site.site_id} site={site} date={date} line={lineFor(site)} sent={project.sent} />
                  ))}
                </ul>
              </DprSection>

              {report.issues.length === 0 ? (
                <DprSection
                  icon={TriangleAlert}
                  title="Issues"
                  className="py-3"
                  meta={
                    detail.report_source === 'preview' && report.reported_site_count === 0
                      ? 'Show here once a site is confirmed'
                      : 'None reported'
                  }
                />
              ) : (
                <DprSection
                  icon={TriangleAlert}
                  title="Issues"
                  meta={report.issues.length}
                  action={severe > 0 ? <span className={cn(CHIP, 'bg-destructive/10 text-destructive')}>{severe} high or critical</span> : undefined}
                >
                  <ul className="flex flex-col divide-y">
                    {report.issues.map((issue, i) => {
                      const sev = severityChip(issue.severity)
                      return (
                        <li key={i} className="flex items-start justify-between gap-3 py-2">
                          <div className="flex min-w-0 flex-col">
                            <span className="text-sm">{issue.narrative || (issue.issue_type ?? 'Issue').toLowerCase().replace(/_/g, ' ')}</span>
                            <span className="text-xs text-muted-foreground">
                              {issue.site_name}
                              {issue.status && ` · ${issue.status.toLowerCase()}`}
                            </span>
                          </div>
                          {sev && <span className={cn(CHIP, sev.className)}>{sev.label}</span>}
                        </li>
                      )
                    })}
                  </ul>
                </DprSection>
              )}

              {report.materials.length === 0 ? (
                <DprSection icon={Package} title="Materials" meta="None received or used" className="py-3" />
              ) : (
                <DprSection icon={Package} title="Materials" meta={report.materials.length}>
                  <div className="overflow-x-auto rounded-lg border">
                    <table className="w-full text-sm">
                      <thead className="bg-muted/50 text-xs text-muted-foreground">
                        <tr>
                          <th className="px-3 py-1.5 text-left font-medium">Material</th>
                          <th className="px-3 py-1.5 text-right font-medium">Received</th>
                          <th className="px-3 py-1.5 text-right font-medium">Used</th>
                        </tr>
                      </thead>
                      <tbody className="tabular-nums">
                        {report.materials.map((m) => (
                          <tr key={`${m.material_name}-${m.unit}`} className="border-t">
                            <td className="px-3 py-1.5">
                              {m.material_name} <span className="text-muted-foreground">({m.unit})</span>
                            </td>
                            <td className="px-3 py-1.5 text-right">{qty(m.received)}</td>
                            <td className="px-3 py-1.5 text-right">{qty(m.used)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </DprSection>
              )}
            </div>

            <DprAside>
              {detail.summary && <DprSummaryCard summary={detail.summary} />}
              <DprVersionsCard
                reportId={reportId}
                versions={detail.versions}
                onPdf={openPdf}
                empty="Versions appear once the project DPR is sent."
              />
            </DprAside>
          </div>
        </>
      )}
    </div>
  )
}
