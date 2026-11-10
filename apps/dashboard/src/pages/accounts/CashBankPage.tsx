import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowDownLeft, ArrowUpRight, Landmark, Wallet } from 'lucide-react'
import { BooksClosed, BooksTabs, ExcelButton, PeriodBar, usePeriod } from '@/components/accounts/books'
import { DrCr, SplitBars } from '@/components/accounts/visuals'
import { DprHeader, DprSection, PageError, StatStrip } from '@/components/dpr-page'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { useScope } from '@/lib/ScopeContext'
import { fetchCashBank, formatDay, mayReadBooks, rupees, scopeParams, short } from '@/lib/accounts'
import { usePageTitle } from '@/lib/page-title'

// ACC-07 / ACC-22: every cash box and bank account: opening, money in, money out, closing; each day's money in and
// out (moves between the company's own accounts left out); each account opens its book. For a project: the money
// paid and received for it. Backend: GET /accounts/cash-bank.

export default function CashBankPage() {
  usePageTitle('Cash & bank')
  const { me } = useAuth()
  const { scope } = useScope()
  const periodState = usePeriod('this_month')
  const { period } = periodState
  const sp = scopeParams(scope)
  const allowed = mayReadBooks(me?.role)
  const q = useQuery({ queryKey: ['accounts', 'cash-bank', period, sp], queryFn: () => fetchCashBank(period, sp), enabled: allowed })
  if (!allowed) return <BooksClosed />
  if (q.isError) return <PageError message="Cash and bank could not be loaded." onRetry={() => q.refetch()} back={{ to: '/accounts', label: 'Accounts' }} />
  const d = q.data
  const keep = window.location.search
  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader back={{ to: '/accounts', label: 'Accounts' }} crumb="Accounts" title="Cash & bank" date={d?.scope} action={d && <ExcelButton path="/accounts/cash-bank/export" params={{ ...period, ...sp }} name={`cash-and-bank-${period.date_from}-to-${period.date_to}`} />} />
      <BooksTabs current="/accounts/cash-bank" />
      <PeriodBar state={periodState} />
      {!d ? (
        <Skeleton className="h-96 rounded-xl" />
      ) : (
        <>
          <StatStrip
            phoneCols={2}
            stats={[
              { label: 'Opening', value: rupees(d.total.opening), icon: Wallet },
              { label: 'Money in', value: rupees(d.total.in), icon: ArrowDownLeft, tone: 'good' },
              { label: 'Money out', value: rupees(d.total.out), icon: ArrowUpRight },
              { label: 'Closing', value: rupees(d.total.closing), icon: Landmark, tone: Number(d.total.closing) < 0 ? 'bad' : 'info' },
            ]}
          />
          {d.days.length > 0 && (
            <div className="rounded-xl border px-4 py-3">
              <SplitBars
                up="Money in"
                down="Money out"
                upClass="fill-emerald-500"
                downClass="fill-slate-400"
                items={d.days.map((x) => ({
                  key: x.date,
                  label: new Date(`${x.date}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }),
                  up: Number(x.in),
                  down: Number(x.out),
                  detail: (
                    <>
                      {formatDay(x.date)}: in {short(x.in)}, out {short(x.out)}
                    </>
                  ),
                }))}
              />
            </div>
          )}
          <DprSection icon={Landmark} title="Accounts" meta={d.accounts.length || undefined}>
            {d.accounts.length === 0 ? (
              <p className="rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground">No cash box or bank account has moved money in this period{scope.mode !== 'portfolio' ? ` for ${d.scope}` : ''}.</p>
            ) : (
              <div className="overflow-x-auto rounded-lg border">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b bg-muted/40 text-xs text-muted-foreground">
                      <th className="px-3 py-2 text-left font-medium">Account</th>
                      <th className="hidden px-3 py-2 text-right font-medium md:table-cell">Opening</th>
                      <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">In</th>
                      <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">Out</th>
                      <th className="px-3 py-2 text-right font-medium">Closing</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {d.accounts.map((a) => (
                      <tr key={a.ledger_id} className="hover:bg-muted/40">
                        <td className="px-3 py-2">
                          <Link to={`/accounts/ledgers/${a.ledger_id}${keep}`} className="font-medium hover:underline">
                            {a.name}
                          </Link>
                          <span className="block text-xs text-muted-foreground">
                            {a.group} · {a.lines} entries
                          </span>
                        </td>
                        <td className="hidden px-3 py-2 text-right md:table-cell">
                          <DrCr value={a.opening} />
                        </td>
                        <td className="hidden px-3 py-2 text-right tabular-nums text-success sm:table-cell">{Number(a.in) ? `+${rupees(a.in)}` : ''}</td>
                        <td className="hidden px-3 py-2 text-right tabular-nums sm:table-cell">{Number(a.out) ? `−${rupees(a.out)}` : ''}</td>
                        <td className="px-3 py-2 text-right">
                          <DrCr value={a.closing} strong />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="text-xs text-muted-foreground">The same balances as Finance › Money. Tap an account for its book, day by day.</p>
          </DprSection>
        </>
      )}
    </div>
  )
}
