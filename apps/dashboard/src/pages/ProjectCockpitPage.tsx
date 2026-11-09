import * as React from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import type { LucideIcon } from 'lucide-react'
import { ArrowUpRight, CalendarClock, CircleCheck, Gauge, Inbox, IndianRupee, Settings2, ShoppingCart, TriangleAlert, Truck, Users } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { usePageTitle } from '@/lib/page-title'
import { fetchSchedule, type Activity } from '@/lib/schedule'
import { fetchProjectBudget, type BudgetKind } from '@/lib/cost'
import { fetchMaterialPlan } from '@/lib/material-plan'
import { fetchSiteDaysApi } from '@/lib/api'
import { fetchAllOpenIssues } from '@/lib/issues'
import { fetchLogs } from '@/lib/equipment'
import { fetchInbox } from '@/lib/approvals'
import { fetchAttention } from '@/lib/attention'
import { rupees } from '@/lib/expenses'
import { hasUpdates, localIsoDate } from '@/lib/site-day'
import { cn } from '@/lib/utils'

// GM-03 (plan docs/plans/gm-pm-plan.md): one project's cockpit. The answer first (handover, done vs spent), then why
// (this project's attention alerts, GM-04), then one panel per question a GM asks, each from its module's own read and
// each linking to the page that explains it. Nothing is computed twice: every figure is the module's own. A panel the
// person's role may not see (money, D-CC4) says so instead of a number.

const n = (v: string | null | undefined) => (v === null || v === undefined || v === '' ? null : Number(v))
const pct = (part: number | null, whole: number | null) => (part !== null && whole ? Math.round((part / whole) * 100) : null)
const day = (iso: string | null | undefined) => (iso ? new Date(iso + (iso.length === 10 ? 'T00:00:00' : '')).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) : '–')

function useProjectQuery<T>(key: string, id: string, fn: () => Promise<T>, enabled = true) {
  return useQuery({ queryKey: ['cockpit', key, id], queryFn: fn, enabled: !!id && enabled, retry: false, staleTime: 60_000 })
}

export default function ProjectCockpitPage() {
  const { id = '' } = useParams<{ id: string }>()
  const today = React.useMemo(() => localIsoDate(new Date()), [])
  const schedule = useProjectQuery('schedule', id, () => fetchSchedule(id))
  const budget = useProjectQuery('budget', id, () => fetchProjectBudget(id))
  const plan = useProjectQuery('plan', id, () => fetchMaterialPlan(id, 4))
  const days = useProjectQuery('days', id, () => fetchSiteDaysApi(today, id))
  const issues = useProjectQuery('issues', id, () => fetchAllOpenIssues(id))
  const logs = useProjectQuery('logs', id, () => fetchLogs({ project_id: id, date: today }))
  const inbox = useProjectQuery('inbox', id, () => fetchInbox(id))
  const attention = useProjectQuery('attention', id, () => fetchAttention(id))

  const project = schedule.data?.project
  const name = project?.name ?? days.data?.items[0]?.project_name ?? 'Project'
  usePageTitle(name)
  const s = schedule.data?.summary
  const kinds = budget.data?.kinds ?? []
  const sum = (key: keyof BudgetKind) => {
    const values = kinds.map((k) => n(k[key] as string | null)).filter((v): v is number => v !== null)
    return values.length ? values.reduce((a, b) => a + b, 0) : null
  }
  const boqBudget = sum('budget')
  const earned = sum('earned')
  const spent = n(budget.data?.total_spent)
  const committed = sum('committed')
  const done = pct(earned, boqBudget) ?? (s?.progress ?? null)
  const spentPct = pct(spent, boqBudget)
  const alerts = attention.data?.items ?? []
  const worst = alerts.some((a) => a.severity === 'bad') ? 'bad' : alerts.length ? 'warn' : 'ok'

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className={cn('inline-flex size-10 items-center justify-center rounded-xl', worst === 'bad' ? 'bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-200' : worst === 'warn' ? 'bg-draft-soft text-draft' : 'bg-success-soft text-success')}>
            <Gauge className="size-5" />
          </span>
          <div>
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              Project{project?.stage_label && <span className="rounded-full bg-muted px-2 py-px font-medium text-foreground/80">{project.stage_label}</span>}
              {project?.client && <span>· {project.client}</span>}
            </div>
            <h1 className="text-2xl leading-tight font-semibold tracking-tight">{name}</h1>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="outline" size="sm"><Link to={`/planning/schedule?project=${id}`}>Schedule</Link></Button>
          <Button asChild variant="outline" size="sm"><Link to={`/projects/${id}/boq`}>BOQ</Link></Button>
          <Button asChild variant="ghost" size="sm" className="gap-1.5"><Link to={`/projects/${id}`}><Settings2 className="size-4" />Setup</Link></Button>
        </div>
      </header>

      <div className="grid grid-cols-2 gap-2 sm:gap-3 lg:grid-cols-4">
        <Tile label="Handover" value={s?.forecast_finish ? day(s.forecast_finish) : s?.contract_finish ? day(s.contract_finish) : '–'}
          note={s?.slip_days ? `${s.slip_days} days after ${s.contract_finish ? 'the contract date' : 'the plan'} (${day(s.contract_finish ?? s.planned_finish)})` : s?.forecast_finish ? 'On plan' : schedule.isLoading ? '' : 'No schedule yet'}
          tone={s?.slip_days ? 'bad' : s?.forecast_finish ? 'ok' : undefined} />
        <Tile label="Work done" value={done !== null ? `${done}%` : '–'} note={earned !== null && boqBudget ? `${rupees(earned)} of ${rupees(boqBudget)} BOQ` : 'From the work measured'} />
        <Tile label="Spent" value={spentPct !== null ? `${spentPct}%` : spent !== null ? rupees(spent) : '–'}
          note={budget.isError ? 'Shown to the roles that see spending' : spentPct !== null && done !== null ? (spentPct > done + 5 ? `${spentPct - done} points ahead of the work` : 'In step with the work') : ''}
          tone={spentPct !== null && done !== null ? (spentPct > done + 5 ? 'bad' : 'ok') : undefined} />
        <Tile label="Committed, not billed" value={committed !== null ? rupees(committed) : '–'} note={budget.isError ? 'Shown to the roles that see spending' : 'Orders and work orders still to come'} />
      </div>

      <section aria-label="Why" className={cn('grid grid-cols-[6px_minmax(0,1fr)] overflow-hidden rounded-xl border bg-card')}>
        <span className={worst === 'bad' ? 'bg-red-600' : worst === 'warn' ? 'bg-amber-500' : 'bg-emerald-600'} aria-hidden />
        <div className="flex flex-col gap-3 p-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            {worst === 'ok' ? <><CircleCheck className="size-4 text-success" />Nothing has crossed a line</> : <>Why it is {worst === 'bad' ? 'red' : 'amber'}</>}
            <span className="rounded-full bg-ai-soft px-2 py-px text-[11px] font-medium text-ai">from today's numbers</span>
          </h2>
          {attention.isLoading && <div className="h-12 animate-pulse rounded bg-muted/50" />}
          {alerts.slice(0, 3).map((a, i) => (
            <div key={a.key} className="grid grid-cols-[20px_minmax(0,1fr)] items-start gap-x-3 gap-y-2 sm:grid-cols-[20px_minmax(0,1fr)_auto]">
              <span className="pt-0.5 font-mono text-xs text-muted-foreground">{i + 1}</span>
              <div className="min-w-0">
                <div className="font-semibold">{a.title}{a.site_name ? <span className="font-normal text-muted-foreground"> · {a.site_name}</span> : null}</div>
                <div className="text-sm text-muted-foreground">{a.detail}</div>
              </div>
              <Button asChild size="sm" variant="outline" className="col-start-2 justify-self-start sm:col-start-auto"><Link to={a.action.link}>{a.action.label}</Link></Button>
            </div>
          ))}
          {alerts.length > 3 && <Link to={`/site/attention?project=${id}`} className="text-sm font-medium text-primary-ink hover:underline">{alerts.length - 3} more in Attention</Link>}
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Schedule" icon={CalendarClock} link={`/planning/schedule?project=${id}`} linkLabel="Open the schedule">
          {schedule.isError && <Muted>The schedule did not load.</Muted>}
          {schedule.data && <Gantt activities={schedule.data.activities} today={schedule.data.today} />}
        </Panel>
        <Panel title="Cost by kind, to date" icon={IndianRupee} link={`/cost/budget?project=${id}`} linkLabel="Budget vs actual">
          {budget.isError && <Muted>Shown to the roles that see spending.</Muted>}
          {budget.data && kinds.length === 0 && <Muted>No BOQ with rates yet.</Muted>}
          {kinds.map((k) => <KindRow key={k.kind} kind={k} />)}
          {budget.data && <p className="text-xs text-muted-foreground">Spent against what the work done should have cost (earned). Forecast: at the rate so far.</p>}
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="Order soon" icon={ShoppingCart} link={`/planning/materials?project=${id}`} linkLabel="Material plan">
          {plan.isError && <Muted>Shown to the roles that see the BOQ.</Muted>}
          {plan.data && <OrderList plan={plan.data} today={today} />}
        </Panel>
        <Panel title="Today on site" icon={Users} link="/today" linkLabel="Today">
          {(days.data?.items ?? []).map((site) => (
            <Row key={site.site_id} title={site.site_name}
              note={hasUpdates(site) ? (site.site_working === 'none' ? 'No work today' : sentToday(site)) : 'Not reported yet'}
              chip={hasUpdates(site) ? { text: 'Reported', tone: 'ok' } : { text: 'Waiting', tone: 'warn' }} />
          ))}
          {(logs.data?.items ?? []).filter((l) => l.event_type === 'day_log').slice(0, 4).map((l) => (
            <Row key={l.id} icon={Truck} title={l.machine ?? 'Machine'}
              note={`${n(l.worked_hours) ?? 0} h worked${n(l.idle_hours) ? ` · ${n(l.idle_hours)} h idle` : ''}${n(l.breakdown_hours) ? ` · ${n(l.breakdown_hours)} h breakdown` : ''}`}
              chip={n(l.breakdown_hours) || n(l.idle_hours) ? { text: n(l.breakdown_hours) ? 'Breakdown' : 'Idle', tone: 'warn' } : undefined} />
          ))}
          {days.data && days.data.items.length === 0 && <Muted>No sites yet.</Muted>}
        </Panel>
        <Panel title="Open issues" icon={TriangleAlert} link={`/issues?project=${id}`} linkLabel="All issues">
          {issues.data && issues.data.length === 0 && <Muted>None open.</Muted>}
          {[...(issues.data ?? [])].sort((a, b) => a.occurred_at.localeCompare(b.occurred_at)).slice(0, 5).map((i) => {
            const age = Math.floor((Date.now() - new Date(i.occurred_at).getTime()) / 86_400_000)
            return (
              <Row key={i.id} title={(i.narrative || i.issue_type.replace(/_/g, ' ').toLowerCase()).slice(0, 60)}
                note={`${age === 0 ? 'Today' : `${age} day${age === 1 ? '' : 's'}`} · ${String(i.severity).toLowerCase()} · ${i.assigned_user_name ? `${i.assigned_user_name}${i.due_on ? `, by ${day(i.due_on)}` : ''}` : 'no one on it'}`}
                chip={i.due_on && i.due_on < today ? { text: 'Overdue', tone: 'bad' } : ['HIGH', 'CRITICAL'].includes(String(i.severity)) ? { text: 'High', tone: 'bad' } : age >= 2 ? { text: `${age} d`, tone: 'warn' } : undefined} />
            )
          })}
        </Panel>
      </div>

      <Panel title="Waiting for you on this project" icon={Inbox} link={`/site/approvals?project=${id}`} linkLabel="Waiting for you">
        {inbox.data && inbox.data.items.length === 0 && <Muted>Nothing waiting.</Muted>}
        <div className="grid gap-x-6 sm:grid-cols-2">
          {(inbox.data?.items ?? []).slice(0, 6).map((r) => (
            <Row key={r.key} title={r.title} note={r.fact} chip={r.flagged ? { text: 'Check', tone: 'bad' } : undefined} />
          ))}
        </div>
      </Panel>
    </div>
  )
}

/** What a site sent today, in words: only the parts it sent ("12 workers · 3 work updates · 1 delivery"). */
function sentToday(site: { workers: number; work_items: number; materials?: number; issues_today?: number; progress_updates?: number; drafts?: number }): string {
  const parts: [number | undefined, string][] = [
    [site.workers, 'worker'], [site.work_items, 'work update'], [site.progress_updates, 'progress update'],
    [site.materials, 'material entry'], [site.issues_today, 'issue'], [site.drafts, 'item to confirm'],
  ]
  return parts.filter(([v]) => (v ?? 0) > 0).map(([v, w]) => `${v} ${w}${v === 1 ? '' : 's'}`).join(' · ')
}

function Tile({ label, value, note, tone }: { label: string; value: string; note?: string; tone?: 'ok' | 'bad' }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5 rounded-xl border bg-card p-3 sm:p-3.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="truncate text-xl font-semibold tabular-nums sm:text-2xl">{value}</span>
      {note && <span className={cn('text-xs', tone === 'bad' ? 'text-red-700 dark:text-red-300' : tone === 'ok' ? 'text-success' : 'text-muted-foreground')}>{note}</span>}
    </div>
  )
}

function Panel({ title, icon: Icon, link, linkLabel, children }: { title: string; icon: LucideIcon; link: string; linkLabel: string; children: React.ReactNode }) {
  return (
    <section className="flex min-w-0 flex-col rounded-xl border bg-card">
      <h2 className="flex items-center justify-between gap-2 border-b px-4 py-2.5 text-sm font-semibold">
        <span className="flex items-center gap-2"><Icon className="size-4 text-muted-foreground" />{title}</span>
        <Link to={link} className="inline-flex items-center gap-0.5 text-xs font-medium text-primary-ink hover:underline">{linkLabel}<ArrowUpRight className="size-3" /></Link>
      </h2>
      <div className="flex flex-col gap-2.5 p-4">{children}</div>
    </section>
  )
}

function Muted({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>
}

const CHIP = { ok: 'bg-success-soft text-success', warn: 'bg-draft-soft text-draft', bad: 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200' }

function Row({ title, note, chip, icon: Icon }: { title: string; note?: string; chip?: { text: string; tone: keyof typeof CHIP }; icon?: LucideIcon }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="flex min-w-0 items-start gap-2">
        {Icon && <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />}
        <div className="min-w-0">
          <div className="truncate text-sm font-medium first-letter:uppercase">{title}</div>
          {note && <div className="text-xs text-muted-foreground">{note}</div>}
        </div>
      </div>
      {chip && <span className={cn('shrink-0 rounded-full px-2 py-px text-[11px] font-medium', CHIP[chip.tone])}>{chip.text}</span>}
    </div>
  )
}

function Gantt({ activities, today }: { activities: Activity[]; today: string }) {
  const acts = activities.filter((a) => a.start && a.end).sort((a, b) => a.start!.localeCompare(b.start!))
  if (!acts.length) return <Muted>No dates on the schedule yet.</Muted>
  const DAY = 86_400_000
  const t = (iso: string) => new Date(iso + 'T00:00:00').getTime()
  const from = Math.min(t(today), ...acts.map((a) => t(a.start!)))
  const to = Math.max(t(today), ...acts.map((a) => Math.max(t(a.end!), a.forecast_end ? t(a.forecast_end) : 0))) + DAY
  const x = (ms: number) => ((ms - from) / (to - from)) * 100
  const shown = acts.slice(0, 9)
  return (
    <div className="flex flex-col gap-1.5">
      {shown.map((a) => {
        const left = x(t(a.start!))
        const width = Math.max(x(t(a.end!) + DAY) - left, 1)
        const filled = (width * (a.done ? 100 : a.progress ?? 0)) / 100
        const tone = a.done ? 'bg-emerald-600' : a.state === 'late' ? 'bg-red-600' : a.state === 'behind' ? 'bg-amber-500' : 'bg-sky-600'
        return (
          <div key={a.id} className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)] items-center gap-2 text-xs">
            <span className="flex min-w-0 items-center gap-1"><span className="truncate">{a.name}</span>{a.critical && !a.done && <span className="shrink-0 rounded bg-red-100 px-1 text-[10px] text-red-800 dark:bg-red-950 dark:text-red-200">critical</span>}</span>
            <span className="relative h-4 rounded bg-muted">
              <span className={cn('absolute inset-y-0.5 rounded-sm border bg-background', a.state === 'late' ? 'border-red-400' : 'border-foreground/15')} style={{ left: `${left}%`, width: `${width}%` }} />
              <span className={cn('absolute inset-y-0.5 rounded-sm', tone)} style={{ left: `${left}%`, width: `${filled}%` }} />
              <span className="absolute -inset-y-1 w-0.5 bg-foreground/60" style={{ left: `${x(t(today))}%` }} />
            </span>
          </div>
        )
      })}
      <p className="text-xs text-muted-foreground">The line is today; the fill is how much is done; a red outline is late.{acts.length > shown.length ? ` ${acts.length - shown.length} more on the schedule.` : ''}</p>
    </div>
  )
}

function KindRow({ kind }: { kind: BudgetKind }) {
  const earned = n(kind.earned)
  const actual = n(kind.actual) ?? 0
  const ratio = earned ? Math.round((actual / earned) * 100) : null
  const tone = ratio === null ? 'bg-muted-foreground/40' : ratio > 110 ? 'bg-red-600' : ratio > 100 ? 'bg-amber-500' : 'bg-emerald-600'
  const fc = n(kind.forecast_difference)
  return (
    <div className="grid grid-cols-[6.5rem_minmax(0,1fr)_auto] items-center gap-3 text-sm">
      <span>{kind.label}</span>
      <span className="relative h-2 rounded-full bg-muted">
        <span className={cn('absolute inset-y-0 left-0 rounded-full', tone)} style={{ width: `${Math.min(ratio ?? 0, 130) / 1.3}%` }} />
      </span>
      <span className="text-right font-mono text-xs tabular-nums">
        {ratio !== null ? `${ratio}%` : '–'}
        <span className={cn('block text-[11px]', fc !== null && fc < 0 ? 'text-red-700 dark:text-red-300' : 'text-muted-foreground')}>
          {fc === null ? (kind.forecast_basis === 'too_early' ? 'too early' : 'no budget') : fc < 0 ? `${rupees(-fc)} over` : `${rupees(fc)} under`}
        </span>
      </span>
    </div>
  )
}

function OrderList({ plan, today }: { plan: Awaited<ReturnType<typeof fetchMaterialPlan>>; today: string }) {
  const week = new Date(new Date(today + 'T00:00:00').getTime() + 7 * 86_400_000).toISOString().slice(0, 10)
  const soon = plan.materials.filter((m) => m.order_by && m.order_by <= week)
  if (plan.lines_with_norms === 0) return <Muted>No BOQ line has its materials per unit yet, so there is no plan.</Muted>
  if (!soon.length) return <Muted>Nothing to order in the next 7 days.</Muted>
  return (
    <>
      {soon.slice(0, 5).map((m) => (
        <Row key={m.material_id} title={`${m.material} · ${Math.ceil(Number(m.short_by))} ${m.unit}`}
          note={`Short from ${day(m.short_day)}${m.supplier ? ` · ${m.supplier}, ${m.lead_days} days` : ''}`}
          chip={{ text: m.order_now ? 'Today' : day(m.order_by), tone: m.order_now ? 'bad' : 'warn' }} />
      ))}
    </>
  )
}
