import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ListChecks } from 'lucide-react'
import { useAuth } from '@/lib/AuthContext'
import { MONEY_ROLES } from '@/lib/module-map'
import { fetchPriceList, gstWords, rate, shortDate, type PriceQuote } from '@/lib/rates'
import { cn } from '@/lib/utils'

// PRC-51: a supplier's price list on its page -- per item what it last quoted (from which RFQ, valid until when) and
// what we last paid it (from which order), both as a unit costs the company, the same number as the Rates page
// (D-CC8); the quote's own words ("said ₹472 incl. 28% GST") under it. Expired quotes are greyed. Backend: rates_router.supplier_price_list.

function Quote({ q, unit }: { q: PriceQuote; unit: string }) {
  return (
    <span className={cn('flex flex-col', !q.live && 'text-muted-foreground')}>
      <span className="text-sm font-semibold tabular-nums">
        {rate(q.rate)}<span className="text-xs font-normal text-muted-foreground"> /{unit}</span>
        {!q.live && <span className="ml-1.5 rounded bg-muted px-1.5 py-0.5 text-[10px] font-semibold tracking-wide uppercase">expired</span>}
      </span>
      <span className="text-xs text-muted-foreground">
        {q.gst_known && q.rate !== q.rate_entered && `said ${rate(q.rate_entered)}${gstWords(q)} · `}
        {q.valid_until ? `valid till ${shortDate(q.valid_until)}` : q.quoted_on ? `quoted ${shortDate(q.quoted_on)}` : ''}
        {' · '}<Link to={`/procurement/quotations?id=${q.rfq_id}&tab=all`} className="underline-offset-2 hover:underline">{q.rfq_ref}</Link>
        {q.brand && ` · ${q.brand}`}
      </span>
    </span>
  )
}

export function VendorPriceList({ vendorId }: { vendorId: string }) {
  const { me } = useAuth()
  const allowed = (MONEY_ROLES as readonly string[]).includes((me?.role || '').toUpperCase())
  const { data, isLoading } = useQuery({
    queryKey: ['procurement', 'price-list', vendorId],
    queryFn: () => fetchPriceList(vendorId),
    enabled: allowed,
    retry: false,
  })
  if (!allowed) return null
  const items = data?.items ?? []
  return (
    <section className="flex flex-col gap-2 border-b px-4 py-3">
      <h3 className="flex items-center gap-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
        <ListChecks className="size-3.5" /> Price list
        {items.length > 0 && <span className="rounded-full bg-muted px-1.5 text-foreground">{items.length}</span>}
      </h3>
      {isLoading ? (
        <p className="text-xs text-muted-foreground">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-xs text-muted-foreground">No quote or priced delivery from this supplier yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full min-w-[34rem] text-left">
            <thead className="bg-muted/40 text-[11px] tracking-wide text-muted-foreground uppercase">
              <tr><th className="px-3 py-2 font-semibold">Item</th><th className="px-3 py-2 font-semibold">Last quoted</th><th className="px-3 py-2 font-semibold">Last paid</th></tr>
            </thead>
            <tbody className="divide-y">
              {items.map((i) => (
                <tr key={i.material_id} className="align-top">
                  <td className="px-3 py-2 text-sm font-semibold">{i.material_name}</td>
                  <td className="px-3 py-2">{i.quoted ? <Quote q={i.quoted} unit={i.unit} /> : <span className="text-xs text-muted-foreground">No quote</span>}</td>
                  <td className="px-3 py-2">
                    {i.paid ? (
                      <span className="flex flex-col">
                        <span className="text-sm font-semibold tabular-nums">{rate(i.paid.rate)}<span className="text-xs font-normal text-muted-foreground"> /{i.unit}</span></span>
                        <span className="text-xs text-muted-foreground">
                          {shortDate(i.paid.date)}
                          {i.paid.order_id && <>{' · '}<Link to={`/procurement/orders?id=${i.paid.order_id}&tab=all`} className="underline-offset-2 hover:underline">{i.paid.order_ref}</Link></>}
                        </span>
                      </span>
                    ) : <span className="text-xs text-muted-foreground">Not bought yet</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
