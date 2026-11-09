import * as React from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { fetchLifecycle, type Stage } from '@/lib/schedule'
import { fetchPortfolio } from '@/lib/cost'
import { COLOUR_DOT, COLOUR_WORD } from '@/lib/cost-colours'
import { fetchSiteDaysApi } from '@/lib/api'
import { fetchWaiting } from '@/lib/approvals'
import { fetchAttention } from '@/lib/attention'
import { hasUpdates, localIsoDate } from '@/lib/site-day'
import { Section } from '@/components/page/page-kit'
import { cn } from '@/lib/utils'

// GM-02 on main's home (UX-11): every live project in one table, worst first, for the owner / admin and the PM.
// Each column is a module's own read (lifecycle, cost portfolio for the roles that see it, today's site days,
// Attention GM-04, the NXT-08 waiting list); a row opens the project hub (UX-12), a cell the page behind it.

const LIVE: Stage[] = ['running', 'handover', 'defects']
const day = (iso: string | null | undefined) => (iso ? new Date(iso + 'T00:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) : '')

export function ProjectBoard({ withMoney }: { withMoney: boolean }) {
  const today = React.useMemo(() => localIsoDate(new Date()), [])
  const opts = { retry: false, staleTime: 60_000 } as const
  const lifecycle = useQuery({ queryKey: ['home', 'board', 'lifecycle'], queryFn: fetchLifecycle, ...opts })
  const portfolio = useQuery({ queryKey: ['home', 'portfolio'], queryFn: fetchPortfolio, enabled: withMoney, ...opts })
  const days = useQuery({ queryKey: ['home', 'board', 'days', today], queryFn: () => fetchSiteDaysApi(today), ...opts })
  const attention = useQuery({ queryKey: ['home', 'board', 'attention'], queryFn: () => fetchAttention(null), ...opts })
  const waiting = useQuery({ queryKey: ['home', 'board', 'waiting'], queryFn: fetchWaiting, ...opts })
  const money = withMoney && !portfolio.isError

  const rows = React.useMemo(() => (Array.isArray(lifecycle.data) ? lifecycle.data : []).filter((p) => LIVE.includes(p.stage)).map((p) => {
    const alerts = (attention.data?.items ?? []).filter((a) => a.project_id === p.id)
    const cost = portfolio.data?.projects?.find((c) => c.project_id === p.id)
    const sites = (days.data?.items ?? []).filter((s) => s.project_id === p.id)
    const bad = alerts.filter((a) => a.severity === 'bad').length
    const score = bad * 10 + alerts.length + (p.slip_days > 0 ? 5 : 0) + (cost?.colour === 'red' ? 5 : cost?.colour === 'amber' ? 2 : 0)
    return {
      p, cost, sites, bad, alerts: alerts.length, score,
      order: alerts.find((a) => a.kind === 'order'),
      waiting: (waiting.data?.items ?? []).filter((w) => w.project_id === p.id).length,
    }
  }).sort((a, b) => b.score - a.score || a.p.name.localeCompare(b.p.name)), [lifecycle.data, attention.data, portfolio.data, days.data, waiting.data])

  if (lifecycle.isError || (!lifecycle.isLoading && rows.length < 2)) return null
  return (
    <Section title="Your projects" note="Worst first: act-now alerts, a late handover, a red forecast. Open a row for the project.">
      <div className="overflow-x-auto rounded-xl border">
        <table className="w-full min-w-[760px] text-sm">
          <thead className="bg-muted/60 text-left text-[11px] tracking-wide text-muted-foreground uppercase">
            <tr>
              <th className="px-3 py-2 font-semibold">Project</th>
              <th className="px-3 py-2 font-semibold">Schedule</th>
              {money && <th className="px-3 py-2 font-semibold">Done · spent</th>}
              {money && <th className="px-3 py-2 font-semibold">Cost</th>}
              <th className="px-3 py-2 font-semibold">Reported today</th>
              <th className="px-3 py-2 font-semibold">Act now</th>
              <th className="px-3 py-2 font-semibold">Waiting</th>
              <th className="px-3 py-2 font-semibold">Order</th>
            </tr>
          </thead>
          <tbody>
            {lifecycle.isLoading && <tr><td colSpan={8} className="h-16 animate-pulse bg-muted/30" /></tr>}
            {rows.map((r) => (
              <tr key={r.p.id} className="border-t hover:bg-muted/30">
                <td className="px-3 py-2.5">
                  <div className="flex items-center gap-2">
                    <span className={cn('size-2.5 shrink-0 rounded-full', r.bad ? 'bg-red-600' : r.alerts ? 'bg-amber-500' : 'bg-emerald-600')} />
                    <Link to={`/projects/${r.p.id}`} className="font-semibold hover:underline">{r.p.name}</Link>
                  </div>
                </td>
                <td className="px-3 py-2.5">
                  <Link to={`/planning/schedule?project=${r.p.id}`} className="block text-xs">
                    {!r.p.scheduled ? <span className="text-muted-foreground">No schedule</span>
                      : r.p.slip_days > 0 ? <span className="font-medium text-red-700 dark:text-red-300">{r.p.slip_days} days late</span>
                        : r.p.late ? <span className="text-draft">{r.p.late} late</span> : <span className="text-success">On time</span>}
                    {r.p.forecast_finish && <span className="text-muted-foreground"> · {day(r.p.forecast_finish)}</span>}
                  </Link>
                </td>
                {money && (
                  <td className="px-3 py-2.5 text-xs tabular-nums">
                    {r.cost?.percent_done != null
                      ? <Link to={`/cost/budget?project=${r.p.id}`} className={cn(Number(r.cost.percent_spent ?? 0) > Number(r.cost.percent_done) + 5 && 'text-red-700 dark:text-red-300')}>{Math.round(Number(r.cost.percent_done))}% · {Math.round(Number(r.cost.percent_spent ?? 0))}%</Link>
                      : <span className="text-muted-foreground">–</span>}
                  </td>
                )}
                {money && (
                  <td className="px-3 py-2.5 text-xs">
                    {r.cost ? <Link to={`/cost/green-red?project=${r.p.id}`} className="inline-flex items-center gap-1.5"><span className={cn('size-2 rounded-full', COLOUR_DOT[r.cost.colour])} />{COLOUR_WORD[r.cost.colour]}</Link> : <span className="text-muted-foreground">–</span>}
                  </td>
                )}
                <td className="px-3 py-2.5 text-xs tabular-nums">
                  <Link to={`/today?project=${r.p.id}`}>{r.sites.filter(hasUpdates).length}/{r.sites.length}</Link>
                </td>
                <td className="px-3 py-2.5 text-xs">
                  {r.bad ? <Link to={`/site/attention?project=${r.p.id}`} className="font-medium text-red-700 dark:text-red-300">{r.bad}</Link> : <span className="text-muted-foreground">–</span>}
                </td>
                <td className="px-3 py-2.5 text-xs tabular-nums">{r.waiting || <span className="text-muted-foreground">–</span>}</td>
                <td className="px-3 py-2.5 text-xs">
                  {r.order ? <Link to={r.order.action.link} className={r.order.severity === 'bad' ? 'text-red-700 dark:text-red-300' : 'text-draft'}>{r.order.title.replace(/^Order /, '')}</Link> : <span className="text-muted-foreground">–</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  )
}
