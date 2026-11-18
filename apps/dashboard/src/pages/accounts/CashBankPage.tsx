import * as React from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowDownLeft, ArrowRight, ArrowUpRight, ChevronDown, Landmark, Wallet } from 'lucide-react'
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
// UX-43 (Mercon's bank accounts as the reference): the period as a sum (opening + in − out = closing); each account a
// card with its balance, its share of all the money, what came in and went out; its last entries open in the card,
// each to its voucher; money in and out day by day below.

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
      <DprHeader back={{ to: '/accounts', label: 'Accounts' }} crumb="Accounts" title="Cash & bank" />
      <PeriodBar state={periodState} />
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
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {accounts.map((a) => {
                  const cash = isCash(a)
                  const Icon = cash ? Wallet : Landmark
                  const closing = Number(a.closing)
                  const share = Math.max(0, closing) / all
                  const moved = Number(a.in) + Number(a.out) || 1
                  const isOpen = open === a.ledger_id
                  return (
                    <div key={a.ledger_id} className={cn('flex flex-col overflow-hidden rounded-xl border bg-card shadow-xs', isOpen && 'md:col-span-2 xl:col-span-3')}>
                      <div className="flex flex-col gap-3 p-4">
                        <div className="flex items-start gap-3">
                          <span className={cn('flex size-10 shrink-0 items-center justify-center rounded-xl', cash ? 'bg-amber-500/10 text-amber-700 dark:text-amber-400' : 'bg-sky-500/10 text-sky-700 dark:text-sky-400')}>
                            <Icon className="size-5" />
                          </span>
                          <div className="min-w-0 flex-1">
                            <Link to={`/accounts/ledgers/${a.ledger_id}${keep}`} className="block truncate font-semibold hover:underline">
                              {a.name}
                            </Link>
                            <span className="block text-xs text-muted-foreground">
                              {a.group} · {a.lines} {a.lines === 1 ? 'entry' : 'entries'}
                            </span>
                          </div>
                          <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium tabular-nums text-muted-foreground" title="Share of all the money in cash and bank">
                            {Math.round(share * 100)}%
                          </span>
                        </div>
                        <div>
                          <p className={cn('text-2xl font-semibold tabular-nums tracking-tight', closing < -tiny && 'text-destructive')}>
                            {closing < -tiny && '−'}
                            {rupees(closing)}
                          </p>
                          <p className="text-xs text-muted-foreground tabular-nums">from {rupees(a.opening)} on {formatDay(d.date_from)}</p>
                        </div>
                        <div className="flex flex-col gap-1.5">
                          <div className="flex h-1.5 w-full gap-0.5 overflow-hidden rounded-full bg-muted">
                            {Number(a.in) > tiny && <span className="h-full rounded-l-full bg-emerald-500" style={{ width: `${(Number(a.in) / moved) * 100}%` }} />}
                            {Number(a.out) > tiny && <span className="h-full rounded-r-full bg-rose-500" style={{ width: `${(Number(a.out) / moved) * 100}%` }} />}
                          </div>
                          <div className="flex justify-between text-xs tabular-nums">
                            <span className="inline-flex items-center gap-1 text-emerald-700 dark:text-emerald-400">
                              <ArrowDownLeft className="size-3.5" /> {rupees(a.in)} in
                            </span>
                            <span className="inline-flex items-center gap-1 text-rose-700 dark:text-rose-400">
                              <ArrowUpRight className="size-3.5" /> {rupees(a.out)} out
                            </span>
                          </div>
                        </div>
                      </div>
                      <div className="mt-auto flex items-center justify-between border-t bg-muted/30 px-4 py-2 text-xs">
                        <button type="button" onClick={() => setOpen(isOpen ? null : a.ledger_id)} aria-expanded={isOpen} className="inline-flex items-center gap-1 font-medium text-muted-foreground hover:text-foreground">
                          <ChevronDown className={cn('size-3.5 transition-transform', isOpen && 'rotate-180')} /> {isOpen ? 'Hide entries' : 'Last entries'}
                        </button>
                        <Link to={`/accounts/ledgers/${a.ledger_id}${keep}`} className="inline-flex items-center gap-1 font-medium text-primary-ink hover:underline">
                          Statement <ArrowRight className="size-3" />
                        </Link>
                      </div>
                      {isOpen && <LedgerEntries ledgerId={a.ledger_id} period={period} scope={sp} debitUp keep={keep} onEntry={setEntry} indent="pl-4" />}
                    </div>
                  )
                })}
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
