import * as React from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDownLeft, ArrowUpRight, BadgeCheck, CircleAlert, FileUp, Landmark, Link2, ListChecks, Undo2 } from 'lucide-react'
import { BooksClosed, BooksTabs, ExcelButton } from '@/components/accounts/books'
import { Callout, DprHeader, DprSection, PageError, Segmented, StatStrip } from '@/components/dpr-page'
import { Button } from '@/components/ui/button'
import { Combobox } from '@/components/ui/combobox'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast-notification'
import { useAuth } from '@/lib/AuthContext'
import {
  bankLineAction,
  fetchBank,
  fetchBankAccounts,
  fetchChart,
  formatDay,
  mayReadBooks,
  rupees,
  uploadStatement,
  type BankLine,
  type LineStatus,
  type StatementImport,
} from '@/lib/accounts'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'

// ACC-13: the bank statement against the money movements Mesiri has for the account. Import the statement (Excel or
// CSV as the bank gives it), lines match on their own (amount, direction, ±3 days, the UTR); what the bank has and
// Mesiri does not (charges, interest) is booked with one tap as a movement in Finance › Money, so the books and Money
// keep agreeing. The reconciliation says why the books and the statement differ. Backend: /accounts/bank.

const STATE: Record<LineStatus, { word: string; cls: string }> = {
  open: { word: 'To reconcile', cls: 'bg-draft-soft text-draft' },
  matched: { word: 'Matched', cls: 'bg-success-soft text-success' },
  booked: { word: 'Booked', cls: 'bg-info-soft text-info' },
  ignored: { word: 'Ignored', cls: 'bg-muted text-muted-foreground' },
}
type View = 'open' | 'all'

export default function BankRecoPage() {
  usePageTitle('Bank reconciliation')
  const { me } = useAuth()
  const allowed = mayReadBooks(me?.role)
  const toast = useToast()
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const accounts = useQuery({ queryKey: ['accounts', 'bank'], queryFn: fetchBankAccounts, enabled: allowed })
  const list = accounts.data?.accounts ?? []
  const accountId = params.get('account') ?? list.find((a) => a.account_type === 'bank')?.id ?? list[0]?.id ?? ''
  const q = useQuery({ queryKey: ['accounts', 'bank', accountId], queryFn: () => fetchBank(accountId), enabled: allowed && !!accountId })
  const [view, setView] = React.useState<View>('open')
  const [booking, setBooking] = React.useState<BankLine | null>(null)
  const [preview, setPreview] = React.useState<{ file: File; data: StatementImport } | null>(null)
  const fileRef = React.useRef<HTMLInputElement>(null)
  const refresh = (data?: unknown) => {
    if (data) qc.setQueryData(['accounts', 'bank', accountId], data)
    qc.invalidateQueries({ queryKey: ['accounts'] })
  }
  const act = useMutation({
    mutationFn: (a: { line: string; action: 'match' | 'book' | 'ignore' | 'undo'; body?: object }) => bankLineAction(a.line, a.action, a.body),
    onSuccess: (data) => refresh(data),
    onError: (err: unknown) => toast.error('Not done', apiErrorMessage(err)),
  })
  const read = useMutation({
    mutationFn: (file: File) => uploadStatement(accountId, file, true),
    onSuccess: (data, file) => setPreview({ file, data }),
    onError: (err: unknown) => toast.error('The statement could not be read', apiErrorMessage(err)),
  })
  const save = useMutation({
    mutationFn: () => uploadStatement(accountId, preview!.file, false),
    onSuccess: (data) => {
      toast.success(`${data.new} lines imported`, `${data.matched ?? 0} matched on their own${data.already_imported ? `; ${data.already_imported} were already in` : ''}.`)
      setPreview(null)
      refresh()
    },
    onError: (err: unknown) => toast.error('Not imported', apiErrorMessage(err)),
  })

  if (!allowed) return <BooksClosed />
  if (accounts.isError || q.isError) return <PageError message="Bank reconciliation could not be loaded." onRetry={() => (accounts.isError ? accounts.refetch() : q.refetch())} back={{ to: '/accounts/cash-bank', label: 'Cash & bank' }} />
  const d = q.data
  const rec = d?.reconciliation
  const shown = (d?.lines ?? []).filter((l) => view === 'all' || l.status === 'open')

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader
        back={{ to: '/accounts/cash-bank', label: 'Cash & bank' }}
        crumb="Accounts"
        title="Bank reconciliation"
        date={d ? d.account.name : undefined}
        action={
          <div className="flex flex-wrap gap-1.5">
            {d && d.total > 0 && <ExcelButton path={`/accounts/bank/${accountId}/export`} params={{}} name={`bank-reconciliation-${d.account.name}`} />}
            <Button size="sm" className="gap-1.5" disabled={!accountId || read.isPending} onClick={() => fileRef.current?.click()}>
              <FileUp className="size-4" /> {read.isPending ? 'Reading…' : 'Import statement'}
            </Button>
          </div>
        }
      />
      <input ref={fileRef} type="file" accept=".csv,.xlsx,.xlsm,.txt" className="hidden" onChange={(e) => {
        const f = e.target.files?.[0]
        if (f) read.mutate(f)
        e.target.value = ''
      }} />
      <BooksTabs current="/accounts/bank-reco" />
      {list.length > 1 && (
        <Segmented<string> label="Account" value={accountId} options={list.map((a) => ({ value: a.id, label: `${a.name}${Number(a.open) ? ` (${a.open})` : ''}` }))}
          onChange={(v) => setParams((p) => { const n = new URLSearchParams(p); n.set('account', v); return n }, { replace: true })} />
      )}
      {accounts.isSuccess && list.length === 0 ? (
        <p className="rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground">No bank account yet. Add one in <Link to="/finance/money" className="underline">Finance › Money</Link>.</p>
      ) : !d ? (
        <Skeleton className="h-96 rounded-xl" />
      ) : (
        <>
          <StatStrip
            phoneCols={2}
            stats={[
              { label: 'Reconciled', value: d.reconciled_pct === null ? '—' : `${d.reconciled_pct}%`, icon: ListChecks, tone: d.reconciled_pct === 100 ? 'good' : d.total ? 'warn' : 'default', hint: `${d.total - d.counts.open} of ${d.total} lines` },
              { label: 'To reconcile', value: String(d.counts.open), icon: CircleAlert, tone: d.counts.open ? 'warn' : 'good' },
              { label: 'Balance in the books', value: rupees(d.books_today), icon: Landmark, hint: 'today' },
              { label: 'Difference', value: rec?.difference == null ? '—' : rupees(rec.difference), icon: BadgeCheck, tone: rec?.difference == null ? 'default' : Number(rec.difference) ? 'bad' : 'good', hint: rec ? `on ${formatDay(rec.as_of)}` : 'import a statement' },
            ]}
          />
          {d.total === 0 && (
            <Callout tone="info" icon={FileUp}>
              Download the statement from the bank's website as Excel or CSV and import it. Mesiri finds the columns (date, narration, withdrawal, deposit, balance) and matches each line to what you recorded.
            </Callout>
          )}
          {rec && (
            <DprSection icon={BadgeCheck} title="Reconciliation" meta={`on ${formatDay(rec.as_of)}`}>
              <dl className="divide-y rounded-lg border text-sm">
                {([
                  ['Balance in the books', rec.books, null],
                  ['Add: paid in Mesiri, not in the bank yet', rec.paid_not_in_bank, '+'],
                  ['Less: received in Mesiri, not in the bank yet', rec.received_not_in_bank, '−'],
                  ['Add: in the bank only, not reconciled', rec.bank_only_in, '+'],
                  ['Less: out of the bank only, not reconciled', rec.bank_only_out, '−'],
                ] as const).map(([k, v, sign]) => (
                  <div key={k} className="flex items-center gap-4 px-3 py-2">
                    <dt className="flex-1 text-muted-foreground">{k}</dt>
                    <dd className="tabular-nums">{sign && Number(v) ? `${sign} ` : ''}{rupees(v)}</dd>
                  </div>
                ))}
                <div className="flex items-center gap-4 px-3 py-2 font-medium">
                  <dt className="flex-1">Balance the bank should show</dt>
                  <dd className="tabular-nums">{rupees(rec.explained_bank)}</dd>
                </div>
                <div className="flex items-center gap-4 px-3 py-2">
                  <dt className="flex-1 text-muted-foreground">Balance the statement shows</dt>
                  <dd className="tabular-nums">{rec.statement == null ? 'not in the file' : rupees(rec.statement)}</dd>
                </div>
                {rec.difference != null && (
                  <div className={cn('flex items-center gap-4 px-3 py-2 font-semibold', Number(rec.difference) ? 'text-destructive' : 'text-success')}>
                    <dt className="flex-1">{Number(rec.difference) ? 'Not explained' : 'Explained to the paisa'}</dt>
                    <dd className="tabular-nums">{rupees(rec.difference)}</dd>
                  </div>
                )}
              </dl>
            </DprSection>
          )}
          {d.total > 0 && (
            <DprSection
              icon={ListChecks}
              title="Statement lines"
              meta={view === 'open' ? `${d.counts.open} to reconcile` : `${d.total}`}
              action={<Segmented<View> label="Show" value={view} options={[{ value: 'open', label: 'To reconcile' }, { value: 'all', label: 'All' }]} onChange={setView} />}
            >
              {shown.length === 0 ? (
                <p className="rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground">Every line is reconciled.</p>
              ) : (
                <ul className="divide-y rounded-lg border text-sm">
                  {shown.map((l) => {
                    const inflow = Number(l.amount) > 0
                    return (
                      <li key={l.id} className="flex flex-col gap-2 px-3 py-2.5">
                        <div className="flex items-start gap-3">
                          {inflow ? <ArrowDownLeft className="mt-0.5 size-4 shrink-0 text-success" /> : <ArrowUpRight className="mt-0.5 size-4 shrink-0 text-muted-foreground" />}
                          <span className="min-w-0 flex-1">
                            <span className="block break-words font-medium">{l.description ?? 'No narration'}</span>
                            <span className="block text-xs text-muted-foreground">
                              {[formatDay(l.date), l.reference, l.movement ? `↔ ${[l.movement.party, l.movement.description].filter(Boolean).join(' · ') || 'a money movement'}` : null, l.booked_ledger ? `booked to ${l.booked_ledger}` : null].filter(Boolean).join(' · ')}
                            </span>
                          </span>
                          <span className={cn('shrink-0 font-semibold tabular-nums', inflow && 'text-success')}>{inflow ? '+' : '−'}{rupees(l.amount)}</span>
                          <span className={cn('hidden shrink-0 rounded-full px-2 py-0.5 text-xs sm:inline', STATE[l.status].cls)}>{STATE[l.status].word}</span>
                        </div>
                        <div className="flex flex-wrap gap-1.5 pl-7">
                          {l.status === 'open' ? (
                            <>
                              {l.suggestions.map((s) => (
                                <Button key={s.id} size="sm" variant="outline" className="h-7 gap-1 text-xs" disabled={act.isPending}
                                  onClick={() => act.mutate({ line: l.id, action: 'match', body: { money_transaction_id: s.id } })}>
                                  <Link2 className="size-3" /> {formatDay(s.date)} · {s.party ?? s.description ?? 'movement'}
                                </Button>
                              ))}
                              <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => setBooking(l)}>Book it</Button>
                              <Button size="sm" variant="ghost" className="h-7 text-xs text-muted-foreground" disabled={act.isPending}
                                onClick={() => act.mutate({ line: l.id, action: 'ignore' })}>Ignore</Button>
                            </>
                          ) : (
                            <Button size="sm" variant="ghost" className="h-7 gap-1 text-xs text-muted-foreground" disabled={act.isPending}
                              onClick={() => act.mutate({ line: l.id, action: 'undo' })}>
                              <Undo2 className="size-3" /> Undo{l.status === 'booked' ? ' (reversed in Money)' : ''}
                            </Button>
                          )}
                        </div>
                      </li>
                    )
                  })}
                </ul>
              )}
            </DprSection>
          )}
          {d.not_in_bank.length > 0 && (
            <DprSection icon={Landmark} title="In Mesiri, not in the statement yet" meta={d.not_in_bank.length}>
              <ul className="divide-y rounded-lg border text-sm">
                {d.not_in_bank.map((m) => (
                  <li key={m.id} className="flex items-center gap-3 px-3 py-2">
                    <span className="min-w-0 flex-1">
                      <span className="block font-medium">{m.party ?? m.description ?? 'Money movement'}</span>
                      <span className="block text-xs text-muted-foreground">{[formatDay(m.date), m.party ? m.description : null].filter(Boolean).join(' · ')}</span>
                    </span>
                    <span className="tabular-nums">{m.inflow ? '+' : '−'}{rupees(m.amount)}</span>
                  </li>
                ))}
              </ul>
              <p className="text-xs text-muted-foreground">A cheque not presented yet or a deposit not credited yet. If one never reaches the bank, undo it in Finance › Money.</p>
            </DprSection>
          )}
        </>
      )}
      <BookDialog line={booking} onClose={() => setBooking(null)} onBook={(ledger_id) => {
        act.mutate({ line: booking!.id, action: 'book', body: { ledger_id } }, { onSuccess: () => { setBooking(null); toast.success('Booked', 'Recorded in Finance › Money and posted to the books.') } })
      }} busy={act.isPending} />
      <Dialog open={!!preview} onOpenChange={(o) => !o && setPreview(null)}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Import {preview?.file.name}?</DialogTitle>
            <DialogDescription>
              {preview && `${preview.data.lines} lines from ${formatDay(preview.data.date_from)} to ${formatDay(preview.data.date_to)}: in ${rupees(preview.data.money_in)}, out ${rupees(preview.data.money_out)}${preview.data.closing_balance ? `, closing ${rupees(preview.data.closing_balance)}` : ''}.`}
              {preview && preview.data.already_imported > 0 && ` ${preview.data.already_imported} are already in and will be skipped.`}
            </DialogDescription>
          </DialogHeader>
          <ul className="max-h-60 divide-y overflow-y-auto rounded-lg border text-xs">
            {preview?.data.sample.map((s, i) => (
              <li key={i} className="flex gap-3 px-3 py-1.5">
                <span className="w-20 shrink-0 text-muted-foreground">{formatDay(s.date)}</span>
                <span className="min-w-0 flex-1 truncate">{s.description}</span>
                <span className="tabular-nums">{Number(s.amount) > 0 ? '+' : '−'}{rupees(s.amount)}</span>
              </li>
            ))}
          </ul>
          <p className="text-xs text-muted-foreground">Check the first lines read right (dates, in and out). The columns are remembered for this account's next statement.</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPreview(null)}>Cancel</Button>
            <Button onClick={() => save.mutate()} disabled={save.isPending || !preview?.data.new}>{save.isPending ? 'Importing…' : `Import ${preview?.data.new ?? 0} lines`}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

/** What the bank has and Mesiri does not: the ledger it goes to (bank charges and interest first). */
function BookDialog({ line, onClose, onBook, busy }: { line: BankLine | null; onClose: () => void; onBook: (ledgerId: string) => void; busy: boolean }) {
  const chart = useQuery({ queryKey: ['accounts', 'chart'], queryFn: fetchChart, enabled: !!line })
  const [ledger, setLedger] = React.useState('')
  React.useEffect(() => setLedger(''), [line])
  const ledgers = (chart.data?.ledgers ?? []).filter((l) => l.is_active && l.link_kind !== 'money_account')
  const quick = ledgers.filter((l) => (Number(line?.amount) > 0 ? ['bank_interest'] : ['bank_charges']).includes(l.code ?? ''))
  const groups = new Map((chart.data?.groups ?? []).map((g) => [g.id, g.name]))
  return (
    <Dialog open={!!line} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Book {line ? rupees(line.amount) : ''} {Number(line?.amount) > 0 ? 'received' : 'paid'}</DialogTitle>
          <DialogDescription>{line?.description}. It is recorded in Finance › Money on this account and posted to the ledger you pick.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-wrap gap-1.5">
          {quick.map((l) => (
            <Button key={l.id} size="sm" variant={ledger === l.id ? 'default' : 'outline'} onClick={() => setLedger(l.id)}>{l.name}</Button>
          ))}
        </div>
        <Combobox options={ledgers.map((l) => ({ value: l.id, label: `${l.name} · ${groups.get(l.group_id) ?? ''}` }))} value={ledger} onValueChange={setLedger} placeholder="Or another ledger (a supplier, a client …)" searchPlaceholder="Type a ledger" />
        <p className="text-xs text-muted-foreground">A payment to a supplier or from a client you forgot to record is better recorded in Finance or Receivables, then matched: it then shows on their account too.</p>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button disabled={!ledger || busy} onClick={() => onBook(ledger)}>{busy ? 'Booking…' : 'Book it'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
