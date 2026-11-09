import { useUrlState } from '@/lib/url-state'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ClipboardCheck, Download, Image, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useScope } from '@/lib/ScopeContext'
import { usePageTitle } from '@/lib/page-title'
import { exportCsv } from '@/lib/export'
import { qty } from '@/lib/requests'
import { fetchGrns, type GoodsReceipt } from '@/lib/orders'
import { ProjectDot } from '@/components/requests/parts'
import { VendorTile } from '@/components/orders/order-detail'
import { cn } from '@/lib/utils'
import { VendorLink } from '@/components/vendors/vendor-parts'
import { ModuleTitle } from '@/components/page/page-kit'

// PRC-29: Procurement > GRN. Every goods received note: what came against which order, what was accepted into stock
// and what was turned away (and why), the challan number and photo, who received it. A GRN is made by "Material
// came" on the order; this page is where the office and accounts look them up.

function day(d: string): string {
  return new Date(`${d}T00:00:00`).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })
}

function exportGrns(items: GoodsReceipt[]): void {
  const rows = items.flatMap((g) => g.lines.map((l) => [
    g.ref, g.received_on, g.order_ref, g.vendor_name, g.project_name, g.site_name, l.material, Number(l.accepted),
    Number(l.rejected), l.unit, l.rejected_reason ?? '', g.challan_no ?? '', g.received_by_name ?? '', g.created_by_name ?? '',
  ]))
  exportCsv(`goods-received-${new Date().toISOString().slice(0, 10)}.csv`,
    ['GRN', 'Date', 'Order', 'Supplier', 'Project', 'Site', 'Item', 'Accepted', 'Rejected', 'Unit', 'Why rejected',
      'Challan no.', 'Received by', 'Recorded by'], rows)
}

export default function GoodsReceiptsPage() {
  usePageTitle('Goods received')
  const { scope } = useScope()
  const projectId = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : null
  const siteId = scope.mode === 'site' ? scope.siteId : null
  const [search, setSearch] = useUrlState<string>('q', '')  // UX-09: links land on one order's deliveries
  const { data, isLoading, isError } = useQuery({
    queryKey: ['procurement', 'grns', projectId, siteId],
    queryFn: () => fetchGrns({ project_id: projectId, site_id: siteId }),
  })
  const all = data?.items ?? []
  const q = search.trim().toLowerCase()
  const list = q
    ? all.filter((g) => [g.ref, g.order_ref, g.vendor_name, g.challan_no ?? '', g.site_name, ...g.lines.map((l) => l.material)].some((x) => x.toLowerCase().includes(q)))
    : all
  const rejectedCount = all.filter((g) => g.lines.some((l) => Number(l.rejected) > 0)).length

  return (
    <div className="flex flex-col gap-4 p-4 md:p-6">
      <header className="flex items-center justify-between gap-3">
        <ModuleTitle icon={ClipboardCheck} title="Goods received" />
        <Button variant="outline" className="gap-2" disabled={!list.length} onClick={() => exportGrns(list)}><Download className="size-4" /> <span className="hidden sm:inline">Export</span></Button>
      </header>

      <div className="flex flex-wrap items-center gap-2">
        <label className="flex h-9 items-center gap-2 rounded-md border px-2.5">
          <Search className="size-4 text-muted-foreground" />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="GRN, PO, supplier, challan, item" className="w-48 bg-transparent text-sm outline-none sm:w-64" />
        </label>
        {rejectedCount > 0 && <span className="rounded-full bg-destructive/10 px-2.5 py-1 text-xs font-semibold text-destructive">{rejectedCount} with something rejected</span>}
      </div>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : isError ? (
        <p className="text-sm text-destructive">Goods received could not be loaded.</p>
      ) : list.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border p-10 text-center text-sm text-muted-foreground">
          <ClipboardCheck className="size-6" />
          {all.length === 0 ? 'Nothing received against an order yet. Open an order and tap “Material came”: it records the challan, what was accepted and what was rejected.' : 'No goods received match this search.'}
        </div>
      ) : (
        <ul className="flex flex-col divide-y rounded-xl border">
          {list.map((g) => {
            const rejected = g.lines.some((l) => Number(l.rejected) > 0)
            return (
              <li key={g.id} className={cn('flex flex-col gap-2 p-3 sm:flex-row sm:items-start sm:gap-4 sm:p-4', rejected && 'bg-destructive/5')}>
                <div className="flex min-w-0 flex-1 items-start gap-3">
                  <VendorTile id={g.vendor_name} name={g.vendor_name} />
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-baseline gap-x-2">
                      <span className="font-semibold tabular-nums">{g.ref}</span>
                      <VendorLink id={g.vendor_id} name={g.vendor_name} className="text-sm" />
                      <Link to={`/procurement/orders?id=${g.order_id}`} className="text-xs text-muted-foreground tabular-nums underline-offset-2 hover:underline">{g.order_ref}</Link>
                    </div>
                    <div className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
                      <span>{day(g.received_on)}</span>
                      <span className="inline-flex items-center gap-1"><ProjectDot id={g.project_id} />{g.project_name} › {g.site_name}</span>
                      {g.challan_no && <span>challan {g.challan_no}</span>}
                      {g.received_by_name && <span>received by {g.received_by_name}</span>}
                    </div>
                    <div className="mt-1 flex flex-col text-sm">
                      {g.lines.map((l) => (
                        <span key={l.line_id}>
                          <span className="font-medium">{l.material}</span> · <span className="text-success">{qty(l.accepted, l.unit)} accepted</span>
                          {Number(l.rejected) > 0 && <span className="text-destructive"> · {qty(l.rejected, l.unit)} rejected: {l.rejected_reason}</span>}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
                {g.photo_url ? (
                  <a href={g.photo_url} target="_blank" rel="noreferrer" className="inline-flex shrink-0 items-center gap-1.5 self-start rounded-md border px-2.5 py-1.5 text-xs font-medium hover:bg-muted/50"><Image className="size-3.5" /> Challan photo</a>
                ) : (
                  <span className="shrink-0 self-start text-xs text-muted-foreground">{g.has_photo ? 'Photo saved (cannot be opened right now)' : 'No photo'}</span>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
