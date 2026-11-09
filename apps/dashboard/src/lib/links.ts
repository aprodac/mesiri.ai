import type { LinkedRecord } from '@/components/page/page-kit'
import type { PurchaseOrder } from '@/lib/orders'
import type { MaterialRequest } from '@/lib/requests'

// Where each record sits in its chain (UX-09, docs/plans/ui-story-plan.md section 4c), built from the ids the
// API already returns. One place per record kind, so every panel that shows the record shows the same links.
// Addresses open the record itself: list pages select from ?id= (lib/url-state.ts).

export const recordUrl = {
  request: (id: string) => `/materials/requests?tab=all&id=${id}`,
  order: (id: string) => `/procurement/orders?tab=all&id=${id}`,
  supplier: (id: string, tab: 'account' | 'orders' = 'account') => `/finance/vendors/${id}?tab=${tab}`,
  siteDay: (projectId: string, siteId: string) => `/today?project=${projectId}&site=${siteId}`,
  // NXT-08: the approvals inbox opens each record where it is decided.
  siteReport: (date: string, siteId: string) => `/reports/${date}/sites/${siteId}`,
  task: (id: string) => `/tasks?id=${id}`,
  raBill: (id: string, projectId: string) => `/billing/ra-bills?project=${projectId}&bill=${id}`,
  workOrderBills: (workOrderId: string) => `/subcontract/work-orders/${workOrderId}?tab=bills`,
}

/** BUY → PAY: the requests an order came from; the supplier's account (bills, payments) it goes to. */
export function orderLinks(order: PurchaseOrder): LinkedRecord[] {
  const seen = new Set<string>()
  const requests: LinkedRecord[] = []
  for (const line of order.lines) {
    if (!line.request || seen.has(line.request.id)) continue
    seen.add(line.request.id)
    requests.push({ kind: 'Request', label: line.request.ref, status: line.request.status, url: recordUrl.request(line.request.id), side: 'before' })
  }
  const grns = order.grns ?? []
  return [
    ...requests,
    ...(grns.length ? [{ kind: 'Received', label: grns.map((g) => g.ref).join(', '), status: `${grns.length} ${grns.length === 1 ? 'delivery' : 'deliveries'}`, url: `/procurement/grn?q=${encodeURIComponent(order.ref)}`, side: 'after' as const }] : []),
    { kind: 'Supplier account', label: order.vendor_name, status: 'bills and payments', url: recordUrl.supplier(order.vendor_id), side: 'after' },
  ]
}

/** PLAN → DO: the site day a request came from; the orders that bring it. */
export function requestLinks(request: MaterialRequest): LinkedRecord[] {
  return [
    { kind: 'Site', label: request.site_name, status: 'today', url: recordUrl.siteDay(request.project_id, request.site_id), side: 'before' },
    ...request.orders.map((o) => ({ kind: 'Order', label: `${o.ref} · ${o.vendor_name}`, status: o.status, url: recordUrl.order(o.id), side: 'after' as const })),
  ]
}

/** WORK → COST: the work order a bill was checked against; the supplier's account and the project's cost after. */
export function expenseLinks(expense: { vendor_id?: string | null; vendor_name?: string | null; project_id?: string | null; project_name?: string | null },
  workOrder?: { work_order_id: string; wo_ref: string; check_status: string } | null): LinkedRecord[] {
  const links: LinkedRecord[] = []
  if (workOrder) links.push({ kind: 'Work order', label: workOrder.wo_ref, status: workOrder.check_status, url: `/subcontract/work-orders/${workOrder.work_order_id}?tab=bills`, side: 'before' })
  if (expense.vendor_id) links.push({ kind: 'Supplier account', label: expense.vendor_name || 'Supplier', url: recordUrl.supplier(expense.vendor_id), side: 'after' })
  if (expense.project_id) links.push({ kind: 'Project cost', label: expense.project_name || 'Project', status: 'budget vs actual', url: `/cost/budget?project=${expense.project_id}`, side: 'after' })
  return links
}

/** MONEY IN: a client bill prices the BOQ's measured work; then the money received and the project's profit. */
export function raBillLinks(bill: { project_id: string; project_name: string; status: string }): LinkedRecord[] {
  return [
    { kind: 'BOQ', label: bill.project_name, status: 'measured work', url: `/projects/${bill.project_id}/boq`, side: 'before' },
    ...(bill.status === 'draft' ? [] : [{ kind: 'Money received', label: 'Receivables', url: '/accounts/receivables', side: 'after' as const }]),
    { kind: 'Profit', label: 'Project P&L', url: `/accounts/projects/${bill.project_id}`, side: 'after' },
  ]
}

/** WORK → COST: a work order prices BOQ work for a subcontractor; its bills, the subcontractor's account and the
 *  project's cost come after. */
export function workOrderLinks(wo: { id: string; vendor_id: string; vendor_name: string; project_id: string; project_name: string; site_id: string | null; site_name: string | null }): LinkedRecord[] {
  return [
    { kind: 'BOQ', label: wo.project_name, status: 'the lines it covers', url: `/projects/${wo.project_id}/boq`, side: 'before' },
    ...(wo.site_id ? [{ kind: 'Site', label: wo.site_name ?? 'Site', status: 'work measured there', url: recordUrl.siteDay(wo.project_id, wo.site_id), side: 'before' as const }] : []),
    { kind: 'Bills', label: 'Bills & checks', url: `/subcontract/work-orders/${wo.id}?tab=bills`, side: 'after' },
    { kind: 'Subcontractor account', label: wo.vendor_name, url: recordUrl.supplier(wo.vendor_id), side: 'after' },
    { kind: 'Project cost', label: wo.project_name, status: 'budget vs actual', url: `/cost/budget?project=${wo.project_id}`, side: 'after' },
  ]
}

/** WORK → COST: a worker's days come from attendance; what they cost lands on the BOQ lines' labour. */
export function workerLinks(worker: { trades: string[]; contractors: string[] }): LinkedRecord[] {
  return [
    ...worker.trades.slice(0, 3).map((t) => ({ kind: 'Attendance', label: t, status: 'every day on site', url: `/labour?trade=${encodeURIComponent(t)}`, side: 'before' as const })),
    { kind: 'Labour cost', label: 'Green / red', status: 'labour against the budget it earned', url: '/cost/green-red', side: 'after' },
  ]
}
