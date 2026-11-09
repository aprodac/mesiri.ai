import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { LucideIcon } from 'lucide-react'
import { AlarmClock, BellOff, BellRing, CalendarClock, CircleCheck, Hammer, IndianRupee, Radio, ShoppingCart, TriangleAlert, Truck, Wallet } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useToast } from '@/components/ui/toast-notification'
import { useScope } from '@/lib/ScopeContext'
import { usePageTitle } from '@/lib/page-title'
import { errorDetail } from '@/lib/site-day'
import { cn } from '@/lib/utils'
import { ATTENTION_KEY, GROUPS, KIND_LABEL, fetchAttention, snoozeAlert, unsnoozeAlert, type Alert, type AlertKind } from '@/lib/attention'

// GM-04 (plan docs/plans/gm-pm-plan.md): Site > Attention. What crossed a line since yesterday, for this person:
// over budget, late, to order, a site that sent nothing, an issue left open, a hire bill above its log. Each alert
// says what, by how much, and opens the page that acts on it. "Not today" hides it for this person until tomorrow;
// if it is still true then, it is back. Red ones first.

const KIND_ICON: Record<AlertKind, LucideIcon> = {
  handover: CalendarClock,
  budget: Wallet,
  late: AlarmClock,
  cost: IndianRupee,
  order: ShoppingCart,
  issue: TriangleAlert,
  unreported: Radio,
  hire: Truck,
}

const SEVERITY = {
  bad: { stripe: 'bg-red-600', icon: 'bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-200', chip: 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200', label: 'Act now' },
  warn: { stripe: 'bg-amber-500', icon: 'bg-draft-soft text-draft', chip: 'bg-draft-soft text-draft', label: 'Worth a look' },
} as const

export default function AttentionPage() {
  usePageTitle('Attention')
  const { scope } = useScope()
  const projectId = scope.mode === 'portfolio' ? null : scope.projectId
  const { data, isLoading, isError } = useQuery({
    queryKey: [...ATTENTION_KEY, projectId],
    queryFn: () => fetchAttention(projectId),
    refetchInterval: 5 * 60_000,
  })
  const [group, setGroup] = React.useState('all')
  const [showSnoozed, setShowSnoozed] = React.useState(false)
  const items = React.useMemo(() => {
    const g = GROUPS.find((x) => x.key === group)
    return (data?.items ?? []).filter((a) => !g || !g.kinds.length || g.kinds.includes(a.kind))
  }, [data, group])

  const qc = useQueryClient()
  const toast = useToast()
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ATTENTION_KEY })
    void qc.invalidateQueries({ queryKey: ['attention-count'] })
  }
  const snooze = useMutation({
    mutationFn: (a: Alert) => snoozeAlert(a.key, 1),
    onSuccess: (_, a) => { toast.success('Hidden for today', `“${a.title}” is back tomorrow if it is still true.`); refresh() },
    onError: (e) => toast.error('Not hidden', errorDetail(e) ?? 'Refresh and try again.'),
  })
  const unsnooze = useMutation({
    mutationFn: (a: Alert) => unsnoozeAlert(a.key),
    onSuccess: () => refresh(),
  })

  const counts = data?.counts
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <header className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="inline-flex size-10 items-center justify-center rounded-xl bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-200">
            <BellRing className="size-5" />
          </span>
          <div>
            <div className="text-xs text-muted-foreground">Site</div>
            <h1 className="text-2xl leading-tight font-semibold tracking-tight">Attention</h1>
          </div>
        </div>
        <p className="hidden max-w-xs text-right text-xs text-muted-foreground sm:block">
          Things that crossed a line, from what Mesiri already has. Nothing here needs typing.
        </p>
      </header>

      <div className="grid grid-cols-3 gap-2 sm:gap-3">
        {[
          { label: 'Act now', value: counts?.bad, tone: SEVERITY.bad.icon, icon: TriangleAlert },
          { label: 'Worth a look', value: counts?.warn, tone: SEVERITY.warn.icon, icon: Hammer },
          { label: 'Hidden for today', value: counts?.snoozed, tone: 'bg-muted text-muted-foreground', icon: BellOff },
        ].map((t) => (
          <div key={t.label} className="flex flex-col items-center gap-1 rounded-xl border bg-card p-2 text-center sm:flex-row sm:gap-3 sm:p-3.5 sm:text-left">
            <span className={cn('inline-flex size-8 shrink-0 items-center justify-center rounded-lg sm:size-11 sm:rounded-xl', t.tone)}>
              <t.icon className="size-4 sm:size-5" />
            </span>
            <span className="flex flex-col">
              <span className="text-xl leading-none font-semibold tabular-nums sm:text-3xl">{isLoading ? '–' : t.value ?? 0}</span>
              <span className="text-[11px] leading-tight text-muted-foreground sm:text-sm sm:text-foreground/80">{t.label}</span>
            </span>
          </div>
        ))}
      </div>

      <div role="tablist" aria-label="Kind" className="flex max-w-full gap-0.5 self-start overflow-x-auto rounded-xl bg-muted p-1">
        {GROUPS.map((g) => {
          const n = (data?.items ?? []).filter((a) => !g.kinds.length || g.kinds.includes(a.kind)).length
          if (g.key !== 'all' && n === 0) return null
          const on = group === g.key
          return (
            <button key={g.key} role="tab" type="button" aria-selected={on} onClick={() => setGroup(g.key)}
              className={cn('inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-3 text-sm whitespace-nowrap', on ? 'bg-background font-semibold shadow-sm' : 'text-foreground/75 hover:text-foreground')}>
              {g.label}
              <span className={cn('rounded-full px-1.5 text-[11px] font-semibold tabular-nums', on ? 'bg-foreground text-background' : 'bg-background/70')}>{n}</span>
            </button>
          )
        })}
      </div>

      <section aria-label="Alerts" className="overflow-hidden rounded-xl border">
        {isLoading && <div className="flex flex-col">{[0, 1, 2].map((i) => <div key={i} className="h-24 animate-pulse border-b bg-muted/40" />)}</div>}
        {isError && <p className="p-6 text-sm text-destructive">The alerts did not load. Refresh to try again.</p>}
        {!isLoading && !isError && items.length === 0 && (
          <div className="flex flex-col items-center gap-2 px-4 py-14 text-center text-sm text-muted-foreground">
            <CircleCheck className="size-8 text-success opacity-70" />
            Nothing has crossed a line{projectId ? ' on this project' : ''}.
            <span className="max-w-sm text-xs">Mesiri watches budgets, the schedule, what to order, sites that have not reported, open issues and hire bills.</span>
          </div>
        )}
        {items.map((a) => <AlertRow key={a.key} alert={a} busy={snooze.isPending} onSnooze={() => snooze.mutate(a)} />)}
      </section>

      {(data?.snoozed.length ?? 0) > 0 && (
        <div className="flex flex-col gap-2">
          <button type="button" className="self-start text-sm font-medium text-muted-foreground hover:text-foreground" onClick={() => setShowSnoozed((s) => !s)}>
            {showSnoozed ? 'Hide' : 'Show'} {data!.snoozed.length} hidden for today
          </button>
          {showSnoozed && (
            <section aria-label="Hidden for today" className="overflow-hidden rounded-xl border opacity-75">
              {data!.snoozed.map((a) => (
                <AlertRow key={a.key} alert={a} busy={unsnooze.isPending} snoozed onSnooze={() => unsnooze.mutate(a)} />
              ))}
            </section>
          )}
        </div>
      )}
    </div>
  )
}

function AlertRow({ alert, busy, snoozed, onSnooze }: { alert: Alert; busy: boolean; snoozed?: boolean; onSnooze: () => void }) {
  const look = SEVERITY[alert.severity]
  const Icon = KIND_ICON[alert.kind]
  const where = [alert.project_name, alert.site_name].filter(Boolean).join(' · ')
  return (
    <div className="grid grid-cols-[4px_minmax(0,1fr)] border-b bg-card last:border-b-0">
      <span className={look.stripe} aria-hidden />
      <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start">
        <span className={cn('inline-flex size-9 shrink-0 items-center justify-center rounded-lg', look.icon)}><Icon className="size-4" /></span>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
            <span className={cn('rounded-full px-2 py-px font-medium', look.chip)}>{look.label}</span>
            <span className="rounded-full bg-muted px-2 py-px text-muted-foreground">{KIND_LABEL[alert.kind]}</span>
            {where && <span className="text-muted-foreground">{where}</span>}
          </div>
          <div className="font-semibold">{alert.title}</div>
          <div className="text-sm text-muted-foreground">{alert.detail}</div>
        </div>
        <div className="flex shrink-0 gap-2 sm:flex-col sm:items-end">
          <Button asChild size="sm" variant={alert.severity === 'bad' ? 'default' : 'outline'}>
            <Link to={alert.action.link}>{alert.action.label}</Link>
          </Button>
          <Button size="sm" variant="ghost" disabled={busy} onClick={onSnooze} className="text-muted-foreground">
            {snoozed ? 'Show again' : 'Not today'}
          </Button>
        </div>
      </div>
    </div>
  )
}
