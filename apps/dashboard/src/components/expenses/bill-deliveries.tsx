import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link2, PackageCheck, TriangleAlert, Unlink } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { apiErrorMessage } from '@/lib/logo-upload'
import { rupees } from '@/lib/expenses'
import { cn } from '@/lib/utils'
import { billDeliveryList, day, fetchLedger, matchDeliveries, num, unmatchDelivery, vendorUrl } from '@/lib/vendors'

// PRC-11: a supplier's bill (an expense with a supplier) and the deliveries the site recorded for it. What is on it,
// with anything the bill says differently (more than delivered, another rate); a delivery put on it by mistake can be
// taken off; and when nothing is on it yet, the supplier's deliveries with no bill in that project, to tick and put on
// it -- so a delivery and its bill are owed and counted once.

export function BillDeliveries({ expenseId, vendorId, vendorName, projectId, amount, canManage, hideList }: {
  expenseId: string
  vendorId: string
  vendorName: string
  projectId: string | null | undefined
  amount: number
  canManage: boolean
  /** The bill's own lines are shown above (a material bill): only flags and the change actions here. */
  hideList?: boolean
}) {
  const queryClient = useQueryClient()
  const on = useQuery({ queryKey: ['finance', 'bill-deliveries', expenseId], queryFn: () => billDeliveryList(vendorId, expenseId), retry: false })
  const waiting = useQuery({
    queryKey: ['finance', 'ledger', vendorId, projectId ?? '', 'all'],
    queryFn: () => fetchLedger(vendorId, { project_id: projectId ?? undefined }),
    enabled: canManage && on.isSuccess && on.data.length === 0,
  })
  const [picked, setPicked] = React.useState<string[]>([])
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['finance'] })
  const link = useMutation({ mutationFn: () => matchDeliveries(vendorId, expenseId, picked), onSuccess: () => { setPicked([]); refresh() } })
  const unlink = useMutation({ mutationFn: (rid: string) => unmatchDelivery(vendorId, expenseId, rid), onSuccess: refresh })

  if (on.isError || !on.data) return null
  const rows = on.data
  const flagged = rows.filter((r) => r.flags.length)
  const unbilled = (waiting.data?.unbilled ?? []).filter((d) => !projectId || d.project_id === projectId)
  const pickedTotal = unbilled.filter((d) => picked.includes(d.links.receipt_id!)).reduce((n, d) => n + num(d.owe), 0)

  if (rows.length === 0 && unbilled.length === 0) return null

  return (
    <section className="flex flex-col gap-2">
      <h3 className="flex items-center gap-2 font-semibold">
        <PackageCheck className="size-4 text-muted-foreground" aria-hidden="true" /> Deliveries on this bill
      </h3>
      {flagged.length > 0 && (
        <div className="flex flex-col gap-1 rounded-lg border border-draft/30 bg-draft-soft px-3 py-2 text-sm text-draft">
          {flagged.map((r) => (
            <span key={r.receipt_id} className="flex items-start gap-1.5">
              <TriangleAlert className="mt-0.5 size-4 shrink-0" />
              <span>{r.material} ({day(r.date)}): {r.flags.join('; ')}.</span>
            </span>
          ))}
        </div>
      )}
      {rows.length > 0 && !hideList && (
        <ul className="divide-y rounded-lg border text-sm">
          {rows.map((r) => (
            <li key={r.receipt_id} className="flex items-center gap-2 px-3 py-1.5">
              <span className="w-14 shrink-0 text-xs text-muted-foreground">{day(r.date)}</span>
              <span className="min-w-0 flex-1 truncate">{r.quantity} {r.unit} {r.material}{r.site ? ` · ${r.site}` : ''}</span>
              {r.amount && <span className="tabular-nums">{rupees(num(r.amount))}</span>}
              {canManage && (
                <Button size="icon" variant="ghost" className="size-7 text-muted-foreground" title="Not on this bill" aria-label={`Take ${r.material} off this bill`} disabled={unlink.isPending} onClick={() => unlink.mutate(r.receipt_id)}>
                  <Unlink className="size-3.5" />
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {rows.length === 0 && canManage && unbilled.length > 0 && (
        <div className="flex flex-col gap-2 rounded-lg border border-sky-200 bg-sky-50/60 p-3 text-sm dark:border-sky-900 dark:bg-sky-950/30">
          <p>{vendorName} has {unbilled.length} {unbilled.length === 1 ? 'delivery' : 'deliveries'} with no bill here. Tick the ones on this bill, so they are not owed and counted twice.</p>
          <ul className="max-h-44 divide-y overflow-y-auto rounded-md border bg-background">
            {unbilled.map((d) => {
              const id = d.links.receipt_id!
              return (
                <li key={id}>
                  <label className="flex cursor-pointer items-center gap-2 px-2.5 py-1.5">
                    <input type="checkbox" className="size-4 accent-primary" checked={picked.includes(id)} onChange={() => setPicked((x) => (x.includes(id) ? x.filter((y) => y !== id) : [...x, id]))} />
                    <span className="w-14 shrink-0 text-xs text-muted-foreground">{day(d.date)}</span>
                    <span className="min-w-0 flex-1 truncate">{d.title}{d.site ? ` · ${d.site}` : ''}</span>
                    <span className="tabular-nums">{rupees(num(d.owe))}</span>
                  </label>
                </li>
              )
            })}
          </ul>
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" className="gap-1.5" disabled={!picked.length || link.isPending} onClick={() => link.mutate()}>
              <Link2 className="size-4" /> Put {picked.length || ''} on this bill
            </Button>
            {picked.length > 0 && (
              <span className={cn('text-xs', Math.abs(pickedTotal - amount) < 1 ? 'text-success' : 'text-muted-foreground')}>
                {rupees(pickedTotal)} at the site's rates{Math.abs(pickedTotal - amount) >= 1 ? ` · bill ${rupees(amount)}` : ' · same as the bill'}
              </span>
            )}
            <Link to={vendorUrl(vendorId, 'unbilled')} className="ml-auto text-xs font-semibold underline-offset-2 hover:underline">All of {vendorName}'s</Link>
          </div>
          {link.isError && <p className="text-destructive">{apiErrorMessage(link.error)}</p>}
        </div>
      )}
      {unlink.isError && <p className="text-sm text-destructive">{apiErrorMessage(unlink.error)}</p>}
    </section>
  )
}
