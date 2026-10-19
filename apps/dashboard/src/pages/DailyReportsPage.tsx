import * as React from 'react'
import { Link } from 'react-router-dom'
import { useInfiniteQuery } from '@tanstack/react-query'
import { Download, FileText, RefreshCw } from 'lucide-react'
import { useScope } from '@/lib/ScopeContext'
import { fetchDailyReportPdfApi, fetchDprHistoryApi, type DprHistoryItem } from '@/lib/api'
import { CHIP, errorDetail, localIsoDate, longDate, plural, projectDayPath, siteDayPath } from '@/lib/site-day'
import { exportCsv } from '@/lib/export'
import { cn } from '@/lib/utils'
import { useToast } from '@/components/ui/toast-notification'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

// Daily Reports history (WEB-06): every site and project DPR, newest day
// first, with the figures from the version that was confirmed or sent. Each
// row opens its day (the site DPR page, WEB-04, or the project DPR page,
// WEB-05) and its PDF. Reads GET /dpr/daily-reports. Confirming happens on
// the day pages; this page only looks back.

const PAGE_SIZE = 100
const SELECT = 'h-9 rounded-md border border-input bg-background px-2 text-sm'

const LEVELS = [
  { value: '', label: 'Site and project DPRs' },
  { value: 'site', label: 'Site DPRs' },
  { value: 'project', label: 'Project DPRs' },
] as const

const STATUSES = [
  { value: '', label: 'Any status' },
  { value: 'published', label: 'Sent' },
  { value: 'approved', label: 'Confirmed, not sent' },
  { value: 'not_reported', label: 'Not reported' },
] as const

/** A project DPR before it is sent only holds the cutoff's draft roll-up,
 * built before the sites were confirmed: its figures and PDF never go out
 * (the project DPR page shows the live preview instead). */
function unsentProject(item: DprHistoryItem): boolean {
  return item.level === 'project' && !['approved', 'published'].includes(item.workflow_status)
}

function historyStatus(item: DprHistoryItem): { label: string; className: string } {
  if (unsentProject(item)) return { label: 'Not sent yet', className: 'bg-muted text-muted-foreground' }
  switch (item.workflow_status) {
    case 'published':
      return { label: 'Sent', className: 'bg-success-soft text-success' }
    case 'approved':
      return { label: 'Confirmed', className: 'bg-success-soft text-success' }
    case 'not_reported':
      return { label: 'Not reported', className: 'bg-muted text-muted-foreground' }
    default:
      return { label: 'Not confirmed', className: 'bg-draft-soft text-draft' }
  }
}

function money(value: string): string {
  const n = Number(value)
  return n > 0 ? `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—'
}

function figures(item: DprHistoryItem): string {
  if (unsentProject(item)) return 'Open it to see what would go out now'
  if (item.version_no === null) return 'Nothing recorded'
  const parts = [plural(item.workers, 'worker'), plural(item.work_items, 'work item')]
  if (item.level === 'project' && item.total_sites !== null) {
    parts.unshift(`${item.reported_sites ?? 0} of ${item.total_sites} sites`)
  }
  if (Number(item.labour_cost) > 0) parts.push(`${money(item.labour_cost)} labour`)
  if (item.open_issues > 0) parts.push(plural(item.open_issues, 'open issue'))
  if (item.photos > 0) parts.push(plural(item.photos, 'photo'))
  return parts.join(' · ')
}

function dayPath(item: DprHistoryItem): string {
  return item.level === 'project' || !item.site_id
    ? projectDayPath(item.project_id, item.report_date)
    : siteDayPath(item.site_id, item.report_date)
}

function ReportRow({ item, onPdf }: { item: DprHistoryItem; onPdf: (item: DprHistoryItem) => void }) {
  const status = historyStatus(item)
  return (
    <li className="flex flex-col gap-3 py-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold">{item.level === 'project' ? 'Project DPR' : item.site_name}</span>
          <span className="text-sm text-muted-foreground">{item.project_name}</span>
          <span className={cn(CHIP, status.className)}>{status.label}</span>
        </div>
        <span className="text-sm text-muted-foreground">{figures(item)}</span>
        {item.summary && <p className="text-sm">{item.summary}</p>}
        {item.approved_at && item.level === 'site' && (
          <span className="text-xs text-muted-foreground">
            Confirmed{item.approved_by ? ` by ${item.approved_by}` : ''} · {item.dpr_number}
          </span>
        )}
      </div>
      <div className="flex shrink-0 gap-2">
        {item.version_no !== null && !unsentProject(item) && (
          <Button variant="ghost" className="h-11" onClick={() => onPdf(item)}>
            <FileText /> PDF
          </Button>
        )}
        <Button asChild variant="outline" className="h-11 font-semibold">
          <Link to={dayPath(item)}>Open</Link>
        </Button>
      </div>
    </li>
  )
}

export default function DailyReportsPage() {
  const toast = useToast()
  const { scope } = useScope()
  const projectFilter = scope.mode === 'portfolio' ? undefined : scope.projectId
  const [dateFrom, setDateFrom] = React.useState(() => localIsoDate(new Date(Date.now() - 29 * 86_400_000)))
  const [dateTo, setDateTo] = React.useState(() => localIsoDate(new Date()))
  const [level, setLevel] = React.useState<'' | 'site' | 'project'>('')
  const [status, setStatus] = React.useState('')

  const filters = {
    project_id: projectFilter,
    level: level || undefined,
    status: status || undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
  }
  const query = useInfiniteQuery({
    queryKey: ['dpr-history', filters],
    queryFn: ({ pageParam }) => fetchDprHistoryApi({ ...filters, limit: PAGE_SIZE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + p.items.length, 0)
      return loaded < last.total ? loaded : undefined
    },
  })

  const items = React.useMemo(() => query.data?.pages.flatMap((p) => p.items) ?? [], [query.data])
  const total = query.data?.pages[0]?.total ?? 0
  const byDate = React.useMemo(() => {
    const groups = new Map<string, DprHistoryItem[]>()
    for (const item of items) {
      groups.set(item.report_date, [...(groups.get(item.report_date) ?? []), item])
    }
    return [...groups.entries()]
  }, [items])

  const openPdf = async (item: DprHistoryItem) => {
    try {
      const blob = await fetchDailyReportPdfApi(item.id)
      window.open(URL.createObjectURL(blob), '_blank', 'noopener')
    } catch (err) {
      toast.error('Could not open the PDF', errorDetail(err) ?? 'Please try again.')
    }
  }

  const exportRows = () =>
    exportCsv(
      `daily-reports-${dateFrom || 'start'}-to-${dateTo || 'today'}.csv`,
      ['Date', 'DPR', 'Project', 'Site', 'Status', 'Workers', 'Work items', 'Open issues', 'Photos', 'Labour cost', 'Confirmed by'],
      items.map((i) => [
        i.report_date,
        i.dpr_number,
        i.project_name,
        i.level === 'project' ? 'Project DPR' : i.site_name,
        historyStatus(i).label,
        i.workers,
        i.work_items,
        i.open_issues,
        i.photos,
        Number(i.labour_cost) || 0,
        i.approved_by,
      ]),
    )

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-5 p-4 sm:p-6">
      <header className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-bold">Daily Reports</h1>
          <p className="text-sm text-muted-foreground">
            Every site and project DPR, newest first. Open a day to review, confirm or send it.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" className="h-9 gap-1.5" onClick={() => query.refetch()}>
            <RefreshCw className={cn('size-4', query.isFetching && 'animate-spin')} />
            Refresh
          </Button>
          <Button variant="outline" size="sm" className="h-9 gap-1.5" disabled={items.length === 0} onClick={exportRows}>
            <Download className="size-4" />
            Export CSV
          </Button>
        </div>
      </header>

      <section aria-label="Filters" className="grid grid-cols-2 gap-3 rounded-xl border bg-card p-4 sm:grid-cols-4">
        <div className="flex flex-col gap-1">
          <Label htmlFor="dpr-from">From</Label>
          <Input id="dpr-from" type="date" value={dateFrom} max={dateTo || undefined} onChange={(e) => setDateFrom(e.target.value)} />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="dpr-to">To</Label>
          <Input id="dpr-to" type="date" value={dateTo} min={dateFrom || undefined} onChange={(e) => setDateTo(e.target.value)} />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="dpr-level">Reports</Label>
          <select
            id="dpr-level"
            className={SELECT}
            value={level}
            onChange={(e) => setLevel(e.target.value as '' | 'site' | 'project')}
          >
            {LEVELS.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="dpr-status">Status</Label>
          <select id="dpr-status" className={SELECT} value={status} onChange={(e) => setStatus(e.target.value)}>
            {STATUSES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
      </section>

      {query.isLoading ? (
        <p className="text-sm text-muted-foreground">Loading reports…</p>
      ) : query.isError ? (
        <p className="text-sm text-destructive">Could not load the reports. Try Refresh.</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">No reports for these filters.</p>
      ) : (
        <>
          <p className="text-sm text-muted-foreground">
            {plural(total, 'report')}
            {items.length < total && ` · showing ${items.length}`}
          </p>
          {byDate.map(([day, reports]) => (
            <section key={day} aria-label={longDate(day)} className="rounded-2xl border bg-card px-5 py-3">
              <h2 className="border-b pb-2 text-base font-semibold">{longDate(day)}</h2>
              <ul className="flex flex-col divide-y">
                {reports.map((item) => (
                  <ReportRow key={item.id} item={item} onPdf={openPdf} />
                ))}
              </ul>
            </section>
          ))}
          {query.hasNextPage && (
            <Button
              variant="outline"
              className="h-11 self-center font-semibold"
              disabled={query.isFetchingNextPage}
              onClick={() => query.fetchNextPage()}
            >
              Show older reports
            </Button>
          )}
        </>
      )}
    </div>
  )
}
