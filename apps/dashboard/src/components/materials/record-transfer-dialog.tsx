import * as React from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ShieldAlert, CheckCircle2, ArrowRight } from 'lucide-react'
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
import { fetchProjects, fetchSites } from '@/lib/projects'
import {
  fetchMaterials,
  fetchStockCheck,
  createTransfer,
  asOverStockConflict,
  newIdempotencyKey,
  type OverStockConflict,
} from '@/lib/materials'
import type { AppScope } from '@/lib/scope-types'
import { Combobox } from '@/components/ui/combobox'

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

interface RecordTransferDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  scope: AppScope
}

// Moves material out of one site's stock and into another's as ONE record
// (POST /materials/transfers): both halves are written together, so a
// transfer is never half-recorded, and it is corrected as a whole.
export function RecordTransferDialog({ open, onOpenChange, scope }: RecordTransferDialogProps) {
  const queryClient = useQueryClient()

  const scopedProjectId = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : ''
  const scopedSiteId = scope.mode === 'site' ? scope.siteId : ''

  const [fromProjectId, setFromProjectId] = React.useState(scopedProjectId)
  const [fromSiteId, setFromSiteId] = React.useState(scopedSiteId)
  // Defaults to the same project; leftovers often go to the next job, so the
  // destination project can be changed.
  const [toProjectId, setToProjectId] = React.useState(scopedProjectId)
  const [toSiteId, setToSiteId] = React.useState('')
  const [materialId, setMaterialId] = React.useState('')
  const [quantity, setQuantity] = React.useState('')
  const [occurredDate, setOccurredDate] = React.useState(todayIso())
  const [notes, setNotes] = React.useState('')
  const [error, setError] = React.useState('')
  const [success, setSuccess] = React.useState(false)
  const [overStock, setOverStock] = React.useState<OverStockConflict | null>(null)
  const [idempotencyKey, setIdempotencyKey] = React.useState(newIdempotencyKey)

  React.useEffect(() => {
    if (open) {
      setFromProjectId(scopedProjectId)
      setFromSiteId(scopedSiteId)
      setToProjectId(scopedProjectId)
      setToSiteId('')
      setMaterialId('')
      setQuantity('')
      setOccurredDate(todayIso())
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
    enabled: open,
    staleTime: 60_000,
  })

  const { data: fromSites = [] } = useQuery({
    queryKey: ['scope-sites', fromProjectId],
    queryFn: () => fetchSites(fromProjectId),
    enabled: open && !!fromProjectId,
    staleTime: 60_000,
  })

  const { data: toSites = [] } = useQuery({
    queryKey: ['scope-sites', toProjectId],
    queryFn: () => fetchSites(toProjectId),
    enabled: open && !!toProjectId,
    staleTime: 60_000,
  })

  const { data: catalog } = useQuery({
    queryKey: ['materials', 'catalog', ''],
    queryFn: () => fetchMaterials({ is_active: true, limit: 200 }),
    enabled: open,
    staleTime: 60_000,
  })

  const selectedMaterial = catalog?.items.find((m) => m.id === materialId)
  const materialOptions = React.useMemo(
    () => (catalog?.items ?? []).map((m) => ({ value: m.id, label: m.name })),
    [catalog]
  )
  const destinationSites = toSites.filter((s) => s.id !== fromSiteId)

  // Advisory only: the backend re-reads the balance under a lock.
  const { data: stock } = useQuery({
    queryKey: ['materials', 'stock-check', materialId, fromSiteId],
    queryFn: () => fetchStockCheck(materialId, fromSiteId),
    enabled: open && !!materialId && !!fromSiteId,
    staleTime: 10_000,
  })

  const mutation = useMutation({
    mutationFn: (allowNegative: boolean) =>
      createTransfer(
        {
          from_site_id: fromSiteId,
          to_site_id: toSiteId,
          material_id: materialId,
          unit_id: selectedMaterial!.default_unit_id,
          quantity,
          occurred_date: occurredDate,
          notes: notes.trim() || undefined,
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
      const conflict = asOverStockConflict(err)
      if (conflict) {
        setOverStock(conflict)
        return
      }
      const detail = err.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Failed to record the transfer.')
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setOverStock(null)
    if (!fromSiteId || !toSiteId) {
      setError('Choose the site sending the material and the site receiving it.')
      return
    }
    if (fromSiteId === toSiteId) {
      setError('A transfer needs two different sites.')
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
      <DialogContent className="sm:max-w-[520px] max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Move material between sites</DialogTitle>
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
              <span>Transfer recorded at both sites.</span>
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-[1fr_auto_1fr] sm:items-end">
            <div className="grid gap-1.5">
              <Label>From</Label>
              <Select
                value={fromProjectId}
                onValueChange={(v) => {
                  setFromProjectId(v)
                  setFromSiteId('')
                }}
              >
                <SelectTrigger className="h-9">
                  <SelectValue placeholder="Project" />
                </SelectTrigger>
                <SelectContent>
                  {projects.map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={fromSiteId} onValueChange={setFromSiteId} disabled={!fromProjectId}>
                <SelectTrigger className="h-9">
                  <SelectValue placeholder="Sending site" />
                </SelectTrigger>
                <SelectContent>
                  {fromSites.map((s) => (
                    <SelectItem key={s.id} value={s.id}>
                      {s.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <ArrowRight className="hidden sm:block size-4 text-muted-foreground mb-2.5" />
            <div className="grid gap-1.5">
              <Label>To</Label>
              <Select
                value={toProjectId}
                onValueChange={(v) => {
                  setToProjectId(v)
                  setToSiteId('')
                }}
              >
                <SelectTrigger className="h-9">
                  <SelectValue placeholder="Project" />
                </SelectTrigger>
                <SelectContent>
                  {projects.map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={toSiteId} onValueChange={setToSiteId} disabled={!toProjectId}>
                <SelectTrigger className="h-9">
                  <SelectValue placeholder="Receiving site" />
                </SelectTrigger>
                <SelectContent>
                  {destinationSites.map((s) => (
                    <SelectItem key={s.id} value={s.id}>
                      {s.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
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
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label htmlFor="transferQuantity">Quantity</Label>
              <Input
                id="transferQuantity"
                type="number"
                min="0"
                step="any"
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
                required
              />
              {stock && (
                <span className="text-[11px] text-muted-foreground tabular-nums">
                  {stock.available} {stock.unit ?? selectedMaterial?.default_unit ?? ''} at the sending site
                </span>
              )}
            </div>
            <div className="grid gap-1.5">
              <Label>Unit</Label>
              <Input value={selectedMaterial?.default_unit ?? ''} disabled placeholder="Set by the material" />
            </div>
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="transferDate">Date</Label>
            <Input
              id="transferDate"
              type="date"
              value={occurredDate}
              onChange={(e) => setOccurredDate(e.target.value)}
              required
            />
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="transferNotes">Notes</Label>
            <textarea
              id="transferNotes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="flex min-h-[60px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-xs shadow-xs focus-visible:outline-hidden focus-visible:ring-1 focus-visible:ring-ring"
              placeholder="Optional, e.g. vehicle number or who carried it"
            />
          </div>

          {overStock && (
            <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-xs space-y-2">
              <p className="font-bold text-amber-700 dark:text-amber-400">
                Only {overStock.available} {overStock.unit} of {overStock.material_name} at the sending site
              </p>
              <p className="text-muted-foreground">
                Sending {overStock.requested} {overStock.unit} leaves it at{' '}
                <span className="tabular-nums">
                  {Number(overStock.available) - Number(overStock.requested)} {overStock.unit}
                </span>
                . A delivery or opening stock may be missing there.
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
                  Yes, transfer anyway
                </Button>
              </div>
            </div>
          )}

          <DialogFooter className="pt-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={mutation.isPending}>
              Cancel
            </Button>
            <Button type="submit" disabled={mutation.isPending || !!overStock}>
              {mutation.isPending ? 'Saving…' : 'Move it'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
