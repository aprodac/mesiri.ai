import * as React from 'react'
import { Link } from 'react-router-dom'
import { Building2, ChevronRight, HandCoins, Minus, Plus, TrendingDown, TrendingUp, Truck, type LucideIcon } from 'lucide-react'
import { rupees, type PlGroup, type PlTotals, type ProfitLoss } from '@/lib/accounts'
import { cn } from '@/lib/utils'

// UX-31 (asked 17 Nov 2026: "for an owner and for an accountant, different profit and loss?" -> the same numbers,
// a different first view): the owner's P&L. One card says the result in a sentence and where each ₹100 of income
// went; under it the statement reads top to bottom in plain words (money earned, site costs, office and running
// costs, other money in, profit), each line with its share of income and its change. The accounting name stays in
// small text beside the plain one. Same GET /accounts/pl as the other views.

const tiny = 0.005
const n = (v: string | number | null | undefined) => Number(v ?? 0)

type Kind = 'income' | 'direct' | 'indirect' | 'other'
const LOOK: Record<Kind, { icon: LucideIcon; tile: string; bar: string; fg: string }> = {
  income: { icon: TrendingUp, tile: 'bg-success-soft text-success', bar: 'bg-success', fg: 'text-success' },
  direct: { icon: Truck, tile: 'bg-draft-soft text-draft', bar: 'bg-draft', fg: 'text-draft' },
  indirect: { icon: Building2, tile: 'bg-ai-soft text-ai', bar: 'bg-ai', fg: 'text-ai' },
  other: { icon: HandCoins, tile: 'bg-info-soft text-info', bar: 'bg-info', fg: 'text-info' },
}

/** "▲ ₹2,45,300 · 14.9%", green when it is good news. */
function Change({ now, before, goodWhenUp, className }: { now: number; before: number | null; goodWhenUp: boolean; className?: string }) {
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

// --- The result, in a sentence ---------------------------------------------------------------------------------

export function PlOwnerHero({ pl, periodLabel, priorLabel }: { pl: ProfitLoss; periodLabel: string; priorLabel?: string }) {
  const t = pl.totals
  const p = pl.prior_totals
  const income = n(t.income)
  const other = n(t.other_income)
  const direct = n(t.direct)
  const indirect = n(t.indirect)
  const np = n(t.net_profit)
  const loss = np < -tiny
  const before = p ? n(p.net_profit) : null
  const kept = income > tiny ? Math.round((np / income) * 100) : null

  // Where the money went: site costs, office costs and profit share the money that came in (income + other). In a
  // loss the costs are more than came in; the bar then shows the costs, and the loss is the part past the line.
  const cameIn = income + other
  const base = Math.max(cameIn, direct + indirect, 1)
  const parts = [
    { key: 'direct', label: 'Site costs', v: direct, cls: LOOK.direct.bar },
    { key: 'indirect', label: 'Office and running costs', v: indirect, cls: LOOK.indirect.bar },
    { key: 'profit', label: 'Profit', v: Math.max(0, np), cls: 'bg-success' },
  ].filter((x) => x.v > tiny)
  const per100 = (v: number) => (income > tiny ? Math.round((v / income) * 100) : null)
  const Icon = loss ? TrendingDown : TrendingUp

  return (
    <div data-guide="pl.stats" className={cn('grid gap-5 rounded-xl border bg-card p-4 shadow-xs sm:p-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]', loss ? 'border-destructive/30' : 'border-success/30')}>
      <div className="flex min-w-0 flex-col gap-1.5">
        <span className={cn('inline-flex w-fit items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold', loss ? 'bg-destructive/10 text-destructive' : 'bg-success-soft text-success')}>
          <Icon className="size-3.5" aria-hidden="true" />
          {loss ? 'Loss' : 'Profit'} · {periodLabel}
        </span>
        <p className={cn('text-3xl font-semibold tabular-nums tracking-tight sm:text-4xl', loss ? 'text-destructive' : 'text-success')}>
          {loss && '−'}
          {rupees(np)}
        </p>
        <p className="text-sm text-muted-foreground">
          {loss ? 'Costs were more than the money earned.' : kept !== null ? (
            <>
              Out of every <span className="font-medium text-foreground">₹100</span> earned, you kept <span className="font-semibold text-success">₹{kept}</span>.
            </>
          ) : (
            'No income in this period.'
          )}
        </p>
        {before !== null && (
          <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            <Change now={np} before={before} goodWhenUp />
            <span>
              against {before < -tiny ? 'a loss of ' : ''}
              {rupees(before)} in {priorLabel ?? 'the period before'}
            </span>
          </p>
        )}
      </div>

      <div className="flex min-w-0 flex-col justify-center gap-2.5">
        <p className="text-xs font-medium text-muted-foreground">Where each ₹100 earned went</p>
        <div className="flex h-3.5 w-full gap-0.5 overflow-hidden rounded-full bg-muted">
          {parts.map((x) => (
            <span key={x.key} title={`${x.label}: ${rupees(x.v)}`} className={cn('h-full first:rounded-l-full last:rounded-r-full', x.cls)} style={{ width: `${(x.v / base) * 100}%` }} />
          ))}
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {[
            { label: 'Site costs', v: direct, dot: LOOK.direct.bar },
            { label: 'Office and running costs', v: indirect, dot: LOOK.indirect.bar },
            { label: loss ? 'Loss' : 'Profit', v: np, dot: loss ? 'bg-destructive' : 'bg-success' },
          ].map((x) => {
            const share = per100(Math.abs(x.v))
            return (
              <div key={x.label} className="flex min-w-0 items-baseline gap-2 sm:flex-col sm:gap-0.5">
                <span className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
                  <span className={cn('size-2 shrink-0 rounded-full', x.dot)} />
                  <span className="truncate">{x.label}</span>
                </span>
                <span className="ml-auto text-sm font-semibold tabular-nums sm:ml-0">
                  {share !== null ? `₹${share}` : '—'}
                  <span className="ml-1 text-xs font-normal text-muted-foreground">{rupees(x.v)}</span>
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// --- The statement, top to bottom ------------------------------------------------------------------------------

function Ledgers({ group, comparing, goodWhenUp, keep, indent }: { group: PlGroup; comparing: boolean; goodWhenUp: boolean; keep: string; indent: string }) {
  return (
    <>
      {group.ledgers.map((l) => (
        <div key={l.ledger_id} className={cn('flex items-center gap-3 border-t border-border/50 py-2 pr-4 text-sm text-muted-foreground', indent)}>
          <Link to={`/accounts/ledgers/${l.ledger_id}${keep}`} className="min-w-0 flex-1 truncate hover:text-foreground hover:underline">
            {l.name}
            {l.is_overheads && <span className="ml-2 rounded bg-muted px-1.5 py-px text-[10px]">head-office share</span>}
          </Link>
          {comparing && <Change now={n(l.amount)} before={n(l.prior)} goodWhenUp={goodWhenUp} className="hidden sm:inline-flex" />}
          <span className="w-32 shrink-0 text-right tabular-nums">{rupees(n(l.amount))}</span>
        </div>
      ))}
    </>
  )
}

function SectionBlock({
  kind,
  sign,
  label,
  formal,
  hint,
  groups,
  v,
  before,
  income,
  goodWhenUp,
  keep,
}: {
  kind: Kind
  sign: '+' | '−'
  label: string
  formal: string
  hint: string
  groups: PlGroup[]
  v: number
  before: number | null
  income: number
  goodWhenUp: boolean
  keep: string
}) {
  const [open, setOpen] = React.useState<Set<string>>(new Set())
  const look = LOOK[kind]
  const Icon = look.icon
  const share = income > tiny ? (v / income) * 100 : null
  const single = groups.length === 1
  const headOpen = single && open.has('__head')
  const toggle = (id: string) =>
    setOpen((s) => {
      const next = new Set(s)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  const SignIcon = sign === '+' ? Plus : Minus
  return (
    <div className="border-t first:border-t-0">
      <button
        type="button"
        onClick={() => single && toggle('__head')}
        aria-expanded={single ? headOpen : undefined}
        className={cn('flex w-full items-center gap-3 px-4 py-3 text-left', single && 'hover:bg-muted/40')}
      >
        {kind === 'income' ? <span className="w-3.5 shrink-0" /> : <SignIcon className="size-3.5 shrink-0 text-muted-foreground" aria-label={sign === '+' ? 'plus' : 'less'} />}
        <span className={cn('flex size-8 shrink-0 items-center justify-center rounded-lg', look.tile)}>
          <Icon className="size-4" aria-hidden="true" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-semibold">{label}</span>
            <span className="text-[11px] text-muted-foreground">{formal}</span>
            {single && <ChevronRight className={cn('size-3.5 self-center text-muted-foreground transition-transform', headOpen && 'rotate-90')} />}
          </span>
          <span className="block text-xs text-muted-foreground">{hint}</span>
          {share !== null && kind !== 'income' && (
            <span className="mt-1.5 flex items-center gap-2">
              <span className="h-1.5 w-full max-w-48 overflow-hidden rounded-full bg-muted">
                <span className={cn('block h-full rounded-full', look.bar)} style={{ width: `${Math.min(100, Math.abs(share))}%` }} />
              </span>
              <span className="shrink-0 text-[11px] text-muted-foreground tabular-nums">₹{Math.round(share)} of every ₹100</span>
            </span>
          )}
        </span>
        <span className="flex shrink-0 flex-col items-end gap-1">
          <span className={cn('text-base font-semibold tabular-nums', look.fg)}>{rupees(v)}</span>
          <Change now={v} before={before} goodWhenUp={goodWhenUp} />
        </span>
      </button>
      {single && headOpen && <Ledgers group={groups[0]} comparing={before !== null} goodWhenUp={goodWhenUp} keep={keep} indent="pl-[4.75rem]" />}
      {!single &&
        groups.map((g) => {
          const id = g.group_id ?? g.name
          const isOpen = open.has(id)
          return (
            <React.Fragment key={id}>
              <button type="button" onClick={() => toggle(id)} aria-expanded={isOpen} className="flex w-full items-center gap-3 border-t border-border/50 py-2 pl-[4.75rem] pr-4 text-left text-sm hover:bg-muted/40">
                <ChevronRight className={cn('-ml-5 size-3.5 shrink-0 text-muted-foreground transition-transform', isOpen && 'rotate-90')} />
                <span className="min-w-0 flex-1 truncate">{g.name}</span>
                {before !== null && <Change now={n(g.amount)} before={n(g.prior)} goodWhenUp={goodWhenUp} className="hidden sm:inline-flex" />}
                <span className="w-32 shrink-0 text-right font-medium tabular-nums">{rupees(n(g.amount))}</span>
              </button>
              {isOpen && <Ledgers group={g} comparing={before !== null} goodWhenUp={goodWhenUp} keep={keep} indent="pl-[6rem]" />}
            </React.Fragment>
          )
        })}
    </div>
  )
}

function ResultLine({ label, formal, v, before, income, strong }: { label: string; formal: string; v: number; before: number | null; income: number; strong?: boolean }) {
  const loss = v < -tiny
  const share = income > tiny ? Math.round((v / income) * 100) : null
  return (
    <div className={cn('flex items-center gap-3 border-t px-4', strong ? 'border-t-2 py-4' : 'bg-muted/50 py-3', strong && (loss ? 'border-t-destructive/40 bg-destructive/[0.05]' : 'border-t-success/40 bg-success-soft/50'))}>
      <span className="w-3.5 shrink-0 text-center font-semibold text-muted-foreground">=</span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-baseline gap-x-2">
          <span className={cn('font-semibold', strong && 'text-base')}>{loss ? label.replace('profit', 'loss').replace('Profit', 'Loss') : label}</span>
          <span className="text-[11px] text-muted-foreground">{loss ? formal.replace('profit', 'loss') : formal}</span>
        </span>
        {share !== null && <span className="block text-xs text-muted-foreground">{share < 0 ? `Lost ₹${-share} on every ₹100 earned` : `₹${share} of every ₹100 earned`}</span>}
      </span>
      <span className="flex shrink-0 flex-col items-end gap-1">
        <span className={cn('font-semibold tabular-nums', strong ? 'text-xl' : 'text-base', loss ? 'text-destructive' : strong && 'text-success')}>
          {loss && '−'}
          {rupees(v)}
        </span>
        <Change now={v} before={before} goodWhenUp />
      </span>
    </div>
  )
}

export function PlSimple({ pl }: { pl: ProfitLoss }) {
  const t = pl.totals
  const p = pl.prior_totals
  const pr = (k: keyof PlTotals) => (p ? n(p[k]) : null)
  const income = n(t.income)
  const keep = typeof window !== 'undefined' && window.location.search ? window.location.search : ''
  const empty = !income && !n(t.direct) && !n(t.indirect) && !n(t.other_income)
  if (empty) {
    return <p className="rounded-xl border border-dashed bg-card px-4 py-6 text-sm text-muted-foreground">No income or cost in the books for this period.</p>
  }
  const s = pl.sections
  const showOther = s.other_income.length > 0 || Math.abs(n(t.other_income)) > tiny
  const showIndirect = s.indirect.length > 0 || Math.abs(n(t.indirect)) > tiny
  return (
    <div className="overflow-hidden rounded-xl border bg-card shadow-xs">
      <div className="flex items-center justify-between gap-2 border-b bg-muted/40 px-4 py-2.5">
        <span className="text-sm font-semibold">How you got there</span>
        <span className="text-[11px] text-muted-foreground">Tap a line for what is in it</span>
      </div>
      <SectionBlock kind="income" sign="+" label="Money earned" formal="Income" hint="RA bills sent, before GST" groups={s.income} v={income} before={pr('income')} income={income} goodWhenUp keep={keep} />
      <SectionBlock kind="direct" sign="−" label="Site costs" formal="Direct costs" hint="Bills and expenses on the projects, after the GST you claim back" groups={s.direct} v={n(t.direct)} before={pr('direct')} income={income} goodWhenUp={false} keep={keep} />
      <ResultLine label="Left after site costs" formal="Gross profit" v={n(t.gross_profit)} before={pr('gross_profit')} income={income} />
      {showIndirect && (
        <SectionBlock kind="indirect" sign="−" label="Office and running costs" formal="Indirect costs" hint="Costs of running the company, not of one job" groups={s.indirect} v={n(t.indirect)} before={pr('indirect')} income={income} goodWhenUp={false} keep={keep} />
      )}
      {showOther && (
        <SectionBlock kind="other" sign="+" label="Other money in" formal="Other income" hint="Money that did not come from project bills" groups={s.other_income} v={n(t.other_income)} before={pr('other_income')} income={income} goodWhenUp keep={keep} />
      )}
      <ResultLine label="Profit" formal="Net profit" v={n(t.net_profit)} before={pr('net_profit')} income={income} strong />
    </div>
  )
}
