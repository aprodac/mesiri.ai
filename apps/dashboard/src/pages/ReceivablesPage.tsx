import * as React from 'react'
import { BOOKS_PEOPLE } from '@/lib/permissions'
import { NoAccess } from '@/components/page/page-kit'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDownLeft, HandCoins, ReceiptText, Search } from 'lucide-react'
import { BooksLink } from '@/components/accounts/books'
import { ReceiveMoneyDialog } from '@/components/billing/receive-money-dialog'
import { PaymentAlertsCallout } from '@/components/billing/payment-stages'
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
// UXA-05 (Mercon's receivables ageing as the reference): one card says what clients owe and for how long, its bar's
// parts filtering the clients; then one table (UXA-06): a band per client (its age bar, its share of all that is owed,
// its total) and a row per open bill (date, age as a coloured pill, billed, received with its bar, left); money
// received as a table too, in green, newest first.

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
      <PaymentAlertsCallout />
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
                return (
                  <div className="overflow-hidden rounded-xl border bg-card shadow-xs">
                    <div className="overflow-x-auto">
                      <table className="w-full min-w-[760px] text-sm">
                        <thead>
                          <tr className="border-b bg-muted text-xs text-muted-foreground">
                            <th className="px-3 py-2 text-left font-medium">Client / bill</th>
                            <th className="px-3 py-2 text-left font-medium">Billed on</th>
                            <th className="px-3 py-2 text-left font-medium">Waiting</th>
                            <th className="px-3 py-2 text-right font-medium">Billed</th>
                            <th className="px-3 py-2 text-left font-medium">Received</th>
                            <th className="px-3 py-2 text-right font-medium">Left</th>
                            <th className="w-28 px-3 py-2" />
                          </tr>
                        </thead>
                        {shown.map((c) => {
                          const out = Number(c.outstanding)
                          const sum = BUCKETS.reduce((t, b) => t + Number(c.buckets[b]), 0) || 1
                          const bills = c.open_bills.filter((b) => !age || b.bucket === age)
                          return (
                            <tbody key={c.client_id ?? c.client} className="border-b last:border-b-0">
                              <tr className="bg-muted/40">
                                <td colSpan={3} className="px-3 py-2.5">
                                  <span className="flex items-center gap-3">
                                    <PartyAvatar name={c.client} className="size-8" />
                                    <span className="min-w-0">
                                      <span className="block truncate font-semibold">{c.client}</span>
                                      <span className="block text-xs text-muted-foreground">
                                        {c.open_bills.length} open {c.open_bills.length === 1 ? 'bill' : 'bills'}
                                        {c.last_received_on ? ` · last received ${formatDay(c.last_received_on)}` : ''}
                                      </span>
                                    </span>
                                  </span>
                                </td>
                                <td colSpan={2} className="px-3 py-2.5">
                                  <span className="flex flex-col gap-1">
                                    <span className="flex h-2 w-full max-w-56 gap-0.5 overflow-hidden rounded-full bg-muted">
                                      {BUCKETS.filter((b) => Number(c.buckets[b]) > 0).map((b) => (
                                        <span key={b} title={`${BUCKET_LABEL[b]}: ${formatRupees(c.buckets[b])}`} className={cn('h-full first:rounded-l-full last:rounded-r-full', AGE_BAR[b])} style={{ width: `${(Number(c.buckets[b]) / sum) * 100}%` }} />
                                      ))}
                                    </span>
                                    <span className="text-[11px] text-muted-foreground">{out > 0 ? `${Math.round((out / total) * 100)}% of all that is owed` : 'Nothing owed'}</span>
                                  </span>
                                </td>
                                <td colSpan={2} className={cn('px-3 py-2.5 text-right text-base font-semibold tabular-nums', out > 0 ? 'text-draft' : 'text-success')}>
                                  {out > 0 ? formatRupees(c.outstanding) : 'Settled'}
                                </td>
                              </tr>
                              {bills.map((b) => {
                                const got = Number(b.due) > 0 ? Math.min(1, Number(b.received) / Number(b.due)) : 0
                                return (
                                  <tr key={b.id} className="border-t border-border/60 hover:bg-muted/30">
                                    <td className="py-2.5 pl-14 pr-3">
                                      <span className="font-medium">{b.ref}</span> <span className="text-muted-foreground">· {b.project}</span>
                                    </td>
                                    <td className="whitespace-nowrap px-3 py-2.5 tabular-nums text-muted-foreground">{formatDay(b.bill_date)}</td>
                                    <td className="px-3 py-2.5">
                                      <DaysPill days={b.days} />
                                    </td>
                                    <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums">{formatRupees(b.due)}</td>
                                    <td className="px-3 py-2.5">
                                      <span className="flex items-center gap-2">
                                        <span className="h-1.5 w-16 shrink-0 overflow-hidden rounded-full bg-muted">
                                          <span className="block h-full rounded-full bg-emerald-500" style={{ width: `${got * 100}%` }} />
                                        </span>
                                        <span className="whitespace-nowrap tabular-nums text-emerald-700 dark:text-emerald-400">{formatRupees(b.received)}</span>
                                        <span className="text-xs text-muted-foreground">{Math.round(got * 100)}%</span>
                                      </span>
                                    </td>
                                    <td className={cn('whitespace-nowrap px-3 py-2.5 text-right font-semibold tabular-nums', b.days > 60 && 'text-destructive')}>{formatRupees(b.left)}</td>
                                    <td className="px-3 py-2 text-right">
                                      <Button size="sm" variant="outline" className="h-7 gap-1 px-2 text-xs" onClick={() => setDialog({ open: true, bill: b })}>
                                        <ArrowDownLeft className="size-3.5 text-emerald-600" /> Received
                                      </Button>
                                    </td>
                                  </tr>
                                )
                              })}
                              {(Number(c.unapplied) > 0 || Number(c.advance_received) > 0) && (
                                <tr className="border-t border-border/60">
                                  <td colSpan={7} className="py-2 pl-14 pr-3 text-xs text-muted-foreground">
                                    {[
                                      Number(c.unapplied) > 0 ? `${formatRupees(c.unapplied)} received, not on a bill yet` : null,
                                      Number(c.advance_received) > 0 ? `${formatRupees(c.advance_received)} mobilisation advance (recovered through the bills)` : null,
                                    ]
                                      .filter(Boolean)
                                      .join(' · ')}
                                  </td>
                                </tr>
                              )}
                            </tbody>
                          )
                        })}
                        <tfoot>
                          <tr className="border-t-[1.5px] border-foreground/25 bg-muted/30 font-semibold">
                            <td colSpan={5} className="px-3 py-2.5">
                              {age || needle ? 'Shown' : 'All clients'} <span className="font-normal text-muted-foreground">· {shown.length} {shown.length === 1 ? 'client' : 'clients'}</span>
                            </td>
                            <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums text-draft">
                              {formatRupees(String(shown.reduce((t, c) => t + (age ? Number(c.buckets[age]) : Number(c.outstanding)), 0)))}
                            </td>
                            <td />
                          </tr>
                        </tfoot>
                      </table>
                    </div>
                  </div>
                )
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
          <div data-guide="recv.received" className="overflow-hidden rounded-xl border bg-card shadow-xs">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-sm">
                <thead>
                  <tr className="border-b bg-muted text-xs text-muted-foreground">
                    <th className="px-3 py-2 text-left font-medium">Date</th>
                    <th className="px-3 py-2 text-left font-medium">Client</th>
                    <th className="px-3 py-2 text-left font-medium">For</th>
                    <th className="px-3 py-2 text-left font-medium">Into</th>
                    <th className="px-3 py-2 text-right font-medium">Amount</th>
                    <th className="w-28 px-3 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {receipts.data!.map((r) => {
                    const gone = r.status === 'cancelled'
                    return (
                      <tr key={r.id} className={cn('border-t border-border/60 first:border-t-0', gone && 'text-muted-foreground line-through')}>
                        <td className="whitespace-nowrap px-3 py-2.5 tabular-nums">{formatDay(r.received_on)}</td>
                        <td className="px-3 py-2.5">
                          <span className="block font-medium">{r.client ?? 'No client set'}</span>
                          <span className="block text-xs text-muted-foreground">{r.project}</span>
                        </td>
                        <td className="px-3 py-2.5">{KIND_WORD[r.kind]} {r.kind === 'bill' ? r.bill_ref : ''}</td>
                        <td className="px-3 py-2.5">
                          {r.account}
                          {r.reference && <span className="block text-xs text-muted-foreground">{r.reference}</span>}
                        </td>
                        <td className={cn('whitespace-nowrap px-3 py-2.5 text-right font-semibold tabular-nums', !gone && 'text-emerald-700 dark:text-emerald-400')}>
                          <span className="inline-flex items-center gap-1">
                            {!gone && <ArrowDownLeft className="size-3.5" />}
                            {formatRupees(r.amount)}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-right">
                          {r.status === 'confirmed' ? (
                            <Button size="sm" variant="ghost" className="h-7 gap-1 px-2 text-xs" disabled={takeBack.isPending} onClick={() => takeBack.mutate(r.id)}>
                              <ActionIcon kind="undo" className="size-3.5" /> Take back
                            </Button>
                          ) : (
                            <span className="text-xs">Taken back</span>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </DprSection>
      <ReceiveMoneyDialog open={dialog.open} onOpenChange={(o) => setDialog((s) => ({ ...s, open: o }))} bills={openBills} preselect={dialog.bill} />
    </div>
  )
}
