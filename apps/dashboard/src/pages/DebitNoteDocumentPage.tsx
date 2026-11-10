import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, MessageCircle, Printer } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Letterhead, Signatory } from '@/components/documents/letterhead'
import { fetchBranding } from '@/lib/api'
import { rupees, whatsappUrl } from '@/lib/orders'
import { debitNoteMessage, fetchReturn } from '@/lib/returns'

// PRC-46: the debit note for material sent back, on the company's letterhead (as the purchase order, PRC-26). Print it
// or save it as a PDF from the browser; or send it from your own WhatsApp. Mesiri never claims it was sent.

function day(d: string): string {
  return new Date(`${d}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
}

function n(v: string): string {
  return Number(v).toLocaleString('en-IN', { maximumFractionDigits: 3 })
}

export default function DebitNoteDocumentPage() {
  const { id = '' } = useParams()
  const ret = useQuery({ queryKey: ['procurement', 'returns', 'one', id], queryFn: () => fetchReturn(id) })
  const brand = useQuery({ queryKey: ['company', 'branding'], queryFn: fetchBranding, retry: false, staleTime: 300_000 })
  const r = ret.data
  const b = brand.data
  if (ret.isError) return <p className="p-8 text-sm text-muted-foreground">This debit note could not be opened.</p>
  if (!r) return <p className="p-8 text-sm text-muted-foreground">Loading…</p>
  const money = r.total !== undefined
  const company = b?.letterhead_name || b?.company_name || ''

  return (
    <div className="min-h-screen bg-muted/40 py-6 print:bg-white print:py-0">
      <style>{'@page { size: A4; margin: 14mm }'}</style>
      <div className="mx-auto mb-4 flex max-w-[210mm] flex-wrap items-center justify-between gap-2 px-4 print:hidden">
        <Button asChild variant="ghost" className="gap-2"><Link to={`/procurement/returns?id=${r.id}`}><ArrowLeft className="size-4" /> {r.ref}</Link></Button>
        <span className="flex flex-wrap gap-2">
          <Button variant="outline" className="gap-2" onClick={() => window.print()}><Printer className="size-4" /> Print / save PDF</Button>
          <Button asChild className="gap-2 font-semibold">
            <a href={whatsappUrl(r.vendor_phone, debitNoteMessage(r, company))} target="_blank" rel="noreferrer">
              <MessageCircle className="size-4" /> Send on WhatsApp
            </a>
          </Button>
        </span>
        <p className="w-full text-xs text-muted-foreground">
          {r.vendor_phone ? `Opens your WhatsApp to ${r.vendor_name} (${r.vendor_phone}) with the debit note written in; you send it.` : `No phone saved for ${r.vendor_name}: WhatsApp asks whom to send it to. Add their number in Suppliers.`}
        </p>
      </div>

      <article className="mx-auto max-w-[210mm] bg-white px-10 py-9 text-[13px] text-neutral-900 shadow-sm print:max-w-none print:px-0 print:py-0 print:shadow-none">
        <Letterhead brand={b} title="DEBIT NOTE">
          <div className="font-semibold tabular-nums">{r.ref}</div>
          <div className="text-neutral-600">{day(r.returned_on)}</div>
          {r.status === 'cancelled' && <div className="font-bold text-red-700">CANCELLED</div>}
        </Letterhead>

        <section className="mt-5 grid grid-cols-2 gap-6">
          <div>
            <div className="text-[11px] font-semibold tracking-wide text-neutral-500 uppercase">To</div>
            <div className="font-semibold">{r.vendor_name}</div>
            {r.vendor_address && <div className="whitespace-pre-line text-neutral-600">{r.vendor_address}</div>}
            {r.vendor_phone && <div className="text-neutral-600">{r.vendor_phone}</div>}
            {r.vendor_gstin && <div className="text-neutral-600">GSTIN {r.vendor_gstin}</div>}
          </div>
          <div>
            <div className="text-[11px] font-semibold tracking-wide text-neutral-500 uppercase">Returned from</div>
            <div className="font-semibold">{r.project_name} › {r.site_name}</div>
            {(r.grn_ref || r.order_ref) && <div className="text-neutral-600">Against {[r.order_ref, r.grn_ref].filter(Boolean).join(', ')}</div>}
          </div>
        </section>

        <p className="mt-5">We have debited your account for the material below, returned to you. Please send a replacement or reduce the amount from your bill.</p>

        <table className="mt-4 w-full border-collapse">
          <thead>
            <tr className="border-b-2 border-neutral-800 text-left text-[11px] tracking-wide text-neutral-600 uppercase">
              <th className="py-1.5 pr-2 font-semibold">#</th>
              <th className="py-1.5 pr-2 font-semibold">Item</th>
              <th className="py-1.5 pr-2 font-semibold">Reason</th>
              <th className="py-1.5 pr-2 text-right font-semibold">Quantity</th>
              {money && <th className="py-1.5 pr-2 text-right font-semibold">Rate</th>}
              {money && <th className="py-1.5 text-right font-semibold">Amount</th>}
            </tr>
          </thead>
          <tbody>
            {r.lines.map((l, i) => (
              <tr key={l.id} className="border-b border-neutral-200 align-top">
                <td className="py-2 pr-2 tabular-nums text-neutral-500">{i + 1}</td>
                <td className="py-2 pr-2 font-medium">{l.material}</td>
                <td className="py-2 pr-2">{l.reason_label}</td>
                <td className="py-2 pr-2 text-right tabular-nums">{n(l.quantity)} {l.unit}</td>
                {money && <td className="py-2 pr-2 text-right tabular-nums">{l.rate ? `₹${n(l.rate)} / ${l.unit}${l.gst_percent ? ` + ${n(l.gst_percent)}%` : ''}` : '—'}</td>}
                {money && <td className="py-2 text-right tabular-nums">{l.amount ? rupees(l.amount) : '—'}</td>}
              </tr>
            ))}
          </tbody>
          {money && (
            <tfoot>
              {Number(r.gst) > 0 && (
                <>
                  <tr><td colSpan={5} className="pt-3 pr-2 text-right">Before GST</td><td className="pt-3 text-right tabular-nums">{rupees(r.before_gst)}</td></tr>
                  <tr><td colSpan={5} className="pr-2 text-right">GST</td><td className="text-right tabular-nums">{rupees(r.gst)}</td></tr>
                </>
              )}
              <tr>
                <td colSpan={5} className="pt-2 pr-2 text-right font-semibold">Total debited</td>
                <td className="pt-2 text-right text-base font-bold tabular-nums">{rupees(r.total)}</td>
              </tr>
            </tfoot>
          )}
        </table>

        {r.notes && (
          <section className="mt-6">
            <div className="text-[11px] font-semibold tracking-wide text-neutral-500 uppercase">Notes</div>
            <div className="whitespace-pre-line">{r.notes}</div>
          </section>
        )}

        <Signatory brand={b} left={<>Prepared by {r.created_by_name ?? '—'}</>} />
      </article>
    </div>
  )
}
