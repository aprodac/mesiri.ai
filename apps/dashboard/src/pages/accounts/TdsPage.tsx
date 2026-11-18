import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { CalendarClock, CircleAlert, HandCoins, Scissors, UserX } from 'lucide-react'
import { BooksClosed, ExcelButton, PeriodBar, usePeriod } from '@/components/accounts/books'
import { FlowStrip, PartyAvatar } from '@/components/accounts/money-kit'
import { Callout, DprHeader, DprSection, PageError } from '@/components/dpr-page'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { fetchTds, formatDay, mayReadBooks, rupees } from '@/lib/accounts'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'

// ACC-11: TDS. What the company deducted from subcontractors' bills (194C) and holds for the government, deposited
// or still due by the 7th; and what clients deducted from our RA bills (to match with 26AS and claim). Backend:
// GET /accounts/tds.
// UXA-07: the period as a sum (deducted − deposited = to deposit, the next due date, anything late in red); months,
// subcontractors and clients as tables on white with their totals; a month's status as a coloured pill and how much
// of it is deposited as a bar.

const TABLE = 'overflow-x-auto rounded-xl border bg-card shadow-xs'
const HEAD = 'border-b bg-muted text-xs text-muted-foreground'
const FOOT = 'border-t-[1.5px] border-foreground/25 bg-muted/30 font-semibold'

const STATUS = {
  deposited: { word: 'Deposited', cls: 'bg-success-soft text-success' },
  due: { word: 'Due', cls: 'bg-info-soft text-info' },
  overdue: { word: 'Late', cls: 'bg-destructive/10 text-destructive' },
} as const

export default function TdsPage() {
  usePageTitle('TDS')
  const { me } = useAuth()
  const periodState = usePeriod('fy')
  const { period } = periodState
  const allowed = mayReadBooks(me?.role)
  const q = useQuery({ queryKey: ['accounts', 'tds', period], queryFn: () => fetchTds(period), enabled: allowed })
  if (!allowed) return <BooksClosed />
  if (q.isError) return <PageError message="TDS could not be loaded." onRetry={() => q.refetch()} back={{ to: '/accounts', label: 'Accounts' }} />
  const d = q.data
  const deducted = d ? d.deducted.reduce((s, x) => s + Number(x.amount), 0) : 0
  const deposited = d ? d.deposits.reduce((s, x) => s + Number(x.amount), 0) : 0
  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader
        back={{ to: '/accounts', label: 'Accounts' }}
        crumb="Accounts"
        title="TDS"
        date="194C"
        action={d && <ExcelButton path="/accounts/tds/export" params={period} name={`tds-${period.date_from}-to-${period.date_to}`} />}
      />
      <PeriodBar state={periodState} />
      {!d ? (
        <Skeleton className="h-96 rounded-xl" />
      ) : (
        <>
          <FlowStrip
            guide="tds.stats"
            items={[
              { label: 'Deducted from subcontractors', value: rupees(deducted), tone: 'dr', sub: `${d.deducted.length} bills · 194C` },
              { label: 'Deposited', value: rupees(deposited), tone: 'in', op: '−', sub: `${d.deposits.length} ${d.deposits.length === 1 ? 'challan' : 'challans'}` },
              { label: 'To deposit', value: rupees(d.to_deposit), tone: Number(d.overdue) > 0 ? 'out' : 'balance', op: '=', sub: Number(d.overdue) > 0 ? <span className="font-medium text-destructive">{rupees(d.overdue)} late: interest runs</span> : d.next_due ? `next due ${formatDay(d.next_due)}` : 'nothing due' },
              { label: 'Deducted by clients', value: rupees(d.by_clients_total), tone: 'cr', sub: 'claim it against your tax (26AS)' },
            ]}
          />
          {Number(d.overdue) > 0 && (
            <Callout tone="draft" icon={CircleAlert}>
              <span className="font-medium">{rupees(d.overdue)} of TDS is past its due date.</span> Deposit it from Finance › Money.
            </Callout>
          )}
          {d.missing_pan.length > 0 && (
            <Callout tone="draft" icon={UserX} action={<Link to="/finance/vendors" className="text-sm underline">Suppliers</Link>}>
              No PAN (GSTIN) for {d.missing_pan.join(', ')}
            </Callout>
          )}
          <DprSection icon={CalendarClock} title="Month by month" meta={d.months.length || undefined}>
            {d.months.length === 0 ? (
              <p className="rounded-xl border border-dashed bg-card px-4 py-6 text-sm text-muted-foreground">No TDS deducted in this period</p>
            ) : (
              <div data-guide="tds.months" className={TABLE}>
                <table className="w-full min-w-[640px] text-sm">
                  <thead>
                    <tr className={HEAD}>
                      <th className="px-3 py-2 text-left font-medium">Month</th>
                      <th className="px-3 py-2 text-left font-medium">Status</th>
                      <th className="px-3 py-2 text-right font-medium">Deducted</th>
                      <th className="px-3 py-2 text-left font-medium">Deposited</th>
                      <th className="px-3 py-2 text-left font-medium">Due by</th>
                      <th className="px-3 py-2 text-right font-medium">To deposit</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {d.months.map((m) => {
                      const share = Number(m.deducted) > 0 ? Math.min(1, Number(m.deposited) / Number(m.deducted)) : 1
                      return (
                        <tr key={m.month} className={cn(m.status === 'overdue' && 'bg-destructive/5')}>
                          <td className={cn('px-3 py-2.5 font-medium', m.status === 'overdue' && 'border-l-4 border-l-destructive')}>
                            {new Date(`${m.month}-01T00:00:00`).toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })}
                          </td>
                          <td className="px-3 py-2.5">
                            <span className={cn('rounded-full px-2 py-0.5 text-xs font-medium', STATUS[m.status].cls)}>{STATUS[m.status].word}</span>
                          </td>
                          <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums text-draft">{rupees(m.deducted)}</td>
                          <td className="px-3 py-2.5">
                            <span className="flex items-center gap-2">
                              <span className="h-1.5 w-16 overflow-hidden rounded-full bg-muted">
                                <span className="block h-full rounded-full bg-emerald-500" style={{ width: `${share * 100}%` }} />
                              </span>
                              <span className="whitespace-nowrap tabular-nums text-emerald-700 dark:text-emerald-400">{rupees(m.deposited)}</span>
                            </span>
                          </td>
                          <td className="whitespace-nowrap px-3 py-2.5 tabular-nums text-muted-foreground">{formatDay(m.due)}</td>
                          <td className={cn('whitespace-nowrap px-3 py-2.5 text-right font-semibold tabular-nums', !Number(m.left) ? 'text-muted-foreground' : m.status === 'overdue' ? 'text-destructive' : '')}>{Number(m.left) ? rupees(m.left) : 'Nil'}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                  <tfoot>
                    <tr className={FOOT}>
                      <td className="px-3 py-2.5" colSpan={2}>{d.months.length} {d.months.length === 1 ? 'month' : 'months'}</td>
                      <td className="px-3 py-2.5 text-right tabular-nums">{rupees(d.months.reduce((t, m) => t + Number(m.deducted), 0))}</td>
                      <td className="px-3 py-2.5 tabular-nums">{rupees(d.months.reduce((t, m) => t + Number(m.deposited), 0))}</td>
                      <td />
                      <td className="px-3 py-2.5 text-right tabular-nums">{rupees(d.to_deposit)}</td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            )}
          </DprSection>
          {d.by_party.length > 0 && (
            <DprSection icon={Scissors} title="By subcontractor" meta={d.by_party.length}>
              <div data-guide="tds.parties" className={TABLE}>
                <table className="w-full min-w-[560px] text-sm">
                  <thead>
                    <tr className={HEAD}>
                      <th className="px-3 py-2 text-left font-medium">Subcontractor</th>
                      <th className="px-3 py-2 text-left font-medium">PAN</th>
                      <th className="px-3 py-2 text-right font-medium">Bills</th>
                      <th className="px-3 py-2 text-right font-medium">Billed</th>
                      <th className="px-3 py-2 text-right font-medium">TDS</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {d.by_party.map((p) => (
                      <tr key={p.party}>
                        <td className="px-3 py-2">
                          <span className="flex items-center gap-2.5">
                            <PartyAvatar name={p.party} className="size-7 text-[10px]" />
                            <span className="font-medium">{p.party}</span>
                          </span>
                        </td>
                        <td className={cn('px-3 py-2 text-xs', p.pan ? 'tabular-nums text-muted-foreground' : 'font-medium text-destructive')}>{p.pan ?? 'No PAN'}</td>
                        <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">{p.bills}</td>
                        <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">{rupees(p.bill_amount)}</td>
                        <td className="whitespace-nowrap px-3 py-2 text-right font-medium tabular-nums text-draft">{rupees(p.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr className={FOOT}>
                      <td className="px-3 py-2.5" colSpan={3}>{d.by_party.length} {d.by_party.length === 1 ? 'subcontractor' : 'subcontractors'}</td>
                      <td className="px-3 py-2.5 text-right tabular-nums">{rupees(d.by_party.reduce((t, p) => t + Number(p.bill_amount), 0))}</td>
                      <td className="px-3 py-2.5 text-right tabular-nums">{rupees(d.by_party.reduce((t, p) => t + Number(p.amount), 0))}</td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </DprSection>
          )}
          <DprSection icon={HandCoins} title="Deducted by clients from our RA bills" meta={d.by_clients.length || undefined}>
            {d.by_clients.length === 0 ? (
              <p className="text-sm text-muted-foreground">No RA bill with TDS in this period.</p>
            ) : (
              <div data-guide="tds.clients" className={TABLE}>
                <table className="w-full min-w-[640px] text-sm">
                  <thead>
                    <tr className={HEAD}>
                      <th className="px-3 py-2 text-left font-medium">RA bill</th>
                      <th className="px-3 py-2 text-left font-medium">Client PAN</th>
                      <th className="px-3 py-2 text-right font-medium">Bill</th>
                      <th className="px-3 py-2 text-right font-medium">Rate</th>
                      <th className="px-3 py-2 text-right font-medium">TDS</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {d.by_clients.map((r) => (
                      <tr key={r.id}>
                        <td className="px-3 py-2">
                          <Link to={`/billing/ra-bills/${r.id}/document`} className="font-medium hover:underline">
                            {r.ref} · {r.client ?? 'No client'}
                          </Link>
                          <span className="block text-xs text-muted-foreground">{[formatDay(r.date), r.project].filter(Boolean).join(' · ')}</span>
                        </td>
                        <td className="px-3 py-2 text-xs tabular-nums text-muted-foreground">{r.pan ?? '—'}</td>
                        <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">{rupees(r.gross)}</td>
                        <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">{r.rate ? `${Number(r.rate)}%` : '—'}</td>
                        <td className="whitespace-nowrap px-3 py-2 text-right font-medium tabular-nums text-info">{rupees(r.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr className={FOOT}>
                      <td className="px-3 py-2.5" colSpan={4}>{d.by_clients.length} {d.by_clients.length === 1 ? 'RA bill' : 'RA bills'}</td>
                      <td className="px-3 py-2.5 text-right tabular-nums">{rupees(d.by_clients_total)}</td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            )}
          </DprSection>
        </>
      )}
    </div>
  )
}
