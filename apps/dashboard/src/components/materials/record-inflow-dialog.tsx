import * as React from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ShieldAlert, CheckCircle2, Truck } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useAuth } from '@/lib/AuthContext'
import { fetchProjects, fetchSites } from '@/lib/projects'
import {
  fetchMaterials,
  createInflow,
  fetchLastPurchase,
  formatMoney,
  newIdempotencyKey,
  INFLOW_REASONS,
  ADJUSTMENT_REASONS,
  TRANSFER_REASONS,
  type InflowReason,
  type InflowResult,
} from '@/lib/materials'
import { asMoreThanOrdered, dueWords, fetchOrders, setDeliveryOrder, type PurchaseOrder } from '@/lib/orders'
import { ReceiveOrderDialog } from '@/components/orders/order-detail'
import { CategoryTile } from '@/components/requests/parts'
import type { AppScope } from '@/lib/scope-types'
import { fetchVendorsApi } from '@/lib/api'
import { Combobox } from '@/components/ui/combobox'

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

interface RecordInflowDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  scope: AppScope
  /** WEB-77: Materials > Stock's item panel opens it for one site and item. */
  prefill?: { project_id: string; site_id: string; material_id: string } | null
}

export function RecordInflowDialog({ open, onOpenChange, scope, prefill }: RecordInflowDialogProps) {
  const { me } = useAuth()
  const queryClient = useQueryClient()

  const scopedProjectId = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : ''
  const scopedSiteId = scope.mode === 'site' ? scope.siteId : ''
  // WEB-79: a delivery on an open order is received on the order ("Material came": stock, the order, its GRN).
  const [receiving, setReceiving] = React.useState<{ order: PurchaseOrder; lineId: string } | null>(null)

  const [projectId, setProjectId] = React.useState(scopedProjectId)
  const [siteId, setSiteId] = React.useState(scopedSiteId)
  const [materialId, setMaterialId] = React.useState('')
  const [quantity, setQuantity] = React.useState('')
  const [reason, setReason] = React.useState<InflowReason>('RECEIVED')
  const [occurredDate, setOccurredDate] = React.useState(todayIso())
  const [supplier, setSupplier] = React.useState('')
  // PRC-04: the company's vendors suggested as they type; a listed name links that vendor, a new one is added.
  // The list is the Finance module's: without it (403) the field is plain text, as before.
  const { data: vendors } = useQuery({
    queryKey: ['finance', 'vendors', 'names'],
    queryFn: fetchVendorsApi,
    enabled: open,
    retry: false,
    staleTime: 60_000,
  })
  const vendorNames = React.useMemo(
    () => (vendors ?? []).filter((v) => v.status === 'active').map((v) => v.name),
    [vendors],
  )
  const [unitCost, setUnitCost] = React.useState('')
  // Tracked separately from unitCost so an edited total is not overwritten by
  // the quantity x rate calculation -- real invoices carry discounts, freight
  // and rounding that arithmetic would silently erase.
  const [totalCost, setTotalCost] = React.useState('')
  const [totalCostEdited, setTotalCostEdited] = React.useState(false)
  const [notes, setNotes] = React.useState('')
  const [error, setError] = React.useState('')
  const [success, setSuccess] = React.useState(false)
  // PRC-23: what the delivery did to the open orders at the site, and the over-delivery question.
  const [saved, setSaved] = React.useState<InflowResult | null>(null)
  const [extra, setExtra] = React.useState<{ line: string; message: string } | null>(null)
  // One key per dialog session, so a double tap or a retry after a timeout on
  // site wifi replays the first result instead of recording a second delivery.
  const [idempotencyKey, setIdempotencyKey] = React.useState(newIdempotencyKey)

  const canUseAdjustment = me?.role === 'ADMIN' || me?.role === 'PROJECT_MANAGER'
  const visibleReasons = INFLOW_REASONS.filter(
    (r) => !TRANSFER_REASONS.has(r.value) && (canUseAdjustment || !ADJUSTMENT_REASONS.has(r.value))
  )

  React.useEffect(() => {
    if (open) {
      setProjectId(prefill?.project_id || scopedProjectId)
      setSiteId(prefill?.site_id || scopedSiteId)
      setMaterialId(prefill?.material_id ?? '')
      setQuantity('')
      setReason('RECEIVED')
      setOccurredDate(todayIso())
      setSupplier('')
      setUnitCost('')
      setTotalCost('')
      setTotalCostEdited(false)
      setNotes('')
      setError('')
      setSuccess(false)
      setSaved(null)
      setExtra(null)
      setIdempotencyKey(newIdempotencyKey())
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const { data: projects = [] } = useQuery({
    queryKey: ['scope-projects'],
    queryFn: fetchProjects,
    enabled: open && (!scopedProjectId || !!prefill),
    staleTime: 60_000,
  })

  const { data: sites = [] } = useQuery({
    queryKey: ['scope-sites', projectId],
    queryFn: () => fetchSites(projectId),
    enabled: open && !!projectId && (!scopedSiteId || !!prefill),
    staleTime: 60_000,
  })

  // WEB-79: what is still to come on open orders at the chosen site (the chosen item's lines only, once picked),
  // offered before the form so a delivery on an order is received on it instead of saved loose.
  const { data: siteOrders } = useQuery({
    queryKey: ['procurement', 'orders', projectId || null, siteId || null],
    queryFn: () => fetchOrders({ project_id: projectId || null, site_id: siteId || null }),
    enabled: open && !!siteId,
    retry: false,
    staleTime: 30_000,
  })
  const coming = React.useMemo(
    () =>
      (siteOrders?.items ?? [])
        .filter((o) => (o.status === 'open' || o.status === 'part') && o.site_id === siteId)
        .flatMap((o) => o.lines.filter((l) => Number(l.pending) > 0 && (!materialId || l.material_id === materialId)).map((l) => ({ order: o, line: l }))),
    [siteOrders, siteId, materialId],
  )

  const { data: catalog } = useQuery({
    queryKey: ['materials', 'catalog', ''],
    queryFn: () => fetchMaterials({ is_active: true, limit: 200 }),
    enabled: open,
    staleTime: 60_000,
  })

  const selectedMaterial = catalog?.items.find((m) => m.id === materialId)

  const materialOptions = React.useMemo(() => {
    return (catalog?.items ?? []).map((m) => ({
      value: m.id,
      label: m.name,
    }))
  }, [catalog])

  // Keep the total in step with quantity x rate until the user takes it over.
  React.useEffect(() => {
    if (totalCostEdited) return
    const q = Number(quantity)
    const r = Number(unitCost)
    if (!quantity || !unitCost || Number.isNaN(q) || Number.isNaN(r)) {
      setTotalCost('')
      return
    }
    setTotalCost((q * r).toFixed(2))
  }, [quantity, unitCost, totalCostEdited])

  // What this material last cost, so a jump is visible while it can still be
  // questioned rather than in a report weeks later.
  const { data: lastPurchase } = useQuery({
    queryKey: ['materials', 'last-purchase', materialId],
    queryFn: () => fetchLastPurchase(materialId),
    enabled: open && !!materialId,
    staleTime: 60_000,
  })

  const priceJump = React.useMemo(() => {
    const previous = Number(lastPurchase?.unit_cost)
    const current = Number(unitCost)
    if (!lastPurchase?.unit_cost || !unitCost || Number.isNaN(previous) || Number.isNaN(current)) {
      return null
    }
    if (previous <= 0) return null
    const change = ((current - previous) / previous) * 100
    // Below 10% is ordinary market movement; flagging it would train people to
    // ignore the warning that matters.
    return Math.abs(change) >= 10 ? change : null
  }, [lastPurchase, unitCost])

  const mutation = useMutation({
    mutationFn: () =>
      createInflow(
        {
          project_id: projectId,
          site_id: siteId || undefined,
          material_id: materialId,
          unit_id: selectedMaterial!.default_unit_id,
          quantity,
          movement_reason: reason,
          supplier: supplier.trim() || undefined,
          // Omitted entirely when blank, so the backend stores NULL rather
          // than a zero that would read as "this delivery was free".
          unit_cost: unitCost.trim() || undefined,
          total_cost: totalCost.trim() || undefined,
          notes: notes.trim() || undefined,
          occurred_date: occurredDate,
        },
        idempotencyKey
      ),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['materials'] })
      queryClient.invalidateQueries({ queryKey: ['procurement'] })
      setSuccess(true)
      setSaved(result)
      // PRC-23: open orders it may belong to are offered; the dialog stays until they answer.
      if (!result.open_orders?.length) setTimeout(() => onOpenChange(false), result.order ? 2200 : 900)
    },
    onError: (err: any) => {
      setError(err.response?.data?.detail || 'Failed to record material inflow.')
    },
  })

  const putOnOrder = useMutation({
    mutationFn: ({ line, confirm }: { line: string; confirm?: boolean }) => setDeliveryOrder(saved!.id, { line_id: line, confirm_extra: confirm }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['procurement'] })
      onOpenChange(false)
    },
    onError: (err: any, v) => {
      const more = asMoreThanOrdered(err)
      if (more) return setExtra({ line: v.line, message: more.message })
      setError(typeof err.response?.data?.detail === 'string' ? err.response.data.detail : 'Not counted on the order.')
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (!projectId) {
      setError('Project is required.')
      return
    }
    if (!materialId || !selectedMaterial) {
      setError('Material is required.')
      return
    }
    const qty = Number(quantity)
    if (!quantity || Number.isNaN(qty) || qty <= 0) {
      setError('Quantity must be a positive number.')
      return
    }
    mutation.mutate()
  }

  return (
    <>
    <ReceiveOrderDialog order={receiving?.order ?? null} lineId={receiving?.lineId} open={!!receiving} onClose={() => setReceiving(null)} />
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px] max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Record a delivery</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4 py-2 text-xs">
          {error && (
            <div className="bg-destructive/10 border border-destructive text-destructive p-2.5 rounded flex items-center gap-2">
              <ShieldAlert className="size-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}
          {success && (
            <div className="bg-emerald-500/10 border border-emerald-500/30 text-emerald-700 dark:text-emerald-400 p-2.5 rounded flex items-center gap-2">
              <CheckCircle2 className="size-4 shrink-0" />
              <span>
                Delivery recorded.
                {saved?.order && ` Counted on ${saved.order.ref} (${saved.order.vendor_name}): ${Number(saved.order.received)} of ${Number(saved.order.quantity)} ${saved.order.unit} came.`}
              </span>
            </div>
          )}
          {success && saved?.open_orders && saved.open_orders.length > 0 && (
            <div className="flex flex-col gap-2 rounded border border-sky-300 bg-sky-50 p-2.5 text-xs text-sky-950 dark:bg-sky-950 dark:text-sky-100">
              <span className="font-semibold">Is it from one of these orders?</span>
              {extra ? (
                <>
                  <span>{extra.message}</span>
                  <span className="flex flex-wrap gap-2">
                    <Button type="button" size="sm" variant="outline" onClick={() => setExtra(null)}>Back</Button>
                    <Button type="button" size="sm" disabled={putOnOrder.isPending} onClick={() => putOnOrder.mutate({ line: extra.line, confirm: true })}>Yes, the extra came</Button>
                  </span>
                </>
              ) : (
                <span className="flex flex-wrap gap-2">
                  {saved.open_orders.map((o) => (
                    <Button key={o.line_id} type="button" size="sm" variant="outline" disabled={putOnOrder.isPending} onClick={() => putOnOrder.mutate({ line: o.line_id })}>
                      {o.ref} · {o.vendor_name} ({Number(o.pending)} {o.unit} to come)
                    </Button>
                  ))}
                  <Button type="button" size="sm" variant="ghost" onClick={() => onOpenChange(false)}>Not from an order</Button>
                </span>
              )}
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label>Project</Label>
              {scopedProjectId && !prefill ? (
                <Input value={scope.mode !== 'portfolio' ? scope.projectName : ''} disabled />
              ) : (
                <Select value={projectId} onValueChange={(v) => { setProjectId(v); setSiteId('') }}>
                  <SelectTrigger className="h-9">
                    <SelectValue placeholder="Choose project" />
                  </SelectTrigger>
                  <SelectContent>
                    {projects.map((p) => (
                      <SelectItem key={p.id} value={p.id}>
                        {p.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>

            <div className="grid gap-1.5">
              <Label>Site</Label>
              {scopedSiteId && !prefill ? (
                <Input value={scope.mode === 'site' ? scope.siteName : ''} disabled />
              ) : (
                <Select value={siteId} onValueChange={setSiteId} disabled={!projectId}>
                  <SelectTrigger className="h-9">
                    <SelectValue placeholder="Choose site" />
                  </SelectTrigger>
                  <SelectContent>
                    {sites.map((s) => (
                      <SelectItem key={s.id} value={s.id}>
                        {s.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
          </div>

          {!success && reason === 'RECEIVED' && coming.length > 0 && (
            <div className="flex flex-col gap-1.5 rounded-lg border border-blue-200 bg-blue-50/60 p-2.5 dark:border-blue-900 dark:bg-blue-950/40">
              <span className="flex items-center gap-1.5 text-xs font-semibold text-blue-950 dark:text-blue-100">
                <Truck className="size-3.5" /> On order for this site: is it one of these?
              </span>
              {coming.slice(0, 6).map(({ order, line }) => (
                <button
                  key={line.id}
                  type="button"
                  onClick={() => {
                    setReceiving({ order, lineId: line.id })
                    onOpenChange(false)
                  }}
                  className="flex items-center gap-2 rounded-md border bg-background px-2 py-1.5 text-left transition hover:border-blue-400"
                >
                  <CategoryTile mainCategory={line.main_category} size="sm" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold">{line.material}</span>
                    <span className="block truncate text-[11px] text-muted-foreground">
                      {order.ref} · {order.vendor_name} · {dueWords(order)}
                    </span>
                  </span>
                  <span className="shrink-0 text-xs font-semibold tabular-nums">{Number(line.pending)} {line.unit} to come</span>
                </button>
              ))}
              <span className="text-[11px] text-muted-foreground">Not on an order? Fill in the form below.</span>
            </div>
          )}

          <div className="grid gap-1.5">
            <Label>Material</Label>
            <Combobox
              options={materialOptions}
              value={materialId}
              onValueChange={setMaterialId}
              placeholder="Choose material"
              searchPlaceholder="Search materials..."
              emptyText="No materials found."
            />
            {catalog && catalog.items.length === 0 && (
              <p className="text-muted-foreground">
                No materials in the catalog yet — ask an admin to add one first.
              </p>
            )}
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label htmlFor="quantity">Quantity</Label>
              <Input
                id="quantity"
                type="number"
                min="0"
                step="any"
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
                required
              />
            </div>
            <div className="grid gap-1.5">
              <Label>Unit</Label>
              {/* Read-only: a material's Stock Unit is fixed (no conversion) —
                  see materials_catalog.default_unit_id. Selecting the material
                  determines the unit, not the other way around. */}
              <Input value={selectedMaterial?.default_unit ?? ''} disabled placeholder="Set by the material" />
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label>What kind</Label>
              <Select value={reason} onValueChange={(v) => setReason(v as InflowReason)}>
                <SelectTrigger className="h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {visibleReasons.map((r) => (
                    <SelectItem key={r.value} value={r.value}>
                      {r.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="occurredDate">Day</Label>
              <Input
                id="occurredDate"
                type="date"
                value={occurredDate}
                onChange={(e) => setOccurredDate(e.target.value)}
                required
              />
            </div>
          </div>

          {reason === 'OPENING_STOCK' && (
            <p className="rounded-md border border-border/60 bg-muted/30 px-3 py-2 text-[11px] text-muted-foreground">
              What was already on this site before it started using Mesiri. Entered once per site and
              material; to change it later, correct this entry or record an adjustment.
            </p>
          )}

          <div className="grid gap-1.5">
            <Label htmlFor="supplier">Supplier</Label>
            <Input
              id="supplier"
              list="supplier-vendors"
              autoComplete="off"
              value={supplier}
              onChange={(e) => setSupplier(e.target.value)}
              placeholder="Optional · pick a vendor or type a new one"
            />
            <datalist id="supplier-vendors">
              {vendorNames.map((n) => (
                <option key={n} value={n} />
              ))}
            </datalist>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <div className="flex items-baseline justify-between gap-2">
                <Label htmlFor="unitCost">
                  Rate {selectedMaterial ? `per ${selectedMaterial.default_unit}` : ''}
                </Label>
                {lastPurchase?.unit_cost && (
                  <span className="text-[11px] text-muted-foreground tabular-nums">
                    last {formatMoney(lastPurchase.unit_cost)}
                  </span>
                )}
              </div>
              <Input
                id="unitCost"
                type="number"
                min="0"
                step="any"
                value={unitCost}
                onChange={(e) => setUnitCost(e.target.value)}
                placeholder="Optional"
              />
            </div>
            <div className="grid gap-1.5">
              <div className="flex items-baseline justify-between gap-2">
                <Label htmlFor="totalCost">Total cost</Label>
                {totalCostEdited && (
                  <button
                    type="button"
                    className="text-[11px] text-primary-ink font-semibold"
                    onClick={() => setTotalCostEdited(false)}
                  >
                    recalculate
                  </button>
                )}
              </div>
              <Input
                id="totalCost"
                type="number"
                min="0"
                step="any"
                value={totalCost}
                onChange={(e) => {
                  // Any manual edit wins: discounts and freight are real, and
                  // quantity x rate would quietly overwrite them.
                  setTotalCostEdited(true)
                  setTotalCost(e.target.value)
                }}
                placeholder="Optional"
              />
            </div>
          </div>

          {priceJump !== null && (
            <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-700 dark:text-amber-400">
              This rate is {Math.abs(priceJump).toFixed(0)}%{' '}
              {priceJump > 0 ? 'higher' : 'lower'} than the last recorded price
              {lastPurchase?.occurred_date ? ` (${lastPurchase.occurred_date}` : ''}
              {lastPurchase?.supplier ? `, ${lastPurchase.supplier})` : lastPurchase?.occurred_date ? ')' : ''}
              . Worth a check before recording.
            </div>
          )}

          <div className="grid gap-1.5">
            <Label htmlFor="notes">Notes</Label>
            <textarea
              id="notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="flex min-h-[60px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-xs shadow-xs focus-visible:outline-hidden focus-visible:ring-1 focus-visible:ring-ring"
              placeholder="Optional"
            />
          </div>

          <DialogFooter className="pt-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={mutation.isPending}>
              Cancel
            </Button>
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? 'Saving…' : 'Record delivery'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
    </>
  )
}
