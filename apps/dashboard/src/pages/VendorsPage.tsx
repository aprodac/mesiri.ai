import * as React from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MoreHorizontal, Plus, Search, Store, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Callout, PageHeader, StatStrip } from '@/components/dpr-page'
import { FilterSelect } from '@/components/filter-select'
import { CreateVendorDialog } from '@/components/vendors/create-vendor-dialog'
import { VendorDetailSheet } from '@/components/vendors/vendor-detail-sheet'
import { useReadOnly } from '@/lib/trial'
import { useUrlState } from '@/lib/url-state'
import { usePageTitle } from '@/lib/page-title'
import { CHIP } from '@/lib/site-day'
import { cn } from '@/lib/utils'
import { fetchVendorsApi, updateVendorApi, type VendorItem } from '@/lib/api'

// WEB-51 (Ilan, 5 Nov): Finance > Vendors. The shops the company buys from, with phone, GSTIN and address (PRC-04),
// how many expenses and what was paid. Search and a status dropdown; a row opens the vendor, its menu shows its
// expenses, edits it or switches it off (a vendor with history is never deleted). The old page drew card grids with
// made-up figures ("Auto-Discovery ratio: WhatsApp Live").

const rupees = (n: number) => `₹${Math.round(n).toLocaleString('en-IN')}`

export default function VendorsPage() {
  usePageTitle('Vendors')
  const readOnly = useReadOnly()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [q, setQ] = useUrlState<string>('q', '')
  const [status, setStatus] = useUrlState<string>('status', 'active')
  const [editing, setEditing] = React.useState<VendorItem | null | undefined>(undefined)
  const [opened, setOpened] = React.useState<VendorItem | null>(null)

  const vendors = useQuery({ queryKey: ['finance', 'vendors'], queryFn: fetchVendorsApi })
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['finance'] })
  const toggle = useMutation({
    mutationFn: (v: VendorItem) => updateVendorApi(v.id, { status: v.status === 'active' ? 'inactive' : 'active' }),
    onSuccess: refresh,
  })

  const needle = q.trim().toLowerCase()
  const all = vendors.data ?? []
  const shown = all
    .filter((v) => status === 'all' || v.status === status)
    .filter((v) => !needle || [v.name, v.phone, v.gstin, v.address].join(' ').toLowerCase().includes(needle))
    .sort((a, b) => (Number(b.total_amount_paid) || 0) - (Number(a.total_amount_paid) || 0) || a.name.localeCompare(b.name))
  const active = all.filter((v) => v.status === 'active')

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 pb-8 sm:px-2">
      <PageHeader
        title="Vendors"
        actions={
          !readOnly && (
            <Button size="sm" className="gap-1.5 font-semibold" onClick={() => setEditing(null)}>
              <Plus className="size-4" /> Add vendor
            </Button>
          )
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-2 size-4 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, phone, GSTIN" aria-label="Search vendors" className="h-8 w-[190px] pl-8" />
        </div>
        <FilterSelect
          label="Status"
          value={status}
          onChange={setStatus}
          className="w-[150px]"
          options={[
            { value: 'active', label: 'Switched on' },
            { value: 'inactive', label: 'Switched off' },
            { value: 'all', label: 'All vendors' },
          ]}
        />
      </div>

      {vendors.isError ? (
        <Callout tone="draft" icon={TriangleAlert} action={<Button variant="outline" size="sm" className="bg-background" onClick={() => vendors.refetch()}>Try again</Button>}>
          The vendors could not be loaded.
        </Callout>
      ) : vendors.isLoading ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-12 rounded-lg" />
          ))}
        </div>
      ) : (
        <>
          <StatStrip
            stats={[
              { label: 'Vendors', value: active.length || '—', icon: Store },
              { label: 'Paid to vendors', value: rupees(active.reduce((n, v) => n + (Number(v.total_amount_paid) || 0), 0)), icon: Store },
            ]}
          />
          {shown.length === 0 ? (
            <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center">
              <Store className="size-6 text-muted-foreground" aria-hidden="true" />
              <p className="text-sm font-medium">{all.length ? 'No vendors match' : 'No vendors yet'}</p>
              <p className="max-w-sm text-sm text-muted-foreground">
                {all.length ? '' : 'A shop named on a delivery or an expense is added here by itself; add one with its phone and GSTIN.'}
              </p>
            </div>
          ) : (
            <ul className="divide-y rounded-lg border">
              {shown.map((v) => (
                <li key={v.id} className={cn('relative flex items-start gap-3 px-3 py-2 hover:bg-muted/30', v.status !== 'active' && 'opacity-60')}>
                  <button type="button" className="flex min-w-0 flex-1 flex-col gap-0.5 text-left after:absolute after:inset-0" onClick={() => setOpened(v)}>
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{v.name}</span>
                      {v.status !== 'active' && <span className={cn(CHIP, 'bg-muted text-muted-foreground')}>Switched off</span>}
                    </span>
                    <span className="line-clamp-1 text-xs text-muted-foreground">
                      {[v.phone, v.gstin ? `GSTIN ${v.gstin}` : null, v.address].filter(Boolean).join(' · ') || 'No phone or GSTIN yet'}
                    </span>
                  </button>
                  <span className="flex shrink-0 items-center gap-1">
                    <span className="flex flex-col items-end">
                      <span className="font-semibold tabular-nums">{rupees(Number(v.total_amount_paid) || 0)}</span>
                      <span className="text-xs text-muted-foreground">
                        {v.expense_count} {v.expense_count === 1 ? 'expense' : 'expenses'}
                      </span>
                    </span>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button type="button" variant="ghost" size="icon" className="relative z-10 size-8" aria-label={`More for ${v.name}`}>
                          <MoreHorizontal className="size-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-48">
                        <DropdownMenuItem onClick={() => setOpened(v)}>Open</DropdownMenuItem>
                        <DropdownMenuItem onClick={() => navigate(`/finance/expenses?q=${encodeURIComponent(v.name)}&period=all`)}>Its expenses</DropdownMenuItem>
                        {!readOnly && (
                          <>
                            <DropdownMenuItem onClick={() => setEditing(v)}>Edit</DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem onClick={() => toggle.mutate(v)}>{v.status === 'active' ? 'Switch off' : 'Switch on'}</DropdownMenuItem>
                          </>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      <CreateVendorDialog open={editing !== undefined} onOpenChange={(o) => !o && setEditing(undefined)} vendorToEdit={editing ?? null} onSuccess={refresh} />
      <VendorDetailSheet vendor={opened} open={opened !== null} onOpenChange={(o) => !o && setOpened(null)} />
    </div>
  )
}
