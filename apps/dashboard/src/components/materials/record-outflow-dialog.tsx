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
  createOutflow,
  fetchStockCheck,
  asOverStockConflict,
  newIdempotencyKey,
  OUTFLOW_REASONS,
  ADJUSTMENT_REASONS,
  TRANSFER_REASONS,
  type OutflowReason,
  type OverStockConflict,
} from '@/lib/materials'
import type { AppScope } from '@/lib/scope-types'
import { Combobox } from '@/components/ui/combobox'

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

interface RecordOutflowDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  scope: AppScope
}

export function RecordOutflowDialog({ open, onOpenChange, scope }: RecordOutflowDialogProps) {
  const { me } = useAuth()
  const queryClient = useQueryClient()

  const scopedProjectId = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : ''
  const scopedSiteId = scope.mode === 'site' ? scope.siteId : ''

  const [projectId, setProjectId] = React.useState(scopedProjectId)
  const [siteId, setSiteId] = React.useState(scopedSiteId)
  const [materialId, setMaterialId] = React.useState('')
  const [quantity, setQuantity] = React.useState('')
  const [reason, setReason] = React.useState<OutflowReason>('CONSUMED')
  const [occurredDate, setOccurredDate] = React.useState(todayIso())
  const [workItem, setWorkItem] = React.useState('')
  const [notes, setNotes] = React.useState('')
  const [error, setError] = React.useState('')
  const [success, setSuccess] = React.useState(false)
  const [overStock, setOverStock] = React.useState<OverStockConflict | null>(null)
  // One key per dialog session, so N clicks are one delivery. Regenerated when
  // the dialog reopens (see the reset effect below).
  const [idempotencyKey, setIdempotencyKey] = React.useState(newIdempotencyKey)

  const canUseAdjustment = me?.role === 'ADMIN' || me?.role === 'PROJECT_MANAGER'
  const visibleReasons = OUTFLOW_REASONS.filter(
    (r) => !TRANSFER_REASONS.has(r.value) && (canUseAdjustment || !ADJUSTMENT_REASONS.has(r.value))
  )

  React.useEffect(() => {
    if (open) {
      setProjectId(scopedProjectId)
      setSiteId(scopedSiteId)
      setMaterialId('')
      setQuantity('')
      setReason('CONSUMED')
      setOccurredDate(todayIso())
      setWorkItem('')
      setNotes('')
      setError('')
      setSuccess(false)
      setOverStock(null)
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

  // Advisory only -- the backend re-reads the balance under a lock before
  // deciding, so a stale number here can never let a bad write through. This
  // exists so the user sees the problem while typing rather than after
  // submitting.
  const { data: stock } = useQuery({
    queryKey: ['materials', 'stock-check', materialId, siteId],
    queryFn: () => fetchStockCheck(materialId, siteId || undefined),
    enabled: open && !!materialId,
    staleTime: 10_000,
  })

  const mutation = useMutation({
    mutationFn: (allowNegative: boolean) =>
      createOutflow(
        {
          project_id: projectId,
          site_id: siteId || undefined,
          material_id: materialId,
          unit_id: selectedMaterial!.default_unit_id,
          quantity,
          movement_reason: reason,
          work_item: workItem.trim() || undefined,
          notes: notes.trim() || undefined,
          occurred_date: occurredDate,
          allow_negative: allowNegative,
        },
        idempotencyKey
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['materials'] })
      setSuccess(true)
      setTimeout(() => onOpenChange(false), 900)
    },
    onError: (err: any) => {
      // The over-stock 409 is a question, not a failure: negative stock is a
      // real situation (deliveries recorded late), so we show what the server
      // found and let the user decide, keeping everything they typed.
      const conflict = asOverStockConflict(err)
      if (conflict) {
        setOverStock(conflict)
        return
      }
      const detail = err.response?.data?.detail
      setError(
        typeof detail === 'string' ? detail : 'Failed to record material outflow.'
      )
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setOverStock(null)
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
    mutation.mutate(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px] max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Record material used</DialogTitle>
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
              <span>Material outflow recorded.</span>
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
              <div className="flex items-baseline justify-between gap-2">
                <Label htmlFor="quantityOut">Quantity</Label>
                {stock && (
                  <span className="text-[11px] text-muted-foreground tabular-nums">
                    {stock.available} {stock.unit ?? ''} in stock
                  </span>
                )}
              </div>
              <Input
                id="quantityOut"
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
              {/* Read-only: a material's Stock Unit is fixed (no conversion) --
                  see materials_catalog.default_unit_id. */}
              <Input value={selectedMaterial?.default_unit ?? ''} disabled placeholder="Set by the material" />
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label>What kind</Label>
              <Select value={reason} onValueChange={(v) => setReason(v as OutflowReason)}>
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
              <Label htmlFor="occurredDateOut">Day</Label>
              <Input
                id="occurredDateOut"
                type="date"
                value={occurredDate}
                onChange={(e) => setOccurredDate(e.target.value)}
                required
              />
            </div>
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="workItem">Used for</Label>
            <Input id="workItem" value={workItem} onChange={(e) => setWorkItem(e.target.value)} placeholder="e.g. Slab casting, 5th floor" />
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="notesOut">Notes</Label>
            <textarea
              id="notesOut"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="flex min-h-[60px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-xs shadow-xs focus-visible:outline-hidden focus-visible:ring-1 focus-visible:ring-ring"
              placeholder="Optional"
            />
          </div>

          {/* Inline, not a browser confirm() -- matches the dialog idiom, and
              keeps every typed value in place while the user decides. */}
          {overStock && (
            <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-xs space-y-2">
              <p className="font-bold text-amber-700 dark:text-amber-400">
                Only {overStock.available} {overStock.unit} of {overStock.material_name} in stock
              </p>
              <p className="text-muted-foreground">
                Recording {overStock.requested} {overStock.unit} leaves this site at{' '}
                <span className="tabular-nums">
                  {Number(overStock.available) - Number(overStock.requested)} {overStock.unit}
                </span>
                . Corrections need a Project Manager and cannot be undone by editing.
              </p>
              <div className="flex gap-2 pt-0.5">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-7 text-xs"
                  onClick={() => setOverStock(null)}
                  disabled={mutation.isPending}
                >
                  Go back and fix
                </Button>
                <Button
                  type="button"
                  size="sm"
                  className="h-7 text-xs"
                  onClick={() => mutation.mutate(true)}
                  disabled={mutation.isPending}
                >
                  Yes, record anyway
                </Button>
              </div>
            </div>
          )}

          <DialogFooter className="pt-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={mutation.isPending}>
              Cancel
            </Button>
            <Button type="submit" disabled={mutation.isPending || !!overStock}>
              {mutation.isPending ? 'Saving…' : 'Record use'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
