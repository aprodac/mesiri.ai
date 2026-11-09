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

function useWidth(min = 200) {
  const ref = React.useRef<HTMLDivElement>(null)
  const [width, setWidth] = React.useState(0)
  React.useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(min, e.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [min])
  return { ref, width }
}

/** A ledger's balance over the period, one line, with the day under the pointer. Dr above the dashed nil line,
 * Cr below. */
export function BalanceLine({ points, height = 96 }: { points: { date: string; balance: number }[]; height?: number }) {
  const { ref, width } = useWidth()
  const [hover, setHover] = React.useState<number | null>(null)
  if (points.length < 2) return null
  if (!width) return <div ref={ref} className="w-full min-w-0" style={{ height: height + 20 }} />
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
    <div ref={ref} className="relative w-full min-w-0 overflow-hidden">
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

/** Up / down against a prior figure: an arrow and the percentage. ``goodWhenUp``: income and profit (a cost going
 * up is not good). Nothing when there is nothing to compare. */
export function Delta({ pct, goodWhenUp = true, className }: { pct: number | null; goodWhenUp?: boolean; className?: string }) {
  if (pct === null || !Number.isFinite(pct)) return null
  const up = pct >= 0
  const good = up === goodWhenUp
  return (
    <span className={cn('inline-flex items-center gap-0.5 text-xs font-medium tabular-nums', good ? 'text-success' : 'text-destructive', className)}>
      {up ? '▲' : '▼'} {Math.abs(pct) >= 1000 ? '>999' : Math.abs(pct).toFixed(Math.abs(pct) < 10 ? 1 : 0)}%
    </span>
  )
}


/** Two-sided bars around a nil line: up for one thing (profit, money in), down for its opposite (loss, money out).
 * Hover a column for its figures. ``up`` / ``down`` say which is which in the key. */
export function SplitBars({
  items,
  height = 160,
  up,
  down,
  upClass = 'fill-emerald-500',
  downClass = 'fill-rose-500',
}: {
  items: { key: string; label: string; up: number; down: number; detail: React.ReactNode }[]
  height?: number
  up: string
  down: string
  upClass?: string
  downClass?: string
}) {
  const { ref, width } = useWidth()
  const [hover, setHover] = React.useState<number | null>(null)
  if (!items.length) return null
  if (!width) return <div ref={ref} className="w-full min-w-0" style={{ height: height + 20 }} />
  const top = Math.max(1, ...items.map((i) => i.up))
  const bottom = Math.max(0, ...items.map((i) => i.down))
  const pad = { t: 8, b: 20 }
  const inner = height - pad.t - pad.b
  const zero = pad.t + (inner * top) / (top + bottom || 1)
  const scale = inner / (top + bottom || 1)
  const col = width / items.length
  const bar = Math.max(4, Math.min(28, col * 0.55))
  const at = hover ?? items.length - 1
  const every = Math.ceil(items.length / Math.max(1, Math.floor(width / 48)))
  return (
    <div ref={ref} className="w-full min-w-0 overflow-hidden">
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2 text-xs text-muted-foreground">
        <span className="flex items-center gap-3">
          <span className="inline-flex items-center gap-1.5">
            <span className={cn('size-2 rounded-sm', upClass.replace('fill-', 'bg-'))} /> {up}
          </span>
          {bottom > 0 && (
            <span className="inline-flex items-center gap-1.5">
              <span className={cn('size-2 rounded-sm', downClass.replace('fill-', 'bg-'))} /> {down}
            </span>
          )}
        </span>
        <span className="tabular-nums">{items[at]?.detail}</span>
      </div>
      <svg width={width} height={height} className="block" role="img" aria-label={`${up} and ${down} by period`} onPointerLeave={() => setHover(null)}>
        <line x1={0} x2={width} y1={zero} y2={zero} className="stroke-border" />
        {items.map((it, i) => {
          const cx = col * i + col / 2
          return (
            <g key={it.key} onPointerEnter={() => setHover(i)}>
              <rect x={col * i} y={0} width={col} height={height} fill="transparent" />
              {it.up > 0 && <rect x={cx - bar / 2} y={zero - it.up * scale} width={bar} height={Math.max(1, it.up * scale)} rx={3} className={cn(upClass, hover !== null && hover !== i && 'opacity-50')} />}
              {it.down > 0 && <rect x={cx - bar / 2} y={zero + 2} width={bar} height={Math.max(1, it.down * scale)} rx={3} className={cn(downClass, hover !== null && hover !== i && 'opacity-50')} />}
              {i % every === 0 && (
                <text x={cx} y={height - 5} textAnchor="middle" className="fill-muted-foreground text-[10px]">
                  {it.label}
                </text>
              )}
            </g>
          )
        })}
      </svg>
    </div>
  )
}

/** Parts of a whole as one stacked bar with its key (cost by cost centre). Up to six parts, the rest as Other. */
export function PartsBar({ parts }: { parts: { label: string; value: number }[] }) {
  const COLOURS = ['bg-sky-500', 'bg-amber-500', 'bg-violet-500', 'bg-emerald-500', 'bg-rose-500', 'bg-slate-400']
  const sorted = [...parts].filter((p) => p.value > 0).sort((a, b) => b.value - a.value)
  const shown = sorted.slice(0, 5)
  const rest = sorted.slice(5).reduce((s, p) => s + p.value, 0)
  if (rest > 0) shown.push({ label: 'Other', value: rest })
  const total = shown.reduce((s, p) => s + p.value, 0)
  if (!total) return null
  return (
    <div className="flex flex-col gap-2">
      <div className="flex h-3 w-full gap-0.5 overflow-hidden rounded-full">
        {shown.map((p, i) => (
          <span key={p.label} className={cn('h-full', COLOURS[i])} style={{ width: `${(p.value / total) * 100}%` }} title={`${p.label}: ${rupees(p.value)}`} />
        ))}
      </div>
      <ul className="grid gap-1 text-sm">
        {shown.map((p, i) => (
          <li key={p.label} className="flex items-center gap-2">
            <span className={cn('size-2 shrink-0 rounded-sm', COLOURS[i])} />
            <span className="min-w-0 flex-1 truncate">{p.label}</span>
            <span className="tabular-nums text-muted-foreground">{((p.value / total) * 100).toFixed(0)}%</span>
            <span className="w-28 text-right tabular-nums">{rupees(p.value)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** A margin as "72.3%" (one decimal), or "—". */
export function pctText(v: string | number | null | undefined): string {
  return v === null || v === undefined || v === '' ? '—' : `${Number(v).toFixed(1)}%`
}
