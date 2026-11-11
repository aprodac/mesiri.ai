import { useQuery } from '@tanstack/react-query'
import { api } from './api'

// PRC-52: a supplier's own papers (GST, PAN, cheque, agreement, ISO / BIS, other). Backend: domains/vendors/documents.py,
// routes in vendors/router.py. PAN, cheque and agreement only reach the roles that see spending.

export type PaperKind = 'gst' | 'pan' | 'cheque' | 'agreement' | 'iso_bis' | 'other'
export type PaperStatus = 'valid' | 'expiring' | 'expired' | 'missing' | 'none'

export interface Paper {
  id: string
  kind: PaperKind
  number: string | null
  valid_until: string | null
  status: 'current' | 'superseded' | 'archived'
  file_name: string
  content_type: string
  size_bytes: number
  notes: string | null
  uploaded_by_name: string | null
  created_at: string
}

export interface PaperKindRow {
  kind: PaperKind
  label: string
  restricted: boolean
  required: boolean
  status: PaperStatus
  days_left: number | null
  /** What the supplier record already holds (GSTIN; PAN read from it). */
  on_record: string | null
  current: Paper[]
  history: Paper[]
}

export interface VendorPapers {
  vendor_id: string
  kinds: PaperKindRow[]
  attention: 'expired' | 'missing' | 'expiring' | 'ok'
  may_add: boolean
}

export interface PapersAttention {
  vendor_id: string
  name: string
  attention: 'expired' | 'missing' | 'expiring'
  papers: { kind: PaperKind; label: string; status: PaperStatus; days_left: number | null }[]
}

export async function fetchVendorPapers(vendorId: string): Promise<VendorPapers> {
  return (await api.get<VendorPapers>(`/finance/vendors/${vendorId}/documents`)).data
}

export async function addVendorPaper(vendorId: string, file: File, fields: { kind: PaperKind; number?: string; valid_until?: string }): Promise<VendorPapers> {
  const form = new FormData()
  form.append('file', file)
  for (const [k, v] of Object.entries(fields)) if (v) form.append(k, v)
  return (await api.post<VendorPapers>(`/finance/vendors/${vendorId}/documents`, form)).data
}

export async function paperLink(vendorId: string, docId: string): Promise<string | null> {
  return (await api.get<{ url: string | null }>(`/finance/vendors/${vendorId}/documents/${docId}`)).data.url
}

export async function archiveVendorPaper(vendorId: string, docId: string): Promise<VendorPapers> {
  return (await api.delete<VendorPapers>(`/finance/vendors/${vendorId}/documents/${docId}`)).data
}

/** Suppliers whose papers need a look (the list's warning, Today). */
export function usePapersAttention(enabled = true) {
  return useQuery({
    queryKey: ['finance', 'vendor-papers', 'attention'],
    queryFn: async () => (await api.get<{ items: PapersAttention[] }>('/finance/vendors/papers')).data.items,
    enabled, staleTime: 5 * 60_000, retry: false,
  })
}

export function paperStatusWords(status: PaperStatus, daysLeft: number | null): string {
  if (status === 'expired') return daysLeft !== null ? `Expired ${-daysLeft} day${daysLeft === -1 ? '' : 's'} ago` : 'Expired'
  if (status === 'expiring') return daysLeft === 0 ? 'Expires today' : `Expires in ${daysLeft} day${daysLeft === 1 ? '' : 's'}`
  if (status === 'missing') return 'Missing'
  if (status === 'valid') return 'Valid'
  return 'Not on file'
}
