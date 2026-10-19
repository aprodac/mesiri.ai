import * as React from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Send } from 'lucide-react'
import {
  fetchDailyReportPdfApi,
  fetchProjectDayApi,
  sendProjectDprNowApi,
  type DprVersion,
  type ProjectDayDetail,
  type SiteDayItem,
} from '@/lib/api'
import {
  CHIP,
  FROZEN,
  errorDetail,
  longDate,
  missingText,
  plural,
  qty,
  siteDayPath,
  siteStatus,
} from '@/lib/site-day'
import { useReadOnly } from '@/lib/trial'
import { cn, formatClock } from '@/lib/utils'
import { useToast } from '@/components/ui/toast-notification'
import { DprVersionsCard } from '@/components/dpr-versions-card'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

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

function Stat({ value, label }: { value: React.ReactNode; label: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-xl border bg-card px-4 py-3">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-2xl font-bold">{value}</span>
    </div>
  )
}

function SiteRow({
  site,
  date,
  inReport,
  sent,
}: {
  site: SiteDayItem
  date: string
  inReport: boolean
  sent: boolean
}) {
  const status = siteStatus(site)
  const missing = missingText(site)
  const drafts = site.drafts ?? 0
  return (
    <li className="flex flex-col gap-3 py-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold">{site.site_name}</span>
          <span className={cn(CHIP, status.className)}>{status.label}</span>
          {!inReport && (
            <span className={cn(CHIP, 'bg-draft-soft text-draft')}>
              {sent ? 'Not in the sent DPR' : 'Not in the DPR yet'}
            </span>
          )}
        </div>
        <span className="text-sm text-muted-foreground">
          {plural(site.workers, 'worker')} · {plural(site.work_items, 'work item')} · {plural(site.photos, 'photo')}
          {site.open_issues > 0 && ` · ${plural(site.open_issues, 'open issue')}`}
        </span>
        {site.site_working === 'none' ? (
          <span className="text-xs text-muted-foreground">Marked as no work today.</span>
        ) : missing && !FROZEN.includes(site.status) ? (
          <span className="text-xs text-draft">{missing}</span>
        ) : null}
        {drafts > 0 && <span className="text-xs font-semibold text-draft">{plural(drafts, 'item')} still to confirm</span>}
      </div>
      <Button asChild variant="outline" className="h-11 shrink-0 font-semibold">
        <Link to={siteDayPath(site.site_id, date)}>{drafts > 0 ? 'Review and confirm' : 'Open site DPR'}</Link>
      </Button>
    </li>
  )
}

export default function ProjectDayPage() {
  const { projectId = '', date = '' } = useParams()
  const toast = useToast()
  const queryClient = useQueryClient()
  const readOnly = useReadOnly()
  const [busy, setBusy] = React.useState(false)

  const query = useQuery({
    queryKey: ['project-day', projectId, date],
    queryFn: () => fetchProjectDayApi(projectId, date),
    enabled: Boolean(projectId && date),
    refetchInterval: 60_000,
  })
  const detail = query.data

  if (query.isLoading) {
    return <div className="p-6 text-sm text-muted-foreground">Loading the project's day…</div>
  }
  if (query.isError || !detail) {
    return (
      <div className="flex flex-col gap-3 p-6">
        <p className="text-sm text-destructive">This project's day could not be loaded.</p>
        <Link to={`/today?date=${date}`} className="text-sm font-semibold text-primary hover:underline">
          Back to Today
        </Link>
      </div>
    )
  }

  const { project, report, sites } = detail
  const singleSite = sites.length === 1
  const state = dprState(detail)
  const reportId = project.project_report_id
  const canSend = !readOnly && !project.sent && !project.send_requested
  const reported = new Set(report.sites.filter((s) => s.reported).map((s) => s.site_name))

  const sendNow = async () => {
    setBusy(true)
    try {
      await sendProjectDprNowApi(project.project_id)
      toast.success('Sending the DPR', `${project.project_name}'s DPR goes out within a minute.`)
      queryClient.invalidateQueries({ queryKey: ['project-day', projectId, date] })
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

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-5 p-4 sm:p-6">
      <div className="flex flex-col gap-3">
        <Link to={`/today?date=${date}`} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-4" /> Today
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-1">
            <h1 className="text-2xl font-bold">{project.project_name}</h1>
            <p className="text-sm text-muted-foreground">
              Project DPR · {longDate(date)}
              {project.dpr_send_deadline && !project.sent && ` · Sends by ${formatClock(project.dpr_send_deadline)}`}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className={cn(CHIP, state.className)}>{state.label}</span>
            {canSend && (
              <Button className="h-11 gap-1.5 font-semibold" disabled={busy} onClick={sendNow}>
                <Send className="size-4" />
                Send now
              </Button>
            )}
          </div>
        </div>
        <p
          className={cn(
            'rounded-lg px-3 py-2 text-sm',
            detail.report_source === 'sent' ? 'bg-success-soft text-success' : 'bg-muted/60 text-muted-foreground',
          )}
        >
          {state.note}
        </p>
        {singleSite && (
          <p className="text-sm text-muted-foreground">
            Single-site project: its site DPR is what gets sent.{' '}
            <Link to={siteDayPath(sites[0].site_id, date)} className="font-semibold text-primary hover:underline">
              Open the site DPR
            </Link>
          </p>
        )}
      </div>

      <section aria-label="Summary" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          label="Sites in the DPR"
          value={
            <>
              {report.reported_site_count}{' '}
              <span className="text-base font-medium text-muted-foreground">of {report.total_site_count}</span>
            </>
          }
        />
        <Stat label="Workers" value={report.labour.headcount || '—'} />
        <Stat label="Work items" value={report.activity_count || '—'} />
        <Stat label="Labour cost" value={money(report.labour.total_cost)} />
      </section>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Sites today</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="flex flex-col divide-y">
            {sites.map((site) => (
              <SiteRow
                key={site.site_id}
                site={site}
                date={date}
                inReport={reported.has(site.site_name)}
                sent={project.sent}
              />
            ))}
          </ul>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">In the DPR, by site</CardTitle>
        </CardHeader>
        <CardContent>
          <table className="w-full text-sm">
            <thead className="text-xs text-muted-foreground">
              <tr>
                <th className="py-1 text-left font-medium">Site</th>
                <th className="py-1 text-right font-medium">Work items</th>
                <th className="py-1 text-right font-medium">Workers</th>
                <th className="hidden py-1 text-right font-medium sm:table-cell">Labour cost</th>
                <th className="hidden py-1 text-right font-medium sm:table-cell">Open issues</th>
              </tr>
            </thead>
            <tbody>
              {report.sites.map((s) =>
                s.reported ? (
                  <tr key={s.site_name ?? ''} className="border-t">
                    <td className="py-2">{s.site_name}</td>
                    <td className="py-2 text-right">{s.activity_count}</td>
                    <td className="py-2 text-right">{s.headcount}</td>
                    <td className="hidden py-2 text-right sm:table-cell">{money(s.labour_cost)}</td>
                    <td className="hidden py-2 text-right sm:table-cell">{s.open_issue_count}</td>
                  </tr>
                ) : (
                  <tr key={s.site_name ?? ''} className="border-t text-muted-foreground">
                    <td className="py-2">{s.site_name}</td>
                    <td className="py-2 text-right" colSpan={4}>
                      Not reported
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <div className="grid gap-5 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Materials</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            {report.materials.length === 0 ? (
              <p className="text-sm text-muted-foreground">No materials received or used.</p>
            ) : (
              <table className="w-full text-sm">
                <thead className="text-xs text-muted-foreground">
                  <tr>
                    <th className="py-1 text-left font-medium">Material</th>
                    <th className="py-1 text-right font-medium">Received</th>
                    <th className="py-1 text-right font-medium">Used</th>
                  </tr>
                </thead>
                <tbody>
                  {report.materials.map((m) => (
                    <tr key={`${m.material_name}-${m.unit}`}>
                      <td className="py-1">
                        {m.material_name} <span className="text-muted-foreground">({m.unit})</span>
                      </td>
                      <td className="py-1 text-right">{qty(m.received)}</td>
                      <td className="py-1 text-right">{qty(m.used)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Issues</CardTitle>
          </CardHeader>
          <CardContent>
            {report.issues.length === 0 ? (
              <p className="text-sm text-muted-foreground">No issues reported.</p>
            ) : (
              <ul className="flex flex-col gap-2 text-sm">
                {report.issues.map((issue, i) => (
                  <li key={i} className="flex flex-col">
                    <span>{issue.narrative || (issue.issue_type ?? 'Issue').toLowerCase().replace(/_/g, ' ')}</span>
                    <span className="text-xs text-muted-foreground">
                      {issue.site_name}
                      {issue.severity && ` · ${issue.severity.charAt(0) + issue.severity.slice(1).toLowerCase()}`}
                      {issue.status && ` · ${issue.status.toLowerCase()}`}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <DprVersionsCard
        reportId={reportId}
        versions={detail.versions}
        onPdf={openPdf}
        empty="Versions appear once the project DPR is sent."
      />
    </div>
  )
}
