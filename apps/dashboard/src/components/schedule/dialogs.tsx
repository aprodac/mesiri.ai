import * as React from 'react'
import { Hint } from '@/components/hint'
import { ArrowRight, CalendarDays, CalendarRange, Diamond, ListOrdered, Plus, Scale, TriangleAlert, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  countWorkDays, endForWorkDays, nextWorkDay, plural, shortDay, WEEK_DAYS, weekWords, workCalendar,
  type Activity, type LinkKind, type ScheduleChange, type ScheduleProject,
} from '@/lib/schedule'
import { cn } from '@/lib/utils'
import { DatePicker } from '@/components/ui/date-picker'

/** ST-04: a change is shown before it is saved: what moves with it, and how far the project's last day moves. */
export function ConfirmChangeDialog({
  label,
  preview,
  loading,
  saving,
  error,
  today,
  onConfirm,
  onCancel,
}: {
  label: string
  preview: ScheduleChange | null
  loading: boolean
  saving: boolean
  error: string
  today: string
  onConfirm: () => void
  onCancel: () => void
}) {
  const moved = preview?.moved ?? []
  return (
    <Dialog open onOpenChange={(o) => !o && onCancel()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{label}</DialogTitle>
          <DialogDescription>Check what moves with it before saving.</DialogDescription>
        </DialogHeader>
        {loading && <p className="animate-pulse text-sm text-muted-foreground">Working out what moves…</p>}
        {error && <p className="flex items-center gap-2 text-sm text-destructive"><TriangleAlert className="size-4" /> {error}</p>}
        {preview && (
          <div className="flex flex-col gap-3 text-sm">
            {moved.length === 0 ? (
              <p className="rounded-lg bg-success-soft px-3 py-2 text-success">Nothing else moves.</p>
            ) : (
              <>
                <p><strong>{plural(moved.length, 'activity')}</strong> after it {moved.length === 1 ? 'moves' : 'move'} too, keeping {moved.length === 1 ? 'its' : 'their'} length:</p>
                <ul className="max-h-56 divide-y overflow-y-auto rounded-lg border">
                  {moved.map((m) => (
                    <li key={m.id} className="flex items-center gap-2 px-3 py-1.5">
                      <span className="min-w-0 flex-1 truncate font-medium">{m.name}</span>
                      <span className="text-xs text-muted-foreground tabular-nums">{shortDay(m.from_start, today)}</span>
                      <ArrowRight className="size-3 text-muted-foreground" />
                      <span className="text-xs tabular-nums">{shortDay(m.start, today)}</span>
                      {m.days !== null && <span className={cn('w-12 text-right text-xs font-semibold tabular-nums', m.days > 0 ? 'text-red-600' : 'text-success')}>{m.days > 0 ? '+' : ''}{m.days}d</span>}
                    </li>
                  ))}
                </ul>
              </>
            )}
            {preview.finish_moves !== 0 && (
              <p className={cn('rounded-lg px-3 py-2 font-medium', preview.finish_moves > 0 ? 'bg-red-50 text-red-800 dark:bg-red-950 dark:text-red-200' : 'bg-success-soft text-success')}>
                The last day of the work moves {preview.finish_moves > 0 ? 'later' : 'earlier'} by {plural(Math.abs(preview.finish_moves), 'day')}, to {shortDay(preview.schedule.summary.planned_finish, today)}.
              </p>
            )}
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>Cancel</Button>
          <Button disabled={!preview || saving} onClick={onConfirm}>{saving ? 'Saving…' : moved.length ? `Save and move ${moved.length + 1}` : 'Save'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** ST-04 quick plan: the sections one after another from a start day, each with its working days. The fastest first
 * schedule from a freshly imported BOQ; every date can be fine-tuned afterwards. QA Step 11: days are working days on
 * the project's calendar; a start in the past is called out (the work would show as behind at once); the finish is
 * set against the client's handover, and "Spread to handover" shares the time by each section's BOQ value. */
export function QuickPlanDialog({
  open,
  onOpenChange,
  activities,
  project,
  today,
  defaultStart,
  saving,
  onSubmit,
  onCalendar,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  activities: Activity[]
  project: ScheduleProject
  today: string
  defaultStart: string
  saving: boolean
  onSubmit: (start: string, items: { id: string; days: number }[]) => void
  onCalendar?: () => void
}) {
  const cal = React.useMemo(() => workCalendar(project), [project])
  const [start, setStart] = React.useState(defaultStart)
  const [days, setDays] = React.useState<Record<string, number>>({})
  const [picked, setPicked] = React.useState<Record<string, boolean>>({})
  React.useEffect(() => {
    if (!open) return
    setStart(defaultStart)
    setDays(Object.fromEntries(activities.map((a) => [a.id, a.duration ?? (a.milestone ? 0 : 7)])))
    setPicked(Object.fromEntries(activities.map((a) => [a.id, !a.start])))
  }, [open, activities, defaultStart])
  const chosen = activities.filter((a) => picked[a.id])
  const total = chosen.reduce((n, a) => n + (days[a.id] ?? 0), 0)
  const first = nextWorkDay(cal, start)
  const finish = chosen.length ? endForWorkDays(cal, first, Math.max(total, 1)) : start
  const handover = project.planned_finish
  const room = handover && handover >= first ? countWorkDays(cal, first, handover) : null
  const gap = handover ? Math.round((Date.parse(handover) - Date.parse(finish)) / 86_400_000) : 0
  const past = start < today

  /** The working days up to handover, shared by each section's BOQ value (equally when the values are not known). */
  const spread = () => {
    if (!room) return
    const work = chosen.filter((a) => (days[a.id] ?? 0) > 0)
    const weights = work.map((a) => a.weight ?? 0)
    const sum = weights.reduce((x, y) => x + y, 0)
    const next = { ...days }
    work.forEach((a, i) => { next[a.id] = Math.max(1, Math.floor(room * (sum > 0 ? weights[i] / sum : 1 / work.length))) })
    setDays(next)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><ListOrdered className="size-4" /> Quick plan <Hint title="Quick plan" text="The sections go one after another from the start day, each linked to the one before it, so a delay moves the rest. Days are working days: the project's days off and holidays are skipped. 0 days makes a milestone. Unticked ones keep their dates. Fine-tune later: drag the bars, or make work run alongside with 'with it' in an activity." /></DialogTitle>
          <DialogDescription className="sr-only">Put the sections one after another from a start day.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3 text-sm">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1">
              <Label htmlFor="qp-start" className="text-xs">Work starts</Label>
              <DatePicker id="qp-start" value={start} onChange={(v) => setStart(v)} className="w-44" />
            </div>
            <p className="pb-2 text-muted-foreground">Finishes about <strong className="text-foreground">{shortDay(finish, today)}</strong> ({plural(total, 'working day')})</p>
          </div>
          <p className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
            <CalendarDays className="size-3.5" /> Working days: {weekWords(cal.week)}{cal.holidays.size ? `, ${plural(cal.holidays.size, 'holiday')} off` : ''}
            {onCalendar && <button type="button" className="text-primary-ink underline-offset-2 hover:underline" onClick={onCalendar}>Change</button>}
          </p>
          {past && (
            <div className="flex flex-wrap items-center gap-2 rounded-lg bg-draft-soft px-3 py-2 text-draft">
              <TriangleAlert className="size-4 shrink-0" />
              <span className="min-w-0 flex-1">Starts {shortDay(start, today)}, before today: the first work shows as behind at once until site reports it.</span>
              <Button size="sm" variant="outline" onClick={() => setStart(today)}>Start today</Button>
            </div>
          )}
          {handover && chosen.length > 0 && (
            <div className={cn('flex flex-wrap items-center gap-2 rounded-lg px-3 py-2', gap < 0 ? 'bg-destructive/10 text-destructive' : 'bg-muted/60')}>
              <span className="min-w-0 flex-1">
                Client's handover <strong>{shortDay(handover, today)}</strong>:{' '}
                {gap < 0 ? <strong>{plural(-gap, 'day')} late</strong> : gap === 0 ? 'finishes on the day' : <>finishes {plural(gap, 'day')} early</>}
              </span>
              {room && room > chosen.length && (
                <Button size="sm" variant="outline" className="gap-1.5" onClick={spread} title="Share the working days up to handover by each section's BOQ value">
                  <Scale className="size-3.5" /> Spread to handover
                </Button>
              )}
            </div>
          )}
          <ul className="max-h-[50vh] divide-y overflow-y-auto rounded-lg border">
            {activities.map((a, i) => (
              <li key={a.id} className={cn('flex items-center gap-2 px-3 py-1.5', !picked[a.id] && 'opacity-50')}>
                <input type="checkbox" className="size-4" checked={!!picked[a.id]} onChange={(e) => setPicked((p) => ({ ...p, [a.id]: e.target.checked }))} aria-label={`Include ${a.name}`} />
                <span className="w-6 text-xs text-muted-foreground tabular-nums">{i + 1}</span>
                <span className="min-w-0 flex-1 truncate">{a.name}{a.site_name && <span className="ml-1 text-xs text-muted-foreground">· {a.site_name}</span>}{a.start && <span className="ml-1 text-xs text-muted-foreground">(has dates)</span>}</span>
                {days[a.id] === 0 && <Diamond className="size-3 fill-current text-foreground" />}
                <input type="number" min={0} max={1000} value={days[a.id] ?? 7} onChange={(e) => setDays((d) => ({ ...d, [a.id]: Math.max(0, Number(e.target.value) || 0) }))} className="w-16 rounded-md border bg-background px-2 py-1 text-right tabular-nums" aria-label={`Working days for ${a.name}`} />
                <span className="w-8 text-xs text-muted-foreground">days</span>
              </li>
            ))}
          </ul>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={saving || chosen.length === 0} onClick={() => onSubmit(start, chosen.map((a) => ({ id: a.id, days: days[a.id] ?? 7 })))} className="gap-1.5">
            <CalendarRange className="size-4" /> {saving ? 'Planning…' : `Plan ${plural(chosen.length, 'activity')}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** An activity or milestone that is not a BOQ section: mobilisation, approvals, handover; or a BOQ section's work on
 * one site ("Villa 2 slab"), planned on its own. */
export function AddActivityDialog({
  open,
  onOpenChange,
  activities,
  project,
  sites,
  people,
  defaultStart,
  saving,
  onSubmit,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  activities: Activity[]
  project: ScheduleProject
  sites: { id: string; name: string }[]
  people: { id: string; name: string }[]
  defaultStart: string
  saving: boolean
  onSubmit: (body: { name: string; start: string; end?: string; milestone: boolean; site_id: string | null; assigned_user_id: string | null; after: { id: string; lag: number; kind: LinkKind }[] }) => void
}) {
  const cal = React.useMemo(() => workCalendar(project), [project])
  const [name, setName] = React.useState('')
  const [milestone, setMilestone] = React.useState(false)
  const [start, setStart] = React.useState(defaultStart)
  const [end, setEnd] = React.useState(endForWorkDays(cal, defaultStart, 6))
  const [after, setAfter] = React.useState('')
  const [kind, setKind] = React.useState<LinkKind>('FS')
  const [site, setSite] = React.useState('')
  const [person, setPerson] = React.useState('')
  React.useEffect(() => {
    if (!open) return
    setName('')
    setMilestone(false)
    setStart(nextWorkDay(cal, defaultStart))
    setEnd(endForWorkDays(cal, defaultStart, 6))
    setAfter('')
    setKind('FS')
    setSite('')
    setPerson('')
  }, [open, defaultStart, cal])
  const length = Math.max(countWorkDays(cal, start, end), 1)
  const place = (id: string, how: LinkKind) => {
    const p = activities.find((a) => a.id === id)
    if (!p?.end || !p.start) return
    const s = how === 'SS' ? nextWorkDay(cal, p.start) : p.milestone ? nextWorkDay(cal, p.end) : nextWorkDay(cal, endForWorkDays(cal, p.end, 2))
    setStart(s)
    setEnd(endForWorkDays(cal, s, length))
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><Plus className="size-4" /> Add to the schedule <Hint title="Add to the schedule" text="A step that is not a BOQ section (mobilisation, a permit, curing, handover), or one site's part of the work (Villa 2 slab) planned on its own." /></DialogTitle>
          <DialogDescription className="sr-only">A step that is not a BOQ section.</DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-3 text-sm"
          onSubmit={(e) => {
            e.preventDefault()
            onSubmit({ name, start, end: milestone ? undefined : end, milestone, site_id: site || null, assigned_user_id: person || null, after: after ? [{ id: after, lag: 0, kind }] : [] })
          }}
        >
          <div className="flex flex-col gap-1">
            <Label htmlFor="add-name">Name</Label>
            <Input id="add-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Site mobilisation" required autoFocus />
          </div>
          <label className="flex items-center gap-2"><input type="checkbox" className="size-4 accent-foreground" checked={milestone} onChange={(e) => setMilestone(e.target.checked)} /> Milestone (one day)</label>
          <div className="grid grid-cols-2 gap-2">
            <div className="flex flex-col gap-1">
              <Label htmlFor="add-site">Site</Label>
              <select id="add-site" value={site} onChange={(e) => setSite(e.target.value)} className="h-9 rounded-md border bg-background px-2">
                <option value="">All sites</option>
                {sites.map((st) => <option key={st.id} value={st.id}>{st.name}</option>)}
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="add-person">Who runs it</Label>
              <select id="add-person" value={person} onChange={(e) => setPerson(e.target.value)} className="h-9 rounded-md border bg-background px-2">
                <option value="">Nobody named</option>
                {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="add-after">Follows</Label>
            <div className="flex gap-2">
              <select id="add-after" value={after} onChange={(e) => { setAfter(e.target.value); place(e.target.value, kind) }} className="h-9 min-w-0 flex-1 rounded-md border bg-background px-2">
                <option value="">Nothing (any time)</option>
                {activities.filter((a) => a.start).map((a) => <option key={a.id} value={a.id}>{a.name}{a.site_name ? ` · ${a.site_name}` : ''}</option>)}
              </select>
              {after && (
                <select aria-label="How it follows" value={kind} onChange={(e) => { const k = e.target.value as LinkKind; setKind(k); place(after, k) }} className="h-9 rounded-md border bg-background px-2">
                  <option value="FS">after it ends</option>
                  <option value="SS">with it</option>
                </select>
              )}
            </div>
          </div>
          <div className={cn('grid gap-2', milestone ? 'grid-cols-1' : 'grid-cols-2')}>
            <div className="flex flex-col gap-1"><Label htmlFor="add-start">{milestone ? 'Day' : 'Start'}</Label><DatePicker id="add-start" value={start} onChange={(v) => setStart(v)} required /></div>
            {!milestone && <div className="flex flex-col gap-1"><Label htmlFor="add-end">End</Label><DatePicker id="add-end" value={end} min={start} onChange={(v) => setEnd(v)} required /></div>}
          </div>
          {!milestone && <p className="text-xs text-muted-foreground">{plural(countWorkDays(cal, start, end), 'working day')} ({weekWords(cal.week)})</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={saving || !name.trim()}>{saving ? 'Adding…' : 'Add'}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/** QA Step 11: the days site works and the holidays, for this project. Dates already planned stay; lengths, the push
 * and Quick plan count working days from now on. */
export function WorkCalendarDialog({
  open,
  onOpenChange,
  project,
  saving,
  onSave,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  project: ScheduleProject
  saving: boolean
  onSave: (body: { work_week: string; holidays: string[] }) => void
}) {
  const [week, setWeek] = React.useState(project.work_week ?? '1111111')
  const [holidays, setHolidays] = React.useState<string[]>(project.holidays ?? [])
  const [day, setDay] = React.useState('')
  React.useEffect(() => {
    if (!open) return
    setWeek(project.work_week ?? '1111111')
    setHolidays(project.holidays ?? [])
    setDay('')
  }, [open, project])
  const toggle = (i: number) => setWeek((w) => w.slice(0, i) + (w[i] === '1' ? '0' : '1') + w.slice(i + 1))
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><CalendarDays className="size-4" /> Working days</DialogTitle>
          <DialogDescription>Days off are skipped when Mesiri counts an activity's days and moves what follows.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4 text-sm">
          <div className="flex flex-col gap-1.5">
            <span className="text-xs font-medium">Site works on</span>
            <div className="flex flex-wrap gap-1.5">
              {WEEK_DAYS.map((d, i) => (
                <button key={d} type="button" aria-pressed={week[i] === '1'} onClick={() => toggle(i)}
                  className={cn('w-12 rounded-md border py-1.5 text-xs font-medium', week[i] === '1' ? 'border-primary bg-primary/10 text-foreground' : 'text-muted-foreground line-through')}>
                  {d}
                </button>
              ))}
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <span className="text-xs font-medium">Holidays</span>
            <div className="flex items-center gap-2">
              <DatePicker id="hol-day" value={day} onChange={(v) => setDay(v)} className="w-44" />
              <Button type="button" size="sm" variant="outline" disabled={!day || holidays.includes(day)} onClick={() => { setHolidays((h) => [...h, day].sort()); setDay('') }}>Add</Button>
            </div>
            {holidays.length === 0 ? <p className="text-xs text-muted-foreground">None yet: Onam, Diwali, a local festival.</p> : (
              <ul className="flex flex-wrap gap-1.5">
                {holidays.map((h) => (
                  <li key={h} className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs">
                    {shortDay(h)} {h.slice(0, 4)}
                    <button type="button" aria-label={`Remove ${h}`} onClick={() => setHolidays((x) => x.filter((y) => y !== h))}><X className="size-3" /></button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <p className="text-xs text-muted-foreground">Dates already planned stay as they are. Run Quick plan again to spread the work on the new days.</p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={saving || !week.includes('1')} onClick={() => onSave({ work_week: week, holidays })}>{saving ? 'Saving…' : 'Save'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
