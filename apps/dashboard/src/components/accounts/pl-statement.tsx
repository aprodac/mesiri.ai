import * as React from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import { Delta, pctText } from '@/components/accounts/visuals'
import { change, rupees, type PlGroup, type ProfitLoss } from '@/lib/accounts'
import { cn } from '@/lib/utils'

// ACC-06: the P&L in Tally's layout, shared by the company's P&L and a project's books. Income and direct costs give
// the gross profit; other income and indirect costs, the net profit. Each group opens to its ledgers, each ledger to
// its statement; with a comparison, each figure shows its change.

function Money({ v, className }: { v: string | number; className?: string }) {
  const n = Number(v)
  return <span className={cn('tabular-nums', n < 0 && 'text-destructive', className)}>{n < 0 ? `(${rupees(n)})` : rupees(n)}</span>
}

function Section({ title, groups, compare, cost, keep }: { title: string; groups: PlGroup[]; compare: boolean; cost: boolean; keep: string }) {
  const [open, setOpen] = React.useState<Set<string>>(new Set())
  if (!groups.length) return null
  return (
    <>
      <tr>
        <td colSpan={compare ? 3 : 2} className="px-3 pt-3 pb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {title}
        </td>
      </tr>
      {groups.map((g) => {
        const id = g.group_id ?? g.name
        const isOpen = open.has(id)
        return (
          <React.Fragment key={id}>
            <tr
              className="cursor-pointer hover:bg-muted/40"
              onClick={() =>
                setOpen((s) => {
                  const n = new Set(s)
                  if (n.has(id)) n.delete(id)
                  else n.add(id)
                  return n
                })
              }
            >
              <td className="px-3 py-2">
                <span className="inline-flex items-center gap-1 font-medium">
                  <ChevronRight className={cn('size-3.5 text-muted-foreground transition-transform', isOpen && 'rotate-90')} /> {g.name}
                </span>
              </td>
              {compare && (
                <td className="hidden px-3 py-2 text-right text-muted-foreground sm:table-cell">
                  <Money v={g.prior ?? 0} />
                </td>
              )}
              <td className="px-3 py-2 text-right">
                <span className="inline-flex items-center gap-2">
                  {compare && <Delta pct={change(g.amount, g.prior)} goodWhenUp={!cost} />}
                  <Money v={g.amount} className="font-medium" />
                </span>
              </td>
            </tr>
            {isOpen &&
              g.ledgers.map((l) => (
                <tr key={l.ledger_id} className="text-muted-foreground">
                  <td className="py-1.5 pl-9 pr-3">
                    <Link to={`/accounts/ledgers/${l.ledger_id}${keep}`} className="hover:text-foreground hover:underline">
                      {l.name}
                    </Link>
                    {l.is_overheads && <span className="ml-2 rounded bg-muted px-1.5 text-[11px]">head-office share</span>}
                  </td>
                  {compare && (
                    <td className="hidden px-3 py-1.5 text-right sm:table-cell">
                      <Money v={l.prior ?? 0} />
                    </td>
                  )}
                  <td className="px-3 py-1.5 text-right">
                    <Money v={l.amount} />
                  </td>
                </tr>
              ))}
          </React.Fragment>
        )
      })}
    </>
  )
}

function ResultRow({ label, v, prior, margin, compare, strong }: { label: string; v: string; prior?: string | null; margin: string | null; compare: boolean; strong?: boolean }) {
  const n = Number(v)
  return (
    <tr className={cn('border-y', strong ? 'bg-muted/50 text-base' : 'bg-muted/25')}>
      <td className="px-3 py-2.5 font-semibold">
        {n < 0 ? label.replace('profit', 'loss') : label}
        {margin !== null && <span className="ml-2 text-xs font-normal text-muted-foreground">{pctText(margin)} of income</span>}
      </td>
      {compare && (
        <td className="hidden px-3 py-2.5 text-right font-medium text-muted-foreground sm:table-cell">
          <Money v={prior ?? 0} />
        </td>
      )}
      <td className="px-3 py-2.5 text-right">
        <span className="inline-flex items-center gap-2">
          {compare && <Delta pct={change(v, prior)} />}
          <Money v={v} className={cn('font-semibold', n > 0 && 'text-success')} />
        </span>
      </td>
    </tr>
  )
}

export function PlStatement({ pl, periodLabel, priorLabel }: { pl: ProfitLoss; periodLabel: string; priorLabel?: string }) {
  const compare = !!pl.prior_totals
  const t = pl.totals
  const p = pl.prior_totals
  const keep = typeof window !== 'undefined' && window.location.search ? window.location.search : ''
  const empty = !Number(t.income) && !Number(t.direct) && !Number(t.indirect) && !Number(t.other_income)
  if (empty) {
    return <p className="rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground">No income or cost in the books for this period.</p>
  }
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b bg-muted/40 text-xs text-muted-foreground">
            <th className="px-3 py-2 text-left font-medium">Particulars</th>
            {compare && <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">{priorLabel}</th>}
            <th className="px-3 py-2 text-right font-medium">{periodLabel}</th>
          </tr>
        </thead>
        <tbody>
          <Section title="Income" groups={pl.sections.income} compare={compare} cost={false} keep={keep} />
          <Section title="Direct costs" groups={pl.sections.direct} compare={compare} cost keep={keep} />
          <ResultRow label="Gross profit" v={t.gross_profit} prior={p?.gross_profit} margin={t.gross_margin} compare={compare} />
          <Section title="Other income" groups={pl.sections.other_income} compare={compare} cost={false} keep={keep} />
          <Section title="Indirect costs" groups={pl.sections.indirect} compare={compare} cost keep={keep} />
          <ResultRow label="Net profit" v={t.net_profit} prior={p?.net_profit} margin={t.net_margin} compare={compare} strong />
        </tbody>
      </table>
    </div>
  )
}
