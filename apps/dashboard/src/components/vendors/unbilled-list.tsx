import * as React from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { CircleCheck, Download, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Callout } from '@/components/dpr-page'
import { rupees } from '@/lib/expenses'
import { exportCsv } from '@/lib/export'
import { cn } from '@/lib/utils'
import { day, fetchUnbilled, num, vendorUrl, type UnbilledDelivery } from '@/lib/vendors'

// PRC-11: every delivery the site recorded that has no bill yet, oldest first: what the office chases. Chips narrow
// it to deliveries that came without an order, with no supplier named, or with no rate. A supplier opens its Not billed
// tab (record their bill there, or put them on one typed earlier).

type Chip = 'all' | 'no_order' | 'no_supplier' | 'no_rate' | 'old'

export function UnbilledList({ projectId }: { projectId?: string }) {
  const q = useQuery({ queryKey: ['finance', 'unbilled', projectId ?? ''], queryFn: () => fetchUnbilled({ project_id: projectId }) })
  const [chip, setChip] = React.useState<Chip>('all')
  if (q.isError) return <Callout tone="draft" icon={TriangleAlert} action={<Button variant="outline" size="sm" className="bg-background" onClick={() => q.refetch()}>Try again</Button>}>The deliveries could not be loaded.</Callout>
  if (!q.data) return <Skeleton className="h-64 rounded-xl" />
  const all = q.data.deliveries
  const test: Record<Chip, (d: UnbilledDelivery) => boolean> = {
    all: () => true, no_order: (d) => !d.order_id, no_supplier: (d) => !d.supplier, no_rate: (d) => !d.amount, old: (d) => d.days > 15,
  }
  const chips: { value: Chip; label: string }[] = [
    { value: 'all', label: `All ${all.length}` },
    { value: 'old', label: `Over 15 days · ${all.filter(test.old).length}` },
    { value: 'no_order', label: `No order · ${q.data.totals.no_order}` },
    { value: 'no_rate', label: `No rate · ${q.data.totals.unpriced}` },
    { value: 'no_supplier', label: `No supplier · ${q.data.totals.no_supplier}` },
  ]
  const shown = all.filter(test[chip])
  if (!all.length) {
    return (
      <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center">
        <CircleCheck className="size-6 text-success" />
        <p className="text-sm font-medium">Every delivery is on a bill</p>
      </div>
    )
  }
  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-1.5">
          {chips.map((c) => (
            <button key={c.value} type="button" aria-pressed={chip === c.value} onClick={() => setChip(c.value)}
              className={cn('h-8 rounded-full border px-3 text-sm', chip === c.value ? 'border-primary bg-primary/10 font-semibold' : 'hover:bg-muted')}>
              {c.label}
            </button>
          ))}
        </div>
        <Button variant="outline" size="sm" className="gap-1.5" onClick={() => exportCsv(`deliveries-not-billed-${q.data.as_of}.csv`,
          ['Date', 'Days', 'Material', 'Quantity', 'Unit', 'Rate', 'Amount', 'Supplier', 'Project', 'Site', 'Order'],
          shown.map((d) => [d.date, d.days, d.material, Number(d.quantity), d.unit, d.rate ? num(d.rate) : '', d.amount ? num(d.amount) : '', d.supplier ?? '', d.project ?? '', d.site ?? '', d.order_ref ?? 'No order']))}>
          <Download className="size-4" /> Export
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">{rupees(num(q.data.totals.amount))} at the site's rates{q.data.totals.unpriced ? `, and ${q.data.totals.unpriced} with no rate` : ''}. When the supplier's bill comes, open the supplier › Not billed and record it, so nothing is counted twice.</p>
      <ul className="divide-y rounded-xl border bg-card">
        {shown.map((d) => (
          <li key={d.receipt_id} className="flex items-center gap-3 px-3 py-2.5 text-sm">
            <span className={cn('w-16 shrink-0 text-xs', d.days > 15 ? 'font-semibold text-draft' : 'text-muted-foreground')}>{day(d.date)}<br />{d.days} days</span>
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium">{d.quantity} {d.unit} {d.material}</span>
              <span className="block truncate text-xs text-muted-foreground">
                {d.supplier ? (d.vendor_id ? <Link to={vendorUrl(d.vendor_id, 'unbilled')} className="font-medium text-foreground underline-offset-2 hover:underline">{d.supplier}</Link> : d.supplier) : <span className="text-draft">No supplier named</span>}
                {' · '}{[d.project, d.site].filter(Boolean).join(' › ')}
                {' · '}{d.order_id ? <Link to={`/procurement/orders?id=${d.order_id}&tab=all`} className="underline-offset-2 hover:underline">{d.order_ref}</Link> : <span>no order</span>}
              </span>
            </span>
            <span className="shrink-0 text-right tabular-nums">{d.amount ? rupees(num(d.amount)) : <span className="text-xs text-muted-foreground">no rate</span>}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
