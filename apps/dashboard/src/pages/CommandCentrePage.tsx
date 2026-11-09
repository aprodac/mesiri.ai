import * as React from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, LayoutDashboard } from 'lucide-react'
import { usePageTitle } from '@/lib/page-title'
import { useAuth } from '@/lib/AuthContext'
import { fetchLifecycle, type ProjectLifecycle, type Stage } from '@/lib/schedule'
import { fetchPortfolio, type PortfolioRow } from '@/lib/cost'
import { COLOUR_DOT, COLOUR_WORD } from '@/lib/cost-colours'
import { fetchSiteDaysApi, type SiteDayItem } from '@/lib/api'
import { fetchAllOpenIssues } from '@/lib/issues'
import { fetchInbox } from '@/lib/approvals'
import { fetchAttention, type Alert } from '@/lib/attention'
import { hasUpdates, localIsoDate } from '@/lib/site-day'
import { cn } from '@/lib/utils'

// GM-02 (plan docs/plans/gm-pm-plan.md): every project on one screen, worst first. Each column is a module's own
// read (no new API): the schedule (lifecycle list), cost (the portfolio, money roles only), today's reports, open
// issues, Waiting for you and Attention. A row opens the project's cockpit (GM-03); a cell opens the page behind it.
// The landing page and the sidebar order are unchanged: making this the landing page is D-GM1 (shared layout).

const STAGES: { key: Stage | 'live'; label: string }[] = [
  { key: 'live', label: 'Running & handover' },
  { key: 'tender', label: 'Tender & won' },
  { key: 'closed', label: 'Closed' },
]
const LIVE: Stage[] = ['running', 'handover', 'defects']
const day = (iso: string | null | undefined) => (iso ? new Date(iso + 'T00:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) : '–')

interface Row {
  p: ProjectLifecycle
  cost?: PortfolioRow
  sites: SiteDayItem[]
  issues: { open: number; oldest: number; overdue: number }
  waiting: number
  alerts: Alert[]
  orderBy?: Alert
  score: number
}

export default function CommandCentrePage() {
  usePageTitle('Command centre')
  const { me } = useAuth()
  const today = React.useMemo(() => localIsoDate(new Date()), [])
  const opts = { retry: false, staleTime: 60_000 } as const
  const lifecycle = useQuery({ queryKey: ['cc', 'lifecycle'], queryFn: fetchLifecycle, ...opts })
  const portfolio = useQuery({ queryKey: ['cc', 'portfolio'], queryFn: fetchPortfolio, ...opts })
  const days = useQuery({ queryKey: ['cc', 'days', today], queryFn: () => fetchSiteDaysApi(today), ...opts })
  const issues = useQuery({ queryKey: ['cc', 'issues'], queryFn: () => fetchAllOpenIssues(undefined), ...opts })
  const inbox = useQuery({ queryKey: ['cc', 'inbox'], queryFn: () => fetchInbox(null), ...opts })
  const attention = useQuery({ queryKey: ['cc', 'attention'], queryFn: () => fetchAttention(null), ...opts })
  const [stage, setStage] = React.useState<Stage | 'live'>('live')
  const [open, setOpen] = React.useState<Record<string, boolean>>({})
  const money = !portfolio.isError

  const rows: Row[] = React.useMemo(() => {
    const now = Date.now()
    return (lifecycle.data ?? [])
      .filter((p) => (stage === 'live' ? LIVE.includes(p.stage) : stage === 'tender' ? ['tender', 'won'].includes(p.stage) : p.stage === 'closed'))
      .map((p) => {
        const mine = (issues.data ?? []).filter((i) => i.project_id === p.id)
        const alerts = (attention.data?.items ?? []).filter((a) => a.project_id === p.id)
        const cost = portfolio.data?.projects.find((c) => c.project_id === p.id)
        const row: Row = {
          p, cost, alerts,
          sites: (days.data?.items ?? []).filter((s) => s.project_id === p.id),
          issues: {
            open: mine.length,
            oldest: mine.reduce((m, i) => Math.max(m, Math.floor((now - new Date(i.occurred_at).getTime()) / 86_400_000)), 0),
            overdue: mine.filter((i) => i.due_on && i.due_on < today).length,
          },
          waiting: (inbox.data?.items ?? []).filter((r) => r.project_id === p.id).length,
          orderBy: alerts.find((a) => a.kind === 'order'),
          score: 0,
        }
        row.score = alerts.filter((a) => a.severity === 'bad').length * 10 + alerts.length + (p.slip_days > 0 ? 5 : 0)
          + (cost?.colour === 'red' ? 5 : cost?.colour === 'amber' ? 2 : 0)
        return row
      })
      .sort((a, b) => b.score - a.score || a.p.name.localeCompare(b.p.name))
  }, [lifecycle.data, issues.data, attention.data, portfolio.data, days.data, inbox.data, stage, today])

  const live = (lifecycle.data ?? []).filter((p) => LIVE.includes(p.stage))
  const liveIds = new Set(live.map((p) => p.id))
  const sites = (days.data?.items ?? []).filter((s) => liveIds.has(s.project_id))
  const reported = sites.filter(hasUpdates).length
  const late = live.filter((p) => p.slip_days > 0)
  const first = (me?.name || me?.full_name || '').split(' ')[0]
  const hour = new Date().getHours()

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="inline-flex size-10 items-center justify-center rounded-xl bg-yellow-100 text-yellow-800 dark:bg-yellow-950 dark:text-yellow-200">
            <LayoutDashboard className="size-5" />
          </span>
          <div>
            <div className="text-xs text-muted-foreground">Command centre · {live.length} live project{live.length === 1 ? '' : 's'} · {sites.length} sites</div>
            <h1 className="text-2xl leading-tight font-semibold tracking-tight">Good {hour < 12 ? 'morning' : hour < 17 ? 'afternoon' : 'evening'}{first ? `, ${first}` : ''}</h1>
          </div>
        </div>
        <div role="tablist" aria-label="Stage" className="flex gap-0.5 rounded-xl bg-muted p-1">
          {STAGES.map((s) => (
            <button key={s.key} role="tab" type="button" aria-selected={stage === s.key} onClick={() => setStage(s.key)}
              className={cn('h-8 rounded-lg px-3 text-sm whitespace-nowrap', stage === s.key ? 'bg-background font-semibold shadow-sm' : 'text-foreground/75 hover:text-foreground')}>
              {s.label}
            </button>
          ))}
        </div>
      </header>

      <div className="grid grid-cols-2 gap-2 sm:gap-3 lg:grid-cols-4">
        <Stat to="/today" label="Sites reported today" value={`${reported}/${sites.length}`}
          note={sites.length - reported ? `${sites.filter((s) => !hasUpdates(s)).map((s) => s.site_name).slice(0, 2).join(', ')}${sites.length - reported > 2 ? '…' : ''} not yet` : 'All in'}
          tone={sites.length - reported ? 'warn' : 'ok'} />
        <Stat to="/site/approvals" label="Waiting for you" value={String(inbox.data?.counts.total ?? '–')}
          note={inbox.data?.counts.flagged ? `${inbox.data.counts.flagged} flagged by a check` : 'Nothing flagged'} tone={inbox.data?.counts.flagged ? 'bad' : undefined} />
        <Stat to="/site/attention" label="Act now" value={String(attention.data?.counts.bad ?? '–')}
          note={`${attention.data?.counts.warn ?? 0} more worth a look`} tone={attention.data?.counts.bad ? 'bad' : 'ok'} />
        <Stat to="/planning/schedule" label="Projects late" value={`${late.length}/${live.length}`}
          note={late.length ? `Worst: ${[...late].sort((a, b) => b.slip_days - a.slip_days)[0].name}, +${Math.max(...late.map((p) => p.slip_days))} days` : 'All on time'}
          tone={late.length ? 'bad' : 'ok'} />
      </div>

      <div className="overflow-x-auto rounded-xl border">
        <table className="w-full min-w-[960px] text-sm">
          <thead className="bg-muted/60 text-left text-[11px] tracking-wide text-muted-foreground uppercase">
            <tr>
              <th className="px-3 py-2 font-semibold">Project</th>
              <th className="px-3 py-2 font-semibold">Schedule</th>
              {money && <th className="px-3 py-2 font-semibold">Done vs spent</th>}
              {money && <th className="px-3 py-2 font-semibold">Cost</th>}
              <th className="px-3 py-2 font-semibold">Today</th>
              <th className="px-3 py-2 font-semibold">Issues</th>
              <th className="px-3 py-2 font-semibold">For you</th>
              <th className="px-3 py-2 font-semibold">Order</th>
            </tr>
          </thead>
          <tbody>
            {lifecycle.isLoading && <tr><td colSpan={8} className="h-24 animate-pulse bg-muted/30" /></tr>}
            {!lifecycle.isLoading && rows.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-10 text-center text-muted-foreground">No projects at this stage.</td></tr>
            )}
            {rows.map((r) => {
              const bad = r.alerts.some((a) => a.severity === 'bad')
              const isOpen = open[r.p.id]
              const reportedHere = r.sites.filter(hasUpdates).length
              return (
                <React.Fragment key={r.p.id}>
                  <tr className="border-t align-top hover:bg-muted/30">
                    <td className="px-3 py-3">
                      <div className="flex items-start gap-2">
                        <button type="button" aria-label={isOpen ? 'Hide sites' : 'Show sites'} onClick={() => setOpen((o) => ({ ...o, [r.p.id]: !o[r.p.id] }))}
                          className="mt-0.5 text-muted-foreground hover:text-foreground">
                          {isOpen ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                        </button>
                        <span className={cn('mt-1.5 size-2.5 shrink-0 rounded-full', bad ? 'bg-red-600' : r.alerts.length ? 'bg-amber-500' : 'bg-emerald-600')} />
                        <div className="min-w-0">
                          <Link to={`/projects/${r.p.id}/cockpit`} className="font-semibold hover:underline">{r.p.name}</Link>
                          <div className="text-xs text-muted-foreground">{[r.p.stage_label, r.p.client].filter(Boolean).join(' · ')}</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      <Link to={`/planning/schedule?project=${r.p.id}`} className="block">
                        {!r.p.scheduled ? <Chip tone="info">No schedule</Chip>
                          : r.p.slip_days > 0 ? <Chip tone="bad">{r.p.slip_days} days late</Chip>
                            : r.p.late ? <Chip tone="warn">{r.p.late} late</Chip> : <Chip tone="ok">On time</Chip>}
                        <div className="mt-1 text-xs text-muted-foreground">{r.p.forecast_finish ? `Forecast ${day(r.p.forecast_finish)}` : r.p.planned_finish ? `Handover ${day(r.p.planned_finish)}` : ''}</div>
                      </Link>
                    </td>
                    {money && (
                      <td className="px-3 py-3">
                        {r.cost?.percent_done != null ? (
                          <Link to={`/cost/budget?project=${r.p.id}`} className="flex w-36 flex-col gap-1">
                            <Bar value={Number(r.cost.percent_done)} tone="bg-emerald-600" />
                            <Bar value={Number(r.cost.percent_spent ?? 0)} tone={Number(r.cost.percent_spent ?? 0) > Number(r.cost.percent_done) + 5 ? 'bg-red-600' : 'bg-muted-foreground/60'} />
                            <span className="text-xs text-muted-foreground tabular-nums">{Math.round(Number(r.cost.percent_done))}% done · {Math.round(Number(r.cost.percent_spent ?? 0))}% spent</span>
                          </Link>
                        ) : <span className="text-xs text-muted-foreground">{r.cost ? 'No work measured yet' : 'No BOQ yet'}</span>}
                      </td>
                    )}
                    {money && (
                      <td className="px-3 py-3">
                        {r.cost ? (
                          <Link to={`/cost/green-red?project=${r.p.id}`} className="flex flex-col gap-1">
                            <span className="inline-flex items-center gap-1.5"><span className={cn('size-2 rounded-full', COLOUR_DOT[r.cost.colour])} />{COLOUR_WORD[r.cost.colour]}</span>
                            <span className="text-xs text-muted-foreground">This week {COLOUR_WORD[r.cost.week.colour].toLowerCase()}{r.cost.week.red_lines ? `, ${r.cost.week.red_lines} red lines` : ''}</span>
                          </Link>
                        ) : <span className="text-xs text-muted-foreground">–</span>}
                      </td>
                    )}
                    <td className="px-3 py-3">
                      <Link to={`/today?project=${r.p.id}`} className="block">
                        <span className="tabular-nums">{reportedHere}/{r.sites.length}</span> <span className="text-xs text-muted-foreground">sites</span>
                      </Link>
                    </td>
                    <td className="px-3 py-3">
                      <Link to={`/issues?project=${r.p.id}`} className="block">
                        {r.issues.open ? <><span className="tabular-nums">{r.issues.open}</span> <span className="text-xs text-muted-foreground">oldest {r.issues.oldest} d</span></> : <span className="text-xs text-muted-foreground">None</span>}
                        {r.issues.overdue > 0 && <div><Chip tone="bad">{r.issues.overdue} overdue</Chip></div>}
                      </Link>
                    </td>
                    <td className="px-3 py-3">
                      {r.waiting ? <Link to={`/site/approvals?project=${r.p.id}`}><Chip tone="yellow">{r.waiting} waiting</Chip></Link> : <span className="text-xs text-muted-foreground">–</span>}
                    </td>
                    <td className="px-3 py-3 text-xs">
                      {r.orderBy ? <Link to={r.orderBy.action.link} className={cn('hover:underline', r.orderBy.severity === 'bad' ? 'text-red-700 dark:text-red-300' : 'text-draft')}>{r.orderBy.title.replace(/^Order /, '')}</Link> : <span className="text-muted-foreground">–</span>}
                    </td>
                  </tr>
                  {isOpen && r.sites.map((s) => (
                    <tr key={s.site_id} className="bg-muted/20 text-xs">
                      <td className="py-2 pr-3 pl-14">{s.site_name}</td>
                      <td colSpan={money ? 3 : 1} className="px-3 py-2 text-muted-foreground">{s.latest_update ?? (hasUpdates(s) ? 'Updates in' : 'Nothing yet today')}</td>
                      <td className="px-3 py-2">{hasUpdates(s) ? <Chip tone="ok">Reported</Chip> : <Chip tone="warn">Not yet</Chip>}</td>
                      <td className="px-3 py-2 text-muted-foreground">{s.open_issues ? `${s.open_issues} open` : ''}</td>
                      <td colSpan={2} />
                    </tr>
                  ))}
                </React.Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">
        Worst first: act-now alerts, then a late handover and a red forecast. Each figure is the module's own: open a cell for the page behind it.
        {!money && ' Cost columns are shown to the roles that see spending.'}
      </p>
    </div>
  )
}

const TONES = {
  ok: 'bg-success-soft text-success',
  warn: 'bg-draft-soft text-draft',
  bad: 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200',
  info: 'bg-muted text-muted-foreground',
  yellow: 'bg-yellow-100 text-yellow-900 dark:bg-yellow-950 dark:text-yellow-100',
}

function Chip({ tone, children }: { tone: keyof typeof TONES; children: React.ReactNode }) {
  return <span className={cn('inline-flex rounded-full px-2 py-px text-xs font-medium whitespace-nowrap', TONES[tone])}>{children}</span>
}

function Bar({ value, tone }: { value: number; tone: string }) {
  return (
    <span className="relative h-1.5 w-full overflow-hidden rounded-full bg-muted">
      <span className={cn('absolute inset-y-0 left-0 rounded-full', tone)} style={{ width: `${Math.min(Math.max(value, 0), 100)}%` }} />
    </span>
  )
}

function Stat({ to, label, value, note, tone }: { to: string; label: string; value: string; note: string; tone?: 'ok' | 'warn' | 'bad' }) {
  return (
    <Link to={to} className="flex min-w-0 flex-col gap-0.5 rounded-xl border bg-card p-3 transition hover:border-foreground/30 sm:p-3.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-2xl font-semibold tabular-nums">{value}</span>
      <span className={cn('truncate text-xs', tone === 'bad' ? 'text-red-700 dark:text-red-300' : tone === 'warn' ? 'text-draft' : tone === 'ok' ? 'text-success' : 'text-muted-foreground')}>{note}</span>
    </Link>
  )
}
