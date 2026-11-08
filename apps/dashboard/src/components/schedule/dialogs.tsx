import * as React from 'react'
import { ArrowRight, CalendarRange, Diamond, ListOrdered, Plus, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { addDays, plural, shortDay, type Activity, type ScheduleChange } from '@/lib/schedule'
import { cn } from '@/lib/utils'

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

/** ST-04 quick plan: the sections one after another from a start day, each with its days. The fastest first
 * schedule from a freshly imported BOQ; every date can be fine-tuned afterwards. */
export function QuickPlanDialog({
  open,
  onOpenChange,
  activities,
  defaultStart,
  saving,
  onSubmit,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  activities: Activity[]
  defaultStart: string
  saving: boolean
  onSubmit: (start: string, items: { id: string; days: number }[]) => void
}) {
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
  const finish = chosen.length ? addDays(start, Math.max(total - 1, 0)) : start
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><ListOrdered className="size-4" /> Quick plan</DialogTitle>
          <DialogDescription>Put the sections one after another from a start day. Say how many days each takes (0 for a milestone); fine-tune any of them later by dragging.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3 text-sm">
          <div className="flex items-end gap-3">
            <div className="flex flex-col gap-1">
              <Label htmlFor="qp-start" className="text-xs">Work starts</Label>
              <Input id="qp-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} className="w-44" />
            </div>
            <p className="pb-2 text-muted-foreground">Finishes about <strong className="text-foreground">{shortDay(finish)}</strong> ({plural(total, 'day')})</p>
          </div>
          <ul className="max-h-[50vh] divide-y overflow-y-auto rounded-lg border">
            {activities.map((a, i) => (
              <li key={a.id} className={cn('flex items-center gap-2 px-3 py-1.5', !picked[a.id] && 'opacity-50')}>
                <input type="checkbox" className="size-4" checked={!!picked[a.id]} onChange={(e) => setPicked((p) => ({ ...p, [a.id]: e.target.checked }))} aria-label={`Include ${a.name}`} />
                <span className="w-6 text-xs text-muted-foreground tabular-nums">{i + 1}</span>
                <span className="min-w-0 flex-1 truncate">{a.name}{a.start && <span className="ml-1 text-xs text-muted-foreground">(has dates)</span>}</span>
                {days[a.id] === 0 && <Diamond className="size-3 fill-current text-violet-600" />}
                <input type="number" min={0} max={1000} value={days[a.id] ?? 7} onChange={(e) => setDays((d) => ({ ...d, [a.id]: Math.max(0, Number(e.target.value) || 0) }))} className="w-16 rounded-md border bg-background px-2 py-1 text-right tabular-nums" aria-label={`Days for ${a.name}`} />
                <span className="w-8 text-xs text-muted-foreground">days</span>
              </li>
            ))}
          </ul>
          <p className="text-xs text-muted-foreground">Each one is linked to the one before it, so a delay moves the rest. Unticked ones keep their dates.</p>
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

/** An activity or milestone that is not a BOQ section: mobilisation, approvals, handover. */
export function AddActivityDialog({
  open,
  onOpenChange,
  activities,
  defaultStart,
  saving,
  onSubmit,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  activities: Activity[]
  defaultStart: string
  saving: boolean
  onSubmit: (body: { name: string; start: string; end?: string; milestone: boolean; after: { id: string; lag: number }[] }) => void
}) {
  const [name, setName] = React.useState('')
  const [milestone, setMilestone] = React.useState(false)
  const [start, setStart] = React.useState(defaultStart)
  const [end, setEnd] = React.useState(addDays(defaultStart, 6))
  const [after, setAfter] = React.useState('')
  React.useEffect(() => {
    if (!open) return
    setName('')
    setMilestone(false)
    setStart(defaultStart)
    setEnd(addDays(defaultStart, 6))
    setAfter('')
  }, [open, defaultStart])
  const pickAfter = (id: string) => {
    setAfter(id)
    const p = activities.find((a) => a.id === id)
    if (p?.end) {
      const s = p.milestone ? p.end : addDays(p.end, 1)
      setEnd(addDays(s, Math.max(0, (new Date(end).getTime() - new Date(start).getTime()) / 86_400_000)))
      setStart(s)
    }
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><Plus className="size-4" /> Add to the schedule</DialogTitle>
          <DialogDescription>A step that is not a BOQ section: mobilisation, a permit, curing, handover.</DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-3 text-sm"
          onSubmit={(e) => {
            e.preventDefault()
            onSubmit({ name, start, end: milestone ? undefined : end, milestone, after: after ? [{ id: after, lag: 0 }] : [] })
          }}
        >
          <div className="flex flex-col gap-1">
            <Label htmlFor="add-name">Name</Label>
            <Input id="add-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Site mobilisation" required autoFocus />
          </div>
          <label className="flex items-center gap-2"><input type="checkbox" className="size-4 accent-violet-600" checked={milestone} onChange={(e) => setMilestone(e.target.checked)} /> Milestone (one day, e.g. “Slab cast”, “Handover”)</label>
          <div className="flex flex-col gap-1">
            <Label htmlFor="add-after">Starts after</Label>
            <select id="add-after" value={after} onChange={(e) => pickAfter(e.target.value)} className="h-9 rounded-md border bg-background px-2">
              <option value="">Nothing (any time)</option>
              {activities.filter((a) => a.start).map((a) => <option key={a.id} value={a.id}>{a.name} (ends {shortDay(a.end)})</option>)}
            </select>
          </div>
          <div className={cn('grid gap-2', milestone ? 'grid-cols-1' : 'grid-cols-2')}>
            <div className="flex flex-col gap-1"><Label htmlFor="add-start">{milestone ? 'Day' : 'Start'}</Label><Input id="add-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} required /></div>
            {!milestone && <div className="flex flex-col gap-1"><Label htmlFor="add-end">End</Label><Input id="add-end" type="date" value={end} min={start} onChange={(e) => setEnd(e.target.value)} required /></div>}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={saving || !name.trim()}>{saving ? 'Adding…' : 'Add'}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
