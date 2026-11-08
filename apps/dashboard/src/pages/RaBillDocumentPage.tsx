import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Printer } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { fetchBranding } from '@/lib/api'
import { billDay, fetchRaBill, qty, rupees } from '@/lib/billing'

// NXT-02: an RA bill as the document the client receives, on the company's letterhead (the purchase order's layout,
// PRC-26). Print it or save it as a PDF from the browser. A draft prints with "DRAFT" so it is never sent by mistake.

export default function RaBillDocumentPage() {
  const { id = '' } = useParams()
  const bill = useQuery({ queryKey: ['ra-bill', id], queryFn: () => fetchRaBill(id) })
  const brand = useQuery({ queryKey: ['company', 'branding'], queryFn: fetchBranding, retry: false, staleTime: 300_000 })
  const b = bill.data
  const lh = brand.data
  if (bill.isError) return <p className="p-8 text-sm text-muted-foreground">This bill could not be opened.</p>
  if (!b) return <p className="p-8 text-sm text-muted-foreground">Loading…</p>
  const colour = lh?.brand_color || '#1f2937'
  const company = lh?.letterhead_name || lh?.company_name || ''
  const draft = b.status === 'draft'
  const money: [string, string | null, string][] = [
    ['Value of work this bill', b.gross, ''],
    [`Add: GST @ ${Number(b.gst_pct)}%`, b.gst, '+'],
    [`Less: retention @ ${Number(b.retention_pct)}%`, b.retention, '−'],
    [`Less: mobilisation advance recovery @ ${Number(b.advance_recovery_pct)}%`, b.advance_recovery, '−'],
    [`Less: TDS @ ${Number(b.tds_pct)}%`, b.tds, '−'],
  ]

  return (
    <div className="min-h-screen bg-muted/40 py-6 print:bg-white print:py-0">
      <style>{'@page { size: A4; margin: 14mm }'}</style>
      <div className="mx-auto mb-4 flex max-w-[210mm] flex-wrap items-center justify-between gap-2 px-4 print:hidden">
        <Button asChild variant="ghost" className="gap-2"><Link to={`/billing/ra-bills?project=${b.project_id}&bill=${b.id}`}><ArrowLeft className="size-4" /> {b.ref}</Link></Button>
        <Button variant="outline" className="gap-2" onClick={() => window.print()}><Printer className="size-4" /> Print / save PDF</Button>
        {draft && <p className="w-full text-xs text-muted-foreground">This is a draft: it prints marked DRAFT. Submit it to send the final bill.</p>}
      </div>

      <article className="relative mx-auto max-w-[210mm] bg-white px-10 py-9 text-[12.5px] text-neutral-900 shadow-sm print:max-w-none print:px-0 print:py-0 print:shadow-none">
        {draft && <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-[110px] font-black tracking-widest text-neutral-200/70 -rotate-12 select-none">DRAFT</div>}
        <header className="relative flex items-start justify-between gap-6 border-b-4 pb-4" style={{ borderColor: colour }}>
          <div className="flex items-center gap-3">
            {lh?.logo_url && <img src={lh.logo_url} alt="" className="h-14 w-auto object-contain" />}
            <div>
              <div className="text-xl font-bold" style={{ color: colour }}>{company}</div>
              {lh?.address && <div className="max-w-[90mm] whitespace-pre-line text-neutral-600">{lh.address}</div>}
              <div className="text-neutral-600">{[lh?.phone, lh?.email].filter(Boolean).join(' · ')}</div>
              {lh?.gstin && <div className="text-neutral-600">GSTIN {lh.gstin}</div>}
            </div>
          </div>
          <div className="text-right">
            <div className="text-lg font-bold tracking-wide">RUNNING ACCOUNT BILL</div>
            <div className="font-semibold tabular-nums">{b.ref}</div>
            <div className="text-neutral-600">{billDay(b.bill_date)}</div>
            {b.period_to && <div className="text-neutral-600">Work up to {billDay(b.period_to)}</div>}
          </div>
        </header>

        <section className="relative mt-5 grid grid-cols-2 gap-6">
          <div>
            <div className="text-[11px] font-semibold tracking-wide text-neutral-500 uppercase">To</div>
            <div className="font-semibold">{b.client_name ?? '—'}</div>
            {b.client_address && <div className="whitespace-pre-line text-neutral-600">{b.client_address}</div>}
            {b.client_gstin && <div className="text-neutral-600">GSTIN {b.client_gstin}</div>}
          </div>
          <div>
            <div className="text-[11px] font-semibold tracking-wide text-neutral-500 uppercase">Project</div>
            <div className="font-semibold">{b.project_name}</div>
            {b.contract_no && <div className="text-neutral-600">Agreement {b.contract_no}</div>}
            {b.contract_value && <div className="text-neutral-600">Contract value {rupees(b.contract_value)}</div>}
          </div>
        </section>

        <table className="relative mt-6 w-full border-collapse">
          <thead>
            <tr className="border-b-2 border-neutral-800 text-left text-[10.5px] tracking-wide text-neutral-600 uppercase">
              <th className="py-1.5 pr-2 font-semibold">Item</th>
              <th className="py-1.5 pr-2 font-semibold">Description</th>
              <th className="py-1.5 pr-2 text-right font-semibold">Up to previous</th>
              <th className="py-1.5 pr-2 text-right font-semibold">This bill</th>
              <th className="py-1.5 pr-2 text-right font-semibold">Up to date</th>
              <th className="py-1.5 pr-2 text-right font-semibold">Rate</th>
              <th className="py-1.5 text-right font-semibold">Amount</th>
            </tr>
          </thead>
          <tbody>
            {b.lines?.map((l, i) => (
              <tr key={l.id} className="border-b border-neutral-200 align-top">
                <td className="py-2 pr-2 tabular-nums text-neutral-500">{l.boq_code ?? i + 1}</td>
                <td className="py-2 pr-2 font-medium">{l.work}</td>
                <td className="py-2 pr-2 text-right tabular-nums">{qty(l.previous_quantity)}</td>
                <td className="py-2 pr-2 text-right tabular-nums">{qty(l.quantity)} {l.unit}</td>
                <td className="py-2 pr-2 text-right tabular-nums">{qty(l.upto_date)}</td>
                <td className="py-2 pr-2 text-right tabular-nums">{rupees(l.client_rate, 2)}</td>
                <td className="py-2 text-right tabular-nums">{rupees(l.amount, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <section className="relative mt-5 ml-auto w-[95mm]">
          {money.map(([label, value]) => (
            <div key={label} className="flex justify-between gap-4 py-0.5">
              <span className="text-neutral-700">{label}</span>
              <span className="tabular-nums">{rupees(value, 2)}</span>
            </div>
          ))}
          <div className="mt-1 flex justify-between gap-4 border-t-2 border-neutral-800 pt-1.5 text-base font-bold">
            <span>Net amount payable</span>
            <span className="tabular-nums">{rupees(b.net, 2)}</span>
          </div>
          {b.previous_billed !== undefined && Number(b.previous_billed) > 0 && (
            <div className="mt-2 text-neutral-600">Billed before this bill (work value): {rupees(b.previous_billed, 2)}</div>
          )}
        </section>

        {b.notes && (
          <section className="relative mt-6">
            <div className="text-[11px] font-semibold tracking-wide text-neutral-500 uppercase">Notes</div>
            <div className="whitespace-pre-line">{b.notes}</div>
          </section>
        )}

        <footer className="relative mt-14 flex items-end justify-between gap-6">
          <div className="text-neutral-600">Quantities as measured at site{b.lines?.some((l) => l.edited) ? ' and checked by the office' : ''}.</div>
          <div className="text-center">
            <div className="mb-1 h-10 w-48 border-b border-neutral-400" />
            <div className="font-semibold">{lh?.signatory_name ?? 'Authorised signatory'}</div>
            {lh?.signatory_designation && <div className="text-neutral-600">{lh.signatory_designation}</div>}
          </div>
        </footer>
      </article>
    </div>
  )
}
