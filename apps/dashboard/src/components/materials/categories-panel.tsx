import * as React from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, CircleSlash2, FolderPlus, MoreHorizontal, Pencil, Plus, ShieldAlert, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { CHIP } from '@/lib/site-day'
import { cn } from '@/lib/utils'
import {
  applyStandardCategories,
  categoryTree,
  createMaterialCategory,
  deleteMaterialCategory,
  updateMaterialCategory,
  type MaterialCategory,
} from '@/lib/materials'

// PRC-01: the company's category tree -- main categories and their sub-categories.
// Two levels only: a size or type (1-module, 2-way, 20 mm) is a material, not a third level.
// A category with materials is switched off, never deleted, so its materials keep their place.

type Editing =
  | { kind: 'add-main' }
  | { kind: 'add-sub'; parent: MaterialCategory }
  | { kind: 'rename'; category: MaterialCategory }
  | null

export function CategoriesPanel({ categories }: { categories: MaterialCategory[] }) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = React.useState<Editing>(null)
  const [name, setName] = React.useState('')
  const [error, setError] = React.useState('')
  const tree = React.useMemo(() => categoryTree(categories), [categories])
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['materials'] })
  const detail = (err: any, fallback: string) => err?.response?.data?.detail || fallback

  const save = useMutation({
    mutationFn: async () => {
      if (!editing) return
      if (editing.kind === 'rename') return updateMaterialCategory(editing.category.id, { name: name.trim() })
      return createMaterialCategory({ name: name.trim(), parent_id: editing.kind === 'add-sub' ? editing.parent.id : null })
    },
    onSuccess: () => {
      refresh()
      setEditing(null)
    },
    onError: (err) => setError(detail(err, 'Could not save the category.')),
  })
  const toggle = useMutation({
    mutationFn: (c: MaterialCategory) => updateMaterialCategory(c.id, { is_active: !c.is_active }),
    onSuccess: refresh,
  })
  const remove = useMutation({
    mutationFn: (c: MaterialCategory) => deleteMaterialCategory(c.id),
    onSuccess: refresh,
    onError: (err) => setError(detail(err, 'Could not delete the category.')),
  })
  const standard = useMutation({ mutationFn: applyStandardCategories, onSuccess: refresh })

  const open = (next: Editing) => {
    setEditing(next)
    setName(next?.kind === 'rename' ? next.category.name : '')
    setError('')
  }
  const subCount = (id: string) => categories.filter((c) => c.parent_id === id).length

  const menu = (c: MaterialCategory, isMain: boolean) => (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="ghost" size="icon" className="size-8" aria-label={`More for ${c.name}`}>
          <MoreHorizontal className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        <DropdownMenuItem onClick={() => open({ kind: 'rename', category: c })}>
          <Pencil className="mr-2 size-3.5" /> Rename
        </DropdownMenuItem>
        {isMain && (
          <DropdownMenuItem onClick={() => open({ kind: 'add-sub', parent: c })}>
            <Plus className="mr-2 size-3.5" /> Add a sub-category
          </DropdownMenuItem>
        )}
        <DropdownMenuItem onClick={() => toggle.mutate(c)}>
          {c.is_active ? <CircleSlash2 className="mr-2 size-3.5" /> : <CheckCircle2 className="mr-2 size-3.5" />}
          {c.is_active ? 'Stop offering it' : 'Offer it again'}
        </DropdownMenuItem>
        {c.material_count === 0 && (isMain ? subCount(c.id) === 0 : true) && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem className="text-destructive focus:text-destructive" onClick={() => remove.mutate(c)}>
              <Trash2 className="mr-2 size-3.5" /> Delete
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )

  // A main category counts its sub-categories' materials too.
  const total = (c: MaterialCategory, isMain: boolean) =>
    c.material_count + (isMain ? categories.filter((s) => s.parent_id === c.id).reduce((n, s) => n + s.material_count, 0) : 0)

  const row = (c: MaterialCategory, isMain: boolean) => (
    <li key={c.id} className={cn('flex items-center gap-3 py-1.5 pr-1', isMain ? 'pl-3' : 'pl-8', !c.is_active && 'text-muted-foreground')}>
      <span className={cn('min-w-0 flex-1 truncate', isMain && 'font-semibold')}>{c.name}</span>
      {!c.is_active && <span className={cn(CHIP, 'bg-muted text-muted-foreground')}>Not offered</span>}
      <span className="w-24 text-right text-xs text-muted-foreground tabular-nums">
        {total(c, isMain) === 0 ? 'Empty' : `${total(c, isMain)} ${total(c, isMain) === 1 ? 'material' : 'materials'}`}
      </span>
      {menu(c, isMain)}
    </li>
  )

  return (
    <section className="flex flex-col gap-2 rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-semibold">Categories</h3>
        <span className="text-muted-foreground">Main category, then sub-category. Sizes and types are separate materials.</span>
        <div className="ml-auto flex flex-wrap gap-2">
          <Button size="sm" variant="outline" className="gap-1.5" disabled={standard.isPending} onClick={() => standard.mutate()}>
            {standard.isPending ? 'Adding…' : 'Add the standard builder list'}
          </Button>
          <Button size="sm" variant="outline" className="gap-1.5" onClick={() => open({ kind: 'add-main' })}>
            <FolderPlus className="size-3.5" /> Add main category
          </Button>
        </div>
      </div>
      {standard.data && (
        <p className="text-muted-foreground">
          {standard.data.categories_added === 0 && standard.data.materials_placed === 0
            ? 'You already have the standard list.'
            : `Added ${standard.data.categories_added} categories and placed ${standard.data.materials_placed} materials.`}
        </p>
      )}
      {error && !editing && (
        <p className="flex items-center gap-2 text-destructive">
          <ShieldAlert className="size-4 shrink-0" /> {error}
        </p>
      )}
      {tree.length === 0 ? (
        <p className="py-4 text-center text-muted-foreground">No categories yet. Start with the standard builder list, or add your own.</p>
      ) : (
        <ul className="divide-y rounded-md border">
          {tree.map(({ main, subs }) => (
            <React.Fragment key={main.id}>
              {row(main, true)}
              {subs.map((s) => row(s, false))}
            </React.Fragment>
          ))}
        </ul>
      )}

      <Dialog open={editing !== null} onOpenChange={(o) => !o && setEditing(null)}>
        <DialogContent className="sm:max-w-md">
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault()
              if (!name.trim()) return setError('A name is needed.')
              save.mutate()
            }}
          >
            <DialogHeader>
              <DialogTitle className="text-base font-semibold">
                {editing?.kind === 'rename'
                  ? `Rename ${editing.category.name}`
                  : editing?.kind === 'add-sub'
                    ? `Add a sub-category to ${editing.parent.name}`
                    : 'Add a main category'}
              </DialogTitle>
              <DialogDescription>
                {editing?.kind === 'add-main' ? 'For example Electrical, Plumbing & CP or Fire protection.' : 'For example Switches & sockets, or Pipes.'}
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-1.5">
              <Label htmlFor="categoryName">Name</Label>
              <Input id="categoryName" value={name} onChange={(e) => setName(e.target.value)} maxLength={80} autoFocus />
              {error && <p className="text-sm text-destructive">{error}</p>}
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setEditing(null)}>
                Cancel
              </Button>
              <Button type="submit" disabled={save.isPending}>
                {save.isPending ? 'Saving…' : 'Save'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </section>
  )
}
