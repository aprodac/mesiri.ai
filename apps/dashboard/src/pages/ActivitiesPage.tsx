import * as React from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  Activity as ActivityIcon,
  Search,
  RefreshCw,
  Calendar,
  Paperclip,
  ChevronRight,
  Bot,
  Scale,
  History,
  Image as ImageIcon,
  Download,
  X,
  Pencil,
  Trash2,
  ShieldAlert,
  CircleCheck,
  CirclePlay,
  CircleDashed,
  CirclePause,
  TriangleAlert,
} from 'lucide-react'
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
import { Badge } from '@/components/ui/badge'
import { Callout, PageHeader, StatStrip } from '@/components/dpr-page'
import { useSiteNames } from '@/lib/site-names'
import { useUrlState } from '@/lib/url-state'
import { downloadTextFile, toCsv } from '@/lib/export'
import { CHIP, longDate, plural, qty, siteDayPath } from '@/lib/site-day'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
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

function StatusBadge({ status }: { status: string }) {
  const st = statusOf(status)
  return <span className={cn(CHIP, st.chip)}>{st.label}</span>
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
          { label: 'Work items', value: stats.totalCount || '—' },
          { label: 'In progress', value: stats.inProgress || '—' },
          { label: 'Completed', value: stats.completed || '—' },
          { label: 'Stopped', value: stats.stopped || '—', tone: stats.stopped > 0 ? 'warn' : 'default' },
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

      {/* List: by day, then by site */}
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
        <div className="flex flex-col gap-5">
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
      )}

      {/* Activity Detail Sheet */}
      <Sheet open={!!selectedActivityId} onOpenChange={(open) => !open && setSelectedActivityId(null)}>
        <SheetContent className="sm:max-w-xl overflow-y-auto w-full p-0">
          <SheetHeader className="shrink-0 border-b px-6 pt-5 pb-4">
            <div className="flex items-start justify-between gap-3 pr-8">
              <div className="min-w-0">
                <SheetTitle className="text-base font-semibold">{humanize(detailData?.work_type) || 'Work item'}</SheetTitle>
                <SheetDescription className="mt-0.5 text-xs">
                  {detailData
                    ? [longDate(detailData.activity_date), names.get(detailData.site_id)?.name].filter(Boolean).join(' · ')
                    : 'Quantities, updates and photos'}
                </SheetDescription>
              </div>
              {detailData && <StatusBadge status={detailData.status} />}
            </div>
            {detailData && (
              <div className="flex items-center gap-2 mt-3">
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
            )}
          </SheetHeader>

          <div className="px-6 py-4">
            {detailLoading ? (
              <div className="space-y-4">
                <Skeleton className="h-5 w-3/4" />
                <Skeleton className="h-24 w-full" />
                <Skeleton className="h-36 w-full" />
              </div>
            ) : detailError ? (
              <div className="py-10 text-center flex flex-col items-center gap-2">
                <TriangleAlert className="size-5 text-destructive" />
                <p className="text-xs font-semibold text-foreground">{detailError}</p>
              </div>
            ) : detailData ? (
              <div className="space-y-5 text-xs">
                {/* Metadata Grid */}
                <div className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-lg bg-muted/50 p-4">
                  <div>
                    <p className="mb-0.5 text-muted-foreground">Project</p>
                    <p className="font-medium">{names.get(detailData.site_id)?.project || '—'}</p>
                  </div>
                  <div>
                    <p className="mb-0.5 text-muted-foreground">Site</p>
                    <p className="font-medium">{names.get(detailData.site_id)?.name || '—'}</p>
                  </div>
                  <div>
                    <p className="mb-0.5 text-muted-foreground">Contractor</p>
                    <p className="font-medium">{detailData.contractor || 'Own workers'}</p>
                  </div>
                  <div>
                    <p className="mb-0.5 text-muted-foreground">Sent by</p>
                    <p className="font-medium">{detailData.source?.toLowerCase() === 'whatsapp' ? 'WhatsApp' : humanize(detailData.source)}</p>
                  </div>
                  {detailData.started_at && (
                    <div className="col-span-2">
                      <p className="mb-0.5 text-muted-foreground">Time</p>
                      <p className="font-medium">
                        {clock(detailData.started_at)}{detailData.ended_at ? ` – ${clock(detailData.ended_at)}` : ''}
                      </p>
                    </div>
                  )}
                </div>

                {/* Narrative */}
                {detailData.narrative && detailData.narrative.trim().toLowerCase() !== (detailData.work_type ?? '').trim().toLowerCase() && (
                  <div className="space-y-1.5">
                    <p className="font-medium">Description</p>
                    <div className="leading-relaxed text-muted-foreground">
                      {detailData.narrative}
                    </div>
                  </div>
                )}

                {/* Tabs */}
                <Tabs defaultValue="quantities" className="w-full">
                  <TabsList className="grid grid-cols-4 w-full h-9">
                    <TabsTrigger value="quantities" className="text-xs gap-1.5">
                      <Scale className="size-3.5" />Quantities ({detailData.quantities?.length || 0})
                    </TabsTrigger>
                    <TabsTrigger value="updates" className="text-xs gap-1.5">
                      <History className="size-3.5" />Updates ({detailData.progress_updates?.length || 0})
                    </TabsTrigger>
                    <TabsTrigger value="attachments" className="text-xs gap-1.5">
                      <Paperclip className="size-3.5" />Photos ({detailData.attachments?.length || 0})
                    </TabsTrigger>
                    <TabsTrigger value="corrections" className="text-xs gap-1.5">
                      <ShieldAlert className="size-3.5" />History ({corrections.length})
                    </TabsTrigger>
                  </TabsList>

                  <TabsContent value="quantities" className="pt-3">
                    {!detailData.quantities || detailData.quantities.length === 0 ? (
                      <div className="text-center py-8 text-muted-foreground">
                        <Scale className="size-7 mx-auto mb-2 opacity-30" />
                        <p className="text-[11px]">No quantity measurements logged for this activity.</p>
                      </div>
                    ) : (
                      <div className="rounded-lg border border-border/70 overflow-hidden">
                        <Table>
                          <TableHeader className="bg-muted/30 text-[11px]">
                            <TableRow>
                              <TableHead>Type</TableHead>
                              <TableHead>Measurement</TableHead>
                              <TableHead className="text-right">Quantity</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody className="text-xs">
                            {detailData.quantities.map((q) => (
                              <TableRow key={q.id}>
                                <TableCell className="font-medium">{humanize(q.work_type) || 'Work'}</TableCell>
                                <TableCell className="text-muted-foreground">{humanize(q.measurement_type?.toLowerCase())}</TableCell>
                                <TableCell className="text-right font-semibold">{qty(String(q.quantity))} {q.unit || ''}</TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    )}
                  </TabsContent>

                  <TabsContent value="updates" className="pt-3">
                    {!detailData.progress_updates || detailData.progress_updates.length === 0 ? (
                      <div className="text-center py-8 text-muted-foreground">
                        <History className="size-7 mx-auto mb-2 opacity-30" />
                        <p className="text-[11px]">No incremental progress updates recorded yet.</p>
                      </div>
                    ) : (
                      <div className="space-y-3 border-l-2 border-border pl-4 py-1 ml-2">
                        {detailData.progress_updates.map((upd) => {
                          const superseded = detailData.progress_updates.some((other) => other.supersedes_id === upd.id)
                          return (
                            <div key={upd.id} className={cn('relative space-y-1', superseded && 'opacity-50')}>
                              <div className="absolute -left-[21px] top-1 size-2.5 rounded-full bg-info" />
                              <div className="flex items-center justify-between text-[11px] gap-2">
                                <span className="font-semibold text-foreground capitalize">{upd.update_kind}</span>
                                <div className="flex items-center gap-1.5 shrink-0">
                                  <span className="text-muted-foreground">{new Date(upd.occurred_at).toLocaleString()}</span>
                                  {!superseded && (
                                    <>
                                      <button
                                        type="button"
                                        className="text-muted-foreground hover:text-foreground"
                                        title="Correct this quantity"
                                        onClick={() => openCorrectUpdate(upd.id, upd.quantity)}
                                      >
                                        <Pencil className="size-3" />
                                      </button>
                                      <button
                                        type="button"
                                        className="text-muted-foreground hover:text-destructive"
                                        title="Remove this update"
                                        onClick={() => { setVoidUpdateId(upd.id); setVoidUpdateReason(''); setVoidUpdateError(null) }}
                                      >
                                        <Trash2 className="size-3" />
                                      </button>
                                    </>
                                  )}
                                </div>
                              </div>
                              {upd.narrative && <p className="text-muted-foreground">{upd.narrative}</p>}
                              {upd.quantity != null && (
                                <Badge variant="outline" className="font-semibold text-[10px]">+{upd.quantity} {upd.unit || ''}</Badge>
                              )}
                              {upd.supersedes_id && (
                                <p className="text-[10px] text-draft">Corrects a previous entry</p>
                              )}
                              {superseded && (
                                <p className="text-[10px] text-muted-foreground italic">Superseded by a correction below</p>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </TabsContent>

                  <TabsContent value="corrections" className="pt-3">
                    {correctionsLoading ? (
                      <div className="space-y-2">
                        <Skeleton className="h-10 w-full" />
                        <Skeleton className="h-10 w-full" />
                      </div>
                    ) : corrections.length === 0 ? (
                      <div className="text-center py-8 text-muted-foreground">
                        <ShieldAlert className="size-7 mx-auto mb-2 opacity-30" />
                        <p className="text-[11px]">No corrections or removals recorded for this activity.</p>
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {corrections.map((c) => (
                          <div key={c.id} className="rounded-lg border border-border/70 p-3 space-y-1 text-[11px]">
                            <div className="flex items-center justify-between">
                              <span className="font-semibold text-foreground">{c.field_name}</span>
                              <span className="text-muted-foreground">{new Date(c.created_at).toLocaleString()}</span>
                            </div>
                            <p className="text-muted-foreground">
                              <span className="line-through">{JSON.stringify(c.old_value)}</span>
                              {' → '}
                              <span className="font-semibold text-foreground">{JSON.stringify(c.new_value)}</span>
                            </p>
                            {c.reason && <p className="text-muted-foreground italic">"{c.reason}"</p>}
                          </div>
                        ))}
                      </div>
                    )}
                  </TabsContent>

                  <TabsContent value="attachments" className="pt-3">
                    {!detailData.attachments || detailData.attachments.length === 0 ? (
                      <div className="text-center py-8 text-muted-foreground">
                        <ImageIcon className="size-7 mx-auto mb-2 opacity-30" />
                        <p className="text-[11px]">No media evidence or photo attachments uploaded.</p>
                      </div>
                    ) : (
                      <div className="grid grid-cols-2 gap-3">
                        {detailData.attachments.map((att) => (
                          <div key={att.id} className="rounded-lg border border-border/70 overflow-hidden">
                            <div className="aspect-video bg-muted/40 flex items-center justify-center text-muted-foreground border-b border-border/40">
                              <ImageIcon className="size-8 opacity-30" />
                            </div>
                            <div className="p-2.5 space-y-0.5">
                              <p className="font-semibold text-foreground truncate text-[11px]">{att.caption || att.attachment_type || 'Site Photo'}</p>
                              {att.ai_caption && (
                                <p className="text-[10px] text-muted-foreground line-clamp-2">
                                  <Bot className="size-2.5 inline mr-0.5" />{att.ai_caption}
                                </p>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </TabsContent>
                </Tabs>
              </div>
            ) : null}
          </div>
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
