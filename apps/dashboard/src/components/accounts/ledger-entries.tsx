import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight } from 'lucide-react'
import { Skeleton } from '@/components/ui/skeleton'
import { fetchStatement, formatDay, rupees, type Period, type Scope } from '@/lib/accounts'
import { cn } from '@/lib/utils'

// UX-31 / UX-33: an account's entries, opened in place under its line (owner's P&L and balance sheet): newest first,
// each opening its voucher, the full statement one tap further. GET /accounts/ledgers/{id}/statement.

const SHOW = 8

/** ``debitUp``: an expense or an asset reads debit as plus; income, a liability or capital read credit as plus. */
export function LedgerEntries({
  ledgerId,
  period,
  scope,
  debitUp,
  keep,
  onEntry,
  indent,
  empty = 'No entries in this period.',
}: {
  ledgerId: string
  period: Period
  scope: Scope
  debitUp: boolean
  keep: string
  onEntry: (entryId: string) => void
  indent: string
  empty?: string
}) {
  const q = useQuery({ queryKey: ['accounts', 'statement', ledgerId, period, scope], queryFn: () => fetchStatement(ledgerId, period, scope) })
  if (q.isLoading) return <div className={cn('border-t border-border/50 py-2 pr-4', indent)}><Skeleton className="h-16 w-full rounded-md" /></div>
  if (q.isError || !q.data) return <p className={cn('border-t border-border/50 py-2 pr-4 text-xs text-muted-foreground', indent)}>The entries could not be loaded.</p>
  const lines = [...q.data.lines].reverse()
  const amount = (debit: string, credit: string) => (debitUp ? 1 : -1) * (Number(debit) - Number(credit))
  return (
    <div className={cn('border-t border-border/50 bg-muted/25 py-1.5 pr-4', indent)}>
      {lines.length === 0 && <p className="py-1.5 text-xs text-muted-foreground">{empty}</p>}
      <ul className="divide-y divide-border/50">
        {lines.slice(0, SHOW).map((l) => {
          const v = amount(l.debit, l.credit)
          return (
            <li key={l.line_id}>
              <button type="button" onClick={() => onEntry(l.entry_id)} className="flex w-full items-start gap-3 py-1.5 text-left text-xs hover:text-foreground">
                <span className="w-14 shrink-0 tabular-nums text-muted-foreground">{formatDay(l.date).replace(/ \d{4}$/, '')}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-foreground">{l.narration || l.against || l.ref}</span>
                  <span className="block truncate text-muted-foreground">{[l.ref, l.project, l.site].filter(Boolean).join(' · ')}</span>
                </span>
                <span className={cn('shrink-0 tabular-nums', v < 0 && 'text-destructive')}>{v < 0 ? `(${rupees(v)})` : rupees(v)}</span>
              </button>
            </li>
          )
        })}
      </ul>
      <Link to={`/accounts/ledgers/${ledgerId}${keep}`} className="mt-1 inline-flex items-center gap-1 py-1 text-xs font-medium text-primary-ink hover:underline">
        {lines.length > SHOW ? `All ${lines.length} entries` : 'The full statement'} <ArrowRight className="size-3" />
      </Link>
    </div>
  )
}
