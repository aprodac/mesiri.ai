import * as React from 'react'
import { Link } from 'react-router-dom'
import { Check, ChevronRight, Landmark, Scale, Wallet, type LucideIcon } from 'lucide-react'
import { subKey, then } from '@/components/accounts/bs-model'
import { rupees, type BalanceSheet, type BsGroup, type Nature } from '@/lib/accounts'
import { cn } from '@/lib/utils'

// UX-33 (Mercon's balance sheet as the reference): the accountant's view. Above, the accounting equation, Assets =
// Liabilities + Capital, each term in its colour, the balance check on the "=" and two ratios an accountant reads first.
// Below, Tally's two columns, capital and liabilities beside assets, totals on one line; each group a coloured pill,
// its subgroups opening to their ledgers, each ledger to its statement. With a comparison date every figure shows its
// change.

const tiny = 0.005
const n = (v: string | number | null | undefined) => Number(v ?? 0)

const TONE: Record<'asset' | 'liability' | 'equity', { pill: string; card: string; value: string; icon: LucideIcon }> = {
  asset: { pill: 'border-sky-500/25 bg-sky-500/10 text-sky-700 dark:text-sky-400', card: 'border-sky-500/30 bg-sky-500/[0.06]', value: 'text-sky-700 dark:text-sky-400', icon: Wallet },
  liability: { pill: 'border-amber-500/25 bg-amber-500/10 text-amber-800 dark:text-amber-400', card: 'border-amber-500/30 bg-amber-500/[0.07]', value: 'text-amber-800 dark:text-amber-400', icon: Landmark },
  equity: { pill: 'border-violet-500/25 bg-violet-500/10 text-violet-700 dark:text-violet-400', card: 'border-violet-500/30 bg-violet-500/[0.06]', value: 'text-violet-700 dark:text-violet-400', icon: Scale },
}
const toneOf = (nature: Nature) => (nature === 'asset' ? TONE.asset : nature === 'equity' ? TONE.equity : TONE.liability)

function Money({ v, className }: { v: number; className?: string }) {
  return <span className={cn('tabular-nums', v < -tiny && 'text-destructive', className)}>{v < -tiny ? `(${rupees(v)})` : rupees(v)}</span>
}

/** Under a figure: its change since the comparison date (neutral grey: on a balance sheet a rise is not good or bad by itself). */
function Sub({ now, before, label }: { now: number; before: number | null; label?: string }) {
  if (before === null) return null
  const d = now - before
  if (Math.abs(d) < tiny) return <span className="block text-[11px] font-normal text-muted-foreground">no change</span>
  const pct = Math.abs(before) < tiny ? null : (d / Math.abs(before)) * 100
  return (
    <span title={label ? `${rupees(before)} on ${label}` : undefined} className="block text-[11px] font-normal tabular-nums text-muted-foreground">
      {d > 0 ? '▲' : '▼'} {rupees(Math.abs(d))}
      {pct !== null && ` · ${Math.abs(pct) >= 1000 ? '>999' : Math.abs(pct).toFixed(1)}%`}
    </span>
  )
}

// --- The equation -----------------------------------------------------------------------------------------------

export function BsEquation({ bs, prior, priorLabel, onTerm }: { bs: BalanceSheet; prior: Map<string, number> | null; priorLabel?: string; onTerm: (nature: 'asset' | 'liability' | 'equity') => void }) {
  const sum = (gs: BsGroup[], pred: (g: BsGroup) => boolean) => gs.filter(pred).reduce((t, g) => t + n(g.amount), 0)
  const sumThen = (gs: BsGroup[], pred: (g: BsGroup) => boolean) => (prior ? gs.filter(pred).reduce((t, g) => t + (then(prior, `g:${g.group_id}`) ?? 0), 0) : null)
  const assets = n(bs.total_assets)
  const liab = sum(bs.liabilities, (g) => g.nature !== 'equity')
  const equity = sum(bs.liabilities, (g) => g.nature === 'equity')
  const out = assets - liab - equity
  const balanced = Math.abs(out) < tiny
  // Ratios: current assets against current liabilities; borrowing and dues against capital
  const currentAssets = sum(bs.assets, (g) => g.code === 'current_assets')
  const currentLiab = sum(bs.liabilities, (g) => g.code === 'current_liabilities')
  const current = currentLiab > tiny ? currentAssets / currentLiab : null
  const debtEquity = equity > tiny ? liab / equity : null
  const term = (label: string, v: number, before: number | null, key: 'asset' | 'liability' | 'equity') => {
    const t = TONE[key]
    return (
      <button type="button" onClick={() => onTerm(key)} title={`Show the ${label.toLowerCase()}`} className={cn('min-w-0 flex-1 rounded-lg border px-3 py-2.5 text-left transition-colors hover:brightness-95', t.card)}>
        <p className={cn('truncate text-xs font-medium', t.value)}>{label}</p>
        <p className={cn('mt-0.5 truncate text-lg font-semibold tabular-nums sm:text-xl', t.value)}>{rupees(v)}</p>
        {before !== null && (
          <span className="flex flex-wrap items-baseline gap-x-1.5 text-[11px] text-muted-foreground">
            <span className="tabular-nums">from {rupees(before)}</span>
            <Sub now={v} before={before} label={priorLabel} />
          </span>
        )}
      </button>
    )
  }
  const ratio = (label: string, v: number | null, warn: boolean, explain: string) => (
    <div title={explain} className="rounded-lg px-3 py-1.5">
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className={cn('text-sm font-semibold tabular-nums', warn ? 'text-draft' : 'text-foreground')}>{v === null ? '—' : `${v.toFixed(2)}${label === 'Current ratio' ? 'x' : ''}`}</p>
    </div>
  )
  return (
    <div data-guide="bs.stats" className="flex flex-col gap-2 rounded-xl border bg-card p-2 shadow-xs lg:flex-row lg:items-center">
      <div className="flex min-w-0 flex-1 flex-col gap-2 sm:flex-row sm:items-stretch">
        {term('Assets', assets, then(prior, 'total_assets'), 'asset')}
        <div className="flex shrink-0 flex-row items-center justify-center gap-1.5 px-1 sm:flex-col sm:gap-0">
          <span className={cn('text-xl font-light', balanced ? 'text-muted-foreground' : 'text-destructive')}>{balanced ? '=' : '≠'}</span>
          <span className={cn('flex items-center gap-0.5 whitespace-nowrap text-[10px] font-medium', balanced ? 'text-success' : 'text-destructive')}>
            {balanced ? (
              <>
                <Check className="size-3" /> Balanced
              </>
            ) : (
              `Out by ${rupees(Math.abs(out))}`
            )}
          </span>
        </div>
        {term('Liabilities', liab, sumThen(bs.liabilities, (g) => g.nature !== 'equity'), 'liability')}
        <span aria-hidden="true" className="hidden shrink-0 self-center px-1 text-xl font-light text-muted-foreground sm:block">
          +
        </span>
        {term('Capital', equity, sumThen(bs.liabilities, (g) => g.nature === 'equity'), 'equity')}
      </div>
      <div className="flex shrink-0 items-center gap-1 border-t pt-2 lg:border-l lg:border-t-0 lg:pl-2 lg:pt-0">
        {ratio('Current ratio', current, current !== null && current < 1, 'Current assets ÷ current liabilities: what turns into cash within a year against what is due within a year. Below 1x, short-term dues are larger than short-term assets.')}
        {ratio('Debt to capital', debtEquity, debtEquity !== null && debtEquity > 2, 'Liabilities ÷ capital: how much of the business runs on what it owes against what the owners put in and kept. Above 2, it leans on borrowing and dues.')}
      </div>
    </div>
  )
}

// --- The two columns --------------------------------------------------------------------------------------------

function GroupRows({ g, prior, priorLabel, open, toggle }: { g: BsGroup; prior: Map<string, number> | null; priorLabel?: string; open: Set<string>; toggle: (id: string) => void }) {
  const t = toneOf(g.nature)
  const Icon = t.icon
  const v = n(g.amount)
  // A group whose only subgroup is itself (ledgers straight under it): the group's row opens to the ledgers
  const flat = g.subgroups.length === 1 && (g.subgroups[0].group_id === g.group_id || g.subgroups[0].name === g.name)
  const headId = `g:${g.group_id}`
  const headOpen = open.has(headId)
  const cell = 'px-3 py-2 text-[13px]'
  const num = 'whitespace-nowrap text-right align-top'
  const ledgerRows = (ls: BsGroup['subgroups'][number]['ledgers'], indent: string) =>
    ls.map((l) => (
      <tr key={l.ledger_id} className="border-b border-border/60 text-muted-foreground hover:bg-muted/40">
        <td className={cn(cell, 'py-1.5', indent)}>
          <Link to={`/accounts/ledgers/${l.ledger_id}`} className="hover:text-foreground hover:underline">
            {l.name}
          </Link>
        </td>
        <td className={cn(cell, num, 'py-1.5')}>
          <Money v={n(l.amount)} />
          <Sub now={n(l.amount)} before={then(prior, `l:${l.ledger_id}`)} label={priorLabel} />
        </td>
      </tr>
    ))
  return (
    <>
      <tr id={`bsg-${g.group_id}`} onClick={() => toggle(headId)} aria-expanded={headOpen} className="cursor-pointer hover:bg-muted/50">
        <td className={cn(cell, 'pb-1.5 pt-3.5')}>
          <span className="flex items-center gap-1.5">
            <span className={cn('inline-flex items-center gap-1.5 rounded-full border py-0.5 pl-1.5 pr-3 text-xs font-semibold', t.pill)}>
              <Icon className="size-3.5" aria-hidden="true" />
              {g.name}
            </span>
            <ChevronRight className={cn('size-3.5 shrink-0 text-muted-foreground transition-transform', headOpen && 'rotate-90')} />
          </span>
        </td>
        <td className={cn(cell, num, 'pb-1.5 pt-3.5 font-semibold')}>
          <Money v={v} />
          <Sub now={v} before={then(prior, `g:${g.group_id}`)} label={priorLabel} />
        </td>
      </tr>
      {headOpen && flat && ledgerRows(g.subgroups[0].ledgers, 'pl-8')}
      {headOpen &&
        !flat &&
        g.subgroups.map((s) => {
          const id = `s:${subKey(g, s)}`
          const isOpen = open.has(id)
          const hasLedgers = s.ledgers.length > 0 && !(s.ledgers.length === 1 && s.ledgers[0].name === s.name)
          return (
            <React.Fragment key={id}>
              <tr onClick={hasLedgers ? () => toggle(id) : undefined} aria-expanded={hasLedgers ? isOpen : undefined} className={cn('border-b border-border/60', hasLedgers && 'cursor-pointer hover:bg-muted/50')}>
                <td className={cn(cell, 'pl-6')}>
                  <span className="flex items-center gap-1.5">
                    {hasLedgers ? <ChevronRight className={cn('size-3.5 shrink-0 text-muted-foreground transition-transform', isOpen && 'rotate-90')} /> : <span className="w-3.5" />}
                    <span className={cn('text-foreground', !s.group_id && 'italic')}>{s.name}</span>
                    {hasLedgers && <span className="text-[11px] text-muted-foreground">{s.ledgers.length}</span>}
                  </span>
                </td>
                <td className={cn(cell, num)}>
                  <Money v={n(s.amount)} />
                  <Sub now={n(s.amount)} before={then(prior, `s:${subKey(g, s)}`)} label={priorLabel} />
                </td>
              </tr>
              {isOpen && ledgerRows(s.ledgers, 'pl-14')}
            </React.Fragment>
          )
        })}
    </>
  )
}

export function BsTwoColumn({ bs, prior, priorLabel, open, toggle }: { bs: BalanceSheet; prior: Map<string, number> | null; priorLabel?: string; open: Set<string>; toggle: (id: string) => void }) {
  if (!bs.assets.length && !bs.liabilities.length) {
    return (
      <p data-guide="bs.sides" className="rounded-xl border border-dashed bg-card px-4 py-6 text-sm text-muted-foreground">
        Nothing in the books on this day yet.
      </p>
    )
  }
  const sides = [
    { title: 'Capital and liabilities', groups: bs.liabilities, total: n(bs.total_liabilities), key: 'total_liabilities' },
    { title: 'Assets', groups: bs.assets, total: n(bs.total_assets), key: 'total_assets' },
  ]
  return (
    <div data-guide="bs.sides" className="grid gap-3 lg:grid-cols-2 print:grid-cols-2">
      {sides.map((side) => (
        <div key={side.title} className="flex min-w-0 flex-col overflow-hidden rounded-xl border bg-card shadow-xs">
          <div className="flex items-center justify-between gap-2 border-b bg-muted/40 px-3 py-2">
            <span className="text-[13px] font-semibold">{side.title}</span>
            <span className="text-[11px] text-muted-foreground">Amount (₹)</span>
          </div>
          <div className="flex-1 overflow-x-auto">
            <table className="w-full min-w-[300px] text-left">
              <tbody>
                {side.groups.map((g) => (
                  <GroupRows key={g.group_id} g={g} prior={prior} priorLabel={priorLabel} open={open} toggle={toggle} />
                ))}
              </tbody>
            </table>
          </div>
          <div className={cn('flex items-start justify-between gap-3 border-t-[1.5px] px-3 py-2.5', bs.balanced ? 'border-success/40' : 'border-destructive/40')}>
            <span className={cn('text-sm font-semibold', bs.balanced ? 'text-success' : 'text-destructive')}>Total</span>
            <span className={cn('text-right text-sm font-semibold', bs.balanced ? 'text-success' : 'text-destructive')}>
              <Money v={side.total} />
              <Sub now={side.total} before={then(prior, side.key)} label={priorLabel} />
            </span>
          </div>
        </div>
      ))}
    </div>
  )
}
