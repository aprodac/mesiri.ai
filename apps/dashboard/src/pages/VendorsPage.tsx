import * as React from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlarmClock, Download, HandCoins, MoreHorizontal, PackageOpen, Plus, Search, Store, TriangleAlert, Wallet } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { useToast } from '@/components/ui/toast-notification'
import { Callout } from '@/components/dpr-page'
import { FilterSelect } from '@/components/filter-select'
import { VendorTile } from '@/components/orders/order-detail'
import { MergeVendorDialog, PayVendorDialog, VendorFormDialog } from '@/components/vendors/vendor-dialogs'
import { AgeBar } from '@/components/vendors/vendor-parts'
import { useAuth } from '@/lib/AuthContext'
import { useScope } from '@/lib/ScopeContext'
import { useReadOnly } from '@/lib/trial'
import { useUrlState } from '@/lib/url-state'
import { usePageTitle } from '@/lib/page-title'
import { MONEY_ROLES } from '@/lib/module-map'
import { mayManageMoney, rupees } from '@/lib/expenses'
import { apiErrorMessage } from '@/lib/logo-upload'
import { exportCsv } from '@/lib/export'
import { cn } from '@/lib/utils'
import { KINDS, day, deleteVendor, fetchPayables, fetchVendors, num, updateVendor, vendorUrl, type PayableRow, type Vendor, type VendorKind } from '@/lib/vendors'

// CC-09 (8 Nov 2026): Finance > Suppliers. Who the company buys from and pays, and -- for the roles that see spending
// -- what it owes each of them: four tiles that filter (we owe, overdue, delivered not billed, paid ahead), how old
// the money owed is, and one row per supplier with its balance. A row opens the supplier's page (ledger, bills, pay).
// Everyone with Finance still sees the directory: a supplier is picked when an expense is recorded.

type Tile = '' | 'owe' | 'overdue' | 'unbilled' | 'ahead'
type Sort = 'owed' | 'overdue' | 'oldest' | 'name'

const SORTS: { value: Sort; label: string }[] = [
  { value: 'owed', label: 'Most owed' },
  { value: 'overdue', label: 'Most overdue' },
  { value: 'oldest', label: 'Waiting longest' },
  { value: 'name', label: 'A to Z' },
]

type Row = Vendor & Partial<PayableRow>

export default function VendorsPage() {
  usePageTitle('Suppliers')
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const toast = useToast()
  const readOnly = useReadOnly()
  const { me } = useAuth()
  const { scope } = useScope()
  const role = (me?.role || '').toUpperCase()
  const seesMoney = (MONEY_ROLES as readonly string[]).includes(role)
  const canManage = mayManageMoney(role) && !readOnly
  const projectId = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : undefined

  const [q, setQ] = useUrlState<string>('q', '')
  const [status, setStatus] = useUrlState<string>('status', 'active')
  const [kind, setKind] = useUrlState<string>('kind', 'all')
  const [tile, setTile] = useUrlState<Tile>('show', '')
  const [sort, setSort] = useUrlState<Sort>('sort', seesMoney ? 'owed' : 'name')
  const [editing, setEditing] = React.useState<Vendor | null | undefined>(undefined)
  const [paying, setPaying] = React.useState<Row | null>(null)
  const [merging, setMerging] = React.useState<Vendor | null>(null)

  const vendors = useQuery({ queryKey: ['vendors', 'all'], queryFn: fetchVendors })
  const payables = useQuery({
    queryKey: ['finance', 'payables', projectId ?? ''],
    queryFn: () => fetchPayables({ project_id: projectId, include_settled: true }),
    enabled: seesMoney,
    retry: (n, e: unknown) => n < 2 && (e as { response?: { status?: number } })?.response?.status !== 403,
  })
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['finance'] })
    queryClient.invalidateQueries({ queryKey: ['vendors'] })
  }
  const toggle = useMutation({
    mutationFn: (v: Vendor) => updateVendor(v.id, { status: v.status === 'active' ? 'inactive' : 'active' }),
    onSuccess: (v) => { refresh(); toast.success(v.status === 'active' ? `${v.name} switched on` : `${v.name} switched off`, v.status === 'active' ? undefined : 'Kept with its history; it is no longer offered when recording.') },
    onError: (e) => toast.error('Not changed', apiErrorMessage(e)),
  })
  const remove = useMutation({
    mutationFn: (v: Vendor) => deleteVendor(v.id).then(() => v),
    onSuccess: (v) => { refresh(); toast.success(`${v.name} deleted`) },
    onError: (e) => toast.error('Not deleted', apiErrorMessage(e)),
  })

  const money = React.useMemo(() => new Map((payables.data?.vendors ?? []).map((r) => [r.id, r])), [payables.data])
  const all: Row[] = React.useMemo(() => (vendors.data ?? []).map((v) => ({ ...v, ...(money.get(v.id) ?? {}) })), [vendors.data, money])
  const needle = q.trim().toLowerCase()
  const base = all
    .filter((v) => status === 'all' || v.status === status)
    .filter((v) => kind === 'all' || (v.kind ?? 'supplier') === kind)
    .filter((v) => !needle || [v.name, v.code, v.phone, v.gstin, v.address, v.contact_person].join(' ').toLowerCase().includes(needle))
  const inTile = (v: Row, t: Tile) =>
    t === 'owe' ? num(v.balance) > 0 : t === 'overdue' ? num(v.overdue) > 0 : t === 'unbilled' ? (v.unbilled_count ?? 0) > 0 : t === 'ahead' ? num(v.balance) < 0 : true
  const oldest = (v: Row) => v.oldest_unbilled ?? '9999'
  const shown = base.filter((v) => inTile(v, tile)).sort((a, b) => {
    if (sort === 'owed') return num(b.balance) - num(a.balance) || a.name.localeCompare(b.name)
    if (sort === 'overdue') return num(b.overdue) - num(a.overdue) || num(b.balance) - num(a.balance)
    if (sort === 'oldest') return oldest(a).localeCompare(oldest(b)) || num(b.balance) - num(a.balance)
    return a.name.localeCompare(b.name)
  })
  const t = payables.data?.totals
  const count = (x: Tile) => base.filter((v) => inTile(v, x)).length
  const tiles: { value: Exclude<Tile, ''>; label: string; value2: string; icon: LucideIcon; tone: string; ring: string; num?: string }[] = [
    { value: 'owe', label: `We owe · ${count('owe')} suppliers`, value2: rupees(num(t?.payable)), icon: HandCoins, tone: 'bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-100', ring: 'ring-sky-500' },
    { value: 'overdue', label: `Overdue · ${count('overdue')}`, value2: rupees(num(t?.overdue)), icon: AlarmClock, tone: 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200', ring: 'ring-red-500', num: 'text-red-700 dark:text-red-400' },
    { value: 'unbilled', label: `Delivered, no bill · ${count('unbilled')}`, value2: rupees(num(t?.unbilled)), icon: PackageOpen, tone: 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-100', ring: 'ring-amber-500' },
    { value: 'ahead', label: `Paid ahead · ${count('ahead')}`, value2: rupees(num(t?.advance)), icon: Wallet, tone: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100', ring: 'ring-emerald-500' },
  ]

  const exportRows = () =>
    exportCsv(`suppliers-${payables.data?.as_of ?? 'list'}.csv`,
      ['Supplier', 'Code', 'Kind', 'Phone', 'GSTIN', 'Credit days', ...(seesMoney ? ['We owe', 'Overdue', 'Not billed', 'Open bills', 'Advance unused', 'Last paid', 'Last paid on'] : [])],
      shown.map((v) => [v.name, v.code ?? '', KINDS[v.kind ?? 'supplier'].label, v.phone ?? '', v.gstin ?? '', v.credit_days ?? '',
        ...(seesMoney ? [num(v.balance), num(v.overdue), num(v.unbilled), v.bills_open ?? 0, num(v.advance_left), v.last_payment ? num(v.last_payment.amount) : '', v.last_payment?.date ?? ''] : [])]))

  const loading = vendors.isLoading || (seesMoney && payables.isLoading)

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <header className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="inline-flex size-10 items-center justify-center rounded-xl bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-200"><Store className="size-5" /></span>
          <div>
            <div className="text-xs text-muted-foreground">Finance</div>
            <h1 className="text-2xl leading-tight font-semibold tracking-tight">Suppliers</h1>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" className="gap-2" disabled={!shown.length} onClick={exportRows} title="The suppliers shown, as a CSV file (opens in Excel)">
            <Download className="size-4" /> <span className="hidden sm:inline">Export</span>
          </Button>
          {!readOnly && (
            <Button className="gap-1.5 font-semibold" onClick={() => setEditing(null)}>
              <Plus className="size-4" /> <span className="hidden sm:inline">Add supplier</span><span className="sm:hidden">Add</span>
            </Button>
          )}
        </div>
      </header>

      {seesMoney && payables.isError ? (
        <Callout tone="draft" icon={TriangleAlert} action={<Button variant="outline" size="sm" className="bg-background" onClick={() => payables.refetch()}>Try again</Button>}>
          What is owed could not be loaded; the list below is the directory only.
        </Callout>
      ) : seesMoney && (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 sm:gap-3">
            {tiles.map((x) => {
              const on = tile === x.value
              return (
                <button key={x.value} type="button" aria-pressed={on} onClick={() => setTile(on ? '' : x.value)}
                  className={cn('flex items-center gap-3 rounded-xl border bg-card p-3 text-left transition hover:-translate-y-px sm:p-3.5', on && cn('ring-2', x.ring))}>
                  <span className={cn('inline-flex size-9 shrink-0 items-center justify-center rounded-lg sm:size-11 sm:rounded-xl', x.tone)}><x.icon className="size-4 sm:size-5" /></span>
                  <span className="flex min-w-0 flex-col">
                    <span className={cn('truncate text-xl leading-none font-semibold tabular-nums sm:text-2xl', x.value2 !== '₹0' && x.num)}>{loading ? '–' : x.value2}</span>
                    <span className="truncate text-xs text-muted-foreground sm:text-sm sm:text-foreground/80">{x.label}</span>
                  </span>
                </button>
              )
            })}
          </div>
          {payables.data && num(payables.data.totals.payable) + num(payables.data.totals.unbilled) > 0 && (
            <div className="rounded-xl border bg-card p-3">
              <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2 text-sm">
                <span className="font-medium">How long it has waited</span>
                <span className="text-xs text-muted-foreground">Unpaid bills and deliveries not billed, by their date{payables.data.partial ? ' · your projects only' : ''}</span>
              </div>
              <AgeBar buckets={payables.data.buckets} />
            </div>
          )}
        </>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="pointer-events-none absolute top-2 left-2.5 size-4 text-muted-foreground" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, phone, GSTIN" aria-label="Search suppliers" className="h-8 w-[200px] pl-8" />
          </div>
          <FilterSelect label="Kind" value={kind} onChange={setKind} className="w-[150px]"
            options={[{ value: 'all', label: 'All kinds' }, ...(Object.keys(KINDS) as VendorKind[]).map((k) => ({ value: k, label: KINDS[k].plural }))]} />
          <FilterSelect label="Status" value={status} onChange={setStatus} className="w-[140px]"
            options={[{ value: 'active', label: 'Switched on' }, { value: 'inactive', label: 'Switched off' }, { value: 'all', label: 'All' }]} />
        </div>
        {seesMoney && (
          <div role="tablist" aria-label="Sort" className="flex max-w-full gap-0.5 overflow-x-auto rounded-xl bg-muted p-1">
            {SORTS.map((s) => (
              <button key={s.value} role="tab" type="button" aria-selected={sort === s.value} onClick={() => setSort(s.value)}
                className={cn('inline-flex h-8 shrink-0 items-center rounded-lg px-3 text-sm whitespace-nowrap', sort === s.value ? 'bg-background font-semibold shadow-sm' : 'text-foreground/75 hover:text-foreground')}>
                {s.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {vendors.isError ? (
        <Callout tone="draft" icon={TriangleAlert} action={<Button variant="outline" size="sm" className="bg-background" onClick={() => vendors.refetch()}>Try again</Button>}>
          The suppliers could not be loaded.
        </Callout>
      ) : loading ? (
        <div className="flex flex-col gap-2">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-16 rounded-lg" />)}</div>
      ) : shown.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center">
          <Store className="size-6 text-muted-foreground" aria-hidden="true" />
          <p className="text-sm font-medium">{all.length ? 'No supplier matches' : 'No suppliers yet'}</p>
          <p className="max-w-sm text-sm text-muted-foreground">
            {all.length ? 'Clear a filter or a tile to see more.' : 'A shop named on a delivery, an order or an expense is added here by itself. Add one with its phone, GSTIN and credit days.'}
          </p>
          {(tile || kind !== 'all' || needle) && all.length > 0 && <Button variant="outline" size="sm" onClick={() => { setTile(''); setKind('all'); setQ('') }}>Clear filters</Button>}
        </div>
      ) : (
        <ul className="divide-y rounded-xl border bg-card">
          {shown.map((v) => {
            const bal = num(v.balance)
            const late = num(v.overdue)
            return (
              <li key={v.id} className={cn('relative flex items-center gap-3 px-3 py-2.5 hover:bg-muted/30', v.status !== 'active' && 'opacity-60')}>
                <VendorTile id={v.id} name={v.name} />
                <button type="button" className="flex min-w-0 flex-1 flex-col gap-0.5 text-left after:absolute after:inset-0" onClick={() => navigate(vendorUrl(v.id))}>
                  <span className="flex flex-wrap items-center gap-1.5">
                    <span className="truncate font-semibold">{v.name}</span>
                    {v.kind && v.kind !== 'supplier' && <span className={cn('rounded px-1.5 py-0.5 text-[11px] font-medium', KINDS[v.kind].chip)}>{KINDS[v.kind].label}</span>}
                    {v.status !== 'active' && <span className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">Switched off</span>}
                  </span>
                  <span className="line-clamp-1 text-xs text-muted-foreground">
                    {[v.code, v.contact_person, v.phone, v.gstin ? `GSTIN ${v.gstin}` : null, v.credit_days != null ? `${v.credit_days} days credit` : null].filter(Boolean).join(' · ') || 'No phone or GSTIN yet'}
                  </span>
                </button>
                {seesMoney && (
                  <span className="flex shrink-0 flex-col items-end">
                    <span className={cn('font-semibold tabular-nums', late > 0 ? 'text-destructive' : bal < 0 ? 'text-emerald-700 dark:text-emerald-400' : bal === 0 && 'text-muted-foreground')}>
                      {bal < 0 ? `+${rupees(-bal)}` : rupees(bal)}
                    </span>
                    <span className="max-w-[46vw] truncate text-xs text-muted-foreground sm:max-w-none">
                      {late > 0 ? `${rupees(late)} overdue` : bal < 0 ? 'paid ahead' : (v.unbilled_count ?? 0) > 0 ? `${v.unbilled_count} not billed` : v.bills_open ? `${v.bills_open} ${v.bills_open === 1 ? 'bill' : 'bills'} open` : v.last_payment ? `paid ${day(v.last_payment.date)}` : bal === 0 ? 'settled' : ''}
                    </span>
                  </span>
                )}
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button type="button" variant="ghost" size="icon" className="relative z-10 size-8 shrink-0" aria-label={`More for ${v.name}`}>
                      <MoreHorizontal className="size-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-52">
                    <DropdownMenuItem onClick={() => navigate(vendorUrl(v.id))}>Open account</DropdownMenuItem>
                    {canManage && <DropdownMenuItem onClick={() => setPaying(v)}>Pay {v.name.split(' ')[0]}</DropdownMenuItem>}
                    <DropdownMenuItem onClick={() => navigate(`/procurement/orders?vendor=${v.id}`)}>Its orders</DropdownMenuItem>
                    {seesMoney && <DropdownMenuItem onClick={() => navigate(`/finance/expenses?vendor=${v.id}&period=all`)}>Its expenses</DropdownMenuItem>}
                    {!readOnly && (
                      <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem onClick={() => setEditing(v)}>Edit</DropdownMenuItem>
                        {canManage && <DropdownMenuItem onClick={() => setMerging(v)}>Merge into another…</DropdownMenuItem>}
                        <DropdownMenuItem onClick={() => toggle.mutate(v)}>{v.status === 'active' ? 'Switch off' : 'Switch on'}</DropdownMenuItem>
                        {canManage && (
                          <DropdownMenuItem className="text-destructive" onClick={() => window.confirm(`Delete ${v.name}? Only a supplier added by mistake, with nothing recorded, can be deleted.`) && remove.mutate(v)}>
                            Delete
                          </DropdownMenuItem>
                        )}
                      </>
                    )}
                  </DropdownMenuContent>
                </DropdownMenu>
              </li>
            )
          })}
        </ul>
      )}
      {shown.length > 0 && <p className="text-xs text-muted-foreground">{shown.length} of {all.length} suppliers{payables.data ? ` · as of ${day(payables.data.as_of)}` : ''}</p>}

      <VendorFormDialog open={editing !== undefined} onOpenChange={(o) => !o && setEditing(undefined)} vendor={editing ?? null} canSetOpening={canManage}
        onSaved={(v) => editing === null && navigate(vendorUrl(v.id))} />
      {paying && (
        <PayVendorDialog open onOpenChange={(o) => !o && setPaying(null)} vendor={paying} projectId={projectId} />
      )}
      {merging && <MergeVendorDialog open onOpenChange={(o) => !o && setMerging(null)} vendor={merging} onMerged={() => setMerging(null)} />}
    </div>
  )
}
