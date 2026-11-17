import * as React from 'react'
import { BOOKS_PEOPLE } from '@/lib/permissions'
import { NoAccess } from '@/components/page/page-kit'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDownLeft, HandCoins, ReceiptText, Search } from 'lucide-react'
import { BooksLink } from '@/components/accounts/books'
import { ReceiveMoneyDialog } from '@/components/billing/receive-money-dialog'
import { AgeingCard, DaysPill, PartyAvatar } from '@/components/accounts/money-kit'
import { AGE_BARS } from '@/components/accounts/money-look'
import { DprHeader, DprSection, PageError } from '@/components/dpr-page'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast-notification'
import { useAuth } from '@/lib/AuthContext'
import { formatRupees } from '@/lib/boq'
import { mayManageMoney } from '@/lib/cost'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import { BUCKET_LABEL, cancelClientReceipt, fetchClientReceipts, fetchReceivables, type Bucket, type OpenBill } from '@/lib/receivables'
import { cn } from '@/lib/utils'
import { ActionIcon } from '@/components/page/action-button'

// NXT-03: what each client owes, most first, by age; the open bills with what came against them; money received,
// newest first, with a way to take one back. Owner, admin and finance only (D-N3). Backend: GET /billing/receivables,
// GET / POST /billing/receipts.
// UX-34 (Mercon's receivables ageing as the reference): one card says what clients owe and for how long, its bar's
// parts filtering the clients; each client a card with its own age bar, its share of all that is owed and its open
// bills (age as a coloured pill, how much of each bill came in as a bar); money received in green, newest first.

function formatDay(iso: string): string {
  const d = new Date(`${iso}T00:00:00`)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
}

const KIND_WORD = { bill: 'for', on_account: 'on account', advance: 'advance' } as const
const BUCKETS: Bucket[] = ['0_30', '31_60', '61_90', '90_plus']
const AGE_BAR: Record<Bucket, string> = { '0_30': AGE_BARS[0], '31_60': AGE_BARS[1], '61_90': AGE_BARS[2], '90_plus': AGE_BARS[3] }

export default function ReceivablesPage() {
  const { me } = useAuth()
  const toast = useToast()
  const qc = useQueryClient()
  usePageTitle('Receivables')
  const allowed = mayManageMoney(me?.role)
  const owed = useQuery({ queryKey: ['billing', 'receivables'], queryFn: fetchReceivables, enabled: allowed })
  const receipts = useQuery({ queryKey: ['billing', 'receipts'], queryFn: fetchClientReceipts, enabled: allowed })
  const [dialog, setDialog] = React.useState<{ open: boolean; bill: OpenBill | null }>({ open: false, bill: null })
  const [age, setAge] = React.useState<Bucket | null>(null)
  const [find, setFind] = React.useState('')
  const takeBack = useMutation({
    mutationFn: cancelClientReceipt,
    onSuccess: () => {
      toast.success('Receipt taken back')
      qc.invalidateQueries({ queryKey: ['billing'] })
    },
    onError: (err: unknown) => toast.error('Could not take it back', apiErrorMessage(err)),
  })

  if (!allowed) {
    return (
      <NoAccess roles={BOOKS_PEOPLE} />
    )
  }
  if (owed.isError) return <PageError message="Receivables could not be loaded." onRetry={() => owed.refetch()} back={{ to: '/billing/ra-bills', label: 'RA bills' }} />
  const d = owed.data
  const openBills = d ? d.clients.flatMap((c) => c.open_bills) : []

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader
        back={{ to: '/billing/ra-bills', label: 'RA bills' }}
        crumb="Accounts"
        title="Receivables"
        action={
          <div className="flex items-center gap-2">
            <BooksLink to="/accounts/ledgers?kind=client" label="Client ledgers" className="hidden sm:inline-flex" />
            <Button data-guide="recv.record" size="sm" className="gap-1.5" onClick={() => setDialog({ open: true, bill: null })}>
              <HandCoins className="size-4" /> Money received
            </Button>
          </div>
        }
      />
      {owed.isLoading || !d ? (
        <Skeleton className="h-48 rounded-lg" />
      ) : (
        <>
          <AgeingCard
            guide="recv.stats"
            title="Clients owe you"
            total={Number(d.outstanding)}
            totalHint={`on RA bills sent, as on ${formatDay(d.date)}`}
            buckets={BUCKETS.map((b) => ({ key: b, label: BUCKET_LABEL[b], value: Number(d.buckets[b]), bar: AGE_BAR[b], late: b === '61_90' || b === '90_plus' }))}
            active={age}
            onPick={(k) => setAge(k as Bucket | null)}
            aside={(() => {
              const late = Number(d.buckets['61_90']) + Number(d.buckets['90_plus'])
              const unapplied = d.clients.reduce((t, c) => t + Number(c.unapplied), 0)
              const total = Number(d.outstanding)
              return (
                <>
                  <span className={cn('rounded-lg border px-3 py-1.5 text-xs', late > 0 ? 'border-destructive/30 bg-destructive/[0.05]' : 'bg-muted/40')}>
                    <span className="block text-muted-foreground">Waiting over 60 days</span>
                    <span className={cn('text-sm font-semibold tabular-nums', late > 0 && 'text-destructive')}>
                      {formatRupees(String(late))}
                      {total > 0 && <span className="ml-1 text-xs font-normal">{Math.round((late / total) * 100)}%</span>}
                    </span>
                  </span>
                  {unapplied > 0 && (
                    <span className="rounded-lg border bg-info-soft/40 px-3 py-1.5 text-xs">
                      <span className="block text-muted-foreground">Received, not on a bill</span>
                      <span className="text-sm font-semibold tabular-nums text-info">{formatRupees(String(unapplied))}</span>
                    </span>
                  )}
                  <span className="rounded-lg border bg-muted/40 px-3 py-1.5 text-xs">
                    <span className="block text-muted-foreground">Clients owing</span>
                    <span className="text-sm font-semibold tabular-nums">{d.clients.filter((c) => Number(c.outstanding) > 0).length}</span>
                  </span>
                </>
              )
            })()}
          />
          <section data-guide="recv.clients" className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2 px-1">
              <h2 className="flex items-center gap-2 text-base font-semibold">
                <ReceiptText className="size-4 text-muted-foreground" /> Clients, most owed first
                {age && (
                  <button type="button" onClick={() => setAge(null)} className="rounded-full bg-muted px-2 py-0.5 text-xs font-normal text-muted-foreground hover:text-foreground">
                    {BUCKET_LABEL[age]} ✕
                  </button>
                )}
              </h2>
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-2 size-4 text-muted-foreground" />
                <Input value={find} onChange={(e) => setFind(e.target.value)} placeholder="Client, bill or project" aria-label="Search clients" className="h-8 w-[220px] bg-card pl-8" />
              </div>
            </div>
            {d.clients.length === 0 ? (
              <p className="rounded-xl border border-dashed bg-card px-4 py-6 text-sm text-muted-foreground">No RA bill sent yet</p>
            ) : (
              (() => {
                const needle = find.trim().toLowerCase()
                const total = Number(d.outstanding) || 1
                const shown = d.clients
                  .filter((c) => !age || Number(c.buckets[age]) > 0)
                  .filter((c) => !needle || [c.client, ...c.open_bills.map((b) => `${b.ref} ${b.project ?? ''}`)].join(' ').toLowerCase().includes(needle))
                if (shown.length === 0) return <p className="rounded-xl border border-dashed bg-card px-4 py-6 text-sm text-muted-foreground">No client matches.</p>
                return shown.map((c) => {
                  const out = Number(c.outstanding)
                  const sum = BUCKETS.reduce((t, b) => t + Number(c.buckets[b]), 0) || 1
                  const bills = c.open_bills.filter((b) => !age || b.bucket === age)
                  return (
                    <div key={c.client_id ?? c.client} className="overflow-hidden rounded-xl border bg-card shadow-xs">
                      <div className="flex flex-wrap items-center gap-3 px-4 py-3">
                        <PartyAvatar name={c.client} />
                        <div className="min-w-0 flex-1">
                          <p className="truncate font-semibold">{c.client}</p>
                          <p className="text-xs text-muted-foreground">
                            {c.open_bills.length} open {c.open_bills.length === 1 ? 'bill' : 'bills'}
                            {c.last_received_on ? ` · last received ${formatDay(c.last_received_on)}` : ''}
                          </p>
                        </div>
                        <div className="flex w-full flex-col gap-1 sm:w-56">
                          <div className="flex h-2 w-full gap-0.5 overflow-hidden rounded-full bg-muted">
                            {BUCKETS.filter((b) => Number(c.buckets[b]) > 0).map((b) => (
                              <span key={b} title={`${BUCKET_LABEL[b]}: ${formatRupees(c.buckets[b])}`} className={cn('h-full first:rounded-l-full last:rounded-r-full', AGE_BAR[b])} style={{ width: `${(Number(c.buckets[b]) / sum) * 100}%` }} />
                            ))}
                          </div>
                          <span className="text-[11px] text-muted-foreground">{out > 0 ? `${Math.round((out / total) * 100)}% of all that is owed` : 'Nothing owed'}</span>
                        </div>
                        <p className={cn('ml-auto text-lg font-semibold tabular-nums', out > 0 ? 'text-draft' : 'text-success')}>{out > 0 ? formatRupees(c.outstanding) : 'Settled'}</p>
                      </div>
                      {bills.length > 0 && (
                        <ul className="divide-y border-t">
                          {bills.map((b) => {
                            const got = Number(b.due) > 0 ? Math.min(1, Number(b.received) / Number(b.due)) : 0
                            return (
                              <li key={b.id} className="flex flex-col gap-2 px-4 py-2.5 text-sm sm:flex-row sm:items-center sm:gap-4">
                                <div className="min-w-0 flex-1">
                                  <p className="flex flex-wrap items-center gap-2 font-medium">
                                    {b.ref} <span className="font-normal text-muted-foreground">· {b.project}</span> <DaysPill days={b.days} />
                                  </p>
                                  <div className="mt-1 flex items-center gap-2">
                                    <span className="h-1.5 w-28 overflow-hidden rounded-full bg-muted">
                                      <span className="block h-full rounded-full bg-emerald-500" style={{ width: `${got * 100}%` }} />
                                    </span>
                                    <span className="text-xs tabular-nums text-muted-foreground">
                                      {formatDay(b.bill_date)} · {formatRupees(b.received)} of {formatRupees(b.due)} received ({Math.round(got * 100)}%)
                                    </span>
                                  </div>
                                </div>
                                <span className={cn('font-semibold tabular-nums', b.days > 60 ? 'text-destructive' : '')}>{formatRupees(b.left)} left</span>
                                <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setDialog({ open: true, bill: b })}>
                                  <ArrowDownLeft className="size-3.5 text-emerald-600" /> Received
                                </Button>
                              </li>
                            )
                          })}
                        </ul>
                      )}
                      {(Number(c.unapplied) > 0 || Number(c.advance_received) > 0) && (
                        <p className="border-t bg-muted/30 px-4 py-2 text-xs text-muted-foreground">
                          {[
                            Number(c.unapplied) > 0 ? `${formatRupees(c.unapplied)} received, not on a bill yet` : null,
                            Number(c.advance_received) > 0 ? `${formatRupees(c.advance_received)} mobilisation advance (recovered through the bills)` : null,
                          ]
                            .filter(Boolean)
                            .join(' · ')}
                        </p>
                      )}
                    </div>
                  )
                })
              })()
            )}
          </section>
        </>
      )}
      <DprSection icon={HandCoins} title="Money received" meta={receipts.data?.length || undefined}>
        {receipts.isLoading ? (
          <Skeleton className="h-24 rounded-lg" />
        ) : (receipts.data ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground">Nothing recorded yet.</p>
        ) : (
          <ul data-guide="recv.received" className="divide-y rounded-xl border bg-card text-sm shadow-xs">
            {receipts.data!.map((r) => (
              <li key={r.id} className={cn('flex flex-col gap-1 px-4 py-2.5 sm:flex-row sm:items-center sm:gap-4', r.status === 'cancelled' && 'text-muted-foreground line-through')}>
                <span className={cn('hidden size-8 shrink-0 items-center justify-center rounded-lg sm:flex', r.status === 'cancelled' ? 'bg-muted' : 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400')}>
                  <ArrowDownLeft className="size-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="font-medium tabular-nums">
                    <span className={cn(r.status !== 'cancelled' && 'text-emerald-700 dark:text-emerald-400')}>{formatRupees(r.amount)}</span> <span className="font-normal text-muted-foreground">{KIND_WORD[r.kind]} {r.kind === 'bill' ? r.bill_ref : ''}</span>
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {formatDay(r.received_on)} · {r.client ?? 'No client set'} · {r.project} · into {r.account}
                    {r.reference ? ` · ${r.reference}` : ''}
                  </p>
                </div>
                {r.status === 'confirmed' ? (
                  <Button size="sm" variant="ghost" className="gap-1.5" disabled={takeBack.isPending} onClick={() => takeBack.mutate(r.id)}>
                    <ActionIcon kind="undo" className="size-3.5" /> Take back
                  </Button>
                ) : (
                  <span className="text-xs">Taken back</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </DprSection>
      <ReceiveMoneyDialog open={dialog.open} onOpenChange={(o) => setDialog((s) => ({ ...s, open: o }))} bills={openBills} preselect={dialog.bill} />
    </div>
  )
}
