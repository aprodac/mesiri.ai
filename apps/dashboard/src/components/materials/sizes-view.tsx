import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Ruler, Trash2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  answerSizeRequest,
  deleteUnitSize,
  dismissSizeRequest,
  fetchMaterials,
  fetchSizeRequests,
  fetchUnitSizes,
  fetchUnitsOfMeasure,
  setUnitSize,
  type SizeRequest,
} from '@/lib/materials'

// WA-168: Sizes -- "1 load M-sand = 60 bags", set once for the company; every
// line in that unit converts into the stock unit from then on. Above them, the
// sizes sites asked for (nobody on site knew, or someone proposed one): an
// answer sets it and saves the lines that waited, as the people who sent them.
// Admins and project managers (the API checks the same).

function detail(err: unknown, fallback: string): string {
  const e = err as { response?: { data?: { detail?: unknown } } }
  return typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : fallback
}

function RequestRow({ request }: { request: SizeRequest }) {
  const queryClient = useQueryClient()
  const [value, setValue] = React.useState(request.proposed_one_unit_equals ?? '')
  const [note, setNote] = React.useState('')
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['materials', 'sizes'] })
  const answer = useMutation({
    mutationFn: () => answerSizeRequest(request.id, Number(value)),
    onSuccess: (r) => { setNote(r.message); refresh() },
    onError: (err) => setNote(detail(err, 'Could not set this size.')),
  })
  const dismiss = useMutation({
    mutationFn: () => dismissSizeRequest(request.id),
    onSuccess: refresh,
    onError: (err) => setNote(detail(err, 'Could not close this request.')),
  })
  const valid = Number(value) > 0
  return (
    <li className="flex flex-col gap-2 rounded-lg border p-3 sm:flex-row sm:items-center">
      <div className="min-w-0 flex-1">
        <p className="font-medium">1 {request.unit_name} {request.material} = ? {request.stock_unit_name}</p>
        <p className="text-muted-foreground text-xs">
          {request.waiting > 0 && `${request.waiting} line${request.waiting === 1 ? '' : 's'} waiting: ${request.held_lines.map((l) => l.summary).join('; ')}. `}
          {request.proposed_by_name && `${request.proposed_by_name} says ${request.proposed_one_unit_equals}.`}
        </p>
        {note && <p className="mt-1 text-xs">{note}</p>}
      </div>
      <div className="flex items-center gap-2">
        <Input
          aria-label={`${request.stock_unit_name} in one ${request.unit_name}`}
          inputMode="decimal" className="h-8 w-24" value={value} onChange={(e) => setValue(e.target.value)}
        />
        <span className="text-muted-foreground text-xs">{request.stock_unit_name}</span>
        <Button size="sm" className="h-8 gap-1" disabled={!valid || answer.isPending} onClick={() => answer.mutate()}>
          <Check className="size-3.5" /> Set
        </Button>
        <Button size="icon" variant="ghost" className="size-8" title="Not a size to set" onClick={() => dismiss.mutate()}>
          <X className="size-4" />
        </Button>
      </div>
    </li>
  )
}

export function SizesView() {
  const queryClient = useQueryClient()
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['materials', 'sizes'] })
  const { data: requests } = useQuery({ queryKey: ['materials', 'sizes', 'requests'], queryFn: fetchSizeRequests })
  const { data: sizes } = useQuery({ queryKey: ['materials', 'sizes', 'set'], queryFn: fetchUnitSizes })
  const { data: catalog } = useQuery({
    queryKey: ['materials', 'catalog', 'manage'], queryFn: () => fetchMaterials({ limit: 200 }), staleTime: 30_000,
  })
  const { data: units } = useQuery({ queryKey: ['materials', 'units-of-measure'], queryFn: fetchUnitsOfMeasure, staleTime: 300_000 })

  const [materialId, setMaterialId] = React.useState('')
  const [unitId, setUnitId] = React.useState('')
  const [value, setValue] = React.useState('')
  const [error, setError] = React.useState('')
  const material = catalog?.items.find((m) => m.id === materialId)
  const stock = units?.items.find((u) => u.id === material?.default_unit_id)
  const add = useMutation({
    mutationFn: () => setUnitSize(materialId, unitId, Number(value)),
    onSuccess: () => { setValue(''); setError(''); refresh() },
    onError: (err) => setError(detail(err, 'Could not set this size.')),
  })
  const remove = useMutation({
    mutationFn: ({ m, u }: { m: string; u: string }) => deleteUnitSize(m, u),
    onSuccess: refresh,
  })

  return (
    <div className="flex flex-col gap-6">
      {!!requests?.items.length && (
        <section className="flex flex-col gap-2">
          <h2 className="flex items-center gap-2 text-sm font-semibold"><Ruler className="size-4" /> Sizes asked for</h2>
          <ul className="flex flex-col gap-2">{requests.items.map((r) => <RequestRow key={r.id} request={r} />)}</ul>
        </section>
      )}

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">Sizes set for the company</h2>
        <p className="text-muted-foreground text-xs">
          A delivery or use said in one of these units is converted into the material's stock unit. A wrong one can be
          removed: it is asked again next time; quantities already saved stay as they were.
        </p>
        {sizes?.items.length ? (
          <ul className="divide-y rounded-lg border">
            {sizes.items.map((s) => (
              <li key={`${s.material_id}:${s.from_unit_id}`} className="flex items-center gap-2 px-3 py-2 text-sm">
                <span className="flex-1">1 {s.unit_name} {s.material} = {s.one_unit_equals} {s.stock_unit_name}</span>
                <Button size="icon" variant="ghost" className="size-8" title="Remove this size"
                  onClick={() => remove.mutate({ m: s.material_id, u: s.from_unit_id })}>
                  <Trash2 className="size-4" />
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted-foreground text-sm">No sizes yet.</p>
        )}
      </section>

      <section className="flex flex-col gap-2 rounded-lg border p-3">
        <h2 className="text-sm font-semibold">Add a size</h2>
        <div className="flex flex-wrap items-end gap-2">
          <div className="flex flex-col gap-1">
            <Label className="text-xs">Material</Label>
            <Select value={materialId} onValueChange={setMaterialId}>
              <SelectTrigger className="h-8 w-48"><SelectValue placeholder="Material" /></SelectTrigger>
              <SelectContent>
                {catalog?.items.filter((m) => m.is_active).map((m) => <SelectItem key={m.id} value={m.id}>{m.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1">
            <Label className="text-xs">1 of this unit</Label>
            <Select value={unitId} onValueChange={setUnitId}>
              <SelectTrigger className="h-8 w-36"><SelectValue placeholder="Unit" /></SelectTrigger>
              <SelectContent>
                {units?.items.filter((u) => u.is_active && u.id !== material?.default_unit_id)
                  .map((u) => <SelectItem key={u.id} value={u.id}>{u.display_name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1">
            <Label className="text-xs">= how many {stock?.display_name ?? 'stock units'}</Label>
            <Input inputMode="decimal" className="h-8 w-28" value={value} onChange={(e) => setValue(e.target.value)} />
          </div>
          <Button size="sm" className="h-8" disabled={!materialId || !unitId || !(Number(value) > 0) || add.isPending}
            onClick={() => add.mutate()}>
            Set
          </Button>
        </div>
        {error && <p className="text-destructive text-xs">{error}</p>}
      </section>
    </div>
  )
}
