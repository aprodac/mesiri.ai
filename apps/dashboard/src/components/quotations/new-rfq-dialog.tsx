import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Store, X } from 'lucide-react'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Combobox } from '@/components/ui/combobox'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useToast } from '@/components/ui/toast-notification'
import { fetchVendorsApi } from '@/lib/api'
import { fetchProjects, fetchSites } from '@/lib/projects'
import { categoryPaths, fetchMaterialCategories, fetchMaterials } from '@/lib/materials'
import { createRfq, type Rfq } from '@/lib/rfqs'
import type { AppScope } from '@/lib/scope-types'
import { cn } from '@/lib/utils'
import { CategoryTile } from '@/components/requests/parts'

// PRC-40: ask suppliers for quotes. From a site's request it opens filled in (its site and what is still to buy, each
// line linked so the request follows the order the award makes); from Rates with the item. Suppliers are picked as
// chips from the company's list (the ones who sold this category before first) or typed new.

export interface RfqPrefill {
  project_id?: string
  site_id?: string
  site_name?: string
  request_id?: string
  request_ref?: string
  lines?: { material_id: string; quantity: string }[]
  suppliers?: string[]
}

type Line = { key: number; materialId: string; quantity: string }
type Due = 'today' | 'tomorrow' | 'three' | 'pick'

function iso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function dueDate(due: Due, picked: string): string | null {
  const d = new Date()
  if (due === 'today') return iso(d)
  if (due === 'tomorrow') return iso(new Date(d.getTime() + 86_400_000))
  if (due === 'three') return iso(new Date(d.getTime() + 3 * 86_400_000))
  return picked || null
}

export function NewRfqDialog({ open, onOpenChange, scope, prefill, onCreated }: {
  open: boolean
  onOpenChange: (open: boolean) => void
  scope: AppScope
  prefill?: RfqPrefill | null
  onCreated?: (rfq: Rfq) => void
}) {
  const scopedProject = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : ''
  const scopedSite = scope.mode === 'site' ? scope.siteId : ''
  const [projectId, setProjectId] = React.useState('')
  const [siteId, setSiteId] = React.useState('')
  const [lines, setLines] = React.useState<Line[]>([])
  const [suppliers, setSuppliers] = React.useState<string[]>([])
  const [typed, setTyped] = React.useState('')
  const [due, setDue] = React.useState<Due>('tomorrow')
  const [picked, setPicked] = React.useState('')
  const [neededBy, setNeededBy] = React.useState('')
  const [terms, setTerms] = React.useState('')
  const [error, setError] = React.useState('')
  const queryClient = useQueryClient()
  const toast = useToast()
  const fromRequest = !!prefill?.request_id

  React.useEffect(() => {
    if (!open) return
    setProjectId(prefill?.project_id ?? scopedProject)
    setSiteId(prefill?.site_id ?? scopedSite)
    setLines(prefill?.lines?.length ? prefill.lines.map((l, i) => ({ key: i + 1, materialId: l.material_id, quantity: l.quantity })) : [{ key: 1, materialId: '', quantity: '' }])
    setSuppliers(prefill?.suppliers ?? [])
    setTyped('')
    setDue('tomorrow')
    setPicked('')
    setNeededBy('')
    setTerms('Delivery to site included. Rates valid for 15 days.')
    setError('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, prefill])

  const { data: projects = [] } = useQuery({ queryKey: ['scope-projects'], queryFn: fetchProjects, enabled: open, staleTime: 60_000 })
  const { data: sites = [] } = useQuery({ queryKey: ['scope-sites', projectId], queryFn: () => fetchSites(projectId), enabled: open && !!projectId, staleTime: 60_000 })
  React.useEffect(() => {
    if (open && projectId && !siteId && sites.length === 1) setSiteId(sites[0].id)
  }, [open, projectId, siteId, sites])
  const { data: vendors = [] } = useQuery({ queryKey: ['finance', 'vendors', 'names'], queryFn: fetchVendorsApi, enabled: open, retry: false, staleTime: 60_000 })
  const { data: catalog } = useQuery({ queryKey: ['materials', 'catalog', ''], queryFn: () => fetchMaterials({ is_active: true, limit: 200 }), enabled: open, staleTime: 60_000 })
  const { data: categories } = useQuery({ queryKey: ['materials', 'categories'], queryFn: fetchMaterialCategories, enabled: open, staleTime: 60_000 })
  const paths = React.useMemo(() => categoryPaths(categories?.items ?? []), [categories])
  const materials = React.useMemo(() => catalog?.items ?? [], [catalog])
  const options = React.useMemo(() => materials.map((m) => ({ value: m.id, label: m.name })), [materials])
  const suggested = React.useMemo(() => vendors.filter((v) => v.status === 'active' && !suppliers.some((s) => s.toLowerCase() === v.name.toLowerCase())).slice(0, 8), [vendors, suppliers])

  const ready = lines.filter((l) => l.materialId && Number(l.quantity) > 0)
  const addSupplier = (name: string) => {
    const clean = name.trim()
    if (clean && !suppliers.some((s) => s.toLowerCase() === clean.toLowerCase())) setSuppliers((all) => [...all, clean])
    setTyped('')
  }
  const update = (key: number, patch: Partial<Line>) => setLines((all) => all.map((l) => (l.key === key ? { ...l, ...patch } : l)))

  const save = useMutation({
    mutationFn: () => createRfq(fromRequest
      ? { request_id: prefill!.request_id, suppliers, due_date: dueDate(due, picked), needed_by: neededBy || null, terms: terms.trim() || null }
      : {
        project_id: projectId, site_id: siteId, suppliers, due_date: dueDate(due, picked), needed_by: neededBy || null, terms: terms.trim() || null,
        lines: ready.map((l) => ({ material_id: l.materialId, quantity: l.quantity, unit_id: materials.find((m) => m.id === l.materialId)?.default_unit_id ?? '' })),
      }),
    onSuccess: (rfq) => {
      queryClient.invalidateQueries({ queryKey: ['procurement'] })
      toast.success(`${rfq.ref} ready to send`, `Send it to ${rfq.suppliers.length} supplier${rfq.suppliers.length === 1 ? '' : 's'} on WhatsApp from the next screen.`)
      onCreated?.(rfq)
      onOpenChange(false)
    },
    onError: (err) => {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Not saved. Try again.')
    },
  })
  const canSave = (fromRequest || (!!projectId && !!siteId && ready.length > 0)) && suppliers.length > 0 && !save.isPending && (due !== 'pick' || !!picked)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Ask for quotes{prefill?.request_ref ? ` · for ${prefill.request_ref}` : ''}</DialogTitle>
        </DialogHeader>
        <form className="flex flex-col gap-5" onSubmit={(e) => { e.preventDefault(); if (canSave) save.mutate() }}>
          {!fromRequest && (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <Label>Project</Label>
                <Select value={projectId} onValueChange={(v) => { setProjectId(v); setSiteId('') }}>
                  <SelectTrigger><SelectValue placeholder="Choose project" /></SelectTrigger>
                  <SelectContent>{projects.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>Deliver to site</Label>
                <Select value={siteId} onValueChange={setSiteId} disabled={!projectId}>
                  <SelectTrigger><SelectValue placeholder="Choose site" /></SelectTrigger>
                  <SelectContent>{sites.map((s) => <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>)}</SelectContent>
                </Select>
              </div>
            </div>
          )}

          <div className="flex flex-col gap-2">
            <Label>Items{fromRequest ? <span className="font-normal text-muted-foreground"> · what {prefill?.request_ref} still needs, at {prefill?.site_name}</span> : null}</Label>
            {lines.map((line) => {
              const material = materials.find((m) => m.id === line.materialId)
              const main = material?.category_id ? paths.get(material.category_id)?.main.name ?? null : null
              return (
                <div key={line.key} className="flex flex-wrap items-center gap-2 rounded-xl border p-2.5">
                  <CategoryTile mainCategory={main} />
                  <div className="min-w-[180px] flex-1">
                    <Combobox options={options} value={line.materialId} onValueChange={(v) => update(line.key, { materialId: v })} placeholder="Item" searchPlaceholder="Name or size" emptyText="Not in your list. Add it in Materials > Items." disabled={fromRequest} />
                  </div>
                  <div className="flex w-36 items-center rounded-md border focus-within:ring-2 focus-within:ring-ring">
                    <Input aria-label="Quantity" inputMode="decimal" className="border-0 text-right font-semibold tabular-nums shadow-none focus-visible:ring-0" value={line.quantity} placeholder="0" disabled={fromRequest} onChange={(e) => update(line.key, { quantity: e.target.value.replace(/[^0-9.]/g, '') })} />
                    <span className="pr-2.5 text-xs text-muted-foreground">{material?.default_unit ?? ''}</span>
                  </div>
                  {lines.length > 1 && !fromRequest && <Button type="button" variant="ghost" size="icon" aria-label="Remove item" onClick={() => setLines((all) => all.filter((l) => l.key !== line.key))}><X className="size-4" /></Button>}
                </div>
              )
            })}
            {!fromRequest && (
              <Button type="button" variant="outline" className="h-10 justify-start gap-2 border-dashed text-muted-foreground" onClick={() => setLines((all) => [...all, { key: Math.max(0, ...all.map((l) => l.key)) + 1, materialId: '', quantity: '' }])}>
                <Plus className="size-4" /> Add item
              </Button>
            )}
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="rfq-supplier">Suppliers to ask <span className="font-normal text-muted-foreground">· three is usual</span></Label>
            <div className="flex flex-wrap items-center gap-1.5 rounded-xl border p-2 focus-within:ring-2 focus-within:ring-ring">
              {suppliers.map((s) => (
                <span key={s} className="inline-flex h-8 items-center gap-1 rounded-full bg-foreground pl-3 pr-1 text-sm font-semibold text-background">
                  {s}
                  <button type="button" aria-label={`Remove ${s}`} className="inline-flex size-6 items-center justify-center rounded-full hover:bg-background/20" onClick={() => setSuppliers((all) => all.filter((x) => x !== s))}><X className="size-3.5" /></button>
                </span>
              ))}
              <span className="flex min-w-[160px] flex-1 items-center gap-2 px-1">
                <Store className="size-4 text-muted-foreground" />
                <input id="rfq-supplier" list="rfq-vendors" className="h-8 flex-1 bg-transparent text-sm outline-none" placeholder={suppliers.length ? 'Add another' : 'Type a supplier, Enter to add'} value={typed}
                  onChange={(e) => setTyped(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addSupplier(typed) } }} onBlur={() => typed && addSupplier(typed)} />
              </span>
              <datalist id="rfq-vendors">{vendors.map((v) => <option key={v.id} value={v.name} />)}</datalist>
            </div>
            {suggested.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {suggested.map((v) => (
                  <button key={v.id} type="button" onClick={() => addSupplier(v.name)} className="inline-flex h-7 items-center gap-1 rounded-full border bg-background px-2.5 text-xs hover:border-foreground/40"><Plus className="size-3" />{v.name}</button>
                ))}
              </div>
            )}
          </div>

          <div className="flex flex-col gap-2">
            <Label>Quotes wanted by</Label>
            <div role="radiogroup" aria-label="Quotes wanted by" className="flex flex-wrap gap-2">
              {(['today', 'tomorrow', 'three', 'pick'] as Due[]).map((w) => (
                <button key={w} type="button" role="radio" aria-checked={due === w} onClick={() => setDue(w)} className={cn('h-9 rounded-full border px-3.5 text-sm font-semibold', due === w ? 'border-foreground bg-foreground text-background' : 'bg-background hover:border-foreground/40')}>
                  {{ today: 'Today', tomorrow: 'Tomorrow', three: 'In 3 days', pick: 'Pick a date' }[w]}
                </button>
              ))}
              {due === 'pick' && <Input type="date" aria-label="Date" className="h-9 w-[150px] dark:[color-scheme:dark]" min={iso(new Date())} value={picked} onChange={(e) => setPicked(e.target.value)} />}
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-[180px_1fr]">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="rfq-needed">Site needs it by</Label>
              <Input id="rfq-needed" type="date" className="dark:[color-scheme:dark]" value={neededBy} onChange={(e) => setNeededBy(e.target.value)} />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="rfq-terms">Terms for the suppliers</Label>
              <Input id="rfq-terms" value={terms} maxLength={500} onChange={(e) => setTerms(e.target.value)} />
            </div>
          </div>

          {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
          <DialogFooter className="items-center gap-2 sm:justify-between">
            <span className="text-sm text-muted-foreground">{suppliers.length ? `${suppliers.length} supplier${suppliers.length === 1 ? '' : 's'} · ${fromRequest ? (prefill?.lines?.length ?? 0) : ready.length} item${(fromRequest ? (prefill?.lines?.length ?? 0) : ready.length) === 1 ? '' : 's'}` : 'Add at least one supplier'}</span>
            <span className="flex gap-2">
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
              <Button type="submit" disabled={!canSave} className="font-semibold">Create RFQ</Button>
            </span>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
