import * as React from 'react'
import { Link } from 'react-router-dom'
import {
  AlertTriangle, ArrowRight, CalendarClock, CheckCircle2, ClipboardList, Diamond, Flame, Handshake, Link2, MessageSquareText,
  RotateCcw, Trash2, X,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { formatQuantity } from '@/lib/boq'
import { addDays, daysBetween, plural, shortDay, STATE_WORDS, type Activity, type ActivityUpdate, type Schedule } from '@/lib/schedule'
import { cn } from '@/lib/utils'
import { STATE_BAR } from './gantt'

// ST-04: one activity, everything about it in one place: where it stands and why, what it pushes, the BOQ lines
// site measured, who is doing it (work orders), what is stuck (issues), the last site update; and, for those who
// plan, its days and "starts after", always previewed before the ones after it move.

export function StateChip({ state, className }: { state: Activity['state']; className?: string }) {
  return <span className={cn('inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold', STATE_BAR[state].chip, className)}>{STATE_WORDS[state]}</span>
}

function why(a: Activity, today: string): string {
  switch (a.state) {
    case 'late':
      return `Should have finished ${shortDay(a.end, today)}: ${plural(a.days_late, 'day')} late${a.progress !== null ? ` at ${a.progress}%` : ''}.`
    case 'behind':
      return a.progress === null || a.progress === 0
        ? `Should have started ${shortDay(a.start, today)}; site has not reported work on it yet.`
        : `${a.progress}% done; by today it should be about ${a.expected}%.`
    case 'on_track':
      return a.progress !== null ? `${a.progress}% done, on pace for ${shortDay(a.end, today)}.` : 'Running to plan.'
    case 'not_started':
      return `Starts ${shortDay(a.start, today)}${a.pushed_days ? `, but late work before it pushes it about ${plural(a.pushed_days, 'day')}` : ''}.`
    case 'done':
      return a.actual_end ? `Finished ${shortDay(a.actual_end, today)}.` : 'Finished.'
    default:
      return 'No dates yet: give it a start and an end to put it on the schedule.'
  }
}

export function ActivityPanel({
  schedule,
  activity: a,
  projectId,
  canEdit,
  busy,
  onChange,
  onDelete,
  onClose,
}: {
  schedule: Schedule
  activity: Activity
  projectId: string
  canEdit: boolean
  busy: boolean
  /** Asks the page to preview, then confirm, the change. */
  onChange: (body: ActivityUpdate, label: string) => void
  onDelete: () => void
  onClose?: () => void
}) {
  const today = schedule.today
  const [start, setStart] = React.useState(a.start ?? today)
  const [end, setEnd] = React.useState(a.end ?? addDays(a.start ?? today, 6))
  const [milestone, setMilestone] = React.useState(a.milestone)
  const [after, setAfter] = React.useState<Record<string, number>>(Object.fromEntries(a.after.map((p) => [p.id, p.lag])))
  const [pickAfter, setPickAfter] = React.useState(false)
  React.useEffect(() => {
    setStart(a.start ?? today)
    setEnd(a.end ?? addDays(a.start ?? today, 6))
    setMilestone(a.milestone)
    setAfter(Object.fromEntries(a.after.map((p) => [p.id, p.lag])))
    setPickAfter(false)
  }, [a, today])

  const others = schedule.activities.filter((x) => x.id !== a.id)
  const followers = schedule.links.filter((l) => l.predecessor === a.id).map((l) => others.find((x) => x.id === l.successor)).filter(Boolean) as Activity[]
  const datesChanged = start !== a.start || (!milestone && end !== a.end) || milestone !== a.milestone
  const afterChanged = JSON.stringify(Object.entries(after).sort()) !== JSON.stringify(a.after.map((p) => [p.id, p.lag]).sort())
  const length = milestone ? 0 : daysBetween(start, end) + 1
  const invalid = !milestone && daysBetween(start, end) < 0
  const tone = STATE_BAR[a.state]

  const save = () => {
    const body: ActivityUpdate = {}
    if (datesChanged) Object.assign(body, milestone ? { start, milestone: true } : { start, end, milestone: false })
    if (afterChanged) body.after = Object.entries(after).map(([id, lag]) => ({ id, lag }))
    onChange(body, `${a.name}: new ${datesChanged ? 'days' : '“starts after”'}`)
  }

  return (
    <div className="flex flex-col">
      <header className="flex items-start gap-3 border-b p-4">
        <span className={cn('mt-0.5 inline-flex size-9 shrink-0 items-center justify-center rounded-lg', tone.chip)}>
          {a.milestone ? <Diamond className="size-4" /> : <CalendarClock className="size-4" />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <h2 className="truncate text-base font-semibold">{a.name}</h2>
            <StateChip state={a.state} />
            {a.critical && a.state !== 'done' && (
              <span className="inline-flex items-center gap-0.5 rounded-full bg-orange-100 px-2 py-0.5 text-xs font-semibold text-orange-800 dark:bg-orange-950 dark:text-orange-200" title="No slack: a day late here is a day late for the project">
                <Flame className="size-3" /> Critical
              </span>
            )}
          </div>
          <p className="mt-0.5 text-sm text-muted-foreground">{why(a, today)}</p>
        </div>
        {onClose && <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close"><X className="size-4" /></Button>}
      </header>

      {/* Progress against the calendar */}
      {a.start && !a.milestone && (
        <section className="flex flex-col gap-2 border-b p-4">
          <div className="flex items-baseline justify-between text-sm">
            <span className="font-medium">Progress</span>
            <span className="tabular-nums text-muted-foreground">
              {a.progress !== null ? <strong className="text-foreground">{a.progress}%</strong> : 'not measured'}
              {a.expected !== null && a.state !== 'done' ? ` · should be ${a.expected}%` : ''}
            </span>
          </div>
          <div className="relative h-2.5 overflow-hidden rounded-full bg-muted">
            <div className={cn('h-full rounded-full', tone.fill)} style={{ width: `${a.progress ?? 0}%` }} />
            {a.expected !== null && a.state !== 'done' && <div className="absolute inset-y-0 w-0.5 bg-foreground/70" style={{ left: `${a.expected}%` }} />}
          </div>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
            <Fact label="Planned">{shortDay(a.start, today)} → {shortDay(a.end, today)}</Fact>
            <Fact label="Length">{plural(a.duration ?? 0, 'day')}</Fact>
            <Fact label="Started on site">{a.actual_start ? shortDay(a.actual_start, today) : 'Not yet'}</Fact>
            <Fact label="Forecast finish" bad={a.slip_days > 0}>
              {a.forecast_end ? shortDay(a.forecast_end, today) : '—'}{a.slip_days > 0 ? ` (+${a.slip_days}d)` : ''}
            </Fact>
          </dl>
          {a.progress === null && (
            <p className="text-xs text-muted-foreground">Progress comes from the site's work updates on this section's BOQ lines. Add BOQ lines to measure it.</p>
          )}
        </section>
      )}

      {/* Knock-on */}
      {(followers.length > 0 || a.pushed_days > 0) && (
        <section className="flex flex-col gap-1.5 border-b p-4 text-sm">
          <h3 className="flex items-center gap-1.5 font-medium"><Link2 className="size-4 text-muted-foreground" /> Linked work</h3>
          {a.pushed_days > 0 && (
            <p className="flex items-start gap-1.5 text-red-700 dark:text-red-300"><AlertTriangle className="mt-0.5 size-3.5 shrink-0" /> Late work before this one pushes it about {plural(a.pushed_days, 'day')}.</p>
          )}
          {followers.length > 0 && (
            <p className="text-muted-foreground">
              Comes before: {followers.map((f, i) => <React.Fragment key={f.id}>{i > 0 && ', '}<span className="text-foreground">{f.name}</span>{f.pushed_days > 0 && <span className="text-red-600"> (+{f.pushed_days}d)</span>}</React.Fragment>)}
            </p>
          )}
        </section>
      )}

      {/* Edit */}
      {canEdit && (
        <section className="flex flex-col gap-3 border-b p-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium">Plan</h3>
            <label className="flex items-center gap-1.5 text-sm">
              <input type="checkbox" checked={milestone} onChange={(e) => setMilestone(e.target.checked)} className="size-4 accent-violet-600" /> Milestone (one day)
            </label>
          </div>
          <div className={cn('grid gap-2', milestone ? 'grid-cols-1' : 'grid-cols-2')}>
            <div className="flex flex-col gap-1">
              <Label htmlFor="act-start" className="text-xs">{milestone ? 'Day' : 'Start'}</Label>
              <Input id="act-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} />
            </div>
            {!milestone && (
              <div className="flex flex-col gap-1">
                <Label htmlFor="act-end" className="text-xs">End</Label>
                <Input id="act-end" type="date" value={end} min={start} onChange={(e) => setEnd(e.target.value)} />
              </div>
            )}
          </div>
          {!milestone && (
            <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
              {invalid ? <span className="text-destructive">The end is before the start.</span> : <span>{plural(length, 'day')}</span>}
              <span className="ml-auto">Quick:</span>
              {[-3, -1, 1, 3, 7].map((n) => (
                <button key={n} type="button" className="rounded border px-1.5 py-0.5 hover:bg-muted" onClick={() => { setStart(addDays(start, n)); setEnd(addDays(end, n)) }}>
                  {n > 0 ? `+${n}` : n}d
                </button>
              ))}
            </div>
          )}

          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium">Starts after</span>
              <button type="button" className="text-xs text-primary-ink hover:underline" onClick={() => setPickAfter((v) => !v)}>{pickAfter ? 'Done' : 'Change'}</button>
            </div>
            {!pickAfter ? (
              <p className="text-sm">{Object.keys(after).length === 0 ? <span className="text-muted-foreground">Nothing: it can start any time</span> : Object.keys(after).map((id) => others.find((o) => o.id === id)?.name).filter(Boolean).join(', ')}</p>
            ) : (
              <ul className="max-h-48 divide-y overflow-y-auto rounded-lg border text-sm">
                {others.map((o) => {
                  const on = o.id in after
                  return (
                    <li key={o.id} className="flex items-center gap-2 px-2.5 py-1.5">
                      <input type="checkbox" checked={on} id={`after-${o.id}`} className="size-4" onChange={(e) => setAfter((cur) => {
                        const next = { ...cur }
                        if (e.target.checked) next[o.id] = 0
                        else delete next[o.id]
                        return next
                      })} />
                      <label htmlFor={`after-${o.id}`} className="min-w-0 flex-1 truncate">{o.name}</label>
                      {on && (
                        <label className="flex items-center gap-1 text-xs text-muted-foreground">
                          + <input type="number" value={after[o.id]} min={-30} max={90} onChange={(e) => setAfter((cur) => ({ ...cur, [o.id]: Number(e.target.value) || 0 }))} className="w-12 rounded border bg-background px-1 py-0.5 text-right tabular-nums" /> days
                        </label>
                      )}
                    </li>
                  )
                })}
              </ul>
            )}
          </div>

          <div className="flex flex-wrap gap-2">
            <Button size="sm" disabled={busy || invalid || (!datesChanged && !afterChanged)} onClick={save} className="gap-1.5">
              <ArrowRight className="size-4" /> {a.start ? 'Review the change' : 'Put on the schedule'}
            </Button>
            {a.start && (
              a.done ? (
                <Button size="sm" variant="outline" disabled={busy} onClick={() => onChange({ done: false, push: false }, `${a.name}: reopened`)} className="gap-1.5"><RotateCcw className="size-4" /> Reopen</Button>
              ) : (
                <Button size="sm" variant="outline" disabled={busy} onClick={() => onChange({ done: true, push: false }, `${a.name}: finished`)} className="gap-1.5"><CheckCircle2 className="size-4" /> Mark finished</Button>
              )
            )}
            {a.lines.length === 0 && (
              <Button size="sm" variant="ghost" disabled={busy} onClick={onDelete} className="ml-auto gap-1.5 text-destructive"><Trash2 className="size-4" /> Remove</Button>
            )}
          </div>
        </section>
      )}

      {/* Connections */}
      <section className="flex flex-col gap-2 border-b p-4 text-sm">
        <h3 className="flex items-center gap-1.5 font-medium"><ClipboardList className="size-4 text-muted-foreground" /> BOQ work measured by site</h3>
        {a.lines.length === 0 ? (
          <p className="text-muted-foreground">No BOQ lines in this section.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {a.lines.map((l) => (
              <li key={l.id} className="flex flex-col gap-1">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="min-w-0 truncate">{l.boq_code ? <span className="text-muted-foreground">{l.boq_code} </span> : null}{l.work}</span>
                  <span className="shrink-0 tabular-nums text-muted-foreground">{formatQuantity(l.done_quantity)} / {formatQuantity(l.planned_quantity)} {l.unit}</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-muted"><div className={cn('h-full rounded-full', tone.fill)} style={{ width: `${l.progress ?? 0}%` }} /></div>
              </li>
            ))}
          </ul>
        )}
        <Link to={`/projects/${projectId}/boq`} className="inline-flex items-center gap-1 text-xs text-primary-ink hover:underline">Open the BOQ <ArrowRight className="size-3" /></Link>
      </section>

      <section className="grid gap-3 p-4 text-sm sm:grid-cols-2">
        <div className="flex flex-col gap-1">
          <h3 className="flex items-center gap-1.5 font-medium"><Handshake className="size-4 text-muted-foreground" /> Who is doing it</h3>
          {a.work_orders.length === 0 ? (
            <p className="text-muted-foreground">No work order. <Link className="text-primary-ink hover:underline" to="/subcontract/work-orders">Give it to a subcontractor</Link></p>
          ) : a.work_orders.map((w) => (
            <Link key={w.id} to={`/subcontract/work-orders/${w.id}`} className="truncate text-primary-ink hover:underline">{w.ref} · {w.vendor}</Link>
          ))}
        </div>
        <div className="flex flex-col gap-1">
          <h3 className="flex items-center gap-1.5 font-medium"><MessageSquareText className="size-4 text-muted-foreground" /> From site</h3>
          <p className="text-muted-foreground">
            {a.updates ? <>{plural(a.updates, 'update')}, last {shortDay(a.last_update, today)}. <Link to={`/site-log?project=${projectId}`} className="text-primary-ink hover:underline">Site log</Link></> : 'No updates yet.'}
          </p>
          {a.open_issues > 0 && (
            <Link to={`/issues?project=${projectId}`} className="inline-flex items-center gap-1 font-medium text-red-700 hover:underline dark:text-red-300"><AlertTriangle className="size-3.5" /> {plural(a.open_issues, 'open issue')}</Link>
          )}
        </div>
      </section>
    </div>
  )
}

function Fact({ label, children, bad }: { label: string; children: React.ReactNode; bad?: boolean }) {
  return (
    <div className="flex flex-col">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={cn('tabular-nums', bad && 'font-semibold text-red-700 dark:text-red-300')}>{children}</dd>
    </div>
  )
}
