import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { HandCoins, Landmark, ReceiptText, Undo2 } from 'lucide-react'
import { BooksLink } from '@/components/accounts/books'
import { ReceiveMoneyDialog } from '@/components/billing/receive-money-dialog'
import { DprHeader, DprSection, PageError, StatStrip } from '@/components/dpr-page'
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

// NXT-03: what each client owes, most first, by age; the open bills with what came against them; money received,
// newest first, with a way to take one back. Owner, admin and finance only (D-N3). Backend: GET /billing/receivables,
// GET / POST /billing/receipts.

function formatDay(iso: string): string {
  const d = new Date(`${iso}T00:00:00`)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
}

const KIND_WORD = { bill: 'for', on_account: 'on account', advance: 'advance' } as const

export default function ReceivablesPage() {
  const { me } = useAuth()
  const toast = useToast()
  const qc = useQueryClient()
  usePageTitle('Receivables')
  const allowed = mayManageMoney(me?.role)
  const owed = useQuery({ queryKey: ['billing', 'receivables'], queryFn: fetchReceivables, enabled: allowed })
  const receipts = useQuery({ queryKey: ['billing', 'receipts'], queryFn: fetchClientReceipts, enabled: allowed })
  const [dialog, setDialog] = React.useState<{ open: boolean; bill: OpenBill | null }>({ open: false, bill: null })
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
      <div className="mx-auto flex w-full max-w-md flex-col items-center gap-3 py-16 text-center">
        <p className="font-medium">Receivables show what clients owe the company.</p>
        <p className="text-sm text-muted-foreground">Only the owner, an admin or finance can open it.</p>
      </div>
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
        date="What clients owe"
        action={
          <div className="flex items-center gap-2">
            <BooksLink to="/accounts/ledgers?kind=client" label="Client ledgers" className="hidden sm:inline-flex" />
            <Button size="sm" className="gap-1.5" onClick={() => setDialog({ open: true, bill: null })}>
              <HandCoins className="size-4" /> Money received
            </Button>
          </div>
        }
      />
      {owed.isLoading || !d ? (
        <Skeleton className="h-48 rounded-lg" />
      ) : (
        <>
          <StatStrip
            stats={[
              { label: 'Clients owe', value: formatRupees(d.outstanding), icon: Landmark, tone: Number(d.outstanding) > 0 ? 'warn' : 'good' },
              ...(Object.keys(BUCKET_LABEL) as Bucket[]).map((b) => ({
                label: BUCKET_LABEL[b],
                value: formatRupees(d.buckets[b]),
                tone: (b === '90_plus' || b === '61_90') && Number(d.buckets[b]) > 0 ? ('bad' as const) : ('default' as const),
              })),
            ]}
          />
          <DprSection icon={ReceiptText} title="Clients, most owed first" meta={d.clients.length || undefined}>
            {d.clients.length === 0 ? (
              <p className="rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground">
                No RA bill has been sent to a client yet. Bills sent from Client billing › RA bills show here until they are paid.
              </p>
            ) : (
              <ul className="flex flex-col gap-3">
                {d.clients.map((c) => (
                  <li key={c.client_id ?? c.client} className="rounded-lg border">
                    <div className="flex flex-col gap-1 border-b px-4 py-3 sm:flex-row sm:items-baseline sm:justify-between">
                      <p className="font-medium">{c.client}</p>
                      <p className={cn('text-sm font-semibold tabular-nums', Number(c.outstanding) > 0 ? 'text-draft' : 'text-success')}>
                        {Number(c.outstanding) > 0 ? `${formatRupees(c.outstanding)} owed` : 'Nothing owed'}
                      </p>
                    </div>
                    {c.open_bills.length > 0 && (
                      <ul className="divide-y">
                        {c.open_bills.map((b) => (
                          <li key={b.id} className="flex flex-col gap-2 px-4 py-2.5 text-sm sm:flex-row sm:items-center sm:gap-4">
                            <div className="min-w-0 flex-1">
                              <p className="font-medium">
                                {b.ref} <span className="font-normal text-muted-foreground">· {b.project}</span>
                              </p>
                              <p className="text-xs text-muted-foreground tabular-nums">
                                {formatDay(b.bill_date)} · {b.days} days · bill {formatRupees(b.due)} · received {formatRupees(b.received)}
                              </p>
                            </div>
                            <span className={cn('font-semibold tabular-nums', b.days > 60 ? 'text-destructive' : '')}>{formatRupees(b.left)} left</span>
                            <Button size="sm" variant="outline" onClick={() => setDialog({ open: true, bill: b })}>
                              Received
                            </Button>
                          </li>
                        ))}
                      </ul>
                    )}
                    {(Number(c.unapplied) > 0 || Number(c.advance_received) > 0 || c.last_received_on) && (
                      <p className="border-t px-4 py-2 text-xs text-muted-foreground">
                        {[
                          Number(c.unapplied) > 0 ? `${formatRupees(c.unapplied)} received, not on a bill yet` : null,
                          Number(c.advance_received) > 0 ? `${formatRupees(c.advance_received)} mobilisation advance (recovered through the bills)` : null,
                          c.last_received_on ? `last received ${formatDay(c.last_received_on)}` : null,
                        ]
                          .filter(Boolean)
                          .join(' · ')}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </DprSection>
        </>
      )}
      <DprSection icon={HandCoins} title="Money received" meta={receipts.data?.length || undefined}>
        {receipts.isLoading ? (
          <Skeleton className="h-24 rounded-lg" />
        ) : (receipts.data ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground">Nothing recorded yet.</p>
        ) : (
          <ul className="divide-y rounded-lg border text-sm">
            {receipts.data!.map((r) => (
              <li key={r.id} className={cn('flex flex-col gap-1 px-4 py-2.5 sm:flex-row sm:items-center sm:gap-4', r.status === 'cancelled' && 'text-muted-foreground line-through')}>
                <div className="min-w-0 flex-1">
                  <p className="font-medium tabular-nums">
                    {formatRupees(r.amount)} <span className="font-normal text-muted-foreground">{KIND_WORD[r.kind]} {r.kind === 'bill' ? r.bill_ref : ''}</span>
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {formatDay(r.received_on)} · {r.client ?? 'No client set'} · {r.project} · into {r.account}
                    {r.reference ? ` · ${r.reference}` : ''}
                  </p>
                </div>
                {r.status === 'confirmed' ? (
                  <Button size="sm" variant="ghost" className="gap-1.5" disabled={takeBack.isPending} onClick={() => takeBack.mutate(r.id)}>
                    <Undo2 className="size-3.5" /> Take back
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
