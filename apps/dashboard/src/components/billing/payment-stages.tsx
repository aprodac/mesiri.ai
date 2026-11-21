import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Flag, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DatePicker } from '@/components/ui/date-picker'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast-notification'
import { Hint } from '@/components/hint'
import { ActionButton } from '@/components/page/action-button'
import { apiErrorMessage } from '@/lib/logo-upload'
import {
  createPaymentStage, deletePaymentStage, fetchPaymentAlerts, fetchPaymentStages, rupees, updatePaymentStage,
  type PaymentAlert, type PaymentStage,
} from '@/lib/billing'
import { fetchSchedule } from '@/lib/schedule'
import { cn } from '@/lib/utils'

// FB-01: the client's payment schedule. Each stage is an amount the client pays when a point in the work is reached
// (Footing, Lintel, Roof slab), tied to the schedule activity whose completion reaches it, so the day the site marks
// "Lintel done" the office sees whether the money for it has come in. A lump-sum contract's bills are made from the
// stages reached; a measured contract's bills still come from the BOQ and the stages are the schedule only.

const NONE = '__none__'

function day(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(`${iso}T00:00:00`)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
}

const invalidate = (qc: ReturnType<typeof useQueryClient>) => {
  for (const k of ['payment-stages', 'payment-alerts', 'ra-bills', 'home']) qc.invalidateQueries({ queryKey: [k] })
}

export function PaymentStagesCard({ projectId }: { projectId: string }) {
  const toast = useToast()
  const qc = useQueryClient()
  const state = useQuery({ queryKey: ['payment-stages', projectId], queryFn: () => fetchPaymentStages(projectId) })
  const schedule = useQuery({ queryKey: ['schedule', projectId], queryFn: () => fetchSchedule(projectId), retry: false })
  const activities = schedule.data?.activities ?? []
  const [name, setName] = React.useState('')
  const [amount, setAmount] = React.useState('')
  const [activity, setActivity] = React.useState(NONE)

  const add = useMutation({
    mutationFn: () => createPaymentStage(projectId, { name: name.trim(), amount: amount.trim(), work_package_id: activity === NONE ? null : activity }),
    onSuccess: () => { setName(''); setAmount(''); setActivity(NONE); invalidate(qc) },
    onError: (e) => toast.error('Could not add the stage', apiErrorMessage(e)),
  })
  const change = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Parameters<typeof updatePaymentStage>[1] }) => updatePaymentStage(id, body),
    onSuccess: () => invalidate(qc),
    onError: (e) => toast.error('Could not change the stage', apiErrorMessage(e)),
  })
  const remove = useMutation({
    mutationFn: (id: string) => deletePaymentStage(id),
    onSuccess: () => invalidate(qc),
    onError: (e) => toast.error('Could not remove the stage', apiErrorMessage(e)),
  })

  const s = state.data
  const lump = s?.contract_type === 'lump_sum'
  const short = Number(s?.short ?? 0)

  return (
    <section className="overflow-hidden rounded-xl border bg-card shadow-xs" data-guide="ra.stages" aria-label="Payment stages">
      <header className="flex flex-wrap items-start justify-between gap-2 border-b px-4 py-3">
        <div>
          <h2 className="flex items-center gap-1.5 text-[15px] font-semibold">
            <Flag className="size-4 text-muted-foreground" /> Payment stages
            <Hint
              title="Payment stages"
              text="What the client pays at each point in the work. Tie a stage to its schedule activity: when the site marks it done, Mesiri checks the money came in and tells you if it did not."
              example="Lintel ₹4,00,000. Lintel is marked done but only ₹20,000 came in: Home and Receivables show ₹3,80,000 to follow up."
            />
          </h2>
          <p className="text-xs text-muted-foreground">
            {lump ? 'Lump sum: each new RA bill asks for the stages reached and not billed yet.' : 'The payment schedule. Bills still come from the measured BOQ work.'}
          </p>
        </div>
        {s && s.stages.length > 0 && (
          <div className="text-right text-sm tabular-nums">
            <p>{rupees(s.received)} received of {rupees(s.due)} due so far</p>
            <p className="text-xs text-muted-foreground">{rupees(s.total)} in all stages</p>
          </div>
        )}
      </header>

      {short > 0 && s?.behind_since && (
        <p className="flex items-center gap-2 border-b bg-draft-soft px-4 py-2 text-sm text-draft" role="alert">
          <AlertTriangle className="size-4 shrink-0" />
          {rupees(s.short)} not received since {s.behind_since.name} was reached ({day(s.behind_since.reached_on)}). Follow up with the client.
        </p>
      )}

      {!s ? (
        <Skeleton className="m-4 h-24" />
      ) : (
        <ul className="divide-y">
          {s.stages.map((st) => (
            <StageRow key={st.id} stage={st} activities={activities} busy={change.isPending || remove.isPending}
              onChange={(body) => change.mutate({ id: st.id, body })} onRemove={() => remove.mutate(st.id)} />
          ))}
          {s.stages.length === 0 && (
            <li className="px-4 py-3 text-sm text-muted-foreground">No stages yet. Add them from the agreement's payment schedule, e.g. Footing, Lintel, Roof slab, Handover.</li>
          )}
        </ul>
      )}

      <form
        className="grid gap-2 border-t bg-muted/30 px-4 py-3 sm:grid-cols-[1.3fr_1fr_1.4fr_auto]"
        onSubmit={(e) => { e.preventDefault(); if (name.trim() && amount.trim()) add.mutate() }}
      >
        <Input aria-label="Stage name" placeholder="Stage, e.g. Lintel" value={name} onChange={(e) => setName(e.target.value)} className="h-9" />
        <div className="relative">
          <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-sm text-muted-foreground">₹</span>
          <Input aria-label="Amount" inputMode="decimal" type="number" min={0} step="any" placeholder="Amount" value={amount} onChange={(e) => setAmount(e.target.value)} className="h-9 pl-7 tabular-nums" />
        </div>
        <ActivitySelect value={activity} onChange={setActivity} activities={activities} />
        <Button type="submit" size="sm" className="h-9 gap-1.5" data-guide="ra.stage-add" disabled={!name.trim() || !amount.trim() || add.isPending}>
          <Plus className="size-4" /> Add
        </Button>
      </form>
    </section>
  )
}

function ActivitySelect({ value, onChange, activities, disabled }: {
  value: string; onChange: (v: string) => void; activities: { id: string; name: string; milestone: boolean }[]; disabled?: boolean
}) {
  return (
    <Select value={value} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger aria-label="Reached when" className="h-9 w-full"><SelectValue placeholder="Reached when" /></SelectTrigger>
      <SelectContent>
        <SelectItem value={NONE}>Marked by hand</SelectItem>
        {activities.map((a) => <SelectItem key={a.id} value={a.id}>When {a.name} is done{a.milestone ? ' ◆' : ''}</SelectItem>)}
      </SelectContent>
    </Select>
  )
}

function StageRow({ stage, activities, busy, onChange, onRemove }: {
  stage: PaymentStage
  activities: { id: string; name: string; milestone: boolean }[]
  busy: boolean
  onChange: (body: { work_package_id?: string | null; reached_on?: string | null }) => void
  onRemove: () => void
}) {
  const billed = !!stage.bill_ref
  const status = !stage.reached
    ? { label: 'Not reached', tone: 'bg-muted text-muted-foreground' }
    : stage.paid
      ? { label: `Paid · reached ${day(stage.reached_on)}`, tone: 'bg-success-soft text-success' }
      : { label: `Due · reached ${day(stage.reached_on)}`, tone: 'bg-draft-soft text-draft' }
  return (
    <li className="grid items-center gap-2 px-4 py-2.5 text-sm sm:grid-cols-[1.3fr_1fr_1.4fr_auto]" data-record-id={stage.id}>
      <div className="min-w-0">
        <p className="truncate font-medium">{stage.name}</p>
        <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs', status.tone)}>
          {stage.reached && stage.paid && <CheckCircle2 className="size-3" />}{status.label}
        </span>
        {billed && <span className="ml-1.5 text-xs text-muted-foreground">on {stage.bill_ref}</span>}
      </div>
      <p className="tabular-nums sm:text-right">{rupees(stage.amount)}</p>
      {stage.work_package_id || activities.length > 0 ? (
        <ActivitySelect value={stage.work_package_id ?? NONE} activities={activities} disabled={busy || billed}
          onChange={(v) => onChange({ work_package_id: v === NONE ? null : v })} />
      ) : <span />}
      <div className="flex items-center justify-end gap-1">
        {!stage.work_package_id && (
          stage.reached_on ? (
            <Button size="sm" variant="ghost" disabled={busy || billed} onClick={() => onChange({ reached_on: null })}>Not reached</Button>
          ) : (
            <DatePicker value="" onChange={(d) => d && onChange({ reached_on: d })} placeholder="Mark reached" className="[&>button]:h-8" />
          )
        )}
        <ActionButton kind="delete" iconOnly label={billed ? `On ${stage.bill_ref}: cancel that bill first` : 'Remove the stage'} disabled={busy || billed} onClick={onRemove} />
      </div>
    </li>
  )
}

/** The follow-ups: projects whose client paid less than the stages reached ask for. Nothing when none. */
export function PaymentAlertsCallout({ projectId }: { projectId?: string | null }) {
  const alerts = useQuery({ queryKey: ['payment-alerts', projectId ?? null], queryFn: () => fetchPaymentAlerts(projectId), retry: false, staleTime: 60_000 })
  const rows = alerts.data?.projects ?? []
  if (rows.length === 0) return null
  return (
    <section className="rounded-xl border border-draft/40 bg-draft-soft/40 p-3" aria-label="Stage payments to follow up" data-guide="receivables.stages">
      <h2 className="mb-1.5 flex items-center gap-1.5 text-sm font-semibold text-draft">
        <AlertTriangle className="size-4" /> Stage payments to follow up · {rupees(alerts.data?.short)}
      </h2>
      <ul className="grid gap-1 text-sm">
        {rows.map((a) => <li key={a.project_id}><AlertLine alert={a} /></li>)}
      </ul>
    </section>
  )
}

export function AlertLine({ alert }: { alert: PaymentAlert }) {
  const since = alert.behind_since
  return (
    <Link to={`/billing/ra-bills?project=${alert.project_id}`} className="flex flex-wrap justify-between gap-x-3 rounded-md px-1 py-0.5 hover:bg-background/60">
      <span><span className="font-medium">{alert.project}</span>{since && <span className="text-muted-foreground"> · {since.name} reached {day(since.reached_on)}</span>}</span>
      <span className="tabular-nums">{rupees(alert.short)} short <span className="text-muted-foreground">({rupees(alert.received)} of {rupees(alert.due)})</span></span>
    </Link>
  )
}
