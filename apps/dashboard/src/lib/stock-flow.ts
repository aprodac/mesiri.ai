import type { OrderLine, PurchaseOrder } from '@/lib/orders'
import type { MaterialRequest, RequestLine } from '@/lib/requests'

// WEB-77: Materials > Stock joined to Procurement -- for each site and item, the requests waiting for the office and
// the open order lines still to come, read from the same lists the Requests and Purchase orders pages show.

/** What procurement has in hand for one item at one site: waiting requests and open order lines. */
export interface StockFlow {
  requests: { request: MaterialRequest; line: RequestLine }[]
  orders: { order: PurchaseOrder; line: OrderLine }[]
  /** Asked for on waiting requests, in the stock unit. */
  asked: number
}

export const NO_FLOW: StockFlow = { requests: [], orders: [], asked: 0 }

export const flowKey = (siteId: string | null, materialId: string) => `${siteId ?? ''}:${materialId}`

/** The waiting requests and open orders of every site and item, keyed by `flowKey`. */
export function buildFlows(requests: MaterialRequest[], orders: PurchaseOrder[]): Map<string, StockFlow> {
  const flows = new Map<string, StockFlow>()
  const get = (key: string) => {
    let flow = flows.get(key)
    if (!flow) flows.set(key, (flow = { requests: [], orders: [], asked: 0 }))
    return flow
  }
  for (const request of requests) {
    if (request.status !== 'waiting') continue
    for (const line of request.lines) {
      const flow = get(flowKey(request.site_id, line.material_id))
      flow.requests.push({ request, line })
      flow.asked += Number(line.quantity)
    }
  }
  for (const order of orders) {
    if (order.status !== 'open' && order.status !== 'part') continue
    for (const line of order.lines) if (Number(line.pending) > 0) get(flowKey(order.site_id, line.material_id)).orders.push({ order, line })
  }
  return flows
}

export const lasts = (days: number | null) => (days === null ? '' : days < 1 ? 'under 1 day' : `~${days} ${days === 1 ? 'day' : 'days'}`)

/** A running-low row's chip: out, how long it lasts, or (PRC-47) "Below min" when nothing was used and only the
 * minimum makes it low -- never "under 1 day" for stock nobody is using. */
export function lowWords(row: { closing: string; days_left: number | null; below_min?: boolean }): string {
  if (Number(row.closing) <= 0) return 'Out'
  if (row.days_left === null) return row.below_min ? 'Below min' : 'Low'
  return lasts(row.days_left)
}

