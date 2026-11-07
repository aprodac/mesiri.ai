import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, MessageCircle, Plus, X } from 'lucide-react'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Combobox } from '@/components/ui/combobox'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useToast } from '@/components/ui/toast-notification'
import { fetchProjects, fetchSites } from '@/lib/projects'
import { fetchMaterialCategories, categoryPaths, fetchMaterials, fetchStockCheck } from '@/lib/materials'
import { asDuplicateConflict, createRequest, qty, updateRequest, type DuplicateConflict, type MaterialRequest } from '@/lib/requests'
import type { AppScope } from '@/lib/scope-types'
import { cn } from '@/lib/utils'
import { CategoryTile } from './parts'

// PRC-22: ask for material. Built for speed: the site is the scope's, several items in one request, each line says
// what the site already holds, and a request that repeats an open one is shown before it is saved.

type Line = { key: number; materialId: string; quantity: string; lineId?: string }
type When = 'today' | 'tomorrow' | 'week' | 'pick'

function iso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function dateFor(when: When, picked: string): string | null {
  const d = new Date()
  if (when === 'today') return iso(d)
  if (when === 'tomorrow') return iso(new Date(d.getTime() + 86_400_000))
  if (when === 'week') return iso(new Date(d.getTime() + ((5 - d.getDay() + 7) % 7 || 7) * 86_400_000))
  return picked || null
}

export function NewRequestDialog({ open, onOpenChange, scope, editing }: { open: boolean; onOpenChange: (open: boolean) => void; scope: AppScope; editing?: MaterialRequest | null }) {
  // PRC-31: with `editing`, the same form changes a waiting request (its site stays).
  const scopedProject = editing ? editing.project_id : scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : ''
  const scopedSite = editing ? editing.site_id : scope.mode === 'site' ? scope.siteId : ''
  const [projectId, setProjectId] = React.useState(scopedProject)
  const [siteId, setSiteId] = React.useState(scopedSite)
  const [lines, setLines] = React.useState<Line[]>([{ key: 1, materialId: '', quantity: '' }])
  const [when, setWhen] = React.useState<When>('tomorrow')
  const [picked, setPicked] = React.useState('')
  const [purpose, setPurpose] = React.useState('')
  const [duplicate, setDuplicate] = React.useState<DuplicateConflict | null>(null)
  const [error, setError] = React.useState('')
  const queryClient = useQueryClient()
  const toast = useToast()

  React.useEffect(() => {
    if (!open) return
    setProjectId(scopedProject)
    setSiteId(scopedSite)
    setLines(editing ? editing.lines.map((l, i) => ({ key: i + 1, materialId: l.material_id, quantity: l.quantity, lineId: l.id })) : [{ key: 1, materialId: '', quantity: '' }])
    setWhen(editing ? 'pick' : 'tomorrow')
    setPicked(editing?.needed_by ?? '')
    setPurpose(editing?.purpose ?? '')
    setDuplicate(null)
    setError('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing?.id])

  // The page's scope can settle after the dialog opened (it picks a project once projects load): follow it.
  React.useEffect(() => {
    if (!open) return
    if (scopedProject) setProjectId(scopedProject)
    if (scopedSite) setSiteId(scopedSite)
  }, [open, scopedProject, scopedSite])

  const { data: projects = [] } = useQuery({ queryKey: ['scope-projects'], queryFn: fetchProjects, enabled: open, staleTime: 60_000 })
  const { data: sites = [] } = useQuery({ queryKey: ['scope-sites', projectId], queryFn: () => fetchSites(projectId), enabled: open && !!projectId, staleTime: 60_000 })
  React.useEffect(() => {
    if (open && !siteId && sites.length === 1) setSiteId(sites[0].id)
  }, [open, siteId, sites])
  const { data: catalog } = useQuery({ queryKey: ['materials', 'catalog', ''], queryFn: () => fetchMaterials({ is_active: true, limit: 200 }), enabled: open, staleTime: 60_000 })
  const { data: categories } = useQuery({ queryKey: ['materials', 'categories'], queryFn: fetchMaterialCategories, enabled: open, staleTime: 60_000 })
  const paths = React.useMemo(() => categoryPaths(categories?.items ?? []), [categories])
  const materials = React.useMemo(() => catalog?.items ?? [], [catalog])
  const options = React.useMemo(() => materials.map((m) => ({ value: m.id, label: m.name })), [materials])

  const save = useMutation({
    mutationFn: (confirm: boolean) => editing
      ? updateRequest(editing.id, {
        lines: lines.filter((l) => l.materialId && Number(l.quantity) > 0).map((l) => ({
          ...(l.lineId ? { id: l.lineId } : {}),
          material_id: l.materialId,
          quantity: l.quantity,
          unit_id: materials.find((m) => m.id === l.materialId)?.default_unit_id ?? '',
        })),
        needed_by: dateFor(when, picked),
        purpose: purpose.trim() || null,
      })
      : createRequest({
        project_id: projectId,
        site_id: siteId,
        lines: lines.filter((l) => l.materialId && Number(l.quantity) > 0).map((l) => ({
          material_id: l.materialId,
          quantity: l.quantity,
          unit_id: materials.find((m) => m.id === l.materialId)?.default_unit_id ?? '',
        })),
        needed_by: dateFor(when, picked),
        purpose: purpose.trim() || null,
        confirm_duplicate: confirm,
      }),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['procurement', 'requests'] })
      toast.success(editing ? `${created.ref} changed` : `${created.ref} sent`, editing ? undefined : 'The office is told on WhatsApp.')
      onOpenChange(false)
    },
    onError: (err) => {
      const dup = asDuplicateConflict(err)
      if (dup) {
        setDuplicate(dup)
        return
      }
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Not sent. Try again.')
    },
  })

  const ready = lines.filter((l) => l.materialId && Number(l.quantity) > 0)
  const canSend = !!projectId && !!siteId && ready.length > 0 && !save.isPending && (when !== 'pick' || !!picked || !!editing)
  const update = (key: number, patch: Partial<Line>) => {
    setDuplicate(null)
    setLines((all) => all.map((l) => (l.key === key ? { ...l, ...patch } : l)))
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{editing ? `Change ${editing.ref}` : 'New request'}</DialogTitle>
        </DialogHeader>
        <form
          className="flex flex-col gap-5"
          onSubmit={(e) => {
            e.preventDefault()
            if (canSend) save.mutate(false)
          }}
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label>Project</Label>
              <Select value={projectId} onValueChange={(v) => { setProjectId(v); setSiteId(''); setDuplicate(null) }} disabled={!!scopedProject || !!editing}>
                <SelectTrigger><SelectValue placeholder="Choose project" /></SelectTrigger>
                <SelectContent>{projects.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>Site</Label>
              <Select value={siteId} onValueChange={(v) => { setSiteId(v); setDuplicate(null) }} disabled={!projectId || !!scopedSite}>
                <SelectTrigger><SelectValue placeholder="Choose site" /></SelectTrigger>
                <SelectContent>{sites.map((s) => <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>)}</SelectContent>
              </Select>
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <Label>Items</Label>
            {lines.map((line) => {
              const material = materials.find((m) => m.id === line.materialId)
              const main = material?.category_id ? paths.get(material.category_id)?.main.name ?? null : null
              return (
                <div key={line.key} className="flex flex-col gap-2 rounded-xl border p-3">
                  <div className="flex items-center gap-2">
                    <CategoryTile mainCategory={main} size="md" />
                    <div className="min-w-0 flex-1">
                      <Combobox options={options} value={line.materialId} onValueChange={(v) => update(line.key, { materialId: v })} placeholder="Item" searchPlaceholder="Name or size" emptyText="Not in your list. Add it in Materials > Items." />
                    </div>
                    <div className="flex w-32 items-center rounded-md border focus-within:ring-2 focus-within:ring-ring">
                      <Input
                        aria-label="Quantity"
                        inputMode="decimal"
                        className="border-0 text-right font-semibold tabular-nums shadow-none focus-visible:ring-0"
                        value={line.quantity}
                        placeholder="0"
                        onChange={(e) => update(line.key, { quantity: e.target.value.replace(/[^0-9.]/g, '') })}
                      />
                      <span className="pr-2.5 text-xs text-muted-foreground">{material?.default_unit ?? ''}</span>
                    </div>
                    {lines.length > 1 && (
                      <Button type="button" variant="ghost" size="icon" aria-label="Remove item" onClick={() => setLines((all) => all.filter((l) => l.key !== line.key))}>
                        <X className="size-4" />
                      </Button>
                    )}
                  </div>
                  {material && siteId && <StockHint materialId={material.id} siteId={siteId} unit={material.default_unit ?? ''} />}
                </div>
              )
            })}
            <Button type="button" variant="outline" className="h-10 justify-start gap-2 border-dashed text-muted-foreground" onClick={() => setLines((all) => [...all, { key: Math.max(...all.map((l) => l.key)) + 1, materialId: '', quantity: '' }])}>
              <Plus className="size-4" /> Add item
            </Button>
          </div>

          <div className="flex flex-col gap-2">
            <Label>Needed by</Label>
            <div role="radiogroup" aria-label="Needed by" className="flex flex-wrap gap-2">
              {(['today', 'tomorrow', 'week', 'pick'] as When[]).map((w) => (
                <button
                  key={w}
                  type="button"
                  role="radio"
                  aria-checked={when === w}
                  onClick={() => setWhen(w)}
                  className={cn('h-9 rounded-full border px-3.5 text-sm font-semibold', when === w ? 'border-foreground bg-foreground text-background' : 'bg-background hover:border-foreground/40')}
                >
                  {{ today: 'Today', tomorrow: 'Tomorrow', week: 'This week', pick: 'Pick a date' }[w]}
                </button>
              ))}
              {when === 'pick' && <Input type="date" aria-label="Date" className="h-9 w-[150px] dark:[color-scheme:dark]" min={editing?.needed_by && editing?.needed_by < iso(new Date()) ? editing?.needed_by : iso(new Date())} value={picked} onChange={(e) => setPicked(e.target.value)} />}
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="request-purpose">Purpose</Label>
            <Input id="request-purpose" value={purpose} maxLength={300} placeholder="First-floor slab" onChange={(e) => setPurpose(e.target.value)} />
          </div>

          {duplicate && (
            <div className="flex flex-col gap-2 rounded-xl border border-orange-300 bg-orange-50 p-3 text-sm text-orange-950 dark:bg-orange-950 dark:text-orange-100">
              <div className="flex items-start gap-2">
                <Copy className="mt-0.5 size-4 shrink-0" />
                <span><strong>Already asked.</strong> {duplicate.message}</span>
              </div>
              <div className="flex flex-wrap gap-2 pl-6">
                <Button type="button" size="sm" variant="outline" onClick={() => onOpenChange(false)}>Don’t send</Button>
                <Button type="button" size="sm" className="bg-orange-600 text-white hover:bg-orange-700" disabled={save.isPending} onClick={() => save.mutate(true)}>It is extra, send anyway</Button>
              </div>
            </div>
          )}
          {error && <p className="text-sm text-destructive" role="alert">{error}</p>}

          <DialogFooter className="items-center gap-2 sm:justify-between">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-success-soft px-2.5 py-1 text-xs text-success"><MessageCircle className="size-3.5" />Site engineers can also ask on WhatsApp</span>
            <span className="flex gap-2">
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
              <Button type="submit" disabled={!canSend || !!duplicate} className="font-semibold">
                {editing ? 'Save changes' : `Send request${ready.length > 1 ? ` · ${ready.length} items` : ''}`}
              </Button>
            </span>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function StockHint({ materialId, siteId, unit }: { materialId: string; siteId: string; unit: string }) {
  const { data } = useQuery({ queryKey: ['materials', 'stock-check', materialId, siteId], queryFn: () => fetchStockCheck(materialId, siteId), staleTime: 30_000 })
  if (!data) return null
  const here = Number(data.available)
  return (
    <span className={cn('w-fit rounded-md px-2 py-0.5 text-xs font-semibold', here > 0 ? 'bg-success-soft text-success' : 'bg-muted text-muted-foreground')}>
      {here > 0 ? `${qty(String(here), unit)} already at this site` : 'None at this site'}
    </span>
  )
}
