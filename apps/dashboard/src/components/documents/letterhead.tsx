import type { ReactNode } from 'react'
import type { CompanyBranding } from '@/lib/api'

// The company's letterhead on a document sent to a supplier (PRC-26 purchase order, PRC-46 debit note): logo, name in
// the brand colour, address, phone, GSTIN on the left; the document's title, number and date on the right. One
// header, so every document the company sends looks the same.

export function Letterhead({ brand: b, title, children }: { brand: CompanyBranding | undefined; title: string; children: ReactNode }) {
  const colour = b?.brand_color || '#1f2937'
  return (
    <header className="flex items-start justify-between gap-6 border-b-4 pb-4" style={{ borderColor: colour }}>
      <div className="flex items-center gap-3">
        {b?.logo_url && <img src={b.logo_url} alt="" className="h-14 w-auto object-contain" />}
        <div>
          <div className="text-xl font-bold" style={{ color: colour }}>{b?.letterhead_name || b?.company_name || ''}</div>
          {b?.address && <div className="max-w-[90mm] whitespace-pre-line text-neutral-600">{b.address}</div>}
          <div className="text-neutral-600">{[b?.phone, b?.email].filter(Boolean).join(' · ')}</div>
          {b?.gstin && <div className="text-neutral-600">GSTIN {b.gstin}</div>}
        </div>
      </div>
      <div className="text-right">
        <div className="text-lg font-bold tracking-wide">{title}</div>
        {children}
      </div>
    </header>
  )
}

/** The signature block at the foot of a document. */
export function Signatory({ brand: b, left }: { brand: CompanyBranding | undefined; left: ReactNode }) {
  return (
    <footer className="mt-14 flex items-end justify-between gap-6">
      <div className="text-neutral-600">{left}</div>
      <div className="text-center">
        <div className="mb-1 h-10 w-48 border-b border-neutral-400" />
        <div className="font-semibold">{b?.signatory_name ?? 'Authorised signatory'}</div>
        {b?.signatory_designation && <div className="text-neutral-600">{b.signatory_designation}</div>}
      </div>
    </footer>
  )
}
