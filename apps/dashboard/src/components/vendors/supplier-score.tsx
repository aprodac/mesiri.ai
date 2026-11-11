import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Clock, Gauge, PackageX, Star } from 'lucide-react'
import { fetchSupplierPerformance, scoreBreakdown, useSeesScores, type SupplierPerformance } from '@/lib/supplier-performance'
import { shortDate } from '@/lib/rates'
import { cn } from '@/lib/utils'

// PRC-50: the supplier score where people choose a supplier (list, pickers, comparison sheet) and in full on the
// supplier page. Worked out, never typed; the breakdown is on hover. A manual rating sits beside it, not in it.

function tone(score: number): string {
  if (score >= 4) return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300'
  if (score >= 3) return 'bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300'
  return 'bg-red-100 text-red-800 dark:bg-red-950/50 dark:text-red-300'
}

/** "★ 4.2" (or "new" with too little history), the breakdown on hover. Nothing for roles that do not see rates. */
export function ScoreChip({ p, className }: { p: SupplierPerformance | undefined; className?: string }) {
  if (!p) return null
  const title = scoreBreakdown(p)
  if (p.score === null) {
    return <span title={title} className={cn('inline-flex shrink-0 items-center rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-semibold text-muted-foreground', className)}>new</span>
  }
  return (
    <span title={title} data-testid="score-chip" className={cn('inline-flex shrink-0 items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[10px] font-bold tabular-nums', tone(Number(p.score)), className)}>
      <Gauge className="size-3" />{p.score}
    </span>
  )
}

function Sparkline({ points }: { points: { month: string; score: string | null }[] }) {
  const w = 120, h = 32
  const xy = points.map((p, i) => (p.score === null ? null : [i * (w / (points.length - 1)), h - 3 - (Number(p.score) / 5) * (h - 6)] as const))
  const path = xy.reduce((d, p, i) => (p === null ? d : `${d}${d && xy[i - 1] ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`), '')
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-8 w-[120px] text-foreground" role="img"
      aria-label={`Score by month: ${points.map((p) => `${p.month} ${p.score ?? 'none'}`).join(', ')}`}>
      <line x1="0" x2={w} y1={h - 3} y2={h - 3} className="stroke-border" strokeWidth="1" />
      <path d={path} fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinejoin="round" strokeLinecap="round" />
      {xy.map((p, i) => p && <circle key={points[i].month} cx={p[0]} cy={p[1]} r="2" fill="currentColor"><title>{`${points[i].month}: ${points[i].score}`}</title></circle>)}
    </svg>
  )
}

const PROBLEM_ICON = { late: Clock, rejected: PackageX, short: AlertTriangle }

/** The supplier page header card: score, the five measures, the trend, the last problems, the manual rating. */
export function SupplierPerformanceCard({ vendorId }: { vendorId: string }) {
  const sees = useSeesScores()
  const { data: p, isLoading } = useQuery({ queryKey: ['procurement', 'performance', vendorId], queryFn: () => fetchSupplierPerformance(vendorId), enabled: sees, retry: false })
  if (!sees) return null
  if (isLoading || !p) return <section className="h-28 animate-pulse rounded-xl border bg-card" aria-label="Supplier performance loading" />
  const m = p.measures
  const tiles = [
    { label: 'On time', value: m.on_time.pct, unit: '%', sub: m.on_time.of ? `of ${m.on_time.of} deliveries` : 'no due dates' },
    { label: 'Complete', value: m.complete.pct, unit: '%', sub: m.complete.of ? `of ${m.complete.of} orders` : 'no finished orders' },
    { label: 'Rejected', value: m.rejected.pct, unit: '%', sub: 'lower is better' },
    { label: 'Price', value: m.price.index, unit: '×', sub: m.price.index ? (Number(m.price.index) <= 1 ? 'of the average, cheaper' : 'of the average, dearer') : 'nobody else to compare' },
    { label: 'Quotes', value: m.quote_response.pct, unit: '%', sub: m.quote_response.asked ? `${m.quote_response.quoted} of ${m.quote_response.asked} RFQs · not scored` : 'never asked' },
  ]
  return (
    <section className="flex flex-col gap-3 rounded-xl border bg-card p-4" aria-label="Supplier performance">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
        <div title={scoreBreakdown(p)} className="flex items-center gap-3">
          {p.score !== null ? (
            <span className={cn('inline-flex size-14 flex-col items-center justify-center rounded-xl', tone(Number(p.score)))}>
              <span className="text-xl leading-none font-bold tabular-nums">{p.score}</span>
              <span className="text-[10px] font-semibold">of 5</span>
            </span>
          ) : (
            <span className="inline-flex size-14 items-center justify-center rounded-xl bg-muted text-muted-foreground"><Gauge className="size-6" /></span>
          )}
          <span className="flex flex-col">
            <span className="text-sm font-semibold">{p.score !== null ? 'Performance, 12 months' : 'Not enough orders yet'}</span>
            <span className="text-xs text-muted-foreground">
              {p.score !== null ? 'Worked out from orders, deliveries, rates. Hover for how.' : `${p.deliveries} of ${p.min_deliveries} deliveries needed for a score.`}
            </span>
          </span>
        </div>
        {p.trend.some((t) => t.score !== null) && (
          <div className="flex flex-col gap-0.5">
            <Sparkline points={p.trend} />
            <span className="text-[10px] text-muted-foreground">{shortDate(`${p.trend[0].month}-01`)} – now</span>
          </div>
        )}
        {p.rating && (
          <div className="flex flex-col" title={p.rating.last_note ?? undefined}>
            <span className="inline-flex items-center gap-1 text-sm font-semibold"><Star className="size-4 fill-amber-400 text-amber-400" />{p.rating.stars}<span className="text-xs font-normal text-muted-foreground">your rating · {p.rating.count} order{p.rating.count === 1 ? '' : 's'}</span></span>
            {p.rating.last_note && <span className="max-w-60 truncate text-xs text-muted-foreground">“{p.rating.last_note}”</span>}
          </div>
        )}
      </div>
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        {tiles.map((t) => (
          <div key={t.label} className="rounded-lg bg-muted/40 px-3 py-2">
            <dt className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{t.label}</dt>
            <dd className="text-base font-bold tabular-nums">{t.value !== null ? `${t.value}${t.unit}` : '—'}</dd>
            <dd className="text-[11px] text-muted-foreground">{t.sub}</dd>
          </div>
        ))}
      </dl>
      {p.problems.length > 0 && (
        <div className="flex flex-col gap-1">
          <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Last problems</h3>
          <ul className="flex flex-col divide-y rounded-lg border text-sm">
            {p.problems.map((x) => {
              const Icon = PROBLEM_ICON[x.kind]
              return (
                <li key={`${x.kind}-${x.grn_id ?? x.order_id}`} className="flex items-center gap-2 px-3 py-1.5">
                  <Icon className={cn('size-4 shrink-0', x.kind === 'late' ? 'text-amber-600' : 'text-red-600')} />
                  <span className="min-w-0 flex-1 truncate">{x.what}</span>
                  <Link to={`/procurement/orders?id=${x.order_id}&tab=all`} className="shrink-0 text-xs text-muted-foreground underline-offset-2 hover:underline">{x.grn_ref ?? x.order_ref}</Link>
                  <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{shortDate(x.date)}</span>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </section>
  )
}
