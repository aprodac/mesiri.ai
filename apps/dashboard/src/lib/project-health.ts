import type { PortfolioRow } from '@/lib/cost'

// UX-57 (asked 18 Nov 2026): a project's money read two ways, side by side, so the books' profit is never read alone.
// - Books (the period): billed less the cost booked: bills, wages and expenses entered in the accounts. Materials
//   delivered but not yet billed by the supplier, and attendance not yet paid, are not in it yet, so early in a project
//   the books' margin looks far better than the truth.
// - Real, to date: the work done so far at the client's rates (billed so far + measured work not billed yet, UX-60) less
//   Cost control's full cost so far (with attendance and deliveries not billed), and where Cost control says the job
//   will finish against its BOQ budget. On the work done, not on what is billed, so a bill raised late does not read
//   as a loss; what is not billed yet is shown on its own, as money to raise.
// One rule decides a project's health for the list's order and colours, and the project page's header chip.

export type Health = 'bad' | 'attention' | 'good' | 'unknown'

export interface RealView {
  /** Billed so far (all time). */
  billed: number
  /** Measured work on no bill yet, at the client rate (/billing/to-bill). */
  unbilled: number
  /** The work done so far at the client's rates: billed + unbilled. */
  work: number
  /** Cost control's full cost so far. */
  spent: number
  profit: number
  /** Real margin %, null when nothing is billed yet. */
  margin: number | null
  budget: number | null
  forecast: number | null
  /** Forecast above the budget (positive = over). */
  over: number | null
  overPct: number | null
  done: number | null
  spentPct: number | null
}

export function realView(billedToDate: number, row: PortfolioRow | undefined, unbilled = 0): RealView | null {
  if (!row) return null
  const spent = Number(row.spent)
  const budget = row.budget === null ? null : Number(row.budget)
  const forecast = row.forecast === null ? null : Number(row.forecast)
  const over = budget !== null && forecast !== null ? forecast - budget : null
  const work = billedToDate + unbilled
  return {
    billed: billedToDate,
    unbilled,
    work,
    spent,
    profit: work - spent,
    margin: work > 0 ? ((work - spent) / work) * 100 : null,
    budget,
    forecast,
    over,
    overPct: over !== null && budget ? (over / budget) * 100 : null,
    done: row.percent_done === null ? null : Number(row.percent_done),
    spentPct: row.percent_spent === null ? null : Number(row.percent_spent),
  }
}

/** Red: losing money so far, or heading 10% or more over the budget. Amber: heading over at all, a thin real margin
 * (under 10%), or cost running ahead of the work done. Green otherwise. Unknown without Cost control figures. */
export function healthOf(real: RealView | null, booksProfit: number): { health: Health; why: string } {
  if (!real) return booksProfit < 0 ? { health: 'bad', why: 'Loss in the books' } : { health: 'unknown', why: 'No BOQ budget' }
  if (real.margin !== null && real.margin < 0) return { health: 'bad', why: 'Losing money so far' }
  if (real.overPct !== null && real.overPct >= 10) return { health: 'bad', why: `Heading ${Math.round(real.overPct)}% over budget` }
  if (real.work === 0 && real.spent > 0) return { health: 'attention', why: 'Cost with no work measured' }
  if (real.over !== null && real.over > 0) return { health: 'attention', why: 'Heading over budget' }
  if (real.margin !== null && real.margin < 10) return { health: 'attention', why: 'Thin margin' }
  if (real.done !== null && real.spentPct !== null && real.spentPct > real.done + 10) return { health: 'attention', why: 'Cost ahead of work' }
  if (real.unbilled > 0 && real.work > 0 && real.unbilled / real.work > 0.2) return { health: 'attention', why: 'Work waiting to be billed' }
  return { health: 'good', why: 'On track' }
}

export const HEALTH_ORDER: Record<Health, number> = { bad: 0, attention: 1, good: 2, unknown: 3 }

export const HEALTH_LOOK: Record<Health, { pill: string; edge: string; dot: string; label: string }> = {
  bad: { pill: 'bg-destructive/10 text-destructive', edge: 'before:bg-destructive', dot: 'bg-destructive', label: 'At risk' },
  attention: { pill: 'bg-draft-soft text-draft', edge: 'before:bg-draft', dot: 'bg-draft', label: 'Watch' },
  good: { pill: 'bg-success-soft text-success', edge: 'before:bg-success', dot: 'bg-success', label: 'Healthy' },
  unknown: { pill: 'bg-muted text-muted-foreground', edge: 'before:bg-muted-foreground/40', dot: 'bg-muted-foreground/50', label: 'No budget' },
}

/** UX-60: how old the oldest unpaid bill is: grey to 30 days, amber to 60, red after. */
export function ageTone(days: number): string {
  return days > 60 ? 'bg-destructive/10 text-destructive' : days > 30 ? 'bg-draft-soft text-draft' : 'bg-muted text-muted-foreground'
}
