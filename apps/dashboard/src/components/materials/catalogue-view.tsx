import * as React from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, CircleSlash2, FolderTree, MoreHorizontal, Pencil, Plus, Search, ShieldAlert, Trash2 } from 'lucide-react'
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
  fetchMaterials,
  fetchUnitsOfMeasure,
  createMaterial,
  deleteMaterial,
  updateMaterial,
  type MaterialCatalog,
} from '@/lib/materials'
import { CategoriesPanel } from './categories-panel'

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
export function CatalogueView() {
  const queryClient = useQueryClient()

  const [editingMaterial, setEditingMaterial] = React.useState<MaterialCatalog | null>(null)
  const [name, setName] = React.useState('')
  const [unitId, setUnitId] = React.useState('')
  const [categoryId, setCategoryId] = React.useState(NO_CATEGORY)
  const [panelOpen, setPanelOpen] = React.useState(false)
  const [sku, setSku] = React.useState('')
  const [error, setError] = React.useState('')

  const { data: catalog } = useQuery({
    queryKey: ['materials', 'catalog', 'manage'],
    queryFn: () => fetchMaterials({ limit: 200 }),
    staleTime: 30_000,
  })

  const { data: categoryList } = useQuery({
    queryKey: ['materials', 'categories'],
    queryFn: fetchMaterialCategories,
    staleTime: 30_000,
  })
  const categories = React.useMemo(() => categoryList?.items ?? [], [categoryList])
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
      (m) => !q || `${m.name} ${categoryLabel(paths.get(m.category_id ?? ''))} ${m.sku ?? ''}`.toLowerCase().includes(q),
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
        ].filter((g) => g.list.length > 0),
      }))
      .filter((sec) => sec.groups.length > 0)
    const loose = shown.filter((m) => !m.category_id || !paths.has(m.category_id)).sort(byName)
    return { placed, loose }
  }, [catalog, search, paths, tree])
  const nothingShown = sections.placed.length === 0 && sections.loose.length === 0

  const editing = editingMaterial !== null
  const showForm = formOpen || editing

  const materialRow = (m: MaterialCatalog, loose: boolean) => (
    <li key={m.id} className={cn('flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2', !m.is_active && 'text-muted-foreground')}>
      <span className="min-w-0 flex-1 truncate font-medium">
        {m.name}
        {m.sku && <span className="ml-2 text-xs font-normal text-muted-foreground">{m.sku}</span>}
        {loose && m.category && <span className="ml-2 text-xs font-normal text-muted-foreground">was “{m.category}”</span>}
      </span>
      {!m.is_active && <span className={cn(CHIP, 'bg-muted text-muted-foreground')}>Not used</span>}
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
      <span className="w-28 text-right text-sm text-muted-foreground">{unitName(m)}</span>
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
            <Trash2 className="mr-2 size-3.5" /> Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </li>
  )

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-64">
          <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
          <Input placeholder="Search materials…" aria-label="Search materials" value={search} onChange={(e) => setSearch(e.target.value)} className="h-9 pl-8" />
        </div>
        <span className="text-sm text-muted-foreground">{catalog ? `${catalog.items.length} materials` : 'Loading…'}</span>
        <div className="ml-auto flex flex-wrap gap-2">
          <Button size="sm" variant={panelOpen ? 'secondary' : 'outline'} className="gap-1.5" onClick={() => setPanelOpen((o) => !o)}>
            <FolderTree className="size-3.5" /> Categories
          </Button>
          {!showForm && (
            <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setFormOpen(true)}>
              <Plus className="size-3.5" /> Add material
            </Button>
          )}
        </div>
      </div>

      {(panelOpen || (categoryList && categories.length === 0)) && <CategoriesPanel categories={categories} />}
      {categoryList && categories.length > 0 && categoryList.uncategorised > 0 && (
        <Callout tone="info" icon={FolderTree}>
          {categoryList.uncategorised === 1 ? '1 material has' : `${categoryList.uncategorised} materials have`} no category yet. Pick one for
          each under <strong className="font-semibold">No category</strong> below, so stock and spend add up by category.
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

      {catalog && catalog.items.length === 0 ? (
        <p className="rounded-xl border border-dashed py-10 text-center text-sm text-muted-foreground">No materials yet.</p>
      ) : nothingShown ? (
        <p className="rounded-xl border border-dashed py-10 text-center text-sm text-muted-foreground">No materials match.</p>
      ) : (
        <>
          {sections.placed.map((sec) => (
            <section key={sec.key} className="flex flex-col gap-2">
              <h3 className="text-sm font-semibold">
                {sec.title}{' '}
                <span className="font-normal text-muted-foreground">{sec.groups.reduce((n, g) => n + g.list.length, 0)}</span>
              </h3>
              {sec.groups.map((g) => (
                <div key={g.key} className="flex flex-col gap-1">
                  {g.title && (
                    <h4 className="text-xs font-semibold text-muted-foreground">
                      {g.title} <span className="font-normal">{g.list.length}</span>
                    </h4>
                  )}
                  <ul className="divide-y rounded-lg border">{g.list.map((m) => materialRow(m, false))}</ul>
                </div>
              ))}
            </section>
          ))}
          {sections.loose.length > 0 && (
            <section className="flex flex-col gap-1.5">
              <h3 className="text-sm font-semibold">
                No category <span className="font-normal text-muted-foreground">{sections.loose.length}</span>
              </h3>
              <ul className="divide-y rounded-lg border">{sections.loose.map((m) => materialRow(m, true))}</ul>
            </section>
          )}
        </>
      )}

      <Dialog open={deleting !== null} onOpenChange={(open) => !open && setDeleting(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-base font-semibold">Delete {deleting?.name}?</DialogTitle>
            <DialogDescription>
              Only possible while nothing has been recorded for it. Once it has deliveries or use, choose "Stop offering it" instead: its
              records stay, and it is no longer offered.
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
