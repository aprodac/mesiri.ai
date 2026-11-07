import { api } from './api'
import type { Urgency } from './requests'

// PRC-06/07/08: purchase orders. Shapes mirror backend/src/mesiri/domains/procurement/orders.py (what an order
// shows) and orders_router.py (the routes). Received and still-to-come are read from deliveries, never typed.

export type OrderStatus = 'open' | 'part' | 'received' | 'closed' | 'cancelled'

export interface OrderLine {
  id: string
  material_id: string
  material: string
  main_category: string | null
  category_id: string | null
  main_category_id: string | null
  unit: string
  unit_id: string
  quantity: string
  said: string | null
  received: string
  pending: string
  extra: string
  /** Only for the roles that see spending. */
  rate: string | null
  amount: string | null
  request: { id: string; ref: string; status: string; line_id: string } | null
}

export interface PurchaseOrder {
  id: string
  number: number
  ref: string
  project_id: string
  project_name: string
  site_id: string
  site_name: string
  vendor_id: string
  vendor_name: string
  vendor_phone: string | null
  status: OrderStatus
  urgency: Urgency
  expected_date: string | null
  notes: string | null
  /** PRC-30: the number it also goes by outside Mesiri (their paper PO, the supplier's quote, a Tally voucher). */
  their_ref: string | null
  status_note: string | null
  status_by_name: string | null
  status_at: string | null
  raised_over_duplicate: boolean
  created_by: string | null
  created_by_name: string | null
  created_at: string
  lines: OrderLine[]
  progress: number
  value: string | null
  value_received: string | null
  value_complete: boolean | null
  deliveries: { id: string; line_id: string; material: string; quantity: string; unit: string; date: string; by_name: string | null; at: string }[]
  duplicates: { id: string; ref: string; vendor_name: string; created_by_name: string | null }[]
  /** PRC-23 (one order only): deliveries at its site of its materials, on no order, since it was placed. */
  unlinked_deliveries?: { id: string; material_id: string; material: string; quantity: string; unit: string; date: string; supplier: string | null; by_name: string | null }[]
  may_edit: boolean
  may_cancel: boolean
  may_close: boolean
  may_receive: boolean
  /** PRC-31: a closed or cancelled order can be opened again (the office). */
  may_reopen: boolean
}

export async function fetchOrders(params: { project_id?: string | null; site_id?: string | null }): Promise<{ items: PurchaseOrder[] }> {
  const { data } = await api.get('/procurement/orders', {
    params: { status: 'all', project_id: params.project_id || undefined, site_id: params.site_id || undefined },
  })
  return data
}

export interface CreateOrderPayload {
  project_id: string
  site_id: string
  vendor_id?: string | null
  supplier?: string | null
  lines: { material_id: string; quantity: string; unit_id: string; rate?: string | null; request_line_id?: string | null }[]
  expected_date?: string | null
  notes?: string | null
  their_ref?: string | null
  confirm_duplicate?: boolean
}

export async function createOrder(payload: CreateOrderPayload): Promise<PurchaseOrder> {
  const { data } = await api.post('/procurement/orders', payload)
  return data
}

export async function updateOrder(id: string, payload: {
  expected_date?: string | null
  notes?: string | null
  supplier?: string | null
  their_ref?: string | null
  lines?: CreateOrderPayload['lines']
}): Promise<PurchaseOrder> {
  const { data } = await api.patch(`/procurement/orders/${id}`, payload)
  return data
}

export async function reopenOrder(id: string): Promise<PurchaseOrder> {
  const { data } = await api.post(`/procurement/orders/${id}/reopen`)
  return data
}

export async function cancelOrder(id: string, reason: string): Promise<PurchaseOrder> {
  const { data } = await api.post(`/procurement/orders/${id}/cancel`, { reason })
  return data
}

export async function closeOrder(id: string, reason: string): Promise<PurchaseOrder> {
  const { data } = await api.post(`/procurement/orders/${id}/close`, { reason })
  return data
}

export async function receiveOrder(id: string, payload: { occurred_date: string; lines: { line_id: string; quantity: string }[]; notes?: string; confirm_extra?: boolean }): Promise<PurchaseOrder> {
  const { data } = await api.post(`/procurement/orders/${id}/receive`, payload)
  return data
}

/** PRC-23: put a delivery already recorded on an order line, or take it off its order (`line_id` null). */
export async function setDeliveryOrder(receiptId: string, payload: { line_id: string | null; confirm_extra?: boolean }): Promise<unknown> {
  const { data } = await api.post(`/procurement/orders/deliveries/${receiptId}/order`, payload)
  return data
}

/** PRC-23: the API's question when more came than the line still has to come (409 `more_than_ordered`). */
export interface MoreThanOrdered { code: 'more_than_ordered'; message: string; ref: string; pending: string; quantity: string; unit: string }

export function asMoreThanOrdered(err: unknown): MoreThanOrdered | null {
  const res = (err as { response?: { status?: number; data?: { detail?: unknown } } })?.response
  const d = res?.status === 409 ? (res.data?.detail as MoreThanOrdered | undefined) : undefined
  return d && typeof d === 'object' && d.code === 'more_than_ordered' ? d : null
}

export const ORDER_LOOK: Record<OrderStatus, { label: string; chip: string; dot: string }> = {
  open: { label: 'Ordered', chip: 'bg-info-soft text-info', dot: 'bg-blue-600' },
  part: { label: 'Part received', chip: 'bg-teal-100 text-teal-900 dark:bg-teal-950 dark:text-teal-100', dot: 'bg-teal-600' },
  received: { label: 'Received', chip: 'bg-success-soft text-success', dot: 'bg-green-700' },
  closed: { label: 'Closed short', chip: 'bg-stone-200 text-stone-800 dark:bg-stone-700 dark:text-stone-100', dot: 'bg-stone-500' },
  cancelled: { label: 'Cancelled', chip: 'bg-muted text-muted-foreground', dot: 'bg-muted-foreground/60' },
}

export function rupees(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const n = Number(value)
  if (n >= 1e7) return `₹${(n / 1e7).toLocaleString('en-IN', { maximumFractionDigits: 2 })} Cr`
  if (n >= 1e5) return `₹${(n / 1e5).toLocaleString('en-IN', { maximumFractionDigits: 2 })} L`
  return `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
}

export function dueWords(o: Pick<PurchaseOrder, 'expected_date' | 'status'>, today = new Date()): string {
  if (o.status === 'received') return 'Received'
  if (o.status === 'closed' || o.status === 'cancelled') return 'Closed'
  if (!o.expected_date) return 'No date'
  const due = new Date(`${o.expected_date}T00:00:00`)
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  const days = Math.round((due.getTime() - start.getTime()) / 86_400_000)
  if (days < 0) return `${-days} day${days === -1 ? '' : 's'} late`
  if (days === 0) return 'Due today'
  if (days === 1) return 'Due tomorrow'
  return `Due ${due.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })}`
}
