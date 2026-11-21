import type { LucideIcon } from 'lucide-react'
import { ClipboardCheck, ClipboardList, FileText, HardHat, ListChecks, Package, ReceiptIndianRupee, Scale, Wallet } from 'lucide-react'
import { api } from './api'
import { recordUrl } from './links'

// NXT-08: the approvals inbox, "what is waiting for me". Backend: domains/approvals (GET /approvals/waiting), a read
// over each module's own list as the caller, so a row is here exactly when its page would show it to this person.

export type WaitingKind = 'site_report' | 'material_request' | 'subcontract_bill' | 'ra_bill' | 'wage_sheet' | 'labour_split' | 'task' | 'stock_count'

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
  /** wage_sheet: the pay week's first day. */
  period_from?: string
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
  wage_sheet: 'Wages to approve or pay',
  labour_split: 'Labour on the BOQ to confirm',
  task: 'My tasks',
  stock_count: 'Stock counts to approve',
}
export const KIND_ORDER: WaitingKind[] = ['site_report', 'material_request', 'subcontract_bill', 'ra_bill', 'wage_sheet', 'labour_split', 'stock_count', 'task']

/** UX-62: each kind's short name, icon and tile colour on the Approvals page (one colour per kind, everywhere). */
export const KIND_LOOK: Record<WaitingKind, { short: string; icon: LucideIcon; tile: string }> = {
  site_report: { short: 'Site reports', icon: ClipboardCheck, tile: 'bg-orange-100 text-orange-700 dark:bg-orange-950 dark:text-orange-300' },
  material_request: { short: 'Material', icon: Package, tile: 'bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300' },
  subcontract_bill: { short: 'Sub bills', icon: ReceiptIndianRupee, tile: 'bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-300' },
  ra_bill: { short: 'RA bills', icon: FileText, tile: 'bg-teal-100 text-teal-700 dark:bg-teal-950 dark:text-teal-300' },
  wage_sheet: { short: 'Wages', icon: Wallet, tile: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300' },
  labour_split: { short: 'Labour', icon: HardHat, tile: 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300' },
  stock_count: { short: 'Stock counts', icon: Scale, tile: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-950 dark:text-cyan-300' },
  task: { short: 'My tasks', icon: ListChecks, tile: 'bg-stone-200 text-stone-700 dark:bg-stone-800 dark:text-stone-200' },
}
export const NOTHING_ICON = ClipboardList

/** Whole days an item has waited (0 = today). */
export function daysWaited(since: string | null, today: string): number {
  if (!since || !today) return 0
  return Math.max(0, Math.round((Date.parse(today.slice(0, 10)) - Date.parse(since.slice(0, 10))) / 86_400_000))
}

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
    case 'wage_sheet':
      // LW-08: the week's sheet, on its site and week.
      return `/labour/wages?${item.site_id ? `at=${item.site_id}&` : ''}week=${item.period_from ?? ''}`
    case 'labour_split':
      // BOQ-02c: the project's Budget page, its "Labour to check" list.
      return `/cost/budget?project=${item.project_id ?? ''}#labour-to-lines`
    case 'task':
      return recordUrl.task(item.id)
    case 'stock_count':
      return `/materials/counts?id=${item.id}`
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

/** FB-02: confirm every draft on a site's day in one go (the site's labour, work, materials and issues). */
export async function confirmSiteDay(siteId: string, date: string): Promise<{ confirmed: number }> {
  return (await api.post<{ confirmed: number }>(`/dpr/site-days/${siteId}/confirm`, null, { params: { date } })).data
}

/** FB-02: the rows that can be decided without opening them, so they can be ticked and approved together: a site's
 *  day (confirm all its entries) and a draft week of wages (approve). Bills, requests and counts are checked one by
 *  one on purpose: each carries its own figures, a reason or a choice. */
export function bulkApprovable(item: WaitingItem): boolean {
  if (item.kind === 'site_report') return !!(item.site_id && item.date)
  if (item.kind === 'wage_sheet') return (item.detail ?? '').startsWith('Draft')
  return false
}

export const itemKey = (item: WaitingItem) => `${item.kind}-${item.id}`
