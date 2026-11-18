import * as React from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowUpRight, History, ScrollText, Search } from 'lucide-react'
import { BooksClosed, ExcelButton, PeriodBar, VoucherSheet, usePeriod } from '@/components/accounts/books'
import { FlowStrip, PartyAvatar } from '@/components/accounts/money-kit'
import { BalanceLine, DrCr, VoucherBadge } from '@/components/accounts/visuals'
import { Callout, DprHeader, PageError, Segmented } from '@/components/dpr-page'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { useScope } from '@/lib/ScopeContext'
import { LINK_LABEL, VOUCHER_LABEL, drCr, fetchStatement, formatDay, linkedRecord, mayReadBooks, rupees, scopeParams, type Statement, type StatementLine } from '@/lib/accounts'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'
import { Pager } from '@/components/page/pager'
import { usePagedUrl } from '@/lib/paging'

// ACC-05: one ledger (a supplier, a client, a bank, an expense head ...): opening, every entry with what it was
// against and the running balance, closing; for the company, a project or a site. Each line opens its voucher.
// Backend: GET /accounts/ledgers/{id}/statement.
// UX-43 (Mercon's ledger as the reference): the period as a sum in the ledger's own words (a bank: opening + money in
// − money out = closing; a supplier: opening + billed − paid = owed), the balance as a line, and the entries month by
// month with each month's totals, debits amber and credits blue as on the voucher. Search and a debit / credit filter.

type Side = '' | 'dr' | 'cr'

/** What a debit and a credit mean for this ledger, in plain words. ``creditUp``: its balance grows with credits. */
function words(d: Statement): { dr: string; cr: string; creditUp: boolean; closing: string } {
  const k = d.ledger.link_kind
  const nature = d.ledger.nature
  if (k === 'money_account') return { dr: 'Money in', cr: 'Money out', creditUp: false, closing: 'In the account' }
  if (k === 'client') return { dr: 'Billed', cr: 'Received', creditUp: false, closing: 'They owe' }
  if (k === 'vendor') return { dr: 'Paid', cr: 'Billed', creditUp: true, closing: 'You owe' }
  if (k === 'staff') return { dr: 'Paid back', cr: 'Spent for you', creditUp: true, closing: 'You owe them' }
  if (nature === 'expense') return { dr: 'Spent', cr: 'Taken back', creditUp: false, closing: 'Spent so far' }
  if (nature === 'income') return { dr: 'Taken back', cr: 'Earned', creditUp: true, closing: 'Earned so far' }
  if (nature === 'asset') return { dr: 'Added', cr: 'Reduced', creditUp: false, closing: 'Closing' }
  return { dr: 'Reduced', cr: 'Added', creditUp: true, closing: 'Closing' }
}

const monthOf = (iso: string) => new Date(`${iso.slice(0, 7)}-01T00:00:00`).toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })

export default function LedgerStatementPage() {
  const { id = '' } = useParams()
  const { me } = useAuth()
  const { scope } = useScope()
  const periodState = usePeriod()
  const { period } = periodState
  const sp = scopeParams(scope)
  const allowed = mayReadBooks(me?.role)
  const st = useQuery({ queryKey: ['accounts', 'statement', id, period, sp], queryFn: () => fetchStatement(id, period, sp), enabled: allowed && !!id })
  const [openId, setOpenId] = React.useState<string | null>(null)
  const [q, setQ] = React.useState('')
  const [side, setSide] = React.useState<Side>('')
  usePageTitle(st.data?.ledger.name ?? 'Ledger')
  const needle = q.trim().toLowerCase()
  const lines = (st.data?.lines ?? []).filter(
    (l) => (!side || (side === 'dr' ? Number(l.debit) > 0 : Number(l.credit) > 0)) && (!needle || [l.against, l.narration, l.ref, l.project, l.site].join(' ').toLowerCase().includes(needle)),
  )
  const filtered = !!needle || !!side
  // UX-37: 100 lines to a page; a later page starts with the balance brought forward (unfiltered only: a filtered
  // list has no running balance to bring forward).
  const pagedLines = usePagedUrl(lines, { size: 100, resetOn: JSON.stringify([period, sp, needle, side]) })
  const before = !filtered && pagedLines.from > 1 ? lines[pagedLines.from - 2] : undefined
  const lastPage = pagedLines.page === pagedLines.pages

  if (!allowed) return <BooksClosed />
  if (st.isError) return <PageError message="This ledger could not be loaded." onRetry={() => st.refetch()} back={{ to: '/accounts/ledgers', label: 'Ledgers' }} />
  const d = st.data
  const record = d ? linkedRecord(d.ledger.link_kind, d.ledger.link_id) : null
  const w = d ? words(d) : null
  // Money in and out read green and red only for a bank or cash account; elsewhere the two sides keep the voucher's
  // colours (debit amber, credit blue), since a receipt or a bill is not good or bad news by itself
  const money = d?.ledger.link_kind === 'money_account'
  const drTone = money ? ('in' as const) : ('dr' as const)
  const crTone = money ? ('out' as const) : ('cr' as const)
  const months = (() => {
    const m = new Map<string, StatementLine[]>()
    for (const l of pagedLines.shown) m.set(l.date.slice(0, 7), [...(m.get(l.date.slice(0, 7)) ?? []), l])
    return [...m.entries()]
  })()

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader
        back={{ to: '/accounts/ledgers', label: 'Ledgers' }}
        crumb="Accounts"
        title={d?.ledger.name ?? 'Ledger'}
        chip={d && <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">{d.ledger.group_name}{d.ledger.link_kind ? ` · ${LINK_LABEL[d.ledger.link_kind]}` : ''}</span>}
        action={
          d && (
            <div className="flex gap-2">
              {record && (
                <Button asChild size="sm" variant="outline" className="gap-1">
                  <Link to={record.to}>
                    {record.label} <ArrowUpRight className="size-3.5" />
                  </Link>
                </Button>
              )}
              <ExcelButton path={`/accounts/ledgers/${id}/statement/export`} params={{ ...period, ...sp }} name={`${d.ledger.name}-${period.date_from}-to-${period.date_to}`} />
            </div>
          )
        }
      />
      <PeriodBar state={periodState} />
      {!d || !w ? (
        <Skeleton className="h-96 rounded-xl" />
      ) : (
        <>
          <FlowStrip
            items={
              w.creditUp
                ? [
                    { label: 'Opening', value: drCr(d.opening), tone: 'plain', sub: formatDay(d.date_from) },
                    { label: w.cr, value: rupees(d.credit), tone: crTone, op: '+', sub: `${d.lines.filter((l) => Number(l.credit) > 0).length} entries` },
                    { label: w.dr, value: rupees(d.debit), tone: drTone, op: '−', sub: `${d.lines.filter((l) => Number(l.debit) > 0).length} entries` },
                    { label: w.closing, value: drCr(d.closing), tone: 'balance', op: '=', sub: formatDay(d.date_to) },
                  ]
                : [
                    { label: 'Opening', value: drCr(d.opening), tone: 'plain', sub: formatDay(d.date_from) },
                    { label: w.dr, value: rupees(d.debit), tone: drTone, op: '+', sub: `${d.lines.filter((l) => Number(l.debit) > 0).length} entries` },
                    { label: w.cr, value: rupees(d.credit), tone: crTone, op: '−', sub: `${d.lines.filter((l) => Number(l.credit) > 0).length} entries` },
                    { label: w.closing, value: drCr(d.closing), tone: 'balance', op: '=', sub: formatDay(d.date_to) },
                  ]
            }
          />
          {d.ledger.notes && (
            <Callout tone="muted" icon={ScrollText}>
              {d.ledger.notes}
            </Callout>
          )}
          {d.lines.length > 1 && (
            <div className="rounded-xl border bg-card px-4 py-3 shadow-xs">
              <BalanceLine points={[{ date: formatDay(d.date_from), balance: Number(d.opening) }, ...d.lines.map((l) => ({ date: formatDay(l.date), balance: Number(l.balance) }))]} />
            </div>
          )}

          <div className="overflow-hidden rounded-xl border bg-card shadow-xs">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b bg-muted/40 px-3 py-2">
              <span className="flex items-center gap-2 text-sm font-semibold">
                <ScrollText className="size-4 text-muted-foreground" /> Entries
                <span className="text-xs font-normal text-muted-foreground">{filtered ? `${lines.length} of ${d.lines.length}` : d.lines.length}</span>
              </span>
              <div className="flex flex-wrap items-center gap-2">
                <Segmented<Side>
                  label="Which entries"
                  value={side}
                  options={[
                    { value: '', label: 'All' },
                    { value: 'dr', label: w.dr },
                    { value: 'cr', label: w.cr },
                  ]}
                  onChange={setSide}
                />
                <div className="relative">
                  <Search className="pointer-events-none absolute left-2.5 top-2 size-4 text-muted-foreground" />
                  <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Party, words, number, project" aria-label="Search the entries" className="h-8 w-[220px] bg-card pl-8" />
                </div>
              </div>
            </div>
            {d.lines.length === 0 ? (
              <p className="px-4 py-6 text-sm text-muted-foreground">No entry in this ledger in the period{scope.mode !== 'portfolio' ? ` on ${d.scope}` : ''}.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[560px] text-sm">
                  <thead>
                    <tr className="border-b text-xs text-muted-foreground">
                      <th className="px-3 py-2 text-left font-medium">Date</th>
                      <th className="px-3 py-2 text-left font-medium">Particulars</th>
                      <th className="px-3 py-2 text-right font-medium">
                        <span className="inline-flex items-center gap-1.5"><span className="size-1.5 rounded-full bg-draft" /> Debit</span>
                      </th>
                      <th className="px-3 py-2 text-right font-medium">
                        <span className="inline-flex items-center gap-1.5"><span className="size-1.5 rounded-full bg-info" /> Credit</span>
                      </th>
                      <th className="px-3 py-2 text-right font-medium">Balance</th>
                    </tr>
                  </thead>
                  <tbody>
                    {!filtered && (
                      <tr className="border-b bg-muted/30 text-muted-foreground">
                        <td className="whitespace-nowrap px-3 py-2">{formatDay(before ? before.date : d.date_from)}</td>
                        <td className="px-3 py-2 font-medium">{before ? 'Brought forward' : `Opening balance${d.year_start ? ' (from the start of the year)' : ''}`}</td>
                        <td />
                        <td />
                        <td className="px-3 py-2 text-right tabular-nums">{drCr(before ? before.balance : d.opening)}</td>
                      </tr>
                    )}
                    {months.map(([m, list]) => {
                      const dr = list.reduce((t, l) => t + Number(l.debit), 0)
                      const cr = list.reduce((t, l) => t + Number(l.credit), 0)
                      return (
                        <React.Fragment key={m}>
                          {months.length > 1 && (
                            <tr className="border-b bg-muted/50 text-xs">
                              <td colSpan={2} className="px-3 py-1.5 font-semibold">
                                {monthOf(m)} <span className="font-normal text-muted-foreground">· {list.length} entries</span>
                              </td>
                              <td className="px-3 py-1.5 text-right font-medium tabular-nums text-draft">{dr ? rupees(dr) : ''}</td>
                              <td className="px-3 py-1.5 text-right font-medium tabular-nums text-info">{cr ? rupees(cr) : ''}</td>
                              <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{drCr(list[list.length - 1].balance)}</td>
                            </tr>
                          )}
                          {list.map((l) => (
                            <tr key={l.line_id} className={cn('cursor-pointer border-b border-border/60 align-top hover:bg-muted/40', l.after_close && 'bg-draft-soft/30')} onClick={() => setOpenId(l.entry_id)}>
                              <td className="whitespace-nowrap px-3 py-2.5 tabular-nums text-muted-foreground">{formatDay(l.date)}</td>
                              <td className="px-3 py-2.5">
                                <span className="flex items-start gap-2.5">
                                  {l.against ? <PartyAvatar name={l.against} className="size-7 text-[10px]" /> : null}
                                  <span className="min-w-0">
                                    <span className="flex flex-wrap items-center gap-1.5">
                                      <VoucherBadge type={l.voucher_type} label={VOUCHER_LABEL[l.voucher_type]} />
                                      {l.after_close && <History className="size-3.5 shrink-0 text-draft" aria-label="Changed after close" />}
                                      <span className="font-medium">{l.against ? `${Number(l.debit) > 0 ? 'To' : 'By'} ${l.against}` : l.narration}</span>
                                    </span>
                                    <span className="mt-0.5 block text-xs text-muted-foreground">{[l.ref, l.against ? l.narration : null, l.project, l.site].filter(Boolean).join(' · ')}</span>
                                  </span>
                                </span>
                              </td>
                              <td className="px-3 py-2.5 text-right tabular-nums text-draft">{Number(l.debit) ? rupees(l.debit) : ''}</td>
                              <td className="px-3 py-2.5 text-right tabular-nums text-info">{Number(l.credit) ? rupees(l.credit) : ''}</td>
                              <td className="px-3 py-2.5 text-right">
                                <DrCr value={l.balance} />
                              </td>
                            </tr>
                          ))}
                        </React.Fragment>
                      )
                    })}
                    {lines.length === 0 && (
                      <tr>
                        <td colSpan={5} className="px-3 py-6 text-center text-sm text-muted-foreground">
                          No entry matches.{' '}
                          <button type="button" className="font-medium text-foreground underline-offset-2 hover:underline" onClick={() => { setQ(''); setSide('') }}>
                            Show all
                          </button>
                        </td>
                      </tr>
                    )}
                  </tbody>
                  {!filtered && lastPage && (
                    <tfoot>
                      <tr className="border-t-[1.5px] border-foreground/25 bg-muted/30 font-semibold">
                        <td className="whitespace-nowrap px-3 py-2.5">{formatDay(d.date_to)}</td>
                        <td className="px-3 py-2.5">Closing balance</td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-draft">{rupees(d.debit)}</td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-info">{rupees(d.credit)}</td>
                        <td className="px-3 py-2.5 text-right">
                          <DrCr value={d.closing} strong />
                        </td>
                      </tr>
                    </tfoot>
                  )}
                </table>
              </div>
            )}
          </div>
          <Pager {...pagedLines.pager} noun="lines" />
        </>
      )}
      <VoucherSheet entryId={openId} onClose={() => setOpenId(null)} onOpen={setOpenId} />
    </div>
  )
}
