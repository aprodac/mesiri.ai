import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { ShieldAlert, Search, Plus, RefreshCw, CheckCircle2, Check } from 'lucide-react'
import { useScope } from '@/lib/ScopeContext'
import {
  fetchSiteIssuesApi,
  createSiteIssueApi,
  resolveSiteIssueApi,
  acknowledgeSiteIssueApi,
  wontFixSiteIssueApi,
  type SiteIssueItem,
} from '@/lib/api'
import { useToast } from '@/components/ui/toast-notification'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'
import { fetchSites } from '@/lib/projects'

// ─── Helpers ──────────────────────────────────────────────────────────────────

const CHIP = 'inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold whitespace-nowrap'

// Severity, using the V1 status tokens (WEB-07). Critical is the only red.
function getSeverityBadge(severity: string) {
  switch (severity.toUpperCase()) {
    case 'CRITICAL':
      return <span className={cn(CHIP, 'bg-destructive/10 text-destructive')}>Critical</span>
    case 'HIGH':
      return <span className={cn(CHIP, 'bg-draft-soft text-draft')}>High</span>
    case 'MEDIUM':
      return <span className={cn(CHIP, 'bg-info-soft text-info')}>Medium</span>
    default:
      return <span className={cn(CHIP, 'bg-muted text-muted-foreground')}>Low</span>
  }
}

// A status nobody is waiting on any more. CANCELLED means the report was
// withdrawn as a mistake, which is deliberately NOT the same as RESOLVED --
// see migration 0460 -- but it is equally not an open blocker.
const CLOSED_ISSUE_STATUSES = ['RESOLVED', 'WONT_FIX', 'CANCELLED']

function isClosed(status: string) {
  return CLOSED_ISSUE_STATUSES.includes(status.toUpperCase())
}

function getStatusBadge(status: string) {
  switch (status.toUpperCase()) {
    case 'RESOLVED':
      return <span className={cn(CHIP, 'bg-success-soft text-success')}><Check className="size-3" />Resolved</span>
    case 'ACKNOWLEDGED':
      return <span className={cn(CHIP, 'bg-info-soft text-info')}>Acknowledged</span>
    case 'WONT_FIX':
      return <span className={cn(CHIP, 'bg-muted text-muted-foreground')}>Won't fix</span>
    // Muted rather than coloured: a withdrawn report is not an outcome, and
    // giving it the "done" treatment would read as work completed.
    case 'CANCELLED':
      return <span className={cn(CHIP, 'bg-muted text-muted-foreground opacity-70')}>Withdrawn</span>
    default:
      return <span className={cn(CHIP, 'bg-draft-soft text-draft')}>Open</span>
  }
}

// The default view: everything not closed (OPEN + ACKNOWLEDGED). Fetched
// unfiltered and narrowed here, since the API takes a single status.
const ACTIVE_FILTER = 'ACTIVE'

const SEVERITY_RANK: Record<string, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 }

function humanizeIssueType(issueType: string): string {
  const words = issueType.toLowerCase().replace(/_/g, ' ').trim()
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : 'Issue'
}

function formatDuration(minutes: number): string {
  if (minutes <= 0) return '0 min'
  if (minutes < 60) return `${minutes} min`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest ? `${hours} h ${rest} min` : `${hours} h`
}

/** How long an issue has been open, from when it happened. */
function openFor(occurredAt: string): string {
  const ms = Date.now() - new Date(occurredAt).getTime()
  const hours = Math.floor(ms / 3_600_000)
  if (hours < 1) return 'Under an hour'
  if (hours < 24) return `${hours} h`
  const days = Math.floor(hours / 24)
  return days === 1 ? '1 day' : `${days} days`
}

// ─── Main Operations Issues Page ───────────────────────────────────────────────

export default function OperationsIssuesPage() {
  const { scope } = useScope()
  const toast = useToast()

  const [issues, setIssues] = React.useState<SiteIssueItem[]>([])
  // The server's count of every matching issue. `issues` holds one page
  // (limit 100), so counting that array under-reports the moment a site
  // passes 100 issues -- silently, and only on the busiest sites.
  const [totalCount, setTotalCount] = React.useState<number>(0)
  const [loading, setLoading] = React.useState<boolean>(true)

  // Filters
  const [searchQuery, setSearchQuery] = React.useState<string>('')
  const [statusFilter, setStatusFilter] = React.useState<string>(ACTIVE_FILTER)
  const [severityFilter, setSeverityFilter] = React.useState<string>('ALL')

  // Modals
  const [createDialogOpen, setCreateDialogOpen] = React.useState<boolean>(false)
  const [resolveDialogOpen, setResolveDialogOpen] = React.useState<boolean>(false)
  const [wontFixDialogOpen, setWontFixDialogOpen] = React.useState<boolean>(false)
  const [selectedIssue, setSelectedIssue] = React.useState<SiteIssueItem | null>(null)
  const [inspectSheetOpen, setInspectSheetOpen] = React.useState<boolean>(false)

  // Form states
  const [newIssueType, setNewIssueType] = React.useState<string>('OTHER')
  const [newSeverity, setNewSeverity] = React.useState<string>('MEDIUM')
  const [newNarrative, setNewNarrative] = React.useState<string>('')
  const [newDelayMins, setNewDelayMins] = React.useState<string>('30')
  const [submitting, setSubmitting] = React.useState<boolean>(false)
  const [resolutionNotes, setResolutionNotes] = React.useState<string>('')

  const activeProjectId = React.useMemo(() => {
    return scope.mode !== 'portfolio' ? scope.projectId : undefined
  }, [scope])

  const activeSiteId = React.useMemo(() => {
    return scope.mode === 'site' ? scope.siteId : undefined
  }, [scope])

  const scopeFilter = React.useMemo(() => ({
    projectId: activeProjectId,
    siteId: activeSiteId,
  }), [activeProjectId, activeSiteId])

  const loadIssues = React.useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchSiteIssuesApi({
        projectId: scopeFilter.projectId,
        siteId: scopeFilter.siteId,
        status: statusFilter !== 'ALL' && statusFilter !== ACTIVE_FILTER ? statusFilter : undefined,
        severity: severityFilter !== 'ALL' ? severityFilter : undefined,
        limit: 100,
      })
      setIssues(res.items || [])
      setTotalCount(res.total ?? (res.items || []).length)
    } catch {
      setIssues([])
      setTotalCount(0)
    } finally {
      setLoading(false)
    }
  }, [scopeFilter, statusFilter, severityFilter])

  React.useEffect(() => {
    loadIssues()
  }, [loadIssues])

  // Status "Open (not closed)", search, then the owner's order: most severe
  // first, and within a severity the longest-open first (WEB-07).
  const filteredIssues = React.useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    return issues
      .filter((item) => statusFilter !== ACTIVE_FILTER || !isClosed(item.status))
      .filter(
        (item) =>
          !q ||
          item.issue_type.toLowerCase().includes(q) ||
          (item.narrative || '').toLowerCase().includes(q) ||
          (item.resolution_notes || '').toLowerCase().includes(q)
      )
      .sort((a, b) => {
        const bySeverity =
          (SEVERITY_RANK[a.severity.toUpperCase()] ?? 9) - (SEVERITY_RANK[b.severity.toUpperCase()] ?? 9)
        if (bySeverity !== 0) return bySeverity
        return new Date(a.occurred_at).getTime() - new Date(b.occurred_at).getTime()
      })
  }, [issues, searchQuery, statusFilter])

  const stats = React.useMemo(() => {
    // Every non-closed status counts as open: WONT_FIX and CANCELLED are
    // settled too, and counting them would overstate what is blocking work.
    const open = issues.filter((i) => !isClosed(i.status))
    return {
      openCount: open.length,
      urgentOpenCount: open.filter((i) => ['CRITICAL', 'HIGH'].includes(i.severity.toUpperCase())).length,
      openMinutesLost: open.reduce((acc, i) => acc + (i.delay_duration_minutes || 0), 0),
    }
  }, [issues])

  // Site names: the issues API returns ids only. One sites call per project
  // that appears in the list, cached by react-query.
  const projectIdsInList = React.useMemo(
    () => Array.from(new Set(issues.map((i) => i.project_id))).sort(),
    [issues]
  )
  const { data: siteNames = {} } = useQuery<Record<string, string>>({
    queryKey: ['issue-site-names', projectIdsInList],
    enabled: projectIdsInList.length > 0,
    queryFn: async () => {
      const perProject = await Promise.all(
        projectIdsInList.map((projectId) => fetchSites(projectId).catch(() => []))
      )
      const names: Record<string, string> = {}
      for (const sites of perProject) {
        for (const site of sites) names[site.id] = site.name
      }
      return names
    },
  })
  const siteLabel = (item: SiteIssueItem) => siteNames[item.site_id] || '—'

  const scopeLabel = React.useMemo(() => {
    if (scope.mode === 'portfolio') return 'Portfolio Scope (All Projects)'
    if (scope.mode === 'project') return `Project Scope: ${scope.projectName}`
    return `Site Scope: ${scope.projectName} / ${scope.siteName}`
  }, [scope])

  const handleCreateIssue = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!activeProjectId || !activeSiteId) {
      toast.error('Project & Site Scope Required', 'Please select a specific Site scope in the header scope switcher before creating an issue.')
      return
    }

    setSubmitting(true)
    try {
      await createSiteIssueApi({
        project_id: activeProjectId,
        site_id: activeSiteId,
        issue_type: newIssueType,
        severity: newSeverity,
        narrative: newNarrative,
        delay_duration_minutes: parseInt(newDelayMins, 10) || 0,
      })
      toast.success('Site Blocker Reported', 'Issue successfully recorded in database and assigned to site team.')
      setCreateDialogOpen(false)
      setNewNarrative('')
      loadIssues()
    } catch {
      toast.error('Failed to Create Issue', 'Could not record site issue. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleResolveIssue = async () => {
    if (!selectedIssue) return
    setSubmitting(true)
    try {
      await resolveSiteIssueApi(selectedIssue.id, resolutionNotes)
      toast.success('Blocker Resolved', `Issue ${selectedIssue.id.slice(0, 8)} marked as RESOLVED.`)
      setResolveDialogOpen(false)
      setSelectedIssue(null)
      setResolutionNotes('')
      loadIssues()
    } catch {
      toast.error('Resolution Failed', 'Could not resolve issue. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleAcknowledgeIssue = async (issue: SiteIssueItem) => {
    try {
      await acknowledgeSiteIssueApi(issue.id)
      toast.success('Issue Acknowledged', `Issue ${issue.id.slice(0, 8)} marked as ACKNOWLEDGED.`)
      loadIssues()
    } catch {
      toast.error('Acknowledge Failed', 'Could not acknowledge issue. Please try again.')
    }
  }

  const handleWontFixIssue = async () => {
    if (!selectedIssue) return
    setSubmitting(true)
    try {
      await wontFixSiteIssueApi(selectedIssue.id, resolutionNotes)
      toast.success('Marked as Won\'t Fix', `Issue ${selectedIssue.id.slice(0, 8)} closed as WONT_FIX.`)
      setWontFixDialogOpen(false)
      setSelectedIssue(null)
      setResolutionNotes('')
      loadIssues()
    } catch {
      toast.error('Update Failed', 'Could not update issue. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex flex-col gap-5 w-full max-w-full relative pb-12">

      {/* ── Page Header ── */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <p className="text-sm text-muted-foreground">{scopeLabel}</p>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">What's stuck</h1>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={loadIssues}
            disabled={loading}
            className="h-9 gap-1.5"
            aria-label="Refresh issues"
          >
            <RefreshCw className={cn('size-4', loading && 'animate-spin')} />
            Refresh
          </Button>
          <Button size="sm" className="h-9 gap-1.5 font-semibold" onClick={() => setCreateDialogOpen(true)}>
            <Plus className="size-4" />
            Report issue
          </Button>
        </div>
      </div>

      {/* ── Summary ── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="rounded-xl border bg-card px-5 py-4 flex flex-col gap-1">
          <span className="text-sm text-muted-foreground">Open issues</span>
          <span className="text-3xl font-bold">{stats.openCount}</span>
        </div>
        <div className="rounded-xl border bg-card px-5 py-4 flex flex-col gap-1">
          <span className="text-sm text-muted-foreground">High or critical, still open</span>
          <span className={cn('text-3xl font-bold', stats.urgentOpenCount > 0 && 'text-draft')}>
            {stats.urgentOpenCount}
          </span>
        </div>
        <div className="rounded-xl border bg-card px-5 py-4 flex flex-col gap-1">
          <span className="text-sm text-muted-foreground">Time lost to open issues</span>
          <span className="text-3xl font-bold">{formatDuration(stats.openMinutesLost)}</span>
        </div>
      </div>

      {/* ── Filters ── */}
      <div className="flex flex-col sm:flex-row flex-wrap gap-2.5 items-stretch sm:items-center">
        <div className="relative w-full sm:w-72">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
          <Input
            placeholder="Search issues"
            aria-label="Search issues"
            value={searchQuery}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSearchQuery(e.target.value)}
            className="pl-9 h-10"
          />
        </div>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="h-10 w-full sm:w-44" aria-label="Status">
            <SelectValue placeholder="Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ACTIVE_FILTER}>Open (not closed)</SelectItem>
            <SelectItem value="ALL">All statuses</SelectItem>
            <SelectItem value="OPEN">Open, not acknowledged</SelectItem>
            <SelectItem value="ACKNOWLEDGED">Acknowledged</SelectItem>
            <SelectItem value="RESOLVED">Resolved</SelectItem>
            <SelectItem value="WONT_FIX">Won't fix</SelectItem>
            <SelectItem value="CANCELLED">Withdrawn</SelectItem>
          </SelectContent>
        </Select>
        <Select value={severityFilter} onValueChange={setSeverityFilter}>
          <SelectTrigger className="h-10 w-full sm:w-40" aria-label="Severity">
            <SelectValue placeholder="Severity" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="ALL">All severities</SelectItem>
            <SelectItem value="CRITICAL">Critical</SelectItem>
            <SelectItem value="HIGH">High</SelectItem>
            <SelectItem value="MEDIUM">Medium</SelectItem>
            <SelectItem value="LOW">Low</SelectItem>
          </SelectContent>
        </Select>
        <span className="text-sm text-muted-foreground sm:ml-auto">
          {filteredIssues.length} shown · {totalCount} recorded
        </span>
      </div>

      {/* ── Issues ── */}
      {filteredIssues.length === 0 ? (
        <div className="rounded-xl border bg-card p-12 text-center flex flex-col items-center gap-2">
          <CheckCircle2 className="size-8 text-success" aria-hidden="true" />
          <p className="text-base font-semibold">
            {statusFilter === ACTIVE_FILTER ? 'Nothing is stuck right now' : 'No issues match these filters'}
          </p>
          <p className="text-sm text-muted-foreground">
            Issues reported on WhatsApp or here appear in this list.
          </p>
        </div>
      ) : (
        <div className="rounded-xl border bg-card overflow-x-auto">
          <Table className="min-w-[760px]">
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs font-semibold text-muted-foreground">Issue</TableHead>
                <TableHead className="text-xs font-semibold text-muted-foreground">Site</TableHead>
                <TableHead className="text-xs font-semibold text-muted-foreground">Severity</TableHead>
                <TableHead className="text-xs font-semibold text-muted-foreground">Open for</TableHead>
                <TableHead className="text-xs font-semibold text-muted-foreground">Time lost</TableHead>
                <TableHead className="text-xs font-semibold text-muted-foreground">Status</TableHead>
                <TableHead className="text-right text-xs font-semibold text-muted-foreground">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody className="text-sm">
              {filteredIssues.map((item) => (
                <TableRow key={item.id}>
                  <TableCell className="max-w-[320px]">
                    <button
                      type="button"
                      className="flex flex-col items-start gap-0.5 text-left hover:underline"
                      onClick={() => {
                        setSelectedIssue(item)
                        setInspectSheetOpen(true)
                      }}
                    >
                      <span className="font-semibold">{humanizeIssueType(item.issue_type)}</span>
                      {item.narrative && (
                        <span className="text-xs text-muted-foreground line-clamp-1">{item.narrative}</span>
                      )}
                    </button>
                  </TableCell>
                  <TableCell className="whitespace-nowrap">{siteLabel(item)}</TableCell>
                  <TableCell>{getSeverityBadge(item.severity)}</TableCell>
                  <TableCell className="whitespace-nowrap text-muted-foreground">
                    {isClosed(item.status) ? 'Closed' : openFor(item.occurred_at)}
                  </TableCell>
                  <TableCell className="whitespace-nowrap">
                    {item.delay_duration_minutes ? formatDuration(item.delay_duration_minutes) : '—'}
                  </TableCell>
                  <TableCell>{getStatusBadge(item.status)}</TableCell>
                  <TableCell className="text-right">
                    {!isClosed(item.status) && (
                      <div className="flex items-center justify-end gap-1.5">
                        {item.status.toUpperCase() === 'OPEN' && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-8"
                            onClick={() => handleAcknowledgeIssue(item)}
                          >
                            Acknowledge
                          </Button>
                        )}
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-8 gap-1"
                          onClick={() => {
                            setSelectedIssue(item)
                            setResolveDialogOpen(true)
                          }}
                        >
                          <Check className="size-3.5" />
                          Resolve
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-8 text-muted-foreground"
                          onClick={() => {
                            setSelectedIssue(item)
                            setWontFixDialogOpen(true)
                          }}
                        >
                          Won't fix
                        </Button>
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* ── Report Issue Dialog ── */}
      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <form onSubmit={handleCreateIssue}>
            <DialogHeader>
              <DialogTitle className="text-base font-bold flex items-center gap-2">
                <ShieldAlert className="size-5 text-draft" />
                Report Site Blocker / Issue
              </DialogTitle>
              <DialogDescription className="text-xs">
                Record an operational issue or site delay for audit & resolution.
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-3.5 py-4 text-xs">
              <div className="space-y-1">
                <label className="font-bold text-foreground">Issue Type</label>
                <Select value={newIssueType} onValueChange={setNewIssueType}>
                  <SelectTrigger className="h-9 text-xs">
                    <SelectValue placeholder="Select type" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="WEATHER">WEATHER</SelectItem>
                    <SelectItem value="MATERIAL_SHORTAGE">MATERIAL_SHORTAGE</SelectItem>
                    <SelectItem value="LABOUR_SHORTAGE">LABOUR_SHORTAGE</SelectItem>
                    <SelectItem value="DRAWING_PENDING">DRAWING_PENDING</SelectItem>
                    <SelectItem value="EQUIPMENT_BREAKDOWN">EQUIPMENT_BREAKDOWN</SelectItem>
                    <SelectItem value="INSPECTION_WAITING">INSPECTION_WAITING</SelectItem>
                    <SelectItem value="ACCESS">ACCESS</SelectItem>
                    <SelectItem value="OTHER">OTHER</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="font-bold text-foreground">Severity</label>
                  <Select value={newSeverity} onValueChange={setNewSeverity}>
                    <SelectTrigger className="h-9 text-xs">
                      <SelectValue placeholder="Severity" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="LOW">LOW</SelectItem>
                      <SelectItem value="MEDIUM">MEDIUM</SelectItem>
                      <SelectItem value="HIGH">HIGH</SelectItem>
                      <SelectItem value="CRITICAL">CRITICAL</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-1">
                  <label className="font-bold text-foreground">Delay (Minutes)</label>
                  <Input
                    type="number"
                    value={newDelayMins}
                    onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewDelayMins(e.target.value)}
                    className="h-9 text-xs font-mono"
                    placeholder="30"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="font-bold text-foreground">Narrative Description</label>
                <textarea
                  value={newNarrative}
                  onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setNewNarrative(e.target.value)}
                  placeholder="Describe the cause of delay, affected location, and equipment involved..."
                  className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-xs shadow-2xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring min-h-24"
                />
              </div>
            </div>

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setCreateDialogOpen(false)} className="h-8 text-xs">
                Cancel
              </Button>
              <Button type="submit" disabled={submitting} className="h-9 font-semibold">
                {submitting ? 'Reporting...' : 'Submit Blocker Report'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* ── Resolve Issue Dialog ── */}
      <Dialog open={resolveDialogOpen} onOpenChange={setResolveDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-base font-bold flex items-center gap-2">
              <CheckCircle2 className="size-5 text-success" />
              Resolve Site Blocker
            </DialogTitle>
            <DialogDescription className="text-xs">
              Mark issue {selectedIssue?.id.slice(0, 8)} as RESOLVED.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3 py-3 text-xs">
            <div className="p-3 rounded-lg bg-muted/20 border text-muted-foreground">
              <strong>Narrative:</strong> {selectedIssue?.narrative || 'No narrative provided'}
            </div>

            <div className="space-y-1">
              <label className="font-bold text-foreground">Resolution Notes</label>
              <textarea
                value={resolutionNotes}
                onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setResolutionNotes(e.target.value)}
                placeholder="Explain how the blocker was cleared (e.g. Pump replaced, weather cleared)..."
                className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-xs shadow-2xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring min-h-20"
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setResolveDialogOpen(false)} className="h-8 text-xs">
              Cancel
            </Button>
            <Button disabled={submitting} onClick={handleResolveIssue} className="h-9 font-semibold">
              {submitting ? 'Resolving...' : 'Confirm Resolution'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Won't Fix Dialog ── */}
      <Dialog open={wontFixDialogOpen} onOpenChange={setWontFixDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-base font-bold flex items-center gap-2">
              <ShieldAlert className="size-5 text-muted-foreground" />
              Mark as Won't Fix
            </DialogTitle>
            <DialogDescription className="text-xs">
              Close issue {selectedIssue?.id.slice(0, 8)} without resolving it (e.g. no longer relevant).
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3 py-3 text-xs">
            <div className="p-3 rounded-lg bg-muted/20 border text-muted-foreground">
              <strong>Narrative:</strong> {selectedIssue?.narrative || 'No narrative provided'}
            </div>

            <div className="space-y-1">
              <label className="font-bold text-foreground">Reason</label>
              <textarea
                value={resolutionNotes}
                onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setResolutionNotes(e.target.value)}
                placeholder="Explain why this issue will not be fixed..."
                className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-xs shadow-2xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring min-h-20"
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setWontFixDialogOpen(false)} className="h-8 text-xs">
              Cancel
            </Button>
            <Button disabled={submitting} onClick={handleWontFixIssue} className="h-8 text-xs font-bold bg-zinc-700 text-white hover:bg-zinc-800">
              {submitting ? 'Updating...' : "Confirm Won't Fix"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Inspection Sheet ── */}
      <Sheet open={inspectSheetOpen} onOpenChange={setInspectSheetOpen}>
        <SheetContent className="sm:max-w-md overflow-y-auto">
          <SheetHeader>
            <SheetTitle className="text-sm font-bold flex items-center gap-2">
              <ShieldAlert className="size-4 text-draft" />
              {selectedIssue ? humanizeIssueType(selectedIssue.issue_type) : null}
            </SheetTitle>
            <SheetDescription className="text-[11px]">
              ID: {selectedIssue?.id}
            </SheetDescription>
          </SheetHeader>

          <div className="space-y-4 pt-4 text-xs">
            <div className="p-3 rounded-lg border bg-muted/10 space-y-1">
              <span className="font-bold block">Description</span>
              <p className="text-muted-foreground leading-relaxed">{selectedIssue?.narrative || 'No description'}</p>
            </div>

            {selectedIssue?.resolution_notes && (
              <div className="p-3 rounded-lg bg-success-soft space-y-1">
                <span className="font-semibold text-success block">Resolution Notes</span>
                <p className="text-foreground">{selectedIssue.resolution_notes}</p>
              </div>
            )}
          </div>
        </SheetContent>
      </Sheet>
    </div>
  )
}
