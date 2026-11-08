import { Car, Cog, Construction, Container, Drill, Fuel, Gauge, Hammer, Truck, Wrench, Zap, type LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import { STATE_LOOK, hrs, type Machine, type MachineState } from '@/lib/equipment'

// NXT-11: the small pieces every equipment page shares, so a machine looks the same on the board, the daily log,
// the hire check and the machine's own page.

const ICONS: [RegExp, LucideIcon][] = [
  [/jcb|backhoe|excavat|poclain|hitachi|bobcat|loader|grader/i, Construction],
  [/mixer|pump|vibrat/i, Cog],
  [/crane|hydra|hoist|lift/i, Container],
  [/compressor|breaker/i, Drill],
  [/generator|dg set/i, Zap],
  [/roller|compactor/i, Gauge],
  [/bar bend|bar cut/i, Hammer],
  [/tipper|lorry|truck|tractor|tanker|pickup/i, Truck],
  [/car|two-wheeler|bike|scooter/i, Car],
]

function machineIcon(m: Pick<Machine, 'type' | 'name' | 'kind'>): LucideIcon {
  const words = `${m.type ?? ''} ${m.name}`
  return ICONS.find(([re]) => re.test(words))?.[1] ?? (m.kind === 'vehicle' ? Truck : Wrench)
}

export function MachineAvatar({ machine, size = 'md' }: { machine: Pick<Machine, 'type' | 'name' | 'kind' | 'ownership' | 'state'>; size?: 'sm' | 'md' | 'lg' }) {
  const Icon = machineIcon(machine)
  const look = STATE_LOOK[machine.state]
  return (
    <span className={cn('relative inline-flex shrink-0 items-center justify-center rounded-xl',
      machine.ownership === 'hired' ? 'bg-teal-100 text-teal-800 dark:bg-teal-950 dark:text-teal-200' : 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200',
      size === 'sm' ? 'size-8' : size === 'lg' ? 'size-14 rounded-2xl' : 'size-11')}>
      <Icon className={size === 'sm' ? 'size-4' : size === 'lg' ? 'size-7' : 'size-5'} />
      <span aria-hidden className={cn('absolute -right-0.5 -bottom-0.5 size-3 rounded-full ring-2 ring-card', look.dot)} />
    </span>
  )
}

export function StateChip({ state, className }: { state: MachineState; className?: string }) {
  const look = STATE_LOOK[state]
  return (
    <span className={cn('inline-flex shrink-0 items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold whitespace-nowrap', look.chip, className)}>
      <span className={cn('size-1.5 rounded-full', look.dot)} />{look.label}
    </span>
  )
}

export function OwnershipChip({ machine }: { machine: Pick<Machine, 'ownership' | 'vendor_name'> }) {
  return machine.ownership === 'hired'
    ? <span className="inline-flex max-w-[180px] items-center truncate rounded-full bg-teal-50 px-2 py-0.5 text-[11px] font-semibold text-teal-800 ring-1 ring-teal-200 ring-inset dark:bg-teal-950 dark:text-teal-200 dark:ring-teal-800">Hired{machine.vendor_name ? ` · ${machine.vendor_name}` : ''}</span>
    : <span className="inline-flex items-center rounded-full bg-slate-50 px-2 py-0.5 text-[11px] font-semibold text-slate-700 ring-1 ring-slate-200 ring-inset dark:bg-slate-900 dark:text-slate-300 dark:ring-slate-700">Owned</span>
}

/** One day as a bar out of 12 hours: worked (green), idle (amber), breakdown (red). */
export function DayBar({ worked, idle, breakdown, className, scale = 12 }: { worked: string | null; idle: string | null; breakdown: string | null; className?: string; scale?: number }) {
  const parts = [
    { v: Number(worked ?? 0), c: STATE_LOOK.working.bar, label: 'worked' },
    { v: Number(idle ?? 0), c: STATE_LOOK.idle.bar, label: 'idle' },
    { v: Number(breakdown ?? 0), c: STATE_LOOK.breakdown.bar, label: 'breakdown' },
  ]
  const total = parts.reduce((n, p) => n + p.v, 0)
  const max = Math.max(scale, total)
  return (
    <span className={cn('flex h-2 overflow-hidden rounded-full bg-muted', className)} role="img"
      aria-label={total ? parts.filter((p) => p.v).map((p) => `${p.v} h ${p.label}`).join(', ') : 'not logged'}>
      {parts.map((p) => p.v > 0 && <span key={p.label} className={p.c} style={{ width: `${(p.v / max) * 100}%` }} />)}
    </span>
  )
}

/** The last 14 days, one column per day (worked over idle over breakdown); a missing day is a dash. */
export function Spark({ recent, className, tall = false }: { recent: Machine['recent']; className?: string; tall?: boolean }) {
  const max = Math.max(10, ...recent.map((d) => Number(d.worked ?? 0) + Number(d.idle ?? 0) + Number(d.breakdown ?? 0)))
  const h = tall ? 56 : 28
  return (
    <span className={cn('flex items-end gap-[3px]', className)} style={{ height: h }} aria-hidden>
      {recent.map((d) => {
        const w = Number(d.worked ?? 0), i = Number(d.idle ?? 0), b = Number(d.breakdown ?? 0)
        if (d.worked === null) return <span key={d.date} className="w-full flex-1 self-end rounded-sm bg-muted" style={{ height: 3 }} title={`${d.date}: not logged`} />
        return (
          <span key={d.date} className="flex w-full flex-1 flex-col-reverse overflow-hidden rounded-sm" style={{ height: `${Math.max(((w + i + b) / max) * 100, 8)}%` }}
            title={`${d.date}: ${w} h worked${i ? `, ${i} idle` : ''}${b ? `, ${b} breakdown` : ''}${d.fuel && Number(d.fuel) ? `, ${d.fuel} L` : ''}`}>
            <span className={STATE_LOOK.working.bar} style={{ flex: w }} />
            <span className={STATE_LOOK.idle.bar} style={{ flex: i }} />
            <span className={STATE_LOOK.breakdown.bar} style={{ flex: b }} />
          </span>
        )
      })}
    </span>
  )
}

export function ServiceChip({ service }: { service: Machine['service'] }) {
  if (!service || service.status === 'ok') return null
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold',
      service.status === 'due' ? 'bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-100' : 'bg-orange-100 text-orange-900 dark:bg-orange-950 dark:text-orange-100')}>
      <Wrench className="size-3" />{service.status === 'due' ? 'Service due' : `Service in ${hrs(service.left)}`}
    </span>
  )
}

export function FuelFigure({ litres, className }: { litres: string | null | undefined; className?: string }) {
  if (!litres || !Number(litres)) return null
  return <span className={cn('inline-flex items-center gap-1 tabular-nums', className)}><Fuel className="size-3.5 opacity-70" />{Number(litres)} L</span>
}

export function Legend({ className }: { className?: string }) {
  return (
    <span className={cn('flex flex-wrap items-center gap-3 text-xs text-muted-foreground', className)}>
      {(['working', 'idle', 'breakdown'] as const).map((s) => (
        <span key={s} className="inline-flex items-center gap-1.5"><span className={cn('size-2 rounded-sm', STATE_LOOK[s].bar)} />{s === 'working' ? 'Worked' : s === 'idle' ? 'Idle' : 'Breakdown'}</span>
      ))}
    </span>
  )
}
