import * as React from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlarmClock, FileWarning, MoreHorizontal, PackageOpen, Plus, Search, Store, TriangleAlert, Wallet } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { useToast } from '@/components/ui/toast-notification'
import { Callout } from '@/components/dpr-page'
import { FilterSelect } from '@/components/filter-select'
import { VendorTile } from '@/components/orders/order-detail'
import { LinkNamesDialog, MergeVendorDialog, PayVendorDialog, VendorFormDialog } from '@/components/vendors/vendor-dialogs'
import { AgeingCard } from '@/components/accounts/money-kit'
import { AGE_BARS } from '@/components/accounts/money-look'
import { UnbilledList } from '@/components/vendors/unbilled-list'
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
import { BUCKETS, KINDS, day, deleteVendor, fetchPayables, fetchUnlinkedNames, fetchVendors, num, updateVendor, vendorUrl, type Buckets, type PayableRow, type Vendor, type VendorKind } from '@/lib/vendors'
import { ModuleTitle, type KpiProps } from '@/components/page/page-kit'
import { ScoreChip } from '@/components/vendors/supplier-score'
import { useSupplierScores } from '@/lib/supplier-performance'
import { paperStatusWords, usePapersAttention } from '@/lib/vendor-documents'
import { ActionIcon } from '@/components/page/action-button'

// CC-09 (8 Nov 2026): Finance > Suppliers. Who the company buys from and pays, and -- for the roles that see spending
// -- what it owes each of them: four tiles that filter (we owe, overdue, delivered not billed, paid ahead), how old
// the money owed is, and one row per supplier with its balance. A row opens the supplier's page (ledger, bills, pay).
// UX-43 (Mercon's payables ageing as the reference): what you owe and how long it waited in one card (AgeingCard, as on
// Receivables), the four figures beside it still filtering, a part of the bar filtering by age; each supplier's own
// age bar under its balance.
// Everyone with Finance still sees the directory: a supplier is picked when an expense is recorded.

type Tile = '' | 'owe' | 'overdue' | 'unbilled' | 'ahead'
type Sort = 'owed' | 'overdue' | 'oldest' | 'score' | 'name'

const SORTS: { value: Sort; label: string }[] = [
  { value: 'owed', label: 'Most owed' },
  { value: 'overdue', label: 'Most overdue' },
  { value: 'oldest', label: 'Waiting longest' },
  { value: 'score', label: 'Best score' },  // PRC-50
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
  const [age, setAge] = useUrlState<string>('age', '')  // UX-43: a part of the age bar picked
  const [sort, setSort] = useUrlState<Sort>('sort', seesMoney ? 'owed' : 'name')
  const scores = useSupplierScores(seesMoney)
  // PRC-52: a supplier whose papers are expired, missing (GST / PAN of a registered one) or expiring soon.
  const papers = new Map((usePapersAttention().data ?? []).map((x) => [x.vendor_id, x]))
  const [view, setView] = useUrlState<'suppliers' | 'unbilled'>('view', 'suppliers')
  const [editing, setEditing] = React.useState<Vendor | null | undefined>(undefined)
  const [paying, setPaying] = React.useState<Row | null>(null)
  const [merging, setMerging] = React.useState<Vendor | null>(null)
  const [linking, setLinking] = React.useState(false)
  const unlinked = useQuery({ queryKey: ['vendors', 'unlinked'], queryFn: fetchUnlinkedNames, enabled: seesMoney, retry: false })

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
  // PRC-50: no score (too few orders) sorts after every scored supplier.
  const scoreOf = (v: Row) => Number(scores.get(v.id)?.score ?? -1)
  const shown = base.filter((v) => inTile(v, tile) && (!age || num(v.buckets?.[age as keyof Buckets]) > 0)).sort((a, b) => {
    if (sort === 'owed') return num(b.balance) - num(a.balance) || a.name.localeCompare(b.name)
    if (sort === 'overdue') return num(b.overdue) - num(a.overdue) || num(b.balance) - num(a.balance)
    if (sort === 'oldest') return oldest(a).localeCompare(oldest(b)) || num(b.balance) - num(a.balance)
    if (sort === 'score') return scoreOf(b) - scoreOf(a) || a.name.localeCompare(b.name)
    return a.name.localeCompare(b.name)
  })
  const t = payables.data?.totals
  const count = (x: Tile) => base.filter((v) => inTile(v, x)).length
  // UX-15: page kit figures. Overdue is red and shows its share of what we owe; delivered-not-billed is amber.
  const owe = num(t?.payable)
  const tiles: (KpiProps & { value2: Exclude<Tile, ''> })[] = [
    { value2: 'owe', label: 'We owe', value: rupees(owe), kind: 'money', hint: `${count('owe')} suppliers` },
    { value2: 'overdue', label: 'Overdue', value: rupees(num(t?.overdue)), icon: AlarmClock, tone: num(t?.overdue) > 0 ? 'bad' : 'default', share: owe > 0 ? num(t?.overdue) / owe : undefined, hint: `${count('overdue')} suppliers` },
    { value2: 'unbilled', label: 'Delivered, no bill', value: rupees(num(t?.unbilled)), icon: PackageOpen, tone: num(t?.unbilled) > 0 ? 'attention' : 'default', hint: `${count('unbilled')} suppliers` },
    { value2: 'ahead', label: 'Paid ahead', value: rupees(num(t?.advance)), icon: Wallet, hint: `${count('ahead')} suppliers` },
  ]

  const exportRows = () =>
    exportCsv(`suppliers-${payables.data?.as_of ?? 'list'}.csv`,
      ['Supplier', 'Code', 'Kind', 'Phone', 'GSTIN', 'Credit days', ...(seesMoney ? ['We owe', 'Overdue', 'Not billed', 'Open bills', 'Advance unused', 'Last paid', 'Last paid on'] : [])],
      shown.map((v) => [v.name, v.code ?? '', KINDS[v.kind ?? 'supplier'].label, v.phone ?? '', v.gstin ?? '', v.credit_days ?? '',
        ...(seesMoney ? [num(v.balance), num(v.overdue), num(v.unbilled), v.bills_open ?? 0, num(v.advance_left), v.last_payment ? num(v.last_payment.amount) : '', v.last_payment?.date ?? ''] : [])]))

  const loading = vendors.isLoading || (seesMoney && payables.isLoading)

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <header className="flex items-center justify-between gap-3">
        <ModuleTitle icon={Store} title="Suppliers" />
        <div className="flex items-center gap-2">
          <Button variant="outline" className="gap-2" disabled={!shown.length} onClick={exportRows} title="The suppliers shown, as a CSV file (opens in Excel)">
            <ActionIcon kind="export-excel" className="size-4" /> <span className="hidden sm:inline">Export</span>
          </Button>
          {!readOnly && (
            <Button className="gap-1.5 font-semibold" onClick={() => setEditing(null)} data-guide="vendors.add">
              <Plus className="size-4" /> <span className="hidden sm:inline">Add supplier</span><span className="sm:hidden">Add</span>
            </Button>
          )}
        </div>
      </header>

      {seesMoney && payables.isError ? (
        <Callout tone="draft" icon={TriangleAlert} action={<Button variant="outline" size="sm" className="bg-background" onClick={() => payables.refetch()}>Try again</Button>}>
          What is owed could not be loaded.
        </Callout>
      ) : seesMoney && (
        <>
          <AgeingCard
            guide="vendors.age"
            title="You owe suppliers"
            total={owe}
            totalHint={
              <>
                {count('owe')} suppliers{payables.data ? ` · as on ${day(payables.data.as_of)}` : ''}{payables.data?.partial ? ' · your projects only' : ''}
                <span className="block">The bar: unpaid bills and deliveries not billed, by how long they have waited</span>
              </>
            }
            buckets={BUCKETS.map((b, i) => ({ key: b.key, label: b.label, value: num(payables.data?.buckets[b.key]), bar: AGE_BARS[i], late: i >= 2 }))}
            active={age || null}
            onPick={(k) => setAge(k ?? '')}
            aside={
              <div data-guide="vendors.tiles" className="flex flex-wrap gap-2">
                {tiles.map(({ value2: x, label, value, hint }) => {
                  const pressed = tile === x
                  const tone = x === 'overdue' && num(t?.overdue) > 0 ? 'border-destructive/30 bg-destructive/[0.05] text-destructive' : x === 'unbilled' && num(t?.unbilled) > 0 ? 'border-draft/30 bg-draft-soft/50 text-draft' : x === 'ahead' ? 'border-emerald-500/30 bg-emerald-500/[0.06] text-emerald-700 dark:text-emerald-400' : 'bg-muted/40'
                  return (
                    <button
                      key={x}
                      type="button"
                      aria-pressed={pressed}
                      onClick={() => (x === 'unbilled' ? setView('unbilled') : setTile(pressed ? '' : x))}
                      className={cn('min-w-[7.5rem] rounded-lg border px-3 py-1.5 text-left text-xs transition-colors hover:brightness-95', tone, pressed && 'ring-2 ring-ring ring-offset-1 ring-offset-background')}
                    >
                      <span className="block text-muted-foreground">{label}</span>
                      <span className="text-sm font-semibold tabular-nums">
                        {loading ? '…' : value}
                        {x === 'overdue' && owe > 0 && num(t?.overdue) > 0 && <span className="ml-1 text-xs font-normal">{Math.round((num(t?.overdue) / owe) * 100)}%</span>}
                      </span>
                      <span className="block text-[11px] text-muted-foreground">{hint}</span>
                    </button>
                  )
                })}
              </div>
            }
          />
        </>
      )}

      {canManage && (unlinked.data?.length ?? 0) > 0 && (
        <Callout tone="info" icon={Store} action={<Button variant="outline" size="sm" className="bg-background" onClick={() => setLinking(true)}>Link them</Button>}>
          {unlinked.data!.length} supplier {unlinked.data!.length === 1 ? 'name' : 'names'} on {unlinked.data!.reduce((n, x) => n + x.deliveries, 0)} deliveries {unlinked.data!.length === 1 ? 'is' : 'are'} on no account yet.
        </Callout>
      )}

      {seesMoney && (
        <div role="tablist" aria-label="View" className="flex w-fit gap-0.5 rounded-xl bg-muted p-1" data-guide="vendors.view">
          {([['suppliers', 'Suppliers'], ['unbilled', 'Delivered, no bill']] as const).map(([v, l]) => (
            <button key={v} role="tab" type="button" aria-selected={view === v} onClick={() => setView(v)}
              className={cn('inline-flex h-8 items-center rounded-lg px-3 text-sm', view === v ? 'bg-background font-semibold shadow-sm' : 'text-foreground/75 hover:text-foreground')}>
              {l}
            </button>
          ))}
        </div>
      )}

      {seesMoney && view === 'unbilled' ? <UnbilledList projectId={projectId} /> : (<>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2" data-guide="vendors.search">
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
          <div role="tablist" aria-label="Sort" className="flex max-w-full gap-0.5 overflow-x-auto rounded-xl bg-muted p-1" data-guide="vendors.sort">
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
        <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center" data-guide="vendors.list">
          <Store className="size-6 text-muted-foreground" aria-hidden="true" />
          <p className="text-sm font-medium">{all.length ? 'No supplier matches' : 'No suppliers yet'}</p>
          {(tile || age || kind !== 'all' || needle) && all.length > 0 && <Button variant="outline" size="sm" onClick={() => { setTile(''); setAge(''); setKind('all'); setQ('') }}>Clear filters</Button>}
        </div>
      ) : (
        <ul className="divide-y rounded-xl border bg-card" data-guide="vendors.list">
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
                    {papers.get(v.id) && (
                      <span data-testid="papers-warning" role="img" className="relative z-10 inline-flex"
                        title={`Papers: ${papers.get(v.id)!.papers.map((x) => `${x.label} ${paperStatusWords(x.status, x.days_left).toLowerCase()}`).join(', ')}`}
                        aria-label={`Papers: ${papers.get(v.id)!.papers.map((x) => `${x.label} ${paperStatusWords(x.status, x.days_left).toLowerCase()}`).join(', ')}`}>
                        <FileWarning className={cn('size-4 shrink-0', papers.get(v.id)!.attention === 'expiring' ? 'text-amber-600' : 'text-red-600')} />
                      </span>
                    )}
                  </span>
                  <span className="line-clamp-1 text-xs text-muted-foreground">
                    {[v.code, v.contact_person, v.phone, v.gstin ? `GSTIN ${v.gstin}` : null, v.credit_days != null ? `${v.credit_days} days credit` : null].filter(Boolean).join(' · ') || 'No phone or GSTIN yet'}
                  </span>
                </button>
                {seesMoney && <ScoreChip p={scores.get(v.id)} className="relative z-10 text-xs" />}
                {seesMoney && (
                  <span className="flex shrink-0 flex-col items-end">
                    <span className={cn('font-semibold tabular-nums', late > 0 ? 'text-destructive' : bal < 0 ? 'text-emerald-700 dark:text-emerald-400' : bal === 0 && 'text-muted-foreground')}>
                      {bal < 0 ? `+${rupees(-bal)}` : rupees(bal)}
                    </span>
                    {bal > 0 && v.buckets && (() => {
                      const sum = BUCKETS.reduce((n, x) => n + num(v.buckets![x.key]), 0) || 1
                      return (
                        <span className="my-0.5 flex h-1.5 w-24 gap-px overflow-hidden rounded-full bg-muted" title={`${Math.round((bal / (owe || 1)) * 100)}% of all you owe`}>
                          {BUCKETS.map((x, i) => num(v.buckets![x.key]) > 0 && <span key={x.key} className={cn('h-full', AGE_BARS[i])} style={{ width: `${(num(v.buckets![x.key]) / sum) * 100}%` }} />)}
                        </span>
                      )
                    })()}
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
      </>)}

      <VendorFormDialog open={editing !== undefined} onOpenChange={(o) => !o && setEditing(undefined)} vendor={editing ?? null} canSetOpening={canManage}
        onSaved={(v) => editing === null && navigate(vendorUrl(v.id))} />
      {paying && (
        <PayVendorDialog open onOpenChange={(o) => !o && setPaying(null)} vendor={paying} projectId={projectId} />
      )}
      <LinkNamesDialog open={linking} onOpenChange={setLinking} names={unlinked.data ?? []} />
      {merging && <MergeVendorDialog open onOpenChange={(o) => !o && setMerging(null)} vendor={merging} onMerged={() => setMerging(null)} />}
    </div>
  )
}
