import * as React from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, CircleSlash2, FolderTree, IndianRupee, MoreHorizontal, Pencil, Plus, Ruler, Search, ShieldAlert, Snail, Target } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Callout } from '@/components/dpr-page'
import { CHIP } from '@/lib/site-day'
import { cn } from '@/lib/utils'
import {
  categoryLabel,
  categoryPaths,
  categoryTree,
  fetchMaterialCategories,
  fetchAllMaterials,
  fetchUnitsOfMeasure,
  createMaterial,
  deleteMaterial,
  updateMaterial,
  type MaterialCatalog,
  type MaterialCategory,
} from '@/lib/materials'
import { CategoriesPanel } from './categories-panel'
import { ImportDialog } from './import-dialog'
import { CategoryTile } from '@/components/requests/parts'
import { ActionIcon } from '@/components/page/action-button'
import { Pill, ToggleChip } from '@/components/page/page-kit'
import { fetchStockSummary as fetchStock } from '@/lib/materials'
import { appNow } from '@/lib/clock'
import { useUrlState } from '@/lib/url-state'
import { toLocalISODate } from '@/lib/utils'
import { qty as qtyWords } from '@/lib/site-day'

// Radix Select can't hold an empty value; this stands for "no category".
const NO_CATEGORY = 'none'

// Admin-only Materials Catalog management -- a tab on the Materials page
// (see MaterialsPage.tsx) alongside Inventory/Inflows/Outflows, not a modal:
// it used to be a dialog, which put a full CRUD table half off-screen inside
// a small popup. This is reference-data upkeep, not a daily operational
// surface, but it's still a real page-shaped view, not a modal-shaped one.
// A material's Stock Unit (default_unit_id) can't change once it has any
// recorded movement (backend PATCH /materials/{id} enforces this) -- the
// unit select is disabled for such rows rather than letting the user pick a
// value the save will just reject.
// WEB-29: grouped by category, search, form folded away until needed,
// delete confirmed in a dialog; bulk select (activate / deactivate /
// delete) removed.
// PRC-01: grouped by the company's category tree (main › sub) instead of the
// free-text group; materials with no category are listed last, each with a
// picker to place it, and the old group shown as a hint.
// WEB-50: Materials > Items. The view switch, search and a category filter on one toolbar row; Categories, Sizes and
// the import open in place instead of being separate tabs.
export function CatalogueView({ leading, sizes }: { leading?: React.ReactNode; sizes?: React.ReactNode } = {}) {
  const queryClient = useQueryClient()

  const [editingMaterial, setEditingMaterial] = React.useState<MaterialCatalog | null>(null)
  const [name, setName] = React.useState('')
  const [unitId, setUnitId] = React.useState('')
  const [categoryId, setCategoryId] = React.useState(NO_CATEGORY)
  const [panelOpen, setPanelOpen] = React.useState(false)
  const [importOpen, setImportOpen] = React.useState(false)
  const [sizesOpen, setSizesOpen] = React.useState(false)
  // UX-69 (asked 18 Nov: "Items, focus on the categorisation"): the category tree is the page's navigation. `pick` is
  // 'all', a main category's id, 's:' + a sub-category's id, or 'none' (no category); kept in the address.
  const [pick, setPick] = useUrlState<string>('cat', 'all')
  const onlySub = pick.startsWith('s:') ? pick.slice(2) : null

  const [sku, setSku] = React.useState('')
  const [error, setError] = React.useState('')
  // UX-69: what each item holds and costs, from the last 90 days' stock (every site this person sees), and chips for
  // what to tidy: no rate yet, no minimum set anywhere, not used in 90 days. Each chip is also a filter.
  const [fix, setFix] = React.useState<'' | 'rate' | 'min' | 'idle'>('')
  const since = React.useMemo(() => { const d = appNow(); d.setDate(d.getDate() - 90); return toLocalISODate(d) }, [])
  const { data: stock } = useQuery({ queryKey: ['materials', 'stock-summary', { date_from: since, date_to: toLocalISODate(), all: true }], queryFn: () => fetchStock({ date_from: since, date_to: toLocalISODate() }), staleTime: 60_000, retry: false })
  const held = React.useMemo(() => {
    const m = new Map<string, { onHand: number; used: number; rate: string | null; min: boolean; money: boolean }>()
    for (const r of stock ?? []) {
      const x = m.get(r.material_id) ?? { onHand: 0, used: 0, rate: null, min: false, money: false }
      x.onHand += Number(r.closing)
      x.used += Number(r.used)
      x.rate = r.last_rate ?? x.rate
      x.min = x.min || Number(r.min_qty ?? 0) > 0
      x.money = x.money || r.spend !== null
      m.set(r.material_id, x)
    }
    return m
  }, [stock])
  const seesMoney = (stock ?? []).some((r) => r.spend !== null)
  const needs = (m: MaterialCatalog, f: 'rate' | 'min' | 'idle') => {
    const h = held.get(m.id)
    if (!m.is_active) return false
    if (f === 'rate') return seesMoney && !h?.rate
    if (f === 'min') return !!h && h.onHand > 0 && !h.min
    return !h || h.used <= 0
  }

  const { data: catalog } = useQuery({
    queryKey: ['materials', 'catalog', 'manage'],
    queryFn: () => fetchAllMaterials(),
    staleTime: 30_000,
  })

  const { data: categoryList } = useQuery({
    queryKey: ['materials', 'categories'],
    queryFn: fetchMaterialCategories,
    staleTime: 30_000,
  })
  const categories = React.useMemo(() => categoryList?.items ?? [], [categoryList])
  const onlyCategory = onlySub ? (categories.find((c) => c.id === onlySub)?.parent_id ?? 'all') : pick
  const paths = React.useMemo(() => categoryPaths(categories), [categories])
  const tree = React.useMemo(() => categoryTree(categories), [categories])
  const chosenCategory = categoryId === NO_CATEGORY ? null : categoryId

  const placeMutation = useMutation({
    mutationFn: ({ id, category }: { id: string; category: string }) => updateMaterial(id, { category_id: category }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['materials'] }),
  })

  const { data: units } = useQuery({
    queryKey: ['materials', 'units-of-measure'],
    queryFn: fetchUnitsOfMeasure,
    staleTime: 5 * 60_000,
  })

  const createMutation = useMutation({
    mutationFn: () =>
      createMaterial({
        name: name.trim(),
        default_unit_id: unitId,
        category_id: chosenCategory,
        sku: sku.trim() || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['materials'] })
      setName('')
      setUnitId('')
      setCategoryId(NO_CATEGORY)
      setSku('')
      setError('')
    },
    onError: (err: any) => {
      setError(err.response?.data?.detail || 'Failed to add material.')
    },
  })

  const updateMutation = useMutation({
    mutationFn: () =>
      updateMaterial(editingMaterial!.id, {
        name: name.trim(),
        default_unit_id: unitId,
        category_id: chosenCategory,
        sku: sku.trim() || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['materials'] })
      setEditingMaterial(null)
      setName('')
      setUnitId('')
      setCategoryId(NO_CATEGORY)
      setSku('')
      setError('')
    },
    onError: (err: any) => {
      setError(err.response?.data?.detail || 'Failed to update material.')
    },
  })

  const toggleActiveMutation = useMutation({
    mutationFn: ({ id, isActive }: { id: string; isActive: boolean }) =>
      updateMaterial(id, { is_active: isActive }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['materials'] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: deleteMaterial,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['materials'] })
    },
    onError: (err: any) => {
      setError(err.response?.data?.detail || 'Failed to delete material.')
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (!name.trim()) {
      setError('Name is required.')
      return
    }
    if (!unitId) {
      setError('Stock Unit is required.')
      return
    }
    if (editingMaterial) {
      updateMutation.mutate()
    } else {
      createMutation.mutate()
    }
  }

  const handleEditClick = (m: MaterialCatalog) => {
    setEditingMaterial(m)
    setName(m.name)
    setUnitId(m.default_unit_id)
    setCategoryId(m.category_id ?? NO_CATEGORY)
    setSku(m.sku ?? '')
    setError('')
  }

  const handleCancelEdit = () => {
    setEditingMaterial(null)
    setName('')
    setUnitId('')
    setCategoryId(NO_CATEGORY)
    setSku('')
    setError('')
  }

  const [deleting, setDeleting] = React.useState<MaterialCatalog | null>(null)
  const [formOpen, setFormOpen] = React.useState(false)
  const [search, setSearch] = React.useState('')
  const unitName = (m: MaterialCatalog) => units?.items.find((u) => u.id === m.default_unit_id)?.display_name ?? m.default_unit ?? '—'
  // One section per main category, in the tree's order; inside it, the materials placed on the main
  // category itself, then one group per sub-category. Materials with no category come last.
  const sections = React.useMemo(() => {
    const q = search.trim().toLowerCase()
    const shown = (catalog?.items ?? []).filter(
      (m) => (!q || `${m.name} ${categoryLabel(paths.get(m.category_id ?? ''))} ${m.sku ?? ''}`.toLowerCase().includes(q)) && (!fix || needs(m, fix)),
    )
    const byName = (a: MaterialCatalog, b: MaterialCatalog) => a.name.localeCompare(b.name)
    const inCategory = (id: string) => shown.filter((m) => m.category_id === id).sort(byName)
    const placed = tree
      .map(({ main, subs }) => ({
        key: main.id,
        title: main.name,
        groups: [
          { key: main.id, title: null as string | null, list: inCategory(main.id) },
          ...subs.map((s) => ({ key: s.id, title: s.name as string | null, list: inCategory(s.id) })),
        ].filter((g) => g.list.length > 0 && (!onlySub || g.key === onlySub)),
      }))
      .filter((sec) => sec.groups.length > 0 && (onlyCategory === 'all' || sec.key === onlyCategory))
    const loose = shown.filter((m) => !m.category_id || !paths.has(m.category_id)).sort(byName)
    return { placed, loose: onlyCategory === 'all' || onlyCategory === 'none' ? loose : [] }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog, search, paths, tree, onlyCategory, onlySub, fix, held])
  const nothingShown = sections.placed.length === 0 && sections.loose.length === 0
  const countIn = (ids: string[]) => (catalog?.items ?? []).filter((m) => m.category_id && ids.includes(m.category_id)).length
  const looseCount = (catalog?.items ?? []).filter((m) => !m.category_id || !paths.has(m.category_id)).length
  const addHere = (catId: string) => { handleCancelEdit(); setCategoryId(catId); setFormOpen(true); window.scrollTo({ top: 0, behavior: 'smooth' }) }

  const editing = editingMaterial !== null
  const showForm = formOpen || editing

  const materialRow = (m: MaterialCatalog, loose: boolean) => (
    <li key={m.id} className={cn('flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-1.5 hover:bg-muted/30', !m.is_active && 'text-muted-foreground')}>
      <span className="min-w-0 flex-1 truncate font-medium max-sm:basis-full">
        {m.name}
        {m.sku && <span className="ml-2 text-xs font-normal text-muted-foreground">{m.sku}</span>}
        {loose && m.category && <span className="ml-2 text-xs font-normal text-muted-foreground">was “{m.category}”</span>}
      </span>
      {!m.is_active && <span className={cn(CHIP, 'bg-muted text-muted-foreground')}>Not used</span>}
      {(() => {
        const h = held.get(m.id)
        return (
          <span className="flex flex-wrap items-center gap-1.5">
            {h && h.onHand > 0 && <span className="text-xs font-semibold tabular-nums">{qtyWords(String(h.onHand))} <span className="font-normal text-muted-foreground max-sm:hidden">on hand</span></span>}
            {seesMoney && h?.rate && <span className="text-xs text-muted-foreground tabular-nums">₹{Number(h.rate).toLocaleString('en-IN')}</span>}
            {needs(m, 'rate') && <Pill tone="attention" size="xs" icon={IndianRupee}>No rate</Pill>}
            {needs(m, 'min') && <Pill tone="muted" size="xs" icon={Target}>No minimum</Pill>}
            {m.is_active && needs(m, 'idle') && <Pill tone="muted" size="xs" icon={Snail}>Not used 90 d</Pill>}
          </span>
        )
      })()}
      {loose && tree.length > 0 && (
        <div className="w-full sm:w-56">
          <CategorySelect
            value={NO_CATEGORY}
            onChange={(v) => v !== NO_CATEGORY && placeMutation.mutate({ id: m.id, category: v })}
            tree={tree}
            label={`Category for ${m.name}`}
            placeholder="Put in a category…"
          />
        </div>
      )}
      <span className="text-right sm:w-28 max-sm:ml-auto"><span className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">{unitName(m)}</span></span>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button type="button" variant="ghost" size="icon" className="size-8" aria-label={`More for ${m.name}`}>
            <MoreHorizontal className="size-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-52">
          <DropdownMenuItem
            onClick={() => {
              handleEditClick(m)
              window.scrollTo({ top: 0, behavior: 'smooth' })
            }}
          >
            <Pencil className="mr-2 size-3.5" /> Edit
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => toggleActiveMutation.mutate({ id: m.id, isActive: !m.is_active })}>
            {m.is_active ? <CircleSlash2 className="mr-2 size-3.5" /> : <CheckCircle2 className="mr-2 size-3.5" />}
            {m.is_active ? 'Stop offering it' : 'Offer it again'}
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem className="text-destructive focus:text-destructive" onClick={() => setDeleting(m)}>
            <ActionIcon kind="delete" className="mr-2 size-3.5" /> Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </li>
  )

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        {leading}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-2 size-4 text-muted-foreground" />
            <Input placeholder="Search items" aria-label="Search items" value={search} onChange={(e) => setSearch(e.target.value)} className="h-8 w-[160px] pl-8" />
          </div>

        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-muted-foreground">{catalog ? `${catalog.items.length} items` : 'Loading…'}</span>
        <span className="flex flex-wrap gap-1.5" data-guide="items.fix">
          {(['rate', 'min', 'idle'] as const).map((f) => (
            <ToggleChip key={f} on={fix === f} onClick={() => setFix(fix === f ? '' : f)} tone={f === 'rate' ? 'attention' : 'muted'}
              icon={f === 'rate' ? IndianRupee : f === 'min' ? Target : Snail}
              count={(catalog?.items ?? []).filter((m) => needs(m, f)).length}
              label={f === 'rate' ? 'no rate' : f === 'min' ? 'no minimum' : 'not used 90 d'} />
          ))}
        </span>
        <div className="ml-auto flex flex-wrap gap-2">
          {!showForm && (
            <Button size="sm" className="gap-1.5" onClick={() => setFormOpen(true)}>
              <Plus className="size-3.5" /> Add item
            </Button>
          )}
          <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setImportOpen(true)}>
            <ActionIcon kind="import-excel" className="size-3.5" /> Import
          </Button>
          <Button size="sm" variant={panelOpen ? 'secondary' : 'outline'} aria-pressed={panelOpen} className="gap-1.5" onClick={() => setPanelOpen((o) => !o)}>
            <FolderTree className="size-3.5" /> Categories
          </Button>
          {sizes && (
            <Button size="sm" variant={sizesOpen ? 'secondary' : 'outline'} aria-pressed={sizesOpen} className="gap-1.5" onClick={() => setSizesOpen((o) => !o)}>
              <Ruler className="size-3.5" /> Sizes
            </Button>
          )}
        </div>
      </div>
      {sizesOpen && sizes}

      {(panelOpen || (categoryList && categories.length === 0)) && <CategoriesPanel categories={categories} />}
      {categoryList && categories.length > 0 && categoryList.uncategorised > 0 && (
        <Callout tone="info" icon={FolderTree}>
          {categoryList.uncategorised === 1 ? '1 material has' : `${categoryList.uncategorised} materials have`} no category yet.
        </Callout>
      )}

      {showForm && (
        <form onSubmit={handleSubmit} className="flex flex-col gap-3 rounded-lg border p-4 text-sm">
          <h3 className="font-semibold">{editing ? `Edit ${editingMaterial.name}` : 'Add a material'}</h3>
          {error && (
            <p className="flex items-center gap-2 text-destructive">
              <ShieldAlert className="size-4 shrink-0" /> {error}
            </p>
          )}
          <div className="grid gap-3 sm:grid-cols-4">
            <div className="grid gap-1.5 sm:col-span-2">
              <Label htmlFor="newMaterialName">Name</Label>
              <Input id="newMaterialName" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. OPC Cement" autoFocus />
            </div>
            <div className="grid gap-1.5">
              <Label>Counted in</Label>
              <Select value={unitId} onValueChange={setUnitId}>
                <SelectTrigger className="h-9">
                  <SelectValue placeholder="Unit" />
                </SelectTrigger>
                <SelectContent>
                  {units?.items.map((u) => (
                    <SelectItem key={u.id} value={u.id}>
                      {u.display_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1.5">
              <Label>Category</Label>
              <CategorySelect value={categoryId} onChange={setCategoryId} tree={tree} label="Category" />
            </div>
            <div className="grid gap-1.5 sm:col-span-2">
              <Label htmlFor="newMaterialSku">Item code (optional)</Label>
              <Input id="newMaterialSku" value={sku} onChange={(e) => setSku(e.target.value)} />
            </div>
          </div>
          <div className="flex gap-2">
            <Button type="submit" size="sm" className="font-semibold" disabled={createMutation.isPending || updateMutation.isPending}>
              {editing ? (updateMutation.isPending ? 'Saving…' : 'Save') : createMutation.isPending ? 'Adding…' : 'Add material'}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                handleCancelEdit()
                setFormOpen(false)
              }}
            >
              Cancel
            </Button>
          </div>
        </form>
      )}

      <div className="flex flex-col gap-4 lg:grid lg:grid-cols-[230px_minmax(0,1fr)] lg:items-start">
      {tree.length > 0 && (
        <CategoryNav tree={tree} pick={pick} onPick={setPick} total={catalog?.items.length ?? 0} countIn={countIn} loose={looseCount} />
      )}
      <div className="flex min-w-0 flex-col gap-4">
      {catalog && catalog.items.length === 0 ? (
        <p className="rounded-xl border border-dashed py-10 text-center text-sm text-muted-foreground">No materials yet.</p>
      ) : nothingShown ? (
        <p className="rounded-xl border border-dashed py-10 text-center text-sm text-muted-foreground">No materials match.</p>
      ) : (
        <>
          {sections.placed.map((sec) => (
            // WEB-80: one list per main category, its sub-categories as heading rows inside (as Materials > Stock).
            <section key={sec.key} className="overflow-hidden rounded-xl border bg-card shadow-xs" data-guide="items.section">
              <header className="flex flex-wrap items-center gap-3 border-b bg-muted/40 px-3 py-2.5">
                <CategoryTile mainCategory={sec.title} />
                <span className="min-w-0">
                  <span className="block text-base font-semibold">{sec.title}</span>
                  <span className="block text-xs text-muted-foreground">{plural(sec.groups.reduce((n, g) => n + g.list.length, 0), 'item')}{sec.groups.filter((g) => g.title).length ? ` · ${plural(sec.groups.filter((g) => g.title).length, 'group')}` : ''}</span>
                </span>
                <span className="ml-auto flex flex-wrap items-center gap-1.5">
                  {sec.groups.filter((g) => g.title).map((g) => (
                    <button key={g.key} type="button" onClick={() => setPick(onlySub === g.key ? sec.key : `s:${g.key}`)} aria-pressed={onlySub === g.key}
                      className={cn('rounded-full border px-2 py-0.5 text-xs font-medium', onlySub === g.key ? 'border-foreground bg-foreground text-background' : 'bg-background/80 hover:bg-background')}>
                      {g.title} <span className="tabular-nums opacity-70">{g.list.length}</span>
                    </button>
                  ))}
                  <Button size="sm" variant="ghost" className="h-7 gap-1 px-2 text-xs" onClick={() => addHere(sec.key)}><Plus className="size-3.5" />Add here</Button>
                </span>
              </header>
              <ul className="divide-y">
                {sec.groups.map((g) => (
                  <React.Fragment key={g.key}>
                    {g.title && (
                      <li className="flex items-center gap-2 bg-muted/40 px-3 py-1.5 text-xs font-semibold">
                        <span className="h-3.5 w-1 rounded-full bg-foreground/40" />
                        {g.title} <span className="font-normal text-muted-foreground tabular-nums">{g.list.length}</span>
                      </li>
                    )}
                    {g.list.map((m) => materialRow(m, false))}
                  </React.Fragment>
                ))}
              </ul>
            </section>
          ))}
          {sections.loose.length > 0 && (
            <section className="overflow-hidden rounded-xl border border-draft/40 bg-card shadow-xs">
              <header className="flex items-center gap-3 border-b bg-draft-soft/50 px-3 py-2.5">
                <CategoryTile mainCategory={null} />
                <span className="text-base font-semibold">No category</span>
                <span className="text-xs text-muted-foreground tabular-nums">{sections.loose.length} to place</span>
              </header>
              <ul className="divide-y">{sections.loose.map((m) => materialRow(m, true))}</ul>
            </section>
          )}
        </>
      )}
      </div>
      </div>

      <ImportDialog open={importOpen} onOpenChange={setImportOpen} />

      <Dialog open={deleting !== null} onOpenChange={(open) => !open && setDeleting(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-base font-semibold">Delete {deleting?.name}?</DialogTitle>
            <DialogDescription>
              Only while it has no records. Otherwise use "Stop offering it".
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleting(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={deleteMutation.isPending}
              onClick={() =>
                deleting &&
                deleteMutation.mutate(deleting.id, {
                  onSuccess: () => setDeleting(null),
                  onError: () => setDeleting(null),
                })
              }
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// Main categories with their sub-categories indented; only the ones still offered.
/** UX-69: the category tree as the page's navigation: every main category with its tile and count, its sub-categories
 * under it when picked, and No category (amber) when some are loose. A row on a laptop, chips on a phone. */
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

function CategoryNav({ tree, pick, onPick, total, countIn, loose }: {
  tree: { main: MaterialCategory; subs: MaterialCategory[] }[]
  pick: string
  onPick: (v: string) => void
  total: number
  countIn: (ids: string[]) => number
  loose: number
}) {
  const sub = pick.startsWith('s:') ? pick.slice(2) : null
  const openMain = sub ? tree.find((t) => t.subs.some((x) => x.id === sub))?.main.id : pick
  const row = (on: boolean) => cn('flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition', on ? 'bg-foreground text-background' : 'hover:bg-muted')
  return (
    <nav aria-label="Categories" data-guide="items.categories" className="lg:sticky lg:top-4">
      <div className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1 lg:hidden">
        {[{ id: 'all', name: 'All', n: total }, ...tree.map((t) => ({ id: t.main.id, name: t.main.name, n: countIn([t.main.id, ...t.subs.map((x) => x.id)]) })), ...(loose ? [{ id: 'none', name: 'No category', n: loose }] : [])].map((c) => (
          <button key={c.id} type="button" onClick={() => onPick(c.id)} aria-pressed={pick === c.id || openMain === c.id}
            className={cn('flex shrink-0 items-center gap-1.5 rounded-full border bg-card py-1 pr-2.5 pl-1 text-xs font-medium', (pick === c.id || openMain === c.id) && 'border-foreground bg-foreground text-background')}>
            {c.id !== 'all' && c.id !== 'none' ? <CategoryTile mainCategory={c.name} size="sm" /> : <span className="w-1" />}
            {c.name} <span className="tabular-nums opacity-70">{c.n}</span>
          </button>
        ))}
      </div>
      <ul className="hidden flex-col gap-0.5 rounded-xl border bg-card p-1.5 shadow-xs lg:flex">
        <li><button type="button" className={row(pick === 'all')} onClick={() => onPick('all')}><FolderTree className="size-4" /><span className="flex-1">All items</span><span className="text-xs tabular-nums opacity-70">{total}</span></button></li>
        {tree.map(({ main, subs }) => {
          const n = countIn([main.id, ...subs.map((x) => x.id)])
          const open = openMain === main.id
          return (
            <li key={main.id}>
              <button type="button" className={row(pick === main.id)} onClick={() => onPick(pick === main.id ? 'all' : main.id)} aria-expanded={open}>
                <CategoryTile mainCategory={main.name} size="sm" />
                <span className="flex-1 truncate font-medium">{main.name}</span>
                <span className="text-xs tabular-nums opacity-70">{n}</span>
              </button>
              {open && subs.length > 0 && (
                <ul className="my-0.5 ml-5 flex flex-col gap-0.5 border-l pl-2">
                  {subs.map((x) => {
                    const c = countIn([x.id])
                    return (
                      <li key={x.id}>
                        <button type="button" className={cn(row(sub === x.id), 'py-1 text-xs')} onClick={() => onPick(sub === x.id ? main.id : `s:${x.id}`)}>
                          <span className="flex-1 truncate">{x.name}</span><span className={cn('tabular-nums', c ? 'opacity-70' : 'opacity-40')}>{c}</span>
                        </button>
                      </li>
                    )
                  })}
                </ul>
              )}
            </li>
          )
        })}
        {loose > 0 && (
          <li><button type="button" className={cn(row(pick === 'none'), pick !== 'none' && 'text-draft')} onClick={() => onPick(pick === 'none' ? 'all' : 'none')}><FolderTree className="size-4" /><span className="flex-1">No category</span><span className="text-xs font-semibold tabular-nums">{loose}</span></button></li>
        )}
      </ul>
    </nav>
  )
}

function CategorySelect({
  value,
  onChange,
  tree,
  label,
  placeholder = 'No category',
}: {
  value: string
  onChange: (value: string) => void
  tree: ReturnType<typeof categoryTree>
  label: string
  placeholder?: string
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="h-9" aria-label={label}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={NO_CATEGORY}>{placeholder}</SelectItem>
        {tree
          .filter(({ main }) => main.is_active)
          .map(({ main, subs }) => (
            <React.Fragment key={main.id}>
              <SelectItem value={main.id} className="font-semibold">
                {main.name}
              </SelectItem>
              {subs
                .filter((s) => s.is_active)
                .map((s) => (
                  <SelectItem key={s.id} value={s.id} className="pl-6">
                    {s.name}
                  </SelectItem>
                ))}
            </React.Fragment>
          ))}
      </SelectContent>
    </Select>
  )
}
