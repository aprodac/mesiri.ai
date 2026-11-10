import * as React from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { PackageX, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/lib/AuthContext'
import { rupees } from '@/lib/orders'
import { RETURN_LOOK, fetchReturns, mayReturn, seesMoney } from '@/lib/returns'
import { cn } from '@/lib/utils'
import { NewReturnDialog } from './new-return-dialog'

// PRC-46: the supplier page's Returns tab: what went back to this supplier, its debit notes and where each stands;
// "Return material" starts one from their deliveries of the last 90 days.

export function VendorReturns({ vendorId, readOnly }: { vendorId: string; readOnly?: boolean }) {
  const { me } = useAuth()
  const navigate = useNavigate()
  const [starting, setStarting] = React.useState(false)
  const { data, isLoading } = useQuery({ queryKey: ['procurement', 'returns', 'vendor', vendorId], queryFn: () => fetchReturns({ vendor_id: vendorId }) })
  const items = data?.items ?? []
  const owed = data?.counts.owed_to_you
  return (
    <div className="flex flex-col gap-3 rounded-xl border bg-card p-3 sm:p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          {owed && Number(owed) > 0 ? <>On returns not settled yet, they owe you <strong className="text-foreground">{rupees(owed)}</strong> (already off their balance).</> : 'Material sent back to this supplier, with its debit note.'}
        </p>
        {mayReturn(me?.role) && !readOnly && (
          <Button size="sm" className="gap-1.5" onClick={() => setStarting(true)}><Plus className="size-3.5" /> Return material</Button>
        )}
      </div>
      {isLoading ? (
        <p className="py-4 text-sm text-muted-foreground">Loading…</p>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center gap-1 py-8 text-center text-sm text-muted-foreground"><PackageX className="size-6 opacity-40" />Nothing sent back to them yet.</div>
      ) : (
        <ul className="divide-y rounded-lg border">
          {items.map((r) => (
            <li key={r.id}>
              <Link to={`/procurement/returns?id=${r.id}`} className={cn('flex items-center gap-3 px-3 py-2.5 hover:bg-muted/40', r.status === 'cancelled' && 'opacity-60')}>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold">{r.ref} · {r.what}</span>
                  <span className="block truncate text-xs text-muted-foreground">{r.site_name} · {r.returned_on}</span>
                </span>
                {r.total && <span className="shrink-0 text-sm font-semibold tabular-nums">{rupees(r.total)}</span>}
                <span className={cn('shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold', RETURN_LOOK[r.status].chip)}>{RETURN_LOOK[r.status].label}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <NewReturnDialog open={starting} onOpenChange={setStarting} from={{ vendor_id: vendorId }} money={seesMoney(me?.role)} onCreated={(r) => navigate(`/procurement/returns?id=${r.id}`)} />
    </div>
  )
}
