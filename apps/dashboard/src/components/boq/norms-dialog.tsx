import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Combobox } from '@/components/ui/combobox'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { fetchMaterials, type MaterialCatalog } from '@/lib/materials'
import { formatQuantity, type BoqLine, type NormInput } from '@/lib/boq'

// MP-01: what one unit of a BOQ line uses ("1 m³ of M20: 8 bags cement, 15 cft M-sand"). Each amount is in the
// material's stock unit, so the material plan (MP-02) compares it with stock without converting anything.

type Row = { material_id: string; quantity_per_unit: string; wastage_pct: string }

const toRows = (line: BoqLine | null): Row[] =>
  line?.materials.length
    ? line.materials.map((m) => ({ material_id: m.material_id, quantity_per_unit: String(Number(m.quantity_per_unit)), wastage_pct: String(Number(m.wastage_pct)) }))
    : [{ material_id: '', quantity_per_unit: '', wastage_pct: '' }]

export function NormsDialog({
  line,
  similar,
  onClose,
  onSave,
  saving,
}: {
  line: BoqLine | null
  /** How many other lines have the same work and unit (offered "use for those too"). */
  similar: number
  onClose: () => void
  onSave: (norms: NormInput[], copy: boolean) => void
  saving: boolean
}) {
  const [rows, setRows] = React.useState<Row[]>(() => toRows(line))
  const [copy, setCopy] = React.useState(false)
  React.useEffect(() => {
    setRows(toRows(line))
    setCopy(false)
  }, [line])

  const catalog = useQuery({
    queryKey: ['materials-catalog-active'],
    queryFn: () => fetchMaterials({ is_active: true, limit: 200 }),
    enabled: !!line,
    staleTime: 60_000,
  })
  const materials: MaterialCatalog[] = catalog.data?.items ?? []
  const byId = new Map(materials.map((m) => [m.id, m]))
  const used = new Set(rows.map((r) => r.material_id).filter(Boolean))

  const set = (i: number, patch: Partial<Row>) => setRows((rs) => rs.map((r, k) => (k === i ? { ...r, ...patch } : r)))
  const filled = rows.filter((r) => r.material_id && r.quantity_per_unit.trim())
  const invalid = filled.some((r) => !(Number(r.quantity_per_unit) > 0) || (r.wastage_pct !== '' && !(Number(r.wastage_pct) >= 0 && Number(r.wastage_pct) <= 100)))
  const half = rows.some((r) => (r.material_id && !r.quantity_per_unit.trim()) || (!r.material_id && r.quantity_per_unit.trim()))

  return (
    <Dialog open={!!line} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Materials for {line?.work}</DialogTitle>
          <DialogDescription>
            What one {line?.unit} of this work uses. The material plan multiplies it by the work still to do
            {line ? ` (${formatQuantity(line.remaining_quantity)} ${line.unit} left)` : ''} to show what to order and when.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-2">
          <div className="hidden grid-cols-[1fr_7.5rem_5.5rem_2rem] gap-2 text-xs text-muted-foreground sm:grid">
            <span>Material</span>
            <span>Per {line?.unit}</span>
            <span>Wastage %</span>
            <span />
          </div>
          {rows.map((r, i) => {
            const m = byId.get(r.material_id)
            return (
              <div key={i} className="grid grid-cols-[1fr_2rem] gap-2 sm:grid-cols-[1fr_7.5rem_5.5rem_2rem]">
                <Combobox
                  className="col-span-1"
                  options={materials.filter((x) => x.id === r.material_id || !used.has(x.id)).map((x) => ({ value: x.id, label: x.name }))}
                  value={r.material_id}
                  onValueChange={(v) => set(i, { material_id: v })}
                  placeholder={catalog.isLoading ? 'Loading…' : 'Pick a material'}
                  searchPlaceholder="Search materials"
                  emptyText="Not in your material list. Add it under Materials first."
                />
                <Button variant="ghost" size="icon" className="size-9 sm:order-last" aria-label="Remove this material"
                  onClick={() => setRows((rs) => (rs.length > 1 ? rs.filter((_, k) => k !== i) : [{ material_id: '', quantity_per_unit: '', wastage_pct: '' }]))}>
                  <Trash2 className="size-4" />
                </Button>
                <div className="relative">
                  <Input inputMode="decimal" aria-label="Amount per unit" placeholder="8" value={r.quantity_per_unit}
                    onChange={(e) => set(i, { quantity_per_unit: e.target.value })} className="pr-12" />
                  <span className="pointer-events-none absolute inset-y-0 right-2 flex items-center text-xs text-muted-foreground">{m?.default_unit ?? ''}</span>
                </div>
                <Input inputMode="decimal" aria-label="Wastage %" placeholder="0" value={r.wastage_pct}
                  onChange={(e) => set(i, { wastage_pct: e.target.value })} />
              </div>
            )
          })}
          <Button variant="outline" size="sm" className="w-fit gap-1.5"
            onClick={() => setRows((rs) => [...rs, { material_id: '', quantity_per_unit: '', wastage_pct: '' }])}>
            <Plus className="size-3.5" /> Add a material
          </Button>
          {similar > 0 && (
            <label className="mt-2 flex items-center gap-2 text-sm">
              <input type="checkbox" className="size-4" checked={copy} onChange={(e) => setCopy(e.target.checked)} />
              Use the same for the {similar} other line{similar > 1 ? 's' : ''} with this work (other floors or sections); lines that already have their own materials are kept
            </label>
          )}
          {invalid && <p className="text-xs text-destructive">Amounts must be more than 0; wastage between 0 and 100.</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button disabled={saving || invalid || half}
            onClick={() => onSave(filled.map((r) => ({ material_id: r.material_id, quantity_per_unit: r.quantity_per_unit.trim(), wastage_pct: r.wastage_pct.trim() || '0' })), copy)}>
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
