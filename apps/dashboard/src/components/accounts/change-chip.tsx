import { rupees } from '@/lib/accounts'
import { cn } from '@/lib/utils'

// UX-31 / UX-33: a figure's change against the comparison, as a small pill (owner's P&L and balance sheet).

const tiny = 0.005

/** "▲ ₹2,45,300 · 14.9%", green when it is good news. */
export function Change({ now, before, goodWhenUp, className }: { now: number; before: number | null; goodWhenUp: boolean; className?: string }) {
  if (before === null) return null
  const d = now - before
  if (Math.abs(d) < tiny) return <span className={cn('text-[11px] text-muted-foreground', className)}>no change</span>
  const pct = Math.abs(before) < tiny ? null : (d / Math.abs(before)) * 100
  const good = d > 0 === goodWhenUp
  return (
    <span className={cn('inline-flex items-center gap-0.5 rounded-full px-1.5 py-px text-[11px] font-medium tabular-nums', good ? 'bg-success-soft text-success' : 'bg-destructive/10 text-destructive', className)}>
      {d > 0 ? '▲' : '▼'} {rupees(Math.abs(d))}
      {pct !== null && ` · ${Math.abs(pct) >= 1000 ? '>999' : Math.abs(pct).toFixed(1)}%`}
    </span>
  )
}
