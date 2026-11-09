import { api } from './api'
import { recordUrl } from './links'

// NXT-08: the approvals inbox, "what is waiting for me". Backend: domains/approvals (GET /approvals/waiting), a read
// over each module's own list as the caller, so a row is here exactly when its page would show it to this person.

export type WaitingKind = 'site_report' | 'material_request' | 'subcontract_bill' | 'ra_bill' | 'task'

export interface WaitingItem {
  kind: WaitingKind
  id: string
  ref: string | null
  title: string
  detail: string | null
  project_id: string | null
  project_name: string | null
  site_id: string | null
  site_name: string | null
  since: string | null
  urgent: boolean
  date?: string
  count?: number
  work_order_id?: string
  amount?: string | null
}

export interface Waiting {
  today: string
  total: number
  urgent: number
  counts: Partial<Record<WaitingKind, number>>
  items: WaitingItem[]
  unavailable: WaitingKind[]
}

export async function fetchWaiting(): Promise<Waiting> {
  const data = (await api.get<Partial<Waiting>>('/approvals/waiting')).data ?? {}
  return {
    today: data.today ?? '',
    total: data.total ?? 0,
    urgent: data.urgent ?? 0,
    counts: data.counts ?? {},
    items: data.items ?? [],
    unavailable: data.unavailable ?? [],
  }
}

/** The groups in the panel, in the order a person deals with them. */
export const KIND_LABEL: Record<WaitingKind, string> = {
  site_report: 'Site reports to confirm',
  material_request: 'Material requests',
  subcontract_bill: 'Subcontractor bills',
  ra_bill: 'RA bills in draft',
  task: 'My tasks',
}
export const KIND_ORDER: WaitingKind[] = ['site_report', 'material_request', 'subcontract_bill', 'ra_bill', 'task']

/** Where a row opens: the record's own page (lib/links.ts), never a new screen. */
export function waitingUrl(item: WaitingItem): string {
  switch (item.kind) {
    case 'site_report':
      return item.date && item.site_id ? recordUrl.siteReport(item.date, item.site_id) : '/today'
    case 'material_request':
      return recordUrl.request(item.id)
    case 'subcontract_bill':
      return item.work_order_id ? recordUrl.workOrderBills(item.work_order_id) : '/subcontract/work-orders'
    case 'ra_bill':
      return item.project_id ? recordUrl.raBill(item.id, item.project_id) : '/billing/ra-bills'
    case 'task':
      return recordUrl.task(item.id)
  }
}

/** "today", "yesterday", "3 days" from the item's date (the company's today from the API). */
export function waitedFor(since: string | null, today: string): string {
  if (!since || !today) return ''
  const days = Math.round((Date.parse(today.slice(0, 10)) - Date.parse(since.slice(0, 10))) / 86_400_000)
  if (days <= 0) return 'today'
  if (days === 1) return 'yesterday'
  return `${days} days`
}
