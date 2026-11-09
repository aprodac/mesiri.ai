import * as React from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowLeft, ArrowRightLeft, CheckCircle2, ClipboardPen, Download, Fuel, Gauge, MapPin, Pencil, ReceiptText, Trash2, Wrench } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useToast } from '@/components/ui/toast-notification'
import { Legend, MachineAvatar, OwnershipChip, ServiceChip, StateChip } from '@/components/equipment/parts'
import { HireBillDialog, LogDayDialog, LogLine, MoveDialog } from '@/components/equipment/actions'
import { MachineDialog } from '@/components/equipment/machine-dialog'
import { useAuth } from '@/lib/AuthContext'
import { usePageTitle } from '@/lib/page-title'
import { useReadOnly } from '@/lib/trial'
import { exportCsv } from '@/lib/export'
import { cn } from '@/lib/utils'
import { deleteHireBill, deleteMachine, errorWords, fetchMachine, hrs, iso, pct, rateWords, updateMachine, voidLog, type MachineDetail, type MachineLog, inr } from '@/lib/equipment'

// NXT-11 / NXT-13 / NXT-15: one machine. Its period in figures (30 days by default), a day-by-day chart, the logbook,
// what happened to it (moves, on / off hire, service), breakdowns and hire bills with their check.

const PERIODS = [{ days: 7, label: '7 days' }, { days: 30, label: '30 days' }, { days: 90, label: '90 days' }]

function Kpi({ icon: Icon, label, value, hint, tone }: { icon: React.ComponentType<{ className?: string }>; label: string; value: string; hint?: string; tone?: string }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border bg-card p-3">
      <span className={cn('inline-flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted', tone)}><Icon className="size-5" /></span>
      <span className="flex min-w-0 flex-col">
        <span className="text-xl leading-tight font-semibold tabular-nums">{value}</span>
        <span className="text-xs text-muted-foreground">{label}{hint ? ` · ${hint}` : ''}</span>
      </span>
    </div>
  )
}

function Chart({ m, days }: { m: MachineDetail; days: number }) {
  const byDate = new Map(m.logs.map((l) => [l.date, l]))
  const to = new Date(`${m.period.to}T00:00:00`)
  const cols: { date: string; log?: MachineLog }[] = []
  for (let i = days - 1; i >= 0; i--) {
    const d = iso(new Date(to.getTime() - i * 86_400_000))
    cols.push({ date: d, log: byDate.get(d) })
  }
  const max = Math.max(10, ...m.logs.map((l) => Number(l.worked_hours ?? 0) + Number(l.idle_hours ?? 0) + Number(l.breakdown_hours ?? 0)))
  return (
    <div className="flex flex-col gap-2">
      <div className="flex h-36 items-end gap-[2px]" role="img" aria-label={`Hours per day, last ${days} days`}>
        {cols.map(({ date, log }) => {
          if (!log) return <span key={date} className="flex-1 self-end rounded-sm bg-muted" style={{ height: 3 }} title={`${date}: not logged`} />
          const w = Number(log.worked_hours ?? 0), i = Number(log.idle_hours ?? 0), b = Number(log.breakdown_hours ?? 0)
          return (
            <span key={date} className="flex flex-1 flex-col-reverse overflow-hidden rounded-sm" style={{ height: `${Math.max(((w + i + b) / max) * 100, 4)}%` }}
              title={`${date}: ${w} h worked${i ? `, ${i} idle` : ''}${b ? `, ${b} breakdown` : ''}${log.fuel_litres ? `, ${Number(log.fuel_litres)} L` : ''}`}>
              <span className="bg-emerald-500" style={{ flex: w }} /><span className="bg-amber-400" style={{ flex: i }} /><span className="bg-red-500" style={{ flex: b }} />
            </span>
          )
        })}
      </div>
      <div className="flex justify-between text-[11px] text-muted-foreground tabular-nums"><span>{cols[0]?.date}</span><Legend /><span>{cols.at(-1)?.date}</span></div>
    </div>
  )
}

const EVENT_WORDS: Record<string, (e: MachineLog) => string> = {
  arrived: (e) => `Came to ${e.site_name ?? 'site'}`,
  moved: (e) => `Moved ${e.from_site_name ? `from ${e.from_site_name} ` : ''}to ${e.to_site_name ?? e.site_name}`,
  departed: (e) => `Off hire from ${e.site_name ?? 'site'}`,
  serviced: (e) => `Serviced${e.meter_reading ? ` at ${e.meter_reading} h on the meter` : ''}`,
}

export default function MachinePage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const { me } = useAuth()
  const role = (me?.role || '').toUpperCase()
  const office = ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'PROJECT_MANAGER'].includes(role)
  const seesMoney = office || role === 'FINANCE'
  const readOnly = useReadOnly()
  const toast = useToast()
  const qc = useQueryClient()
  const [days, setDays] = React.useState(30)
  const [dialog, setDialog] = React.useState<'' | 'log' | 'move' | 'edit' | 'bill'>('')
  const today = iso(new Date())
  const from = iso(new Date(Date.now() - (days - 1) * 86_400_000))
  const { data: m, isLoading, isError } = useQuery({ queryKey: ['equipment', 'machine', id, days], queryFn: () => fetchMachine(id, { date_from: from, date_to: today }) })
  usePageTitle(m?.name ?? 'Machine')

  const refresh = () => qc.invalidateQueries({ queryKey: ['equipment'] })
  const undo = useMutation({ mutationFn: voidLog, onSuccess: () => { refresh(); toast.success('Log taken back') }, onError: (e) => toast.error('Not taken back', errorWords(e)) })
  const dropBill = useMutation({ mutationFn: deleteHireBill, onSuccess: () => { refresh(); toast.success('Bill removed') }, onError: (e) => toast.error('Not removed', errorWords(e)) })
  const retire = useMutation({
    mutationFn: async () => {
      try { await deleteMachine(id); return 'deleted' } catch (e) {
        if ((e as { response?: { status?: number } })?.response?.status !== 409) throw e
        await updateMachine(id, { status: 'retired' }); return 'retired'
      }
    },
    onSuccess: (how) => { refresh(); toast.success(how === 'deleted' ? 'Machine deleted' : 'Machine retired', how === 'retired' ? 'Its logs and bills stay in the history.' : undefined); navigate('/equipment') },
    onError: (e) => toast.error('Not changed', errorWords(e)),
  })

  if (isLoading) return <div className="mx-auto w-full p-6"><div className="h-40 animate-pulse rounded-xl bg-muted/50" /></div>
  if (isError || !m) return <div className="mx-auto w-full p-6 text-sm text-destructive">This machine did not load. <Link to="/equipment" className="underline">Back to machines</Link></div>

  const p = m.period
  const exportLog = () => exportCsv(`${m.name}-log-${p.from}-${p.to}.csv`,
    ['Date', 'Site', 'Worked (h)', 'Idle (h)', 'Breakdown (h)', 'Breakdown reason', 'Diesel (L)', 'Diesel cost', 'Operator', 'Trips', 'Meter', 'Logged by', 'From'],
    m.logs.map((l) => [l.date, l.site_name ?? '', l.worked_hours ?? '', l.idle_hours ?? '', l.breakdown_hours ?? '', l.breakdown_reason ?? '', l.fuel_litres ?? '', l.fuel_cost ?? '',
      l.operator_name ?? '', l.trips ?? '', l.meter_reading ?? '', l.created_by_name ?? '', l.source ?? '']))

  return (
    <div className="mx-auto flex w-full flex-col gap-5 pb-24 sm:px-2 md:pb-8">
      <Link to="/equipment" className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" />Machines</Link>
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-4">
          <MachineAvatar machine={m} size="lg" />
          <div className="flex flex-col gap-1.5">
            <div className="flex items-baseline gap-2"><h1 className="text-2xl font-semibold tracking-tight">{m.name}</h1><span className="text-sm text-muted-foreground tabular-nums">{m.ref}</span></div>
            <div className="flex flex-wrap items-center gap-1.5"><StateChip state={m.state} /><OwnershipChip machine={m} /><ServiceChip service={m.service} /></div>
            <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-sm text-muted-foreground">
              {m.type && <span>{m.type}</span>}{m.make_model && <span>{m.make_model}</span>}{m.registration_no && <span className="tabular-nums">{m.registration_no}</span>}
              {m.site_name && <span className="inline-flex items-center gap-1"><MapPin className="size-3.5" />{m.project_name} › {m.site_name}</span>}
              {m.operator_name && <span>{m.kind === 'vehicle' ? 'Driver' : 'Operator'} {m.operator_name}</span>}
            </div>
            {seesMoney && rateWords(m) && <div className="text-sm font-medium">{rateWords(m)}{m.on_hire_from ? <span className="font-normal text-muted-foreground"> · on hire from {m.on_hire_from}</span> : null}
              {m.vendor_id && <Link to={`/finance/vendors/${m.vendor_id}`} className="ml-2 font-normal text-primary hover:underline">Their account →</Link>}</div>}
          </div>
        </div>
        {!readOnly && m.status !== 'retired' && (
          <div className="flex flex-wrap gap-2">
            {m.status === 'active' && m.site_id && <Button className="gap-1.5" onClick={() => setDialog('log')}><ClipboardPen className="size-4" />{m.today ? 'Change today' : 'Log today'}</Button>}
            <Button variant="outline" className="gap-1.5" onClick={() => setDialog('move')}><ArrowRightLeft className="size-4" />{m.status === 'off_hire' ? 'On hire again' : 'Move'}</Button>
            {seesMoney && m.ownership === 'hired' && <Button variant="outline" className="gap-1.5" onClick={() => setDialog('bill')}><ReceiptText className="size-4" />Hire bill</Button>}
            {office && <Button variant="ghost" className="gap-1.5" onClick={() => setDialog('edit')}><Pencil className="size-4" />Edit</Button>}
            {office && <Button variant="ghost" className="gap-1.5 text-destructive" disabled={retire.isPending}
              onClick={() => { if (window.confirm(`Remove ${m.name}? With logs or bills it is retired instead, and keeps its history.`)) retire.mutate() }}><Trash2 className="size-4" /></Button>}
          </div>
        )}
      </header>

      <div className="flex items-center justify-between gap-2">
        <div role="tablist" aria-label="Period" className="flex gap-0.5 rounded-xl bg-muted p-1">
          {PERIODS.map((x) => (
            <button key={x.days} role="tab" type="button" aria-selected={days === x.days} onClick={() => setDays(x.days)}
              className={cn('h-8 rounded-lg px-3 text-sm', days === x.days ? 'bg-background font-semibold shadow-sm' : 'text-foreground/75')}>{x.label}</button>
          ))}
        </div>
        <Button variant="outline" size="sm" className="gap-1.5" disabled={!m.logs.length} onClick={exportLog}><Download className="size-4" />Logbook</Button>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi icon={Gauge} label="Worked" value={hrs(p.worked)} hint={`${p.days_logged} days logged`} tone="text-emerald-700 dark:text-emerald-300" />
        <Kpi icon={AlertTriangle} label="Idle · breakdown" value={`${hrs(p.idle)} · ${hrs(p.breakdown)}`} tone="text-amber-700 dark:text-amber-300" />
        <Kpi icon={Fuel} label="Diesel" value={Number(p.fuel_litres) ? `${Number(p.fuel_litres)} L` : '–'} hint={p.litres_per_hour ? `${p.litres_per_hour} L / h` : undefined} />
        {seesMoney
          ? <Kpi icon={ReceiptText} label={m.ownership === 'hired' ? 'Hire + diesel' : 'Diesel cost'} value={inr(Number(p.hire_cost ?? 0) + Number(p.fuel_cost ?? 0))} hint={`used ${pct(p.utilisation)} of the time`} />
          : <Kpi icon={CheckCircle2} label="Used of the time on site" value={pct(p.utilisation)} />}
      </div>

      <section className="rounded-xl border p-4"><Chart m={m} days={days} /></section>

      <div className="grid gap-5 lg:grid-cols-[1fr_360px]">
        <section aria-label="Logbook" className="overflow-hidden rounded-xl border">
          <h2 className="border-b bg-muted/30 px-4 py-2 text-sm font-semibold">Logbook</h2>
          {m.logs.length === 0 && <p className="p-4 text-sm text-muted-foreground">No days logged in this period.</p>}
          <div className="divide-y">{m.logs.map((l) => <LogLine key={l.id} log={l} onVoid={readOnly ? undefined : () => { if (window.confirm(`Take back ${m.name}'s log of ${l.date}?`)) undo.mutate(l.id) }} />)}</div>
        </section>
        <div className="flex flex-col gap-5">
          {m.ownership === 'hired' && seesMoney && (
            <section aria-label="Hire bills" className="overflow-hidden rounded-xl border">
              <h2 className="flex items-center justify-between border-b bg-muted/30 px-4 py-2 text-sm font-semibold">Hire bills <Link to="/equipment/hire" className="text-xs font-normal text-primary hover:underline">Hire check</Link></h2>
              {m.bills.length === 0 && <p className="p-4 text-sm text-muted-foreground">No bill yet. When {m.vendor_name ?? 'the hire company'}'s bill comes, enter it: it is checked against the hours logged.</p>}
              {m.bills.map((b) => (
                <div key={b.id} className="flex flex-col gap-1.5 border-b px-4 py-3 text-sm last:border-b-0">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-semibold">{b.bill_ref ?? 'Bill'} <span className="font-normal text-muted-foreground">{b.period_from} – {b.period_to}</span></span>
                    <span className="font-semibold tabular-nums">{inr(b.amount)}</span>
                  </div>
                  {b.check && (
                    <>
                      <div className="flex flex-wrap gap-x-3 text-xs text-muted-foreground tabular-nums">
                        <span>billed {b.billed_hours ? `${Number(b.billed_hours)} h` : '–'}{b.billed_days ? ` / ${Number(b.billed_days)} days` : ''}</span>
                        <span>recorded {hrs(b.check.recorded.charged_hours)} chargeable · {b.check.recorded.days_on_site} days</span>
                        <span>comes to {inr(b.check.recorded.expected)}</span>
                      </div>
                      <span className={cn('w-fit rounded-full px-2 py-0.5 text-xs font-semibold', b.check.status === 'over' ? 'bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-100' : b.check.status === 'check' ? 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-100' : 'bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100')}>
                        {b.check.status === 'over' ? `₹${Number(b.check.difference).toLocaleString('en-IN')} more than recorded` : b.check.status === 'check' ? 'Check' : 'Matches the site'}
                      </span>
                      {b.check.flags.map((f) => <span key={f} className="text-xs text-muted-foreground">• {f}</span>)}
                    </>
                  )}
                  {!readOnly && <button type="button" className="w-fit text-xs text-muted-foreground hover:text-destructive" onClick={() => { if (window.confirm('Remove this bill?')) dropBill.mutate(b.id) }}>Remove</button>}
                </div>
              ))}
            </section>
          )}
          {m.breakdowns.length > 0 && (
            <section aria-label="Breakdowns" className="overflow-hidden rounded-xl border">
              <h2 className="flex items-center justify-between border-b bg-muted/30 px-4 py-2 text-sm font-semibold">Breakdowns <Link to={m.project_id ? `/issues?project=${m.project_id}${m.site_id ? `&site=${m.site_id}` : ''}` : '/issues'} className="text-xs font-normal text-primary hover:underline">Issues</Link></h2>
              {m.breakdowns.map((b) => (
                <div key={b.id} className="flex items-center gap-3 border-b px-4 py-2.5 text-sm last:border-b-0">
                  <span className="w-16 shrink-0 text-xs text-muted-foreground tabular-nums">{b.date.slice(5)}</span>
                  <span className="min-w-0 flex-1 truncate">{b.breakdown_reason ?? 'Breakdown'} <span className="text-muted-foreground">· {b.site_name}</span></span>
                  <span className="shrink-0 font-semibold text-red-700 tabular-nums dark:text-red-300">{hrs(b.breakdown_hours)}</span>
                  {b.issue_status && <span className="shrink-0 rounded-full bg-muted px-1.5 text-[11px]">{b.issue_status.toLowerCase()}</span>}
                </div>
              ))}
            </section>
          )}
          <section aria-label="What happened" className="overflow-hidden rounded-xl border">
            <h2 className="border-b bg-muted/30 px-4 py-2 text-sm font-semibold">Moves and service</h2>
            {m.events.length === 0 && <p className="p-4 text-sm text-muted-foreground">Nothing yet.</p>}
            {m.events.map((e) => (
              <div key={e.id} className="flex items-center gap-3 border-b px-4 py-2.5 text-sm last:border-b-0">
                {e.event_type === 'serviced' ? <Wrench className="size-4 shrink-0 text-muted-foreground" /> : <ArrowRightLeft className="size-4 shrink-0 text-muted-foreground" />}
                <span className="min-w-0 flex-1">{(EVENT_WORDS[e.event_type] ?? ((x) => x.event_type))(e)}</span>
                <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{e.date}</span>
              </div>
            ))}
          </section>
          {m.notes && <p className="rounded-xl border bg-muted/30 p-3 text-sm">{m.notes}</p>}
        </div>
      </div>

      <LogDayDialog machine={m} open={dialog === 'log'} onOpenChange={(o) => setDialog(o ? 'log' : '')} />
      <MoveDialog machine={m} open={dialog === 'move'} onOpenChange={(o) => setDialog(o ? 'move' : '')} />
      <HireBillDialog machine={m} open={dialog === 'bill'} onOpenChange={(o) => setDialog(o ? 'bill' : '')} />
      <MachineDialog open={dialog === 'edit'} onOpenChange={(o) => setDialog(o ? 'edit' : '')} editing={m} />
    </div>
  )
}
