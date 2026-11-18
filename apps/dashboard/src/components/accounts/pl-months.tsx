import * as React from 'react'
import { Link } from 'react-router-dom'
import { useQueries } from '@tanstack/react-query'
import { ChevronRight } from 'lucide-react'
import { SplitBars } from '@/components/accounts/visuals'
import { Skeleton } from '@/components/ui/skeleton'
import { fetchPl, rupees, type Period, type PlGroup, type PlTotals, type ProfitLoss, type Scope } from '@/lib/accounts'
import { cn } from '@/lib/utils'

// UX-39 (asked 17 Nov 2026, Mercon's "Month by month" as the reference): the period's P&L one column per month, with
// a Total column, and the net result by month as bars above it. Each month is the same GET /accounts/pl the
// statement uses, asked for that month (no new API); the Total column is the whole period's answer, so it always
// matches the statement.

const MAX_MONTHS = 12
const tiny = 0.005
const n = (v: string | number | null | undefined) => Number(v ?? 0)
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

/** The calendar months a period covers, each clipped to the period. */
function monthsOf(p: Period): Period[] {
  const out: Period[] = []
  const end = new Date(`${p.date_to}T00:00:00`)
  let cur = new Date(`${p.date_from}T00:00:00`)
  while (cur <= end && out.length <= MAX_MONTHS) {
    const last = new Date(cur.getFullYear(), cur.getMonth() + 1, 0)
    out.push({ date_from: iso(cur), date_to: iso(last < end ? last : end) })
    cur = new Date(cur.getFullYear(), cur.getMonth() + 1, 1)
  }
  return out
}

const monthLabel = (p: Period) => new Date(`${p.date_from}T00:00:00`).toLocaleDateString('en-IN', { month: 'short', year: 'numeric' })

type SectionKey = keyof ProfitLoss['sections']
const SECTIONS: { key: SectionKey; label: string; total: keyof PlTotals; band: string; fg: string }[] = [
  { key: 'income', label: 'Income', total: 'income', band: 'bg-success-soft', fg: 'text-success' },
  { key: 'direct', label: 'Direct costs', total: 'direct', band: 'bg-draft-soft', fg: 'text-draft' },
  { key: 'indirect', label: 'Indirect costs', total: 'indirect', band: 'bg-ai-soft', fg: 'text-ai' },
  { key: 'other_income', label: 'Other income', total: 'other_income', band: 'bg-info-soft', fg: 'text-info' },
]

const groupId = (g: PlGroup) => g.group_id ?? g.name

function Amount({ v, className }: { v: number; className?: string }) {
  if (Math.abs(v) < tiny) return <span className={cn('text-muted-foreground/60', className)}>—</span>
  return <span className={cn('tabular-nums', v < 0 && 'text-destructive', className)}>{v < 0 ? `(${rupees(v)})` : rupees(v)}</span>
}

export function PlMonths({ period, scope, total }: { period: Period; scope: Scope; total: ProfitLoss }) {
  const months = monthsOf(period)
  const tooMany = months.length > MAX_MONTHS
  const qs = useQueries({
    queries: (tooMany ? [] : months).map((m) => ({
      queryKey: ['accounts', 'pl', m, scope, ''],
      queryFn: () => fetchPl(m, scope, ''),
    })),
  })
  const [open, setOpen] = React.useState<Set<string>>(new Set())
  const toggle = (id: string) =>
    setOpen((s) => {
      const next = new Set(s)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  const keep = typeof window !== 'undefined' && window.location.search ? window.location.search : ''

  if (tooMany) {
    return <p className="rounded-xl border border-dashed bg-card px-4 py-6 text-sm text-muted-foreground">Month by month shows up to {MAX_MONTHS} months. Pick a shorter period, or use Statement.</p>
  }
  if (qs.some((q) => q.isError)) {
    return <p className="rounded-xl border border-dashed bg-card px-4 py-6 text-sm text-muted-foreground">Some months could not be loaded. Try again in a moment, or use Statement.</p>
  }
  const data = qs.map((q) => q.data)
  if (data.some((d) => !d)) return <Skeleton className="h-96 rounded-xl" />
  const cols = data as ProfitLoss[]

  // Find a group (and a ledger) in one month by its id; a month without it shows a dash.
  const groupIn = (pl: ProfitLoss, key: SectionKey, id: string) => pl.sections[key].find((g) => groupId(g) === id)
  const ledgerIn = (pl: ProfitLoss, key: SectionKey, gid: string, lid: string) => groupIn(pl, key, gid)?.ledgers.find((l) => l.ledger_id === lid)

  const col = 'px-3 py-2 text-right whitespace-nowrap'
  const totalCol = 'border-l font-semibold'
  const resultRow = (label: string, key: keyof PlTotals, strong?: boolean) => {
    const v = n(total.totals[key])
    return (
      <tr className={cn('border-b', strong ? 'border-t-2 border-t-success/40 bg-success-soft text-[15px]' : 'bg-muted')}>
        <td className={cn('sticky left-0 z-[1] px-3 py-2.5 font-semibold', strong ? 'bg-success-soft text-success' : 'bg-muted')}>{v < 0 ? label.replace('profit', 'loss') : label}</td>
        {cols.map((c, i) => (
          <td key={i} className={cn(col, 'py-2.5 font-semibold')}>
            <Amount v={n(c.totals[key])} />
          </td>
        ))}
        <td className={cn(col, totalCol, 'py-2.5', strong && (v < 0 ? 'text-destructive' : 'text-success'))}>
          <Amount v={v} />
        </td>
      </tr>
    )
  }

  const bars = cols.map((c, i) => {
    const np = n(c.totals.net_profit)
    return {
      key: months[i].date_from,
      label: monthLabel(months[i]),
      up: Math.max(0, np),
      down: Math.max(0, -np),
      detail: `${monthLabel(months[i])}: ${np < 0 ? 'loss' : 'profit'} ${rupees(np)}`,
    }
  })

  return (
    <div className="overflow-hidden rounded-xl border bg-card shadow-xs">
      <div className="border-b px-4 pb-3 pt-3.5">
        <p className="mb-1 text-[13px] font-semibold">Net result by month</p>
        <SplitBars items={bars} height={150} up="Profit" down="Loss" />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-[13px]">
          <thead>
            <tr className="border-b bg-muted text-xs text-muted-foreground">
              <th className="sticky left-0 z-[1] bg-muted px-3 py-2 text-left font-medium">Account</th>
              {months.map((m) => (
                <th key={m.date_from} className={cn(col, 'font-medium')}>
                  {monthLabel(m)}
                </th>
              ))}
              <th className={cn(col, 'border-l font-semibold text-foreground')}>Total</th>
            </tr>
          </thead>
          <tbody>
            {SECTIONS.map((s, si) => {
              const groups = total.sections[s.key]
              // One group: the band opens to its ledgers (the group's row would repeat the band's figures).
              const single = groups.length === 1
              const headId = `${s.key}/${single ? groupId(groups[0]) : ''}`
              const headOpen = single && open.has(headId)
              if (!groups.length && !n(total.totals[s.total])) return si === 1 ? <React.Fragment key={s.key}>{resultRow('Gross profit', 'gross_profit')}</React.Fragment> : null
              return (
                <React.Fragment key={s.key}>
                  <tr className={cn('border-b', s.band, single && 'cursor-pointer')} onClick={single ? () => toggle(headId) : undefined} aria-expanded={single ? headOpen : undefined}>
                    <td className={cn('sticky left-0 z-[1] px-3 py-2 font-semibold', s.fg, s.band)}>
                      <span className="flex items-center gap-1.5">
                        {single && <ChevronRight className={cn('size-3.5 shrink-0 transition-transform', headOpen && 'rotate-90')} />}
                        {s.label}
                        {single && <span className="text-xs font-normal text-muted-foreground">{groups[0].name}</span>}
                      </span>
                    </td>
                    {cols.map((c, i) => (
                      <td key={i} className={cn(col, 'font-semibold', s.fg)}>
                        <Amount v={n(c.totals[s.total])} />
                      </td>
                    ))}
                    <td className={cn(col, 'border-l font-semibold', s.fg)}>
                      <Amount v={n(total.totals[s.total])} />
                    </td>
                  </tr>
                  {groups.map((g) => {
                    const id = `${s.key}/${groupId(g)}`
                    const isOpen = open.has(id)
                    return (
                      <React.Fragment key={id}>
                        {!single && <tr onClick={() => toggle(id)} aria-expanded={isOpen} className="cursor-pointer border-b border-border/60 hover:bg-muted/40">
                          <td className="sticky left-0 z-[1] bg-card px-3 py-2">
                            <span className="flex items-center gap-1.5">
                              <ChevronRight className={cn('size-3.5 shrink-0 text-muted-foreground transition-transform', isOpen && 'rotate-90')} />
                              {g.name}
                            </span>
                          </td>
                          {cols.map((c, i) => (
                            <td key={i} className={col}>
                              <Amount v={n(groupIn(c, s.key, groupId(g))?.amount)} />
                            </td>
                          ))}
                          <td className={cn(col, totalCol)}>
                            <Amount v={n(g.amount)} />
                          </td>
                        </tr>}
                        {isOpen &&
                          g.ledgers.map((l) => (
                            <tr key={l.ledger_id} className="border-b border-border/60 text-muted-foreground">
                              <td className="sticky left-0 z-[1] bg-card py-1.5 pl-9 pr-3">
                                <Link to={`/accounts/ledgers/${l.ledger_id}${keep}`} className="hover:text-foreground hover:underline">
                                  {l.name}
                                </Link>
                              </td>
                              {cols.map((c, i) => (
                                <td key={i} className={cn(col, 'py-1.5')}>
                                  <Amount v={n(ledgerIn(c, s.key, groupId(g), l.ledger_id)?.amount)} />
                                </td>
                              ))}
                              <td className={cn(col, 'border-l py-1.5')}>
                                <Amount v={n(l.amount)} />
                              </td>
                            </tr>
                          ))}
                      </React.Fragment>
                    )
                  })}
                  {si === 1 && resultRow('Gross profit', 'gross_profit')}
                </React.Fragment>
              )
            })}
            {resultRow('Net profit', 'net_profit', true)}
          </tbody>
        </table>
      </div>
    </div>
  )
}
