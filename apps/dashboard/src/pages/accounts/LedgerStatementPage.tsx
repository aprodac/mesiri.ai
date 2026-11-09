import * as React from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowUpRight, History, ScrollText } from 'lucide-react'
import { BooksClosed, BooksTabs, ExcelButton, PeriodBar, VoucherSheet, usePeriod } from '@/components/accounts/books'
import { Callout, DprHeader, DprSection, PageError, StatStrip } from '@/components/dpr-page'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { useScope } from '@/lib/ScopeContext'
import { LINK_LABEL, cell, drCr, fetchStatement, formatDay, linkedRecord, mayReadBooks, rupees, scopeParams } from '@/lib/accounts'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'

// ACC-05: one ledger (a supplier, a client, a bank, an expense head ...): opening, every entry with what it was
// against and the running balance, closing; for the company, a project or a site. Each line opens its voucher.
// Backend: GET /accounts/ledgers/{id}/statement.

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
  usePageTitle(st.data?.ledger.name ?? 'Ledger')

  if (!allowed) return <BooksClosed />
  if (st.isError) return <PageError message="This ledger could not be loaded." onRetry={() => st.refetch()} back={{ to: '/accounts/ledgers', label: 'Ledgers' }} />
  const d = st.data
  const record = d ? linkedRecord(d.ledger.link_kind, d.ledger.link_id) : null
  const credit = d && ['liability', 'equity', 'income'].includes(d.ledger.nature)

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 pb-8 sm:px-2">
      <DprHeader
        back={{ to: '/accounts/ledgers', label: 'Ledgers' }}
        crumb="Accounts"
        title={d?.ledger.name ?? 'Ledger'}
        chip={d && <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">{d.ledger.group_name}{d.ledger.link_kind ? ` · ${LINK_LABEL[d.ledger.link_kind]}` : ''}</span>}
        date={d?.scope}
        action={
          d && (
            <div className="flex gap-2">
              {record && (
                <Button asChild size="sm" variant="ghost" className="gap-1">
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
      <BooksTabs current="/accounts/ledgers" />
      <PeriodBar state={periodState} />
      {!d ? (
        <Skeleton className="h-96 rounded-xl" />
      ) : (
        <>
          <StatStrip
            phoneCols={2}
            stats={[
              { label: 'Opening', value: drCr(d.opening) },
              { label: 'Debits', value: rupees(d.debit) },
              { label: 'Credits', value: rupees(d.credit) },
              { label: 'Closing', value: drCr(d.closing), tone: Number(d.closing) === 0 ? 'good' : 'info', hint: credit ? 'A credit here is owed by the company' : 'A debit here is held or owed to the company' },
            ]}
          />
          {d.ledger.notes && (
            <Callout tone="muted" icon={ScrollText}>
              {d.ledger.notes}
            </Callout>
          )}
          <DprSection icon={ScrollText} title="Entries" meta={d.lines.length || undefined}>
            {d.lines.length === 0 ? (
              <p className="rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground">No entry in this ledger in the period{scope.mode !== 'portfolio' ? ` on ${d.scope}` : ''}.</p>
            ) : (
              <div className="overflow-x-auto rounded-lg border">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b bg-muted/40 text-xs text-muted-foreground">
                      <th className="px-3 py-2 text-left font-medium">Date</th>
                      <th className="px-3 py-2 text-left font-medium">Particulars</th>
                      <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">Debit</th>
                      <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">Credit</th>
                      <th className="px-3 py-2 text-right font-medium">Balance</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    <tr className="text-muted-foreground">
                      <td className="px-3 py-2 whitespace-nowrap">{formatDay(d.date_from)}</td>
                      <td className="px-3 py-2">Opening balance{d.year_start ? ' (from the start of the year)' : ''}</td>
                      <td className="hidden sm:table-cell" />
                      <td className="hidden sm:table-cell" />
                      <td className="px-3 py-2 text-right tabular-nums">{drCr(d.opening)}</td>
                    </tr>
                    {d.lines.map((l) => (
                      <tr key={l.line_id} className="cursor-pointer align-top hover:bg-muted/40" onClick={() => setOpenId(l.entry_id)}>
                        <td className="px-3 py-2 whitespace-nowrap">{formatDay(l.date)}</td>
                        <td className="px-3 py-2">
                          <span className="flex items-center gap-1.5">
                            {l.after_close && <History className="size-3.5 shrink-0 text-draft" aria-label="Changed after close" />}
                            <span>{l.against ? `${Number(l.debit) > 0 ? 'To' : 'By'} ${l.against}` : l.narration}</span>
                          </span>
                          <span className="block text-xs text-muted-foreground">
                            {[l.ref, l.against ? l.narration : null, l.project, l.site].filter(Boolean).join(' · ')}
                          </span>
                          <span className="block text-xs tabular-nums sm:hidden">
                            {Number(l.debit) > 0 ? `Dr ${rupees(l.debit)}` : `Cr ${rupees(l.credit)}`}
                          </span>
                        </td>
                        <td className="hidden px-3 py-2 text-right tabular-nums sm:table-cell">{cell(l.debit)}</td>
                        <td className="hidden px-3 py-2 text-right tabular-nums sm:table-cell">{cell(l.credit)}</td>
                        <td className={cn('px-3 py-2 text-right tabular-nums whitespace-nowrap')}>{drCr(l.balance)}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr className="border-t-2 font-semibold">
                      <td className="px-3 py-2 whitespace-nowrap">{formatDay(d.date_to)}</td>
                      <td className="px-3 py-2">Closing balance</td>
                      <td className="hidden px-3 py-2 text-right tabular-nums sm:table-cell">{rupees(d.debit)}</td>
                      <td className="hidden px-3 py-2 text-right tabular-nums sm:table-cell">{rupees(d.credit)}</td>
                      <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap">{drCr(d.closing)}</td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            )}
          </DprSection>
        </>
      )}
      <VoucherSheet entryId={openId} onClose={() => setOpenId(null)} />
    </div>
  )
}
