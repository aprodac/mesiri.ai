import * as React from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ShieldAlert, CheckCircle2 } from 'lucide-react'
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
} from '@/lib/materials'
import type { AppScope } from '@/lib/scope-types'
import { Combobox } from '@/components/ui/combobox'

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

interface RecordInflowDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  scope: AppScope
}

export function RecordInflowDialog({ open, onOpenChange, scope }: RecordInflowDialogProps) {
  const { me } = useAuth()
  const queryClient = useQueryClient()

  const scopedProjectId = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : ''
  const scopedSiteId = scope.mode === 'site' ? scope.siteId : ''

  const [projectId, setProjectId] = React.useState(scopedProjectId)
  const [siteId, setSiteId] = React.useState(scopedSiteId)
  const [materialId, setMaterialId] = React.useState('')
  const [quantity, setQuantity] = React.useState('')
  const [reason, setReason] = React.useState<InflowReason>('RECEIVED')
  const [occurredDate, setOccurredDate] = React.useState(todayIso())
  const [supplier, setSupplier] = React.useState('')
  const [unitCost, setUnitCost] = React.useState('')
  // Tracked separately from unitCost so an edited total is not overwritten by
  // the quantity x rate calculation -- real invoices carry discounts, freight
  // and rounding that arithmetic would silently erase.
  const [totalCost, setTotalCost] = React.useState('')
  const [totalCostEdited, setTotalCostEdited] = React.useState(false)
  const [notes, setNotes] = React.useState('')
  const [error, setError] = React.useState('')
  const [success, setSuccess] = React.useState(false)
  // One key per dialog session, so a double tap or a retry after a timeout on
  // site wifi replays the first result instead of recording a second delivery.
  const [idempotencyKey, setIdempotencyKey] = React.useState(newIdempotencyKey)

  const canUseAdjustment = me?.role === 'ADMIN' || me?.role === 'PROJECT_MANAGER'
  const visibleReasons = INFLOW_REASONS.filter(
    (r) => !TRANSFER_REASONS.has(r.value) && (canUseAdjustment || !ADJUSTMENT_REASONS.has(r.value))
  )

  React.useEffect(() => {
    if (open) {
      setProjectId(scopedProjectId)
      setSiteId(scopedSiteId)
      setMaterialId('')
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
      setIdempotencyKey(newIdempotencyKey())
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const { data: projects = [] } = useQuery({
    queryKey: ['scope-projects'],
    queryFn: fetchProjects,
    enabled: open && !scopedProjectId,
    staleTime: 60_000,
  })

  const { data: sites = [] } = useQuery({
    queryKey: ['scope-sites', projectId],
    queryFn: () => fetchSites(projectId),
    enabled: open && !!projectId && !scopedSiteId,
    staleTime: 60_000,
  })

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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['materials'] })
      setSuccess(true)
      setTimeout(() => onOpenChange(false), 900)
    },
    onError: (err: any) => {
      setError(err.response?.data?.detail || 'Failed to record material inflow.')
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
              <span>Material inflow recorded.</span>
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label>Project</Label>
              {scopedProjectId ? (
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
              {scopedSiteId ? (
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
            <Input id="supplier" value={supplier} onChange={(e) => setSupplier(e.target.value)} placeholder="Optional" />
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
                    className="text-[11px] text-primary font-semibold"
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
  )
}
