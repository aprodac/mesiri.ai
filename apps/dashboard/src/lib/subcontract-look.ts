import type { LucideIcon } from 'lucide-react'
import { BrickWall, Construction, Droplets, Grid3x3, Hammer, HardHat, PaintRoller, Paintbrush, Plug, ShieldHalf, Wrench } from 'lucide-react'
import { n, type WorkOrder } from './subcontracts'

// UX-64 (18 Nov 2026): the subcontract module's visual language, one place for every page. A job's state (one colour
// each, worst first), a trade's icon and colour (from the work's own words), and the money bar (paid · billed not paid
// · done not billed · left). All read from what GET /subcontracts/work-orders already returns; nothing is stored.

/** A job with nothing measured for this many days is idle (asked 18 Nov: the recommended 14). */
export const IDLE_DAYS = 14

export type JobState = 'over' | 'late' | 'check' | 'retention' | 'idle' | 'draft' | 'track' | 'done' | 'closed'

/** Worst first: a team's state is its worst job's. */
export const STATE_ORDER: JobState[] = ['over', 'late', 'check', 'retention', 'idle', 'draft', 'track', 'done', 'closed']

export const STATE_LOOK: Record<JobState, { label: string; chip: string; dot: string; edge: string }> = {
  over: { label: 'Over-billed', chip: 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200', dot: 'bg-red-500', edge: 'before:bg-red-500' },
  late: { label: 'Late', chip: 'bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-200', dot: 'bg-rose-500', edge: 'before:bg-rose-500' },
  check: { label: 'Bill to check', chip: 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-100', dot: 'bg-amber-500', edge: 'before:bg-amber-500' },
  retention: { label: 'Retention due', chip: 'bg-violet-100 text-violet-900 dark:bg-violet-950 dark:text-violet-100', dot: 'bg-violet-500', edge: 'before:bg-violet-500' },
  idle: { label: 'Idle', chip: 'bg-orange-100 text-orange-900 dark:bg-orange-950 dark:text-orange-100', dot: 'bg-orange-400', edge: 'before:bg-orange-400' },
  draft: { label: 'Draft', chip: 'bg-stone-200 text-stone-800 dark:bg-stone-800 dark:text-stone-100', dot: 'bg-stone-400', edge: 'before:bg-stone-300' },
  track: { label: 'On track', chip: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100', dot: 'bg-emerald-500', edge: 'before:bg-emerald-500' },
  done: { label: 'Work done', chip: 'bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-100', dot: 'bg-sky-500', edge: 'before:bg-sky-400' },
  closed: { label: 'Closed', chip: 'bg-muted text-muted-foreground', dot: 'bg-muted-foreground/40', edge: 'before:bg-muted' },
}

const dayMs = 86_400_000
const daysBetween = (from: string, to: string) => Math.round((Date.parse(to.slice(0, 10)) - Date.parse(from.slice(0, 10))) / dayMs)

/** The day the retention can be released: the work's completion plus its defect period. */
export function retentionDay(w: Pick<WorkOrder, 'completed_on' | 'defect_days'>): string | null {
  if (!w.completed_on) return null
  return new Date(Date.parse(`${w.completed_on}T00:00:00Z`) + w.defect_days * dayMs).toISOString().slice(0, 10)
}

/** The last day anything was measured on the job (or it was issued, when nothing was yet). */
export function lastMeasured(w: WorkOrder): string | null {
  const days = w.lines.map((l) => l.last_measured).filter((d): d is string => !!d).sort()
  return days.at(-1) ?? w.issued_at?.slice(0, 10) ?? w.start_date ?? null
}

export interface JobView {
  state: JobState
  /** "5 days late", "since 12 Dec", "releases 4 Jan": the state's few words. */
  note: string | null
  /** Days to the end date (negative: late); null without one or once done. */
  daysLeft: number | null
}

/** One job's state on `today` (the company's day, lib/clock appNow). */
export function jobView(w: WorkOrder, today: string): JobView {
  const done = Number(w.totals.progress_pct)
  const daysLeft = w.end_date && w.status === 'issued' ? daysBetween(today, w.end_date) : null
  if (w.status === 'cancelled' || w.status === 'closed') return { state: 'closed', note: null, daysLeft: null }
  if (w.status === 'draft') return { state: 'draft', note: 'not issued', daysLeft: null }
  if (w.flags > 0) return { state: 'over', note: `${w.flags} ${w.flags === 1 ? 'line' : 'lines'}`, daysLeft }
  if (w.status === 'issued' && daysLeft !== null && daysLeft < 0 && done < 100) return { state: 'late', note: `${-daysLeft} ${daysLeft === -1 ? 'day' : 'days'} late`, daysLeft }
  if (w.totals.to_check > 0) return { state: 'check', note: `${w.totals.to_check} ${w.totals.to_check === 1 ? 'bill' : 'bills'}`, daysLeft }
  if (w.status === 'completed') {
    const release = retentionDay(w)
    const held = n(w.totals.retention_held)
    if (held > 0 && release && release <= today) return { state: 'retention', note: 'release now', daysLeft: null }
    return { state: 'done', note: held > 0 && release ? `retention ${shortDay(release)}` : null, daysLeft: null }
  }
  const last = lastMeasured(w)
  if (last && daysBetween(last, today) >= IDLE_DAYS) return { state: 'idle', note: `nothing measured since ${shortDay(last)}`, daysLeft }
  return { state: 'track', note: daysLeft !== null ? (daysLeft === 0 ? 'due today' : `${daysLeft} days left`) : null, daysLeft }
}

export function worst(states: JobState[]): JobState {
  return STATE_ORDER.find((s) => states.includes(s)) ?? 'closed'
}

export function shortDay(iso: string): string {
  return new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
}

// --- Trade -------------------------------------------------------------------------------------------------------

const TRADES: { match: RegExp; label: string; icon: LucideIcon; tile: string }[] = [
  { match: /water ?proof/i, label: 'Waterproofing', icon: Droplets, tile: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-950 dark:text-cyan-300' },
  { match: /plaster|putty/i, label: 'Plastering', icon: Paintbrush, tile: 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300' },
  { match: /block|brick|mason/i, label: 'Masonry', icon: BrickWall, tile: 'bg-orange-100 text-orange-700 dark:bg-orange-950 dark:text-orange-300' },
  { match: /tile|tiling|granite|marble/i, label: 'Tiling', icon: Grid3x3, tile: 'bg-pink-100 text-pink-700 dark:bg-pink-950 dark:text-pink-300' },
  { match: /electric|wiring|point|conduit|cable/i, label: 'Electrical', icon: Plug, tile: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-950 dark:text-yellow-300' },
  { match: /plumb|sanitar|pipe|drain/i, label: 'Plumbing', icon: Wrench, tile: 'bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300' },
  { match: /shutter|formwork|centering/i, label: 'Shuttering', icon: Construction, tile: 'bg-lime-100 text-lime-700 dark:bg-lime-950 dark:text-lime-300' },
  { match: /paint|emulsion|primer/i, label: 'Painting', icon: PaintRoller, tile: 'bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-300' },
  { match: /steel|bar bend|rebar|reinforce/i, label: 'Steel', icon: ShieldHalf, tile: 'bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-300' },
  { match: /concrete|rcc|pcc|slab|footing/i, label: 'Concrete', icon: HardHat, tile: 'bg-stone-200 text-stone-700 dark:bg-stone-800 dark:text-stone-300' },
]
const ANY_TRADE = { label: 'Work', icon: Hammer, tile: 'bg-muted text-muted-foreground' }

/** A trade's look from the words of the work (and the team's name). */
export function tradeLook(words: string): { label: string; icon: LucideIcon; tile: string } {
  return TRADES.find((t) => t.match.test(words)) ?? ANY_TRADE
}

export function jobWords(w: WorkOrder): string {
  return [w.title, ...w.lines.map((l) => l.description), w.vendor_name].filter(Boolean).join(' ')
}

/** A job's trade: its biggest line's words (by amount, else quantity), then the title and the team's name. */
export function jobTrade(w: WorkOrder): ReturnType<typeof tradeLook> {
  const big = [...w.lines].sort((a, b) => (n(b.amount) - n(a.amount)) || (n(b.quantity) - n(a.quantity)))[0]
  for (const words of [big?.description, w.title, w.vendor_name, jobWords(w)]) {
    const look = words ? TRADES.find((t) => t.match.test(words)) : undefined
    if (look) return look
  }
  return ANY_TRADE
}

// --- Money ---------------------------------------------------------------------------------------------------------

export interface MoneySplit { value: number; done: number; billed: number; paid: number; unbilled: number; left: number }

/** Paid, billed not paid, done not billed (soon owed), left: always adding to the work's value. */
export function moneySplit(t: WorkOrder['totals']): MoneySplit {
  const value = n(t.value)
  const done = n(t.measured_value)
  const billed = n(t.billed)
  const paid = Math.min(n(t.paid), billed)
  const unbilled = Math.max(done - billed, 0)
  const left = Math.max(value - Math.max(done, billed), 0)
  return { value, done, billed, paid, unbilled, left }
}

export function addSplits(a: MoneySplit, b: MoneySplit): MoneySplit {
  return { value: a.value + b.value, done: a.done + b.done, billed: a.billed + b.billed, paid: a.paid + b.paid, unbilled: a.unbilled + b.unbilled, left: a.left + b.left }
}

export const NO_MONEY: MoneySplit = { value: 0, done: 0, billed: 0, paid: 0, unbilled: 0, left: 0 }

export const BAR_PARTS = [
  { key: 'paid', label: 'Paid', fill: 'bg-emerald-600' },
  { key: 'owed', label: 'Billed, not paid', fill: 'bg-sky-500' },
  { key: 'unbilled', label: 'Done, not billed', fill: 'bg-[repeating-linear-gradient(135deg,#f59e0b_0_4px,#fcd34d_4px_8px)]' },
  { key: 'left', label: 'Not done', fill: 'bg-muted' },
] as const

// --- Rates by work -------------------------------------------------------------------------------------------------

export interface RateRow { key: string; work: string; unit: string; offers: { vendor_id: string; vendor: string; rate: number; wo_id: string; ref: string; project: string }[] }

/** The same work across teams: lines grouped by their words (case, spaces and sizes kept) and unit; the cheapest first. */
export function ratesByWork(wos: WorkOrder[]): RateRow[] {
  const by = new Map<string, RateRow>()
  for (const w of wos) {
    if (w.status === 'cancelled') continue
    for (const l of w.lines) {
      if (!l.rate) continue
      const work = l.description.trim()
      const key = `${work.toLowerCase().replace(/\s+/g, ' ')}|${l.unit.toLowerCase()}`
      const row = by.get(key) ?? { key, work, unit: l.unit, offers: [] }
      const known = row.offers.find((o) => o.vendor_id === w.vendor_id && o.rate === n(l.rate))
      if (!known) row.offers.push({ vendor_id: w.vendor_id, vendor: w.vendor_name, rate: n(l.rate), wo_id: w.id, ref: w.ref, project: w.project_name })
      by.set(key, row)
    }
  }
  return [...by.values()]
    .map((r) => ({ ...r, offers: r.offers.sort((a, b) => a.rate - b.rate) }))
    .sort((a, b) => b.offers.length - a.offers.length || a.work.localeCompare(b.work))
}
