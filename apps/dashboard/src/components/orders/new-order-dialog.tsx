import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Plus, Store, X } from 'lucide-react'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Combobox } from '@/components/ui/combobox'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useToast } from '@/components/ui/toast-notification'
import { useAuth } from '@/lib/AuthContext'
import { fetchVendorsApi } from '@/lib/api'
import { fetchProjects, fetchSites } from '@/lib/projects'
import { categoryPaths, fetchLastPurchase, fetchMaterialCategories, fetchMaterials } from '@/lib/materials'
import { asDuplicateConflict, fetchRequests, qty } from '@/lib/requests'
import { createOrder, rupees, updateOrder, type PurchaseOrder } from '@/lib/orders'
import type { AppScope } from '@/lib/scope-types'
import { cn } from '@/lib/utils'
import { CategoryTile } from '@/components/requests/parts'

// PRC-06/07: place an order with a supplier. From a request (PRC-22) it opens filled in: the request's site and
// what is still to buy, each line linked to the request so the request follows the order. The duplicate check
// (an open order in the project for the same material) is shown before anything is saved.

export interface OrderPrefill {
  project_id: string
  site_id: string
  site_name?: string
  request_ref?: string
  /** PRC-24: the request it comes from; other waiting requests at the same site can be added to the same order. */
  request_id?: string
  lines: { material_id: string; quantity: string; request_line_id?: string }[]
}

type Line = { key: number; materialId: string; quantity: string; rate: string; requestLineId?: string; requestRef?: string }
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

export function NewOrderDialog({ open, onOpenChange, scope, prefill, editing }: { open: boolean; onOpenChange: (open: boolean) => void; scope: AppScope; prefill?: OrderPrefill | null; editing?: PurchaseOrder | null }) {
  const { me } = useAuth()
  const seesMoney = ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE', 'PROJECT_MANAGER'].includes((me?.role || '').toUpperCase())
  const scopedProject = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : ''
  const scopedSite = scope.mode === 'site' ? scope.siteId : ''
  const [projectId, setProjectId] = React.useState('')
  const [siteId, setSiteId] = React.useState('')
  const [supplier, setSupplier] = React.useState('')
  const [lines, setLines] = React.useState<Line[]>([])
  const [when, setWhen] = React.useState<When>('tomorrow')
  const [picked, setPicked] = React.useState('')
  const [notes, setNotes] = React.useState('')
  const [theirRef, setTheirRef] = React.useState('')
  const [duplicate, setDuplicate] = React.useState<{ message: string; request: boolean } | null>(null)
  const [error, setError] = React.useState('')
  const queryClient = useQueryClient()
  const toast = useToast()

  React.useEffect(() => {
    if (!open) return
    // PRC-31: with `editing`, the same form changes an order nothing has come against yet (its site stays).
    setProjectId(editing?.project_id ?? prefill?.project_id ?? scopedProject)
    setSiteId(editing?.site_id ?? prefill?.site_id ?? scopedSite)
    setLines(editing
      ? editing.lines.map((l, i) => ({ key: i + 1, materialId: l.material_id, quantity: l.quantity, rate: l.rate ? String(Number(l.rate)) : '', requestLineId: l.request?.line_id, requestRef: l.request?.ref }))
      : prefill?.lines.length
        ? prefill.lines.map((l, i) => ({ key: i + 1, materialId: l.material_id, quantity: l.quantity, rate: '', requestLineId: l.request_line_id, requestRef: prefill.request_ref }))
        : [{ key: 1, materialId: '', quantity: '', rate: '' }])
    setSupplier(editing?.vendor_name ?? '')
    setWhen(editing ? 'pick' : 'tomorrow')
    setPicked(editing?.expected_date ?? '')
    setNotes(editing ? editing.notes ?? '' : prefill?.request_ref ? `For ${prefill.request_ref}` : '')
    setTheirRef(editing?.their_ref ?? '')
    setDuplicate(null)
    setError('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, prefill, editing?.id])

  const { data: projects = [] } = useQuery({ queryKey: ['scope-projects'], queryFn: fetchProjects, enabled: open, staleTime: 60_000 })
  const { data: sites = [] } = useQuery({ queryKey: ['scope-sites', projectId], queryFn: () => fetchSites(projectId), enabled: open && !!projectId, staleTime: 60_000 })
  React.useEffect(() => {
    if (open && projectId && !siteId && sites.length === 1) setSiteId(sites[0].id)
  }, [open, projectId, siteId, sites])
  const { data: vendors = [] } = useQuery({ queryKey: ['finance', 'vendors', 'names'], queryFn: fetchVendorsApi, enabled: open, retry: false, staleTime: 60_000 })
  const vendorNames = React.useMemo(() => vendors.filter((v) => v.status === 'active').map((v) => v.name), [vendors])
  const { data: catalog } = useQuery({ queryKey: ['materials', 'catalog', ''], queryFn: () => fetchMaterials({ is_active: true, limit: 200 }), enabled: open, staleTime: 60_000 })
  const { data: categories } = useQuery({ queryKey: ['materials', 'categories'], queryFn: fetchMaterialCategories, enabled: open, staleTime: 60_000 })
  const paths = React.useMemo(() => categoryPaths(categories?.items ?? []), [categories])
  const materials = React.useMemo(() => catalog?.items ?? [], [catalog])
  const options = React.useMemo(() => materials.map((m) => ({ value: m.id, label: m.name })), [materials])

  // PRC-24: other requests waiting at the same site, to put in this one order (from a request only).
  const { data: siteRequests } = useQuery({
    queryKey: ['procurement', 'requests', 'site', siteId],
    queryFn: () => fetchRequests({ site_id: siteId }),
    enabled: open && !!prefill && !editing && !!siteId,
    staleTime: 30_000,
  })
  const added = new Set(lines.map((l) => l.requestLineId).filter(Boolean))
  const alsoWaiting = (siteRequests?.items ?? []).filter((r) => r.status === 'waiting' && r.id !== prefill?.request_id && !r.lines.some((l) => added.has(l.id)))
  const addRequest = (r: (typeof alsoWaiting)[number]) => {
    setDuplicate(null)
    // The note written for them ("For REQ-0002") follows the requests in the order; their own words are kept.
    setNotes((n) => (/^For (REQ-\d+(, )?)+$/.test(n) ? `${n}, ${r.ref}` : n))
    setLines((all) => [...all, ...r.lines.map((l, i) => ({
      key: Math.max(0, ...all.map((x) => x.key)) + i + 1, materialId: l.material_id,
      quantity: Number(l.to_buy) > 0 ? l.to_buy : l.quantity, rate: '', requestLineId: l.id, requestRef: r.ref,
    }))])
  }
  const fromRequests = [...new Set(lines.map((l) => l.requestRef).filter(Boolean))]

  const ready = lines.filter((l) => l.materialId && Number(l.quantity) > 0)
  const total = ready.reduce((n, l) => n + (Number(l.rate) || 0) * Number(l.quantity), 0)

  const orderLines = ready.map((l) => ({
    material_id: l.materialId,
    quantity: l.quantity,
    unit_id: materials.find((m) => m.id === l.materialId)?.default_unit_id ?? '',
    rate: l.rate ? l.rate : null,
    request_line_id: l.requestLineId ?? null,
  }))
  const save = useMutation({
    mutationFn: (confirm: boolean) => editing
      ? updateOrder(editing.id, { supplier: supplier.trim(), lines: orderLines, expected_date: dateFor(when, picked), notes: notes.trim() || null, their_ref: theirRef.trim() || null })
      : createOrder({
        project_id: projectId,
        site_id: siteId,
        supplier: supplier.trim(),
        lines: orderLines,
        expected_date: dateFor(when, picked),
        notes: notes.trim() || null,
        their_ref: theirRef.trim() || null,
        confirm_duplicate: confirm,
      }),
    onSuccess: (po) => {
      queryClient.invalidateQueries({ queryKey: ['procurement'] })
      if (editing) toast.success(`${po.ref} changed`)
      else toast.success(`${po.ref} placed with ${po.vendor_name}`, fromRequests.length ? `${fromRequests.join(', ')} ${fromRequests.length > 1 ? 'are' : 'is'} marked ordered; whoever asked is told.` : undefined)
      onOpenChange(false)
    },
    onError: (err) => {
      const dup = asDuplicateConflict(err)
      // PRC-23: the same material already on an open order, or a site's waiting request for it (order from the request).
      if (dup) return setDuplicate({ message: dup.message, request: !dup.duplicates?.length && !!dup.requests?.length })
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Not placed. Try again.')
    },
  })

  const canSave = !!projectId && !!siteId && !!supplier.trim() && ready.length > 0 && !save.isPending && (when !== 'pick' || !!picked || !!editing)
  const update = (key: number, patch: Partial<Line>) => {
    setDuplicate(null)
    setLines((all) => all.map((l) => (l.key === key ? { ...l, ...patch } : l)))
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{editing ? `Change ${editing.ref}` : `New purchase order${fromRequests.length ? ` · for ${fromRequests.join(', ')}` : ''}`}</DialogTitle>
        </DialogHeader>
        <form className="flex flex-col gap-5" onSubmit={(e) => { e.preventDefault(); if (canSave) save.mutate(false) }}>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="po-supplier">Supplier</Label>
            <div className="flex items-center gap-2 rounded-md border px-3 focus-within:ring-2 focus-within:ring-ring">
              <Store className="size-4 text-muted-foreground" />
              <input id="po-supplier" list="po-vendors" autoFocus className="h-10 flex-1 bg-transparent text-sm outline-none" placeholder="Malabar Hardware" value={supplier} onChange={(e) => { setSupplier(e.target.value); setDuplicate(null) }} />
            </div>
            <datalist id="po-vendors">{vendorNames.map((n) => <option key={n} value={n} />)}</datalist>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label>Project</Label>
              <Select value={projectId} onValueChange={(v) => { setProjectId(v); setSiteId(''); setDuplicate(null) }} disabled={!!prefill || !!editing}>
                <SelectTrigger><SelectValue placeholder="Choose project" /></SelectTrigger>
                <SelectContent>{projects.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>Deliver to site</Label>
              <Select value={siteId} onValueChange={(v) => { setSiteId(v); setDuplicate(null) }} disabled={!projectId || !!prefill || !!editing}>
                <SelectTrigger><SelectValue placeholder={prefill?.site_name ?? 'Choose site'} /></SelectTrigger>
                <SelectContent>{sites.map((s) => <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>)}</SelectContent>
              </Select>
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <Label>Items</Label>
            {lines.map((line) => {
              const material = materials.find((m) => m.id === line.materialId)
              const main = material?.category_id ? paths.get(material.category_id)?.main.name ?? null : null
              const unit = material?.default_unit ?? ''
              return (
                <div key={line.key} className="flex flex-col gap-2 rounded-xl border p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <CategoryTile mainCategory={main} />
                    <div className="min-w-[180px] flex-1">
                      <Combobox options={options} value={line.materialId} onValueChange={(v) => update(line.key, { materialId: v })} placeholder="Item" searchPlaceholder="Name or size" emptyText="Not in your list. Add it in Materials > Items." disabled={!!line.requestLineId} />
                    </div>
                    <div className="flex w-32 items-center rounded-md border focus-within:ring-2 focus-within:ring-ring">
                      <Input aria-label="Quantity" inputMode="decimal" className="border-0 text-right font-semibold tabular-nums shadow-none focus-visible:ring-0" value={line.quantity} placeholder="0" onChange={(e) => update(line.key, { quantity: e.target.value.replace(/[^0-9.]/g, '') })} />
                      <span className="pr-2.5 text-xs text-muted-foreground">{unit}</span>
                    </div>
                    {seesMoney && (
                      <div className="flex w-36 items-center rounded-md border focus-within:ring-2 focus-within:ring-ring">
                        <span className="pl-2.5 text-sm text-muted-foreground">₹</span>
                        <Input aria-label="Rate" inputMode="decimal" className="border-0 text-right tabular-nums shadow-none focus-visible:ring-0" value={line.rate} placeholder="Rate" onChange={(e) => update(line.key, { rate: e.target.value.replace(/[^0-9.]/g, '') })} />
                        <span className="pr-2.5 text-xs text-muted-foreground">/{unit || 'unit'}</span>
                      </div>
                    )}
                    {lines.length > 1 && (
                      <Button type="button" variant="ghost" size="icon" aria-label="Remove item" onClick={() => setLines((all) => all.filter((l) => l.key !== line.key))}><X className="size-4" /></Button>
                    )}
                  </div>
                  {material && seesMoney && <LastRate materialId={material.id} unit={unit} onUse={(r) => !line.rate && update(line.key, { rate: r })} />}
                  {line.requestLineId && <span className="w-fit rounded-md bg-muted px-2 py-0.5 text-xs font-semibold">From {line.requestRef}</span>}
                </div>
              )
            })}
            {prefill && !editing && (
              <p className="text-xs text-muted-foreground">Order part of it here: lower a quantity or take an item off, and the rest stays to buy for another supplier.</p>
            )}
            {alsoWaiting.length > 0 && (
              <div className="flex flex-col gap-1.5 rounded-xl border border-dashed p-3">
                <span className="text-xs font-semibold text-muted-foreground">Also waiting at {prefill?.site_name ?? 'this site'}: add to this order</span>
                <div className="flex flex-wrap gap-1.5">
                  {alsoWaiting.slice(0, 6).map((r) => (
                    <button key={r.id} type="button" onClick={() => addRequest(r)} className="inline-flex items-center gap-1.5 rounded-full border bg-background px-2.5 py-1 text-xs hover:border-foreground/40">
                      <Plus className="size-3" /><span className="font-semibold tabular-nums">{r.ref}</span>
                      {r.lines.map((l) => `${qty(Number(l.to_buy) > 0 ? l.to_buy : l.quantity, l.unit)} ${l.material}`).join(', ')}
                      {r.requested_by_name ? ` · ${r.requested_by_name.split(' ')[0]}` : ''}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {(!prefill || editing) && (
              <Button type="button" variant="outline" className="h-10 justify-start gap-2 border-dashed text-muted-foreground" onClick={() => setLines((all) => [...all, { key: Math.max(0, ...all.map((l) => l.key)) + 1, materialId: '', quantity: '', rate: '' }])}>
                <Plus className="size-4" /> Add item
              </Button>
            )}
          </div>

          <div className="flex flex-col gap-2">
            <Label>Expected by</Label>
            <div role="radiogroup" aria-label="Expected by" className="flex flex-wrap gap-2">
              {(['today', 'tomorrow', 'week', 'pick'] as When[]).map((w) => (
                <button key={w} type="button" role="radio" aria-checked={when === w} onClick={() => setWhen(w)} className={cn('h-9 rounded-full border px-3.5 text-sm font-semibold', when === w ? 'border-foreground bg-foreground text-background' : 'bg-background hover:border-foreground/40')}>
                  {{ today: 'Today', tomorrow: 'Tomorrow', week: 'This week', pick: 'Pick a date' }[w]}
                </button>
              ))}
              {when === 'pick' && <Input type="date" aria-label="Date" className="h-9 w-[150px] dark:[color-scheme:dark]" min={editing?.expected_date && editing?.expected_date < iso(new Date()) ? editing?.expected_date : iso(new Date())} value={picked} onChange={(e) => setPicked(e.target.value)} />}
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_200px]">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="po-notes">Notes</Label>
              <Input id="po-notes" value={notes} maxLength={500} placeholder="Unload at the back gate" onChange={(e) => setNotes(e.target.value)} />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="po-their-ref">Their number <span className="font-normal text-muted-foreground">(optional)</span></Label>
              <Input id="po-their-ref" value={theirRef} maxLength={60} placeholder="Paper PO, quote no." onChange={(e) => setTheirRef(e.target.value)} />
            </div>
          </div>

          {duplicate && (
            <div className="flex flex-col gap-2 rounded-xl border border-orange-300 bg-orange-50 p-3 text-sm text-orange-950 dark:bg-orange-950 dark:text-orange-100">
              <div className="flex items-start gap-2"><Copy className="mt-0.5 size-4 shrink-0" /><span><strong>{duplicate.request ? 'A site asked for this.' : 'Already on order.'}</strong> {duplicate.message}</span></div>
              <div className="flex flex-wrap gap-2 pl-6">
                <Button type="button" size="sm" variant="outline" onClick={() => onOpenChange(false)}>Don’t order</Button>
                <Button type="button" size="sm" className="bg-orange-600 text-white hover:bg-orange-700" disabled={save.isPending} onClick={() => save.mutate(true)}>{duplicate.request ? 'Order it separately' : 'It is extra, order anyway'}</Button>
              </div>
            </div>
          )}
          {error && <p className="text-sm text-destructive" role="alert">{error}</p>}

          <DialogFooter className="items-center gap-2 sm:justify-between">
            <span className="text-sm text-muted-foreground">{seesMoney && total > 0 ? <>Order value <strong className="text-foreground tabular-nums">{rupees(total)}</strong></> : ready.length ? `${ready.length} item${ready.length > 1 ? 's' : ''}` : ''}</span>
            <span className="flex gap-2">
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
              <Button type="submit" disabled={!canSave || !!duplicate} className="font-semibold">{editing ? 'Save changes' : 'Place order'}</Button>
            </span>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function LastRate({ materialId, unit, onUse }: { materialId: string; unit: string; onUse: (rate: string) => void }) {
  const { data } = useQuery({ queryKey: ['materials', 'last-purchase', materialId], queryFn: () => fetchLastPurchase(materialId), staleTime: 60_000 })
  if (!data?.unit_cost) return null
  const rate = String(Number(data.unit_cost))
  return (
    <button type="button" onClick={() => onUse(rate)} className="w-fit rounded-md bg-muted px-2 py-0.5 text-left text-xs hover:bg-muted/70">
      Last time ₹{Number(data.unit_cost).toLocaleString('en-IN')} / {unit}{data.supplier ? ` from ${data.supplier}` : ''}{data.occurred_date ? `, ${new Date(`${data.occurred_date}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}` : ''} · <span className="font-semibold underline">use it</span>
    </button>
  )
}

