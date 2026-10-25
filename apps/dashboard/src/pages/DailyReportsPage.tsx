import * as React from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useInfiniteQuery } from '@tanstack/react-query'
import { Building2, ChevronRight, CircleCheck, CircleDashed, Download, FileText, RefreshCw, TriangleAlert, X } from 'lucide-react'
import { useScope } from '@/lib/ScopeContext'
import { fetchDailyReportPdfApi, fetchDprHistoryApi, type DprHistoryItem } from '@/lib/api'
import { CHIP, errorDetail, localIsoDate, longDate, plural, projectDayPath, siteDayPath } from '@/lib/site-day'
import { exportCsv } from '@/lib/export'
import { cn } from '@/lib/utils'
import { useToast } from '@/components/ui/toast-notification'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Callout, PageHeader } from '@/components/dpr-page'
import { useUrlState } from '@/lib/url-state'

// Daily Reports history (WEB-06): every site and project DPR, newest day
// first, with the figures from the version that was confirmed or sent. Each
// row opens its day (the site DPR page, WEB-04, or the project DPR page,
// WEB-05) and its PDF. Reads GET /dpr/daily-reports. Confirming happens on
// the day pages; this page only looks back.

const PAGE_SIZE = 100

const LEVELS = [
  { value: '', short: 'All' },
  { value: 'site', short: 'Site DPRs' },
  { value: 'project', short: 'Project DPRs' },
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

function ReportRow({ item, onPdf, nested }: { item: DprHistoryItem; onPdf: (item: DprHistoryItem) => void; nested?: boolean }) {
  const status = historyStatus(item)
  const sent = item.workflow_status === 'published'
  const confirmed = item.workflow_status === 'approved' && !unsentProject(item)
  const quiet = item.workflow_status === 'not_reported' || unsentProject(item) || item.version_no === null
  return (
    <li className={cn('flex items-center gap-3 py-2.5', nested && 'pl-3 sm:pl-7')}>
      <span className="shrink-0" title={status.label}>
        {sent || confirmed ? (
          <CircleCheck className="size-5 text-success" />
        ) : quiet ? (
          <CircleDashed className="size-5 text-muted-foreground" />
        ) : (
          <CircleDashed className="size-5 text-draft" />
        )}
      </span>
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
          <Link to={dayPath(item)} className="font-medium hover:underline">
            {item.level === 'project' ? 'Project DPR' : item.site_name}
          </Link>
          <span className={cn(CHIP, status.className)}>{status.label}</span>
        </div>
        <span className="truncate text-xs text-muted-foreground">
          {figures(item)}
          {item.approved_at && item.level === 'site' ? ` · confirmed${item.approved_by ? ` by ${item.approved_by}` : ''}` : ''}
        </span>
        {item.summary && <p className="line-clamp-2 text-xs text-foreground/70">{item.summary}</p>}
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {item.version_no !== null && !unsentProject(item) && (
          <Button variant="ghost" size="icon" className="size-8 text-muted-foreground" title="PDF" aria-label="Open the PDF" onClick={() => onPdf(item)}>
            <FileText />
          </Button>
        )}
        <Button asChild variant="outline" size="sm" className="gap-1">
          <Link to={dayPath(item)}>
            Open <ChevronRight />
          </Link>
        </Button>
      </div>
    </li>
  )
}

const RANGE_LABELS = { '7': 'Last 7 days', '30': 'Last 30 days', '90': 'Last 90 days', custom: 'Pick dates' } as const
type RangeKey = keyof typeof RANGE_LABELS

export default function DailyReportsPage() {
  const toast = useToast()
  const { scope } = useScope()
  const projectFilter = scope.mode === 'portfolio' ? undefined : scope.projectId
  // Filters live in the address (WEB-26): they survive Back and can be shared.
  const [, setParams] = useSearchParams()
  const [range, setRange] = useUrlState<RangeKey>('range', '30')
  const [customFrom, setCustomFrom] = useUrlState<string>('from', '')
  const [customTo, setCustomTo] = useUrlState<string>('to', '')
  const [level, setLevel] = useUrlState<'' | 'site' | 'project'>('level', '')
  const [status, setStatus] = useUrlState<string>('status', '')
  const [today] = React.useState(() => localIsoDate(new Date()))
  const [dateFrom, dateTo] =
    range === 'custom'
      ? [customFrom, customTo]
      : [localIsoDate(new Date(new Date(`${today}T00:00:00`).getTime() - (Number(range) - 1) * 86_400_000)), today]
  const filtered = range !== '30' || !!level || !!status
  const clearFilters = () =>
    setParams(
      (prev) => {
        for (const k of ['range', 'from', 'to', 'level', 'status']) prev.delete(k)
        return prev
      },
      { replace: true },
    )

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
  // Day -> project -> its project DPR and its sites' DPRs.
  const byDate = React.useMemo(() => {
    const days = new Map<string, Map<string, { name: string; project?: DprHistoryItem; sites: DprHistoryItem[] }>>()
    for (const item of items) {
      const day = days.get(item.report_date) ?? new Map()
      const group = day.get(item.project_id) ?? { name: item.project_name, sites: [] }
      if (item.level === 'project') group.project = item
      else group.sites.push(item)
      day.set(item.project_id, group)
      days.set(item.report_date, day)
    }
    return [...days.entries()]
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
      ['Date', 'DPR', 'Project', 'Site', 'Status', 'Workers', 'Work items', 'Open issues', 'Photos', 'Confirmed by'],
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
        i.approved_by,
      ]),
    )

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 pb-8 sm:px-2">
      <PageHeader
        title="Reports"
        subtitle="Every site and project DPR, newest first"
        actions={
          <>
            <Button variant="outline" size="sm" className="gap-1.5" disabled={items.length === 0} onClick={exportRows}>
              <Download className="size-4" /> Export CSV
            </Button>
            <Button variant="ghost" size="icon" className="size-8" onClick={() => query.refetch()} disabled={query.isFetching} title="Refresh" aria-label="Refresh">
              <RefreshCw className={cn('size-4', query.isFetching && 'animate-spin')} />
            </Button>
          </>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <Select value={range} onValueChange={(v) => setRange(v as RangeKey)}>
          <SelectTrigger className="h-9 w-[140px]" aria-label="Dates">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(Object.keys(RANGE_LABELS) as RangeKey[]).map((r) => (
              <SelectItem key={r} value={r}>
                {RANGE_LABELS[r]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {range === 'custom' && (
          <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <Input type="date" aria-label="From" value={customFrom} max={customTo || undefined} onChange={(e) => setCustomFrom(e.target.value)} className="h-9 w-[150px] dark:[color-scheme:dark]" />
            to
            <Input type="date" aria-label="To" value={customTo} min={customFrom || undefined} onChange={(e) => setCustomTo(e.target.value)} className="h-9 w-[150px] dark:[color-scheme:dark]" />
          </div>
        )}
        <div className="flex rounded-lg border p-0.5" role="group" aria-label="Reports">
          {LEVELS.map((l) => (
            <button
              key={l.value}
              type="button"
              aria-pressed={level === l.value}
              onClick={() => setLevel(l.value)}
              className={cn('rounded-md px-2.5 py-1 text-xs font-medium', level === l.value ? 'bg-foreground text-background' : 'text-muted-foreground hover:text-foreground')}
            >
              {l.short}
            </button>
          ))}
        </div>
        <Select value={status || 'any'} onValueChange={(v) => setStatus(v === 'any' ? '' : v)}>
          <SelectTrigger className="h-9 w-[170px]" aria-label="Status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATUSES.map((st) => (
              <SelectItem key={st.value || 'any'} value={st.value || 'any'}>
                {st.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {filtered && (
          <Button variant="ghost" size="sm" className="gap-1 text-muted-foreground" onClick={clearFilters}>
            <X className="size-4" /> Clear
          </Button>
        )}
        <span className="ml-auto text-sm text-muted-foreground">
          {plural(total, 'report')}
          {items.length < total && ` · showing ${items.length}`}
        </span>
      </div>

      {query.isError ? (
        <Callout tone="draft" icon={TriangleAlert} action={<Button variant="outline" size="sm" className="bg-background" onClick={() => query.refetch()}>Try again</Button>}>
          The reports could not be loaded.
        </Callout>
      ) : query.isLoading ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-12 rounded-lg" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center">
          <FileText className="size-6 text-muted-foreground" />
          <p className="text-sm font-medium">No reports for these filters</p>
          {filtered && <Button variant="outline" size="sm" onClick={clearFilters}>Clear filters</Button>}
        </div>
      ) : (
        <div className="flex flex-col gap-5">
          {byDate.map(([day, projects]) => (
            <section key={day} aria-label={longDate(day)} className="flex flex-col">
              <h2 className="sticky top-[60px] z-10 -mx-1 bg-background/95 px-1 py-1.5 text-sm font-semibold backdrop-blur">{longDate(day)}</h2>
              <div className="flex flex-col gap-3">
                {[...projects.entries()].map(([projectId, group]) => (
                  <div key={projectId} className="rounded-xl border px-4 py-1">
                    <p className="flex items-center gap-2 border-b py-2 text-sm">
                      <Building2 className="size-4 text-muted-foreground" />
                      <span className="font-medium">{group.name}</span>
                    </p>
                    <ul className="flex flex-col divide-y">
                      {group.project && <ReportRow item={group.project} onPdf={openPdf} />}
                      {group.sites.map((item) => (
                        <ReportRow key={item.id} item={item} onPdf={openPdf} nested={!!group.project} />
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </section>
          ))}
          {query.hasNextPage && (
            <Button variant="outline" className="self-center" disabled={query.isFetchingNextPage} onClick={() => query.fetchNextPage()}>
              {query.isFetchingNextPage ? 'Loading…' : `Show older reports (${total - items.length} left)`}
            </Button>
          )}
        </div>
      )}
    </div>
  )
}
