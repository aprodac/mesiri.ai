import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowUpDown, FileText, Search, ShoppingBag, TriangleAlert, Truck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Callout, StatStrip } from '@/components/dpr-page'
import { fetchInflows, formatMoney, INFLOW_REASONS, REASON_WORDS, type MaterialReceipt } from '@/lib/materials'
import { useSiteNames } from '@/lib/site-names'
import { CHIP, qty } from '@/lib/site-day'
import { cn, toLocalISODate } from '@/lib/utils'
import { PurchaseDetailsSheet } from './purchase-details-sheet'
import { InvoiceDetailsSheet } from './invoice-details-sheet'

// WEB-29: what was bought, from whom, for how much -- one row per purchase,
// supplier first, price on the right. Totals say how many purchases carry a
// price, so a partial figure never reads as the whole spend.

const shortDay = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString([], { day: 'numeric', month: 'short' })

interface PurchaseHistoryViewProps {
  projectId: string | null
  siteId: string | null
}

type SortOption = 'newest' | 'oldest' | 'material_asc' | 'supplier_asc'

export function PurchaseHistoryView({ projectId, siteId }: PurchaseHistoryViewProps) {
  const [search, setSearch] = React.useState('')
  const [supplierSearch, setSupplierSearch] = React.useState('')
  // Purchases are deliveries; stock moved in from another site or opening
  // stock is not spend (WEB-29), though the other kinds stay one pick away.
  const [reason, setReason] = React.useState('RECEIVED')
  const [sortOrder, setSortOrder] = React.useState<SortOption>('newest')
  const [selectedId, setSelectedId] = React.useState<string | null>(null)
  const [selectedInvoiceId, setSelectedInvoiceId] = React.useState<string | null>(null)
  const [invoiceSheetOpen, setInvoiceSheetOpen] = React.useState(false)
  const [sheetOpen, setSheetOpen] = React.useState(false)

  const filters = {
    project_id: projectId ?? undefined,
    site_id: siteId ?? undefined,
    material_name: search || undefined,
    movement_reason: reason === 'ALL' ? undefined : reason,
    limit: 100,
  }

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['materials', 'purchase-history', filters],
    queryFn: () => fetchInflows(filters),
  })

  const siteNames = useSiteNames()

  const openPurchase = (id: string) => {
    setSelectedId(id)
    setSheetOpen(true)
  }

  const openInvoice = (id: string) => {
    setSelectedInvoiceId(id)
    setInvoiceSheetOpen(true)
  }

  // Memoized so the `?? []` fallback doesn't mint a new array identity on
  // every render, which would defeat the filter/sort useMemo below and re-run
  // the whole sort on every unrelated state change (search box keystrokes).
  const rawItems = React.useMemo(() => data?.items ?? [], [data])

  // Client-side supplier search and sorting filtering on top of server query
  const items = React.useMemo(() => {
    let result = [...rawItems]

    if (supplierSearch.trim()) {
      const q = supplierSearch.toLowerCase().trim()
      result = result.filter(
        (item) => item.supplier && item.supplier.toLowerCase().includes(q)
      )
    }

    result.sort((a, b) => {
      if (sortOrder === 'newest') {
        return new Date(b.occurred_date).getTime() - new Date(a.occurred_date).getTime()
      }
      if (sortOrder === 'oldest') {
        return new Date(a.occurred_date).getTime() - new Date(b.occurred_date).getTime()
      }
      if (sortOrder === 'material_asc') {
        return a.material_name.localeCompare(b.material_name)
      }
      if (sortOrder === 'supplier_asc') {
        return (a.supplier || '').localeCompare(b.supplier || '')
      }
      return 0
    })

    return result
  }, [rawItems, supplierSearch, sortOrder])

  // Refined storekeeper KPIs: Today, This Month, Total Purchase Value, Suppliers Used
  const summary = React.useMemo(() => {
    const todayStr = toLocalISODate()
    const currentMonthStr = todayStr.slice(0, 7) // YYYY-MM

    let purchasesToday = 0
    let purchasesThisMonth = 0
    let totalCostSum = 0
    let pricedCount = 0
    let costableCount = 0
    const supplierSet = new Set<string>()

    for (const item of items) {
      if (item.occurred_date === todayStr) {
        purchasesToday += 1
      }
      if (item.occurred_date && item.occurred_date.startsWith(currentMonthStr)) {
        purchasesThisMonth += 1
      }
      if (item.supplier?.trim()) {
        supplierSet.add(item.supplier.trim())
      }
      // A corrected purchase was not money spent -- counting it would overstate
      // what the company actually paid.
      if (item.is_reversed) continue
      costableCount += 1
      const cost = item.total_cost === null ? NaN : parseFloat(item.total_cost ?? '')
      if (!isNaN(cost)) {
        totalCostSum += cost
        pricedCount += 1
      }
    }

    return {
      purchasesToday,
      purchasesThisMonth,
      suppliersUsed: supplierSet.size,
      totalCostSum,
      // How much of the total is actually backed by recorded prices. Shown so
      // a figure covering 12 of 60 purchases can never read as the full spend
      // -- the same reason the DPR refuses to report material cost at all.
      pricedCount,
      costableCount,
    }
  }, [items])

  const unpriced = summary.costableCount - summary.pricedCount
  const total = data?.total ?? 0

  return (
    <div className="flex flex-col gap-3">
      {!isLoading && !isError && rawItems.length > 0 && (
        <StatStrip
          stats={[
            {
              label: summary.pricedCount < summary.costableCount ? `Spent (${summary.pricedCount} of ${summary.costableCount} priced)` : 'Spent',
              value: summary.pricedCount > 0 ? `₹${summary.totalCostSum.toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—',
            },
            { label: 'No price recorded', value: unpriced || '—', tone: unpriced ? 'warn' : 'default' },
            { label: 'Suppliers', value: summary.suppliersUsed || '—' },
            { label: 'This month', value: summary.purchasesThisMonth || '—' },
          ]}
        />
      )}

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-52">
          <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
          <Input placeholder="Material…" aria-label="Search material" value={search} onChange={(e) => setSearch(e.target.value)} className="h-9 pl-8" />
        </div>
        <div className="relative w-full sm:w-52">
          <Truck className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
          <Input placeholder="Supplier…" aria-label="Search supplier" value={supplierSearch} onChange={(e) => setSupplierSearch(e.target.value)} className="h-9 pl-8" />
        </div>
        <Select value={reason} onValueChange={setReason}>
          <SelectTrigger className="h-9 w-[170px]" aria-label="Kind">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="ALL">Everything received</SelectItem>
            {INFLOW_REASONS.map((r) => (
              <SelectItem key={r.value} value={r.value}>
                {REASON_WORDS[r.value]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={sortOrder} onValueChange={(v) => setSortOrder(v as SortOption)}>
          <SelectTrigger className="h-9 w-[150px]" aria-label="Sort">
            <ArrowUpDown className="mr-1 size-3.5 text-muted-foreground" />
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="newest">Newest first</SelectItem>
            <SelectItem value="oldest">Oldest first</SelectItem>
            <SelectItem value="material_asc">Material A–Z</SelectItem>
            <SelectItem value="supplier_asc">Supplier A–Z</SelectItem>
          </SelectContent>
        </Select>
        {total > rawItems.length && <span className="ml-auto text-sm text-muted-foreground">Newest {rawItems.length} of {total}</span>}
      </div>

      {isError ? (
        <Callout
          tone="draft"
          icon={TriangleAlert}
          action={
            <Button variant="outline" size="sm" className="bg-background" onClick={() => refetch()}>
              Try again
            </Button>
          }
        >
          Purchases could not be loaded.
        </Callout>
      ) : isLoading ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-12 rounded-lg" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center">
          <ShoppingBag className="size-6 text-muted-foreground" aria-hidden="true" />
          <p className="text-sm font-medium">{rawItems.length ? 'Nothing matches' : 'No purchases recorded yet'}</p>
        </div>
      ) : (
        <ul className="divide-y rounded-lg border">
          {items.map((row: MaterialReceipt) => {
            const site = row.site_id ? siteNames.get(row.site_id) : undefined
            return (
              <li key={row.id} className="flex items-center gap-3 px-3 py-2">
                <button type="button" onClick={() => openPurchase(row.id)} className="flex min-w-0 flex-1 flex-col text-left">
                  <span className="truncate">
                    <strong className="font-semibold">{row.supplier || 'No supplier named'}</strong>
                    <span className="text-muted-foreground"> · </span>
                    <span className="tabular-nums">
                      {qty(row.quantity)} {row.unit}
                    </span>{' '}
                    {row.material_name}
                  </span>
                  <span className="truncate text-xs text-muted-foreground">
                    {[shortDay(row.occurred_date), !siteId && site?.name, !projectId && site?.project, row.movement_reason !== 'RECEIVED' && REASON_WORDS[row.movement_reason]]
                      .filter(Boolean)
                      .join(' · ')}
                  </span>
                </button>
                {row.invoice_id && (
                  <Button variant="ghost" size="sm" className="gap-1" onClick={() => openInvoice(row.invoice_id!)}>
                    <FileText className="size-3.5" /> Invoice
                  </Button>
                )}
                <span className={cn('w-28 text-right tabular-nums', row.total_cost ? 'font-semibold' : 'text-sm text-muted-foreground', row.is_reversed && 'line-through')}>
                  {row.total_cost ? formatMoney(row.total_cost) : 'No price'}
                </span>
                {row.is_reversed && <span className={cn(CHIP, 'bg-draft-soft text-draft')}>Corrected</span>}
              </li>
            )
          })}
        </ul>
      )}

      {/* Read-Only Purchase Details Sheet */}
      <PurchaseDetailsSheet id={selectedId} open={sheetOpen} onOpenChange={setSheetOpen} />

      <InvoiceDetailsSheet
        invoiceId={selectedInvoiceId}
        open={invoiceSheetOpen}
        onOpenChange={setInvoiceSheetOpen}
      />
    </div>
  )
}
