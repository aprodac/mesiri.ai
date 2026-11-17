import * as React from 'react'
import { Link } from 'react-router-dom'
import { Building2, ChevronRight, HandCoins, Receipt, TrendingUp, Truck, type LucideIcon } from 'lucide-react'
import { pctText } from '@/components/accounts/visuals'
import { rupees, type PlGroup, type PlTotals, type ProfitLoss } from '@/lib/accounts'
import { cn } from '@/lib/utils'

// UX-30 (asked 17 Nov 2026, Mercon's P&L as the reference): the P&L read as Tally lays it out, in two parts that
// each balance. The trading account sets income against direct costs, down to gross profit; the profit and loss
// account sets indirect costs against the gross result and other income, down to net profit. Each side is a card;
// the two totals sit on the same line. Above it, the sum as a row of figures: income − direct costs = gross profit
// − indirect costs + other income = net profit. Same data as the list view (pl-statement.tsx), nothing new from
// the backend.

/** Each kind of figure keeps one colour on the strip, its pill and its card (docs/DESIGN.md §3, category colours). */
type Kind = 'income' | 'direct' | 'indirect' | 'other' | 'result'
const LOOK: Record<Kind, { pill: string; card: string; value: string; icon: LucideIcon }> = {
  income: { pill: 'border-success/25 bg-success-soft text-success', card: 'border-success/30 bg-success-soft/45', value: 'text-success', icon: TrendingUp },
  direct: { pill: 'border-draft/25 bg-draft-soft text-draft', card: 'border-draft/30 bg-draft-soft/55', value: 'text-draft', icon: Truck },
  indirect: { pill: 'border-ai/25 bg-ai-soft text-ai', card: 'border-ai/25 bg-ai-soft/60', value: 'text-ai', icon: Building2 },
  other: { pill: 'border-info/25 bg-info-soft text-info', card: 'border-info/25 bg-info-soft/50', value: 'text-info', icon: HandCoins },
  result: { pill: '', card: 'bg-card', value: 'text-foreground', icon: Receipt },
}

const n = (v: string | number | null | undefined) => Number(v ?? 0)
const tiny = 0.005

function Money({ v, className }: { v: number; className?: string }) {
  return <span className={cn('tabular-nums', v < -tiny && 'text-destructive', className)}>{v < -tiny ? `(${rupees(v)})` : rupees(v)}</span>
}

/** Under a figure: its change against the comparison (green when good news), or its share of income. */
function Sub({ now, before, goodWhenUp, share, priorLabel }: { now: number; before: number | null; goodWhenUp: boolean; share?: number | null; priorLabel?: string }) {
  if (before !== null) {
    const d = now - before
    if (Math.abs(d) < tiny) return <span className="block text-[11px] font-normal text-muted-foreground">no change</span>
    const pct = Math.abs(before) < tiny ? null : (d / Math.abs(before)) * 100
    const good = d > 0 === goodWhenUp
    return (
      <span title={priorLabel ? `${rupees(before)} in ${priorLabel}` : undefined} className={cn('block text-[11px] font-medium tabular-nums', good ? 'text-success' : 'text-destructive')}>
        {d > 0 ? '▲' : '▼'} {rupees(Math.abs(d))}
        {pct !== null && ` · ${Math.abs(pct) >= 1000 ? '>999' : Math.abs(pct).toFixed(1)}%`}
      </span>
    )
  }
  if (share !== undefined && share !== null) return <span className="block text-[11px] font-normal text-muted-foreground">{share.toFixed(1)}% of income</span>
  return null
}

// --- The sum, as a row of figures ------------------------------------------------------------------------------

export function PlFormulaStrip({ pl, priorLabel }: { pl: ProfitLoss; priorLabel?: string }) {
  const t = pl.totals
  const p = pl.prior_totals
  const income = n(t.income)
  const share = (v: number) => (Math.abs(income) < tiny ? null : (v / income) * 100)
  const cell = (key: keyof PlTotals, label: string, kind: Kind, goodWhenUp: boolean, signed = false) => {
    const v = n(t[key])
    const before = p ? n(p[key]) : null
    const look = kind === 'result' ? (v < -tiny ? 'border-destructive/30 bg-destructive/[0.05]' : signed ? 'border-success/40 bg-success-soft/45' : 'bg-card') : LOOK[kind].card
    const value = kind === 'result' ? (v < -tiny ? 'text-destructive' : signed ? 'text-success' : 'text-foreground') : LOOK[kind].value
    return (
      <div className={cn('min-w-0 flex-1 rounded-lg border px-3 py-2.5', look)}>
        <p className={cn('truncate text-xs font-medium', kind === 'result' && !signed ? 'text-muted-foreground' : value)}>
          {kind === 'result' && v < -tiny ? label.replace('profit', 'loss') : label}
        </p>
        <p className={cn('mt-0.5 truncate text-lg font-semibold tabular-nums sm:text-xl', value)}>
          {v < -tiny && '−'}
          {rupees(v)}
        </p>
        <div className="mt-0.5 flex min-w-0 flex-wrap items-baseline gap-x-1.5 text-[11px] text-muted-foreground">
          {before !== null && <span className="tabular-nums">from {rupees(before)}</span>}
          <Sub now={v} before={before} goodWhenUp={goodWhenUp} share={key === 'income' ? null : share(v)} priorLabel={priorLabel} />
        </div>
      </div>
    )
  }
  const op = (s: string) => (
    <span aria-hidden="true" className="hidden shrink-0 self-center text-base font-medium text-muted-foreground lg:block">
      {s}
    </span>
  )
  return (
    <div data-guide="pl.stats" className="grid grid-cols-2 gap-2 rounded-xl border bg-card p-2 shadow-xs sm:grid-cols-3 lg:flex lg:items-stretch">
      {cell('income', 'Income', 'income', true)}
      {op('−')}
      {cell('direct', 'Direct costs', 'direct', false)}
      {op('=')}
      {cell('gross_profit', 'Gross profit', 'result', true)}
      {op('−')}
      {cell('indirect', 'Indirect costs', 'indirect', false)}
      {op('+')}
      {cell('other_income', 'Other income', 'other', true)}
      {op('=')}
      {cell('net_profit', 'Net profit', 'result', true, true)}
    </div>
  )
}

// --- The two-column statement ----------------------------------------------------------------------------------

type Item =
  | { type: 'section'; key: string; label: string; kind: Kind; groups: PlGroup[]; total: number; prior: number | null; cost: boolean }
  | { type: 'carried'; key: string; label: string; tag?: string; v: number; prior: number | null; good: boolean; hint: string }

interface Side {
  title: string
  items: Item[]
}
interface Part {
  key: string
  title: string
  hint: string
  left: Side
  right: Side
  total: number
  prior: number | null
}

const pos = (v: number | null) => (v === null ? null : Math.max(0, v))
const neg = (v: number | null) => (v === null ? null : Math.max(0, -v))

/** The two parts, each balancing: Tally's layout. */
function plParts(pl: ProfitLoss): Part[] {
  const t = pl.totals
  const p = pl.prior_totals
  const pr = (k: keyof PlTotals) => (p ? n(p[k]) : null)
  const gp = n(t.gross_profit)
  const np = n(t.net_profit)
  const cGp = pr('gross_profit')
  const cNp = pr('net_profit')
  const s = pl.sections
  const section = (key: keyof ProfitLoss['sections'], label: string, kind: Kind, tk: keyof PlTotals, cost: boolean): Item => ({
    type: 'section',
    key,
    label,
    kind,
    groups: s[key],
    total: n(t[tk]),
    prior: pr(tk),
    cost,
  })
  const carried = (key: string, label: string, tag: string | undefined, v: number, prior: number | null, good: boolean, hint: string): Item => ({
    type: 'carried',
    key,
    label,
    tag,
    v,
    prior,
    good,
    hint,
  })
  const keep = (xs: (Item | false)[]) => xs.filter((x): x is Item => x !== false)
  const sum = (xs: Item[]) => xs.reduce((a, x) => a + (x.type === 'section' ? x.total : x.v), 0)
  const sumPrior = (xs: Item[]) => (p ? xs.reduce((a, x) => a + (x.prior ?? 0), 0) : null)

  const tradingLeft = keep([
    section('direct', 'Direct costs', 'direct', 'direct', true),
    gp > tiny && carried('gp-cd', 'Gross profit', 'carried down', gp, pos(cGp), true, 'Gross profit c/d: moved to the profit and loss account'),
  ])
  const tradingRight = keep([
    section('income', 'Income', 'income', 'income', false),
    gp < -tiny && carried('gl-cd', 'Gross loss', 'carried down', -gp, neg(cGp), false, 'Gross loss c/d: moved to the profit and loss account'),
  ])
  const plLeft = keep([
    gp < -tiny && carried('gl-bd', 'Gross loss', 'brought down', -gp, neg(cGp), false, 'Gross loss b/d: from the trading account'),
    (s.indirect.length > 0 || n(t.indirect) !== 0) && section('indirect', 'Indirect costs', 'indirect', 'indirect', true),
    np > tiny && carried('np', 'Net profit', undefined, np, pos(cNp), true, 'The balancing figure: income less every cost'),
  ])
  const plRight = keep([
    gp > tiny && carried('gp-bd', 'Gross profit', 'brought down', gp, pos(cGp), true, 'Gross profit b/d: from the trading account'),
    (s.other_income.length > 0 || n(t.other_income) !== 0) && section('other_income', 'Other income', 'other', 'other_income', false),
    np < -tiny && carried('nl', 'Net loss', undefined, -np, neg(cNp), false, 'The balancing figure: costs over income'),
  ])
  const total = (l: Item[], r: Item[]) => Math.max(sum(l), sum(r))
  const totalPrior = (l: Item[], r: Item[]) => {
    const a = sumPrior(l)
    const b = sumPrior(r)
    return a === null || b === null ? null : Math.max(a, b)
  }
  return [
    {
      key: 'trading',
      title: 'Trading account',
      hint: 'Income against the direct cost of earning it, down to gross profit',
      left: { title: 'Costs', items: tradingLeft },
      right: { title: 'Income', items: tradingRight },
      total: total(tradingLeft, tradingRight),
      prior: totalPrior(tradingLeft, tradingRight),
    },
    {
      key: 'pl',
      title: 'Profit and loss account',
      hint: 'Indirect costs and other income against the gross result, down to net profit',
      left: { title: 'Costs', items: plLeft },
      right: { title: 'Income', items: plRight },
      total: total(plLeft, plRight),
      prior: totalPrior(plLeft, plRight),
    },
  ]
}

const cell = 'px-3 py-2 text-[13px]'
const num = 'whitespace-nowrap text-right align-top'

function SectionRows({ item, comparing, priorLabel, keep, open, toggle }: { item: Extract<Item, { type: 'section' }>; comparing: boolean; priorLabel?: string; keep: string; open: Set<string>; toggle: (id: string) => void }) {
  const look = LOOK[item.kind]
  const Icon = look.icon
  const up = !item.cost
  // One group: the section's own row opens to its ledgers (the group's row would repeat the same figure).
  const single = item.groups.length === 1
  const headId = `${item.key}/__head`
  const headOpen = single && open.has(headId)
  return (
    <>
      <tr onClick={single ? () => toggle(headId) : undefined} aria-expanded={single ? headOpen : undefined} className={cn(single && 'cursor-pointer hover:bg-muted/50')}>
        <td className={cn(cell, 'pb-1.5 pt-3.5')}>
          <span className="flex items-center gap-1.5">
            <span className={cn('inline-flex items-center gap-1.5 rounded-full border py-0.5 pl-1.5 pr-3 text-xs font-semibold', look.pill)}>
              <Icon className="size-3.5" aria-hidden="true" />
              {item.label}
            </span>
            {single && (
              <>
                <span className="text-xs text-muted-foreground">{item.groups[0].name}</span>
                <ChevronRight className={cn('size-3.5 shrink-0 text-muted-foreground transition-transform', headOpen && 'rotate-90')} />
              </>
            )}
          </span>
        </td>
        <td className={cn(cell, num, 'pb-1.5 pt-3.5 font-semibold')}>
          <Money v={item.total} />
          {comparing && <Sub now={item.total} before={item.prior} goodWhenUp={up} priorLabel={priorLabel} />}
        </td>
      </tr>
      {item.groups.length === 0 && (
        <tr className="border-b border-border/60">
          <td colSpan={2} className={cn(cell, 'pl-5 text-muted-foreground')}>
            Nothing recorded.
          </td>
        </tr>
      )}
      {(single ? [] : item.groups).map((g) => {
        const id = `${item.key}/${g.group_id ?? g.name}`
        const isOpen = open.has(id)
        const before = comparing ? n(g.prior) : null
        const still = before !== null && Math.abs(n(g.amount) - before) < tiny
        return (
          <React.Fragment key={id}>
            <tr onClick={() => toggle(id)} aria-expanded={isOpen} className={cn('cursor-pointer border-b border-border/60 hover:bg-muted/50', still && 'opacity-60')}>
              <td className={cn(cell, 'pl-4')}>
                <span className="flex items-center gap-1.5">
                  <ChevronRight className={cn('size-3.5 shrink-0 text-muted-foreground transition-transform', isOpen && 'rotate-90')} />
                  <span className="text-foreground">{g.name}</span>
                  <span className="text-[11px] text-muted-foreground">{g.ledgers.length}</span>
                </span>
              </td>
              <td className={cn(cell, num)}>
                <Money v={n(g.amount)} />
                {comparing && <Sub now={n(g.amount)} before={before} goodWhenUp={up} priorLabel={priorLabel} />}
              </td>
            </tr>
            {isOpen &&
              g.ledgers.map((l) => (
                <tr key={l.ledger_id} className="border-b border-border/60 text-muted-foreground hover:bg-muted/40">
                  <td className={cn(cell, 'py-1.5 pl-10')}>
                    <Link to={`/accounts/ledgers/${l.ledger_id}${keep}`} className="hover:text-foreground hover:underline">
                      {l.name}
                    </Link>
                    {l.is_overheads && <span className="ml-2 rounded bg-muted px-1.5 py-px text-[10px]">head-office share</span>}
                  </td>
                  <td className={cn(cell, num, 'py-1.5')}>
                    <Money v={n(l.amount)} />
                    {comparing && <Sub now={n(l.amount)} before={n(l.prior)} goodWhenUp={up} priorLabel={priorLabel} />}
                  </td>
                </tr>
              ))}
          </React.Fragment>
        )
      })}
      {headOpen &&
        item.groups[0].ledgers.map((l) => (
          <tr key={l.ledger_id} className="border-b border-border/60 text-muted-foreground hover:bg-muted/40">
            <td className={cn(cell, 'py-1.5 pl-10')}>
              <Link to={`/accounts/ledgers/${l.ledger_id}${keep}`} className="hover:text-foreground hover:underline">
                {l.name}
              </Link>
              {l.is_overheads && <span className="ml-2 rounded bg-muted px-1.5 py-px text-[10px]">head-office share</span>}
            </td>
            <td className={cn(cell, num, 'py-1.5')}>
              <Money v={n(l.amount)} />
              {comparing && <Sub now={n(l.amount)} before={n(l.prior)} goodWhenUp={up} priorLabel={priorLabel} />}
            </td>
          </tr>
        ))}
    </>
  )
}

function SideCard({ side, total, prior, comparing, periodLabel, priorLabel, keep, open, toggle }: { side: Side; total: number; prior: number | null; comparing: boolean; periodLabel: string; priorLabel?: string; keep: string; open: Set<string>; toggle: (id: string) => void }) {
  return (
    <div className="flex min-w-0 flex-col overflow-hidden rounded-xl border bg-card shadow-xs">
      <div className="flex items-center justify-between gap-2 border-b bg-muted/40 px-3 py-2">
        <span className="text-[13px] font-semibold">{side.title}</span>
        <span className="truncate text-[11px] text-muted-foreground">Amount · {periodLabel}</span>
      </div>
      <div className="flex-1 overflow-x-auto">
        <table className="w-full min-w-[300px] text-left">
          <tbody>
            {side.items.map((item) =>
              item.type === 'section' ? (
                <SectionRows key={item.key} item={item} comparing={comparing} priorLabel={priorLabel} keep={keep} open={open} toggle={toggle} />
              ) : (
                <tr key={item.key} className="border-b border-border/60" title={item.hint}>
                  <td className={cn(cell, 'py-2.5 pl-4 font-medium', item.good ? 'text-success' : 'text-destructive')}>
                    {item.label}
                    {item.tag && <span className="ml-2 rounded bg-muted px-1.5 py-px text-[10px] font-normal text-muted-foreground">{item.tag}</span>}
                  </td>
                  <td className={cn(cell, num, 'py-2.5 font-medium', item.good ? 'text-success' : 'text-destructive')}>
                    {rupees(item.v)}
                    {comparing && <Sub now={item.v} before={item.prior} goodWhenUp={item.good} priorLabel={priorLabel} />}
                  </td>
                </tr>
              ),
            )}
          </tbody>
        </table>
      </div>
      <div className="flex items-start justify-between gap-3 border-t-[1.5px] border-foreground/25 px-3 py-2.5">
        <span className="text-sm font-semibold">Total</span>
        <span className="text-right text-sm font-semibold">
          <Money v={total} />
          {comparing && prior !== null && (
            <span title={priorLabel ? `${rupees(prior)} in ${priorLabel}` : undefined} className="block text-[11px] font-normal text-muted-foreground tabular-nums">
              {Math.abs(total - prior) < tiny ? 'no change' : `${total > prior ? '▲' : '▼'} ${rupees(Math.abs(total - prior))}${Math.abs(prior) < tiny ? '' : ` · ${(Math.abs(total - prior) / Math.abs(prior) * 100).toFixed(1)}%`}`}
            </span>
          )}
        </span>
      </div>
    </div>
  )
}

export function PlTwoColumn({ pl, periodLabel, priorLabel }: { pl: ProfitLoss; periodLabel: string; priorLabel?: string }) {
  const [open, setOpen] = React.useState<Set<string>>(new Set())
  const toggle = (id: string) =>
    setOpen((s) => {
      const next = new Set(s)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  const t = pl.totals
  const comparing = !!pl.prior_totals
  const keep = typeof window !== 'undefined' && window.location.search ? window.location.search : ''
  const empty = !n(t.income) && !n(t.direct) && !n(t.indirect) && !n(t.other_income)
  if (empty) {
    return <p className="rounded-xl border border-dashed bg-card px-4 py-6 text-sm text-muted-foreground">No income or cost in the books for this period.</p>
  }
  return (
    <div className="flex flex-col gap-5">
      {plParts(pl).map((part) => (
        <section key={part.key} aria-label={part.title} className="flex flex-col gap-2">
          <div className="flex flex-wrap items-baseline gap-x-2 px-1">
            <h2 className="text-base font-semibold">{part.title}</h2>
            <p className="text-xs text-muted-foreground">{part.hint}</p>
            {part.key === 'pl' && t.net_margin !== null && (
              <span className="ml-auto text-xs text-muted-foreground">
                Net margin <span className={cn('font-medium', n(t.net_profit) < 0 ? 'text-destructive' : 'text-success')}>{pctText(t.net_margin)}</span>
              </span>
            )}
            {part.key === 'trading' && t.gross_margin !== null && (
              <span className="ml-auto text-xs text-muted-foreground">
                Gross margin <span className={cn('font-medium', n(t.gross_profit) < 0 ? 'text-destructive' : 'text-success')}>{pctText(t.gross_margin)}</span>
              </span>
            )}
          </div>
          <div className="grid gap-3 lg:grid-cols-2 print:grid-cols-2">
            {[part.left, part.right].map((side) => (
              <SideCard key={side.title} side={side} total={part.total} prior={part.prior} comparing={comparing} periodLabel={periodLabel} priorLabel={priorLabel} keep={keep} open={open} toggle={toggle} />
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}
