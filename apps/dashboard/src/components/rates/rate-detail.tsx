import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { BadgePercent, FileText, Info, PackageCheck, ShoppingCart, Trophy, TriangleAlert, Truck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { SheetTitle } from '@/components/ui/sheet'
import { CategoryTile } from '@/components/requests/parts'
import { qty } from '@/lib/site-day'
import { rupees } from '@/lib/orders'
import { cn } from '@/lib/utils'
import { fetchRatePurchases, rate, shortDate, type RateFilters, type RateItem, type RatePurchase, vendorColour } from '@/lib/rates'
import { RateChart, TrendChip } from './parts'
import { VendorLink } from '@/components/vendors/vendor-parts'

// PRC-14: one item on the Rates page -- the last rate and what it moved from, the chart, each supplier against the
// cheapest, what was paid above it, and every purchase (bill, order or plain delivery), newest first.

const SOURCE: Record<RatePurchase['source'], { label: string; icon: typeof FileText; tone: string }> = {
  bill: { label: 'Bill', icon: FileText, tone: 'bg-violet-100 text-violet-900 dark:bg-violet-950 dark:text-violet-100' },
  order: { label: 'Order', icon: ShoppingCart, tone: 'bg-blue-100 text-blue-900 dark:bg-blue-950 dark:text-blue-100' },
  delivery: { label: 'Delivery', icon: Truck, tone: 'bg-muted text-foreground/80' },
}

export function RateDetail({
  item,
  filters,
  inSheet,
  canOrder,
  onOrder,
}: {
  item: RateItem
  filters: RateFilters
  inSheet?: boolean
  canOrder: boolean
  /** Order this item from a supplier at its last rate, at the site of the latest purchase. */
  onOrder: (vendorName: string, lastRate: string, at: RatePurchase | undefined) => void
}) {
  const { data: purchases, isLoading } = useQuery({
    queryKey: ['procurement', 'rates', item.material_id, filters],
    queryFn: () => fetchRatePurchases(item.material_id, filters),
  })
  const best = item.vendors.find((v) => v.best)
  const lastIsBest = !!best && item.last.vendor_key === best.key
  const worst = item.vendors[item.vendors.length - 1]
  const lo = Number(item.vendors[0]?.avg_rate ?? 0)
  const hi = Number(worst?.avg_rate ?? 0)
  const Title = inSheet ? SheetTitle : 'h2'
  const differing = (purchases ?? []).filter((p) => p.differs_from_order)

  return (
    <div className="flex flex-col">
      <div className="flex flex-col gap-3 border-b p-4 sm:p-5">
        <div className="flex items-start gap-3">
          <CategoryTile mainCategory={item.main_category} size="lg" />
          <div className="min-w-0 flex-1">
            <Title className="text-lg leading-tight font-semibold">{item.material_name}</Title>
            <p className="truncate text-sm text-muted-foreground">{item.category ?? 'No category'}</p>
          </div>
        </div>
        <div className="flex flex-wrap items-end justify-between gap-2">
          <p className="text-3xl font-semibold tabular-nums">
            {rate(item.last.rate)} <span className="text-base font-medium text-muted-foreground">/ {item.unit}</span>
          </p>
          <TrendChip item={item} className="text-xs" />
        </div>
        <p className="text-sm text-muted-foreground">
          Last bought {shortDate(item.last.date)} from <span className="font-medium text-foreground">{item.last.vendor_name}</span>
          {item.last.site_name && <> for {item.last.site_name}</>}
          {item.previous && (
            <>
              {' '}· before that {rate(item.previous.rate)} ({item.previous.vendor_name}, {shortDate(item.previous.date)}
              {!item.previous.in_period && ', before this period'})
            </>
          )}
        </p>

        <div className="grid grid-cols-3 gap-2">
          <Stat label="Average" value={rate(item.avg_rate)} />
          <Stat label="Lowest" value={rate(item.min_rate)} tone="text-green-700 dark:text-green-400" />
          <Stat label="Highest" value={rate(item.max_rate)} tone="text-red-700 dark:text-red-400" />
          <Stat label="Bought" value={`${qty(item.quantity)} ${item.unit}`} />
          <Stat label="Purchases" value={String(item.purchases)} />
          <Stat label="Spent" value={rupees(Math.round(Number(item.spend)))} />
        </div>

        {best && Number(item.above_best) > 0 && (
          <div className="flex flex-wrap items-center gap-3 rounded-lg border border-green-300 bg-green-50 px-3 py-2.5 dark:border-green-900 dark:bg-green-950/50">
            <BadgePercent className="size-5 shrink-0 text-green-700 dark:text-green-400" />
            <p className="min-w-0 flex-1 text-sm">
              <span className="font-semibold">{best.name}</span> averaged <span className="font-semibold tabular-nums">{rate(best.avg_rate)}</span> / {item.unit}.
              At that rate this period's {qty(item.quantity)} {item.unit} would have cost{' '}
              <span className="font-semibold tabular-nums text-green-800 dark:text-green-300">{rate(Math.round(Number(item.above_best)))} less</span>.
            </p>
            {canOrder && !lastIsBest && (
              <Button size="sm" variant="outline" className="shrink-0 gap-1.5 bg-background" onClick={() => onOrder(best.name, best.last_rate, purchases?.[0])}>
                <ShoppingCart className="size-3.5" /> Order from {best.name.split(' ')[0]}
              </Button>
            )}
          </div>
        )}
      </div>

      <Section title="Rate over time">
        <RateChart item={item} />
      </Section>

      <Section title={item.vendors.length > 1 ? `Suppliers, cheapest first` : 'Supplier'} count={item.vendors.length}>
        <ul className="flex flex-col gap-2">
          {item.vendors.map((v) => {
            const over = best && !v.best ? Number(v.avg_rate) - Number(best.avg_rate) : 0
            const width = hi > lo ? 30 + ((Number(v.avg_rate) - lo) / (hi - lo)) * 70 : 100
            return (
              <li key={v.key} className={cn('flex flex-col gap-1.5 rounded-lg border px-3 py-2', v.best && 'border-green-400 bg-green-50/60 dark:border-green-900 dark:bg-green-950/30')}>
                <div className="flex items-center gap-2">
                  <span className="size-2.5 shrink-0 rounded-full" style={{ background: vendorColour(v.key) }} />
                  <span className="min-w-0 flex-1 truncate text-sm font-semibold"><VendorLink id={v.key.startsWith('name:') || v.key === 'unknown' ? null : v.key} name={v.name} tab="rates" /></span>
                  {v.best && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-green-600 px-1.5 py-0.5 text-[11px] font-semibold text-white">
                      <Trophy className="size-3" /> Cheapest
                    </span>
                  )}
                  <span className="text-sm font-semibold tabular-nums">{rate(v.avg_rate)}</span>
                </div>
                {item.vendors.length > 1 && (
                  <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                    <div className="h-full rounded-full" style={{ width: `${width}%`, background: vendorColour(v.key) }} />
                  </div>
                )}
                <div className="flex flex-wrap items-center justify-between gap-x-3 text-xs text-muted-foreground">
                  <span>
                    {v.purchases} {v.purchases === 1 ? 'purchase' : 'purchases'} · {qty(v.quantity)} {item.unit} · last {rate(v.last_rate)} on {shortDate(v.last_date)}
                  </span>
                  {over > 0 && (
                    <span className="font-semibold text-red-700 dark:text-red-400">
                      +{rate(Math.round(over * 100) / 100)} ({((over / Number(best!.avg_rate)) * 100).toLocaleString('en-IN', { maximumFractionDigits: 1 })}%) vs cheapest
                    </span>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      </Section>

      <Section title="Purchases, newest first" count={purchases?.length}>
        {differing.length > 0 && (
          <p className="flex items-center gap-2 rounded-lg bg-draft-soft px-3 py-2 text-xs font-medium text-draft">
            <TriangleAlert className="size-4 shrink-0" />
            {differing.length === 1 ? '1 delivery was' : `${differing.length} deliveries were`} charged a different rate from the order.
          </p>
        )}
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <ul className="divide-y overflow-hidden rounded-lg border">
            {(purchases ?? []).map((p) => {
              const look = SOURCE[p.source]
              return (
                <li key={p.id} className="flex flex-col gap-1 px-3 py-2 text-sm">
                  <div className="flex items-center gap-2">
                    <span className="w-14 shrink-0 text-xs text-muted-foreground tabular-nums">{shortDate(p.date)}</span>
                    <span className="size-2 shrink-0 rounded-full" style={{ background: vendorColour(p.vendor_key) }} />
                    <span className="min-w-0 flex-1 truncate font-medium">{p.vendor_name}</span>
                    <span className="font-semibold tabular-nums">{rate(p.rate)}</span>
                  </div>
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1 pl-16 text-xs text-muted-foreground">
                    <span className="tabular-nums">
                      {qty(p.quantity)} {p.unit} · {rate(Math.round(Number(p.amount)))}
                    </span>
                    {p.site_name && <span>· {p.site_name}</span>}
                    <span className={cn('inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-semibold', look.tone)}>
                      <look.icon className="size-3" />
                      {p.source === 'order' && p.order_id ? (
                        <Link to={`/procurement/orders?id=${p.order_id}`} className="hover:underline">
                          {p.order_ref}
                        </Link>
                      ) : p.source === 'bill' && p.invoice_number ? (
                        `Bill ${p.invoice_number}`
                      ) : (
                        look.label
                      )}
                    </span>
                    {p.differs_from_order && p.ordered_rate && (
                      <span className="inline-flex items-center gap-1 rounded-md bg-draft-soft px-1.5 py-0.5 font-semibold text-draft">
                        <TriangleAlert className="size-3" /> Order said {rate(p.ordered_rate)}
                      </span>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </Section>

      <p className="flex items-start gap-2 px-4 py-3 text-xs text-muted-foreground sm:px-5">
        <Info className="mt-0.5 size-3.5 shrink-0" />
        Rates are per {item.unit}, as recorded on each delivery: with or without GST, as it was entered. A rate said in another unit (a load, a bar) was
        converted when it was saved.
      </p>
      {canOrder && (
        <div className="border-t p-4 sm:px-5">
          <Button className="h-10 w-full gap-2 font-semibold" onClick={() => onOrder(item.last.vendor_name, item.last.rate, purchases?.[0])}>
            <PackageCheck className="size-4" /> Order again from {item.last.vendor_name} at {rate(item.last.rate)}
          </Button>
        </div>
      )}
    </div>
  )
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex min-w-0 flex-col rounded-lg bg-muted/60 px-2.5 py-2">
      <span className="text-[11px] font-medium text-muted-foreground">{label}</span>
      <span className={cn('truncate text-sm font-semibold tabular-nums', tone)}>{value}</span>
    </div>
  )
}

function Section({ title, count, children }: { title: string; count?: number; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2 border-b px-4 py-3 sm:px-5">
      <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
        {title}
        {!!count && <span className="ml-1.5 rounded-full bg-muted px-1.5 text-foreground">{count}</span>}
      </h3>
      {children}
    </section>
  )
}
