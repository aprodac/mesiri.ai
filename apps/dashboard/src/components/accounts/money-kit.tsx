import * as React from 'react'
import { rupees } from '@/lib/accounts'
import { cn } from '@/lib/utils'

// UX-34 (asked 17 Nov 2026: ledger statement, cash and bank, receivables, payables and day book in Mercon's style):
// the few parts those pages share, so each figure, colour and bar means the same on every one of them.
//   FlowStrip   - a sum as a row of tinted figures with their operators: Opening + In − Out = Closing.
//   AgeingCard  - what is owed by how long it has waited: the total, one stacked bar (a part filters), the legend.
//   PartyAvatar - a client's or supplier's initials in a stable colour.
// Colours: money in emerald, money out rose (cash and bank); debit amber, credit blue (as on the voucher); a balance sky; an age from calm to red (docs/DESIGN.md section 3).

export type FlowTone = 'in' | 'out' | 'dr' | 'cr' | 'balance' | 'plain'

const FLOW: Record<FlowTone, { card: string; fg: string }> = {
  in: { card: 'border-emerald-500/30 bg-emerald-500/[0.06]', fg: 'text-emerald-700 dark:text-emerald-400' },
  out: { card: 'border-rose-500/30 bg-rose-500/[0.05]', fg: 'text-rose-700 dark:text-rose-400' },
  dr: { card: 'border-draft/30 bg-draft-soft/50', fg: 'text-draft' },
  cr: { card: 'border-info/30 bg-info-soft/50', fg: 'text-info' },
  balance: { card: 'border-sky-500/30 bg-sky-500/[0.06]', fg: 'text-sky-700 dark:text-sky-400' },
  plain: { card: 'bg-card', fg: 'text-foreground' },
}

export interface FlowItem {
  label: string
  value: React.ReactNode
  tone: FlowTone
  sub?: React.ReactNode
  /** The operator before this figure ("+", "−", "="); none for the first. */
  op?: string
}

export function FlowStrip({ items, guide }: { items: FlowItem[]; guide?: string }) {
  return (
    <div data-guide={guide} className={cn('grid grid-cols-2 gap-2 rounded-xl border bg-card p-2 shadow-xs lg:flex lg:items-stretch', items.length === 3 ? 'sm:grid-cols-3' : 'sm:grid-cols-4')}>
      {items.map((it) => (
        <React.Fragment key={it.label}>
          {it.op && (
            <span aria-hidden="true" className="hidden shrink-0 self-center px-0.5 text-lg font-light text-muted-foreground lg:block">
              {it.op}
            </span>
          )}
          <div className={cn('min-w-0 flex-1 rounded-lg border px-3 py-2.5', FLOW[it.tone].card)}>
            <p className={cn('truncate text-xs font-medium', it.tone === 'plain' ? 'text-muted-foreground' : FLOW[it.tone].fg)}>{it.label}</p>
            <p className={cn('mt-0.5 truncate text-lg font-semibold tabular-nums sm:text-xl', FLOW[it.tone].fg)}>{it.value}</p>
            {it.sub && <div className="mt-0.5 truncate text-[11px] text-muted-foreground">{it.sub}</div>}
          </div>
        </React.Fragment>
      ))}
    </div>
  )
}

export interface AgeBucket {
  key: string
  label: string
  value: number
  /** Tailwind background for its part of the bar and its dot. */
  bar: string
  /** Late enough to call out (its figure turns red). */
  late?: boolean
}

export function AgeingCard({
  title,
  total,
  totalHint,
  buckets,
  active,
  onPick,
  aside,
  guide,
}: {
  title: string
  total: number
  totalHint?: React.ReactNode
  buckets: AgeBucket[]
  /** The bucket the list is filtered to. */
  active?: string | null
  onPick?: (key: string | null) => void
  /** Figures beside the total (overdue, advances ...). */
  aside?: React.ReactNode
  guide?: string
}) {
  const sum = buckets.reduce((t, b) => t + Math.max(0, b.value), 0) || 1
  return (
    <div data-guide={guide} className="flex flex-col gap-3 rounded-xl border bg-card p-4 shadow-xs">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div className="min-w-0">
          <p className="text-xs font-medium text-muted-foreground">{title}</p>
          <p className="text-3xl font-semibold tabular-nums tracking-tight">{rupees(total)}</p>
          {totalHint && <p className="text-xs text-muted-foreground">{totalHint}</p>}
        </div>
        {aside && <div className="flex flex-wrap gap-2">{aside}</div>}
      </div>
      <div className="flex h-3.5 w-full gap-0.5 overflow-hidden rounded-full bg-muted">
        {buckets
          .filter((b) => b.value > 0.005)
          .map((b) => (
            <button
              key={b.key}
              type="button"
              title={`${b.label}: ${rupees(b.value)}`}
              aria-label={`${b.label}: ${rupees(b.value)}. Show only these`}
              onClick={() => onPick?.(active === b.key ? null : b.key)}
              className={cn('h-full transition-opacity first:rounded-l-full last:rounded-r-full', b.bar, onPick && 'cursor-pointer hover:opacity-80', active && active !== b.key && 'opacity-35')}
              style={{ width: `${(b.value / sum) * 100}%` }}
            />
          ))}
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {buckets.map((b) => (
          <button
            key={b.key}
            type="button"
            disabled={!onPick}
            onClick={() => onPick?.(active === b.key ? null : b.key)}
            aria-pressed={active === b.key}
            className={cn('flex min-w-0 flex-col items-start rounded-lg border px-2.5 py-1.5 text-left transition-colors', onPick && 'hover:bg-muted/50', active === b.key ? 'border-foreground/40 bg-muted/60' : 'border-transparent')}
          >
            <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <span className={cn('size-2 shrink-0 rounded-full', b.bar)} /> {b.label}
            </span>
            <span className="flex items-baseline gap-1.5">
              <span className={cn('text-sm font-semibold tabular-nums', b.value <= 0.005 ? 'text-muted-foreground' : b.late ? 'text-destructive' : 'text-foreground')}>{rupees(b.value)}</span>
              {b.value > 0.005 && <span className="text-[11px] tabular-nums text-muted-foreground">{Math.round((b.value / sum) * 100)}%</span>}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}

const AVATAR = [
  'bg-sky-500/15 text-sky-700 dark:text-sky-300',
  'bg-violet-500/15 text-violet-700 dark:text-violet-300',
  'bg-teal-500/15 text-teal-700 dark:text-teal-300',
  'bg-amber-500/15 text-amber-800 dark:text-amber-300',
  'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
  'bg-orange-500/15 text-orange-700 dark:text-orange-300',
]

export function PartyAvatar({ name, className }: { name: string; className?: string }) {
  let h = 0
  for (let i = 0; i < name.length; i++) h = name.charCodeAt(i) + ((h << 5) - h)
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join('')
  return <span className={cn('flex size-9 shrink-0 items-center justify-center rounded-lg text-xs font-semibold', AVATAR[Math.abs(h) % AVATAR.length], className)}>{initials || '?'}</span>
}

/** "34 days" as a pill coloured by age (the same scale as AGE_BARS). */
export function DaysPill({ days }: { days: number }) {
  const cls =
    days > 90 ? 'bg-rose-600/10 text-rose-700 dark:text-rose-400' : days > 60 ? 'bg-orange-500/10 text-orange-700 dark:text-orange-400' : days > 30 ? 'bg-amber-500/15 text-amber-800 dark:text-amber-400' : 'bg-sky-500/10 text-sky-700 dark:text-sky-400'
  return <span className={cn('inline-flex shrink-0 items-center rounded-full px-1.5 py-px text-[11px] font-medium tabular-nums', cls)}>{days} {days === 1 ? 'day' : 'days'}</span>
}
