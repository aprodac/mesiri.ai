import * as React from 'react'
import { ArrowDownLeft, ArrowLeftRight, ArrowUpRight, BookOpen, FileText, Lock, ShoppingCart } from 'lucide-react'
import { rupees, type Nature, type VoucherType } from '@/lib/accounts'
import { cn } from '@/lib/utils'

// Visual cues shared by the Accounts pages. Colour carries one meaning each and never alone: a nature's colour sits
// beside its name; a voucher's icon beside its kind; Dr / Cr is a word, the pill only helps the eye.

/** Identity of the five natures (assets, liabilities, capital, income, expenses), always next to a label. */
export const NATURE_DOT: Record<Nature, string> = {
  asset: 'bg-sky-500',
  liability: 'bg-amber-500',
  equity: 'bg-violet-500',
  income: 'bg-emerald-500',
  expense: 'bg-rose-500',
}

export function NatureDot({ nature, className }: { nature: Nature; className?: string }) {
  return <span aria-hidden className={cn('inline-block size-2 shrink-0 rounded-full', NATURE_DOT[nature], className)} />
}

/** How big a figure is next to the largest one on the page: a thin bar, one hue. */
export function ShareBar({ value, max, className }: { value: number; max: number; className?: string }) {
  const pct = max > 0 ? Math.max(2, Math.min(100, (Math.abs(value) / max) * 100)) : 0
  if (!pct) return null
  return (
    <span aria-hidden className={cn('block h-1 w-full overflow-hidden rounded-full bg-muted', className)}>
      <span className="block h-full rounded-full bg-foreground/35" style={{ width: `${pct}%` }} />
    </span>
  )
}

/** "₹1,234.00" with a Dr / Cr pill: a debit balance plain, a credit outlined. Nil is a dash. */
export function DrCr({ value, strong, className }: { value: string | number; strong?: boolean; className?: string }) {
  const n = Number(value ?? 0)
  if (!n) return <span className={cn('text-muted-foreground', className)}>—</span>
  return (
    <span className={cn('inline-flex items-baseline justify-end gap-1.5 whitespace-nowrap tabular-nums', strong && 'font-semibold', className)}>
      {rupees(n)}
      <span
        className={cn(
          'rounded px-1 text-[10px] font-medium leading-4',
          n > 0 ? 'bg-muted text-foreground/70' : 'border border-foreground/20 text-muted-foreground',
        )}
      >
        {n > 0 ? 'Dr' : 'Cr'}
      </span>
    </span>
  )
}

/** What a voucher kind looks like: money in (receipt) and out (payment) point opposite ways. */
export const VOUCHER_LOOK: Record<VoucherType, { icon: React.ComponentType<{ className?: string }>; chip: string; word: string }> = {
  receipt: { icon: ArrowDownLeft, chip: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400', word: 'money in' },
  payment: { icon: ArrowUpRight, chip: 'bg-rose-500/10 text-rose-700 dark:text-rose-400', word: 'money out' },
  purchase: { icon: ShoppingCart, chip: 'bg-amber-500/10 text-amber-700 dark:text-amber-400', word: 'a bill' },
  sales: { icon: FileText, chip: 'bg-sky-500/10 text-sky-700 dark:text-sky-400', word: 'billed to a client' },
  contra: { icon: ArrowLeftRight, chip: 'bg-violet-500/10 text-violet-700 dark:text-violet-400', word: 'between accounts' },
  journal: { icon: BookOpen, chip: 'bg-muted text-muted-foreground', word: 'an entry' },
}

export function VoucherBadge({ type, label }: { type: VoucherType; label: string }) {
  const look = VOUCHER_LOOK[type]
  const Icon = look.icon
  return (
    <span className={cn('inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium', look.chip)} title={look.word}>
      <Icon className="size-3" /> {label}
    </span>
  )
}

/** A ledger's balance over the period, one line, with the day under the pointer. Dr above the dashed nil line,
 * Cr below. */
export function BalanceLine({ points, height = 96 }: { points: { date: string; balance: number }[]; height?: number }) {
  const ref = React.useRef<HTMLDivElement>(null)
  const [width, setWidth] = React.useState(600)
  const [hover, setHover] = React.useState<number | null>(null)
  React.useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(200, e.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  if (points.length < 2) return null
  const pad = { l: 4, r: 4, t: 10, b: 10 }
  const values = points.map((p) => p.balance)
  const lo = Math.min(0, ...values)
  const hi = Math.max(0, ...values)
  const span = hi - lo || 1
  const x = (i: number) => pad.l + (i / (points.length - 1)) * (width - pad.l - pad.r)
  const y = (v: number) => pad.t + (1 - (v - lo) / span) * (height - pad.t - pad.b)
  // Steps: a balance holds until the next entry.
  let d = `M${x(0)},${y(values[0])}`
  for (let i = 1; i < points.length; i++) d += ` H${x(i)} V${y(values[i])}`
  const at = hover ?? points.length - 1
  const p = points[at]
  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect()
    const i = Math.round(((e.clientX - box.left - pad.l) / (box.width - pad.l - pad.r)) * (points.length - 1))
    setHover(Math.max(0, Math.min(points.length - 1, i)))
  }
  return (
    <div ref={ref} className="relative w-full">
      <div className="mb-1 flex items-baseline justify-between text-xs text-muted-foreground">
        <span>Balance over the period</span>
        <span className="tabular-nums">
          {p.date} · <span className="font-medium text-foreground">{Number(p.balance) ? `${rupees(p.balance)} ${p.balance > 0 ? 'Dr' : 'Cr'}` : 'nil'}</span>
        </span>
      </div>
      <svg width={width} height={height} className="block touch-none" onPointerMove={onMove} onPointerLeave={() => setHover(null)} role="img" aria-label="Running balance over the period">
        <line x1={pad.l} x2={width - pad.r} y1={y(0)} y2={y(0)} className="stroke-border" strokeDasharray="3 3" />
        <path d={d} fill="none" className="stroke-info" strokeWidth={2} strokeLinejoin="round" />
        <line x1={x(at)} x2={x(at)} y1={pad.t - 4} y2={height - pad.b + 4} className="stroke-foreground/30" />
        <circle cx={x(at)} cy={y(values[at])} r={4} className="fill-info stroke-background" strokeWidth={2} />
      </svg>
    </div>
  )
}

/** The twelve months of a financial year as a strip: closed, open, this month, not yet. */
export function YearStrip({ fyStart, months, today }: { fyStart: number; months: { month: string; status: 'open' | 'closed'; entries: number }[]; today: string }) {
  const by = new Map(months.map((m) => [m.month, m]))
  const cells = Array.from({ length: 12 }, (_, i) => {
    const d = new Date(fyStart, 3 + i, 1)
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
    return { key, label: d.toLocaleDateString('en-IN', { month: 'short' }), m: by.get(key), future: key > today.slice(0, 7), current: key === today.slice(0, 7) }
  })
  return (
    <ol className="grid grid-cols-6 gap-1 sm:grid-cols-12" aria-label="Months of the year">
      {cells.map((c) => (
        <li
          key={c.key}
          title={c.m ? `${c.label}: ${c.m.status}, ${c.m.entries} vouchers` : c.future ? `${c.label}: not yet` : `${c.label}: no entries`}
          className={cn(
            'flex flex-col items-center gap-0.5 rounded-md border px-1 py-1.5 text-[11px]',
            c.future && 'border-dashed text-muted-foreground/60',
            c.m?.status === 'closed' && 'bg-muted text-foreground',
            c.m?.status === 'open' && !c.future && 'bg-success-soft/60 text-success',
            c.current && 'ring-2 ring-info ring-offset-1 ring-offset-background',
          )}
        >
          <span className="font-medium">{c.label}</span>
          <span className="flex h-3 items-center">
            {c.m?.status === 'closed' ? <Lock className="size-3" /> : c.m ? <span className="tabular-nums">{c.m.entries}</span> : <span>·</span>}
          </span>
        </li>
      ))}
    </ol>
  )
}
