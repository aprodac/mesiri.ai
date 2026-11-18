import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ArrowLeftRight, ArrowRight, FileText, MapPin, MessageSquare, Package, TriangleAlert, Truck } from 'lucide-react'
import { ArrowDownLeft as IcArrowDownLeft, ArrowUpRight as IcArrowUpRight, Warehouse as IcWarehouse, Package as IcPackage, IndianRupee as IcIndianRupee } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Callout, StatStrip } from '@/components/dpr-page'
import {
  fetchInventory,
  fetchLedgerRows,
  fetchAllMaterials,
  fetchTransfers,
  formatMoney,
  REASON_WORDS,
  type LedgerRow,
} from '@/lib/materials'
import { fetchUsers } from '@/lib/api'
import { useSiteNames } from '@/lib/site-names'
import { localIsoDate, qty } from '@/lib/site-day'
import { useUrlState } from '@/lib/url-state'
import { periodRange, type Period } from '@/lib/period'
import { PeriodSelect } from '@/components/filter-select'
import { cn } from '@/lib/utils'
import { MovementDetailsSheet } from './movement-details-sheet'
import { InvoiceDetailsSheet } from './invoice-details-sheet'
import { ActionIcon } from '@/components/page/action-button'
import { StateBar, ToggleChip, type StateItem } from '@/components/page/page-kit'
import type { Tone } from '@/lib/list-kit'
import { appNow } from '@/lib/clock'
import { Pager } from '@/components/page/pager'
import { usePagedUrl } from '@/lib/paging'

// WEB-30: one ledger of everything that came in and went out -- deliveries,
// use, moves between sites, corrections -- as a table: In in green, Out in
// red. Pick a material and it becomes that material's stock book, with the
// stock left on the site after every line and totals at the foot.

// WEB-78: deliveries on a purchase order or on none ("bought outside an order") are a filter of their own.
type Dir = 'all' | 'in' | 'out' | 'order' | 'loose' | 'delivery' | 'used' | 'move' | 'other'

// UX-69: each line's kind, for the kind chips (Deliveries, Used, Moves, Other: returns, wastage, corrections, opening).
type Kind = 'delivery' | 'used' | 'move' | 'other'
const kindOf = (r: LedgerRow): Kind =>
  r.transfer_id || r.movement_reason === 'TRANSFER_IN' || r.movement_reason === 'TRANSFER_OUT' ? 'move'
    : r.movement_reason === 'RECEIVED' && !r.reverses_movement_id ? 'delivery'
      : r.movement_reason === 'CONSUMED' && !r.reverses_movement_id ? 'used' : 'other'
const KINDS: { value: Kind; label: string; icon: typeof Truck; tone: Tone }[] = [
  { value: 'delivery', label: 'Deliveries', icon: Truck, tone: 'good' },
  { value: 'used', label: 'Used', icon: IcArrowUpRight, tone: 'bad' },
  { value: 'move', label: 'Moves', icon: ArrowLeftRight, tone: 'info' },
  { value: 'other', label: 'Other', icon: Package, tone: 'muted' },
]

const onOrder = (r: LedgerRow) => r.direction === 'IN' && !!r.purchase_order_id
const looseDelivery = (r: LedgerRow) => r.direction === 'IN' && r.movement_reason === 'RECEIVED' && !r.purchase_order_id && !r.transfer_id && !r.reverses_movement_id

const dayLabel = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })

export function LedgerView({ projectId, siteId: scopeSiteId, leading }: { projectId: string | null; siteId: string | null; leading?: React.ReactNode }) {
  const siteNames = useSiteNames()
  const [materialId, setMaterialId] = useUrlState<string>('material', 'all')
  const [pickedSite, setPickedSite] = useUrlState<string>('at', 'all')
  const [period, setPeriod] = useUrlState<Period>('period', '30d')
  const [from, setFrom] = useUrlState<string>('from', '')
  const [to, setTo] = useUrlState<string>('to', '')
  const [dir, setDir] = useUrlState<Dir>('dir', 'all')
  const [openRow, setOpenRow] = React.useState<LedgerRow | null>(null)
  const [invoiceId, setInvoiceId] = React.useState<string | null>(null)
  const [today] = React.useState(() => appNow())

  const siteId = scopeSiteId ?? (pickedSite === 'all' ? null : pickedSite)
  const material = materialId === 'all' ? null : materialId
  const { from: rangeFrom, to: rangeTo } = periodRange(period, from, to)
  const range = React.useMemo(() => ({ from: rangeFrom, to: rangeTo }), [rangeFrom, rangeTo])

  const catalogue = useQuery({ queryKey: ['materials', 'catalog', 'manage'], queryFn: () => fetchAllMaterials(), staleTime: 60_000 })
  // With one material, load its whole history so "stock after" is right
  // whatever the dates; the dates then only choose which lines show.
  const scopeFilters = { project_id: projectId ?? undefined, site_id: siteId ?? undefined }
  const query = useQuery({
    queryKey: ['materials', 'ledger-rows', scopeFilters, material, material ? null : range],
    queryFn: () =>
      fetchLedgerRows(material ? { ...scopeFilters, material_id: material } : { ...scopeFilters, date_from: range.from, date_to: range.to }),
  })
  const inventory = useQuery({
    queryKey: ['materials', 'inventory', scopeFilters],
    queryFn: () => fetchInventory(scopeFilters),
    enabled: !!material,
  })
  const transfers = useQuery({
    queryKey: ['materials', 'transfers', projectId],
    queryFn: () => fetchTransfers({ project_id: projectId ?? undefined, limit: 100 }),
  })
  const users = useQuery({ queryKey: ['users-list'], queryFn: fetchUsers, retry: false, staleTime: 5 * 60_000 })
  const userName = React.useMemo(() => new Map((users.data ?? []).map((u) => [u.id, u.full_name.split(' ')[0]])), [users.data])
  const transferById = React.useMemo(() => new Map((transfers.data?.items ?? []).map((t) => [t.id, t])), [transfers.data])

  // Stock on the site after each line (one material only), then the lines
  // the filters ask for, newest first.
  const { lines, balanceAfter } = React.useMemo(() => {
    const all = query.data?.rows ?? []
    const after = new Map<string, number>()
    if (material) {
      const bySite = new Map<string, number>()
      for (const r of all) {
        const key = r.site_id ?? ''
        const next = (bySite.get(key) ?? 0) + (r.direction === 'IN' ? 1 : -1) * Number(r.quantity)
        bySite.set(key, next)
        after.set(r.id, next)
      }
    }
    const shown = all
      .filter((r) => (dir === 'all' ? true : dir === 'in' ? r.direction === 'IN' : dir === 'out' ? r.direction === 'OUT' : dir === 'order' ? onOrder(r) : dir === 'loose' ? looseDelivery(r) : kindOf(r) === dir))
      .filter((r) => !material || ((!range.from || r.occurred_date >= range.from) && (!range.to || r.occurred_date <= range.to)))
      .reverse()
    return { lines: shown, balanceAfter: after }
  }, [query.data, material, dir, range])

  // UX-37: numbered pages, kept in the address.
  const pagedLines = usePagedUrl(lines)
  const unit = material ? catalogue.data?.items.find((m) => m.id === material)?.default_unit ?? lines[0]?.unit ?? '' : ''
  const materialName = material ? catalogue.data?.items.find((m) => m.id === material)?.name ?? 'Material' : null
  const totalIn = lines.filter((r) => r.direction === 'IN').reduce((s, r) => s + Number(r.quantity), 0)
  const totalOut = lines.filter((r) => r.direction === 'OUT').reduce((s, r) => s + Number(r.quantity), 0)
  const spent = lines.reduce((s, r) => s + (r.direction === 'IN' && 'total_cost' in r && r.total_cost && !r.is_reversed ? Number(r.total_cost) : 0), 0)
  const stockNow = (inventory.data ?? []).filter((s) => s.material_id === material).reduce((s, r) => s + Number(r.current_stock), 0)
  const sitesInScope = [...siteNames.entries()].filter(([, s]) => !projectId || s.projectId === projectId).sort(([, a], [, b]) => (a.project + a.name).localeCompare(b.project + b.name))
  const showSite = !siteId
  // The lines in the dates and scope, before the kind filter: what the kind chips and the day chart count.
  const inRange = React.useMemo(() => (query.data?.rows ?? []).filter((r) => !material || ((!range.from || r.occurred_date >= range.from) && (!range.to || r.occurred_date <= range.to))), [query.data, material, range])
  const filtered = material !== null || dir !== 'all' || pickedSite !== 'all' || period !== '30d'

  const kind = (r: LedgerRow) => {
    const t = r.transfer_id ? transferById.get(r.transfer_id) : undefined
    if (t) {
      const other = r.direction === 'OUT' ? t.to_site_name ?? siteNames.get(t.to_site_id)?.name : t.from_site_name ?? siteNames.get(t.from_site_id)?.name
      return (
        <span className="inline-flex items-center gap-1">
          {r.direction === 'OUT' ? 'Moved to' : 'Moved from'} {other ?? 'another site'}
        </span>
      )
    }
    return REASON_WORDS[r.movement_reason] ?? r.movement_reason
  }
  const detail = (r: LedgerRow) => (r.direction === 'IN' ? r.supplier : r.work_item) || r.notes || ''

  const exportCsv = () => {
    const head = ['Date', 'Site', 'Project', 'Material', 'Kind', 'Details', 'Order', 'GRN', 'In', 'Out', 'Unit', ...(material ? ['Stock after'] : []), 'Cost', 'Recorded by', 'From']
    const body = lines.map((r) => {
      const s = r.site_id ? siteNames.get(r.site_id) : undefined
      const k = kind(r)
      return [
        r.occurred_date,
        s?.name ?? '',
        s?.project ?? '',
        r.material_name,
        typeof k === 'string' ? k : r.direction === 'OUT' ? 'Moved to another site' : 'Moved from another site',
        detail(r),
        r.direction === 'IN' ? r.order_ref ?? '' : '',
        r.direction === 'IN' ? r.grn_ref ?? '' : '',
        r.direction === 'IN' ? r.quantity : '',
        r.direction === 'OUT' ? r.quantity : '',
        r.unit,
        ...(material ? [String(balanceAfter.get(r.id) ?? '')] : []),
        r.direction === 'IN' && r.total_cost ? r.total_cost : '',
        (r.created_by && userName.get(r.created_by)) || '',
        r.source === 'whatsapp' ? 'WhatsApp' : 'Dashboard',
      ]
    })
    const csv = [head, ...body].map((row) => row.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(',')).join('\n')
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
    a.download = `materials-ledger-${materialName ? materialName.toLowerCase().replace(/\s+/g, '-') + '-' : ''}${localIsoDate(today)}.csv`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Filters -- WEB-40: all dropdowns, in one row after the view switch. */}
      <div className="flex flex-wrap items-center gap-2">
        {leading}
        <Select value={materialId} onValueChange={setMaterialId}>
          <SelectTrigger className="h-8 w-[170px] gap-1.5 rounded-md [&>span]:flex-1 [&>span]:text-left" aria-label="Material">
            <Package className="size-3.5 text-muted-foreground" />
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All materials</SelectItem>
            {(catalogue.data?.items ?? [])
              .filter((m) => m.is_active || m.id === material)
              .sort((a, b) => a.name.localeCompare(b.name))
              .map((m) => (
                <SelectItem key={m.id} value={m.id}>
                  {m.name}
                </SelectItem>
              ))}
          </SelectContent>
        </Select>
        {!scopeSiteId && sitesInScope.length > 1 && (
          <Select value={pickedSite} onValueChange={setPickedSite}>
            <SelectTrigger className="h-8 w-[170px] gap-1.5 rounded-md [&>span]:flex-1 [&>span]:text-left" aria-label="Site">
              <MapPin className="size-3.5 text-muted-foreground" />
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All sites</SelectItem>
              {sitesInScope.map(([id, s]) => (
                <SelectItem key={id} value={id}>
                  {s.name}
                  {!projectId && <span className="text-muted-foreground"> · {s.project}</span>}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        <PeriodSelect value={period} onChange={setPeriod} from={from} to={to} onFrom={setFrom} onTo={setTo} />

        <div className="ml-auto flex items-center gap-1">
          {filtered && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setMaterialId('all')
                setPickedSite('all')
                setPeriod('30d')
                setDir('all')
              }}
            >
              Clear
            </Button>
          )}
          <Button variant="outline" size="sm" className="gap-1.5" disabled={lines.length === 0} onClick={exportCsv}>
            <ActionIcon kind="export-excel" className="size-3.5" /> CSV
          </Button>
        </div>
      </div>

      {/* The lines' totals */}
      {query.data && (
        <StatStrip
          phoneCols={2}
          stats={
            material
              ? [
                  { label: 'Came in', value: totalIn ? `+${qty(String(totalIn))} ${unit}` : '—', tone: totalIn ? 'good' : 'default', icon: IcArrowDownLeft },
                  { label: 'Went out', value: totalOut ? `−${qty(String(totalOut))} ${unit}` : '—', tone: totalOut ? 'bad' : 'default', icon: IcArrowUpRight },
                  { label: siteId ? 'On site now' : 'On sites now', value: inventory.isLoading ? '…' : `${qty(String(stockNow))} ${unit}`, tone: stockNow < 0 ? 'bad' : stockNow === 0 ? 'warn' : 'default', icon: IcWarehouse, hint: stockNow < 0 ? 'more used than received' : stockNow === 0 ? 'run out' : undefined },
                  { label: 'Spent', value: spent ? `₹${spent.toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—', icon: IcIndianRupee },
                ]
              : [
                  { label: 'Came in', value: lines.filter((r) => r.direction === 'IN').length || '—', tone: 'good', icon: IcArrowDownLeft, hint: 'deliveries and moves in' },
                  { label: 'Went out', value: lines.filter((r) => r.direction === 'OUT').length || '—', tone: 'bad', icon: IcArrowUpRight, hint: 'used, moved or returned' },
                  { label: 'Materials', value: new Set(lines.map((r) => r.material_name)).size || '—', icon: IcPackage },
                  { label: 'Spent', value: spent ? `₹${spent.toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—', icon: IcIndianRupee, hint: 'on deliveries' },
                ]
          }
        />
      )}
      {query.data && inRange.length > 0 && (
        <StateBar
          guide="materials.kinds"
          items={KINDS.map((k): StateItem => ({ value: k.value, label: k.label, icon: k.icon, tone: k.tone, count: inRange.filter((r) => kindOf(r) === k.value).length }))}
          value={['delivery', 'used', 'move', 'other'].includes(dir) ? dir : ''}
          onChange={(v) => setDir((v || 'all') as Dir)}
          extra={
            <>
              <ToggleChip on={dir === 'order'} onClick={() => setDir(dir === 'order' ? 'all' : 'order')} icon={FileText} count={inRange.filter(onOrder).length} label="on an order" />
              <ToggleChip on={dir === 'loose'} onClick={() => setDir(dir === 'loose' ? 'all' : 'loose')} icon={TriangleAlert} tone="attention" count={inRange.filter(looseDelivery).length} label="no order" />
            </>
          }
        >
          <DayChart rows={inRange} unit={material ? unit : null} />
        </StateBar>
      )}
      {query.data?.truncated && (
        <Callout tone="muted" icon={TriangleAlert}>
          Newest entries only. Narrow the filters to see all.
        </Callout>
      )}

      {query.isError ? (
        <Callout
          tone="draft"
          icon={TriangleAlert}
          action={
            <Button variant="outline" size="sm" className="bg-background" onClick={() => query.refetch()}>
              Try again
            </Button>
          }
        >
          The ledger could not be loaded.
        </Callout>
      ) : query.isLoading ? (
        <div className="flex flex-col gap-1.5">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-9 rounded-md" />
          ))}
        </div>
      ) : lines.length === 0 ? (
        <p className="rounded-xl border border-dashed bg-card py-12 text-center text-sm text-muted-foreground">
          {filtered ? 'Nothing came in or went out for these filters.' : 'Nothing has come in or gone out in the last 30 days.'}
        </p>
      ) : (
        <>
        {/* Phones: one line per entry, the quantity in green or red on the right. */}
        <ul className="divide-y overflow-hidden rounded-xl border bg-card shadow-xs sm:hidden" data-guide="materials.list">
          {pagedLines.shown.map((r, i) => {
            const newDay = i === 0 || pagedLines.shown[i - 1].occurred_date !== r.occurred_date
            const site = r.site_id ? siteNames.get(r.site_id) : undefined
            const after = balanceAfter.get(r.id)
            return (
              <li key={`m-${r.direction}-${r.id}`} data-record-id={r.id}>
                {newDay && <div className="border-b bg-muted/30 px-3 py-1 text-xs font-semibold">{dayLabel(r.occurred_date)}</div>}
                <button type="button" onClick={() => setOpenRow(r)} className="flex w-full items-center gap-3 px-3 py-2 text-left">
                  <div className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate font-medium">
                      {material ? kind(r) : r.material_name}
                      {!material && <span className="font-normal text-muted-foreground"> · {kind(r)}</span>}
                    </span>
                    <span className="truncate text-xs text-muted-foreground">{[showSite && site?.name, detail(r)].filter(Boolean).join(' · ') || '—'}</span>
                    {r.direction === 'IN' && r.order_ref && <OrderChip row={r} link={false} className="mt-1 self-start" />}
                  </div>
                  <div className="flex shrink-0 flex-col items-end">
                    <span className={cn('font-semibold tabular-nums', r.direction === 'IN' ? 'text-success' : 'text-destructive')}>
                      {r.direction === 'IN' ? '+' : '−'}
                      {qty(r.quantity)} <span className="text-xs font-normal text-muted-foreground">{r.unit}</span>
                    </span>
                    {after !== undefined && <span className={cn('text-xs tabular-nums', after < 0 ? 'text-destructive' : 'text-muted-foreground')}>left {qty(String(after))}</span>}
                  </div>
                </button>
              </li>
            )
          })}
        </ul>
        <div className="hidden overflow-x-auto rounded-xl border bg-card shadow-xs sm:block" data-guide="materials.list">
          <table className="w-full min-w-[760px] text-sm">
            <thead className="sticky top-0 border-b bg-muted/50 text-xs text-muted-foreground">
              <tr className="text-left">
                <th className="px-3 py-2 font-medium">Date</th>
                {showSite && <th className="px-3 py-2 font-medium">Site</th>}
                {!material && <th className="px-3 py-2 font-medium">Material</th>}
                <th className="px-3 py-2 font-medium">What</th>
                <th className="px-3 py-2 font-medium">Details</th>
                <th className="bg-success-soft/60 px-3 py-2 text-right font-medium text-success">In</th>
                <th className="bg-destructive/[0.06] px-3 py-2 text-right font-medium text-destructive">Out</th>
                {material && <th className="px-3 py-2 text-right font-medium">Stock after</th>}
                <th className="px-3 py-2 text-right font-medium">Cost</th>
                <th className="px-3 py-2 font-medium">By</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {pagedLines.shown.map((r, i) => {
                const newDay = i === 0 || pagedLines.shown[i - 1].occurred_date !== r.occurred_date
                const site = r.site_id ? siteNames.get(r.site_id) : undefined
                const correction = Boolean(r.reverses_movement_id) || (r.direction === 'IN' && Boolean(r.is_reversed))
                const after = balanceAfter.get(r.id)
                return (
                  <tr
                    key={`${r.direction}-${r.id}`}
                    data-record-id={r.id}
                    onClick={() => setOpenRow(r)}
                    className={cn(
                      'cursor-pointer border-t hover:bg-muted/40',
                      // WEB-37 / UX-69: each day reads as a block by a stronger line where it starts; the table stays white.
                      newDay && i > 0 && 'border-t-2 border-t-foreground/15',
                      correction && 'text-muted-foreground',
                    )}
                  >
                    <td className={cn('whitespace-nowrap px-3 py-1.5 font-medium', !newDay && 'text-transparent')}>{dayLabel(r.occurred_date)}</td>
                    {showSite && (
                      <td className="whitespace-nowrap px-3 py-1.5">
                        {site && r.site_id && !scopeSiteId ? <button type="button" className="hover:underline" title={`Only ${site.name}`} onClick={(e) => { e.stopPropagation(); setPickedSite(r.site_id!) }}>{site.name}</button> : site?.name ?? '—'}
                        {!projectId && site && <span className="text-xs text-muted-foreground"> · {site.project}</span>}
                      </td>
                    )}
                    {!material && (
                      <td className="whitespace-nowrap px-3 py-1.5 font-medium">
                        <button type="button" className="hover:underline" title={`Only ${r.material_name}`} onClick={(e) => { e.stopPropagation(); if (r.material_id) setMaterialId(r.material_id) }}>{r.material_name}</button>
                      </td>
                    )}
                    <td className="whitespace-nowrap px-3 py-1.5">
                      {kind(r)}
                      {correction && <span className="ml-1.5 text-xs text-draft">{r.reverses_movement_id ? 'correction' : 'corrected'}</span>}
                    </td>
                    <td className="max-w-[260px] truncate px-3 py-1.5 text-muted-foreground">
                      {r.direction === 'IN' && r.order_ref && <OrderChip row={r} className="mr-1.5" />}
                      {detail(r)}
                      {r.direction === 'IN' && r.invoice_id && (
                        <button
                          type="button"
                          className="ml-1.5 inline-flex items-center gap-0.5 text-foreground hover:underline"
                          onClick={(e) => {
                            e.stopPropagation()
                            setInvoiceId(r.invoice_id!)
                          }}
                        >
                          <FileText className="size-3" /> invoice
                        </button>
                      )}
                    </td>
                    <td className="whitespace-nowrap bg-success-soft/40 px-3 py-1.5 text-right font-semibold text-success">
                      {r.direction === 'IN' ? `+${qty(r.quantity)}` : ''}
                      {r.direction === 'IN' && <span className="ml-1 text-xs font-normal text-muted-foreground">{r.unit}</span>}
                    </td>
                    <td className="whitespace-nowrap bg-destructive/[0.04] px-3 py-1.5 text-right font-semibold text-destructive">
                      {r.direction === 'OUT' ? `−${qty(r.quantity)}` : ''}
                      {r.direction === 'OUT' && <span className="ml-1 text-xs font-normal text-muted-foreground">{r.unit}</span>}
                    </td>
                    {material && (
                      <td className={cn('whitespace-nowrap px-3 py-1.5 text-right', after !== undefined && after < 0 && 'font-semibold text-destructive')}>
                        {after !== undefined ? qty(String(after)) : ''}
                      </td>
                    )}
                    <td className="whitespace-nowrap px-3 py-1.5 text-right">
                      {r.direction === 'IN' && r.total_cost ? formatMoney(r.total_cost) : ''}
                    </td>
                    <td className="whitespace-nowrap px-3 py-1.5 text-muted-foreground">
                      {r.source === 'whatsapp' && <MessageSquare className="mr-1 inline size-3" aria-label="From WhatsApp" />}
                      {(r.created_by && userName.get(r.created_by)) || ''}
                    </td>
                  </tr>
                )
              })}
            </tbody>
            {material && (
              <tfoot className="border-t-2 bg-muted/40 font-semibold tabular-nums">
                <tr>
                  <td className="px-3 py-2" colSpan={showSite ? 4 : 3}>
                    Total{dir === 'all' ? '' : dir === 'in' ? ' in' : ' out'} · {lines.length} {lines.length === 1 ? 'entry' : 'entries'}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right text-success">{totalIn ? `+${qty(String(totalIn))}` : ''}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-right text-destructive">{totalOut ? `−${qty(String(totalOut))}` : ''}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-right">
                    <span className="inline-flex items-center gap-1 text-xs font-normal text-muted-foreground">
                      net <ArrowRight className="size-3" />
                    </span>{' '}
                    {qty(String(totalIn - totalOut))}
                  </td>
                  <td className="px-3 py-2 text-right">{spent ? `₹${spent.toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : ''}</td>
                  <td />
                </tr>
              </tfoot>
            )}
          </table>
        </div>
        <Pager {...pagedLines.pager} noun="entries" className="mt-2" />
        </>
      )}

      <MovementDetailsSheet direction={openRow?.direction ?? 'IN'} id={openRow?.id ?? null} open={openRow !== null} onOpenChange={(open) => !open && setOpenRow(null)} />
      <InvoiceDetailsSheet invoiceId={invoiceId} open={invoiceId !== null} onOpenChange={(open) => !open && setInvoiceId(null)} />
    </div>
  )
}

/** WEB-78: "PO-0002 · GRN-0001" on a delivery that came on an order; opens the order. */
function OrderChip({ row, className, link = true }: { row: LedgerRow; className?: string; link?: boolean }) {
  if (row.direction !== 'IN' || !row.order_ref || !row.purchase_order_id) return null
  const look = cn('inline-flex items-center gap-1 rounded-md bg-blue-100 px-1.5 py-0.5 text-[11px] font-semibold text-blue-950 dark:bg-blue-950 dark:text-blue-100', className)
  // Inside a row that is itself a button (phones) it is a label; the details sheet links the order.
  if (!link)
    return (
      <span className={look}>
        <Truck className="size-3" />
        {row.order_ref}
        {row.grn_ref && <span className="font-normal opacity-80">· {row.grn_ref}</span>}
      </span>
    )
  return (
    <Link
      to={`/procurement/orders?id=${row.purchase_order_id}`}
      onClick={(e) => e.stopPropagation()}
      title="Came on this purchase order"
      className={cn(look, 'hover:underline')}
    >
      <Truck className="size-3" />
      {row.order_ref}
      {row.grn_ref && <span className="font-normal opacity-80">· {row.grn_ref}</span>}
    </Link>
  )
}

/** UX-69: each day in the dates picked, what came in (green, up) against what went out (red, down): lines per day, or
 * the quantity when one material is picked, so a jump stands out. Hover a day for its figures. */
function DayChart({ rows, unit }: { rows: LedgerRow[]; unit: string | null }) {
  const days = React.useMemo(() => {
    const m = new Map<string, { inn: number; out: number }>()
    for (const r of rows) {
      const x = m.get(r.occurred_date) ?? { inn: 0, out: 0 }
      const v = unit ? Number(r.quantity) : 1
      if (r.direction === 'IN') x.inn += v
      else x.out += v
      m.set(r.occurred_date, x)
    }
    const keys = [...m.keys()].sort()
    if (!keys.length) return []
    const out: { day: string; inn: number; out: number }[] = []
    const d = new Date(`${keys[0]}T00:00:00`)
    const end = new Date(`${keys[keys.length - 1]}T00:00:00`)
    while (d <= end && out.length < 93) {
      const k = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
      out.push({ day: k, ...(m.get(k) ?? { inn: 0, out: 0 }) })
      d.setDate(d.getDate() + 1)
    }
    return out
  }, [rows, unit])
  if (days.length < 2) return null
  const top = Math.max(1, ...days.map((d) => Math.max(d.inn, d.out)))
  const what = unit ? unit : 'entries'
  return (
    <div className="flex flex-col gap-1" data-guide="materials.chart">
      <div className="flex h-20 items-stretch gap-px" role="img" aria-label={`In and out per day, ${what}`}>
        {days.map((d) => (
          <div key={d.day} className="flex min-w-0 flex-1 flex-col" title={`${dayLabel(d.day)}: +${qty(String(d.inn))} in, −${qty(String(d.out))} out ${what}`}>
            <div className="flex flex-1 items-end"><div className="w-full rounded-t-sm bg-success/70" style={{ height: `${(d.inn / top) * 100}%` }} /></div>
            <div className="h-px bg-border" />
            <div className="flex flex-1 items-start"><div className="w-full rounded-b-sm bg-destructive/60" style={{ height: `${(d.out / top) * 100}%` }} /></div>
          </div>
        ))}
      </div>
      <div className="flex justify-between text-[11px] text-muted-foreground tabular-nums">
        <span>{dayLabel(days[0].day)}</span>
        <span className="inline-flex items-center gap-3"><span className="inline-flex items-center gap-1"><span className="h-2 w-3 rounded-sm bg-success/70" />In</span><span className="inline-flex items-center gap-1"><span className="h-2 w-3 rounded-sm bg-destructive/60" />Out</span>{unit ? ` · ${unit}` : ' · entries a day'}</span>
        <span>{dayLabel(days[days.length - 1].day)}</span>
      </div>
    </div>
  )
}
