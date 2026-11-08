import * as React from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Combobox } from '@/components/ui/combobox'
import { useToast } from '@/components/ui/toast-notification'
import { useAuth } from '@/lib/AuthContext'
import { cn } from '@/lib/utils'
import {
  createHireBill, errorWords, iso, moveMachine, onHire, saveLogs, useSiteOptions,
  type Machine, type MachineLog,
} from '@/lib/equipment'
import { DayBar, MachineAvatar } from './parts'

// NXT-11: the quick actions on a machine. Log the day in a few taps (Full day / Half day / broke down chips fill the
// hours; one figure is enough), move it to another site, enter the hire company's bill (NXT-13).

const num = (v: string) => v.replace(/[^0-9.]/g, '')

const PRESETS: { label: string; worked?: string; idle?: string; breakdown?: string }[] = [
  { label: 'Full day', worked: '8' },
  { label: 'Half day', worked: '4', idle: '4' },
  { label: 'Stood idle', worked: '0', idle: '8' },
  { label: 'Broke down', worked: '0', breakdown: '8' },
]

function HoursField({ id, label, value, onChange, tone }: { id: string; label: string; value: string; onChange: (v: string) => void; tone: string }) {
  const n = Number(value || 0)
  const step = (d: number) => onChange(String(Math.min(24, Math.max(0, n + d))))
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id} className="flex items-center gap-1.5"><span className={cn('size-2 rounded-sm', tone)} />{label}</Label>
      <div className="flex items-center rounded-lg border bg-background">
        <button type="button" aria-label={`${label} minus one`} onClick={() => step(-1)} className="h-10 w-9 text-lg text-muted-foreground hover:text-foreground">−</button>
        <Input id={id} inputMode="decimal" value={value} onChange={(e) => onChange(num(e.target.value))} placeholder="0"
          className="h-10 border-0 px-0 text-center text-lg font-semibold tabular-nums shadow-none focus-visible:ring-0" />
        <button type="button" aria-label={`${label} plus one`} onClick={() => step(1)} className="h-10 w-9 text-lg text-muted-foreground hover:text-foreground">+</button>
      </div>
    </div>
  )
}

export function LogDayDialog({ machine, open, onOpenChange, date }: { machine: Machine | null; open: boolean; onOpenChange: (o: boolean) => void; date?: string }) {
  const { me } = useAuth()
  const seesMoney = ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE', 'PROJECT_MANAGER'].includes((me?.role || '').toUpperCase())
  const qc = useQueryClient()
  const toast = useToast()
  const [day, setDay] = React.useState(date ?? iso(new Date()))
  const [worked, setWorked] = React.useState('')
  const [idle, setIdle] = React.useState('')
  const [breakdown, setBreakdown] = React.useState('')
  const [reason, setReason] = React.useState('')
  const [fuel, setFuel] = React.useState('')
  const [fuelCost, setFuelCost] = React.useState('')
  const [operator, setOperator] = React.useState('')
  const [trips, setTrips] = React.useState('')
  const [error, setError] = React.useState('')
  const today = machine?.today

  React.useEffect(() => {
    if (!open || !machine) return
    const t = (date ?? iso(new Date())) === iso(new Date()) ? machine.today : null
    setDay(date ?? iso(new Date()))
    setWorked(t?.worked_hours ?? '')
    setIdle(t?.idle_hours ?? '')
    setBreakdown(t?.breakdown_hours ?? '')
    setReason(t?.breakdown_reason ?? '')
    setFuel(t?.fuel_litres ?? '')
    setFuelCost(t?.fuel_cost ? String(Number(t.fuel_cost)) : '')
    setOperator(t?.operator_name ?? machine.operator_name ?? '')
    setTrips(t?.trips ? String(t.trips) : '')
    setError('')
  }, [open, machine, date])

  const total = Number(worked || 0) + Number(idle || 0) + Number(breakdown || 0)
  const save = useMutation({
    mutationFn: () => saveLogs({
      occurred_date: day,
      lines: [{
        equipment_id: machine!.id, worked_hours: worked || null, idle_hours: idle || null, breakdown_hours: breakdown || null,
        breakdown_reason: Number(breakdown) > 0 ? reason.trim() || null : null, fuel_litres: fuel || null,
        ...(seesMoney ? { fuel_cost: fuelCost || null } : {}), operator_name: operator.trim() || null,
        ...(machine!.kind === 'vehicle' ? { trips: trips ? Number(trips) : null } : {}),
      }],
    }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['equipment'] })
      qc.invalidateQueries({ queryKey: ['finance', 'costs'] })
      toast.success(`${machine!.name}: day saved`, r.issues.length ? 'The breakdown is on Issues, for whoever fixes it.' : undefined)
      onOpenChange(false)
    },
    onError: (e) => setError(errorWords(e)),
  })

  if (!machine) return null
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-3">
            <MachineAvatar machine={machine} size="sm" />
            <span className="flex flex-col leading-tight">
              <span>{machine.name}'s day</span>
              <span className="text-xs font-normal text-muted-foreground">{machine.site_name ?? 'No site'}{today && day === iso(new Date()) ? ' · changes what is saved for today' : ''}</span>
            </span>
          </DialogTitle>
        </DialogHeader>
        <form className="flex flex-col gap-4" onSubmit={(e) => { e.preventDefault(); if (total > 0 || fuel) save.mutate() }}>
          <div className="flex flex-wrap gap-2">
            {PRESETS.map((p) => (
              <button key={p.label} type="button" onClick={() => { setWorked(p.worked ?? ''); setIdle(p.idle ?? ''); setBreakdown(p.breakdown ?? '') }}
                className="h-9 rounded-full border bg-background px-3 text-sm font-medium transition hover:border-foreground/40 hover:bg-muted">
                {p.label}
              </button>
            ))}
          </div>
          <div className="grid grid-cols-3 gap-2">
            <HoursField id="lg-worked" label="Worked" value={worked} onChange={setWorked} tone="bg-emerald-500" />
            <HoursField id="lg-idle" label="Idle" value={idle} onChange={setIdle} tone="bg-amber-400" />
            <HoursField id="lg-break" label="Breakdown" value={breakdown} onChange={setBreakdown} tone="bg-red-500" />
          </div>
          <DayBar worked={worked} idle={idle} breakdown={breakdown} className="h-2.5" />
          {total > 24 && <p className="text-sm text-destructive">{total} hours is more than a day.</p>}
          {Number(breakdown) > 0 && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="lg-reason">What broke</Label>
              <Input id="lg-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Hydraulic leak, tyre puncture" maxLength={200} />
              <span className="text-xs text-muted-foreground">It goes on Issues as a breakdown, once, for whoever fixes it.</span>
            </div>
          )}
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="lg-fuel">Diesel (litres)</Label>
              <Input id="lg-fuel" inputMode="decimal" value={fuel} onChange={(e) => setFuel(num(e.target.value))} placeholder="30" className="tabular-nums" />
            </div>
            {seesMoney && (
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="lg-cost">Diesel cost</Label>
                <div className="flex items-center rounded-md border focus-within:ring-2 focus-within:ring-ring">
                  <span className="pl-2.5 text-sm text-muted-foreground">₹</span>
                  <Input id="lg-cost" inputMode="decimal" value={fuelCost} onChange={(e) => setFuelCost(num(e.target.value))} placeholder="2,700" className="border-0 tabular-nums shadow-none focus-visible:ring-0" />
                </div>
              </div>
            )}
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="lg-op">{machine.kind === 'vehicle' ? 'Driver' : 'Operator'}</Label>
              <Input id="lg-op" value={operator} onChange={(e) => setOperator(e.target.value)} placeholder="Suresh" maxLength={80} />
            </div>
            {machine.kind === 'vehicle' && (
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="lg-trips">Trips</Label>
                <Input id="lg-trips" inputMode="numeric" value={trips} onChange={(e) => setTrips(e.target.value.replace(/\D/g, ''))} placeholder="6" className="tabular-nums" />
              </div>
            )}
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="lg-day">Day</Label>
              <Input id="lg-day" type="date" value={day} max={iso(new Date())} onChange={(e) => setDay(e.target.value)} />
            </div>
          </div>
          {error && <p role="alert" className="rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={(!total && !fuel) || total > 24 || save.isPending}>{save.isPending ? 'Saving…' : 'Save the day'}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export function MoveDialog({ machine, open, onOpenChange }: { machine: Machine | null; open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const sites = useSiteOptions()
  const [siteId, setSiteId] = React.useState('')
  const [day, setDay] = React.useState(iso(new Date()))
  const [error, setError] = React.useState('')
  React.useEffect(() => { if (open) { setSiteId(''); setDay(iso(new Date())); setError('') } }, [open])
  const back = machine?.status === 'off_hire'
  const save = useMutation({
    mutationFn: () => (back ? onHire(machine!.id, { site_id: siteId, date: day }) : moveMachine(machine!.id, { site_id: siteId, date: day })),
    onSuccess: (m) => {
      qc.invalidateQueries({ queryKey: ['equipment'] })
      toast.success(back ? `${m.name} is on hire again at ${m.site_name}` : `${m.name} is at ${m.site_name} now`)
      onOpenChange(false)
    },
    onError: (e) => setError(errorWords(e)),
  })
  if (!machine) return null
  const options = (sites.data ?? []).filter((s) => s.id !== machine.site_id).map((s) => ({ value: s.id, label: `${s.projectName} › ${s.name}` }))
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader><DialogTitle>{back ? `${machine.name} back on hire` : `Move ${machine.name}`}</DialogTitle></DialogHeader>
        <div className="flex flex-col gap-3">
          {machine.site_name && <p className="text-sm text-muted-foreground">Now at <strong className="text-foreground">{machine.site_name}</strong>.</p>}
          <div className="flex flex-col gap-1.5"><Label>To site</Label>
            <Combobox options={options} value={siteId} onValueChange={setSiteId} placeholder="Pick a site" searchPlaceholder="Site or project" emptyText="No site with that name" />
          </div>
          <div className="flex flex-col gap-1.5"><Label htmlFor="mv-day">From</Label>
            <Input id="mv-day" type="date" value={day} max={iso(new Date())} onChange={(e) => setDay(e.target.value)} />
          </div>
          {error && <p role="alert" className="rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={!siteId || save.isPending} onClick={() => save.mutate()}>{back ? 'On hire' : 'Move'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function HireBillDialog({ machine, open, onOpenChange }: { machine: Pick<Machine, 'id' | 'name' | 'vendor_name' | 'rate_unit'> | null; open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const now = new Date()
  const first = iso(new Date(now.getFullYear(), now.getMonth(), 1))
  const [from, setFrom] = React.useState(first)
  const [to, setTo] = React.useState(iso(now))
  const [hours, setHours] = React.useState('')
  const [days, setDays] = React.useState('')
  const [amount, setAmount] = React.useState('')
  const [ref, setRef] = React.useState('')
  const [error, setError] = React.useState('')
  React.useEffect(() => { if (open) { setFrom(first); setTo(iso(new Date())); setHours(''); setDays(''); setAmount(''); setRef(''); setError('') } }, [open, first])
  const save = useMutation({
    mutationFn: () => createHireBill({ equipment_id: machine!.id, period_from: from, period_to: to, billed_hours: hours || null, billed_days: days || null, amount, bill_ref: ref.trim() || null }),
    onSuccess: (b) => {
      qc.invalidateQueries({ queryKey: ['equipment'] })
      const c = b.check
      if (c?.status === 'over') toast.error(`${machine!.name}: the bill asks for more than was recorded`, c.flags[0])
      else toast.success(`${machine!.name}: bill checked`, c?.status === 'ok' ? 'It matches the hours recorded on site.' : c?.flags[0])
      onOpenChange(false)
    },
    onError: (e) => setError(errorWords(e)),
  })
  if (!machine) return null
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader><DialogTitle>{machine.vendor_name ? `${machine.vendor_name}'s bill` : 'Hire bill'} for {machine.name}</DialogTitle></DialogHeader>
        <div className="grid grid-cols-2 gap-3">
          <div className="flex flex-col gap-1.5"><Label htmlFor="hb-from">From</Label><Input id="hb-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></div>
          <div className="flex flex-col gap-1.5"><Label htmlFor="hb-to">To</Label><Input id="hb-to" type="date" value={to} onChange={(e) => setTo(e.target.value)} /></div>
          <div className="flex flex-col gap-1.5"><Label htmlFor="hb-h">Hours on the bill</Label><Input id="hb-h" inputMode="decimal" value={hours} onChange={(e) => setHours(num(e.target.value))} placeholder="186" /></div>
          <div className="flex flex-col gap-1.5"><Label htmlFor="hb-d">Days on the bill</Label><Input id="hb-d" inputMode="decimal" value={days} onChange={(e) => setDays(num(e.target.value))} placeholder="24" /></div>
          <div className="flex flex-col gap-1.5"><Label htmlFor="hb-a">Amount</Label>
            <div className="flex items-center rounded-md border focus-within:ring-2 focus-within:ring-ring"><span className="pl-2.5 text-sm text-muted-foreground">₹</span>
              <Input id="hb-a" inputMode="decimal" value={amount} onChange={(e) => setAmount(num(e.target.value))} placeholder="2,04,600" className="border-0 font-semibold tabular-nums shadow-none focus-visible:ring-0" /></div>
          </div>
          <div className="flex flex-col gap-1.5"><Label htmlFor="hb-r">Bill number</Label><Input id="hb-r" value={ref} onChange={(e) => setRef(e.target.value)} placeholder="KE/77" maxLength={60} /></div>
        </div>
        <p className="text-xs text-muted-foreground">Checked at once against the hours logged on site. Pay it from the hire company's page in Finance › Suppliers.</p>
        {error && <p role="alert" className="rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={!amount || !from || !to || save.isPending} onClick={() => save.mutate()}>Check the bill</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** A day log as one line: date, site, the bar, the figures. */
export function LogLine({ log, showMachine, onVoid }: { log: MachineLog; showMachine?: boolean; onVoid?: () => void }) {
  return (
    <div className="flex items-center gap-3 px-3 py-2.5 text-sm sm:px-4">
      <span className="w-20 shrink-0 text-xs text-muted-foreground tabular-nums">{new Date(`${log.date}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', weekday: 'short' })}</span>
      <span className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
          {showMachine && <span className="font-semibold">{log.machine}</span>}
          <span className="text-muted-foreground">{log.site_name}</span>
          {log.operator_name && <span className="text-xs text-muted-foreground">· {log.operator_name}</span>}
          {log.breakdown_reason && <span className="text-xs text-red-700 dark:text-red-300">· {log.breakdown_reason}</span>}
        </span>
        <DayBar worked={log.worked_hours} idle={log.idle_hours} breakdown={log.breakdown_hours} className="max-w-xs" />
      </span>
      <span className="hidden w-14 shrink-0 text-right tabular-nums sm:block">{log.worked_hours ? `${Number(log.worked_hours)} h` : '–'}</span>
      <span className="w-14 shrink-0 text-right text-muted-foreground tabular-nums">{log.fuel_litres ? `${Number(log.fuel_litres)} L` : ''}</span>
      {onVoid && <button type="button" onClick={onVoid} className="shrink-0 text-xs text-muted-foreground hover:text-destructive" title="Take back this day's log">Undo</button>}
    </div>
  )
}
