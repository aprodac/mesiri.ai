import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, FileUp, Landmark, Link2, Undo2, Wand2 } from 'lucide-react'
import { BooksClosed } from '@/components/accounts/books'
import { FlowStrip } from '@/components/accounts/money-kit'
import { DprHeader, PageError, Segmented } from '@/components/dpr-page'
import { Hint } from '@/components/hint'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast-notification'
import { useAuth } from '@/lib/AuthContext'
import { fetchAccountsApi } from '@/lib/api'
import { formatDay, mayReadBooks, rupees } from '@/lib/accounts'
import {
  autoMatch, bookLine, fetchBankRec, ignoreLine, importStatement, matchLine, reopenLine, type BookEntry, type LineStatus, type StatementLine,
} from '@/lib/bank-rec'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import { useUrlState } from '@/lib/url-state'
import { cn } from '@/lib/utils'

// ACC-13 / FB-03 (contractor session, 21 Nov: "bank sync, so the accountant only enters the small ones"): a bank
// account's statement, downloaded from net banking as CSV, imported and matched to the books. Mesiri matches what has
// the same amount within a few days (a cheque or UTR number in the voucher's words wins); what is left is matched by
// hand, booked in one tap (bank charges, interest: a Journal), or left out with a reason. Backend:
// domains/accounts/bankrec.py.

type Filter = LineStatus | 'all'
type Account = { id: string; name: string; account_type: string; status?: string }

export default function BankRecPage() {
  usePageTitle('Bank reconciliation')
  const { me } = useAuth()
  const allowed = mayReadBooks(me?.role)
  const accounts = useQuery({ queryKey: ['finance', 'accounts', 'all'], queryFn: () => fetchAccountsApi(), enabled: allowed })
  const banks: Account[] = ((accounts.data ?? []) as Account[]).filter((a) => a.account_type === 'bank' && a.status !== 'inactive')
  const [picked, setPicked] = useUrlState<string>('account', '')
  const accountId = picked || banks[0]?.id || ''
  if (!allowed) return <BooksClosed />
  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader
        back={{ to: '/accounts/cash-bank', label: 'Cash & bank' }}
        crumb="Accounts"
        title="Bank reconciliation"
        action={banks.length > 1 ? (
          <Select value={accountId} onValueChange={setPicked}>
            <SelectTrigger aria-label="Bank account" className="h-9 w-[220px] bg-card"><SelectValue /></SelectTrigger>
            <SelectContent>{banks.map((a) => <SelectItem key={a.id} value={a.id}>{a.name}</SelectItem>)}</SelectContent>
          </Select>
        ) : undefined}
      />
      {accounts.isLoading ? (
        <Skeleton className="h-64 rounded-xl" />
      ) : banks.length === 0 ? (
        <p className="rounded-xl border border-dashed bg-card px-4 py-6 text-sm text-muted-foreground">
          No bank account yet. Add one in Finance › Money, then import its statement here.
        </p>
      ) : (
        <Reconcile key={accountId} accountId={accountId} />
      )}
    </div>
  )
}

function Reconcile({ accountId }: { accountId: string }) {
  const toast = useToast()
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['accounts', 'bank-rec', accountId], queryFn: () => fetchBankRec(accountId) })
  const [filter, setFilter] = useUrlState<Filter>('show', 'unmatched')
  const file = React.useRef<HTMLInputElement>(null)
  const refresh = () => { qc.invalidateQueries({ queryKey: ['accounts'] }) }

  const upload = useMutation({
    mutationFn: async (f: File) => importStatement(accountId, f.name, await f.text()),
    onSuccess: (r) => {
      toast.success(`${r.added} line${r.added === 1 ? '' : 's'} added, ${r.matched} matched`,
        [r.repeated ? `${r.repeated} already imported` : '', r.skipped.length ? `${r.skipped.length} not read (row ${r.skipped[0].row}: ${r.skipped[0].why})` : ''].filter(Boolean).join(' · ') || undefined)
      setFilter('unmatched')
      refresh()
    },
    onError: (e) => toast.error('The statement was not imported', apiErrorMessage(e)),
    onSettled: () => { if (file.current) file.current.value = '' },
  })
  const auto = useMutation({
    mutationFn: () => autoMatch(accountId),
    onSuccess: (r) => { toast.success(r.matched ? `${r.matched} matched` : 'Nothing more to match by itself'); refresh() },
    onError: (e) => toast.error('Not matched', apiErrorMessage(e)),
  })

  if (q.isError) return <PageError message="The reconciliation did not load." onRetry={() => q.refetch()} back={{ to: '/accounts/cash-bank', label: 'Cash & bank' }} />
  const d = q.data
  const diff = d && d.statement_balance != null && d.book_balance != null ? Number(d.statement_balance) - Number(d.book_balance) : null
  const shown = d ? d.lines.filter((l) => filter === 'all' || l.status === filter) : []

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <Landmark className="size-4" />
          {d && d.lines.length ? `${formatDay(d.date_from)} to ${formatDay(d.date_to)}` : 'No statement imported yet'}
          <Hint
            title="Reconcile the bank"
            text="Download the statement from net banking as CSV and import it. Mesiri matches each line to the payment or receipt already in the books. What is left: match it by hand, book it (bank charges, interest) or leave it out with a reason."
          />
        </p>
        <div className="flex flex-wrap gap-2">
          <input ref={file} type="file" accept=".csv,text/csv,text/plain" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f) }} />
          {d && d.counts.unmatched > 0 && (
            <Button size="sm" variant="outline" className="gap-1.5" disabled={auto.isPending} onClick={() => auto.mutate()}><Wand2 className="size-4" />Match again</Button>
          )}
          <Button size="sm" className="gap-1.5" data-guide="bankrec.import" disabled={upload.isPending} onClick={() => file.current?.click()}>
            <FileUp className="size-4" />{upload.isPending ? 'Importing…' : 'Import statement (CSV)'}
          </Button>
        </div>
      </div>

      {!d ? (
        <Skeleton className="h-80 rounded-xl" />
      ) : (
        <>
          <FlowStrip
            guide="bankrec.stats"
            items={[
              { label: 'Bank says', value: d.statement_balance != null ? rupees(d.statement_balance) : '—', tone: 'plain', sub: `on ${formatDay(d.as_of)}` },
              { label: 'Books say', value: d.book_balance != null ? rupees(d.book_balance) : '—', tone: 'balance', sub: `on ${formatDay(d.as_of)}` },
              {
                label: 'Difference',
                value: diff == null ? '—' : `${diff < 0 ? '−' : ''}${rupees(Math.abs(diff))}`,
                tone: diff != null && Math.abs(diff) < 0.005 ? 'in' : 'out',
                sub: diff != null && Math.abs(diff) < 0.005 ? 'reconciled' : `in ${rupees(d.in_unmatched)} · out ${rupees(d.out_unmatched)} open`,
              },
              { label: 'Lines', value: `${d.counts.matched} of ${d.lines.length}`, tone: 'plain', sub: `matched · ${d.counts.unmatched} open · ${d.counts.ignored} left out` },
            ]}
          />

          <Segmented<Filter>
            label="Show"
            guide="bankrec.filter"
            value={filter}
            onChange={setFilter}
            options={[
              { value: 'unmatched', label: 'To match', count: d.counts.unmatched },
              { value: 'matched', label: 'Matched', count: d.counts.matched },
              { value: 'ignored', label: 'Left out', count: d.counts.ignored },
              { value: 'all', label: 'All', count: d.lines.length },
            ]}
          />

          <section className="overflow-hidden rounded-xl border bg-card shadow-xs" data-guide="bankrec.lines">
            {shown.length === 0 ? (
              <p className="px-4 py-6 text-sm text-muted-foreground">
                {d.lines.length === 0 ? 'Import a statement to start.' : filter === 'unmatched' ? 'Every line is matched or left out.' : 'Nothing here.'}
              </p>
            ) : (
              <ul className="divide-y">
                {shown.map((l) => <LineRow key={l.id} line={l} books={d.books_unmatched} onDone={refresh} />)}
              </ul>
            )}
          </section>

          {d.books_unmatched.length > 0 && (
            <section className="flex flex-col gap-2" data-guide="bankrec.books">
              <h2 className="flex items-center gap-1.5 px-1 text-base font-semibold">
                In the books, not on the statement <span className="text-sm font-normal text-muted-foreground">{d.books_unmatched.length}</span>
                <Hint title="Not on the statement" text="Payments and receipts recorded in Mesiri that the bank has not shown yet: a cheque not cleared, or an entry in the wrong account or with the wrong amount." />
              </h2>
              <ul className="divide-y overflow-hidden rounded-xl border bg-card text-sm shadow-xs">
                {d.books_unmatched.map((b) => (
                  <li key={b.entry_id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2">
                    <span className="min-w-0"><span className="font-medium">{b.ref}</span> <span className="text-muted-foreground">· {formatDay(b.date)} · {b.words}</span></span>
                    <Amount value={b.amount} />
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </>
  )
}

function Amount({ value }: { value: string }) {
  const n = Number(value)
  return <span className={cn('shrink-0 font-semibold tabular-nums', n >= 0 ? 'text-emerald-700 dark:text-emerald-400' : 'text-rose-700 dark:text-rose-400')}>{n >= 0 ? '+' : '−'}{rupees(Math.abs(n))}</span>
}

function LineRow({ line, books, onDone }: { line: StatementLine; books: BookEntry[]; onDone: () => void }) {
  const toast = useToast()
  const [ignoring, setIgnoring] = React.useState(false)
  const [note, setNote] = React.useState('')
  const same = books.filter((b) => Number(b.amount) === Number(line.amount))
  const act = useMutation({
    mutationFn: async (what: { kind: 'match'; entry: string } | { kind: 'book' } | { kind: 'ignore' } | { kind: 'reopen' }) => {
      if (what.kind === 'match') return matchLine(line.id, what.entry)
      if (what.kind === 'book') return bookLine(line.id)
      if (what.kind === 'ignore') return ignoreLine(line.id, note.trim())
      return reopenLine(line.id)
    },
    onSuccess: (_r, what) => {
      toast.success(what.kind === 'book' ? `Booked as ${Number(line.amount) < 0 ? 'bank charges' : 'interest received'} and matched` : what.kind === 'reopen' ? 'Open again' : what.kind === 'ignore' ? 'Left out' : 'Matched')
      setIgnoring(false)
      onDone()
    },
    onError: (e) => toast.error('Not saved', apiErrorMessage(e)),
  })
  const busy = act.isPending
  return (
    <li className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center" data-record-id={line.id}>
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-baseline gap-x-2">
          <span className="text-xs text-muted-foreground tabular-nums">{formatDay(line.date)}</span>
          <span className="min-w-0 truncate font-medium">{line.description || '(no description)'}</span>
          {line.reference && <span className="text-xs text-muted-foreground">Ref {line.reference}</span>}
        </p>
        {line.status === 'matched' && line.entry && (
          <p className="mt-0.5 flex items-center gap-1 text-xs text-emerald-700 dark:text-emerald-400">
            <Check className="size-3" />{line.entry.ref} · {formatDay(line.entry.date)} · {line.entry.words}
            <span className="text-muted-foreground">({line.matched_how === 'auto' ? 'matched by Mesiri' : line.matched_how === 'booked' ? 'booked here' : `matched${line.decided_by ? ` by ${line.decided_by}` : ''}`})</span>
          </p>
        )}
        {line.status === 'ignored' && <p className="mt-0.5 text-xs text-muted-foreground">Left out: {line.note}</p>}
        {line.stale && <p className="mt-0.5 text-xs text-draft">Its voucher is gone (the record was removed): match it again.</p>}
        {ignoring && (
          <form className="mt-2 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (note.trim().length >= 2) act.mutate({ kind: 'ignore' }) }}>
            <Input autoFocus className="h-8" placeholder="Why, e.g. bank error reversed next day" value={note} onChange={(e) => setNote(e.target.value)} />
            <Button size="sm" type="submit" disabled={busy || note.trim().length < 2}>Leave out</Button>
            <Button size="sm" variant="ghost" type="button" onClick={() => setIgnoring(false)}>Cancel</Button>
          </form>
        )}
      </div>
      <Amount value={line.amount} />
      <div className="flex shrink-0 flex-wrap items-center gap-1.5 sm:justify-end">
        {line.status === 'unmatched' && !ignoring && (
          <>
            {same.length > 0 && (
              <Select onValueChange={(v) => act.mutate({ kind: 'match', entry: v })} disabled={busy}>
                <SelectTrigger aria-label="Match to" className="h-8 w-[170px]"><Link2 className="size-3.5" /><SelectValue placeholder={`Match (${same.length})`} /></SelectTrigger>
                <SelectContent>{same.map((b) => <SelectItem key={b.entry_id} value={b.entry_id}>{b.ref} · {formatDay(b.date)} · {b.words?.slice(0, 40)}</SelectItem>)}</SelectContent>
              </Select>
            )}
            <Button size="sm" variant="outline" className="h-8" disabled={busy} onClick={() => act.mutate({ kind: 'book' })}
              title={Number(line.amount) < 0 ? 'A Journal: Bank charges / this bank' : 'A Journal: this bank / Interest received'}>
              Book as {Number(line.amount) < 0 ? 'charges' : 'interest'}
            </Button>
            <Button size="sm" variant="ghost" className="h-8" disabled={busy} onClick={() => setIgnoring(true)}>Leave out</Button>
          </>
        )}
        {line.status !== 'unmatched' && (
          <Button size="sm" variant="ghost" className="h-8 gap-1" disabled={busy} onClick={() => act.mutate({ kind: 'reopen' })}><Undo2 className="size-3.5" />Undo</Button>
        )}
      </div>
    </li>
  )
}
