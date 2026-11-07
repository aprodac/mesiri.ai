import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ChevronRight, Tags, Trophy } from 'lucide-react'
import { useAuth } from '@/lib/AuthContext'
import { MONEY_ROLES } from '@/lib/module-map'
import { fetchRates, rate, ratePeriodRange, shortDate } from '@/lib/rates'
import { TrendChip } from './parts'

// PRC-16: a supplier's last rates on its page -- what it charged for each item in the last 12 months, and whether
// another supplier was cheaper. Each row opens the item on the Rates page.

export function VendorRates({ vendorId, onNavigate }: { vendorId: string; onNavigate?: () => void }) {
  const { me } = useAuth()
  const allowed = (MONEY_ROLES as readonly string[]).includes((me?.role || '').toUpperCase())
  const range = ratePeriodRange('365d', '', '')
  const { data, isLoading } = useQuery({
    queryKey: ['procurement', 'rates', 'vendor', vendorId, range],
    queryFn: () => fetchRates({ ...range, vendor_id: vendorId }),
    enabled: allowed,
    retry: false,
  })
  if (!allowed) return null
  const items = data?.items ?? []
  return (
    <section className="flex max-h-72 flex-col gap-2 overflow-y-auto border-b px-4 py-3">
      <h3 className="flex items-center gap-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
        <Tags className="size-3.5" /> Last rates, 12 months
        {items.length > 0 && <span className="rounded-full bg-muted px-1.5 text-foreground">{items.length}</span>}
      </h3>
      {isLoading ? (
        <p className="text-xs text-muted-foreground">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-xs text-muted-foreground">No delivery from this supplier with a rate yet.</p>
      ) : (
        <ul className="flex flex-col divide-y rounded-lg border">
          {items.map((i) => {
            const mine = i.vendors.find((v) => v.vendor_id === vendorId)!
            const cheaper = i.best && !mine.best ? i.best : null
            return (
              <li key={i.material_id}>
                <Link to={`/procurement/rates?item=${i.material_id}&period=365d`} onClick={onNavigate} className="flex items-center gap-2 px-3 py-2 text-xs transition hover:bg-muted/40">
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate text-sm font-semibold">{i.material_name}</span>
                    <span className="truncate text-muted-foreground">
                      {mine.purchases}× · last {shortDate(mine.last_date)}
                      {cheaper ? (
                        <span className="font-medium text-red-700 dark:text-red-400"> · {cheaper.vendor_name} cheaper at {rate(cheaper.avg_rate)}</span>
                      ) : (
                        mine.best && (
                          <span className="inline-flex items-center gap-0.5 font-medium text-green-700 dark:text-green-400">
                            {' '}· <Trophy className="size-3" /> cheapest
                          </span>
                        )
                      )}
                    </span>
                  </span>
                  {i.last.vendor_key === mine.key && <TrendChip item={i} />}
                  <span className="text-right">
                    <span className="block text-sm font-semibold tabular-nums">{rate(mine.last_rate)}</span>
                    <span className="block text-muted-foreground">/{i.unit}</span>
                  </span>
                  <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
