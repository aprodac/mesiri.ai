import { Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { FileText, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Progress3 } from '@/components/subcontracts/parts'
import { rupees } from '@/lib/expenses'
import { cn } from '@/lib/utils'
import { WO_LOOK, fetchWorkOrders, n, woUrl } from '@/lib/subcontracts'
import { SubcontractorContacts } from '@/components/subcontracts/contacts'

// NXT-05/18: a subcontractor's work orders on its supplier page, with the statement one tap away.

export function VendorWorkOrders({ vendorId, vendorName, canManage = false }: { vendorId: string; vendorName: string; canManage?: boolean }) {
  const navigate = useNavigate()
  const q = useQuery({ queryKey: ['subcontracts', 'list', 'vendor', vendorId], queryFn: () => fetchWorkOrders({ vendor_id: vendorId }) })
  if (q.isLoading) return <Skeleton className="h-40 rounded-xl" />
  const list = q.data?.work_orders ?? []
  const money = !!q.data?.with_money
  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap justify-end gap-2">
        {money && <Button size="sm" variant="outline" className="gap-1" onClick={() => navigate(`/subcontract/statement/${vendorId}`)}><FileText className="size-4" /> Statement</Button>}
        <Button size="sm" className="gap-1" onClick={() => navigate(`/subcontract/work-orders?vendor=${vendorId}`)}><Plus className="size-4" /> Work orders</Button>
      </div>
      {!list.length ? (
        <p className="rounded-xl border border-dashed py-8 text-center text-sm text-muted-foreground">No work order for {vendorName} yet.</p>
      ) : (
        <ul className="divide-y rounded-xl border bg-card">
          {list.map((w) => (
            <li key={w.id}>
              <Link to={woUrl(w.id)} className="flex flex-wrap items-center gap-3 px-3 py-2.5 hover:bg-muted/30">
                <span className="w-20 font-semibold tabular-nums">{w.ref}</span>
                <span className={cn('rounded px-1.5 py-0.5 text-[11px] font-medium', WO_LOOK[w.status].chip)}>{WO_LOOK[w.status].label}</span>
                <span className="min-w-0 flex-1 truncate text-sm">{w.title || w.lines.map((l) => l.description).join(', ')} · {[w.project_name, w.site_name].filter(Boolean).join(' › ')}</span>
                <span className="w-40"><Progress3 done={Number(w.totals.progress_pct)} billed={w.totals.billed_pct ? Number(w.totals.billed_pct) : undefined} /></span>
                {money && <span className="w-24 text-right text-sm tabular-nums">{rupees(n(w.totals.value))}</span>}
                {w.totals.to_check > 0 && <span className="rounded bg-amber-100 px-1.5 text-xs text-amber-900 dark:bg-amber-950 dark:text-amber-100">{w.totals.to_check} to check</span>}
              </Link>
            </li>
          ))}
        </ul>
      )}
      <SubcontractorContacts vendorId={vendorId} vendorName={vendorName} canManage={canManage} />
    </section>
  )
}
