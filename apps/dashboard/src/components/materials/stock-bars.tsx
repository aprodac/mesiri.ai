import { ArrowLeftRight, CalendarClock, ClipboardList, ShoppingCart, Truck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Pill } from '@/components/page/page-kit'
import { CategoryTile } from '@/components/requests/parts'
import { qty } from '@/lib/site-day'
import { TONE, type Tone } from '@/lib/list-kit'
import { cn } from '@/lib/utils'
import type { StockSummaryRow } from '@/lib/materials'
import type { StockFlow } from '@/lib/stock-flow'
import type { OrderPrefill } from '@/components/orders/new-order-dialog'
import type { TransferPrefill } from './record-transfer-dialog'

// UX-69 (18 Nov 2026): Materials › Stock as bars (the Numbers view keeps the full table). One card a material: what is
// in stock in all, a bar per site the width of its stock against the fullest site, coloured by its state (out red,
// low amber, fine green), how many days it lasts as a chip, coming and asked as chips. Two actions where they help:
// "Move" when one site is low and another on screen holds spare (the transfer form filled in), and "Order" on a low
// site for the office (a purchase order filled in with what brings it back up). All from the stock summary the page
// already reads.

export type SiteNames = Map<string, { name: string; project: string; projectId: string }>

/** Low enough to act on (Move / Order): out, running low or below its minimum. */
export function isLow(r: StockSummaryRow): boolean {
  return isOut(r) || r.running_low || !!r.below_min
}

function isOut(r: StockSummaryRow): boolean {
  return Number(r.closing) <= 0 && (Number(r.used) > 0 || Number(r.opening) > 0 || Number(r.received) > 0)
}

/** A site's colour, the same rule as its days chip: out or under 3 days red, low or under 7 days amber, else green. */
export function stockTone(r: StockSummaryRow): Tone {
  const d = r.days_left === null ? null : Math.round(r.days_left)
  if (isOut(r) || (d !== null && d < 3)) return 'bad'
  if (r.running_low || r.below_min || (d !== null && d < 7)) return 'attention'
  return 'good'
}

/** How long the stock lasts, as a chip: out, N days (red under 3, amber under 7), or nothing to say. */
export function DaysChip({ row: r }: { row: StockSummaryRow }) {
  if (isOut(r)) return <Pill tone="bad" size="xs" icon={CalendarClock}>Out</Pill>
  if (r.days_left === null) return r.below_min ? <Pill tone="attention" size="xs">Below min</Pill> : null
  const d = Math.max(0, Math.round(r.days_left))
  const tone: Tone = d < 3 ? 'bad' : d < 7 ? 'attention' : 'good'
  return <Pill tone={tone} size="xs" icon={CalendarClock} title="At the rate it has been used">{d >= 60 ? '60+ d' : `${d} d`}</Pill>
}

/** What to order for a low site: its reorder quantity, else two weeks of use less what is coming, else up to the minimum. */
export function orderQuantity(r: StockSummaryRow, periodDays: number): string {
  if (r.reorder_qty && Number(r.reorder_qty) > 0) return r.reorder_qty
  const perDay = Number(r.used) / Math.max(1, periodDays)
  const twoWeeks = Math.ceil(perDay * 14 - Number(r.on_order ?? 0) - Math.max(0, Number(r.closing)))
  if (twoWeeks > 0) return String(twoWeeks)
  const toMin = Math.ceil(Number(r.min_qty ?? 0) - Number(r.closing) - Number(r.on_order ?? 0))
  return toMin > 0 ? String(toMin) : ''
}

const EDGE: Record<'good' | 'attention' | 'bad', string> = { good: 'before:bg-success/60', attention: 'before:bg-draft', bad: 'before:bg-destructive' }

export interface StockGroup { key: string; name: string; list: StockSummaryRow[] }

export function StockBars({ groups, siteNames, flowOf, canOrder, canMove, periodDays, openedKey, onOpen, onMove, onOrder }: {
  groups: StockGroup[]
  siteNames: SiteNames
  flowOf: (r: StockSummaryRow) => StockFlow
  canOrder: boolean
  canMove: boolean
  periodDays: number
  openedKey: string
  onOpen: (key: string) => void
  onMove: (p: TransferPrefill) => void
  onOrder: (p: OrderPrefill) => void
}) {
  return (
    <div className="flex flex-col gap-4" data-guide="materials.bars">
      {groups.map((g) => {
        const byMaterial = new Map<string, StockSummaryRow[]>()
        for (const r of g.list) byMaterial.set(r.material_id, [...(byMaterial.get(r.material_id) ?? []), r])
        return (
          <section key={g.key} className="flex flex-col gap-2">
            <h3 className="flex items-center gap-2 text-sm font-semibold">
              <CategoryTile mainCategory={g.key === '__none__' ? null : g.key} size="sm" />
              {g.name} <span className="font-normal text-muted-foreground">{byMaterial.size}</span>
            </h3>
            <ul className="gap-2 lg:columns-2 [&>li]:mb-2 [&>li]:break-inside-avoid">
              {[...byMaterial.values()].map((rows) => (
                <MaterialCard key={rows[0].material_id} rows={rows} siteNames={siteNames} flowOf={flowOf} canOrder={canOrder} canMove={canMove}
                  periodDays={periodDays} openedKey={openedKey} onOpen={onOpen} onMove={onMove} onOrder={onOrder} />
              ))}
            </ul>
          </section>
        )
      })}
    </div>
  )
}

function MaterialCard({ rows, siteNames, flowOf, canOrder, canMove, periodDays, openedKey, onOpen, onMove, onOrder }: {
  rows: StockSummaryRow[]
  siteNames: SiteNames
  flowOf: (r: StockSummaryRow) => StockFlow
  canOrder: boolean
  canMove: boolean
  periodDays: number
  openedKey: string
  onOpen: (key: string) => void
  onMove: (p: TransferPrefill) => void
  onOrder: (p: OrderPrefill) => void
}) {
  const first = rows[0]
  const total = rows.reduce((n, r) => n + Number(r.closing), 0)
  const top = Math.max(1, ...rows.map((r) => Number(r.closing)))
  const coming = rows.reduce((n, r) => n + Number(r.on_order ?? 0), 0)
  const asked = rows.reduce((n, r) => n + flowOf(r).asked, 0)
  const worst = rows.some((r) => stockTone(r) === 'bad') ? 'bad' : rows.some((r) => stockTone(r) === 'attention') ? 'attention' : 'good'
  // Spare: a site that is fine and holds more than the low site needs for a fortnight.
  const spareFor = (low: StockSummaryRow) => rows
    .filter((r) => r !== low && !isLow(r) && stockTone(r) === 'good' && Number(r.closing) > 0)
    .sort((a, b) => Number(b.closing) - Number(a.closing))[0]
  const siteName = (r: StockSummaryRow) => siteNames.get(r.site_id ?? '')?.name ?? 'Site'
  return (
    <li className={cn('relative flex w-full flex-col gap-2 overflow-hidden rounded-xl border bg-card p-3 pl-4 shadow-xs before:absolute before:inset-y-0 before:left-0 before:w-1', EDGE[worst])}>
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="font-semibold">{first.material_name}</span>
        <span className="text-xs text-muted-foreground">{first.category?.split(' › ')[1] ?? ''}</span>
        <span className="ml-auto text-lg font-semibold tabular-nums">{qty(String(total))} <span className="text-sm font-normal text-muted-foreground">{first.unit}</span></span>
      </div>
      <ul className="flex flex-col gap-1.5">
        {rows.map((r) => {
          const key = `${r.site_id}:${r.material_id}`
          const tone = stockTone(r)
          const low = isLow(r)
          const spare = low && canMove ? spareFor(r) : undefined
          const orderQty = low && canOrder ? orderQuantity(r, periodDays) : ''
          return (
            <li key={key} className={cn('grid grid-cols-[minmax(0,7rem)_minmax(0,1fr)_auto] items-center gap-x-2 gap-y-1 rounded-md px-1 py-0.5 text-sm', openedKey === key && 'bg-yellow-50 dark:bg-yellow-950/40')}>
              <button type="button" onClick={() => onOpen(key)} className="truncate text-left font-medium hover:underline" title={siteNames.get(r.site_id ?? '')?.project}>{siteName(r)}</button>
              <button type="button" onClick={() => onOpen(key)} className="flex min-w-0 items-center gap-2" aria-label={`${siteName(r)}: ${qty(r.closing)} ${r.unit}`}>
                <span className="block h-2 flex-1 overflow-hidden rounded-full bg-muted">
                  <span className={cn('block h-full rounded-full', TONE[tone].dot)} style={{ width: `${Math.max(2, (Math.max(0, Number(r.closing)) / top) * 100)}%` }} />
                </span>
                <span className={cn('w-16 shrink-0 text-right text-xs font-semibold tabular-nums', tone === 'bad' && 'text-destructive')}>{qty(r.closing)}</span>
              </button>
              <span className="flex items-center justify-end gap-1"><DaysChip row={r} /></span>
              {(spare || orderQty || Number(r.on_order) > 0 || flowOf(r).asked > 0) && (
                <span className="col-span-3 flex flex-wrap items-center gap-1.5 pl-[7.5rem] max-sm:pl-0">
                  {Number(r.on_order) > 0 && <Pill tone="info" size="xs" icon={Truck}>+{qty(r.on_order ?? '0')} coming</Pill>}
                  {flowOf(r).asked > 0 && <Pill tone="muted" size="xs" icon={ClipboardList}>{qty(String(flowOf(r).asked))} asked</Pill>}
                  {spare && (
                    <Button size="sm" variant="outline" className="h-7 gap-1 px-2 text-xs" title={`${qty(spare.closing)} ${r.unit} at ${siteName(spare)}`}
                      onClick={() => r.site_id && spare.site_id && onMove({ from_project_id: spare.project_id, from_site_id: spare.site_id, to_project_id: r.project_id, to_site_id: r.site_id, material_id: r.material_id })}>
                      <ArrowLeftRight className="size-3.5" />Move from {siteName(spare)}
                    </Button>
                  )}
                  {orderQty && Number(r.on_order ?? 0) <= 0 && (
                    <Button size="sm" variant="outline" className="h-7 gap-1 px-2 text-xs"
                      onClick={() => r.site_id && onOrder({ project_id: r.project_id, site_id: r.site_id, site_name: siteName(r), lines: [{ material_id: r.material_id, quantity: orderQty }] })}>
                      <ShoppingCart className="size-3.5" />Order {qty(orderQty)}
                    </Button>
                  )}
                </span>
              )}
            </li>
          )
        })}
      </ul>
      {(coming > 0 || asked > 0) && rows.length > 1 && (
        <span className="flex gap-1.5 border-t pt-2 text-xs text-muted-foreground">
          {[coming > 0 ? `+${qty(String(coming))} coming in all` : '', asked > 0 ? `${qty(String(asked))} asked in all` : ''].filter(Boolean).join(' · ')}
        </span>
      )}
    </li>
  )
}
