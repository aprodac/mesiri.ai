import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, MessageCircle, Printer } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { fetchBranding } from '@/lib/api'
import { fetchOrder, orderMessage, rupees, whatsappUrl } from '@/lib/orders'

// PRC-26: the purchase order as a document for the supplier, on the company's letterhead. Print it or save it as a
// PDF from the browser; or send it from your own WhatsApp. Mesiri never claims it was sent: the person sends it.

function day(d: string): string {
  return new Date(`${d}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
}

function n(v: string): string {
  return Number(v).toLocaleString('en-IN', { maximumFractionDigits: 3 })
}

export default function PurchaseOrderDocumentPage() {
  const { id = '' } = useParams()
  const order = useQuery({ queryKey: ['procurement', 'orders', 'one', id], queryFn: () => fetchOrder(id) })
  const brand = useQuery({ queryKey: ['company', 'branding'], queryFn: fetchBranding, retry: false, staleTime: 300_000 })
  const o = order.data
  const b = brand.data
  if (order.isError) return <p className="p-8 text-sm text-muted-foreground">This order could not be opened.</p>
  if (!o) return <p className="p-8 text-sm text-muted-foreground">Loading…</p>
  const money = o.value !== null
  const colour = b?.brand_color || '#1f2937'
  const company = b?.letterhead_name || b?.company_name || ''

  return (
    <div className="min-h-screen bg-muted/40 py-6 print:bg-white print:py-0">
      <style>{'@page { size: A4; margin: 14mm }'}</style>
      <div className="mx-auto mb-4 flex max-w-[210mm] flex-wrap items-center justify-between gap-2 px-4 print:hidden">
        <Button asChild variant="ghost" className="gap-2"><Link to={`/procurement/orders?id=${o.id}`}><ArrowLeft className="size-4" /> {o.ref}</Link></Button>
        <span className="flex flex-wrap gap-2">
          <Button variant="outline" className="gap-2" onClick={() => window.print()}><Printer className="size-4" /> Print / save PDF</Button>
          <Button asChild className="gap-2 font-semibold">
            <a href={whatsappUrl(o.vendor_phone, orderMessage(o, company))} target="_blank" rel="noreferrer">
              <MessageCircle className="size-4" /> Send on WhatsApp
            </a>
          </Button>
        </span>
        <p className="w-full text-xs text-muted-foreground">
          {o.vendor_phone ? `Opens your WhatsApp to ${o.vendor_name} (${o.vendor_phone}) with the order written in; you send it.` : `No phone saved for ${o.vendor_name}: WhatsApp asks whom to send it to. Add their number in Suppliers.`}
        </p>
      </div>

      <article className="mx-auto max-w-[210mm] bg-white px-10 py-9 text-[13px] text-neutral-900 shadow-sm print:max-w-none print:px-0 print:py-0 print:shadow-none">
        <header className="flex items-start justify-between gap-6 border-b-4 pb-4" style={{ borderColor: colour }}>
          <div className="flex items-center gap-3">
            {b?.logo_url && <img src={b.logo_url} alt="" className="h-14 w-auto object-contain" />}
            <div>
              <div className="text-xl font-bold" style={{ color: colour }}>{company}</div>
              {b?.address && <div className="max-w-[90mm] whitespace-pre-line text-neutral-600">{b.address}</div>}
              <div className="text-neutral-600">{[b?.phone, b?.email].filter(Boolean).join(' · ')}</div>
              {b?.gstin && <div className="text-neutral-600">GSTIN {b.gstin}</div>}
            </div>
          </div>
          <div className="text-right">
            <div className="text-lg font-bold tracking-wide">PURCHASE ORDER</div>
            <div className="font-semibold tabular-nums">{o.ref}</div>
            {o.their_ref && <div className="text-neutral-600">Ref {o.their_ref}</div>}
            <div className="text-neutral-600">{day(o.created_at.slice(0, 10))}</div>
          </div>
        </header>

        <section className="mt-5 grid grid-cols-2 gap-6">
          <div>
            <div className="text-[11px] font-semibold tracking-wide text-neutral-500 uppercase">Supplier</div>
            <div className="font-semibold">{o.vendor_name}</div>
            {o.vendor_address && <div className="whitespace-pre-line text-neutral-600">{o.vendor_address}</div>}
            {o.vendor_phone && <div className="text-neutral-600">{o.vendor_phone}</div>}
            {o.vendor_gstin && <div className="text-neutral-600">GSTIN {o.vendor_gstin}</div>}
          </div>
          <div>
            <div className="text-[11px] font-semibold tracking-wide text-neutral-500 uppercase">Deliver to</div>
            <div className="font-semibold">{o.project_name} › {o.site_name}</div>
            {o.project_location && <div className="text-neutral-600">{o.project_location}</div>}
            {o.expected_date && <div className="mt-1">Needed by <strong>{day(o.expected_date)}</strong></div>}
          </div>
        </section>

        <table className="mt-6 w-full border-collapse">
          <thead>
            <tr className="border-b-2 border-neutral-800 text-left text-[11px] tracking-wide text-neutral-600 uppercase">
              <th className="py-1.5 pr-2 font-semibold">#</th>
              <th className="py-1.5 pr-2 font-semibold">Item</th>
              <th className="py-1.5 pr-2 text-right font-semibold">Quantity</th>
              {money && <th className="py-1.5 pr-2 text-right font-semibold">Rate</th>}
              {money && <th className="py-1.5 text-right font-semibold">Amount</th>}
            </tr>
          </thead>
          <tbody>
            {o.lines.map((l, i) => (
              <tr key={l.id} className="border-b border-neutral-200 align-top">
                <td className="py-2 pr-2 tabular-nums text-neutral-500">{i + 1}</td>
                <td className="py-2 pr-2 font-medium">{l.material}</td>
                <td className="py-2 pr-2 text-right tabular-nums">{n(l.quantity)} {l.unit}</td>
                {money && <td className="py-2 pr-2 text-right tabular-nums">{l.rate ? `₹${n(l.rate)} / ${l.unit}` : '—'}</td>}
                {money && <td className="py-2 text-right tabular-nums">{l.amount ? rupees(l.amount) : '—'}</td>}
              </tr>
            ))}
          </tbody>
          {money && o.value && (
            <tfoot>
              <tr>
                <td colSpan={4} className="pt-3 pr-2 text-right font-semibold">Total{o.value_complete ? '' : ' (items with a rate)'}</td>
                <td className="pt-3 text-right text-base font-bold tabular-nums">{rupees(o.value)}</td>
              </tr>
            </tfoot>
          )}
        </table>

        {o.notes && (
          <section className="mt-6">
            <div className="text-[11px] font-semibold tracking-wide text-neutral-500 uppercase">Notes</div>
            <div className="whitespace-pre-line">{o.notes}</div>
          </section>
        )}

        <footer className="mt-14 flex items-end justify-between gap-6">
          <div className="text-neutral-600">Ordered by {o.created_by_name ?? '—'}</div>
          <div className="text-center">
            <div className="mb-1 h-10 w-48 border-b border-neutral-400" />
            <div className="font-semibold">{b?.signatory_name ?? 'Authorised signatory'}</div>
            {b?.signatory_designation && <div className="text-neutral-600">{b.signatory_designation}</div>}
          </div>
        </footer>
      </article>
    </div>
  )
}
