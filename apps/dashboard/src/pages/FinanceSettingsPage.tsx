import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MoreHorizontal, Plus, Tags, TriangleAlert, Wallet } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Callout, PageHeader } from '@/components/dpr-page'
import { CreateCategoryDialog } from '@/components/categories/create-category-dialog'
import { useAuth } from '@/lib/AuthContext'
import { mayManageMoney } from '@/lib/cost'
import { useReadOnly } from '@/lib/trial'
import { usePageTitle } from '@/lib/page-title'
import { CHIP } from '@/lib/site-day'
import { cn } from '@/lib/utils'
import { fetchCategoriesApi, fetchFinanceSettingsApi, updateCategoryApi, updateFinanceSettingsApi, type CategoryItem } from '@/lib/api'
import { SubcontractSettings } from '@/components/subcontracts/settings-section'

// WEB-51 (Ilan, 5 Nov): Finance > Settings, one page for what used to be Categories, Settings and Finance on
// WhatsApp -- with only what does something. The old pages offered fourteen switches and limits (auto-approval,
// receipt required above, weekly digest, WhatsApp transfer receipts...) that nothing in Mesiri reads; they are not
// shown until they work. What is here: the expense categories (add, rename, switch off) and the petty cash "low"
// line, which Money uses to mark a site's cash as low.

const rupees = (n: number) => `₹${Math.round(n).toLocaleString('en-IN')}`

export default function FinanceSettingsPage() {
  usePageTitle('Finance settings')
  const readOnly = useReadOnly()
  const { me } = useAuth()
  // SEC-04 (8 Nov): adding, renaming and switching off categories is for the owner, admins and finance (the API checks).
  const canManage = !readOnly && mayManageMoney(me?.role)
  const queryClient = useQueryClient()
  const categories = useQuery({ queryKey: ['finance', 'categories'], queryFn: fetchCategoriesApi })
  const settings = useQuery({ queryKey: ['finance', 'settings'], queryFn: fetchFinanceSettingsApi })
  const [editing, setEditing] = React.useState<CategoryItem | null | undefined>(undefined)
  const [low, setLow] = React.useState('')
  React.useEffect(() => {
    if (settings.data) setLow(String(Math.round(Number((settings.data as any).low_float_threshold ?? 50000))))
  }, [settings.data])
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['finance'] })
  const toggle = useMutation({
    mutationFn: (c: CategoryItem) => updateCategoryApi(c.id, { status: c.status === 'active' ? 'inactive' : 'active' }),
    onSuccess: refresh,
  })
  const saveLow = useMutation({
    mutationFn: () => updateFinanceSettingsApi({ low_float_threshold: Number(low) } as any),
    onSuccess: refresh,
  })
  const list = [...(categories.data ?? [])].sort((a, b) => (a.status === b.status ? a.name.localeCompare(b.name) : a.status === 'active' ? -1 : 1))
  const savedLow = Math.round(Number((settings.data as any)?.low_float_threshold ?? 50000))

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 pb-8 sm:px-2">
      <PageHeader title="Finance settings" />

      <section className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 text-[15px] font-semibold">
            <Tags className="size-4 text-muted-foreground" aria-hidden="true" /> Expense categories
          </h2>
          {canManage && (
            <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setEditing(null)}>
              <Plus className="size-3.5" /> Add category
            </Button>
          )}
        </div>
        {categories.isError ? (
          <Callout tone="draft" icon={TriangleAlert} action={<Button variant="outline" size="sm" className="bg-background" onClick={() => categories.refetch()}>Try again</Button>}>
            The categories could not be loaded.
          </Callout>
        ) : categories.isLoading ? (
          <Skeleton className="h-32 rounded-lg" />
        ) : list.length === 0 ? (
          <p className="text-sm text-muted-foreground">No categories yet. An expense whose category is not here is kept under Uncategorized.</p>
        ) : (
          <ul className="divide-y rounded-lg border">
            {!readOnly && !canManage && (
              <li className="px-3 py-2 text-xs text-muted-foreground">Only the owner, an admin or finance can add or change categories.</li>
            )}
            {list.map((c) => (
              <li key={c.id} className={cn('flex items-center gap-3 px-3 py-2', c.status !== 'active' && 'text-muted-foreground')}>
                <span className="min-w-0 flex-1">
                  <span className="font-medium">{c.name}</span>
                  {c.code && <span className="ml-2 text-xs text-muted-foreground">{c.code}</span>}
                  {c.status !== 'active' && <span className={cn(CHIP, 'ml-2 bg-muted text-muted-foreground')}>Switched off</span>}
                </span>
                <span className="text-right text-xs text-muted-foreground tabular-nums">
                  {c.expense_count} {c.expense_count === 1 ? 'expense' : 'expenses'} · {rupees(Number(c.total_amount_spent) || 0)}
                </span>
                {canManage && (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button type="button" variant="ghost" size="icon" className="size-8" aria-label={`More for ${c.name}`}>
                        <MoreHorizontal className="size-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-44">
                      <DropdownMenuItem onClick={() => setEditing(c)}>Edit</DropdownMenuItem>
                      <DropdownMenuItem onClick={() => toggle.mutate(c)}>{c.status === 'active' ? 'Switch off' : 'Switch on'}</DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="flex flex-col gap-2 border-t pt-4">
        <h2 className="flex items-center gap-2 text-[15px] font-semibold">
          <Wallet className="size-4 text-muted-foreground" aria-hidden="true" /> Petty cash
        </h2>
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (Number(low) >= 0) saveLow.mutate()
          }}
        >
          <div className="grid gap-1.5">
            <Label htmlFor="lowLine">A site's petty cash is low below (₹)</Label>
            <Input id="lowLine" type="number" min={0} step={1000} value={low} onChange={(e) => setLow(e.target.value)} className="h-9 w-40" disabled={readOnly} />
          </div>
          {!readOnly && (
            <Button type="submit" size="sm" disabled={saveLow.isPending || Number(low) === savedLow || low === ''}>
              {saveLow.isPending ? 'Saving…' : 'Save'}
            </Button>
          )}
          {saveLow.isSuccess && Number(low) === savedLow && <span className="text-sm text-success">Saved</span>}
        </form>
        <p className="text-xs text-muted-foreground">Money marks a site's cash box as low under this amount.</p>
      </section>

      <SubcontractSettings readOnly={readOnly} />

      <CreateCategoryDialog open={editing !== undefined} onOpenChange={(o) => !o && setEditing(undefined)} categoryToEdit={editing ?? null} onSuccess={refresh} />
    </div>
  )
}
