import * as React from 'react'
import {
  Activity,
  Search,
  Filter,
  RefreshCw,
  Calendar,
  Clock,
  Paperclip,
  CheckCircle2,
  AlertTriangle,
  PlayCircle,
  XCircle,
  HelpCircle,
  ChevronRight,
  Bot,
  MessageSquare,
  Scale,
  History,
  Image as ImageIcon,
  Download,
  Layers,
  X,
  Pencil,
  Trash2,
  ShieldAlert,
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
import { KpiCard } from '@/components/ui/kpi-card'
import { Badge } from '@/components/ui/badge'
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

// --- Status Badge ---

function StatusBadge({ status }: { status: string }) {
  const s = status.toLowerCase()
  switch (s) {
    case 'completed':
      return (
        <Badge variant="outline" className="bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/30 gap-1 font-semibold text-[11px]">
          <CheckCircle2 className="size-3" />Completed
        </Badge>
      )
    case 'in_progress':
      return (
        <Badge variant="outline" className="bg-sky-500/10 text-sky-600 dark:text-sky-400 border-sky-500/30 gap-1 font-semibold text-[11px]">
          <PlayCircle className="size-3" />In Progress
        </Badge>
      )
    case 'planned':
      return (
        <Badge variant="outline" className="bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/30 gap-1 font-semibold text-[11px]">
          <Clock className="size-3" />Planned
        </Badge>
      )
    case 'blocked':
    case 'issue':
      return (
        <Badge variant="outline" className="bg-rose-500/10 text-rose-600 dark:text-rose-400 border-rose-500/30 gap-1 font-semibold text-[11px]">
          <AlertTriangle className="size-3" />Blocked
        </Badge>
      )
    case 'cancelled':
      return (
        <Badge variant="outline" className="bg-zinc-500/10 text-zinc-600 dark:text-zinc-400 border-zinc-500/30 gap-1 font-semibold text-[11px]">
          <XCircle className="size-3" />Cancelled
        </Badge>
      )
    default:
      return (
        <Badge variant="outline" className="bg-muted text-muted-foreground gap-1 font-semibold text-[11px]">
          <HelpCircle className="size-3" />{status}
        </Badge>
      )
  }
}

// --- Source Badge ---

function SourceBadge({ source }: { source: string | null | undefined }) {
  const isWa = source?.toLowerCase() === 'whatsapp'
  return (
    <Badge variant="secondary" className="text-[11px] font-medium border border-border/50 gap-1 bg-muted/30">
      {isWa ? (
        <><MessageSquare className="size-3 text-[#008069]" />WhatsApp</>
      ) : (
        <><Bot className="size-3 text-primary" />{source || 'Web'}</>
      )}
    </Badge>
  )
}

// --- Table Row Skeleton ---

function TableRowSkeleton() {
  return (
    <TableRow>
      <TableCell><Skeleton className="h-4 w-20" /></TableCell>
      <TableCell><div className="flex flex-col gap-1.5"><Skeleton className="h-4 w-40" /><Skeleton className="h-3 w-56" /></div></TableCell>
      <TableCell><Skeleton className="h-4 w-28" /></TableCell>
      <TableCell><Skeleton className="h-5 w-20 rounded-full" /></TableCell>
      <TableCell><Skeleton className="h-5 w-20 rounded-full" /></TableCell>
      <TableCell className="text-right"><Skeleton className="h-6 w-16 ml-auto" /></TableCell>
    </TableRow>
  )
}

// --- Main Page ---

export default function ActivitiesPage() {
  const { scope } = useScope()

  const [activities, setActivities] = React.useState<ActivitySummary[]>([])
  const [total, setTotal] = React.useState<number>(0)
  const [loading, setLoading] = React.useState<boolean>(true)
  const [error, setError] = React.useState<string | null>(null)

  // Filters
  const [statusFilter, setStatusFilter] = React.useState<string>('ALL')
  const [searchQuery, setSearchQuery] = React.useState<string>('')
  const [datePreset, setDatePreset] = React.useState<string>('ALL')
  const [dateFrom, setDateFrom] = React.useState<string>('')
  const [dateTo, setDateTo] = React.useState<string>('')

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

  const handleDatePresetChange = (val: string) => {
    setDatePreset(val)
    const now = new Date()
    if (val === 'ALL') {
      setDateFrom('')
      setDateTo('')
    } else if (val === 'TODAY') {
      const todayStr = toLocalISODate(now)
      setDateFrom(todayStr)
      setDateTo(todayStr)
    } else if (val === 'THIS_WEEK') {
      const lastWeek = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000)
      setDateFrom(toLocalISODate(lastWeek))
      setDateTo(toLocalISODate(now))
    } else if (val === 'THIS_MONTH') {
      const firstDay = new Date(now.getFullYear(), now.getMonth(), 1)
      setDateFrom(toLocalISODate(firstDay))
      setDateTo(toLocalISODate(now))
    }
  }

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
    blocked: activities.filter((a) => ['blocked', 'issue'].includes(a.status.toLowerCase())).length,
    planned: activities.filter((a) => a.status.toLowerCase() === 'planned').length,
  }), [activities])

  const scopeLabel = React.useMemo(() => {
    if (scope.mode === 'portfolio') return 'Portfolio Scope (All Projects)'
    if (scope.mode === 'project') return `Project Scope: ${scope.projectName}`
    return `Site Scope: ${scope.projectName} / ${scope.siteName}`
  }, [scope])

  const hasActiveFilters = statusFilter !== 'ALL' || datePreset !== 'ALL' || !!dateFrom || !!dateTo || !!searchQuery

  const resetFilters = () => {
    setStatusFilter('ALL')
    setDatePreset('ALL')
    setDateFrom('')
    setDateTo('')
    setSearchQuery('')
  }

  return (
    <div className="flex flex-col gap-4 w-full max-w-full relative pb-12">

      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b pb-3.5">
        <div className="flex items-center gap-3">
          <div className="size-10 rounded-lg border border-violet-500/30 bg-violet-500/10 flex items-center justify-center text-violet-600 dark:text-violet-400 shrink-0 shadow-2xs">
            <Activity className="size-5" />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2">
              Site Activities
              <Badge variant="outline" className="text-[10px] font-mono border-violet-500/30 text-violet-600 dark:text-violet-400">
                Operations Module
              </Badge>
            </h1>
            <p className="text-xs text-muted-foreground font-medium">{scopeLabel}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" className="h-8 gap-1.5 text-xs font-medium" onClick={() => alert('Exporting Activities as CSV...')}>
            <Download className="size-3.5" />Export CSV
          </Button>
          <Button variant="outline" size="sm" onClick={fetchList} disabled={loading} className="h-8 gap-1.5 text-xs">
            <RefreshCw className={cn('size-3.5', loading && 'animate-spin')} />Refresh
          </Button>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <KpiCard
          title="Total Activities"
          value={<span className="text-violet-600 dark:text-violet-400">{stats.totalCount}</span>}
          trend="neutral"
          trendValue={`${stats.planned} Planned`}
          description="Logged site activities"
          icon={<Activity className="text-violet-500" />}
          chartData={[4, 8, 6, 12, 10, 15, 18, 20]}
        />
        <KpiCard
          title="In Progress"
          value={<span className="text-sky-600 dark:text-sky-400">{stats.inProgress}</span>}
          trend="up"
          trendValue="Active Now"
          description="Currently running work"
          icon={<PlayCircle className="text-sky-500" />}
          chartData={[2, 4, 3, 6, 5, 8, 7, 9]}
        />
        <KpiCard
          title="Completed"
          value={<span className="text-emerald-600 dark:text-emerald-400">{stats.completed}</span>}
          trend="up"
          trendValue={stats.totalCount > 0 ? `${Math.round((stats.completed / stats.totalCount) * 100)}% Done` : '0% Done'}
          description="Successfully finished tasks"
          icon={<CheckCircle2 className="text-emerald-500" />}
          chartData={[1, 3, 5, 7, 9, 11, 14, 16]}
        />
        <KpiCard
          title="Blocked / Issues"
          value={<span className="text-rose-600 dark:text-rose-400">{stats.blocked}</span>}
          trend={stats.blocked > 0 ? 'down' : 'neutral'}
          trendValue={stats.blocked > 0 ? 'Needs Attention' : 'All Clear'}
          description="Requiring management review"
          icon={<AlertTriangle className="text-rose-500" />}
          chartData={[1, 2, 1, 3, 2, 4, 2, 3]}
        />
      </div>

      {/* Filter Toolbar */}
      <div className="flex flex-col sm:flex-row gap-2.5 items-center justify-between border border-border/80 p-2.5 rounded-lg bg-card/40">
        <div className="flex flex-wrap gap-2 w-full sm:w-auto flex-1 items-center">
          {/* Search */}
          <div className="relative w-full sm:w-60">
            <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
            <Input
              placeholder="Search work type, contractor..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-8 h-9 text-xs"
            />
          </div>

          {/* Status filter */}
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="h-9 text-xs w-full sm:w-36">
              <Filter className="size-3.5 mr-1.5 text-muted-foreground shrink-0" />
              <SelectValue placeholder="All Statuses" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All Statuses</SelectItem>
              <SelectItem value="PLANNED">Planned</SelectItem>
              <SelectItem value="IN_PROGRESS">In Progress</SelectItem>
              <SelectItem value="COMPLETED">Completed</SelectItem>
              <SelectItem value="BLOCKED">Blocked</SelectItem>
              <SelectItem value="CANCELLED">Cancelled</SelectItem>
            </SelectContent>
          </Select>

          {/* Date Preset Dropdown */}
          <Select value={datePreset} onValueChange={handleDatePresetChange}>
            <SelectTrigger className="h-9 text-xs w-full sm:w-36">
              <Calendar className="size-3.5 mr-1.5 text-muted-foreground shrink-0" />
              <SelectValue placeholder="All Dates" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All Dates</SelectItem>
              <SelectItem value="TODAY">Today</SelectItem>
              <SelectItem value="THIS_WEEK">This Week</SelectItem>
              <SelectItem value="THIS_MONTH">This Month</SelectItem>
              <SelectItem value="CUSTOM">Custom Range</SelectItem>
            </SelectContent>
          </Select>

          {/* Custom Date Range Inputs - Clean aligned pill box */}
          {(datePreset === 'CUSTOM' || (dateFrom && datePreset !== 'TODAY' && datePreset !== 'THIS_WEEK' && datePreset !== 'THIS_MONTH')) && (
            <div className="flex items-center gap-1.5 bg-muted/40 p-1 px-2.5 rounded-md border border-border/80 h-9">
              <span className="text-[11px] text-muted-foreground font-semibold shrink-0">From</span>
              <Input
                type="date"
                value={dateFrom}
                onChange={(e) => {
                  setDateFrom(e.target.value)
                  setDatePreset('CUSTOM')
                }}
                className="w-36 h-7 text-xs bg-background font-mono dark:[color-scheme:dark] px-2 py-0 border-border/80 shadow-2xs"
              />
              <span className="text-[11px] text-muted-foreground font-semibold shrink-0">To</span>
              <Input
                type="date"
                value={dateTo}
                onChange={(e) => {
                  setDateTo(e.target.value)
                  setDatePreset('CUSTOM')
                }}
                className="w-36 h-7 text-xs bg-background font-mono dark:[color-scheme:dark] px-2 py-0 border-border/80 shadow-2xs"
              />
            </div>
          )}

          {hasActiveFilters && (
            <Button
              variant="ghost"
              size="sm"
              onClick={resetFilters}
              className="h-9 text-xs text-muted-foreground hover:text-foreground gap-1 px-2"
            >
              <X className="size-3.5" />
              Clear
            </Button>
          )}
        </div>

        <p className="text-xs text-muted-foreground shrink-0 font-medium">
          {filteredActivities.length} of {total} activities
        </p>
      </div>

      {/* Main Table */}
      <div className="rounded-lg border border-border/80 overflow-hidden bg-card">
        <div className="flex items-center justify-between px-4 py-2.5 border-b bg-muted/20">
          <div className="flex items-center gap-2">
            <Layers className="size-4 text-muted-foreground" />
            <span className="text-xs font-semibold text-foreground">Activity Records</span>
          </div>
          {!loading && !error && (
            <span className="text-[11px] text-muted-foreground font-mono">{filteredActivities.length} records</span>
          )}
        </div>

        {error ? (
          <div className="p-12 text-center flex flex-col items-center justify-center gap-3">
            <div className="size-12 rounded-full bg-rose-500/10 border border-rose-500/20 flex items-center justify-center">
              <AlertTriangle className="size-5 text-rose-500" />
            </div>
            <div>
              <h3 className="font-bold text-foreground text-sm">Failed to load activities</h3>
              <p className="text-xs text-muted-foreground mt-1 max-w-md">{error}</p>
            </div>
            <Button variant="outline" size="sm" onClick={fetchList} className="mt-1 text-xs h-8">Try Again</Button>
          </div>
        ) : (
          <Table>
            <TableHeader className="bg-muted/40 text-xs">
              <TableRow>
                <TableHead className="w-[120px] font-semibold">Date</TableHead>
                <TableHead className="font-semibold">Work Type / Package</TableHead>
                <TableHead className="font-semibold">Contractor</TableHead>
                <TableHead className="w-[130px] font-semibold">Status</TableHead>
                <TableHead className="w-[110px] font-semibold">Source</TableHead>
                <TableHead className="w-[90px] text-right font-semibold">Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody className="text-xs">
              {loading ? (
                Array.from({ length: 6 }).map((_, i) => <TableRowSkeleton key={i} />)
              ) : filteredActivities.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6}>
                    <div className="py-16 text-center flex flex-col items-center justify-center gap-3">
                      <div className="size-12 rounded-full bg-muted border border-border flex items-center justify-center">
                        <Activity className="size-5 text-muted-foreground/40" />
                      </div>
                      <div>
                        <p className="text-sm font-semibold text-foreground">No activities found</p>
                        <p className="text-xs text-muted-foreground mt-1 max-w-sm">
                          {hasActiveFilters ? 'No records match your current filters. Try clearing them.' : 'No activity records have been logged for this scope yet.'}
                        </p>
                      </div>
                      {hasActiveFilters && (
                        <Button variant="outline" size="sm" onClick={resetFilters} className="text-xs h-8 mt-1">Clear filters</Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ) : (
                filteredActivities.map((act) => (
                  <TableRow key={act.id} className="hover:bg-muted/30 transition-colors cursor-pointer" onClick={() => setSelectedActivityId(act.id)}>
                    <TableCell className="font-medium whitespace-nowrap">
                      <div className="flex flex-col">
                        <span className="font-semibold text-foreground">{act.activity_date}</span>
                        {act.started_at && (
                          <span className="text-[11px] text-muted-foreground font-mono">
                            {act.started_at}{act.ended_at ? ` \u2013 ${act.ended_at}` : ''}
                          </span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-col gap-0.5">
                        <span className="font-bold text-foreground">{act.work_type || 'General Work Activity'}</span>
                        {act.narrative && <p className="text-muted-foreground line-clamp-1 text-[11px]">{act.narrative}</p>}
                      </div>
                    </TableCell>
                    <TableCell className="whitespace-nowrap font-medium text-foreground">
                      {act.contractor || <span className="text-muted-foreground italic">Direct Labour</span>}
                    </TableCell>
                    <TableCell><StatusBadge status={act.status} /></TableCell>
                    <TableCell><SourceBadge source={act.source} /></TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="sm" className="h-7 text-xs font-semibold gap-1 text-violet-600 hover:text-violet-700 hover:bg-violet-500/10" onClick={(e) => { e.stopPropagation(); setSelectedActivityId(act.id) }}>
                        Details<ChevronRight className="size-3" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        )}
      </div>

      {/* Activity Detail Sheet */}
      <Sheet open={!!selectedActivityId} onOpenChange={(open) => !open && setSelectedActivityId(null)}>
        <SheetContent className="sm:max-w-xl overflow-y-auto w-full p-0">
          <SheetHeader className="px-6 pt-5 pb-4 border-b bg-muted/20 shrink-0">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2.5">
                <div className="size-9 rounded-lg bg-violet-500/10 border border-violet-500/30 flex items-center justify-center shrink-0">
                  <Activity className="size-4 text-violet-600 dark:text-violet-400" />
                </div>
                <div>
                  <SheetTitle className="text-sm font-bold">Activity Detail</SheetTitle>
                  <SheetDescription className="text-[11px] mt-0.5">Quantities, progress updates, and evidence</SheetDescription>
                </div>
              </div>
              {detailData && <StatusBadge status={detailData.status} />}
            </div>
            {detailData && (
              <div className="flex items-center gap-2 mt-3">
                <Button size="sm" variant="outline" className="h-7 gap-1.5 text-[11px]" onClick={openEdit}>
                  <Pencil className="size-3" />Correct Details
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7 gap-1.5 text-[11px] text-rose-600 dark:text-rose-400 border-rose-500/30 hover:bg-rose-500/10"
                  onClick={() => { setVoidReason(''); setVoidError(null); setVoidActivityOpen(true) }}
                >
                  <Trash2 className="size-3" />Remove Activity
                </Button>
              </div>
            )}
          </SheetHeader>

          <div className="p-6">
            {detailLoading ? (
              <div className="space-y-4">
                <Skeleton className="h-5 w-3/4" />
                <Skeleton className="h-24 w-full" />
                <Skeleton className="h-36 w-full" />
              </div>
            ) : detailError ? (
              <div className="py-10 text-center flex flex-col items-center gap-2">
                <div className="size-10 rounded-full bg-rose-500/10 flex items-center justify-center">
                  <AlertTriangle className="size-5 text-rose-500" />
                </div>
                <p className="text-xs font-semibold text-foreground">{detailError}</p>
              </div>
            ) : detailData ? (
              <div className="space-y-5 text-xs">
                {/* Metadata Grid */}
                <div className="grid grid-cols-2 gap-x-4 gap-y-3 p-4 rounded-lg border border-border/70 bg-muted/10">
                  <div>
                    <p className="text-muted-foreground font-medium mb-0.5">Work Type</p>
                    <p className="font-bold text-foreground">{detailData.work_type || 'General Activity'}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground font-medium mb-0.5">Activity Date</p>
                    <p className="font-bold text-foreground">{detailData.activity_date}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground font-medium mb-0.5">Contractor / Sub</p>
                    <p className="font-semibold text-foreground">{detailData.contractor || 'Direct Payroll'}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground font-medium mb-0.5">Reporting Source</p>
                    <p className="font-semibold text-foreground capitalize">{detailData.source}</p>
                  </div>
                  {detailData.started_at && (
                    <div className="col-span-2">
                      <p className="text-muted-foreground font-medium mb-0.5">Time Window</p>
                      <p className="font-semibold text-foreground font-mono">
                        {detailData.started_at}{detailData.ended_at ? ` \u2013 ${detailData.ended_at}` : ''}
                      </p>
                    </div>
                  )}
                </div>

                {/* Narrative */}
                {detailData.narrative && (
                  <div className="space-y-1.5">
                    <p className="font-bold text-foreground">Activity Narrative</p>
                    <div className="p-3.5 rounded-lg border border-border/60 bg-background leading-relaxed text-muted-foreground">
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
                      <Paperclip className="size-3.5" />Evidence ({detailData.attachments?.length || 0})
                    </TabsTrigger>
                    <TabsTrigger value="corrections" className="text-xs gap-1.5">
                      <ShieldAlert className="size-3.5" />Trail ({corrections.length})
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
                                <TableCell className="font-semibold">{q.work_type || 'Main Work'}</TableCell>
                                <TableCell className="capitalize text-muted-foreground">{q.measurement_type}</TableCell>
                                <TableCell className="text-right font-bold font-mono">{q.quantity} {q.unit || ''}</TableCell>
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
                      <div className="space-y-3 border-l-2 border-violet-500/30 pl-4 py-1 ml-2">
                        {detailData.progress_updates.map((upd) => {
                          const superseded = detailData.progress_updates.some((other) => other.supersedes_id === upd.id)
                          return (
                            <div key={upd.id} className={cn('relative space-y-1', superseded && 'opacity-50')}>
                              <div className="absolute -left-[21px] top-1 size-2.5 rounded-full bg-violet-500" />
                              <div className="flex items-center justify-between text-[11px] gap-2">
                                <span className="font-bold text-foreground capitalize">{upd.update_kind}</span>
                                <div className="flex items-center gap-1.5 shrink-0">
                                  <span className="text-muted-foreground font-mono">{new Date(upd.occurred_at).toLocaleString()}</span>
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
                                        className="text-muted-foreground hover:text-rose-500"
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
                                <Badge variant="outline" className="font-mono font-semibold text-[10px]">+{upd.quantity} {upd.unit || ''}</Badge>
                              )}
                              {upd.supersedes_id && (
                                <p className="text-[10px] text-amber-600 dark:text-amber-400">Corrects a previous entry</p>
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
                              <span className="font-bold text-foreground">{c.field_name}</span>
                              <span className="text-muted-foreground font-mono">{new Date(c.created_at).toLocaleString()}</span>
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

      {/* Correct Activity Details */}
      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="sm:max-w-[480px] gap-4">
          <DialogHeader>
            <DialogTitle className="text-sm font-bold">Correct Activity Details</DialogTitle>
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
            {editError && <p className="text-[11px] text-rose-500">{editError}</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setEditOpen(false)} disabled={editSaving}>
              Cancel
            </Button>
            <Button size="sm" onClick={saveEdit} disabled={editSaving}>
              {editSaving ? 'Saving…' : 'Save Correction'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Void Activity */}
      <Dialog open={voidActivityOpen} onOpenChange={setVoidActivityOpen}>
        <DialogContent className="sm:max-w-[440px] gap-4">
          <DialogHeader>
            <DialogTitle className="text-sm font-bold text-rose-600 dark:text-rose-400">Remove This Activity?</DialogTitle>
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
            {voidError && <p className="text-[11px] text-rose-500 mt-1">{voidError}</p>}
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
              {voidBusy ? 'Removing…' : 'Remove Activity'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Correct Progress Update */}
      <Dialog open={!!correctUpdateId} onOpenChange={(open) => !open && setCorrectUpdateId(null)}>
        <DialogContent className="sm:max-w-[420px] gap-4">
          <DialogHeader>
            <DialogTitle className="text-sm font-bold">Correct This Update</DialogTitle>
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
            {correctUpdateError && <p className="text-[11px] text-rose-500">{correctUpdateError}</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setCorrectUpdateId(null)} disabled={correctUpdateBusy}>
              Cancel
            </Button>
            <Button size="sm" onClick={saveCorrectUpdate} disabled={correctUpdateBusy}>
              {correctUpdateBusy ? 'Saving…' : 'Save Correction'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Void Progress Update */}
      <Dialog open={!!voidUpdateId} onOpenChange={(open) => !open && setVoidUpdateId(null)}>
        <DialogContent className="sm:max-w-[420px] gap-4">
          <DialogHeader>
            <DialogTitle className="text-sm font-bold text-rose-600 dark:text-rose-400">Remove This Update?</DialogTitle>
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
            {voidUpdateError && <p className="text-[11px] text-rose-500 mt-1">{voidUpdateError}</p>}
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
              {voidUpdateBusy ? 'Removing…' : 'Remove Update'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
