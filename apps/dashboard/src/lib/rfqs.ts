import { api } from './api'
import { rate } from './rates'

// PRC-40..44: quotations. Shapes mirror backend/src/mesiri/domains/procurement/rfqs.py (what an RFQ and its comparison
// sheet show) and rfqs_router.py (the routes). Every rate is compared as it costs the company (GST per D-CC8).

export type RfqStatus = 'open' | 'ready' | 'awarded' | 'closed' | 'cancelled'
export type SupplierStatus = 'invited' | 'quoted' | 'declined'

export interface QuoteCell {
  rfq_vendor_id: string
  lowest: boolean
  /** Only for the roles that see spending. */
  quote_line_id?: string
  cost?: string
  amount?: string
  highest?: boolean
  rate_entered?: string
  rate_with_gst?: string
  rate_before_gst?: string
  gst_percent?: string | null
  rate_includes_gst?: boolean | null
  gst_known?: boolean
  gst_claimable?: boolean
  brand?: string | null
  remark?: string | null
  vs_last_paid_pct?: string | null
}

export interface RfqLine {
  id: string
  material_id: string
  material: string
  unit: string
  unit_id: string
  quantity: string
  said: string | null
  main_category: string | null
  request_line_id: string | null
  awarded_quote_line_id: string | null
  award_reason: string | null
  /** Cheapest first. */
  quotes: QuoteCell[]
  last_paid: { rate: string; date: string; vendor_name: string } | null
}

export interface RfqSupplier {
  rfq_vendor_id: string
  vendor_id: string
  name: string
  phone: string | null
  gstin: string | null
  status: SupplierStatus
  sent_at: string | null
  decline_reason: string | null
  quoted_at: string | null
  valid_until: string | null
  delivery_days: number | null
  payment_days: number | null
  their_ref: string | null
  notes: string | null
  source: string | null
  has_photo: boolean
  lines_quoted: number
  lines_lowest: number
  total: string | null
  total_with_gst: string | null
  complete: boolean
  best_total: boolean
}

export interface Rfq {
  id: string
  number: number
  ref: string
  project_id: string
  project_name: string
  site_id: string
  site_name: string
  request: { id: string; ref: string } | null
  status: RfqStatus
  due_date: string | null
  due_days: number | null
  needed_by: string | null
  terms: string | null
  notes: string | null
  status_note: string | null
  status_by_name: string | null
  status_at: string | null
  created_by_name: string | null
  created_at: string
  counts: Record<SupplierStatus, number>
  orders: { id: string; ref: string; status: string }[]
  lines: RfqLine[]
  suppliers: RfqSupplier[]
  lowest_total: { rfq_vendor_id: string; name: string; total: string } | null
  lowest_per_line: { total: string; suppliers: number; complete: boolean; saves: string | null } | null
  may_edit: boolean
  may_award: boolean
  may_cancel: boolean
  may_record: boolean
}

export const RFQ_LOOK: Record<RfqStatus, { label: string; chip: string; dot: string }> = {
  open: { label: 'Waiting for quotes', chip: 'bg-info-soft text-info', dot: 'bg-blue-500' },
  ready: { label: 'Ready to compare', chip: 'bg-yellow-100 text-yellow-900 dark:bg-yellow-950 dark:text-yellow-100', dot: 'bg-yellow-500' },
  awarded: { label: 'Ordered', chip: 'bg-teal-100 text-teal-900 dark:bg-teal-950 dark:text-teal-100', dot: 'bg-teal-500' },
  closed: { label: 'Closed', chip: 'bg-muted text-foreground/70', dot: 'bg-muted-foreground/50' },
  cancelled: { label: 'Cancelled', chip: 'bg-muted text-foreground/60', dot: 'bg-muted-foreground/30' },
}

export const SUPPLIER_LOOK: Record<SupplierStatus, { label: string; chip: string }> = {
  invited: { label: 'Waiting', chip: 'bg-muted text-foreground/75' },
  quoted: { label: 'Quoted', chip: 'bg-teal-100 text-teal-900 dark:bg-teal-950 dark:text-teal-100' },
  declined: { label: 'Declined', chip: 'bg-destructive/10 text-destructive' },
}

export async function fetchRfqs(params: { project_id?: string | null; site_id?: string | null } = {}): Promise<{ items: Rfq[]; total: number }> {
  const { data } = await api.get('/procurement/rfqs', { params: { project_id: params.project_id || undefined, site_id: params.site_id || undefined } })
  return data
}

export async function fetchRfq(id: string): Promise<Rfq> {
  const { data } = await api.get<Rfq>(`/procurement/rfqs/${id}`)
  return data
}

export interface RfqCreatePayload {
  project_id?: string
  site_id?: string
  request_id?: string
  lines?: { material_id: string; quantity: string; unit_id: string; request_line_id?: string | null }[]
  vendor_ids?: string[]
  suppliers?: string[]
  due_date?: string | null
  needed_by?: string | null
  terms?: string | null
  notes?: string | null
}

export async function createRfq(payload: RfqCreatePayload): Promise<Rfq> {
  const { data } = await api.post<Rfq>('/procurement/rfqs', payload)
  return data
}

export async function updateRfq(id: string, payload: { due_date?: string | null; needed_by?: string | null; terms?: string | null; notes?: string | null }): Promise<Rfq> {
  const { data } = await api.patch<Rfq>(`/procurement/rfqs/${id}`, payload)
  return data
}

export async function addRfqSupplier(id: string, supplier: string): Promise<Rfq> {
  const { data } = await api.post<Rfq>(`/procurement/rfqs/${id}/suppliers`, { supplier })
  return data
}

export async function markRfqSent(id: string, rv: string): Promise<Rfq> {
  const { data } = await api.post<Rfq>(`/procurement/rfqs/${id}/suppliers/${rv}/sent`)
  return data
}

export async function declineRfq(id: string, rv: string, reason: string): Promise<Rfq> {
  const { data } = await api.post<Rfq>(`/procurement/rfqs/${id}/suppliers/${rv}/decline`, { reason })
  return data
}

export interface QuotePayload {
  vendor_id?: string
  supplier?: string
  lines: { rfq_line_id: string; rate: string; gst_percent?: string; rate_includes_gst?: boolean; brand?: string | null; remark?: string | null }[]
  gst_percent?: string
  rates_include_gst?: boolean
  valid_until?: string | null
  delivery_days?: number | null
  payment_days?: number | null
  their_ref?: string | null
  notes?: string | null
}

export async function recordQuote(id: string, payload: QuotePayload): Promise<Rfq> {
  const { data } = await api.post<Rfq>(`/procurement/rfqs/${id}/quotes`, payload)
  return data
}

export interface AwardPayload {
  mode: 'lowest_total' | 'lowest_per_line' | 'picks'
  picks?: { rfq_line_id: string; vendor_id: string }[]
  reason?: string | null
  expected_date?: string | null
  confirm_duplicate?: boolean
}

export async function awardRfq(id: string, payload: AwardPayload): Promise<Rfq> {
  const { data } = await api.post<Rfq>(`/procurement/rfqs/${id}/award`, payload)
  return data
}

export async function closeRfq(id: string, kind: 'close' | 'cancel', reason: string): Promise<Rfq> {
  const { data } = await api.post<Rfq>(`/procurement/rfqs/${id}/${kind}`, { reason })
  return data
}

/** "Not the cheapest for … : say why" from the award route. */
export function asReasonNeeded(err: unknown): { message: string; items: string[] } | null {
  const r = (err as { response?: { status?: number; data?: { detail?: { code?: string; message?: string; items?: string[] } } } })?.response
  const d = r?.data?.detail
  return r?.status === 422 && d && d.code === 'reason_needed' ? { message: d.message ?? '', items: d.items ?? [] } : null
}

export function dueWords(r: Pick<Rfq, 'due_days' | 'status'>): string | null {
  if (r.status !== 'open' && r.status !== 'ready') return null
  if (r.due_days === null) return null
  if (r.due_days < 0) return `Quotes were due ${-r.due_days} day${r.due_days === -1 ? '' : 's'} ago`
  if (r.due_days === 0) return 'Quotes due today'
  if (r.due_days === 1) return 'Quotes due tomorrow'
  return `Quotes due in ${r.due_days} days`
}

const n = (v: string | number) => Number(v).toLocaleString('en-IN', { maximumFractionDigits: 3 })
const day = (d: string) => new Date(`${d}T00:00:00`).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })

/** The RFQ for a supplier, on WhatsApp (the person sends it). */
export function rfqMessage(r: Rfq, company?: string | null): string {
  return [
    `*Request for quotation ${r.ref}*`,
    company ? `From: ${company}` : null,
    `Deliver to: ${r.project_name} › ${r.site_name}`,
    r.needed_by ? `Needed by: ${day(r.needed_by)}` : null,
    '',
    ...r.lines.map((l) => `• ${l.material}: ${n(l.quantity)} ${l.unit}`),
    '',
    'Please quote for each item: rate per unit, GST % and whether the rate includes it, delivery days, and how long the rate is valid.',
    r.terms ? `Terms: ${r.terms}` : null,
    r.due_date ? `Please reply by ${day(r.due_date)}.` : null,
  ].filter((x) => x !== null).join('\n')
}

/** A thank-you to a supplier that was not chosen. */
export function thanksMessage(r: Rfq, name: string): string {
  return `Thank you ${name} for your quote on ${r.ref}. We have placed this order elsewhere this time; we will ask you again for the next one.`
}

export function perUnit(value: string | null | undefined, unit: string): string {
  return value ? `${rate(value)}/${unit}` : '—'
}
