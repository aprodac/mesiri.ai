import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import { useAuth } from './AuthContext'
import { MONEY_ROLES } from './module-map'

// CC-09 / CC-10: suppliers, what we owe them (the supplier ledger) and paying them. Rules live in the backend
// (domains/vendors/ledger.py): a priced delivery is owed until its bill comes, then the bill; a payment leaves the
// account once and pays the oldest bills first; what is left stays with the supplier as an advance.

export type VendorKind = 'supplier' | 'subcontractor' | 'hire' | 'service'

export const KINDS: Record<VendorKind, { label: string; plural: string; chip: string }> = {
  supplier: { label: 'Supplier', plural: 'Suppliers', chip: 'bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-100' },
  subcontractor: { label: 'Subcontractor', plural: 'Subcontractors', chip: 'bg-violet-100 text-violet-900 dark:bg-violet-950 dark:text-violet-100' },
  hire: { label: 'Hire', plural: 'Hire (machines)', chip: 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-100' },
  service: { label: 'Service', plural: 'Services', chip: 'bg-stone-200 text-stone-800 dark:bg-stone-800 dark:text-stone-100' },
}

export interface Vendor {
  id: string
  name: string
  code: string | null
  status: 'active' | 'inactive'
  phone: string | null
  gstin: string | null
  address: string | null
  kind: VendorKind
  credit_days: number | null
  /** MP-03: days from order to delivery (the material plan's order-by day; 3 when not set). */
  lead_time_days?: number | null
  opening_balance: string | null
  opening_balance_date: string | null
  contact_person: string | null
  notes: string | null
}

export type Buckets = Record<'0_30' | '31_60' | '61_90' | '90_plus', string>

export const BUCKETS: { key: keyof Buckets; label: string; tone: string }[] = [
  { key: '0_30', label: 'Up to 30 days', tone: 'bg-sky-500' },
  { key: '31_60', label: '31–60 days', tone: 'bg-amber-400' },
  { key: '61_90', label: '61–90 days', tone: 'bg-orange-500' },
  { key: '90_plus', label: 'Over 90 days', tone: 'bg-red-600' },
]

export interface Position {
  balance: string
  owed: string
  paid: string
  unbilled: string
  unbilled_count: number
  oldest_unbilled: string | null
  bills_open: number
  bills_left: string
  overdue: string
  advance_left: string
  buckets: Buckets
  last_payment: { date: string; amount: string } | null
  lines: number
}

export type PayableRow = Vendor & Position

export interface Payables {
  as_of: string
  partial: boolean
  totals: { payable: string; advance: string; overdue: string; unbilled: string; bills_left: string }
  buckets: Buckets
  vendors: PayableRow[]
}

export interface OpenBill {
  id: string
  date: string
  number: string | null
  bill_number: string | null
  description: string | null
  project: string | null
  project_id: string | null
  site: string | null
  payment_status: string
  deliveries: number
  /** PRC-11: deliveries on it whose quantity or rate differs from the bill. */
  mismatches: number
  /** NXT-06/07: what may be paid now (0 while a subcontract bill waits for its check; never the retention held). */
  payable: string
  work_order: { ref: string; bill: string; id: string; check_status: string; retention_held: string } | null
  amount: string
  paid: string
  left: string
  due: string | null
  age_days: number
  overdue_days: number
}

export interface Advance {
  id: string
  date: string
  amount: string
  left: string
  account: string
  project: string | null
  reference: string | null
}

export type LineKind = 'opening' | 'delivery' | 'bill' | 'staff_paid' | 'payment'

export interface LedgerLine {
  id: string
  date: string
  kind: LineKind
  title: string
  detail: string
  owe: string | null
  paid: string | null
  balance: string
  project_id: string | null
  project: string | null
  site: string | null
  ref: string | null
  links: { expense_id?: string; receipt_id?: string; order_id?: string; payment_id?: string; account_id?: string }
  bill_left?: string
  mismatches?: number
  on_account?: boolean
  advance_left?: string | null
  recorded_by?: string | null
}

export interface Ledger {
  vendor: Vendor
  as_of: string
  partial: boolean
  date_from: string | null
  date_to: string | null
  brought_forward: string | null
  closing: string
  period: { owed: string; paid: string }
  summary: Position & { open_bills: OpenBill[]; advances: Advance[] }
  unbilled: LedgerLine[]
  lines: LedgerLine[]
}

export interface VendorLinks {
  expenses: number
  deliveries: number
  bills: number
  orders: number
  payments: number
  /** NXT-11 / NXT-13; absent from an older API. */
  machines?: number
  'hire bills'?: number
}

export const LINE_LOOK: Record<LineKind, { label: string; dot: string }> = {
  opening: { label: 'Opening', dot: 'bg-stone-400' },
  delivery: { label: 'Delivered', dot: 'bg-amber-500' },
  bill: { label: 'Bill', dot: 'bg-sky-600' },
  staff_paid: { label: 'Paid by staff', dot: 'bg-violet-500' },
  payment: { label: 'Paid', dot: 'bg-green-600' },
}

export const PAY_METHODS = ['Bank transfer', 'UPI', 'Cheque', 'Cash'] as const

export async function fetchVendors(): Promise<Vendor[]> {
  return (await api.get('/finance/vendors')).data
}

export async function fetchVendor(id: string): Promise<Vendor & { linked: VendorLinks }> {
  return (await api.get(`/finance/vendors/${id}`)).data
}

export async function fetchPayables(params: { project_id?: string; include_settled?: boolean } = {}): Promise<Payables> {
  return (await api.get('/finance/vendors/payables', { params })).data
}

export async function fetchLedger(id: string, params: { project_id?: string; date_from?: string; date_to?: string } = {}): Promise<Ledger> {
  return (await api.get(`/finance/vendors/${id}/ledger`, { params })).data
}

export type VendorInput = Partial<Pick<Vendor, 'name' | 'phone' | 'gstin' | 'address' | 'kind' | 'credit_days' | 'lead_time_days' | 'contact_person' | 'notes' | 'opening_balance' | 'opening_balance_date' | 'status'>>

export async function createVendor(body: VendorInput & { name: string }): Promise<Vendor> {
  return (await api.post('/finance/vendors', body)).data
}

export async function updateVendor(id: string, body: VendorInput): Promise<Vendor> {
  return (await api.patch(`/finance/vendors/${id}`, body)).data
}

export async function deleteVendor(id: string): Promise<void> {
  await api.delete(`/finance/vendors/${id}`)
}

export async function mergeVendor(id: string, into: string): Promise<{ into: Vendor; moved: VendorLinks }> {
  return (await api.post(`/finance/vendors/${id}/merge`, { into_vendor_id: into })).data
}

export interface PayResult {
  payment_id: string
  vendor: string
  amount: string
  account: string
  paid_date: string
  bills_paid: { expense_id: string; number: string | null; amount: string }[]
  advance_left: string
}

export async function payVendor(id: string, body: { account_id: string; amount: string; paid_date?: string; reference?: string; method?: string; project_id?: string; bill_ids?: string[] }): Promise<PayResult> {
  return (await api.post(`/finance/vendors/${id}/payments`, body)).data
}

export async function applyAdvance(id: string, paymentId: string, billIds?: string[]): Promise<{ bills_paid: PayResult['bills_paid']; advance_left: string }> {
  return (await api.post(`/finance/vendors/${id}/payments/${paymentId}/apply`, billIds ? { bill_ids: billIds } : {})).data
}

export async function undoVendorPayment(id: string, paymentId: string): Promise<void> {
  await api.post(`/finance/vendors/${id}/payments/${paymentId}/reverse`)
}

export async function billDeliveries(id: string, body: { receipt_ids: string[]; amount?: string; bill_number?: string; bill_date?: string; tax_amount?: string }): Promise<{ expense_id: string; amount: string; deliveries: number; deliveries_total: string; difference: string }> {
  return (await api.post(`/finance/vendors/${id}/bills`, body)).data
}

export async function matchDeliveries(id: string, expenseId: string, receiptIds: string[]): Promise<{ deliveries: number; deliveries_total: string; bill_amount: string; difference: string }> {
  return (await api.post(`/finance/vendors/${id}/bills/${expenseId}/deliveries`, { receipt_ids: receiptIds })).data
}

export async function billDeliveryList(id: string, expenseId: string): Promise<{ receipt_id: string; date: string; material: string; quantity: string; unit: string; site: string | null; amount: string | null; billed_quantity: string | null; billed_rate: string | null; flags: string[] }[]> {
  return (await api.get(`/finance/vendors/${id}/bills/${expenseId}/deliveries`)).data
}

export async function unmatchDelivery(id: string, expenseId: string, receiptId: string): Promise<void> {
  await api.delete(`/finance/vendors/${id}/bills/${expenseId}/deliveries/${receiptId}`)
}

/** The supplier page, from anywhere a supplier is named. */
export const vendorUrl = (id: string, tab?: string) => `/finance/vendors/${id}${tab ? `?tab=${tab}` : ''}`

export const num = (s: string | null | undefined) => Number(s ?? 0) || 0

/** "12 Nov" (this year) or "12 Nov 2025". */
export function day(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(`${iso}T00:00:00`)
  const sameYear = d.getFullYear() === new Date().getFullYear()
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', ...(sameYear ? {} : { year: 'numeric' }) })
}

/** "We owe ₹58,200" / "They hold ₹2,000 of ours" / "Settled". */
export function balanceWords(balance: string, rupees: (n: number) => string): string {
  const b = num(balance)
  if (b > 0) return `We owe ${rupees(b)}`
  if (b < 0) return `${rupees(-b)} paid ahead`
  return 'Settled'
}

export function initials(name: string): string {
  return name.split(/\s+/).filter(Boolean).map((w) => w[0]).join('').slice(0, 2).toUpperCase()
}

/** How a payment would go, oldest bills first (or the ones ticked): the same rule as the API. */
export function allocate(amount: number, bills: OpenBill[]): { bill: OpenBill; part: number }[] {
  let left = amount
  const out: { bill: OpenBill; part: number }[] = []
  for (const b of bills) {
    if (left <= 0) break
    const part = Math.min(left, num(b.left))
    if (part > 0) out.push({ bill: b, part })
    left -= part
  }
  return out
}

// PRC-11: every delivery with no bill yet, across suppliers.
export interface UnbilledDelivery {
  receipt_id: string
  date: string
  days: number
  material: string
  quantity: string
  unit: string
  rate: string | null
  amount: string | null
  project_id: string
  project: string | null
  site: string | null
  vendor_id: string | null
  supplier: string | null
  order_id: string | null
  order_ref: string | null
}

export async function fetchUnbilled(params: { project_id?: string } = {}): Promise<{ as_of: string; deliveries: UnbilledDelivery[]; totals: { count: number; amount: string; unpriced: number; no_order: number; no_supplier: number } }> {
  return (await api.get('/finance/vendors/unbilled', { params })).data
}

// Supplier names typed on deliveries that point at no supplier record: on no account until linked.
export interface UnlinkedName { name: string; deliveries: number; last: string | null; amount: string | null; likely: { id: string; name: string } | null }

export async function fetchUnlinkedNames(): Promise<UnlinkedName[]> {
  return (await api.get('/finance/vendors/unlinked-names')).data
}

export async function linkName(body: { name: string; vendor_id?: string; create?: boolean }): Promise<{ vendor: Vendor; deliveries: number }> {
  return (await api.post('/finance/vendors/link-name', body)).data
}

/** The company's payables, read once and shared by every place that names a supplier (roles that see spending). */
export function usePayables() {
  const { me } = useAuth()
  const allowed = (MONEY_ROLES as readonly string[]).includes((me?.role || '').toUpperCase())
  return useQuery({ queryKey: ['finance', 'payables', ''], queryFn: () => fetchPayables({ include_settled: true }), enabled: allowed, staleTime: 60_000, retry: false })
}

