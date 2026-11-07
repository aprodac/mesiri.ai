import * as React from 'react'
import { ArrowDownRight, ArrowRight, ArrowUpRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import { rate, shortDate, vendorColour, type RateItem, type RateTrend } from '@/lib/rates'

// PRC-14: the small pieces of the Rates page -- the change chip, a row's trend line, and the detail's chart.
// A supplier keeps one colour everywhere (its key's swatch), so a dot in the chart matches its row below.

const TREND_LOOK: Record<Exclude<RateTrend, null>, { chip: string; line: string; icon: typeof ArrowUpRight; word: string }> = {
  up: { chip: 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200', line: '#dc2626', icon: ArrowUpRight, word: 'up' },
  down: { chip: 'bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-200', line: '#16a34a', icon: ArrowDownRight, word: 'down' },
  same: { chip: 'bg-muted text-muted-foreground', line: '#78716c', icon: ArrowRight, word: 'about the same' },
}

/** "↑ 3.2%" in red, "↓ 1.5%" in green, "→ same"; nothing when there is nothing to compare with. */
export function TrendChip({ item, className }: { item: Pick<RateItem, 'trend' | 'change_pct'>; className?: string }) {
  if (!item.trend || item.change_pct === null) return null
  const look = TREND_LOOK[item.trend]
  const pct = Math.abs(Number(item.change_pct))
  return (
    <span className={cn('inline-flex shrink-0 items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[11px] font-semibold tabular-nums', look.chip, className)} title={`Rate ${look.word} since the purchase before`}>
      <look.icon className="size-3" strokeWidth={2.6} />
      {item.trend === 'same' ? 'same' : `${pct.toLocaleString('en-IN', { maximumFractionDigits: 1 })}%`}
    </span>
  )
}

/** A row's rates over the period as a small line; the last point is the one the row shows. */
export function Sparkline({ item, className }: { item: RateItem; className?: string }) {
  const pts = item.points
  if (pts.length < 2) return <span className={cn('text-[11px] text-muted-foreground', className)}>1 purchase</span>
  const w = 96
  const h = 28
  const values = pts.map((p) => Number(p.rate))
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const span = hi - lo || 1
  const x = (i: number) => 2 + (i / (pts.length - 1)) * (w - 4)
  const y = (v: number) => (hi === lo ? h / 2 : h - 3 - ((v - lo) / span) * (h - 6))
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(Number(p.rate)).toFixed(1)}`).join(' ')
  const colour = item.trend ? TREND_LOOK[item.trend].line : '#78716c'
  const last = pts.length - 1
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width={w} height={h} className={cn('shrink-0 overflow-visible', className)} role="img" aria-label={`Rate trend, ${rate(item.min_rate)} to ${rate(item.max_rate)}`}>
      <path d={d} fill="none" stroke={colour} strokeWidth={1.75} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={x(last)} cy={y(values[last])} r={2.6} fill={colour} />
    </svg>
  )
}

/**
 * The item's rates in the period: every purchase as a dot in its supplier's colour, joined in date order; the
 * cheapest supplier's average as a dashed line. Hover (or tap) a dot for its date, supplier and rate.
 */
export function RateChart({ item }: { item: RateItem }) {
  const [hover, setHover] = React.useState<number | null>(null)
  const pts = item.points
  const W = 420
  const H = 190
  const pad = { l: 46, r: 8, t: 16, b: 24 }
  const values = pts.map((p) => Number(p.rate))
  const bestAvg = item.best ? Number(item.best.avg_rate) : null
  const all = bestAvg !== null ? [...values, bestAvg] : values
  let lo = Math.min(...all)
  let hi = Math.max(...all)
  if (hi === lo) {
    lo = lo * 0.95
    hi = hi * 1.05 || 1
  }
  const margin = (hi - lo) * 0.12
  lo = Math.max(0, lo - margin)
  hi = hi + margin
  const t0 = new Date(`${pts[0].date}T00:00:00`).getTime()
  const t1 = new Date(`${pts[pts.length - 1].date}T00:00:00`).getTime()
  const tSpan = t1 - t0 || 1
  // Same-day purchases sit side by side rather than on top of each other.
  const x = (i: number) => {
    if (t1 === t0) return pad.l + ((i + 0.5) / pts.length) * (W - pad.l - pad.r)
    const t = new Date(`${pts[i].date}T00:00:00`).getTime()
    return pad.l + ((t - t0) / tSpan) * (W - pad.l - pad.r)
  }
  const y = (v: number) => pad.t + (1 - (v - lo) / (hi - lo)) * (H - pad.t - pad.b)
  const ticks = [lo, (lo + hi) / 2, hi]
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(Number(p.rate)).toFixed(1)}`).join(' ')
  const area = `${line} L${x(pts.length - 1).toFixed(1)},${H - pad.b} L${x(0).toFixed(1)},${H - pad.b} Z`
  const names = new Map(item.vendors.map((v) => [v.key, v.name]))
  const shown = hover !== null ? pts[hover] : null

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={`${item.material_name} rates from ${shortDate(pts[0].date)} to ${shortDate(pts[pts.length - 1].date)}`} onMouseLeave={() => setHover(null)}>
        <defs>
          <linearGradient id="rate-fill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="currentColor" stopOpacity={0.12} />
            <stop offset="100%" stopColor="currentColor" stopOpacity={0} />
          </linearGradient>
        </defs>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} className="stroke-border" strokeDasharray="2 4" />
            <text x={pad.l - 8} y={y(t) + 4} textAnchor="end" className="fill-muted-foreground text-[12px] tabular-nums">
              {rate(Math.round(t))}
            </text>
          </g>
        ))}
        {pts.length > 1 && (
          <g className="text-foreground">
            <path d={area} fill="url(#rate-fill)" />
            <path d={line} fill="none" stroke="currentColor" strokeOpacity={0.55} strokeWidth={1.75} strokeLinejoin="round" />
          </g>
        )}
        {bestAvg !== null && (
          <g>
            <line x1={pad.l} x2={W - pad.r} y1={y(bestAvg)} y2={y(bestAvg)} stroke="#16a34a" strokeWidth={1.25} strokeDasharray="6 4" />
          </g>
        )}
        {pts.map((p, i) => (
          <g key={i} onMouseEnter={() => setHover(i)} onClick={() => setHover(i)} className="cursor-pointer">
            <circle cx={x(i)} cy={y(Number(p.rate))} r={12} fill="transparent" />
            <circle cx={x(i)} cy={y(Number(p.rate))} r={hover === i ? 6 : 4.5} fill={vendorColour(p.vendor_key)} className="stroke-background" strokeWidth={2} />
          </g>
        ))}
        <text x={pad.l} y={H - 6} className="fill-muted-foreground text-[12px]">{shortDate(pts[0].date)}</text>
        <text x={W - pad.r} y={H - 6} textAnchor="end" className="fill-muted-foreground text-[12px]">{shortDate(pts[pts.length - 1].date)}</text>
      </svg>
      <div className="mt-1 flex min-h-5 flex-wrap items-center gap-x-3 gap-y-1 text-xs">
        {shown ? (
          <span className="font-medium">
            {shortDate(shown.date)} · <span style={{ color: vendorColour(shown.vendor_key) }}>●</span> {names.get(shown.vendor_key)} ·{' '}
            <span className="font-semibold tabular-nums">{rate(shown.rate)}</span> / {item.unit}
          </span>
        ) : (
          <>
            {item.vendors.map((v) => (
              <span key={v.key} className="inline-flex items-center gap-1.5 text-muted-foreground">
                <span className="size-2.5 rounded-full" style={{ background: vendorColour(v.key) }} />
                {v.name}
              </span>
            ))}
            {bestAvg !== null && (
              <span className="inline-flex items-center gap-1.5 font-medium text-green-700 dark:text-green-400">
                <span className="w-4 border-t-2 border-dashed border-current" />
                Cheapest avg {rate(bestAvg)}
              </span>
            )}
          </>
        )}
      </div>
    </div>
  )
}
