import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowRightLeft, ClipboardPen, ExternalLink, Fuel, MapPin, Pencil, ReceiptText, Undo2, User, Wrench } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useToast } from '@/components/ui/toast-notification'
import { useReadOnly } from '@/lib/trial'
import { useAuth } from '@/lib/AuthContext'
import { cn } from '@/lib/utils'
import { errorWords, hrs, offHire, pct, rateWords, recordService, type Machine, inr } from '@/lib/equipment'
import { DayBar, MachineAvatar, OwnershipChip, ServiceChip, Spark, StateChip } from './parts'
import { HireBillDialog, LogDayDialog, MoveDialog } from './actions'
import { MachineDialog } from './machine-dialog'

// NXT-11: one machine beside the list (a sheet on a phone): where it is, today, the last two weeks, this month in
// figures, service, and the actions -- log today, move, off hire, hire bill, edit.

function Stat({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: string }) {
  return (
    <div className="rounded-lg bg-muted/50 px-3 py-2">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className={cn('text-lg leading-tight font-semibold tabular-nums', tone)}>{value}</div>
      {hint && <div className="text-[11px] text-muted-foreground">{hint}</div>}
    </div>
  )
}

export function MachinePanel({ machine: m, inSheet }: { machine: Machine; inSheet?: boolean }) {
  const { me } = useAuth()
  const readOnly = useReadOnly()
  const role = (me?.role || '').toUpperCase()
  const office = ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'PROJECT_MANAGER'].includes(role)
  const seesMoney = office || role === 'FINANCE'
  const [dialog, setDialog] = React.useState<'' | 'log' | 'move' | 'edit' | 'bill'>('')
  const qc = useQueryClient()
  const toast = useToast()
  const off = useMutation({
    mutationFn: () => offHire(m.id),
    onSuccess: (x) => { qc.invalidateQueries({ queryKey: ['equipment'] }); toast.success(`${x.name} is off hire`, x.ownership === 'hired' ? 'It stops earning hire from today.' : undefined) },
    onError: (e) => toast.error('Not changed', errorWords(e)),
  })
  const serviced = useMutation({
    mutationFn: () => recordService(m.id),
    onSuccess: (x) => { qc.invalidateQueries({ queryKey: ['equipment'] }); toast.success(`${x.name} serviced today`) },
    onError: (e) => toast.error('Not saved', errorWords(e)),
  })
  const t = m.today
  const rate = seesMoney ? rateWords(m) : null

  return (
    <div className={cn('flex flex-col gap-4 p-4', inSheet && 'pb-8')}>
      <div className="flex items-start gap-3">
        <MachineAvatar machine={m} size="lg" />
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex items-center gap-2">
            <h2 className="truncate text-xl font-semibold">{m.name}</h2>
            <span className="text-xs text-muted-foreground tabular-nums">{m.ref}</span>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <StateChip state={m.state} />
            <OwnershipChip machine={m} />
            <ServiceChip service={m.service} />
          </div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-sm text-muted-foreground">
            {m.type && <span>{m.type}</span>}
            {m.site_name && <span className="inline-flex items-center gap-1"><MapPin className="size-3.5" />{m.site_name}</span>}
            {m.operator_name && <span className="inline-flex items-center gap-1"><User className="size-3.5" />{m.operator_name}</span>}
          </div>
          {rate && <div className="text-sm font-medium">{rate}</div>}
        </div>
      </div>

      {!readOnly && m.status !== 'retired' && (
        <div className="flex flex-wrap gap-2">
          {m.status === 'active' && m.site_id && <Button size="sm" className="gap-1.5" onClick={() => setDialog('log')}><ClipboardPen className="size-4" />{t ? 'Change today' : 'Log today'}</Button>}
          <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setDialog('move')}><ArrowRightLeft className="size-4" />{m.status === 'off_hire' ? 'On hire again' : 'Move'}</Button>
          {m.status === 'active' && <Button size="sm" variant="outline" className="gap-1.5" disabled={off.isPending} onClick={() => off.mutate()}><Undo2 className="size-4" />Off hire</Button>}
          {seesMoney && m.ownership === 'hired' && <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setDialog('bill')}><ReceiptText className="size-4" />Hire bill</Button>}
          {office && <Button size="sm" variant="ghost" className="gap-1.5" onClick={() => setDialog('edit')}><Pencil className="size-4" />Edit</Button>}
        </div>
      )}

      <section aria-label="Today" className="rounded-xl border p-3">
        <div className="mb-2 flex items-center justify-between text-sm">
          <span className="font-semibold">Today</span>
          {t ? <span className="text-xs text-muted-foreground">by {t.created_by_name ?? 'someone'}{t.source === 'whatsapp' ? ' on WhatsApp' : ''}</span> : <span className="text-xs text-muted-foreground">{m.status === 'active' ? 'Not logged yet' : ''}</span>}
        </div>
        {t ? (
          <div className="flex flex-col gap-2">
            <DayBar worked={t.worked_hours} idle={t.idle_hours} breakdown={t.breakdown_hours} className="h-3" />
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm tabular-nums">
              <span><strong>{hrs(t.worked_hours)}</strong> worked</span>
              {Number(t.idle_hours) > 0 && <span className="text-amber-700 dark:text-amber-300">{hrs(t.idle_hours)} idle</span>}
              {Number(t.breakdown_hours) > 0 && <span className="text-red-700 dark:text-red-300">{hrs(t.breakdown_hours)} breakdown{t.breakdown_reason ? `: ${t.breakdown_reason}` : ''}</span>}
              {t.fuel_litres && <span className="inline-flex items-center gap-1"><Fuel className="size-3.5" />{Number(t.fuel_litres)} L</span>}
              {t.trips ? <span>{t.trips} trips</span> : null}
            </div>
            {t.issue_id && <Link to={`/issues?project=${t.project_id}&site=${t.site_id}`} className="text-xs font-medium text-red-700 hover:underline dark:text-red-300">Breakdown on Issues ({(t.issue_status ?? 'open').toLowerCase()}) →</Link>}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">{m.status === 'active' && m.site_id ? `Tap Log today, or the site sends "${m.name} 6 hrs, 30 L diesel" on WhatsApp.` : m.status === 'off_hire' ? `Off hire since ${m.off_hire_on ?? '–'}.` : 'Put it at a site to log its days.'}</p>
        )}
      </section>

      <section aria-label="Last 14 days" className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between text-xs text-muted-foreground"><span>Last 14 days</span><span>{m.last_log_date ? `last log ${m.last_log_date}` : 'no logs yet'}</span></div>
        <Spark recent={m.recent} tall />
      </section>

      <section aria-label="This month" className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <Stat label="Worked this month" value={hrs(m.month.worked)} hint={`${m.month.days_logged} days logged`} />
        <Stat label="Idle" value={hrs(m.month.idle)} tone={Number(m.month.idle) ? 'text-amber-700 dark:text-amber-300' : undefined} />
        <Stat label="Breakdown" value={hrs(m.month.breakdown)} tone={Number(m.month.breakdown) ? 'text-red-700 dark:text-red-300' : undefined} />
        <Stat label="Used (of time on site)" value={pct(m.month.utilisation)} />
        <Stat label="Diesel" value={Number(m.month.fuel_litres) ? `${Number(m.month.fuel_litres)} L` : '–'} hint={m.month.litres_per_hour ? `${m.month.litres_per_hour} L an hour` : undefined} />
        {seesMoney ? <Stat label={m.ownership === 'hired' ? 'Hire + diesel' : 'Diesel cost'} value={m.month.cost && Number(m.month.cost) ? inr(m.month.cost) : '–'} hint={m.ownership === 'hired' && m.month.hire_cost ? `hire ${inr(m.month.hire_cost)}` : undefined} />
          : m.kind === 'vehicle' ? <Stat label="Trips" value={String(m.month.trips)} /> : null}
      </section>

      {m.service && (
        <section aria-label="Service" className="flex items-center justify-between gap-3 rounded-xl border px-3 py-2.5 text-sm">
          <span className="flex items-center gap-2"><Wrench className="size-4 text-muted-foreground" />
            <span>Service every {hrs(m.service.every)} · <strong className="tabular-nums">{hrs(m.service.since)}</strong> since {m.service.last_on ? `the last (${m.service.last_on})` : 'added'}</span>
          </span>
          {!readOnly && <Button size="sm" variant="outline" disabled={serviced.isPending} onClick={() => serviced.mutate()}>Serviced today</Button>}
        </section>
      )}

      <Link to={`/equipment/${m.id}`} className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline">Logbook, moves and bills <ExternalLink className="size-3.5" /></Link>

      <LogDayDialog machine={m} open={dialog === 'log'} onOpenChange={(o) => setDialog(o ? 'log' : '')} />
      <MoveDialog machine={m} open={dialog === 'move'} onOpenChange={(o) => setDialog(o ? 'move' : '')} />
      <HireBillDialog machine={m} open={dialog === 'bill'} onOpenChange={(o) => setDialog(o ? 'bill' : '')} />
      <MachineDialog open={dialog === 'edit'} onOpenChange={(o) => setDialog(o ? 'edit' : '')} editing={m} />
    </div>
  )
}
