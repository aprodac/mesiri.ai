import * as React from 'react'
import { Link } from 'react-router-dom'
import { useInfiniteQuery } from '@tanstack/react-query'
import {
  Camera,
  ChevronRight,
  CircleCheck,
  History,
  IndianRupee,
  Package,
  RefreshCw,
  Search,
  TriangleAlert,
  Users,
  Wrench,
} from 'lucide-react'
import { useScope } from '@/lib/ScopeContext'
import { fetchTimelineEntriesApi, type TimelineApiEntry } from '@/lib/api'
import { longDate, plural, siteDayPath } from '@/lib/site-day'
import { useSiteNames } from '@/lib/site-names'
import { Callout, PageHeader } from '@/components/dpr-page'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn, toLocalISODate } from '@/lib/utils'

// Timeline (WEB-24): everything that happened on the sites, newest first,
// grouped by day. Reads GET /timeline -- timeline_entries, filled every
// minute from outbox_events by the projector (infra/mesiri-timeline.timer;
// event types in events/consumers/timeline_projector.py). Each entry links to
// where it lives.

type Kind = 'work' | 'photos' | 'labour' | 'issues' | 'materials' | 'money' | 'other'

const KINDS: Record<Kind, { label: string; icon: React.ComponentType<{ className?: string }>; dot: string }> = {
  work: { label: 'Work', icon: Wrench, dot: 'bg-info-soft text-info' },
  photos: { label: 'Photos', icon: Camera, dot: 'bg-ai-soft text-ai' },
  labour: { label: 'Labour', icon: Users, dot: 'bg-success-soft text-success' },
  issues: { label: 'Issues', icon: TriangleAlert, dot: 'bg-destructive/10 text-destructive' },
  materials: { label: 'Materials', icon: Package, dot: 'bg-draft-soft text-draft' },
  money: { label: 'Money', icon: IndianRupee, dot: 'bg-muted text-foreground/70' },
  other: { label: 'Other', icon: History, dot: 'bg-muted text-muted-foreground' },
}

function kindOf(eventType: string): Kind {
  if (eventType === 'ActivityEvidenceAttached') return 'photos'
  if (eventType.startsWith('Activity')) return 'work'
  if (eventType.startsWith('LabourAttendance')) return 'labour'
  if (eventType.startsWith('SiteIssue')) return 'issues'
  if (eventType.startsWith('Material')) return 'materials'
  if (eventType.startsWith('Expense') || eventType.startsWith('Money')) return 'money'
  return 'other'
}

function humanize(value: unknown): string {
  if (typeof value !== 'string' || !value) return ''
  const text = value.replace(/_/g, ' ').toLowerCase()
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** One plain sentence. Uses the event's payload where the projector's
 * stored summary reads awkwardly ("X activity started"). */
function sentence(e: TimelineApiEntry): string {
  const p = (e.payload ?? {}) as Record<string, unknown>
  switch (e.event_type) {
    case 'ActivityCreated':
      return p.work_type ? `Work reported: ${humanize(p.work_type)}` : 'Work reported'
    case 'ActivityEvidenceAttached':
      return 'Photo added'
    case 'SiteIssueReported':
      return `${humanize(p.issue_type) || 'Issue'} reported${p.severity ? ` · ${humanize(p.severity)}` : ''}`
    case 'SiteIssueResolved':
      return 'Issue resolved'
    case 'LabourAttendanceRecorded':
      return typeof p.total_headcount === 'number' ? `${plural(p.total_headcount, 'worker')} on site` : 'Attendance recorded'
    default:
      return e.summary
  }
}

/** Where to go for the thing an entry is about. */
function linkFor(e: TimelineApiEntry, day: string): { to: string; label: string } | null {
  const kind = kindOf(e.event_type)
  if ((kind === 'work' || kind === 'photos') && e.site_id) return { to: siteDayPath(e.site_id, day), label: 'Site report' }
  if (kind === 'issues') return { to: '/issues', label: 'Issues' }
  if (kind === 'labour') return { to: '/labour/attendance', label: 'Attendance' }
  if (kind === 'materials') return { to: '/materials', label: 'Materials' }
  return null
}

/** Attendance and other date-only records arrive at midnight: no time. */
function clock(iso: string): string {
  const d = new Date(iso)
  if (d.getHours() === 0 && d.getMinutes() === 0) return ''
  return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

const PAGE = 50

export default function OperationsTimelinePage() {
  const { scope } = useScope()
  const names = useSiteNames()
  const [search, setSearch] = React.useState('')
  const [kind, setKind] = React.useState<Kind | 'all'>('all')
  const [range, setRange] = React.useState<'all' | 'today' | 'week' | 'month'>('all')

  const projectId = scope.mode !== 'portfolio' ? scope.projectId : undefined
  const siteId = scope.mode === 'site' ? scope.siteId : undefined
  const dateFrom = React.useMemo(() => {
    const now = new Date()
    if (range === 'today') return toLocalISODate(now)
    if (range === 'week') return toLocalISODate(new Date(now.getTime() - 6 * 86_400_000))
    if (range === 'month') return toLocalISODate(new Date(now.getFullYear(), now.getMonth(), 1))
    return undefined
  }, [range])

  const query = useInfiniteQuery({
    queryKey: ['timeline', projectId, siteId, dateFrom],
    queryFn: ({ pageParam }) => fetchTimelineEntriesApi({ projectId, siteId, dateFrom, limit: PAGE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + p.items.length, 0)
      return loaded < last.total ? loaded : undefined
    },
    refetchInterval: 60_000,
  })
  const total = query.data?.pages[0]?.total ?? 0
  const entries = React.useMemo(() => query.data?.pages.flatMap((p) => p.items) ?? [], [query.data])

  const counts = React.useMemo(() => {
    const c = new Map<Kind, number>()
    for (const e of entries) c.set(kindOf(e.event_type), (c.get(kindOf(e.event_type)) ?? 0) + 1)
    return c
  }, [entries])

  const shown = React.useMemo(() => {
    const q = search.trim().toLowerCase()
    return entries.filter((e) => {
      if (kind !== 'all' && kindOf(e.event_type) !== kind) return false
      if (!q) return true
      const site = e.site_id ? names.get(e.site_id) : undefined
      return [sentence(e), site?.name, site?.project].some((t) => (t ?? '').toLowerCase().includes(q))
    })
  }, [entries, kind, search, names])

  const days = React.useMemo(() => {
    const byDay = new Map<string, TimelineApiEntry[]>()
    for (const e of shown) {
      const day = toLocalISODate(new Date(e.occurred_at))
      byDay.set(day, [...(byDay.get(day) ?? []), e])
    }
    return [...byDay.entries()].sort(([a], [b]) => b.localeCompare(a))
  }, [shown])

  const scopeLabel =
    scope.mode === 'portfolio' ? 'All projects' : scope.mode === 'project' ? scope.projectName : `${scope.projectName} / ${scope.siteName}`

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 pb-8 sm:px-2">
      <PageHeader
        title="Timeline"
        subtitle={<>Everything that happened on the sites, newest first · {scopeLabel}</>}
        actions={
          <Button variant="ghost" size="icon" className="size-8" onClick={() => query.refetch()} disabled={query.isFetching} title="Refresh" aria-label="Refresh">
            <RefreshCw className={cn('size-4', query.isFetching && 'animate-spin')} />
          </Button>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-60">
          <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
          <Input placeholder="Search…" value={search} onChange={(e) => setSearch(e.target.value)} className="h-9 pl-8" />
        </div>
        <Select value={range} onValueChange={(v) => setRange(v as typeof range)}>
          <SelectTrigger className="h-9 w-[140px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Any date</SelectItem>
            <SelectItem value="today">Today</SelectItem>
            <SelectItem value="week">Last 7 days</SelectItem>
            <SelectItem value="month">This month</SelectItem>
          </SelectContent>
        </Select>
        <span className="ml-auto text-sm text-muted-foreground">{plural(total, 'event')}</span>
      </div>

      {/* Kind chips: only the kinds among the loaded events (no counts:
          they would cover only what is loaded so far) */}
      <div className="-mt-1 flex flex-wrap gap-1.5">
        {(['all', ...(Object.keys(KINDS) as Kind[]).filter((k) => counts.has(k))] as const).map((k) => {
          const active = kind === k
          const meta = k === 'all' ? null : KINDS[k]
          return (
            <button
              key={k}
              type="button"
              onClick={() => setKind(k)}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
                active ? 'border-foreground bg-foreground text-background' : 'hover:bg-muted',
              )}
            >
              {meta && <meta.icon className="size-3.5" />}
              {k === 'all' ? 'All' : meta!.label}
            </button>
          )
        })}
      </div>

      {query.isError ? (
        <Callout tone="draft" icon={TriangleAlert} action={<Button variant="outline" size="sm" className="bg-background" onClick={() => query.refetch()}>Try again</Button>}>
          The timeline could not be loaded.
        </Callout>
      ) : query.isLoading ? (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="flex items-center gap-3">
              <Skeleton className="size-7 rounded-full" />
              <Skeleton className="h-4 w-72" />
            </div>
          ))}
        </div>
      ) : days.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center">
          <History className="size-6 text-muted-foreground" />
          <p className="text-sm font-medium">{search || kind !== 'all' || range !== 'all' ? 'Nothing matches' : 'Nothing has happened yet'}</p>
          <p className="text-sm text-muted-foreground">
            {search || kind !== 'all' || range !== 'all' ? 'Try clearing the filters.' : 'Work, photos, labour and issues from the sites show here.'}
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-5">
          {days.map(([day, items]) => (
            <section key={day} className="flex flex-col">
              <h2 className="sticky top-[60px] z-10 -mx-1 flex items-baseline gap-2 bg-background/95 px-1 py-1.5 text-sm font-semibold backdrop-blur">
                {longDate(day)}
                <span className="font-normal text-muted-foreground">{plural(items.length, 'event')}</span>
              </h2>
              <ol className="relative flex flex-col">
                {/* the line the dots sit on */}
                <span aria-hidden className="absolute top-3 bottom-3 left-[13px] w-px bg-border" />
                {items.map((e) => {
                  const k = kindOf(e.event_type)
                  const meta = KINDS[k]
                  const resolved = e.event_type === 'SiteIssueResolved'
                  const Icon = resolved ? CircleCheck : meta.icon
                  const site = e.site_id ? names.get(e.site_id) : undefined
                  const link = linkFor(e, day)
                  return (
                    <li key={e.id} className="relative flex items-start gap-3 py-2">
                      <span className={cn('relative z-[1] flex size-7 shrink-0 items-center justify-center rounded-full ring-4 ring-background', resolved ? 'bg-success-soft text-success' : meta.dot)}>
                        <Icon className="size-3.5" />
                      </span>
                      <div className="flex min-w-0 flex-1 flex-col pt-0.5 sm:flex-row sm:items-baseline sm:gap-3">
                        {/* Phone: time and link share the first line. */}
                        <div className="flex items-center justify-between gap-2 sm:w-16 sm:shrink-0">
                          <span className="text-xs text-muted-foreground tabular-nums">{clock(e.occurred_at)}</span>
                          {link && (
                            <Link to={link.to} className="inline-flex items-center gap-0.5 text-xs font-medium text-primary hover:underline sm:hidden">
                              {link.label} <ChevronRight className="size-3.5" />
                            </Link>
                          )}
                        </div>
                        <div className="flex min-w-0 flex-1 flex-col">
                          <span className="text-sm">{sentence(e)}</span>
                          {site && (
                            <span className="truncate text-xs text-muted-foreground">
                              {site.name}
                              {site.project && ` · ${site.project}`}
                            </span>
                          )}
                        </div>
                        {link && (
                          <Link to={link.to} className="hidden shrink-0 items-center gap-0.5 text-xs font-medium text-primary hover:underline sm:inline-flex">
                            {link.label} <ChevronRight className="size-3.5" />
                          </Link>
                        )}
                      </div>
                    </li>
                  )
                })}
              </ol>
            </section>
          ))}
          {query.hasNextPage && (
            <Button variant="outline" className="self-center" disabled={query.isFetchingNextPage} onClick={() => query.fetchNextPage()}>
              {query.isFetchingNextPage ? 'Loading…' : `Load more (${total - entries.length} left)`}
            </Button>
          )}
        </div>
      )}
    </div>
  )
}
