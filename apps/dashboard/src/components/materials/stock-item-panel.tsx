import { Link } from 'react-router-dom'
import { ClipboardList, PackagePlus, ShoppingCart, Truck, Warehouse } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { SheetTitle } from '@/components/ui/sheet'
import { CategoryTile, StatusChip, UrgencyChip } from '@/components/requests/parts'
import { ORDER_LOOK, dueWords } from '@/lib/orders'
import { ago } from '@/lib/requests'
import { lasts, type StockFlow } from '@/lib/stock-flow'
import { formatMoney, type StockSummaryRow } from '@/lib/materials'
import { qty } from '@/lib/site-day'
import { cn } from '@/lib/utils'
import { StockBook } from './material-ledger-sheet'

// WEB-77: Materials > Stock, one item at one site -- what is here, what is coming on orders, what the site has asked
// for, and the three things to do about it (ask, order, record what came). The Requests / Purchase orders panels'
// look (category tile, three boxes, chips), so the three pages read as one flow.

export function StockItemPanel({
  row,
  siteName,
  projectName,
  flow,
  periodDays,
  money,
  canAsk,
  canOrder,
  canRecord,
  onAsk,
  onOrder,
  onRecord,
}: {
  row: StockSummaryRow
  siteName?: string
  projectName?: string
  flow: StockFlow
  periodDays: number
  money: boolean
  canAsk: boolean
  canOrder: boolean
  canRecord: boolean
  onAsk: () => void
  onOrder: () => void
  onRecord: () => void
}) {
  const closing = Number(row.closing)
  const coming = Number(row.on_order ?? 0)
  const perDay = periodDays > 0 ? Number(row.used) / periodDays : 0
  const out = closing <= 0
  return (
    <div className="flex flex-col">
      <div className={cn('flex flex-col gap-3 border-b p-4 sm:p-5', row.running_low && 'bg-draft-soft/40')}>
        <div className="flex items-start gap-3">
          <CategoryTile mainCategory={row.main_category} size="lg" />
          <div className="min-w-0 flex-1">
            <SheetTitle className="text-lg leading-tight font-semibold">{row.material_name}</SheetTitle>
            <p className="truncate text-sm text-muted-foreground">{[row.category ?? 'No category', siteName, projectName].filter(Boolean).join(' · ')}</p>
          </div>
        </div>
        <div className="flex items-end justify-between gap-3">
          <p className={cn('text-3xl font-semibold tabular-nums', closing < 0 && 'text-destructive')}>
            {qty(row.closing)} <span className="text-base font-medium text-muted-foreground">{row.unit} here</span>
          </p>
          {row.running_low ? (
            <span className="rounded-full bg-draft-soft px-2.5 py-1 text-xs font-semibold text-draft">{out ? 'Out' : `Lasts ${lasts(row.days_left ?? 0)}`}</span>
          ) : (
            row.days_left !== null && <span className="text-sm text-muted-foreground">Lasts {lasts(row.days_left)}</span>
          )}
        </div>
        <div className="grid grid-cols-3 gap-2">
          <Box icon={Warehouse} label="At site" value={`${qty(row.closing)} ${row.unit}`} tone="bg-green-100 text-green-950 dark:bg-green-950 dark:text-green-100" />
          <Box icon={Truck} label="Coming" value={`${qty(String(coming))} ${row.unit}`} tone="bg-blue-100 text-blue-950 dark:bg-blue-950 dark:text-blue-100" />
          <Box icon={ClipboardList} label="Asked for" value={`${qty(String(flow.asked))} ${row.unit}`} tone={flow.asked > 0 ? 'bg-yellow-300 text-yellow-950 dark:bg-yellow-700 dark:text-yellow-50' : 'bg-muted text-foreground/80'} />
        </div>
        <p className="text-xs text-muted-foreground">
          {[`Before the period ${qty(row.opening)}`, `+${qty(row.received)} came`, `−${qty(row.used)} used`, perDay > 0 ? `about ${qty(String(Math.round(perDay * 10) / 10))} ${row.unit} a day` : null]
            .filter(Boolean)
            .join(' · ')}
        </p>
        {(canAsk || canOrder || canRecord) && (
          <div className="flex flex-wrap gap-2">
            {canOrder && (
              <Button className="h-10 flex-1 gap-2 font-semibold" onClick={onOrder}>
                <ShoppingCart className="size-4" /> Create order
              </Button>
            )}
            {canAsk && (
              <Button variant={canOrder ? 'outline' : 'default'} className="h-10 flex-1 gap-2 font-semibold" onClick={onAsk}>
                <ClipboardList className="size-4" /> Request more
              </Button>
            )}
            {canRecord && (
              <Button variant="outline" className="h-10 flex-1 gap-2" onClick={onRecord}>
                <PackagePlus className="size-4" /> Material came
              </Button>
            )}
          </div>
        )}
      </div>

      <Section title="Coming on orders" count={flow.orders.length} empty="Nothing on order for this site.">
        {flow.orders.map(({ order, line }) => (
          <Link key={line.id} to={`/procurement/orders?id=${order.id}`} className="flex items-center gap-3 rounded-lg border px-3 py-2 transition hover:bg-muted/40">
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-semibold">
                {order.ref} · {order.vendor_name}
              </span>
              <span className="block truncate text-xs text-muted-foreground">
                {qty(line.received)} of {qty(line.quantity)} {line.unit} came · {dueWords(order)}
              </span>
            </span>
            <span className="flex shrink-0 flex-col items-end gap-1">
              <span className="text-sm font-semibold tabular-nums text-info">+{qty(line.pending)}</span>
              <span className={cn('inline-flex items-center gap-1 rounded-full px-1.5 text-[11px] font-semibold', ORDER_LOOK[order.status].chip)}>
                <span className={cn('size-1.5 rounded-full', ORDER_LOOK[order.status].dot)} />
                {ORDER_LOOK[order.status].label}
              </span>
            </span>
          </Link>
        ))}
      </Section>

      <Section title="Asked for, waiting" count={flow.requests.length} empty="No request waiting for this item here.">
        {flow.requests.map(({ request, line }) => (
          <Link key={line.id} to={`/materials/requests?id=${request.id}`} className="flex items-center gap-3 rounded-lg border px-3 py-2 transition hover:bg-muted/40">
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-semibold">
                {request.ref} · {qty(line.quantity)} {line.unit}
              </span>
              <span className="block truncate text-xs text-muted-foreground">
                {(request.requested_by_name ?? 'Someone').split(' ')[0]} · {ago(request.created_at)}
                {request.purpose ? ` · ${request.purpose}` : ''}
              </span>
            </span>
            <span className="flex shrink-0 flex-col items-end gap-1">
              {request.urgency !== 'closed' && <UrgencyChip request={request} />}
              <StatusChip status={request.status} />
            </span>
          </Link>
        ))}
      </Section>

      {money && row.last_rate && (
        <Section title="Last rate">
          <p className="text-sm">
            <span className="font-semibold tabular-nums">{formatMoney(row.last_rate)}</span> per {row.unit}
            {Number(row.spend) > 0 && <span className="text-muted-foreground"> · {formatMoney(row.spend)} spent in the period</span>}
          </p>
        </Section>
      )}

      <Section title="Stock book, newest first">
        <StockBook siteId={row.site_id} materialId={row.material_id} />
      </Section>
    </div>
  )
}

function Box({ icon: Icon, label, value, tone }: { icon: LucideIcon; label: string; value: string; tone: string }) {
  return (
    <div className={cn('flex min-w-0 flex-col gap-0.5 rounded-lg px-2.5 py-2', tone)}>
      <span className="inline-flex items-center gap-1 text-[11px] font-semibold">
        <Icon className="size-3" /> {label}
      </span>
      <span className="truncate text-base font-semibold tabular-nums">{value}</span>
    </div>
  )
}

function Section({ title, count, empty, children }: { title: string; count?: number; empty?: string; children: React.ReactNode }) {
  const none = count === 0
  return (
    <section className="flex flex-col gap-2 border-b px-4 py-3 sm:px-5">
      <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
        {title}
        {!!count && <span className="ml-1.5 rounded-full bg-muted px-1.5 text-foreground">{count}</span>}
      </h3>
      {none ? <p className="text-sm text-muted-foreground">{empty}</p> : children}
    </section>
  )
}
