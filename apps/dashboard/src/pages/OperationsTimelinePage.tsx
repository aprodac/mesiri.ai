import * as React from 'react'
import {
  Activity,
  Search,
  Filter,
  RefreshCw,
  Calendar,
  Clock,
  CheckCircle2,
  ChevronRight,
  Download,
  Layers,
  HardHat,
  ShieldAlert,
  LayoutGrid,
  List,
  X,
  CalendarDays,
  DollarSign,
  Package,
  Sparkles,
  TrendingUp,
  User,
  Maximize2,
  Minimize2,
} from 'lucide-react'
import { useScope } from '@/lib/ScopeContext'
import { fetchTimelineEntriesApi } from '@/lib/api'
import { KpiCard } from '@/components/ui/kpi-card'
import { useToast } from '@/components/ui/toast-notification'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { cn, toLocalISODate } from '@/lib/utils'

// ─── Extended Timeline Entry Model ───────────────────────────────────────────

export interface EnrichedTimelineEntry {
  id: string
  projectId: string | null
  siteId: string | null
  eventType: string
  summary: string
  occurredAt: string
  category: 'progress' | 'finance' | 'workforce' | 'materials' | 'blocker' | 'system'
  actorName?: string
  actorRole?: string
  locationName?: string
  metricsTag?: string
  aiVisionCaption?: string
  payloadDetails?: Record<string, any>
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function getCategoryColor(category: string) {
  switch (category) {
    case 'progress':
      return {
        badge: 'bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 border-indigo-500/30',
        dot: 'bg-indigo-600 ring-indigo-500/30',
        icon: <Layers className="size-3.5 text-indigo-600 dark:text-indigo-400" />,
      }
    case 'finance':
      return {
        badge: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/30',
        dot: 'bg-emerald-600 ring-emerald-500/30',
        icon: <DollarSign className="size-3.5 text-emerald-600 dark:text-emerald-400" />,
      }
    case 'workforce':
      return {
        badge: 'bg-sky-500/10 text-sky-600 dark:text-sky-400 border-sky-500/30',
        dot: 'bg-sky-600 ring-sky-500/30',
        icon: <HardHat className="size-3.5 text-sky-600 dark:text-sky-400" />,
      }
    case 'materials':
      return {
        badge: 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/30',
        dot: 'bg-amber-600 ring-amber-500/30',
        icon: <Package className="size-3.5 text-amber-600 dark:text-amber-400" />,
      }
    case 'blocker':
      return {
        badge: 'bg-rose-500/10 text-rose-600 dark:text-rose-400 border-rose-500/30',
        dot: 'bg-rose-600 ring-rose-500/30',
        icon: <ShieldAlert className="size-3.5 text-rose-600 dark:text-rose-400" />,
      }
    default:
      return {
        badge: 'bg-zinc-500/10 text-zinc-600 dark:text-zinc-400 border-zinc-500/30',
        dot: 'bg-zinc-600 ring-zinc-500/30',
        icon: <Activity className="size-3.5 text-zinc-600 dark:text-zinc-400" />,
      }
  }
}

function deriveCategory(eventType: string): EnrichedTimelineEntry['category'] {
  const t = eventType.toUpperCase()
  if (t.includes('DPR') || t.includes('PROGRESS') || t.includes('ACTIVITY')) return 'progress'
  if (t.includes('EXPENSE') || t.includes('FINANCE') || t.includes('VOUCHER') || t.includes('TRANSFER')) return 'finance'
  if (t.includes('WORKFORCE') || t.includes('LABOUR') || t.includes('ATTENDANCE') || t.includes('WORKER')) return 'workforce'
  if (t.includes('MATERIAL') || t.includes('INVENTORY') || t.includes('RECEIPT')) return 'materials'
  if (t.includes('BLOCKER') || t.includes('ISSUE') || t.includes('WEATHER') || t.includes('DELAY')) return 'blocker'
  return 'system'
}

// ─── Main Operations Timeline Page ─────────────────────────────────────────────

export default function OperationsTimelinePage() {
  const { scope } = useScope()
  const toast = useToast()

  const [entries, setEntries] = React.useState<EnrichedTimelineEntry[]>([])
  const [loading, setLoading] = React.useState<boolean>(true)
  const [liveStreamActive, setLiveStreamActive] = React.useState<boolean>(true)
  const [isFullView, setIsFullView] = React.useState<boolean>(false)

  // Filters
  const [searchQuery, setSearchQuery] = React.useState<string>('')
  const [categoryFilter, setCategoryFilter] = React.useState<string>('ALL')
  const [datePreset, setDatePreset] = React.useState<string>('ALL')
  const [dateFrom, setDateFrom] = React.useState<string>('')
  const [dateTo, setDateTo] = React.useState<string>('')
  const [viewMode, setViewMode] = React.useState<'stream' | 'matrix' | 'heatmap'>('stream')

  // Selected event for detail sheet
  const [selectedEntry, setSelectedEntry] = React.useState<EnrichedTimelineEntry | null>(null)

  const currentSiteName = React.useMemo(() => {
    if (scope.mode === 'site') return scope.siteName
    return 'Active Site'
  }, [scope])

  const scopeFilter = React.useMemo(() => ({
    projectId: scope.mode !== 'portfolio' ? scope.projectId : undefined,
    siteId: scope.mode === 'site' ? scope.siteId : undefined,
  }), [scope])

  const loadTimeline = React.useCallback(async () => {
    setLoading(true)
    try {
      // Note: categoryFilter is a client-derived label (progress/finance/workforce/...), not a
      // real backend event_type value, so it is applied via deriveCategory() below rather than
      // sent to the API as an exact-match eventType filter.
      const res = await fetchTimelineEntriesApi({
        projectId: scopeFilter.projectId,
        siteId: scopeFilter.siteId,
        dateFrom: dateFrom || undefined,
        dateTo: dateTo || undefined,
        limit: 100,
      })

      if (res && res.items) {
        const enriched: EnrichedTimelineEntry[] = res.items.map((e) => ({
          id: e.id,
          projectId: e.project_id,
          siteId: e.site_id,
          eventType: e.event_type,
          summary: e.summary,
          occurredAt: e.occurred_at,
          category: deriveCategory(e.event_type),
          actorName: 'Site System',
          locationName: currentSiteName,
          payloadDetails: e.payload,
        }))
        setEntries(enriched)
      } else {
        setEntries([])
      }
    } catch {
      setEntries([])
    } finally {
      setLoading(false)
    }
  }, [scopeFilter, dateFrom, dateTo, currentSiteName])

  React.useEffect(() => {
    loadTimeline()
  }, [loadTimeline])

  // Live Auto-Refresh polling
  React.useEffect(() => {
    if (!liveStreamActive) return
    const interval = setInterval(() => {
      fetchTimelineEntriesApi({
        projectId: scopeFilter.projectId,
        siteId: scopeFilter.siteId,
        limit: 10,
      }).then((res) => {
        if (res && res.items) {
          const enriched: EnrichedTimelineEntry[] = res.items.map((e) => ({
            id: e.id,
            projectId: e.project_id,
            siteId: e.site_id,
            eventType: e.event_type,
            summary: e.summary,
            occurredAt: e.occurred_at,
            category: deriveCategory(e.event_type),
            actorName: 'Site System',
            locationName: currentSiteName,
            payloadDetails: e.payload,
          }))
          setEntries((prev) => {
            const existingIds = new Set(prev.map((item) => item.id))
            const newItems = enriched.filter((item) => !existingIds.has(item.id))
            return [...newItems, ...prev]
          })
        }
      }).catch(() => {})
    }, 15000)
    return () => clearInterval(interval)
  }, [liveStreamActive, scopeFilter, currentSiteName])

  // Filtered timeline entries
  const filteredEntries = React.useMemo(() => {
    return entries.filter((item) => {
      if (categoryFilter !== 'ALL' && item.category !== categoryFilter.toLowerCase()) {
        return false
      }
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase()
        const match =
          item.eventType.toLowerCase().includes(q) ||
          item.summary.toLowerCase().includes(q) ||
          (item.actorName || '').toLowerCase().includes(q) ||
          (item.locationName || '').toLowerCase().includes(q) ||
          (item.metricsTag || '').toLowerCase().includes(q)
        if (!match) return false
      }
      if (dateFrom && item.occurredAt < dateFrom) return false
      if (dateTo && item.occurredAt > dateTo) return false
      return true
    })
  }, [entries, categoryFilter, searchQuery, dateFrom, dateTo])

  // Group entries by Date for Stream View
  const groupedEntries = React.useMemo(() => {
    const groups: Record<string, EnrichedTimelineEntry[]> = {}
    filteredEntries.forEach((item) => {
      const day = item.occurredAt.split('T')[0]
      if (!groups[day]) groups[day] = []
      groups[day].push(item)
    })
    return groups
  }, [filteredEntries])

  // Real Matrix View Computation from backend data
  const matrixGrouped = React.useMemo(() => {
    const packages: Record<string, EnrichedTimelineEntry[]> = {}
    filteredEntries.forEach((item) => {
      const pkg = item.category.toUpperCase()
      if (!packages[pkg]) packages[pkg] = []
      packages[pkg].push(item)
    })
    return packages
  }, [filteredEntries])

  // Real Density Heatmap View Computation from backend data
  const densityHeatmap = React.useMemo(() => {
    const counts: Record<string, number> = {}
    filteredEntries.forEach((item) => {
      const day = item.occurredAt.split('T')[0]
      counts[day] = (counts[day] || 0) + 1
    })
    return counts
  }, [filteredEntries])

  // KPI Metrics
  const stats = React.useMemo(() => {
    const totalEvents = entries.length
    const progressCount = entries.filter((e) => e.category === 'progress').length
    const financeCount = entries.filter((e) => e.category === 'finance').length
    const blockersCount = entries.filter((e) => e.category === 'blocker').length
    const aiCount = entries.filter((e) => Boolean(e.aiVisionCaption)).length

    return { totalEvents, progressCount, financeCount, blockersCount, aiCount }
  }, [entries])

  const scopeLabel = React.useMemo(() => {
    if (scope.mode === 'portfolio') return 'Portfolio Scope (All Projects)'
    if (scope.mode === 'project') return `Project Scope: ${scope.projectName}`
    return `Site Scope: ${scope.projectName} / ${scope.siteName}`
  }, [scope])

  const resetFilters = () => {
    setCategoryFilter('ALL')
    setDatePreset('ALL')
    setDateFrom('')
    setDateTo('')
    setSearchQuery('')
  }

  const hasActiveFilters = categoryFilter !== 'ALL' || datePreset !== 'ALL' || !!dateFrom || !!dateTo || !!searchQuery

  return (
    <div className={cn(
      "flex flex-col gap-4 w-full max-w-full relative pb-12 transition-all",
      isFullView && "fixed inset-0 z-50 bg-background/98 backdrop-blur-2xl p-6 overflow-y-auto pb-16"
    )}>

      {/* ── Page Header (Hidden in Full View Mode for pure stream experience) ── */}
      {!isFullView ? (
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b pb-3.5">
          <div className="flex items-center gap-3">
            <div className="size-10 rounded-lg border border-indigo-500/30 bg-indigo-500/10 flex items-center justify-center text-indigo-600 dark:text-indigo-400 shrink-0 shadow-2xs">
              <Activity className="size-5" />
            </div>
            <div>
              <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2">
                Site Operations Timeline
                <Badge variant="outline" className="text-[10px] font-mono border-indigo-500/30 text-indigo-600 dark:text-indigo-400">
                  Real-Time Event Stream
                </Badge>
              </h1>
              <p className="text-xs text-muted-foreground font-medium">{scopeLabel}</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Full View Toggle Button */}
            <Button
              size="sm"
              variant="outline"
              className="h-8 gap-1.5 text-xs font-bold shadow-2xs border-indigo-500/30 text-indigo-600 dark:text-indigo-400 hover:bg-indigo-500/10"
              onClick={() => {
                setIsFullView(true)
                toast.info('Entered Full View Stream', 'Distraction-free event stream mode')
              }}
            >
              <Maximize2 className="size-3.5" />
              Full View
            </Button>

            {/* Live Auto-Refresh Stream Toggle */}
            <Button
              size="sm"
              variant="outline"
              className={cn(
                'h-8 gap-1.5 text-xs font-semibold border transition-all',
                liveStreamActive
                  ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/30'
                  : 'text-muted-foreground'
              )}
              onClick={() => {
                setLiveStreamActive((prev) => !prev)
                toast.info('Live Stream Updated', liveStreamActive ? 'Paused auto-refresh' : 'Enabled live stream auto-refresh')
              }}
            >
              <span className={cn('size-2 rounded-full', liveStreamActive ? 'bg-emerald-500 animate-pulse' : 'bg-zinc-400')} />
              {liveStreamActive ? 'Live Stream Active' : 'Stream Paused'}
            </Button>

            <Button
              size="sm"
              variant="outline"
              className="h-8 gap-1.5 text-xs font-medium"
              onClick={() => toast.info('Exporting Event Ledger', 'Downloading CSV timeline log')}
            >
              <Download className="size-3.5" />
              Export Log
            </Button>

            <Button
              variant="outline"
              size="sm"
              onClick={loadTimeline}
              disabled={loading}
              className="h-8 gap-1.5 text-xs"
            >
              <RefreshCw className={cn('size-3.5', loading && 'animate-spin')} />
              Refresh
            </Button>
          </div>
        </div>
      ) : (
        /* Full View Floating Control Bar */
        <div className="sticky top-0 z-50 flex items-center justify-between gap-3 p-3 rounded-xl border border-indigo-500/30 bg-card/95 shadow-2xl backdrop-blur-xl mb-2">
          <div className="flex items-center gap-2.5">
            <div className="size-7 rounded-md bg-indigo-500/10 border border-indigo-500/30 flex items-center justify-center text-indigo-600">
              <Activity className="size-4" />
            </div>
            <span className="font-bold text-xs text-foreground font-mono">Operations Feed (Full Screen Stream)</span>
            <span className="text-[11px] text-muted-foreground">· {filteredEntries.length} Events</span>
          </div>

          <div className="flex items-center gap-2">
            <Select value={categoryFilter} onValueChange={setCategoryFilter}>
              <SelectTrigger className="h-7 text-xs w-36 bg-background">
                <SelectValue placeholder="All Categories" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ALL">All Categories</SelectItem>
                <SelectItem value="PROGRESS">🏗️ Progress</SelectItem>
                <SelectItem value="FINANCE">💰 Finance</SelectItem>
                <SelectItem value="WORKFORCE">👷 Workforce</SelectItem>
                <SelectItem value="MATERIALS">📦 Materials</SelectItem>
                <SelectItem value="BLOCKER">⚠️ Delays</SelectItem>
              </SelectContent>
            </Select>

            <Button
              size="sm"
              variant="default"
              className="h-7 text-xs font-bold bg-indigo-600 text-white hover:bg-indigo-700 gap-1.5"
              onClick={() => {
                setIsFullView(false)
                toast.info('Exited Full View', 'Returned to standard layout')
              }}
            >
              <Minimize2 className="size-3.5" />
              Exit Full View
            </Button>
          </div>
        </div>
      )}

      {/* ── Executive KPI Cards (Hidden in Full View Mode) ── */}
      {!isFullView && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <KpiCard
            title="Total Events Logged"
            value={<span className="text-indigo-600 dark:text-indigo-400">{stats.totalEvents}</span>}
            trend="up"
            trendValue="Real-time Stream"
            description="Operational timeline events"
            icon={<Activity className="text-indigo-500" />}
            chartData={[10, 15, 22, 28, 35, 42, 50, 65]}
          />
          <KpiCard
            title="Progress Milestones"
            value={<span className="text-emerald-600 dark:text-emerald-400">{stats.progressCount}</span>}
            trend="up"
            trendValue="Executed & Signed"
            description="Approved site DPRs & pours"
            icon={<CheckCircle2 className="text-emerald-500" />}
            chartData={[4, 8, 12, 16, 20, 24, 28, 32]}
          />
          <KpiCard
            title="Financial Vouchers"
            value={<span className="text-sky-600 dark:text-sky-400">{stats.financeCount}</span>}
            trend="neutral"
            trendValue="Approved Invoices"
            description="Site vouchers & petty cash"
            icon={<DollarSign className="text-sky-500" />}
            chartData={[3, 5, 8, 10, 12, 15, 18, 22]}
          />
          <KpiCard
            title="Flagged Delays"
            value={<span className="text-rose-600 dark:text-rose-400">{stats.blockersCount}</span>}
            trend={stats.blockersCount > 0 ? 'down' : 'neutral'}
            trendValue={`${stats.aiCount} AI Vision Audits`}
            description="Site interruptions logged"
            icon={<ShieldAlert className="text-rose-500" />}
            chartData={[2, 4, 1, 3, 2, 1, 2, 1]}
          />
        </div>
      )}

      {/* ── Toolbar: Search, Filters & View Switcher (Hidden in Full View Mode) ── */}
      {!isFullView && (
        <div className="flex flex-col gap-2 border border-border/80 p-2.5 rounded-lg bg-card/40">
          <div className="flex flex-col sm:flex-row gap-2.5 items-center justify-between">
            <div className="flex flex-wrap gap-2 w-full sm:w-auto flex-1 items-center">
              {/* Search */}
              <div className="relative w-full sm:w-64">
                <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
                <Input
                  placeholder="Search event type, summary, author..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-8 h-9 text-xs"
                />
              </div>

              {/* Category Select */}
              <Select value={categoryFilter} onValueChange={setCategoryFilter}>
                <SelectTrigger className="h-9 text-xs w-full sm:w-40">
                  <Filter className="size-3.5 mr-1.5 text-muted-foreground shrink-0" />
                  <SelectValue placeholder="All Categories" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ALL">All Categories</SelectItem>
                  <SelectItem value="PROGRESS">🏗️ Site Progress</SelectItem>
                  <SelectItem value="FINANCE">💰 Finance & Expenses</SelectItem>
                  <SelectItem value="WORKFORCE">👷 Workforce & Labour</SelectItem>
                  <SelectItem value="MATERIALS">📦 Materials Ledger</SelectItem>
                  <SelectItem value="BLOCKER">⚠️ Delays & Blockers</SelectItem>
                </SelectContent>
              </Select>

              {/* Date Preset */}
              <Select value={datePreset} onValueChange={(val) => {
                setDatePreset(val)
                const now = new Date()
                if (val === 'ALL') { setDateFrom(''); setDateTo('') }
                else if (val === 'TODAY') {
                  const todayStr = toLocalISODate(now)
                  setDateFrom(todayStr); setDateTo(todayStr)
                } else if (val === 'THIS_WEEK') {
                  const lastWeek = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000)
                  setDateFrom(toLocalISODate(lastWeek))
                  setDateTo(toLocalISODate(now))
                }
              }}>
                <SelectTrigger className="h-9 text-xs w-full sm:w-36">
                  <Calendar className="size-3.5 mr-1.5 text-muted-foreground shrink-0" />
                  <SelectValue placeholder="All Time" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ALL">All Time</SelectItem>
                  <SelectItem value="TODAY">Today</SelectItem>
                  <SelectItem value="THIS_WEEK">This Week</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* View Switcher */}
            <div className="flex items-center gap-1 border border-border/80 rounded-md p-0.5 bg-background shrink-0">
              <Button
                variant={viewMode === 'stream' ? 'secondary' : 'ghost'}
                size="sm"
                className="h-7 px-2.5 text-xs font-semibold gap-1"
                onClick={() => setViewMode('stream')}
              >
                <List className="size-3.5" />
                Stream
              </Button>
              <Button
                variant={viewMode === 'matrix' ? 'secondary' : 'ghost'}
                size="sm"
                className="h-7 px-2.5 text-xs font-semibold gap-1"
                onClick={() => setViewMode('matrix')}
              >
                <LayoutGrid className="size-3.5" />
                Matrix
              </Button>
              <Button
                variant={viewMode === 'heatmap' ? 'secondary' : 'ghost'}
                size="sm"
                className="h-7 px-2.5 text-xs font-semibold gap-1"
                onClick={() => setViewMode('heatmap')}
              >
                <CalendarDays className="size-3.5" />
                Density
              </Button>
            </div>
          </div>

          {/* Active Filter Chips */}
          {hasActiveFilters && (
            <div className="flex items-center gap-2 pt-1 text-xs border-t border-border/40 flex-wrap">
              <span className="text-muted-foreground font-semibold text-[11px]">Active Filters:</span>
              {categoryFilter !== 'ALL' && (
                <Badge variant="secondary" className="gap-1 text-[10px]">
                  Category: {categoryFilter}
                  <X className="size-3 cursor-pointer hover:opacity-80" onClick={() => setCategoryFilter('ALL')} />
                </Badge>
              )}
              {searchQuery && (
                <Badge variant="secondary" className="gap-1 text-[10px]">
                  Query: "{searchQuery}"
                  <X className="size-3 cursor-pointer hover:opacity-80" onClick={() => setSearchQuery('')} />
                </Badge>
              )}
              <Button variant="ghost" size="sm" onClick={resetFilters} className="h-5 text-[10px] text-muted-foreground hover:text-foreground p-0 ml-auto">
                Reset All
              </Button>
            </div>
          )}
        </div>
      )}

      {/* ── Stream View: Chronological Timeline Feed ── */}
      {viewMode === 'stream' ? (
        <div className="space-y-6">
          {Object.keys(groupedEntries).length === 0 ? (
            <Card className="p-12 text-center flex flex-col items-center justify-center gap-3">
              <div className="size-12 rounded-full bg-muted border flex items-center justify-center">
                <Activity className="size-5 text-muted-foreground/50" />
              </div>
              <div>
                <p className="text-sm font-semibold text-foreground">No operational events recorded in backend</p>
                <p className="text-xs text-muted-foreground mt-1">Events will appear live as DPRs are submitted, expenses recorded, and site activities logged.</p>
              </div>
              {hasActiveFilters && (
                <Button variant="outline" size="sm" onClick={resetFilters} className="text-xs h-8 mt-1">
                  Clear Filters
                </Button>
              )}
            </Card>
          ) : (
            Object.entries(groupedEntries).map(([dateStr, dateEntries]) => (
              <div key={dateStr} className="space-y-3">

                {/* Day Header Badge */}
                <div className="sticky top-12 z-10 flex items-center gap-2 py-1 bg-background/90 backdrop-blur-md">
                  <Badge variant="outline" className="bg-card shadow-2xs font-mono font-bold text-xs py-1 px-3 border-indigo-500/30 text-indigo-600 dark:text-indigo-400 gap-1.5">
                    <Calendar className="size-3.5" />
                    {dateStr === toLocalISODate() ? `Today — ${dateStr}` : dateStr}
                  </Badge>
                  <div className="h-px flex-1 bg-border/60" />
                  <span className="text-[11px] font-mono text-muted-foreground font-semibold">
                    {dateEntries.length} Events Logged
                  </span>
                </div>

                {/* Timeline Stream Spine Container */}
                <div className="relative pl-6 space-y-3 before:absolute before:left-2.5 before:top-2 before:bottom-2 before:w-0.5 before:bg-border/80">
                  {dateEntries.map((item) => {
                    const style = getCategoryColor(item.category)
                    const timeStr = new Date(item.occurredAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })

                    return (
                      <div key={item.id} className="relative group">

                        {/* Node Avatar Icon Dot */}
                        <div
                          className={cn(
                            'absolute -left-6 top-3 size-5 rounded-full border-2 border-background flex items-center justify-center shadow-2xs transition-transform group-hover:scale-125 z-10',
                            style.dot
                          )}
                        />

                        {/* Event Card */}
                        <div
                          onClick={() => setSelectedEntry(item)}
                          className={cn(
                            "p-3.5 rounded-lg border border-border/80 bg-card hover:border-indigo-500/40 hover:shadow-md transition-all cursor-pointer space-y-2",
                            isFullView && "p-5 border-border/90 shadow-sm"
                          )}
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="flex items-center gap-2 flex-wrap">
                              <Badge variant="outline" className={cn('text-[10px] font-bold uppercase gap-1', style.badge)}>
                                {style.icon}
                                {item.category}
                              </Badge>
                              <span className={cn("font-mono text-xs font-bold text-foreground", isFullView && "text-sm")}>
                                {item.eventType}
                              </span>
                              {item.metricsTag && (
                                <Badge variant="secondary" className="text-[10px] font-mono font-bold">
                                  {item.metricsTag}
                                </Badge>
                              )}
                            </div>

                            <div className="flex items-center gap-1.5 text-muted-foreground text-[11px] font-mono shrink-0">
                              <Clock className="size-3" />
                              <span>{timeStr}</span>
                            </div>
                          </div>

                          {/* Event Summary */}
                          <p className={cn("text-xs text-foreground leading-relaxed font-medium", isFullView && "text-sm leading-relaxed")}>
                            {item.summary}
                          </p>

                          {/* AI Vision Caption Badge */}
                          {item.aiVisionCaption && (
                            <div className="p-2 rounded-md bg-indigo-500/5 border border-indigo-500/20 flex items-center gap-2 text-[11px] text-indigo-700 dark:text-indigo-300 font-medium">
                              <Sparkles className="size-3.5 text-indigo-500 shrink-0" />
                              <span className="italic">{item.aiVisionCaption}</span>
                            </div>
                          )}

                          {/* Footer Meta Row */}
                          <div className="flex items-center justify-between text-[11px] text-muted-foreground pt-1 border-t border-border/40 font-mono">
                            <div className="flex items-center gap-3">
                              {item.actorName && (
                                <span className="flex items-center gap-1">
                                  <User className="size-3 text-muted-foreground" />
                                  <strong className="text-foreground">{item.actorName}</strong>
                                </span>
                              )}
                              {item.locationName && (
                                <span className="text-muted-foreground/80">
                                  📍 {item.locationName}
                                </span>
                              )}
                            </div>

                            <span className="text-indigo-600 font-semibold group-hover:translate-x-0.5 transition-transform flex items-center gap-0.5">
                              Inspect <ChevronRight className="size-3" />
                            </span>
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            ))
          )}
        </div>
      ) : viewMode === 'matrix' ? (
        /* Real Data-Driven Milestone Matrix View */
        Object.keys(matrixGrouped).length === 0 ? (
          <Card className="p-12 text-center flex flex-col items-center justify-center gap-3">
            <div className="size-12 rounded-full bg-muted border flex items-center justify-center">
              <Layers className="size-5 text-muted-foreground/50" />
            </div>
            <div>
              <p className="text-sm font-semibold text-foreground">No category matrix items found in backend</p>
              <p className="text-xs text-muted-foreground mt-1">Matrix packages will populate as real events are recorded.</p>
            </div>
          </Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {Object.entries(matrixGrouped).map(([categoryName, catEntries]) => {
              const style = getCategoryColor(categoryName.toLowerCase())
              return (
                <Card key={categoryName} className="rounded-lg border-border/80 shadow-2xs">
                  <CardHeader className="pb-3 border-b bg-muted/10">
                    <CardTitle className="text-sm font-bold flex items-center justify-between">
                      <span className="flex items-center gap-2">
                        {style.icon}
                        {categoryName} Package Ledger
                      </span>
                      <Badge variant="outline" className="font-mono text-[10px] text-indigo-600">
                        {catEntries.length} Recorded
                      </Badge>
                    </CardTitle>
                    <CardDescription className="text-xs">
                      Live event stream entries grouped by operational module category
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="pt-3 space-y-3 text-xs">
                    <div className="space-y-2">
                      {catEntries.slice(0, 3).map((item) => (
                        <div key={item.id} className="p-2 rounded-md bg-muted/20 border text-[11px] space-y-1">
                          <div className="flex items-center justify-between font-bold">
                            <span className="font-mono text-foreground">{item.eventType}</span>
                            <span className="text-muted-foreground text-[10px]">
                              {new Date(item.occurredAt).toLocaleDateString()}
                            </span>
                          </div>
                          <p className="text-muted-foreground line-clamp-1">{item.summary}</p>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )
            })}
          </div>
        )
      ) : (
        /* Real Data-Driven Event Density Heatmap View */
        <Card className="rounded-lg border-border/80 p-6 space-y-4 shadow-2xs">
          <div className="flex items-center justify-between border-b pb-3">
            <div>
              <h2 className="text-sm font-bold text-foreground flex items-center gap-2">
                <TrendingUp className="size-4 text-indigo-600" />
                Live Event Activity Density
              </h2>
              <p className="text-xs text-muted-foreground">Recorded event volume per day from backend</p>
            </div>
            <Badge variant="outline" className="font-mono text-xs">{filteredEntries.length} Total Events</Badge>
          </div>

          {Object.keys(densityHeatmap).length === 0 ? (
            <div className="p-8 text-center text-xs text-muted-foreground">
              No daily event activity recorded in database yet.
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3 text-xs font-mono">
              {Object.entries(densityHeatmap).map(([dayStr, count]) => (
                <div
                  key={dayStr}
                  className="p-3 rounded-lg border border-indigo-500/30 bg-indigo-500/10 flex items-center justify-between shadow-2xs"
                >
                  <div>
                    <span className="font-bold text-foreground block">{dayStr}</span>
                    <span className="text-[10px] text-muted-foreground">Operational Entries</span>
                  </div>
                  <Badge variant="secondary" className="font-bold text-indigo-600 text-xs">
                    {count} {count === 1 ? 'evt' : 'evts'}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      {/* ── Slide-out Event Inspection Sheet ── */}
      <Sheet open={!!selectedEntry} onOpenChange={(open) => !open && setSelectedEntry(null)}>
        <SheetContent className="sm:max-w-md overflow-y-auto w-full p-0">
          <SheetHeader className="px-6 pt-5 pb-4 border-b bg-muted/20 shrink-0">
            <div className="flex items-center gap-2.5">
              <div className="size-9 rounded-lg bg-indigo-500/10 border border-indigo-500/30 flex items-center justify-center shrink-0">
                <Activity className="size-4 text-indigo-600 dark:text-indigo-400" />
              </div>
              <div>
                <SheetTitle className="text-sm font-bold flex items-center gap-2">
                  {selectedEntry?.eventType || 'Timeline Event'}
                </SheetTitle>
                <SheetDescription className="text-[11px] mt-0.5">
                  ID: {selectedEntry?.id}
                </SheetDescription>
              </div>
            </div>
          </SheetHeader>

          <div className="p-6 space-y-4 text-xs">
            {selectedEntry && (
              <>
                <div className="p-3.5 rounded-lg border border-border/70 bg-muted/10 space-y-2">
                  <span className="font-bold text-foreground block">Event Summary</span>
                  <p className="text-muted-foreground leading-relaxed">{selectedEntry.summary}</p>
                </div>

                <div className="grid grid-cols-2 gap-3 p-3 rounded-lg border border-border/70">
                  <div>
                    <span className="text-muted-foreground block text-[11px]">Occurred At</span>
                    <span className="font-bold font-mono text-foreground">
                      {new Date(selectedEntry.occurredAt).toLocaleString()}
                    </span>
                  </div>
                  <div>
                    <span className="text-muted-foreground block text-[11px]">Category</span>
                    <Badge variant="outline" className="text-[10px] font-bold uppercase mt-0.5">
                      {selectedEntry.category}
                    </Badge>
                  </div>
                </div>

                {selectedEntry.aiVisionCaption && (
                  <div className="p-3.5 rounded-lg border border-indigo-500/30 bg-indigo-500/10 space-y-1">
                    <span className="font-bold text-indigo-700 dark:text-indigo-300 flex items-center gap-1.5">
                      <Sparkles className="size-3.5 text-indigo-500" /> AI Vision Inspection Audit
                    </span>
                    <p className="text-indigo-900 dark:text-indigo-200 text-xs">{selectedEntry.aiVisionCaption}</p>
                  </div>
                )}

                {selectedEntry.payloadDetails && (
                  <div className="space-y-1">
                    <span className="font-bold text-foreground block">Payload Parameters</span>
                    <pre className="p-3 rounded-lg border border-border/80 bg-zinc-950 text-zinc-100 font-mono text-[11px] overflow-x-auto">
                      {JSON.stringify(selectedEntry.payloadDetails, null, 2)}
                    </pre>
                  </div>
                )}
              </>
            )}
          </div>
        </SheetContent>
      </Sheet>
    </div>
  )
}
