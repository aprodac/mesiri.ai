import * as React from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  Activity as ActivityIcon,
  Search,
  RefreshCw,
  Calendar,
  ChevronRight,
  Bot,
  Image as ImageIcon,
  Download,
  X,
  Pencil,
  Trash2,
  CircleCheck,
  CirclePlay,
  CircleDashed,
  CirclePause,
  TriangleAlert,
} from 'lucide-react'
import { ListChecks as IcListChecks, CirclePlay as IcCirclePlay, CircleCheck as IcCircleCheck, CirclePause as IcCirclePause } from 'lucide-react'
import { useScope } from '@/lib/ScopeContext'
import {
  fetchActivitiesApi,
  fetchActivityDetailApi,
  correctActivityApi,
  voidActivityApi,
  correctProgressUpdateApi,
  voidProgressUpdateApi,
  fetchActivityCorrectionsApi,
  type ActivitySummary,
  type ActivityDetailResponse,
  type ActivityCorrection,
} from '@/lib/api'
import { Callout, PageHeader, StatStrip } from '@/components/dpr-page'
import { dayBand } from '@/lib/cues'
import { useSiteNames } from '@/lib/site-names'
import { useUrlState } from '@/lib/url-state'
import { downloadTextFile, toCsv } from '@/lib/export'
import { longDate, plural, qty, siteDayPath } from '@/lib/site-day'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { Fact, Facts, SheetHero, SheetSection } from '@/components/detail-sheet'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { cn, toLocalISODate } from '@/lib/utils'

// --- Status ---
// The backend's activity statuses are PLANNED, IN_PROGRESS, STOPPED and
// COMPLETED (activity_status enum). One icon + colour each (docs/DESIGN.md).

const STATUS: Record<string, { label: string; icon: React.ComponentType<{ className?: string }>; className: string; chip: string }> = {
  completed: { label: 'Completed', icon: CircleCheck, className: 'text-success', chip: 'bg-success-soft text-success' },
  in_progress: { label: 'In progress', icon: CirclePlay, className: 'text-info', chip: 'bg-info-soft text-info' },
  planned: { label: 'Planned', icon: CircleDashed, className: 'text-muted-foreground', chip: 'bg-muted text-muted-foreground' },
  stopped: { label: 'Stopped', icon: CirclePause, className: 'text-draft', chip: 'bg-draft-soft text-draft' },
}

function statusOf(status: string) {
  return STATUS[status.toLowerCase()] ?? { label: status, icon: CircleDashed, className: 'text-muted-foreground', chip: 'bg-muted text-muted-foreground' }
}

function humanize(value: string | null | undefined): string {
  if (!value) return ''
  const text = value.replace(/_/g, ' ').trim()
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** "09:00:00" -> "9:00 am"; times arrive as plain clock strings. */
function clock(value: string | null | undefined): string {
  if (!value) return ''
  const [h, m] = value.split(':').map(Number)
  if (Number.isNaN(h)) return value
  return new Date(2000, 0, 1, h, m || 0).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

function RowSkeleton() {
  return (
    <div className="flex items-center gap-3 py-3">
      <Skeleton className="size-5 rounded-full" />
      <div className="flex flex-1 flex-col gap-1.5">
        <Skeleton className="h-4 w-56" />
        <Skeleton className="h-3 w-40" />
      </div>
    </div>
  )
}

// --- Main Page ---

export default function ActivitiesPage({ embedded = false }: { embedded?: boolean } = {}) {
  const { scope } = useScope()

  const [activities, setActivities] = React.useState<ActivitySummary[]>([])
  const [total, setTotal] = React.useState<number>(0)
  const [loading, setLoading] = React.useState<boolean>(true)
  const [error, setError] = React.useState<string | null>(null)

  // Filters live in the address (survive Back/refresh, shareable). The date
  // range is derived from the preset; only "Pick dates" stores from/to.
  const [, setParams] = useSearchParams()
  const [statusFilter, setStatusFilter] = useUrlState<string>('status', 'ALL')
  const [searchQuery, setSearchQuery] = useUrlState<string>('q', '')
  const [datePreset, setDatePreset] = useUrlState<string>('date', 'ALL')
  const [customFrom, setDateFrom] = useUrlState<string>('from', '')
  const [customTo, setDateTo] = useUrlState<string>('to', '')
  const [dateFrom, dateTo] = React.useMemo(() => {
    const now = new Date()
    if (datePreset === 'TODAY') return [toLocalISODate(now), toLocalISODate(now)]
    if (datePreset === 'THIS_WEEK') return [toLocalISODate(new Date(now.getTime() - 6 * 86_400_000)), toLocalISODate(now)]
    if (datePreset === 'THIS_MONTH') return [toLocalISODate(new Date(now.getFullYear(), now.getMonth(), 1)), toLocalISODate(now)]
    if (datePreset === 'CUSTOM') return [customFrom, customTo]
    return ['', '']
  }, [datePreset, customFrom, customTo])

  // Detail sheet
  const [selectedActivityId, setSelectedActivityId] = React.useState<string | null>(null)
  const [detailData, setDetailData] = React.useState<ActivityDetailResponse | null>(null)
  const [detailLoading, setDetailLoading] = React.useState<boolean>(false)
  const [detailError, setDetailError] = React.useState<string | null>(null)

  // Corrections & undo (ADR-D14/D15)
  const [corrections, setCorrections] = React.useState<ActivityCorrection[]>([])
  const [correctionsLoading, setCorrectionsLoading] = React.useState<boolean>(false)
  const [editOpen, setEditOpen] = React.useState<boolean>(false)
  const [editForm, setEditForm] = React.useState({
    work_type: '', contractor: '', narrative: '', activity_date: '', reason: '',
  })
  const [editSaving, setEditSaving] = React.useState<boolean>(false)
  const [editError, setEditError] = React.useState<string | null>(null)
  const [voidActivityOpen, setVoidActivityOpen] = React.useState<boolean>(false)
  const [voidReason, setVoidReason] = React.useState<string>('')
  const [voidBusy, setVoidBusy] = React.useState<boolean>(false)
  const [voidError, setVoidError] = React.useState<string | null>(null)
  const [correctUpdateId, setCorrectUpdateId] = React.useState<string | null>(null)
  const [correctUpdateForm, setCorrectUpdateForm] = React.useState({ quantity: '', reason: '' })
  const [correctUpdateBusy, setCorrectUpdateBusy] = React.useState<boolean>(false)
  const [correctUpdateError, setCorrectUpdateError] = React.useState<string | null>(null)
  const [voidUpdateId, setVoidUpdateId] = React.useState<string | null>(null)
  const [voidUpdateReason, setVoidUpdateReason] = React.useState<string>('')
  const [voidUpdateBusy, setVoidUpdateBusy] = React.useState<boolean>(false)
  const [voidUpdateError, setVoidUpdateError] = React.useState<string | null>(null)

  const refreshDetail = React.useCallback(async (activityId: string) => {
    const detail = await fetchActivityDetailApi(activityId)
    setDetailData(detail)
  }, [])

  const loadCorrections = React.useCallback(async (activityId: string) => {
    setCorrectionsLoading(true)
    try {
      const res = await fetchActivityCorrectionsApi(activityId)
      setCorrections(res.items || [])
    } catch {
      setCorrections([])
    } finally {
      setCorrectionsLoading(false)
    }
  }, [])

  const openEdit = () => {
    if (!detailData) return
    setEditForm({
      work_type: detailData.work_type || '',
      contractor: detailData.contractor || '',
      narrative: detailData.narrative || '',
      activity_date: detailData.activity_date || '',
      reason: '',
    })
    setEditError(null)
    setEditOpen(true)
  }

  const saveEdit = async () => {
    if (!selectedActivityId) return
    setEditSaving(true)
    setEditError(null)
    try {
      await correctActivityApi(selectedActivityId, {
        work_type: editForm.work_type || null,
        contractor: editForm.contractor || null,
        narrative: editForm.narrative || null,
        activity_date: editForm.activity_date || null,
        reason: editForm.reason || null,
      })
      await refreshDetail(selectedActivityId)
      await loadCorrections(selectedActivityId)
      await fetchList()
      setEditOpen(false)
    } catch (err: any) {
      setEditError(err?.response?.data?.detail || err?.message || 'Failed to save correction')
    } finally {
      setEditSaving(false)
    }
  }

  const confirmVoidActivity = async () => {
    if (!selectedActivityId || !voidReason.trim()) return
    setVoidBusy(true)
    setVoidError(null)
    try {
      await voidActivityApi(selectedActivityId, voidReason.trim())
      setVoidActivityOpen(false)
      setSelectedActivityId(null)
      await fetchList()
    } catch (err: any) {
      setVoidError(err?.response?.data?.detail || err?.message || 'Failed to remove activity')
    } finally {
      setVoidBusy(false)
    }
  }

  const openCorrectUpdate = (updateId: string, currentQuantity: number | string | null | undefined) => {
    setCorrectUpdateId(updateId)
    setCorrectUpdateForm({ quantity: currentQuantity != null ? String(currentQuantity) : '', reason: '' })
    setCorrectUpdateError(null)
  }

  const saveCorrectUpdate = async () => {
    if (!selectedActivityId || !correctUpdateId) return
    setCorrectUpdateBusy(true)
    setCorrectUpdateError(null)
    try {
      await correctProgressUpdateApi(selectedActivityId, correctUpdateId, {
        quantity: correctUpdateForm.quantity === '' ? null : Number(correctUpdateForm.quantity),
        reason: correctUpdateForm.reason || null,
      })
      await refreshDetail(selectedActivityId)
      await loadCorrections(selectedActivityId)
      setCorrectUpdateId(null)
    } catch (err: any) {
      setCorrectUpdateError(err?.response?.data?.detail || err?.message || 'Failed to save correction')
    } finally {
      setCorrectUpdateBusy(false)
    }
  }

  const confirmVoidUpdate = async () => {
    if (!selectedActivityId || !voidUpdateId || !voidUpdateReason.trim()) return
    setVoidUpdateBusy(true)
    setVoidUpdateError(null)
    try {
      await voidProgressUpdateApi(selectedActivityId, voidUpdateId, voidUpdateReason.trim())
      setVoidUpdateId(null)
      setVoidUpdateReason('')
      await refreshDetail(selectedActivityId)
      await loadCorrections(selectedActivityId)
    } catch (err: any) {
      setVoidUpdateError(err?.response?.data?.detail || err?.message || 'Failed to remove update')
    } finally {
      setVoidUpdateBusy(false)
    }
  }

  const handleDatePresetChange = (val: string) => setDatePreset(val)

  const fetchList = React.useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params: Parameters<typeof fetchActivitiesApi>[0] = { limit: 100, offset: 0 }
      if (scope.mode === 'project' && scope.projectId) {
        params.project_id = scope.projectId
      } else if (scope.mode === 'site') {
        if (scope.projectId) params.project_id = scope.projectId
        if (scope.siteId) params.site_id = scope.siteId
      }
      if (statusFilter !== 'ALL') params.status = statusFilter.toLowerCase()
      if (dateFrom) params.date_from = dateFrom
      if (dateTo) params.date_to = dateTo
      const data = await fetchActivitiesApi(params)
      setActivities(data.items || [])
      setTotal(data.total || 0)
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || 'Failed to load activities')
    } finally {
      setLoading(false)
    }
  }, [scope, statusFilter, dateFrom, dateTo])

  React.useEffect(() => { fetchList() }, [fetchList])

  React.useEffect(() => {
    if (!selectedActivityId) {
      setDetailData(null)
      setCorrections([])
      setVoidReason('')
      setVoidError(null)
      return
    }
    let active = true
    setDetailLoading(true)
    setDetailError(null)
    fetchActivityDetailApi(selectedActivityId)
      .then((res) => { if (active) setDetailData(res) })
      .catch((err) => { if (active) setDetailError(err?.response?.data?.detail || err?.message || 'Failed to load detail') })
      .finally(() => { if (active) setDetailLoading(false) })
    loadCorrections(selectedActivityId)
    return () => { active = false }
  }, [selectedActivityId, loadCorrections])

  const filteredActivities = React.useMemo(() => {
    if (!searchQuery.trim()) return activities
    const q = searchQuery.toLowerCase()
    return activities.filter((act) =>
      (act.work_type || '').toLowerCase().includes(q) ||
      (act.contractor || '').toLowerCase().includes(q) ||
      (act.narrative || '').toLowerCase().includes(q) ||
      (act.status || '').toLowerCase().includes(q)
    )
  }, [activities, searchQuery])

  const stats = React.useMemo(() => ({
    totalCount: activities.length,
    inProgress: activities.filter((a) => a.status.toLowerCase() === 'in_progress').length,
    completed: activities.filter((a) => a.status.toLowerCase() === 'completed').length,
    stopped: activities.filter((a) => a.status.toLowerCase() === 'stopped').length,
  }), [activities])

  const scopeLabel =
    scope.mode === 'portfolio' ? 'All projects' : scope.mode === 'project' ? scope.projectName : `${scope.projectName} / ${scope.siteName}`

  const names = useSiteNames()

  // Newest day first; within a day, one block per site.
  const days = React.useMemo(() => {
    const byDay = new Map<string, Map<string, ActivitySummary[]>>()
    for (const act of filteredActivities) {
      const day = byDay.get(act.activity_date) ?? new Map<string, ActivitySummary[]>()
      day.set(act.site_id, [...(day.get(act.site_id) ?? []), act])
      byDay.set(act.activity_date, day)
    }
    return [...byDay.entries()].sort(([a], [b]) => b.localeCompare(a))
  }, [filteredActivities])

  // The Details column only when some item says more than its work type.
  const hasDetails = filteredActivities.some((a) => a.narrative && a.narrative.trim().toLowerCase() !== (a.work_type ?? '').trim().toLowerCase())

  const hasActiveFilters = statusFilter !== 'ALL' || datePreset !== 'ALL' || !!searchQuery

  // One address update: several setters in the same tick would overwrite
  // each other.
  const resetFilters = () =>
    setParams(
      (prev) => {
        for (const key of ['status', 'q', 'date', 'from', 'to']) prev.delete(key)
        return prev
      },
      { replace: true },
    )

  const exportCsv = () => {
    const rows = filteredActivities.map((a) => [
      a.activity_date,
      names.get(a.site_id)?.project ?? '',
      names.get(a.site_id)?.name ?? '',
      a.work_type ?? '',
      a.narrative ?? '',
      a.contractor ?? '',
      statusOf(a.status).label,
      a.started_at ?? '',
      a.source,
    ])
    downloadTextFile(
      `activities-${toLocalISODate(new Date())}.csv`,
      toCsv(['Date', 'Project', 'Site', 'Work', 'Description', 'Contractor', 'Status', 'Started', 'Source'], rows),
    )
  }

  return (
    <div className={embedded ? 'flex flex-col gap-4' : 'mx-auto flex w-full max-w-6xl flex-col gap-4 pb-8 sm:px-2'}>
      {embedded ? (
        <div className="flex justify-end gap-2 sm:-mt-[52px] sm:self-end">
          <>
            <Button variant="outline" size="sm" className="gap-1.5" onClick={exportCsv} disabled={loading || filteredActivities.length === 0}>
              <Download className="size-4" /> Export CSV
            </Button>
            <Button variant="ghost" size="icon" className="size-8" onClick={fetchList} disabled={loading} title="Refresh" aria-label="Refresh">
              <RefreshCw className={cn('size-4', loading && 'animate-spin')} />
            </Button>
          </>
        </div>
      ) : (
        <PageHeader
          title="Activities"
          subtitle={<>Every work item the sites sent, newest first · {scopeLabel}</>}
          actions={
            <>
              <Button variant="outline" size="sm" className="gap-1.5" onClick={exportCsv} disabled={loading || filteredActivities.length === 0}>
                <Download className="size-4" /> Export CSV
              </Button>
              <Button variant="ghost" size="icon" className="size-8" onClick={fetchList} disabled={loading} title="Refresh" aria-label="Refresh">
                <RefreshCw className={cn('size-4', loading && 'animate-spin')} />
              </Button>
            </>
          }
        />
      )}

      <StatStrip
        stats={[
          { label: 'Work items', value: stats.totalCount || '—', icon: IcListChecks },
          { label: 'In progress', value: stats.inProgress || '—', tone: stats.inProgress ? 'info' : 'default', icon: IcCirclePlay },
          { label: 'Completed', value: stats.completed || '—', tone: stats.completed ? 'good' : 'default', icon: IcCircleCheck },
          { label: 'Stopped', value: stats.stopped || '—', tone: stats.stopped > 0 ? 'warn' : 'default', icon: IcCirclePause, hint: stats.stopped ? 'needs a look' : undefined },
        ]}
      />

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-64">
          <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
          <Input
            placeholder="Search work, contractor…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="h-9 pl-8"
          />
        </div>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="h-9 w-[150px]">
            <SelectValue placeholder="Any status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="ALL">Any status</SelectItem>
            <SelectItem value="IN_PROGRESS">In progress</SelectItem>
            <SelectItem value="COMPLETED">Completed</SelectItem>
            <SelectItem value="STOPPED">Stopped</SelectItem>
            <SelectItem value="PLANNED">Planned</SelectItem>
          </SelectContent>
        </Select>
        <Select value={datePreset} onValueChange={handleDatePresetChange}>
          <SelectTrigger className="h-9 w-[150px]">
            <Calendar className="mr-1 size-4 text-muted-foreground" />
            <SelectValue placeholder="Any date" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="ALL">Any date</SelectItem>
            <SelectItem value="TODAY">Today</SelectItem>
            <SelectItem value="THIS_WEEK">Last 7 days</SelectItem>
            <SelectItem value="THIS_MONTH">This month</SelectItem>
            <SelectItem value="CUSTOM">Pick dates</SelectItem>
          </SelectContent>
        </Select>
        {datePreset === 'CUSTOM' && (
          <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <Input type="date" value={customFrom} onChange={(e) => setDateFrom(e.target.value)} className="h-9 w-[150px] dark:[color-scheme:dark]" />
            to
            <Input type="date" value={customTo} onChange={(e) => setDateTo(e.target.value)} className="h-9 w-[150px] dark:[color-scheme:dark]" />
          </div>
        )}
        {hasActiveFilters && (
          <Button variant="ghost" size="sm" onClick={resetFilters} className="gap-1 text-muted-foreground">
            <X className="size-4" /> Clear
          </Button>
        )}
        <span className="ml-auto text-sm text-muted-foreground">
          {filteredActivities.length === total ? plural(total, 'work item') : `${filteredActivities.length} of ${total}`}
        </span>
      </div>

      {/* List: a ledger table (desktop), by day then site (phones) */}
      {error ? (
        <Callout tone="draft" icon={TriangleAlert} action={<Button variant="outline" size="sm" className="bg-background" onClick={fetchList}>Try again</Button>}>
          Activities could not be loaded. {error}
        </Callout>
      ) : loading ? (
        <div className="flex flex-col divide-y">{Array.from({ length: 6 }).map((_, i) => <RowSkeleton key={i} />)}</div>
      ) : days.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center">
          <ActivityIcon className="size-6 text-muted-foreground" />
          <p className="text-sm font-medium">{hasActiveFilters ? 'Nothing matches these filters' : 'No work reported yet'}</p>
          <p className="text-sm text-muted-foreground">
            {hasActiveFilters ? 'Try clearing them.' : 'Work the sites send on WhatsApp shows here.'}
          </p>
          {hasActiveFilters && <Button variant="outline" size="sm" onClick={resetFilters}>Clear filters</Button>}
        </div>
      ) : (
        <>
        {/* Desktop: one ledger table, newest first (WEB-34). */}
        <div className="hidden overflow-x-auto rounded-lg border sm:block">
          <table className="w-full min-w-[820px] text-sm">
            <thead className="sticky top-0 bg-muted/60 text-xs text-muted-foreground">
              <tr className="text-left">
                <th className="px-3 py-2 font-medium">Date</th>
                <th className="px-3 py-2 font-medium">Site</th>
                <th className="px-3 py-2 font-medium">Work</th>
                {hasDetails && <th className="px-3 py-2 font-medium">Details</th>}
                <th className="px-3 py-2 font-medium">Contractor</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Time</th>
                <th className="px-3 py-2 font-medium">From</th>
              </tr>
            </thead>
            <tbody>
              {days.flatMap(([day, sites], di) =>
                [...sites.entries()].flatMap(([siteId, acts], si) =>
                  acts.map((act, ai) => {
                    const st = statusOf(act.status)
                    const site = names.get(siteId)
                    const firstOfDay = si === 0 && ai === 0
                    const detail = act.narrative && act.narrative.trim().toLowerCase() !== (act.work_type ?? '').trim().toLowerCase() ? act.narrative : ''
                    return (
                      <tr
                        key={act.id}
                        onClick={() => setSelectedActivityId(act.id)}
                        // WEB-37: alternate days shaded, each day a block.
                        className={cn('cursor-pointer border-t hover:bg-muted/40', dayBand(di), firstOfDay && di > 0 && 'border-t-foreground/15')}
                      >
                        <td className={cn('whitespace-nowrap px-3 py-1.5 font-medium', !firstOfDay && 'text-transparent')}>
                          {new Date(`${day}T00:00:00`).toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })}
                        </td>
                        <td className="whitespace-nowrap px-3 py-1.5">
                          {ai === 0 ? (
                            <Link to={siteDayPath(siteId, day)} onClick={(e) => e.stopPropagation()} className="hover:underline" title="Open the site report">
                              {site?.name ?? 'Site'}
                              {scope.mode === 'portfolio' && site?.project && <span className="text-xs text-muted-foreground"> · {site.project}</span>}
                            </Link>
                          ) : (
                            <span className="text-transparent">{site?.name}</span>
                          )}
                        </td>
                        <td className="px-3 py-1.5 font-medium">{humanize(act.work_type) || 'Work'}</td>
                        {hasDetails && <td className="max-w-[260px] truncate px-3 py-1.5 text-muted-foreground">{detail}</td>}
                        <td className="whitespace-nowrap px-3 py-1.5 text-muted-foreground">{act.contractor ?? ''}</td>
                        <td className={cn('whitespace-nowrap px-3 py-1.5 font-medium', st.className)}>
                          <span className="inline-flex items-center gap-1.5">
                            <st.icon className="size-3.5" /> {st.label}
                          </span>
                        </td>
                        <td className="whitespace-nowrap px-3 py-1.5 tabular-nums text-muted-foreground">{clock(act.started_at) ?? ''}</td>
                        <td className="whitespace-nowrap px-3 py-1.5 text-muted-foreground">{act.source?.toLowerCase() === 'whatsapp' ? 'WhatsApp' : humanize(act.source)}</td>
                      </tr>
                    )
                  }),
                ),
              )}
            </tbody>
          </table>
        </div>
        {/* Phones: by day, then by site. */}
        <div className="flex flex-col gap-5 sm:hidden">
          {days.map(([day, sites]) => (
            <section key={day} className="flex flex-col">
              <h2 className="sticky top-[60px] z-10 -mx-1 flex items-baseline gap-2 bg-background/95 px-1 py-1.5 text-sm font-semibold backdrop-blur">
                {longDate(day)}
                <span className="font-normal text-muted-foreground">{plural([...sites.values()].flat().length, 'work item')}</span>
              </h2>
              <div className="flex flex-col gap-3">
                {[...sites.entries()].map(([siteId, acts]) => {
                  const site = names.get(siteId)
                  return (
                    <div key={siteId} className="rounded-xl border">
                      <div className="flex items-center justify-between gap-2 border-b bg-muted/40 px-4 py-2">
                        <span className="min-w-0 truncate text-sm">
                          <span className="font-medium">{site?.name ?? 'Site'}</span>
                          {site?.project && <span className="text-muted-foreground"> · {site.project}</span>}
                        </span>
                        <Link to={siteDayPath(siteId, day)} className="inline-flex shrink-0 items-center gap-0.5 text-xs font-medium text-primary hover:underline">
                          Site report <ChevronRight className="size-3.5" />
                        </Link>
                      </div>
                      <ul className="flex flex-col divide-y">
                        {acts.map((act) => {
                          const st = statusOf(act.status)
                          const title = humanize(act.work_type) || 'Work'
                          const detail = act.narrative && act.narrative.trim().toLowerCase() !== (act.work_type ?? '').trim().toLowerCase() ? act.narrative : null
                          return (
                            <li key={act.id}>
                              <button
                                type="button"
                                onClick={() => setSelectedActivityId(act.id)}
                                className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-muted/50"
                              >
                                <st.icon className={cn('size-5 shrink-0', st.className)} />
                                <div className="flex min-w-0 flex-1 flex-col">
                                  <span className="truncate font-medium">{title}</span>
                                  <span className="truncate text-xs text-muted-foreground">
                                    {[detail, act.contractor, clock(act.started_at), act.source?.toLowerCase() === 'whatsapp' ? 'WhatsApp' : act.source]
                                      .filter(Boolean)
                                      .join(' · ')}
                                  </span>
                                </div>
                                <span className={cn('hidden text-xs font-medium sm:inline', st.className)}>{st.label}</span>
                                <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
                              </button>
                            </li>
                          )
                        })}
                      </ul>
                    </div>
                  )
                })}
              </div>
            </section>
          ))}
        </div>
        </>
      )}

      {/* Activity Detail Sheet (WEB-36: the side-panel layout, detail-sheet.tsx;
          sections in a column instead of tabs, empty ones left out) */}
      <Sheet open={!!selectedActivityId} onOpenChange={(open) => !open && setSelectedActivityId(null)}>
        <SheetContent className="w-full gap-0 overflow-y-auto p-0 sm:max-w-xl">
          {detailLoading ? (
            <div className="flex flex-col gap-4 p-6">
              <SheetTitle className="sr-only">Loading</SheetTitle>
              <Skeleton className="h-8 w-3/4" />
              <Skeleton className="h-24 w-full" />
              <Skeleton className="h-36 w-full" />
            </div>
          ) : detailError ? (
            <div className="flex flex-col items-center gap-2 py-16 text-center">
              <SheetTitle className="sr-only">Could not load</SheetTitle>
              <TriangleAlert className="size-5 text-destructive" />
              <p className="text-sm font-medium">{detailError}</p>
            </div>
          ) : detailData ? (
            <>
              <SheetHero
                tone={
                  detailData.status.toLowerCase() === 'completed' ? 'in' : detailData.status.toLowerCase() === 'stopped' ? 'warn' : 'neutral'
                }
                kicker={statusOf(detailData.status).label}
                lead={
                  detailData.quantities?.length ? (
                    <>
                      {qty(String(detailData.quantities[0].quantity))}{' '}
                      <span className="text-xl font-medium text-muted-foreground">{detailData.quantities[0].unit || ''}</span>
                    </>
                  ) : undefined
                }
                title={humanize(detailData.work_type) || 'Work item'}
              >
                <span>{[names.get(detailData.site_id)?.name, names.get(detailData.site_id)?.project].filter(Boolean).join(' · ') || 'Site'}</span>
                <span>{longDate(detailData.activity_date)}</span>
              </SheetHero>

              <div className="flex items-center gap-2 border-b px-5 py-2.5">
                <Button size="sm" variant="outline" className="gap-1.5" onClick={openEdit}>
                  <Pencil className="size-3.5" /> Correct
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="gap-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                  onClick={() => { setVoidReason(''); setVoidError(null); setVoidActivityOpen(true) }}
                >
                  <Trash2 className="size-3.5" /> Remove
                </Button>
                <Button asChild size="sm" variant="ghost" className="ml-auto gap-1 text-primary">
                  <Link to={siteDayPath(detailData.site_id, detailData.activity_date)}>
                    Site report <ChevronRight className="size-3.5" />
                  </Link>
                </Button>
              </div>

              {detailData.narrative && detailData.narrative.trim().toLowerCase() !== (detailData.work_type ?? '').trim().toLowerCase() && (
                <SheetSection title="What was done">
                  <p className="text-sm leading-relaxed">{detailData.narrative}</p>
                </SheetSection>
              )}

              <SheetSection title="Details" className="border-t first:border-t-0">
                <Facts>
                  <Fact label="Contractor">{detailData.contractor || 'Own workers'}</Fact>
                  {detailData.started_at && (
                    <Fact label="Time">
                      {clock(detailData.started_at)}{detailData.ended_at ? ` – ${clock(detailData.ended_at)}` : ''}
                    </Fact>
                  )}
                  <Fact label="Sent">{detailData.source?.toLowerCase() === 'whatsapp' ? 'On WhatsApp' : humanize(detailData.source) || 'On the dashboard'}</Fact>
                </Facts>
              </SheetSection>

              {detailData.quantities && detailData.quantities.length > 0 && (
                <SheetSection title="Quantities" className="border-t">
                  <table className="w-full text-sm">
                    <tbody className="divide-y">
                      {detailData.quantities.map((q) => (
                        <tr key={q.id}>
                          <td className="py-2 pr-2 font-medium">{humanize(q.work_type) || 'Work'}</td>
                          <td className="py-2 pr-2 text-muted-foreground">{humanize(q.measurement_type?.toLowerCase())}</td>
                          <td className="py-2 text-right font-semibold tabular-nums">{qty(String(q.quantity))} {q.unit || ''}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </SheetSection>
              )}

              {detailData.progress_updates && detailData.progress_updates.length > 0 && (
                <SheetSection title={`Updates · ${detailData.progress_updates.length}`} className="border-t">
                  <ol className="ml-1.5 flex flex-col gap-3 border-l-2 py-1 pl-4">
                    {detailData.progress_updates.map((upd) => {
                      const superseded = detailData.progress_updates.some((other) => other.supersedes_id === upd.id)
                      return (
                        <li key={upd.id} className={cn('relative flex flex-col gap-1 text-sm', superseded && 'opacity-50')}>
                          <span className="absolute top-1.5 -left-[22px] size-2.5 rounded-full bg-info" aria-hidden="true" />
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-medium capitalize">
                              {upd.update_kind}
                              {upd.quantity != null && <span className="ml-2 font-semibold text-success tabular-nums">+{upd.quantity} {upd.unit || ''}</span>}
                            </span>
                            <div className="flex shrink-0 items-center gap-2">
                              <span className="text-xs text-muted-foreground">
                                {new Date(upd.occurred_at).toLocaleString([], { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })}
                              </span>
                              {!superseded && (
                                <>
                                  <button
                                    type="button"
                                    className="text-muted-foreground hover:text-foreground"
                                    title="Correct this quantity"
                                    onClick={() => openCorrectUpdate(upd.id, upd.quantity)}
                                  >
                                    <Pencil className="size-3.5" />
                                  </button>
                                  <button
                                    type="button"
                                    className="text-muted-foreground hover:text-destructive"
                                    title="Remove this update"
                                    onClick={() => { setVoidUpdateId(upd.id); setVoidUpdateReason(''); setVoidUpdateError(null) }}
                                  >
                                    <Trash2 className="size-3.5" />
                                  </button>
                                </>
                              )}
                            </div>
                          </div>
                          {upd.narrative && <p className="text-muted-foreground">{upd.narrative}</p>}
                          {upd.supersedes_id && <p className="text-xs text-draft">Corrects an earlier entry</p>}
                          {superseded && <p className="text-xs text-muted-foreground italic">Replaced by a correction</p>}
                        </li>
                      )
                    })}
                  </ol>
                </SheetSection>
              )}

              {detailData.attachments && detailData.attachments.length > 0 && (
                <SheetSection title={`Photos · ${detailData.attachments.length}`} className="border-t">
                  <div className="grid grid-cols-2 gap-3">
                    {detailData.attachments.map((att) => (
                      <div key={att.id} className="overflow-hidden rounded-lg border">
                        <div className="flex aspect-video items-center justify-center border-b bg-muted/40 text-muted-foreground">
                          <ImageIcon className="size-8 opacity-30" />
                        </div>
                        <div className="flex flex-col gap-0.5 p-2.5">
                          <p className="truncate text-sm font-medium">{att.caption || 'Site photo'}</p>
                          {att.ai_caption && (
                            <p className="line-clamp-2 text-xs text-muted-foreground">
                              <Bot className="mr-0.5 inline size-3" />
                              {att.ai_caption}
                            </p>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </SheetSection>
              )}

              {(correctionsLoading || corrections.length > 0) && (
                <SheetSection title="Changes" className="border-t">
                  {correctionsLoading ? (
                    <Skeleton className="h-10 w-full" />
                  ) : (
                    <ul className="flex flex-col gap-2">
                      {corrections.map((c) => (
                        <li key={c.id} className="flex flex-col gap-1 rounded-lg border p-3 text-sm">
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-medium">{humanize(c.field_name)}</span>
                            <span className="text-xs text-muted-foreground">
                              {new Date(c.created_at).toLocaleString([], { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })}
                            </span>
                          </div>
                          <p className="text-muted-foreground">
                            <span className="line-through">{JSON.stringify(c.old_value)}</span>
                            {' → '}
                            <span className="font-medium text-foreground">{JSON.stringify(c.new_value)}</span>
                          </p>
                          {c.reason && <p className="text-muted-foreground italic">"{c.reason}"</p>}
                        </li>
                      ))}
                    </ul>
                  )}
                </SheetSection>
              )}
            </>
          ) : (
            <SheetTitle className="sr-only">Work item</SheetTitle>
          )}
        </SheetContent>
      </Sheet>

      {/* Correct this work item */}
      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="sm:max-w-[480px] gap-4">
          <DialogHeader>
            <DialogTitle className="text-sm font-semibold">Correct this work item</DialogTitle>
            <DialogDescription className="text-xs">
              Header fields only -- allowed even if this day is part of an approved daily report.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label className="text-xs">Work Type</Label>
              <Input
                value={editForm.work_type}
                onChange={(e) => setEditForm((f) => ({ ...f, work_type: e.target.value }))}
                className="h-8 text-xs"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Contractor</Label>
              <Input
                value={editForm.contractor}
                onChange={(e) => setEditForm((f) => ({ ...f, contractor: e.target.value }))}
                className="h-8 text-xs"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Narrative</Label>
              <Input
                value={editForm.narrative}
                onChange={(e) => setEditForm((f) => ({ ...f, narrative: e.target.value }))}
                className="h-8 text-xs"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Activity Date</Label>
              <Input
                type="date"
                value={editForm.activity_date}
                onChange={(e) => setEditForm((f) => ({ ...f, activity_date: e.target.value }))}
                className="h-8 text-xs"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Reason (optional)</Label>
              <Input
                placeholder="Why is this being corrected?"
                value={editForm.reason}
                onChange={(e) => setEditForm((f) => ({ ...f, reason: e.target.value }))}
                className="h-8 text-xs"
              />
            </div>
            {editError && <p className="text-[11px] text-destructive">{editError}</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setEditOpen(false)} disabled={editSaving}>
              Cancel
            </Button>
            <Button size="sm" onClick={saveEdit} disabled={editSaving}>
              {editSaving ? 'Saving…' : 'Save'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Void Activity */}
      <Dialog open={voidActivityOpen} onOpenChange={setVoidActivityOpen}>
        <DialogContent className="sm:max-w-[440px] gap-4">
          <DialogHeader>
            <DialogTitle className="text-sm font-semibold text-destructive">Remove this work item?</DialogTitle>
            <DialogDescription className="text-xs">
              Soft-deleted, never a hard delete. Refused if this day is already part of an approved daily report --
              a correction is used instead in that case.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1">
            <Label className="text-xs">Reason (required)</Label>
            <Input
              placeholder="Why is this being removed?"
              value={voidReason}
              onChange={(e) => setVoidReason(e.target.value)}
              className="h-8 text-xs"
            />
            {voidError && <p className="text-[11px] text-destructive mt-1">{voidError}</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setVoidActivityOpen(false)} disabled={voidBusy}>
              Cancel
            </Button>
            <Button
              size="sm"
              variant="destructive"
              onClick={confirmVoidActivity}
              disabled={voidBusy || !voidReason.trim()}
            >
              {voidBusy ? 'Removing…' : 'Remove'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Correct Progress Update */}
      <Dialog open={!!correctUpdateId} onOpenChange={(open) => !open && setCorrectUpdateId(null)}>
        <DialogContent className="sm:max-w-[420px] gap-4">
          <DialogHeader>
            <DialogTitle className="text-sm font-semibold">Correct this update</DialogTitle>
            <DialogDescription className="text-xs">
              Appends a corrected entry -- the original is kept for the audit trail, never edited or deleted.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label className="text-xs">Quantity</Label>
              <Input
                type="number"
                value={correctUpdateForm.quantity}
                onChange={(e) => setCorrectUpdateForm((f) => ({ ...f, quantity: e.target.value }))}
                className="h-8 text-xs"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Reason (optional)</Label>
              <Input
                placeholder="Why is this being corrected?"
                value={correctUpdateForm.reason}
                onChange={(e) => setCorrectUpdateForm((f) => ({ ...f, reason: e.target.value }))}
                className="h-8 text-xs"
              />
            </div>
            {correctUpdateError && <p className="text-[11px] text-destructive">{correctUpdateError}</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setCorrectUpdateId(null)} disabled={correctUpdateBusy}>
              Cancel
            </Button>
            <Button size="sm" onClick={saveCorrectUpdate} disabled={correctUpdateBusy}>
              {correctUpdateBusy ? 'Saving…' : 'Save'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Void Progress Update */}
      <Dialog open={!!voidUpdateId} onOpenChange={(open) => !open && setVoidUpdateId(null)}>
        <DialogContent className="sm:max-w-[420px] gap-4">
          <DialogHeader>
            <DialogTitle className="text-sm font-semibold text-destructive">Remove this update?</DialogTitle>
            <DialogDescription className="text-xs">
              Soft-deleted, never a hard delete. Refused if this day is already part of an approved daily report.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1">
            <Label className="text-xs">Reason (required)</Label>
            <Input
              placeholder="Why is this being removed?"
              value={voidUpdateReason}
              onChange={(e) => setVoidUpdateReason(e.target.value)}
              className="h-8 text-xs"
            />
            {voidUpdateError && <p className="text-[11px] text-destructive mt-1">{voidUpdateError}</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setVoidUpdateId(null)} disabled={voidUpdateBusy}>
              Cancel
            </Button>
            <Button
              size="sm"
              variant="destructive"
              onClick={confirmVoidUpdate}
              disabled={voidUpdateBusy || !voidUpdateReason.trim()}
            >
              {voidUpdateBusy ? 'Removing…' : 'Remove'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
