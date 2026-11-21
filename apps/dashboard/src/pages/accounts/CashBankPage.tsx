import * as React from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowDownLeft, ArrowUpRight, ChevronDown, Landmark, Wallet } from 'lucide-react'
import { BooksClosed, PeriodBar, VoucherSheet, usePeriod } from '@/components/accounts/books'
import { LedgerEntries } from '@/components/accounts/ledger-entries'
import { FlowStrip } from '@/components/accounts/money-kit'
import { SplitBars } from '@/components/accounts/visuals'
import { DprHeader, PageError } from '@/components/dpr-page'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { useScope } from '@/lib/ScopeContext'
import { fetchCashBank, formatDay, mayReadBooks, rupees, scopeParams, short, type CashAccount } from '@/lib/accounts'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'

// ACC-07 / ACC-22: every cash box and bank account: opening, money in, money out, closing; each day's money in and
// out (moves between the company's own accounts left out); each account opens its book. For a project: the money
// paid and received for it. Backend: GET /accounts/cash-bank.
// UXA-05 (Mercon's bank accounts as the reference): the period as a sum (opening + in − out = closing); the accounts as
// one table (UXA-06): opening, money in (green), money out (rose), an in / out bar, closing, its share of all the money;
// its entries open under its row, each to its voucher; money in and out day by day below.

const tiny = 0.005
const isCash = (a: CashAccount) => /cash/i.test(a.group)

export default function CashBankPage() {
  usePageTitle('Cash & bank')
  const { me } = useAuth()
  const { scope } = useScope()
  const periodState = usePeriod('this_month')
  const { period } = periodState
  const sp = scopeParams(scope)
  const allowed = mayReadBooks(me?.role)
  const q = useQuery({ queryKey: ['accounts', 'cash-bank', period, sp], queryFn: () => fetchCashBank(period, sp), enabled: allowed })
  const [open, setOpen] = React.useState<string | null>(null)
  const [entry, setEntry] = React.useState<string | null>(null)
  if (!allowed) return <BooksClosed />
  if (q.isError) return <PageError message="Cash and bank could not be loaded." onRetry={() => q.refetch()} back={{ to: '/accounts', label: 'Accounts' }} />
  const d = q.data
  const keep = window.location.search
  const all = d ? Math.max(tiny, d.accounts.reduce((t, a) => t + Math.max(0, Number(a.closing)), 0)) : 1
  const net = d ? Number(d.total.in) - Number(d.total.out) : 0
  const accounts = d ? [...d.accounts].sort((a, b) => Number(b.closing) - Number(a.closing)) : []
  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader
        back={{ to: '/accounts', label: 'Accounts' }}
        crumb="Accounts"
        title="Cash & bank"
        action={
          <div className="flex flex-wrap items-center gap-2">
            {/* ACC-13: a bank account's statement matched to the books. */}
            <Link to="/accounts/bank-rec" data-guide="cash.bankrec" className="inline-flex h-9 items-center gap-1.5 rounded-md border bg-card px-3 text-sm font-medium shadow-xs hover:bg-muted">
              <Landmark className="size-4" />Reconcile bank
            </Link>
            <PeriodBar state={periodState} />
          </div>
        }
      />
      {!d ? (
        <Skeleton className="h-96 rounded-xl" />
      ) : (
        <>
          <FlowStrip
            guide="cash.stats"
            items={[
              { label: 'Opening', value: rupees(d.total.opening), tone: 'plain', sub: formatDay(d.date_from) },
              { label: 'Money in', value: rupees(d.total.in), tone: 'in', op: '+', sub: 'received' },
              { label: 'Money out', value: rupees(d.total.out), tone: 'out', op: '−', sub: 'paid' },
              {
                label: 'Closing',
                value: (Number(d.total.closing) < -tiny ? '−' : '') + rupees(d.total.closing),
                tone: 'balance',
                op: '=',
                sub: (
                  <span className={cn('font-medium', net >= 0 ? 'text-emerald-700 dark:text-emerald-400' : 'text-rose-700 dark:text-rose-400')}>
                    {net >= 0 ? '▲' : '▼'} {rupees(Math.abs(net))} {net >= 0 ? 'more' : 'less'} than at the start
                  </span>
                ),
              },
            ]}
          />

          <section data-guide="cash.list" className="flex flex-col gap-2">
            <h2 className="px-1 text-base font-semibold">
              Accounts <span className="text-sm font-normal text-muted-foreground">{d.accounts.length}</span>
            </h2>
            {d.accounts.length === 0 ? (
              <p className="rounded-xl border border-dashed bg-card px-4 py-6 text-sm text-muted-foreground">No cash box or bank account has moved money in this period{scope.mode !== 'portfolio' ? ` for ${d.scope}` : ''}.</p>
            ) : (
              <div className="overflow-hidden rounded-xl border bg-card shadow-xs">
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[720px] text-sm">
                    <thead>
                      <tr className="border-b bg-muted text-xs text-muted-foreground">
                        <th className="px-3 py-2 text-left font-medium">Account</th>
                        <th className="px-3 py-2 text-right font-medium">Opening</th>
                        <th className="px-3 py-2 text-right font-medium">
                          <span className="inline-flex items-center gap-1"><ArrowDownLeft className="size-3.5 text-emerald-600" /> Money in</span>
                        </th>
                        <th className="px-3 py-2 text-right font-medium">
                          <span className="inline-flex items-center gap-1"><ArrowUpRight className="size-3.5 text-rose-600" /> Money out</span>
                        </th>
                        <th className="px-3 py-2 text-left font-medium">In and out</th>
                        <th className="px-3 py-2 text-right font-medium">Closing</th>
                        <th className="px-3 py-2 text-left font-medium">Share</th>
                        <th className="w-24 px-3 py-2" />
                      </tr>
                    </thead>
                    <tbody>
                      {accounts.map((a) => {
                        const cash = isCash(a)
                        const Icon = cash ? Wallet : Landmark
                        const closing = Number(a.closing)
                        const share = Math.max(0, closing) / all
                        const moved = Number(a.in) + Number(a.out) || 1
                        const isOpen = open === a.ledger_id
                        return (
                          <React.Fragment key={a.ledger_id}>
                            <tr className={cn('border-t border-border/60 first:border-t-0 hover:bg-muted/30', isOpen && 'bg-muted/30')}>
                              <td className="px-3 py-2.5">
                                <span className="flex items-center gap-2.5">
                                  <span className={cn('flex size-8 shrink-0 items-center justify-center rounded-lg', cash ? 'bg-amber-500/10 text-amber-700 dark:text-amber-400' : 'bg-sky-500/10 text-sky-700 dark:text-sky-400')}>
                                    <Icon className="size-4" />
                                  </span>
                                  <span className="min-w-0">
                                    <Link to={`/accounts/ledgers/${a.ledger_id}${keep}`} className="block truncate font-semibold hover:underline">
                                      {a.name}
                                    </Link>
                                    <span className="block text-xs text-muted-foreground">
                                      {a.group} · {a.lines} {a.lines === 1 ? 'entry' : 'entries'}
                                    </span>
                                  </span>
                                </span>
                              </td>
                              <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums text-muted-foreground">{rupees(a.opening)}</td>
                              <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums text-emerald-700 dark:text-emerald-400">{Number(a.in) ? `+${rupees(a.in)}` : '—'}</td>
                              <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums text-rose-700 dark:text-rose-400">{Number(a.out) ? `−${rupees(a.out)}` : '—'}</td>
                              <td className="px-3 py-2.5">
                                <span className="flex h-1.5 w-24 gap-0.5 overflow-hidden rounded-full bg-muted">
                                  {Number(a.in) > tiny && <span className="h-full rounded-l-full bg-emerald-500" style={{ width: `${(Number(a.in) / moved) * 100}%` }} />}
                                  {Number(a.out) > tiny && <span className="h-full rounded-r-full bg-rose-500" style={{ width: `${(Number(a.out) / moved) * 100}%` }} />}
                                </span>
                              </td>
                              <td className={cn('whitespace-nowrap px-3 py-2.5 text-right text-base font-semibold tabular-nums', closing < -tiny && 'text-destructive')}>
                                {closing < -tiny && '−'}
                                {rupees(closing)}
                              </td>
                              <td className="px-3 py-2.5">
                                <span className="flex items-center gap-2" title="Share of all the money in cash and bank">
                                  <span className="h-1.5 w-16 overflow-hidden rounded-full bg-muted">
                                    <span className={cn('block h-full rounded-full', cash ? 'bg-amber-500' : 'bg-sky-500')} style={{ width: `${share * 100}%` }} />
                                  </span>
                                  <span className="text-xs tabular-nums text-muted-foreground">{Math.round(share * 100)}%</span>
                                </span>
                              </td>
                              <td className="px-3 py-2 text-right">
                                <button type="button" onClick={() => setOpen(isOpen ? null : a.ledger_id)} aria-expanded={isOpen} className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground">
                                  <ChevronDown className={cn('size-3.5 transition-transform', isOpen && 'rotate-180')} /> Entries
                                </button>
                              </td>
                            </tr>
                            {isOpen && (
                              <tr>
                                <td colSpan={8} className="p-0">
                                  <LedgerEntries ledgerId={a.ledger_id} period={period} scope={sp} debitUp keep={keep} onEntry={setEntry} indent="pl-14" />
                                </td>
                              </tr>
                            )}
                          </React.Fragment>
                        )
                      })}
                    </tbody>
                    <tfoot>
                      <tr className="border-t-[1.5px] border-foreground/25 bg-muted/30 font-semibold">
                        <td className="px-3 py-2.5">All accounts</td>
                        <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums">{rupees(d.total.opening)}</td>
                        <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums text-emerald-700 dark:text-emerald-400">+{rupees(d.total.in)}</td>
                        <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums text-rose-700 dark:text-rose-400">−{rupees(d.total.out)}</td>
                        <td />
                        <td className="whitespace-nowrap px-3 py-2.5 text-right text-base tabular-nums">{rupees(d.total.closing)}</td>
                        <td colSpan={2} />
                      </tr>
                    </tfoot>
                  </table>
                </div>
              </div>
            )}
          </section>

          {d.days.length > 0 && (
            <div className="rounded-xl border bg-card px-4 py-3 shadow-xs">
              <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-[13px] font-semibold">Money in and out, day by day</p>
                <p className="text-xs text-muted-foreground">Moves between your own accounts are left out</p>
              </div>
              <SplitBars
                up="Money in"
                down="Money out"
                upClass="fill-emerald-500"
                downClass="fill-rose-500"
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
        </>
      )}
      <VoucherSheet entryId={entry} onClose={() => setEntry(null)} onOpen={setEntry} />
    </div>
  )
}
