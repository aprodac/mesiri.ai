import { api } from './api'
import { MONEY_ROLES } from './module-map'

// PRC-46: Procurement > Returns -- material sent back to a supplier and its debit note (DN-0001). Typed boundary for
// /procurement/returns; the rules (what leaves stock, the debit note on the supplier ledger) are the API's.

/** Rates and the debit note's value: the roles that see the company's spending (D-CC4), as the API decides. */
export function seesMoney(role: string | null | undefined): boolean {
  return (MONEY_ROLES as readonly string[]).includes((role || '').toUpperCase())
}

/** Who records and settles a return: the office, as for orders (PRC-12 may change it). */
export function mayReturn(role: string | null | undefined): boolean {
  return ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'PROJECT_MANAGER'].includes((role || '').toUpperCase())
}

export type ReturnStatus = 'waiting' | 'sent' | 'settled' | 'cancelled'
export type ReturnReason = 'damaged' | 'short' | 'wrong_size' | 'excess' | 'quality_failed'

export const REASONS: { value: ReturnReason; label: string }[] = [
  { value: 'damaged', label: 'Damaged' },
  { value: 'short', label: 'Short' },
  { value: 'wrong_size', label: 'Wrong size' },
  { value: 'excess', label: 'Excess' },
  { value: 'quality_failed', label: 'Quality failed' },
]

export const RETURN_LOOK: Record<ReturnStatus, { label: string; dot: string; chip: string }> = {
  waiting: { label: 'Waiting for pickup', dot: 'bg-orange-500', chip: 'bg-orange-100 text-orange-900 dark:bg-orange-950 dark:text-orange-100' },
  sent: { label: 'Sent back', dot: 'bg-blue-500', chip: 'bg-blue-100 text-blue-900 dark:bg-blue-950 dark:text-blue-100' },
  settled: { label: 'Settled', dot: 'bg-emerald-500', chip: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100' },
  cancelled: { label: 'Cancelled', dot: 'bg-muted-foreground/50', chip: 'bg-muted text-muted-foreground' },
}

export interface ReturnLine {
  id: string
  material_id: string
  material: string
  unit: string
  unit_id: string
  main_category: string | null
  quantity: string
  reason: ReturnReason
  reason_label: string
  receipt_id: string | null
  receipt_date: string | null
  grn_line_id: string | null
  /** It left stock (RETURN_TO_VENDOR); a GRN's rejected quantity never came in. */
  from_stock: boolean
  // Money roles only.
  rate?: string | null
  gst_percent?: string | null
  rate_includes_gst?: boolean | null
  amount?: string | null
}

export interface MaterialReturn {
  id: string
  number: number
  ref: string
  status: ReturnStatus
  status_label: string
  vendor_id: string
  vendor_name: string
  vendor_phone: string | null
  vendor_gstin: string | null
  vendor_address: string | null
  project_id: string
  project_name: string
  site_id: string
  site_name: string
  grn_id: string | null
  grn_ref: string | null
  order_id: string | null
  order_ref: string | null
  returned_on: string
  notes: string | null
  source: string
  photos: number
  sent_on: string | null
  collected_by: string | null
  settled_how: 'replacement' | 'credit' | null
  settled_receipt_id: string | null
  settled_expense_id: string | null
  settled_expense_number: string | null
  settled_note: string | null
  settled_on: string | null
  cancel_reason: string | null
  created_by_name: string | null
  created_at: string
  what: string
  lines: ReturnLine[]
  timeline: { on: string; what: string; by: string | null }[]
  may_send: boolean
  may_settle: boolean
  may_cancel: boolean
  hint?: string
  // Money roles only.
  before_gst?: string
  gst?: string
  total?: string
  unpriced_lines?: number
}

export interface ReturnList {
  items: MaterialReturn[]
  total: number
  counts: { waiting: number; sent: number; this_month: number; owed_to_you?: string }
}

export async function fetchReturns(params: { project_id?: string | null; site_id?: string | null; vendor_id?: string | null } = {}): Promise<ReturnList> {
  const clean = Object.fromEntries(Object.entries(params).filter(([, v]) => v))
  const res = await api.get<ReturnList>('/procurement/returns', { params: clean })
  return res.data
}

export async function fetchReturn(id: string): Promise<MaterialReturn> {
  const res = await api.get<MaterialReturn>(`/procurement/returns/${id}`)
  return res.data
}

export interface ReturnSource {
  grn_line_id?: string
  receipt_id?: string
  date?: string
  from?: string
  material_id: string
  material: string
  unit: string
  unit_id: string
  delivered?: string
  /** What can still go back from it. */
  left: string
  in_stock: boolean
  said_reason?: string | null
  rate?: string | null
  gst_percent?: string | null
  rate_includes_gst?: boolean | null
  vendor_id: string | null
  vendor_name: string | null
  site_id: string
  site_name: string
  project_id: string
}

export type ReturnFrom = { grn_id: string } | { receipt_id: string } | { vendor_id: string; site_id?: string }

export async function fetchReturnSources(from: ReturnFrom): Promise<ReturnSource[]> {
  const res = await api.get<{ items: ReturnSource[] }>('/procurement/returns/sources', { params: from })
  return res.data.items
}

export interface ReturnLineIn {
  material_id?: string
  quantity: string
  rate?: string | null
  reason: ReturnReason
  receipt_id?: string
  grn_line_id?: string
}

export async function createReturn(body: {
  vendor_id?: string
  site_id?: string
  lines: ReturnLineIn[]
  returned_on?: string
  notes?: string | null
  photos?: { content_type: string; data_base64: string }[]
}): Promise<MaterialReturn> {
  const res = await api.post<MaterialReturn>('/procurement/returns', body)
  return res.data
}

export async function markReturnSent(id: string, body: { sent_on?: string; collected_by?: string | null }): Promise<MaterialReturn> {
  const res = await api.post<MaterialReturn>(`/procurement/returns/${id}/sent`, body)
  return res.data
}

export async function settleReturn(id: string, body: { how: 'replacement' | 'credit'; receipt_id?: string | null; expense_id?: string | null; note?: string | null }): Promise<MaterialReturn> {
  const res = await api.post<MaterialReturn>(`/procurement/returns/${id}/settle`, body)
  return res.data
}

export async function cancelReturn(id: string, reason: string): Promise<MaterialReturn> {
  const res = await api.post<MaterialReturn>(`/procurement/returns/${id}/cancel`, { reason })
  return res.data
}

export async function fetchReturnPhotos(id: string): Promise<string[]> {
  const res = await api.get<{ items: (string | null)[] }>(`/procurement/returns/${id}/photos`)
  return res.data.items.filter((u): u is string => !!u)
}

/** The debit note as a WhatsApp message to the supplier (the person sends it from their own WhatsApp). */
export function debitNoteMessage(r: MaterialReturn, company: string): string {
  const lines = r.lines.map((l) => `• ${l.material}: ${Number(l.quantity).toLocaleString('en-IN')} ${l.unit} (${l.reason_label.toLowerCase()})${l.amount ? ` ₹${Number(l.amount).toLocaleString('en-IN')}` : ''}`)
  return [
    `Debit note ${r.ref}${company ? ` from ${company}` : ''}`,
    `Material returned from ${r.site_name} on ${r.returned_on}${r.grn_ref ? ` (${r.grn_ref}${r.order_ref ? `, ${r.order_ref}` : ''})` : ''}:`,
    ...lines,
    r.total ? `Total ₹${Number(r.total).toLocaleString('en-IN')}: please send a replacement or reduce it from your bill.` : 'Please send a replacement or reduce it from your bill.',
  ].join('\n')
}
