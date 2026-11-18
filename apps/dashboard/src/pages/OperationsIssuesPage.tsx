import * as React from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { LucideIcon } from 'lucide-react'
import {
  Ban, Check, ChevronLeft, ChevronRight, CircleCheck, CircleDot, ClipboardCheck, Clock, CloudRain, Copy, DoorClosed, Eye,
  FileClock, HardHat, Hourglass, ListTodo, MapPin, PackageX, Plus, RefreshCw, ShieldAlert, Siren, TriangleAlert, Undo2, Users, Wrench,
} from 'lucide-react'
import { useScope } from '@/lib/ScopeContext'
import {
  fetchSiteIssueApi,
  fetchSiteIssuesApi,
  createSiteIssueApi,
  resolveSiteIssueApi,
  acknowledgeSiteIssueApi,
  wontFixSiteIssueApi,
  fetchUsers,
  type SiteIssueItem,
} from '@/lib/api'
import { fetchTasks, type Task } from '@/lib/tasks'
import { useModuleEnabled } from '@/lib/modules'
import { useToast } from '@/components/ui/toast-notification'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { Sheet, SheetContent, SheetFooter, SheetTitle } from '@/components/ui/sheet'
import { ByLine, Fact, Facts, SheetHero, SheetSection } from '@/components/detail-sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Callout, PageHeader } from '@/components/dpr-page'
import {
  ActionButton, ActionChip, BulkBar, ClearButton, EmptyState, KpiStrip, Legend, NoMatch, Pager, Pill, SearchBox, SortSelect, StateBar, ToggleChip,
} from '@/components/page/page-kit'
import { NumbersTable, ShowSwitch, type NumberColumn } from '@/components/page/numbers-view'
import { sortByColumn, useColumnSort, useShowMode } from '@/lib/numbers-view'
import { TONE, type Tone } from '@/lib/list-kit'
import { useSiteNames } from '@/lib/site-names'
import { updateParams, useUrlState } from '@/lib/url-state'
import { usePagedUrl } from '@/lib/paging'
import { appNow } from '@/lib/clock'
import { exportCsv } from '@/lib/export'
import { cn } from '@/lib/utils'
import { MakeTaskButton } from '@/components/tasks/make-task-button'

// UX-63: the Issues page on the list kit (docs/design/LIST_PAGE_KIT.md): figures, what needs a person, where the
// issues come from (by kind, by site: each a filter), a bar of states, Bars or Numbers, ticking several, and a panel
// that walks the list (previous / next), shows the issue's timeline, its tasks and the site's other open issues.

// ─── Words, colours and icons ─────────────────────────────────────────────────

const SEVERITIES = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] as const
const SEVERITY_RANK: Record<string, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 }
const SEVERITY_WORD: Record<string, string> = { CRITICAL: 'Critical', HIGH: 'High', MEDIUM: 'Medium', LOW: 'Low' }
// Critical is the only red (WEB-07).
const SEVERITY_TONE: Record<string, Tone> = { CRITICAL: 'bad', HIGH: 'attention', MEDIUM: 'info', LOW: 'muted' }

// CANCELLED is a withdrawn report (migration 0460): not "fixed", but not an open blocker either.
const CLOSED = ['RESOLVED', 'WONT_FIX', 'CANCELLED']
const isClosed = (status: string) => CLOSED.includes(status.toUpperCase())

const STATES: { value: string; label: string; icon: LucideIcon; tone: Tone }[] = [
  { value: 'OPEN', label: 'Not seen', icon: CircleDot, tone: 'attention' },
  { value: 'ACKNOWLEDGED', label: 'Seen', icon: Eye, tone: 'info' },
  { value: 'RESOLVED', label: 'Fixed', icon: CircleCheck, tone: 'good' },
  { value: 'WONT_FIX', label: "Won't fix", icon: Ban, tone: 'muted' },
  { value: 'CANCELLED', label: 'Withdrawn', icon: Undo2, tone: 'muted' },
]
const STATE = Object.fromEntries(STATES.map((s) => [s.value, s]))

const KINDS: { value: string; label: string; icon: LucideIcon }[] = [
  { value: 'MATERIAL_SHORTAGE', label: 'Material shortage', icon: PackageX },
  { value: 'LABOUR_SHORTAGE', label: 'Labour shortage', icon: Users },
  { value: 'EQUIPMENT_BREAKDOWN', label: 'Equipment breakdown', icon: Wrench },
  { value: 'DRAWING_PENDING', label: 'Drawing pending', icon: FileClock },
  { value: 'INSPECTION_WAITING', label: 'Waiting for inspection', icon: ClipboardCheck },
  { value: 'WEATHER', label: 'Weather', icon: CloudRain },
  { value: 'ACCESS', label: 'Site access', icon: DoorClosed },
  { value: 'SAFETY', label: 'Safety', icon: HardHat },
  { value: 'QUALITY', label: 'Quality', icon: ShieldAlert },
  { value: 'OTHER', label: 'Other', icon: CircleDot },
]
const KIND = Object.fromEntries(KINDS.map((k) => [k.value, k]))

function kindWord(issueType: string): string {
  const known = KIND[issueType.toUpperCase()]
  if (known) return known.label
  const words = issueType.toLowerCase().replace(/_/g, ' ').trim()
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : 'Issue'
}
const kindIcon = (issueType: string) => KIND[issueType.toUpperCase()]?.icon ?? CircleDot

function minutesWord(minutes: number): string {
  if (minutes <= 0) return '0 min'
  if (minutes < 60) return `${minutes} min`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest ? `${hours} h ${rest} min` : `${hours} h`
}

const HOUR = 3_600_000
const DAY = 86_400_000

/** A span of time in a few letters: "40 min", "5 h", "3 days". */
function spanWord(ms: number): string {
  if (ms < HOUR) return `${Math.max(1, Math.round(ms / 60_000))} min`
  if (ms < DAY) return `${Math.floor(ms / HOUR)} h`
  const days = Math.floor(ms / DAY)
  return days === 1 ? '1 day' : `${days} days`
}

const dayWord = (iso: string) => new Date(iso).toLocaleDateString([], { day: 'numeric', month: 'short' })
const timeWord = (iso: string) => new Date(iso).toLocaleString([], { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })

/** How long it has waited (open) or took (closed), in ms. */
function waited(i: SiteIssueItem, now: number): number {
  const from = new Date(i.occurred_at).getTime()
  const to = isClosed(i.status) && i.resolved_at ? new Date(i.resolved_at).getTime() : now
  return Math.max(0, to - from)
}

// WEB-37: an open issue turns amber after a day and red after three, so what has been left waiting stands out.
function ageTone(i: SiteIssueItem, now: number): Tone {
  if (isClosed(i.status)) return i.status.toUpperCase() === 'RESOLVED' ? 'good' : 'muted'
  const days = waited(i, now) / DAY
  return days >= 3 ? 'bad' : days >= 1 ? 'attention' : 'muted'
}

/** The row's edge: its severity while open, grey once closed. */
const edgeOf = (i: SiteIssueItem) => (isClosed(i.status) ? 'bg-muted-foreground/25' : TONE[SEVERITY_TONE[i.severity.toUpperCase()] ?? 'muted'].dot)

const SORTS = [
  { value: '', label: 'Worst first' },
  { value: 'oldest', label: 'Waiting longest' },
  { value: 'newest', label: 'Newest' },
  { value: 'lost', label: 'Most time lost' },
  { value: 'site', label: 'Site' },
]

const LATE_DAYS = 3

// ─── The page ─────────────────────────────────────────────────────────────────

export default function OperationsIssuesPage() {
  const { scope } = useScope()
  const toast = useToast()
  const queryClient = useQueryClient()
  const names = useSiteNames()
  const isEnabled = useModuleEnabled()
  const [params, setParams] = useSearchParams()

  const projectId = scope.mode !== 'portfolio' ? scope.projectId : undefined
  const siteId = scope.mode === 'site' ? scope.siteId : undefined

  // Every issue in scope, 100 at a time (the server's most), up to 1,000 (UX-37): every state's count is true, and the
  // filters below work on what is here without asking the server again.
  const issuesQuery = useQuery({
    queryKey: ['site-issues', projectId ?? null, siteId ?? null],
    queryFn: async () => {
      const ask = (offset: number) => fetchSiteIssuesApi({ projectId, siteId, limit: 100, offset })
      const first = await ask(0)
      const items = [...(first.items || [])]
      const total = first.total ?? items.length
      while (items.length < Math.min(total, 1000)) {
        const more = await ask(items.length)
        if (!more.items?.length) break
        items.push(...more.items)
      }
      return { items, total }
    },
  })
  const issues = React.useMemo(() => issuesQuery.data?.items ?? [], [issuesQuery.data])
  const loading = issuesQuery.isLoading
  const reload = () => queryClient.invalidateQueries({ queryKey: ['site-issues'] })

  // The tasks that fix an issue (TSK-03), when Tasks is switched on; a failure only hides them.
  const tasksOn = isEnabled('tasks')
  const tasksQuery = useQuery({
    queryKey: ['issue-tasks', projectId ?? null, siteId ?? null],
    queryFn: () => fetchTasks({ project_id: projectId, site_id: siteId, status: 'all' }),
    enabled: tasksOn,
    retry: false,
    staleTime: 60_000,
  })
  const tasksByIssue = React.useMemo(() => {
    const out = new Map<string, Task[]>()
    for (const t of tasksQuery.data?.items ?? []) {
      if (!t.site_issue_id) continue
      out.set(t.site_issue_id, [...(out.get(t.site_issue_id) ?? []), t])
    }
    return out
  }, [tasksQuery.data])

  const users = useQuery({ queryKey: ['users-list'], queryFn: fetchUsers, retry: false, staleTime: 5 * 60_000 })
  const personName = React.useCallback((id?: string | null) => (id ? users.data?.find((u) => u.id === id)?.full_name : undefined), [users.data])
  const siteName = React.useCallback((i: SiteIssueItem) => names.get(i.site_id)?.name || '—', [names])

  // ── Filters, all in the address (WEB-26). `status` '' is "open" (not seen + seen); ACTIVE and ALL are older links.
  const [search, setSearch] = useUrlState<string>('q', '')
  const [statusRaw, setStatus] = useUrlState<string>('status', '')
  const status = statusRaw === 'ACTIVE' ? '' : statusRaw
  const [severityRaw, setSeverity] = useUrlState<string>('severity', '')
  const severity = severityRaw === 'ALL' ? '' : severityRaw
  const [kind, setKind] = useUrlState<string>('kind', '')
  const [where, setWhere] = useUrlState<string>('where', '')
  const [lateOnly, setLateOnly] = useUrlState<string>('late', '')
  const [urgentOnly, setUrgentOnly] = useUrlState<string>('urgent', '')
  const [noTaskOnly, setNoTaskOnly] = useUrlState<string>('notask', '')
  const [sort, setSort] = useUrlState<string>('sort', '')
  const [show, setShow] = useShowMode('issues')
  const { col, dir, onSort: sortCol, clear: clearCol } = useColumnSort()
  // The open issue's panel: /issues?id=… (also a task's "Fixes the issue" link, TSK-03). Back closes it.
  const [openId, setOpenId] = useUrlState<string>('id', '')
  // Opening one adds a step to the history (so Back closes it); moving to another or closing replaces it.
  const openPanel = (id: string) => updateParams(setParams, (p) => p.set('id', id), !!openId)

  const now = appNow().getTime()
  const isLate = React.useCallback((i: SiteIssueItem) => !isClosed(i.status) && waited(i, now) >= LATE_DAYS * DAY, [now])
  const isUrgent = (i: SiteIssueItem) => ['CRITICAL', 'HIGH'].includes(i.severity.toUpperCase())

  const open = React.useMemo(() => issues.filter((i) => !isClosed(i.status)), [issues])
  const inStatus = React.useCallback(
    (i: SiteIssueItem) => (status === 'ALL' ? true : status ? i.status.toUpperCase() === status : !isClosed(i.status)),
    [status],
  )

  // What the search reads: the kind, the words, the fix notes, the site and who reported it.
  const matches = React.useCallback(
    (i: SiteIssueItem, q: string) =>
      !q ||
      [kindWord(i.issue_type), i.narrative, i.resolution_notes, siteName(i), personName(i.reported_by_user_id)]
        .some((s) => (s || '').toLowerCase().includes(q)),
    [siteName, personName],
  )

  // Everything but the status: the state bar's counts (so a chip says how many it would show).
  const beforeStatus = React.useMemo(() => {
    const q = search.trim().toLowerCase()
    return issues.filter(
      (i) =>
        (!severity || i.severity.toUpperCase() === severity) &&
        (!kind || i.issue_type.toUpperCase() === kind) &&
        (!where || i.site_id === where) &&
        (!lateOnly || isLate(i)) &&
        (!urgentOnly || isUrgent(i)) &&
        (!noTaskOnly || (!isClosed(i.status) && !tasksByIssue.has(i.id))) &&
        matches(i, q),
    )
  }, [issues, search, severity, kind, where, lateOnly, urgentOnly, noTaskOnly, tasksByIssue, isLate, matches])

  const listed = React.useMemo(() => {
    const out = beforeStatus.filter(inStatus)
    const byColumn = show === 'numbers' ? sortByColumn(out, [NAME, ...columns(now, siteName, personName, tasksByIssue)], col, dir) : null
    if (byColumn) return byColumn
    const sev = (i: SiteIssueItem) => SEVERITY_RANK[i.severity.toUpperCase()] ?? 9
    const at = (i: SiteIssueItem) => new Date(i.occurred_at).getTime()
    return [...out].sort((a, b) => {
      if (sort === 'oldest') return at(a) - at(b)
      if (sort === 'newest') return at(b) - at(a)
      if (sort === 'lost') return (b.delay_duration_minutes || 0) - (a.delay_duration_minutes || 0)
      if (sort === 'site') return siteName(a).localeCompare(siteName(b)) || sev(a) - sev(b)
      // Worst first: open before closed, the most severe, then the longest waiting (WEB-07).
      return Number(isClosed(a.status)) - Number(isClosed(b.status)) || sev(a) - sev(b) || at(a) - at(b)
    })
  }, [beforeStatus, inStatus, show, col, dir, sort, now, siteName, personName, tasksByIssue])
  const paged = usePagedUrl(listed)

  const any = !!(search || status || severity || kind || where || lateOnly || urgentOnly || noTaskOnly)
  const clear = () => {
    setSearch(''); setStatus(''); setSeverity(''); setKind(''); setWhere(''); setLateOnly(''); setUrgentOnly(''); setNoTaskOnly('')
  }

  // ── Figures
  const stats = React.useMemo(() => {
    const weekAgo = now - 7 * DAY
    const fixedWeek = issues.filter((i) => i.status.toUpperCase() === 'RESOLVED' && i.resolved_at && new Date(i.resolved_at).getTime() >= weekAgo)
    const fixed = issues.filter((i) => i.status.toUpperCase() === 'RESOLVED' && i.resolved_at)
    const took = fixed.map((i) => waited(i, now)).sort((a, b) => a - b)
    return {
      urgent: open.filter(isUrgent).length,
      late: open.filter(isLate).length,
      lost: open.reduce((t, i) => t + (i.delay_duration_minutes || 0), 0),
      fixedWeek: fixedWeek.length,
      // The middle one: one issue left for a month should not make every fix look slow.
      typicalFix: took.length ? took[Math.floor(took.length / 2)] : null,
      urgentNotSeen: open.filter((i) => isUrgent(i) && i.status.toUpperCase() === 'OPEN').length,
      noTask: tasksOn && tasksQuery.isSuccess ? open.filter((i) => isUrgent(i) && !tasksByIssue.has(i.id)).length : 0,
    }
  }, [issues, open, now, isLate, tasksOn, tasksQuery.isSuccess, tasksByIssue])

  /** A link to this page with some filters set (and the rest cleared), keeping the project. */
  const filterLink = (set: Record<string, string>) => {
    const next = new URLSearchParams()
    for (const k of ['project', 'site']) if (params.get(k)) next.set(k, params.get(k)!)
    for (const [k, v] of Object.entries(set)) next.set(k, v)
    return `/issues?${next}`
  }

  // ── How many of each kind and at each site, in the chosen state: the counts in the Kind and Site menus.
  const breakdownBase = React.useMemo(() => issues.filter(inStatus), [issues, inStatus])
  const byKind = React.useMemo(() => countBy(breakdownBase, (i) => i.issue_type.toUpperCase()), [breakdownBase])
  const bySite = React.useMemo(() => countBy(breakdownBase, (i) => i.site_id), [breakdownBase])

  // Sites the issue can be reported on: the scope's site, else every site in view.
  const siteChoices = React.useMemo(
    () =>
      [...names.entries()]
        .filter(([id, n]) => (siteId ? id === siteId : !projectId || n.projectId === projectId))
        .sort(([, x], [, y]) => (x.project + x.name).localeCompare(y.project + y.name)),
    [names, siteId, projectId],
  )
  const sitesWithIssues = React.useMemo(() => [...new Set(issues.map((i) => i.site_id))], [issues])

  // ── Acting on issues: one or several (ticked).
  const [picked, setPicked] = React.useState<Set<string>>(new Set())
  const togglePick = (id: string) => setPicked((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n })
  const pickedOpen = issues.filter((i) => picked.has(i.id) && !isClosed(i.status))
  const [closing, setClosing] = React.useState<{ ids: string[]; how: 'resolve' | 'wontfix' } | null>(null)
  const [notes, setNotes] = React.useState('')
  const [busy, setBusy] = React.useState(false)

  const run = async (ids: string[], act: (id: string) => Promise<unknown>, done: string, failed: string) => {
    setBusy(true)
    const results = await Promise.allSettled(ids.map(act))
    setBusy(false)
    const bad = results.filter((r) => r.status === 'rejected').length
    if (bad === 0) toast.success(done)
    else toast.error(failed, bad === ids.length ? 'Please try again.' : `${ids.length - bad} done, ${bad} could not be changed.`)
    setPicked(new Set())
    reload()
    queryClient.invalidateQueries({ queryKey: ['issue-tasks'] })
  }
  const label = (ids: string[]) => {
    if (ids.length !== 1) return `${ids.length} issues`
    const i = issues.find((x) => x.id === ids[0])
    return i ? `${kindWord(i.issue_type)} on ${siteName(i)}` : 'The issue'
  }
  const acknowledge = (ids: string[]) => run(ids, acknowledgeSiteIssueApi, `Marked seen: ${label(ids)}`, 'Could not mark it seen')
  const finishClosing = async () => {
    if (!closing) return
    const { ids, how } = closing
    await run(
      ids,
      (id) => (how === 'resolve' ? resolveSiteIssueApi(id, notes) : wontFixSiteIssueApi(id, notes)),
      how === 'resolve' ? `Fixed: ${label(ids)}` : `Closed as won't fix: ${label(ids)}`,
      'Could not close it',
    )
    setClosing(null)
    setNotes('')
  }

  // ── The panel: the issue from the list, or (a closed one the list hides, a link) asked for by its id.
  const fromList = issues.find((i) => i.id === openId)
  const linked = useQuery({
    queryKey: ['site-issue', openId],
    queryFn: () => fetchSiteIssueApi(openId),
    enabled: !!openId && !fromList && issuesQuery.isSuccess,
    retry: false,
  })
  React.useEffect(() => {
    if (linked.isError) {
      toast.error('Issue not found', 'It may have been removed, or it is on a site you do not see.')
      setOpenId('')
    }
  }, [linked.isError, setOpenId, toast])
  const openIssue = fromList ?? linked.data
  const at = listed.findIndex((i) => i.id === openId)
  const stepTo = (d: -1 | 1) => {
    const next = listed[at + d]
    if (next) setOpenId(next.id)
  }

  // ── Reporting one
  const [reportOpen, setReportOpen] = React.useState(false)
  const [newSiteId, setNewSiteId] = React.useState('')
  const [newKind, setNewKind] = React.useState('OTHER')
  const [newSeverity, setNewSeverity] = React.useState('MEDIUM')
  const [newNarrative, setNewNarrative] = React.useState('')
  const [newDelay, setNewDelay] = React.useState('30')
  const openReport = () => {
    setNewSiteId(siteId || where || (siteChoices.length === 1 ? siteChoices[0][0] : ''))
    setReportOpen(true)
  }
  const report = async (e: React.FormEvent) => {
    e.preventDefault()
    const site = names.get(newSiteId)
    if (!site) {
      toast.error('Pick a site', 'Choose which site the issue is on.')
      return
    }
    setBusy(true)
    try {
      const made = await createSiteIssueApi({
        project_id: site.projectId,
        site_id: newSiteId,
        issue_type: newKind,
        severity: newSeverity,
        narrative: newNarrative,
        delay_duration_minutes: parseInt(newDelay, 10) || 0,
      })
      toast.success('Issue reported', `${kindWord(newKind)} on ${site.name} is now open.`)
      setReportOpen(false)
      setNewNarrative('')
      reload()
      if (made?.id) openPanel(made.id)
    } catch {
      toast.error('Could not report the issue', 'Please try again.')
    } finally {
      setBusy(false)
    }
  }

  const exportShown = () =>
    exportCsv(
      'issues.csv',
      ['Kind', 'Severity', 'Status', 'Site', 'What happened', 'Happened', 'Open for / took (days)', 'Time lost (min)', 'Closed', 'How it was closed', 'Reported by', 'Tasks'],
      listed.map((i) => [
        kindWord(i.issue_type),
        SEVERITY_WORD[i.severity.toUpperCase()] ?? i.severity,
        STATE[i.status.toUpperCase()]?.label ?? i.status,
        siteName(i),
        i.narrative ?? '',
        dayWord(i.occurred_at),
        Math.round((waited(i, now) / DAY) * 10) / 10,
        i.delay_duration_minutes ?? 0,
        i.resolved_at ? dayWord(i.resolved_at) : '',
        i.resolution_notes ?? '',
        personName(i.reported_by_user_id) ?? '',
        (tasksByIssue.get(i.id) ?? []).map((t) => t.ref).join(' '),
      ]),
    )

  const cols = columns(now, siteName, personName, tasksByIssue)
  const allOnPageOpen = paged.shown.filter((i) => !isClosed(i.status))
  const allPicked = allOnPageOpen.length > 0 && allOnPageOpen.every((i) => picked.has(i.id))

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <PageHeader
        title="Issues"
        actions={
          <>
            <Button size="sm" className="gap-1.5 font-semibold" onClick={openReport} data-guide="issues.add">
              <Plus className="size-4" /> Report issue
            </Button>
            <Button variant="ghost" size="icon" className="size-8" onClick={reload} disabled={issuesQuery.isFetching} title="Refresh" aria-label="Refresh">
              <RefreshCw className={cn('size-4', issuesQuery.isFetching && 'animate-spin')} />
            </Button>
          </>
        }
      />

      {issuesQuery.isError ? (
        // Never "nothing is stuck": a failed load must not look like good news.
        <Callout tone="draft" icon={TriangleAlert} action={<Button variant="outline" size="sm" className="bg-background" onClick={reload}>Try again</Button>}>
          The issues could not be loaded.
        </Callout>
      ) : loading ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-20 rounded-xl" />
          {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-14 rounded-lg" />)}
        </div>
      ) : issues.length === 0 ? (
        <EmptyState icon={CircleCheck} title="No issues reported" about="When the site says something is stuck, it shows here." whatsapp="No water since morning at the compound wall" />
      ) : (
        <>
          <KpiStrip
            guide="issues.stats"
            stats={[
              { label: 'Open', icon: CircleDot, value: open.length || '—', tone: open.length ? 'attention' : 'good', hint: open.length ? `${open.filter((i) => i.status.toUpperCase() === 'OPEN').length} not seen yet` : 'nothing stuck', to: filterLink({}) },
              { label: 'High or critical', icon: Siren, value: stats.urgent || '—', tone: stats.urgent ? 'bad' : 'good', of: open.length || undefined, to: filterLink({ urgent: '1' }) },
              { label: `Waiting ${LATE_DAYS}+ days`, icon: Hourglass, value: stats.late || '—', tone: stats.late ? 'bad' : 'good', of: open.length || undefined, to: filterLink({ late: '1', sort: 'oldest' }) },
              { label: 'Fixed this week', icon: CircleCheck, value: stats.fixedWeek || '—', tone: stats.fixedWeek ? 'good' : 'default', hint: stats.typicalFix != null ? `usually in ${spanWord(stats.typicalFix)}` : undefined, to: filterLink({ status: 'RESOLVED', sort: 'newest' }) },
            ]}
          />

          {/* One thing to do at most: the most urgent. */}
          {stats.urgentNotSeen > 0 ? (
            <ActionChip icon={Siren} tone="bad" to={filterLink({ status: 'OPEN', urgent: '1' })} action="Show them">
              <span className="font-semibold tabular-nums">{stats.urgentNotSeen}</span> high or critical {stats.urgentNotSeen === 1 ? 'issue nobody has' : 'issues nobody has'} seen yet
            </ActionChip>
          ) : stats.noTask > 0 ? (
            <ActionChip icon={ListTodo} to={filterLink({ urgent: '1', notask: '1' })} action="Give them to someone">
              <span className="font-semibold tabular-nums">{stats.noTask}</span> urgent {stats.noTask === 1 ? 'issue has' : 'issues have'} no task
            </ActionChip>
          ) : null}

          <StateBar
              guide="issues.states"
              strip={false}
              items={STATES.map((s) => ({ ...s, count: beforeStatus.filter((i) => i.status.toUpperCase() === s.value).length }))}
              value={status === 'ALL' ? '' : status}
              onChange={setStatus}
              extra={
                <>
                  <ToggleChip on={!!urgentOnly} onClick={() => setUrgentOnly(urgentOnly ? '' : '1')} icon={Siren} count={open.filter(isUrgent).length} label="high or critical" tone="bad" />
                  <ToggleChip on={!!lateOnly} onClick={() => setLateOnly(lateOnly ? '' : '1')} icon={Hourglass} count={stats.late} label={`waiting ${LATE_DAYS}+ days`} tone="bad" />
                  {noTaskOnly && (
                    <ToggleChip on onClick={() => setNoTaskOnly('')} icon={ListTodo} count={beforeStatus.length} label="with no task" />
                  )}
                  {status !== 'ALL' && (
                    <button type="button" className="text-xs text-muted-foreground hover:text-foreground hover:underline" onClick={() => setStatus('ALL')}>
                      Show all states
                    </button>
                  )}
                </>
              }
            >
            <div className="flex flex-wrap items-center gap-2" data-guide="issues.search">
              <SearchBox value={search} onChange={setSearch} placeholder="Search issues, sites, people" label="Search issues" size="sm" />
              <FilterSelect value={severity} onChange={setSeverity} all="Any severity" label="Severity" options={SEVERITIES.map((s) => ({ value: s, label: SEVERITY_WORD[s] }))} />
              <FilterSelect value={kind} onChange={setKind} all="Any kind" label="Kind" options={withPicked(byKind, kind).map(([k, n]) => ({ value: k, label: `${kindWord(k)} · ${n}` }))} />
              {sitesWithIssues.length > 1 && (
                <FilterSelect value={where} onChange={setWhere} all="Every site" label="Site" options={withPicked(bySite, where).map(([s, n]) => ({ value: s, label: `${names.get(s)?.name || '—'} · ${n}` }))} />
              )}
              <ClearButton show={any} onClick={clear} size="sm" />
              <span className="ml-auto flex flex-wrap items-center gap-2">
                <span className="text-xs text-muted-foreground tabular-nums">{listed.length === issues.length ? listed.length : `${listed.length} of ${issues.length}`}</span>
                <SortSelect value={col ? '' : sort} options={SORTS} onChange={(v) => { setSort(v); clearCol() }} label="Sort the issues" size="sm" />
                <ShowSwitch show={show} onShow={setShow} label="How to show the issues" />
                <ActionButton kind="export-excel" size="sm" className="h-8" disabled={listed.length === 0} onClick={exportShown} title="The issues shown, as a CSV file (opens in Excel)">
                  <span className="hidden sm:inline">{any ? 'Export shown' : 'Export'}</span>
                </ActionButton>
              </span>
            </div>
          </StateBar>

          <BulkBar count={picked.size} onClear={() => setPicked(new Set())}>
            <Button size="sm" variant="secondary" className="h-7 gap-1" disabled={busy || !pickedOpen.some((i) => i.status.toUpperCase() === 'OPEN')} onClick={() => acknowledge(pickedOpen.filter((i) => i.status.toUpperCase() === 'OPEN').map((i) => i.id))}>
              <Eye className="size-3.5" /> Mark seen
            </Button>
            <Button size="sm" variant="secondary" className="h-7 gap-1" disabled={busy || !pickedOpen.length} onClick={() => setClosing({ ids: pickedOpen.map((i) => i.id), how: 'resolve' })}>
              <Check className="size-3.5" /> Mark fixed
            </Button>
            <Button size="sm" variant="ghost" className="h-7 text-background hover:bg-background/10 hover:text-background" disabled={busy || !pickedOpen.length} onClick={() => setClosing({ ids: pickedOpen.map((i) => i.id), how: 'wontfix' })}>
              Won't fix
            </Button>
          </BulkBar>

          {listed.length === 0 ? (
            status === '' && !any ? (
              <EmptyState icon={CircleCheck} title="Nothing is stuck right now" about="Every issue is closed." />
            ) : (
              <NoMatch noun="issue" onClear={clear} />
            )
          ) : show === 'numbers' ? (
            <NumbersTable
              rows={paged.shown}
              rowKey={(i) => i.id}
              first={NAME}
              columns={cols}
              edge={edgeOf}
              col={col}
              dir={dir}
              onSort={sortCol}
              onOpen={(i) => openPanel(i.id)}
              openTitle="Open the issue"
              guide="issues.list"
              minWidth={1080}
              footer="Open for: since it happened · took: until it was closed · time lost: as reported from site"
            />
          ) : (
            <div className="overflow-hidden rounded-xl border bg-card" data-guide="issues.list">
              <table className="w-full text-sm">
                <thead className="bg-muted/50 text-xs text-muted-foreground">
                  <tr>
                    <th className="w-8 py-2 pl-3">
                      <input
                        type="checkbox"
                        className="size-3.5 accent-foreground align-middle"
                        aria-label="Tick the open issues on this page"
                        checked={allPicked}
                        disabled={allOnPageOpen.length === 0}
                        onChange={() => setPicked((s) => { const n = new Set(s); for (const i of allOnPageOpen) { if (allPicked) n.delete(i.id); else n.add(i.id) } return n })}
                      />
                    </th>
                    <th className="px-3 py-2 text-left font-medium">Issue</th>
                    <th className="hidden w-36 px-3 py-2 text-left font-medium md:table-cell">Waiting</th>
                    <th className="hidden w-44 px-3 py-2 text-left font-medium lg:table-cell">Task</th>
                    <th className="px-3 py-2 text-right font-medium">State</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {paged.shown.map((i) => (
                    <IssueRow
                      key={i.id}
                      issue={i}
                      now={now}
                      site={siteName(i)}
                      reporter={personName(i.reported_by_user_id)}
                      tasks={tasksByIssue.get(i.id) ?? []}
                      picked={picked.has(i.id)}
                      onPick={() => togglePick(i.id)}
                      onOpen={() => openPanel(i.id)}
                      onSeen={() => acknowledge([i.id])}
                      onFixed={() => setClosing({ ids: [i.id], how: 'resolve' })}
                      busy={busy}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Pager {...paged.pager} noun="issues" />
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
            <Legend items={[{ tone: 'bad', label: 'Critical' }, { tone: 'attention', label: 'High' }, { tone: 'info', label: 'Medium' }, { tone: 'default', label: 'Low or closed' }]} />
            <span className="text-xs text-muted-foreground">Waiting turns amber after a day, red after {LATE_DAYS}</span>
          </div>
        </>
      )}

      {/* ── Report an issue ── */}
      <Dialog open={reportOpen} onOpenChange={setReportOpen}>
        <DialogContent className="sm:max-w-md">
          <form onSubmit={report}>
            <DialogHeader>
              <DialogTitle className="text-base font-semibold">Report an issue</DialogTitle>
              <DialogDescription>Something stopping or slowing work on a site.</DialogDescription>
            </DialogHeader>
            <div className="space-y-3.5 py-4 text-sm">
              <div className="space-y-1">
                <label className="font-medium" htmlFor="issue-site">Site</label>
                <Select value={newSiteId} onValueChange={setNewSiteId}>
                  <SelectTrigger id="issue-site" className="h-9"><SelectValue placeholder="Pick a site" /></SelectTrigger>
                  <SelectContent>
                    {siteChoices.map(([id, n]) => <SelectItem key={id} value={id}>{n.name} · {n.project}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <span className="font-medium">What kind of issue</span>
                {/* The kinds as tiles with their icons: one tap, no list to read. */}
                <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
                  {KINDS.map((k) => (
                    <button
                      key={k.value}
                      type="button"
                      aria-pressed={newKind === k.value}
                      onClick={() => setNewKind(k.value)}
                      className={cn('flex items-center gap-1.5 rounded-lg border px-2 py-1.5 text-left text-xs transition', newKind === k.value ? 'border-foreground bg-foreground text-background' : 'hover:bg-muted/50')}
                    >
                      <k.icon className="size-3.5 shrink-0" aria-hidden />
                      <span className="truncate">{k.label}</span>
                    </button>
                  ))}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <span className="font-medium">How serious</span>
                  <div className="flex gap-1">
                    {[...SEVERITIES].reverse().map((s) => (
                      <button
                        key={s}
                        type="button"
                        aria-pressed={newSeverity === s}
                        onClick={() => setNewSeverity(s)}
                        className={cn('flex-1 rounded-md px-1 py-1.5 text-[11px] font-semibold transition', TONE[SEVERITY_TONE[s]].pill, newSeverity === s ? 'ring-2 ring-foreground/70' : 'opacity-60 hover:opacity-100')}
                      >
                        {SEVERITY_WORD[s]}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="space-y-1">
                  <label className="font-medium" htmlFor="issue-lost">Time lost (minutes)</label>
                  <Input id="issue-lost" type="number" min={0} value={newDelay} onChange={(e) => setNewDelay(e.target.value)} className="h-9" placeholder="30" />
                </div>
              </div>
              <div className="space-y-1">
                <label className="font-medium" htmlFor="issue-what">What happened</label>
                <textarea
                  id="issue-what"
                  value={newNarrative}
                  onChange={(e) => setNewNarrative(e.target.value)}
                  placeholder="e.g. Cement not delivered, slab pour moved to tomorrow"
                  className="min-h-24 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-2xs focus-visible:ring-1 focus-visible:ring-ring focus-visible:outline-none"
                />
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setReportOpen(false)}>Cancel</Button>
              <Button type="submit" disabled={busy || !newSiteId} className="font-semibold">{busy ? 'Reporting…' : 'Report issue'}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* ── Fixed / won't fix: one or several ── */}
      <Dialog open={!!closing} onOpenChange={(o) => { if (!o) { setClosing(null); setNotes('') } }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-base font-semibold">{closing?.how === 'wontfix' ? 'Close without fixing?' : 'Mark it fixed?'}</DialogTitle>
            <DialogDescription>
              {closing ? label(closing.ids) : ''}
              {closing?.how === 'wontfix' ? ': closed, not marked fixed.' : ': closed as fixed.'}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-3 text-sm">
            {closing?.ids.length === 1 && (
              <div className="rounded-lg border bg-muted/20 p-3 text-muted-foreground">
                {issues.find((i) => i.id === closing.ids[0])?.narrative || openIssue?.narrative || 'No description'}
              </div>
            )}
            <div className="space-y-1">
              <label className="font-medium" htmlFor="issue-notes">{closing?.how === 'wontfix' ? 'Why' : 'How was it fixed? (optional)'}</label>
              <textarea
                id="issue-notes"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder={closing?.how === 'wontfix' ? 'e.g. Work moved to another block' : 'e.g. Pump replaced, cement arrived'}
                className="min-h-20 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-2xs focus-visible:ring-1 focus-visible:ring-ring focus-visible:outline-none"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => { setClosing(null); setNotes('') }}>Cancel</Button>
            <Button disabled={busy} onClick={finishClosing} variant={closing?.how === 'wontfix' ? 'secondary' : 'default'} className="font-semibold">
              {busy ? 'Saving…' : closing?.how === 'wontfix' ? "Close as won't fix" : 'Mark fixed'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── The issue (WEB-36: the side-panel layout, detail-sheet.tsx) ── */}
      <Sheet open={!!openId} onOpenChange={(o) => { if (!o) setOpenId('') }}>
        <SheetContent className="w-full gap-0 overflow-y-auto p-0 sm:max-w-md">
          {openIssue ? (
            <IssuePanel
              issue={openIssue}
              now={now}
              site={siteName(openIssue)}
              reporter={personName(openIssue.reported_by_user_id)}
              tasks={tasksByIssue.get(openIssue.id) ?? []}
              tasksOn={tasksOn}
              sameSite={open.filter((i) => i.site_id === openIssue.site_id && i.id !== openIssue.id)}
              position={at >= 0 ? { at, of: listed.length } : null}
              onStep={stepTo}
              onOpen={setOpenId}
              onSeen={() => acknowledge([openIssue.id])}
              onFixed={() => setClosing({ ids: [openIssue.id], how: 'resolve' })}
              onWontFix={() => setClosing({ ids: [openIssue.id], how: 'wontfix' })}
              onCopy={() => {
                const url = `${window.location.origin}/issues?id=${openIssue.id}`
                navigator.clipboard?.writeText(url).then(() => toast.success('Link copied'), () => toast.error('Could not copy the link'))
              }}
            />
          ) : (
            <div className="flex flex-col gap-3 p-5">
              <SheetTitle className="sr-only">Issue</SheetTitle>
              <Skeleton className="h-24 rounded-xl" />
              <Skeleton className="h-40 rounded-xl" />
            </div>
          )}
        </SheetContent>
      </Sheet>
    </div>
  )
}

// ─── Parts ────────────────────────────────────────────────────────────────────

/** A menu's choices, keeping the picked one even when none are left in the chosen state (else the menu shows blank). */
const withPicked = (rows: [string, number][], picked: string): [string, number][] => (picked && !rows.some(([k]) => k === picked) ? [...rows, [picked, 0]] : rows)

function countBy(rows: SiteIssueItem[], key: (i: SiteIssueItem) => string): [string, number][] {
  const m = new Map<string, number>()
  for (const r of rows) m.set(key(r), (m.get(key(r)) ?? 0) + 1)
  return [...m.entries()].sort((a, b) => b[1] - a[1])
}

/** A small select whose first choice is "any": the value '' in the address. */
function FilterSelect({ value, onChange, all, label, options }: { value: string; onChange: (v: string) => void; all: string; label: string; options: { value: string; label: string }[] }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-label={label}
      className={cn('h-8 max-w-36 rounded-lg border bg-card px-2 text-sm outline-none', value && 'border-foreground/60 font-medium')}
    >
      <option value="">{all}</option>
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  )
}

function SeverityPill({ severity }: { severity: string }) {
  const s = severity.toUpperCase()
  return <Pill tone={SEVERITY_TONE[s] ?? 'muted'} size="xs">{SEVERITY_WORD[s] ?? severity}</Pill>
}

function StatePill({ status }: { status: string }) {
  const s = STATE[status.toUpperCase()] ?? STATE.OPEN
  return <Pill tone={s.tone} icon={s.icon}>{s.label}</Pill>
}

/** How long it has waited (open) or took (closed), coloured by how long. */
function AgePill({ issue, now }: { issue: SiteIssueItem; now: number }) {
  const closed = isClosed(issue.status)
  const ms = waited(issue, now)
  return (
    <Pill tone={ageTone(issue, now)} icon={closed ? CircleCheck : Hourglass} title={closed ? `Happened ${timeWord(issue.occurred_at)}, closed ${issue.resolved_at ? timeWord(issue.resolved_at) : ''}` : `Happened ${timeWord(issue.occurred_at)}`}>
      {closed ? (issue.resolved_at ? `took ${spanWord(ms)}` : 'closed') : spanWord(ms)}
    </Pill>
  )
}

function TaskChip({ tasks }: { tasks: Task[] }) {
  if (!tasks.length) return null
  const live = tasks.find((t) => t.status !== 'done' && t.status !== 'cancelled') ?? tasks[0]
  const tone: Tone = live.status === 'done' ? 'good' : live.overdue ? 'bad' : live.status === 'blocked' ? 'attention' : 'info'
  return (
    <Link
      to={`/tasks?id=${live.id}`}
      onClick={(e) => e.stopPropagation()}
      title={`${live.ref}: ${live.title}`}
      className={cn('inline-flex max-w-full items-center gap-1 rounded-md px-1.5 py-px text-[11px] font-medium hover:underline', TONE[tone].pill)}
    >
      <ListTodo className="size-3 shrink-0" aria-hidden />
      <span className="truncate">
        {live.assigned_to ?? 'Nobody yet'}
        {live.status === 'done' ? ' · done' : live.overdue ? ` · ${live.days_late}d late` : live.due_date ? ` · ${dayWord(live.due_date)}` : ''}
      </span>
      {tasks.length > 1 && <span className="opacity-70">+{tasks.length - 1}</span>}
    </Link>
  )
}

function IssueRow({
  issue: i, now, site, reporter, tasks, picked, onPick, onOpen, onSeen, onFixed, busy,
}: {
  issue: SiteIssueItem; now: number; site: string; reporter?: string; tasks: Task[]; picked: boolean
  onPick: () => void; onOpen: () => void; onSeen: () => void; onFixed: () => void; busy: boolean
}) {
  const closed = isClosed(i.status)
  const Icon = kindIcon(i.issue_type)
  const stop = (e: React.SyntheticEvent) => e.stopPropagation()
  return (
    <tr className={cn('group cursor-pointer align-top hover:bg-muted/30', closed && 'text-muted-foreground', picked && 'bg-muted/40')} onClick={onOpen} title="Open the issue" data-record-id={i.id}>
      <td className="w-8 py-3 pl-3" onClick={stop}>
        {!closed && <input type="checkbox" className="size-3.5 accent-foreground" checked={picked} onChange={onPick} aria-label={`Tick ${kindWord(i.issue_type)} on ${site}`} />}
      </td>
      <td className="relative px-3 py-2.5">
        <span className={cn('absolute top-2 bottom-2 left-0 w-1 rounded-full', edgeOf(i))} aria-hidden />
        <span className="flex items-start gap-2.5">
          <span className={cn('mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md', closed ? TONE.muted.pill : TONE[SEVERITY_TONE[i.severity.toUpperCase()] ?? 'muted'].pill)} aria-hidden>
            <Icon className="size-3.5" />
          </span>
          <span className="flex min-w-0 flex-col gap-0.5">
            <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
              <span className={cn('font-medium', !closed && 'text-foreground')}>{kindWord(i.issue_type)}</span>
              {!closed && <SeverityPill severity={i.severity} />}
            </span>
            {i.narrative && <span className="line-clamp-2 text-sm text-muted-foreground sm:line-clamp-1">{i.narrative}</span>}
            <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
              <span className="inline-flex items-center gap-0.5"><MapPin className="size-3" aria-hidden />{site}</span>
              <span>{dayWord(i.occurred_at)}</span>
              {reporter && <span>by {reporter}</span>}
              {i.delay_duration_minutes ? <span className="inline-flex items-center gap-0.5 font-medium text-draft"><Clock className="size-3" aria-hidden />{minutesWord(i.delay_duration_minutes)} lost</span> : null}
            </span>
            {/* Below a laptop the waiting and the task fold under the name (docs/DESIGN.md section 8). */}
            <span className="flex flex-wrap items-center gap-1.5 pt-1 lg:hidden" onClick={stop}>
              <span className="md:hidden"><AgePill issue={i} now={now} /></span>
              <TaskChip tasks={tasks} />
            </span>
          </span>
        </span>
      </td>
      <td className="hidden px-3 py-2.5 md:table-cell"><AgePill issue={i} now={now} /></td>
      <td className="hidden max-w-44 px-3 py-2.5 lg:table-cell" onClick={stop}>
        {tasks.length ? <TaskChip tasks={tasks} /> : !closed ? <span className="text-[11px] text-muted-foreground">—</span> : null}
      </td>
      <td className="w-px px-3 py-2.5 text-right" onClick={stop}>
        <span className="flex flex-col items-end gap-1.5">
          <StatePill status={i.status} />
          {!closed && (
            <span className="hidden items-center gap-1 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100 sm:flex pointer-fine:opacity-0">
              {i.status.toUpperCase() === 'OPEN' && (
                <Button variant="ghost" size="sm" className="h-7 gap-1 px-2 text-xs" onClick={onSeen} disabled={busy} title="Tell the site someone is on it">
                  <Eye className="size-3.5" /> Mark seen
                </Button>
              )}
              <Button variant="outline" size="sm" className="h-7 gap-1 px-2 text-xs" onClick={onFixed} disabled={busy}>
                <Check className="size-3.5" /> Mark fixed
              </Button>
            </span>
          )}
        </span>
      </td>
    </tr>
  )
}

// ─── Numbers view ─────────────────────────────────────────────────────────────

const NAME: NumberColumn<SiteIssueItem> = {
  key: 'kind',
  label: 'Issue',
  text: true,
  sortValue: (i) => kindWord(i.issue_type).toLowerCase(),
  cell: (i) => (
    <span className="flex flex-col">
      <span className="font-medium">{kindWord(i.issue_type)}</span>
      {i.narrative && <span className="line-clamp-1 max-w-64 text-xs text-muted-foreground">{i.narrative}</span>}
    </span>
  ),
}

function columns(
  now: number,
  siteName: (i: SiteIssueItem) => string,
  personName: (id?: string | null) => string | undefined,
  tasksByIssue: Map<string, Task[]>,
): NumberColumn<SiteIssueItem>[] {
  return [
    { key: 'site', label: 'Site', text: true, sortValue: (i) => siteName(i).toLowerCase(), cell: (i) => siteName(i) },
    { key: 'severity', label: 'Severity', text: true, sortValue: (i) => SEVERITY_RANK[i.severity.toUpperCase()] ?? 9, cell: (i) => <SeverityPill severity={i.severity} /> },
    { key: 'state', label: 'State', text: true, sortValue: (i) => STATES.findIndex((s) => s.value === i.status.toUpperCase()), cell: (i) => <StatePill status={i.status} /> },
    {
      key: 'days',
      label: 'Open for / took',
      title: 'Days since it happened (open) or until it was closed',
      sortValue: (i) => waited(i, now),
      cell: (i) => `${isClosed(i.status) ? 'took ' : ''}${spanWord(waited(i, now))}`,
      tone: (i) => (isClosed(i.status) ? undefined : TONE[ageTone(i, now)].text),
    },
    { key: 'lost', label: 'Time lost', sortValue: (i) => i.delay_duration_minutes || null, cell: (i) => (i.delay_duration_minutes ? minutesWord(i.delay_duration_minutes) : null) },
    { key: 'happened', label: 'Happened', sortValue: (i) => new Date(i.occurred_at).getTime(), cell: (i) => dayWord(i.occurred_at) },
    { key: 'closed', label: 'Closed', sortValue: (i) => (i.resolved_at ? new Date(i.resolved_at).getTime() : null), cell: (i) => (i.resolved_at ? dayWord(i.resolved_at) : null) },
    { key: 'by', label: 'Reported by', text: true, sortValue: (i) => personName(i.reported_by_user_id)?.toLowerCase() ?? null, cell: (i) => personName(i.reported_by_user_id) ?? null },
    { key: 'task', label: 'Task', text: true, sortValue: (i) => tasksByIssue.get(i.id)?.[0]?.assigned_to?.toLowerCase() ?? null, cell: (i) => (tasksByIssue.get(i.id)?.length ? <TaskChip tasks={tasksByIssue.get(i.id)!} /> : null) },
  ]
}

// ─── The panel ────────────────────────────────────────────────────────────────

function IssuePanel({
  issue, now, site, reporter, tasks, tasksOn, sameSite, position, onStep, onOpen, onSeen, onFixed, onWontFix, onCopy,
}: {
  issue: SiteIssueItem
  now: number
  site: string
  reporter?: string
  tasks: Task[]
  tasksOn: boolean
  sameSite: SiteIssueItem[]
  position: { at: number; of: number } | null
  onStep: (d: -1 | 1) => void
  onOpen: (id: string) => void
  onSeen: () => void
  onFixed: () => void
  onWontFix: () => void
  onCopy: () => void
}) {
  const severity = issue.severity.toUpperCase()
  const status = issue.status.toUpperCase()
  const closed = isClosed(status)
  const tone = closed ? (status === 'RESOLVED' ? 'in' : 'neutral') : severity === 'CRITICAL' ? 'out' : severity === 'HIGH' ? 'warn' : 'neutral'

  // ← and → walk the list while the panel is open (never while typing).
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      if (e.metaKey || e.ctrlKey || e.altKey || t?.closest('input, textarea, select, [contenteditable="true"]')) return
      if (e.key === 'ArrowLeft') onStep(-1)
      if (e.key === 'ArrowRight') onStep(1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onStep])

  // What happened to it, in order. "Seen" has no time of its own on the server.
  const steps: { label: string; when?: string; tone: Tone; done: boolean }[] = [
    { label: 'Happened', when: timeWord(issue.occurred_at), tone: 'attention', done: true },
    { label: reporter ? `Reported by ${reporter}` : 'Reported', when: timeWord(issue.created_at), tone: 'muted', done: true },
    { label: 'Seen', tone: 'info', done: status !== 'OPEN' && status !== 'CANCELLED' },
    closed
      ? { label: `${STATE[status]?.label ?? status}${issue.resolved_at ? ` after ${spanWord(waited(issue, now))}` : ''}`, when: issue.resolved_at ? timeWord(issue.resolved_at) : undefined, tone: status === 'RESOLVED' ? 'good' : 'muted', done: true }
      : { label: `Open ${spanWord(waited(issue, now))}`, tone: ageTone(issue, now), done: false },
  ]

  return (
    <>
      <div className="flex items-center gap-1 border-b px-3 py-1.5 text-xs text-muted-foreground">
        {position && (
          <>
            <Button variant="ghost" size="icon" className="size-7" disabled={position.at <= 0} onClick={() => onStep(-1)} aria-label="Previous issue" title="Previous (←)">
              <ChevronLeft className="size-4" />
            </Button>
            <span className="tabular-nums">{position.at + 1} of {position.of}</span>
            <Button variant="ghost" size="icon" className="size-7" disabled={position.at >= position.of - 1} onClick={() => onStep(1)} aria-label="Next issue" title="Next (→)">
              <ChevronRight className="size-4" />
            </Button>
          </>
        )}
        <Button variant="ghost" size="sm" className="mr-8 ml-auto h-7 gap-1 px-2 text-xs" onClick={onCopy} title="Copy a link to this issue">
          <Copy className="size-3.5" /> Copy link
        </Button>
      </div>

      <SheetHero tone={tone} kicker={closed ? STATE[status]?.label ?? status : `${SEVERITY_WORD[severity] ?? severity} · ${STATE[status]?.label ?? status}`} title={kindWord(issue.issue_type)}>
        <span>{site}</span>
        <span>{timeWord(issue.occurred_at)}</span>
        {issue.delay_duration_minutes ? <span className="font-medium text-foreground">{minutesWord(issue.delay_duration_minutes)} lost</span> : null}
      </SheetHero>

      <SheetSection title="What happened">
        <p className={cn('text-sm leading-relaxed', !issue.narrative && 'text-muted-foreground')}>{issue.narrative || 'No description was given.'}</p>
      </SheetSection>

      <SheetSection title="So far" className="border-t">
        <ol className="flex flex-col gap-0">
          {steps.map((s, n) => (
            <li key={s.label} className="relative flex gap-3 pb-3 last:pb-0">
              {n < steps.length - 1 && <span className="absolute top-3 bottom-0 left-[5px] w-px bg-border" aria-hidden />}
              <span className={cn('relative mt-1 size-[11px] shrink-0 rounded-full border-2', s.done ? cn(TONE[s.tone].dot, 'border-transparent') : 'border-muted-foreground/40 bg-card')} aria-hidden />
              <span className="flex min-w-0 flex-1 items-baseline justify-between gap-2 text-sm">
                <span className={cn(!s.done && 'text-muted-foreground', !s.done && s.tone !== 'muted' && TONE[s.tone].text, 'font-medium')}>{s.label}</span>
                {s.when && <span className="shrink-0 text-xs text-muted-foreground">{s.when}</span>}
              </span>
            </li>
          ))}
        </ol>
      </SheetSection>

      {issue.resolution_notes && (
        <SheetSection title={status === 'RESOLVED' ? 'How it was fixed' : 'Why it was closed'} className="border-t">
          <p className={cn('rounded-lg px-3 py-2 text-sm', status === 'RESOLVED' ? 'bg-success-soft/60' : 'bg-muted/60')}>{issue.resolution_notes}</p>
        </SheetSection>
      )}

      {tasksOn && (tasks.length > 0 || !closed) && (
        <SheetSection title="Who is on it" className="border-t">
          {tasks.length ? (
            <ul className="flex flex-col divide-y rounded-lg border">
              {tasks.map((t) => (
                <li key={t.id}>
                  <Link to={`/tasks?id=${t.id}`} className="flex items-center gap-2 px-3 py-2 text-sm hover:bg-muted/40">
                    <ListTodo className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">{t.title}</span>
                      <span className="block text-xs text-muted-foreground">
                        {t.ref} · {t.assigned_to ?? 'nobody yet'}{t.due_date ? ` · due ${dayWord(t.due_date)}` : ''}{t.activity_name ? ` · ${t.activity_name}` : ''}
                      </span>
                    </span>
                    <Pill tone={t.status === 'done' ? 'good' : t.overdue ? 'bad' : t.status === 'blocked' ? 'attention' : t.status === 'cancelled' ? 'muted' : 'info'} size="xs">
                      {t.status === 'done' ? 'Done' : t.overdue ? `${t.days_late}d late` : t.status === 'blocked' ? 'Blocked' : t.status === 'cancelled' ? 'Cancelled' : t.status === 'doing' ? 'Doing' : 'To do'}
                    </Pill>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">No task yet: give it to someone, with a day.</p>
          )}
        </SheetSection>
      )}

      {sameSite.length > 0 && (
        <SheetSection title={`Also open on ${site}`} className="border-t">
          <ul className="flex flex-col gap-1">
            {sameSite.slice(0, 5).map((o) => {
              const Icon = kindIcon(o.issue_type)
              return (
                <li key={o.id}>
                  <button type="button" className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-sm hover:bg-muted/50" onClick={() => onOpen(o.id)}>
                    <span className={cn('size-2 shrink-0 rounded-full', edgeOf(o))} aria-hidden />
                    <Icon className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                    <span className="min-w-0 flex-1 truncate">{kindWord(o.issue_type)}{o.narrative ? <span className="text-muted-foreground"> · {o.narrative}</span> : null}</span>
                    <AgePill issue={o} now={now} />
                  </button>
                </li>
              )
            })}
          </ul>
          {sameSite.length > 5 && <p className="mt-1 px-1.5 text-xs text-muted-foreground">and {sameSite.length - 5} more</p>}
        </SheetSection>
      )}

      <SheetSection title="Details" className="border-t">
        <Facts>
          <Fact label="Severity"><SeverityPill severity={issue.severity} /></Fact>
          <Fact label="State"><StatePill status={issue.status} /></Fact>
          <Fact label="Site">{site}</Fact>
          {issue.delay_duration_minutes ? <Fact label="Time lost">{minutesWord(issue.delay_duration_minutes)}</Fact> : null}
        </Facts>
        <div className="mt-3"><ByLine name={reporter} detail={timeWord(issue.created_at)} /></div>
      </SheetSection>

      {!closed && (
        <SheetFooter className="flex-row flex-wrap items-center gap-2 border-t px-5 py-3">
          <Button size="sm" className="gap-1.5" onClick={onFixed}>
            <Check className="size-3.5" /> Mark fixed
          </Button>
          {status === 'OPEN' && (
            <Button size="sm" variant="outline" className="gap-1.5" onClick={onSeen}>
              <Eye className="size-3.5" /> Mark seen
            </Button>
          )}
          {/* TSK-03: someone's job, by a day; the task links back to this issue. */}
          <MakeTaskButton prefill={{
            project_id: issue.project_id,
            site_id: issue.site_id,
            site_issue_id: issue.id,
            title: issue.narrative ? `Fix: ${issue.narrative}`.slice(0, 200) : `Fix the ${kindWord(issue.issue_type).toLowerCase()}`,
            from: `From the issue: ${kindWord(issue.issue_type)} on ${site}${issue.narrative ? ` — ${issue.narrative}` : ''}`,
          }} />
          <Button size="sm" variant="ghost" className="ml-auto text-muted-foreground" onClick={onWontFix}>
            Won't fix
          </Button>
        </SheetFooter>
      )}
    </>
  )
}
