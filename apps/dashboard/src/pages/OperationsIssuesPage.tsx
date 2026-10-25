import * as React from 'react'
import { Search, Plus, RefreshCw, CheckCircle2, Check, TriangleAlert } from 'lucide-react'
import { useScope } from '@/lib/ScopeContext'
import {
  fetchSiteIssuesApi,
  createSiteIssueApi,
  resolveSiteIssueApi,
  acknowledgeSiteIssueApi,
  wontFixSiteIssueApi,
  fetchUsers,
  type SiteIssueItem,
} from '@/lib/api'
import { useToast } from '@/components/ui/toast-notification'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { useQuery } from '@tanstack/react-query'
import { Sheet, SheetContent, SheetFooter, SheetTitle } from '@/components/ui/sheet'
import { ByLine, Fact, Facts, SheetHero, SheetSection } from '@/components/detail-sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Callout, PageHeader, StatStrip } from '@/components/dpr-page'
import { useSiteNames } from '@/lib/site-names'
import { useUrlState } from '@/lib/url-state'
import { plural } from '@/lib/site-day'
import { cn } from '@/lib/utils'

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

  const names = useSiteNames()
  const [issues, setIssues] = React.useState<SiteIssueItem[]>([])
  const [loadError, setLoadError] = React.useState<boolean>(false)
  // The server's count of every matching issue. `issues` holds one page
  // (limit 100), so counting that array under-reports the moment a site
  // passes 100 issues -- silently, and only on the busiest sites.
  const [totalCount, setTotalCount] = React.useState<number>(0)
  const [loading, setLoading] = React.useState<boolean>(true)

  // Filters live in the address (WEB-26).
  const [searchQuery, setSearchQuery] = useUrlState<string>('q', '')
  const [statusFilter, setStatusFilter] = useUrlState<string>('status', ACTIVE_FILTER)
  const [severityFilter, setSeverityFilter] = useUrlState<string>('severity', 'ALL')
  const [newSiteId, setNewSiteId] = React.useState<string>('')

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
    setLoadError(false)
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
      // Not "nothing is stuck": a failed load must not look like good news.
      setIssues([])
      setTotalCount(0)
      setLoadError(true)
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

  const siteLabel = (item: SiteIssueItem) => names.get(item.site_id)?.name || '—'

  const scopeLabel =
    scope.mode === 'portfolio' ? 'All projects' : scope.mode === 'project' ? scope.projectName : `${scope.projectName} / ${scope.siteName}`
  // Sites the issue can be reported on: the scope's site, else every site in view.
  const siteChoices = React.useMemo(
    () =>
      [...names.entries()]
        .filter(([id, n]) => (activeSiteId ? id === activeSiteId : !activeProjectId || n.projectId === activeProjectId))
        .sort(([, x], [, y]) => (x.project + x.name).localeCompare(y.project + y.name)),
    [names, activeSiteId, activeProjectId],
  )
  const openCreate = () => {
    setNewSiteId(activeSiteId || (siteChoices.length === 1 ? siteChoices[0][0] : ''))
    setCreateDialogOpen(true)
  }

  const handleCreateIssue = async (e: React.FormEvent) => {
    e.preventDefault()
    const site = names.get(newSiteId)
    if (!site) {
      toast.error('Pick a site', 'Choose which site the issue is on.')
      return
    }

    setSubmitting(true)
    try {
      await createSiteIssueApi({
        project_id: site.projectId,
        site_id: newSiteId,
        issue_type: newIssueType,
        severity: newSeverity,
        narrative: newNarrative,
        delay_duration_minutes: parseInt(newDelayMins, 10) || 0,
      })
      toast.success('Issue reported', `${humanizeIssueType(newIssueType)} on ${site.name} is now open.`)
      setCreateDialogOpen(false)
      setNewNarrative('')
      loadIssues()
    } catch {
      toast.error('Could not report the issue', 'Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleResolveIssue = async () => {
    if (!selectedIssue) return
    setSubmitting(true)
    try {
      await resolveSiteIssueApi(selectedIssue.id, resolutionNotes)
      toast.success('Issue resolved', `${humanizeIssueType(selectedIssue.issue_type)} on ${siteLabel(selectedIssue)} is closed.`)
      setResolveDialogOpen(false)
      setSelectedIssue(null)
      setResolutionNotes('')
      loadIssues()
    } catch {
      toast.error('Could not resolve the issue', 'Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleAcknowledgeIssue = async (issue: SiteIssueItem) => {
    try {
      await acknowledgeSiteIssueApi(issue.id)
      toast.success('Acknowledged', `${humanizeIssueType(issue.issue_type)} on ${siteLabel(issue)}.`)
      loadIssues()
    } catch {
      toast.error('Could not acknowledge', 'Please try again.')
    }
  }

  const handleWontFixIssue = async () => {
    if (!selectedIssue) return
    setSubmitting(true)
    try {
      await wontFixSiteIssueApi(selectedIssue.id, resolutionNotes)
      toast.success("Closed as won't fix", `${humanizeIssueType(selectedIssue.issue_type)} on ${siteLabel(selectedIssue)}.`)
      setWontFixDialogOpen(false)
      setSelectedIssue(null)
      setResolutionNotes('')
      loadIssues()
    } catch {
      toast.error('Could not close the issue', 'Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const filtered = statusFilter !== ACTIVE_FILTER || severityFilter !== 'ALL' || !!searchQuery

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 pb-8 sm:px-2">
      <PageHeader
        title="Issues"
        subtitle={<>What's stuck, most severe first · {scopeLabel}</>}
        actions={
          <>
            <Button size="sm" className="gap-1.5 font-semibold" onClick={openCreate}>
              <Plus className="size-4" /> Report issue
            </Button>
            <Button variant="ghost" size="icon" className="size-8" onClick={loadIssues} disabled={loading} title="Refresh" aria-label="Refresh">
              <RefreshCw className={cn('size-4', loading && 'animate-spin')} />
            </Button>
          </>
        }
      />

      <StatStrip
        stats={[
          { label: 'Open', value: stats.openCount || '—', tone: stats.openCount > 0 ? 'warn' : 'default' },
          { label: 'High or critical', value: stats.urgentOpenCount || '—', tone: stats.urgentOpenCount > 0 ? 'bad' : 'default' },
          { label: 'Time lost', value: stats.openMinutesLost ? formatDuration(stats.openMinutesLost) : '—' },
        ]}
      />

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-64">
          <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
          <Input
            placeholder="Search issues…"
            aria-label="Search issues"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="h-9 pl-8"
          />
        </div>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="h-9 w-[170px]" aria-label="Status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ACTIVE_FILTER}>Open (not closed)</SelectItem>
            <SelectItem value="ALL">Any status</SelectItem>
            <SelectItem value="OPEN">Not acknowledged yet</SelectItem>
            <SelectItem value="ACKNOWLEDGED">Acknowledged</SelectItem>
            <SelectItem value="RESOLVED">Resolved</SelectItem>
            <SelectItem value="WONT_FIX">Won't fix</SelectItem>
            <SelectItem value="CANCELLED">Withdrawn</SelectItem>
          </SelectContent>
        </Select>
        <Select value={severityFilter} onValueChange={setSeverityFilter}>
          <SelectTrigger className="h-9 w-[140px]" aria-label="Severity">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="ALL">Any severity</SelectItem>
            <SelectItem value="CRITICAL">Critical</SelectItem>
            <SelectItem value="HIGH">High</SelectItem>
            <SelectItem value="MEDIUM">Medium</SelectItem>
            <SelectItem value="LOW">Low</SelectItem>
          </SelectContent>
        </Select>
        <span className="ml-auto text-sm text-muted-foreground">
          {filteredIssues.length === totalCount ? plural(totalCount, 'issue') : `${filteredIssues.length} of ${totalCount}`}
        </span>
      </div>

      {loadError ? (
        <Callout
          tone="draft"
          icon={TriangleAlert}
          action={
            <Button variant="outline" size="sm" className="bg-background" onClick={loadIssues}>
              Try again
            </Button>
          }
        >
          The issues could not be loaded.
        </Callout>
      ) : loading && issues.length === 0 ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-14 rounded-lg" />
          ))}
        </div>
      ) : filteredIssues.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center">
          <CheckCircle2 className="size-6 text-success" aria-hidden="true" />
          <p className="text-sm font-medium">{filtered ? 'No issues match these filters' : 'Nothing is stuck right now'}</p>
          <p className="text-sm text-muted-foreground">Issues reported on WhatsApp or here show up in this list.</p>
        </div>
      ) : (
        <ul className="flex flex-col divide-y rounded-xl border px-4">
          {filteredIssues.map((item) => {
            const closed = isClosed(item.status)
            return (
              <li key={item.id} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:gap-4">
                <div className="flex min-w-0 flex-1 items-start gap-3">
                  <span className="mt-0.5 w-[68px] shrink-0">{getSeverityBadge(item.severity)}</span>
                  <button
                    type="button"
                    className="flex min-w-0 flex-col items-start text-left"
                    onClick={() => {
                      setSelectedIssue(item)
                      setInspectSheetOpen(true)
                    }}
                  >
                    <span className="font-medium hover:underline">{humanizeIssueType(item.issue_type)}</span>
                    {item.narrative && <span className="line-clamp-1 text-sm text-muted-foreground">{item.narrative}</span>}
                    <span className="text-xs text-muted-foreground">
                      {[
                        siteLabel(item),
                        closed ? null : `open ${openFor(item.occurred_at).toLowerCase()}`,
                        item.delay_duration_minutes ? `${formatDuration(item.delay_duration_minutes)} lost` : null,
                      ]
                        .filter(Boolean)
                        .join(' · ')}
                    </span>
                  </button>
                </div>
                <div className="flex shrink-0 flex-wrap items-center gap-1.5 pl-[80px] sm:pl-0">
                  {getStatusBadge(item.status)}
                  {!closed && item.status.toUpperCase() === 'OPEN' && (
                    <Button variant="ghost" size="sm" onClick={() => handleAcknowledgeIssue(item)}>
                      Acknowledge
                    </Button>
                  )}
                  {!closed && (
                    <>
                      <Button
                        variant="outline"
                        size="sm"
                        className="gap-1"
                        onClick={() => {
                          setSelectedIssue(item)
                          setResolveDialogOpen(true)
                        }}
                      >
                        <Check className="size-3.5" /> Resolve
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-muted-foreground"
                        onClick={() => {
                          setSelectedIssue(item)
                          setWontFixDialogOpen(true)
                        }}
                      >
                        Won't fix
                      </Button>
                    </>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}

      {/* ── Report Issue Dialog ── */}
      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <form onSubmit={handleCreateIssue}>
            <DialogHeader>
              <DialogTitle className="text-base font-semibold">Report an issue</DialogTitle>
              <DialogDescription>Something stopping or slowing work on a site.</DialogDescription>
            </DialogHeader>

            <div className="space-y-3.5 py-4 text-sm">
              <div className="space-y-1">
                <label className="font-medium" htmlFor="issue-site">
                  Site
                </label>
                <Select value={newSiteId} onValueChange={setNewSiteId}>
                  <SelectTrigger id="issue-site" className="h-9">
                    <SelectValue placeholder="Pick a site" />
                  </SelectTrigger>
                  <SelectContent>
                    {siteChoices.map(([id, n]) => (
                      <SelectItem key={id} value={id}>
                        {n.name} · {n.project}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <label className="font-medium">What kind of issue</label>
                <Select value={newIssueType} onValueChange={setNewIssueType}>
                  <SelectTrigger className="h-9 text-xs">
                    <SelectValue placeholder="Select type" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="WEATHER">Weather</SelectItem>
                    <SelectItem value="MATERIAL_SHORTAGE">Material shortage</SelectItem>
                    <SelectItem value="LABOUR_SHORTAGE">Labour shortage</SelectItem>
                    <SelectItem value="DRAWING_PENDING">Drawing pending</SelectItem>
                    <SelectItem value="EQUIPMENT_BREAKDOWN">Equipment breakdown</SelectItem>
                    <SelectItem value="INSPECTION_WAITING">Waiting for inspection</SelectItem>
                    <SelectItem value="ACCESS">Site access</SelectItem>
                    <SelectItem value="SAFETY">Safety (accident, injury)</SelectItem>
                    <SelectItem value="QUALITY">Quality (leakage, seepage, crack)</SelectItem>
                    <SelectItem value="OTHER">Other</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="font-medium">Severity</label>
                  <Select value={newSeverity} onValueChange={setNewSeverity}>
                    <SelectTrigger className="h-9 text-xs">
                      <SelectValue placeholder="Severity" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="LOW">Low</SelectItem>
                      <SelectItem value="MEDIUM">Medium</SelectItem>
                      <SelectItem value="HIGH">High</SelectItem>
                      <SelectItem value="CRITICAL">Critical</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-1">
                  <label className="font-medium">Time lost (minutes)</label>
                  <Input
                    type="number"
                    value={newDelayMins}
                    onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewDelayMins(e.target.value)}
                    className="h-9"
                    placeholder="30"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="font-medium">What happened</label>
                <textarea
                  value={newNarrative}
                  onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setNewNarrative(e.target.value)}
                  placeholder="e.g. Cement not delivered, slab pour moved to tomorrow"
                  className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-2xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring min-h-24"
                />
              </div>
            </div>

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setCreateDialogOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={submitting || !newSiteId} className="font-semibold">
                {submitting ? 'Reporting…' : 'Report issue'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* ── Resolve Issue Dialog ── */}
      <Dialog open={resolveDialogOpen} onOpenChange={setResolveDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-base font-semibold">Resolve this issue?</DialogTitle>
            <DialogDescription>
              {selectedIssue ? `${humanizeIssueType(selectedIssue.issue_type)} on ${siteLabel(selectedIssue)}` : ''} is closed as fixed.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3 py-3 text-sm">
            <div className="p-3 rounded-lg bg-muted/20 border text-muted-foreground">
              {selectedIssue?.narrative || 'No description'}
            </div>

            <div className="space-y-1">
              <label className="font-medium">How was it fixed? (optional)</label>
              <textarea
                value={resolutionNotes}
                onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setResolutionNotes(e.target.value)}
                placeholder="e.g. Pump replaced, cement arrived"
                className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-2xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring min-h-20"
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setResolveDialogOpen(false)}>
              Cancel
            </Button>
            <Button disabled={submitting} onClick={handleResolveIssue} className="font-semibold">
              {submitting ? 'Resolving…' : 'Resolve'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Won't Fix Dialog ── */}
      <Dialog open={wontFixDialogOpen} onOpenChange={setWontFixDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-base font-semibold">Close without fixing?</DialogTitle>
            <DialogDescription>For an issue that no longer matters. It is closed, not marked fixed.</DialogDescription>
          </DialogHeader>

          <div className="space-y-3 py-3 text-sm">
            <div className="p-3 rounded-lg bg-muted/20 border text-muted-foreground">
              {selectedIssue?.narrative || 'No description'}
            </div>

            <div className="space-y-1">
              <label className="font-medium">Why</label>
              <textarea
                value={resolutionNotes}
                onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setResolutionNotes(e.target.value)}
                placeholder="Explain why this issue will not be fixed..."
                className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-2xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring min-h-20"
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setWontFixDialogOpen(false)}>
              Cancel
            </Button>
            <Button disabled={submitting} onClick={handleWontFixIssue} variant="secondary" className="font-semibold">
              {submitting ? 'Closing…' : "Close as won't fix"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Inspection Sheet (WEB-36: the side-panel layout, detail-sheet.tsx) ── */}
      <Sheet open={inspectSheetOpen} onOpenChange={setInspectSheetOpen}>
        <SheetContent className="w-full gap-0 overflow-y-auto p-0 sm:max-w-md">
          {selectedIssue ? (
            <IssuePanel
              issue={selectedIssue}
              site={siteLabel(selectedIssue)}
              // Each closes the panel: the list reloads with the new status.
              onAcknowledge={() => {
                setInspectSheetOpen(false)
                handleAcknowledgeIssue(selectedIssue)
              }}
              onResolve={() => {
                setInspectSheetOpen(false)
                setResolveDialogOpen(true)
              }}
              onWontFix={() => {
                setInspectSheetOpen(false)
                setWontFixDialogOpen(true)
              }}
            />
          ) : (
            <SheetTitle className="sr-only">Issue</SheetTitle>
          )}
        </SheetContent>
      </Sheet>
    </div>
  )
}

const SEVERITY_WORDS: Record<string, string> = { CRITICAL: 'Critical', HIGH: 'High', MEDIUM: 'Medium', LOW: 'Low' }
const STATUS_WORDS: Record<string, string> = { OPEN: 'Open', ACKNOWLEDGED: 'Acknowledged', RESOLVED: 'Resolved', WONT_FIX: "Won't fix", CANCELLED: 'Withdrawn' }

function IssuePanel({
  issue,
  site,
  onAcknowledge,
  onResolve,
  onWontFix,
}: {
  issue: SiteIssueItem
  site: string
  onAcknowledge: () => void
  onResolve: () => void
  onWontFix: () => void
}) {
  const severity = issue.severity.toUpperCase()
  const status = issue.status.toUpperCase()
  const closed = isClosed(status)
  const users = useQuery({ queryKey: ['users-list'], queryFn: fetchUsers, retry: false, staleTime: 5 * 60_000 })
  const reporter = issue.reported_by_user_id ? users.data?.find((u) => u.id === issue.reported_by_user_id)?.full_name : undefined
  const at = (iso: string) => new Date(iso).toLocaleString([], { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })
  const tone = closed ? (status === 'RESOLVED' ? 'in' : 'neutral') : severity === 'CRITICAL' ? 'out' : severity === 'HIGH' ? 'warn' : 'neutral'

  return (
    <>
      <SheetHero tone={tone} kicker={closed ? STATUS_WORDS[status] ?? status : `${SEVERITY_WORDS[severity] ?? severity} · ${STATUS_WORDS[status] ?? status}`} title={humanizeIssueType(issue.issue_type)}>
        <span>{site}</span>
        <span>{at(issue.occurred_at)}</span>
        {!closed && <span className="font-medium text-foreground">Open {openFor(issue.occurred_at).toLowerCase()}</span>}
      </SheetHero>

      <SheetSection title="What happened">
        <p className={cn('text-sm leading-relaxed', !issue.narrative && 'text-muted-foreground')}>{issue.narrative || 'No description was given.'}</p>
      </SheetSection>

      <SheetSection title="Details" className="border-t">
        <Facts>
          <Fact label="Severity">{getSeverityBadge(issue.severity)}</Fact>
          <Fact label="Status">{getStatusBadge(issue.status)}</Fact>
          {issue.delay_duration_minutes ? <Fact label="Time lost">{formatDuration(issue.delay_duration_minutes)}</Fact> : null}
          {issue.resolved_at && <Fact label="Closed">{at(issue.resolved_at)}</Fact>}
        </Facts>
      </SheetSection>

      {issue.resolution_notes && (
        <SheetSection title={status === 'RESOLVED' ? 'How it was fixed' : 'Why it was closed'} className="border-t">
          <p className="rounded-lg bg-success-soft/60 px-3 py-2 text-sm">{issue.resolution_notes}</p>
        </SheetSection>
      )}

      <SheetSection title="Reported by" className="border-t">
        <ByLine name={reporter} detail={at(issue.created_at)} />
      </SheetSection>

      {!closed && (
        <SheetFooter className="flex-row flex-wrap items-center gap-2 border-t px-5 py-3">
          <Button size="sm" className="gap-1.5" onClick={onResolve}>
            <Check className="size-3.5" /> Resolve
          </Button>
          {status === 'OPEN' && (
            <Button size="sm" variant="outline" onClick={onAcknowledge}>
              Acknowledge
            </Button>
          )}
          <Button size="sm" variant="ghost" className="ml-auto text-muted-foreground" onClick={onWontFix}>
            Won't fix
          </Button>
        </SheetFooter>
      )}
    </>
  )
}
