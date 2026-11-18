import { api } from './api'

// ACC-18 / MP-06: cash flow for the coming weeks. Backend: domains/accounts/cashflow.py (GET /accounts/cash-flow). The
// server lists every expected payment with its week; the page adds them up by the kinds switched on, so turning one
// off (say, wages ahead) moves the balance at once with no new request.

export type FlowKind = 'client_bills' | 'to_bill' | 'supplier_bills' | 'delivered' | 'orders' | 'wages_due' | 'wages_ahead'

export interface FlowItem {
  kind: FlowKind
  date: string
  amount: string
  title: string
  who: string | null
  project_id: string | null
  project: string | null
  link: string
  /** Due before today: counted in this week. */
  overdue: boolean
  /** Its date is a guess (no credit days set, no expected date, an estimate). */
  assumed: boolean
  /** 0 is this week; null after the last week shown. */
  week: number | null
}

export interface CashFlow {
  as_of: string
  horizon: number
  client_days: number
  supplier_days: number
  /** Cash and bank today; null when a project is picked (an account is the company's). */
  opening: string | null
  accounts: { id: string; name: string; type: string; balance: string }[]
  items: FlowItem[]
  default_on: FlowKind[]
  weeks: { start: string; in: string; out: string; net: string; balance?: string }[]
}

export const IN_KINDS: FlowKind[] = ['client_bills', 'to_bill']
export const OUT_KINDS: FlowKind[] = ['supplier_bills', 'delivered', 'orders', 'wages_due', 'wages_ahead']

export const KIND_WORD: Record<FlowKind, string> = {
  client_bills: 'Client bills',
  to_bill: 'Work not billed',
  supplier_bills: 'Supplier bills',
  delivered: 'Delivered, not billed',
  orders: 'Orders to come',
  wages_due: 'Wages owed',
  wages_ahead: 'Wages ahead',
}

/** What each kind means, on hover. */
export const KIND_TITLE: Record<FlowKind, string> = {
  client_bills: 'RA bills sent and not paid, expected the client\'s days after the bill',
  to_bill: 'Measured work on no bill yet: money only if you bill it now',
  supplier_bills: 'Supplier and subcontractor bills not paid, due after their credit days',
  delivered: 'Deliveries the supplier has not billed yet',
  orders: 'What is still to come on open purchase orders, at the order\'s rates',
  wages_due: 'Wage sheets with something left to pay',
  wages_ahead: 'Each coming week with no wage sheet yet: the last four weeks\' wages a week',
}

export async function fetchCashFlow(params: { projectId?: string | null; weeks?: number; clientDays?: number; supplierDays?: number }): Promise<CashFlow> {
  return (await api.get<CashFlow>('/accounts/cash-flow', {
    params: {
      project_id: params.projectId || undefined,
      weeks: params.weeks,
      client_days: params.clientDays,
      supplier_days: params.supplierDays,
    },
  })).data
}

export interface WeekSum {
  start: string
  in: number
  out: number
  net: number
  balance: number | null
  items: FlowItem[]
}

/** The weeks added up by the kinds switched on, the running balance from the opening cash, and what is later. */
export function sumWeeks(cf: CashFlow, on: Set<FlowKind>): { weeks: WeekSum[]; later: WeekSum } {
  const opening = cf.opening === null ? null : Number(cf.opening)
  const weeks: WeekSum[] = cf.weeks.map((w) => ({ start: w.start, in: 0, out: 0, net: 0, balance: null, items: [] }))
  const later: WeekSum = { start: '', in: 0, out: 0, net: 0, balance: null, items: [] }
  for (const it of cf.items) {
    if (!on.has(it.kind)) continue
    const target = it.week === null ? later : weeks[it.week]
    if (!target) continue
    target.items.push(it)
    if (IN_KINDS.includes(it.kind)) target.in += Number(it.amount)
    else target.out += Number(it.amount)
  }
  let balance = opening
  for (const w of weeks) {
    w.net = w.in - w.out
    if (balance !== null) {
      balance += w.net
      w.balance = balance
    }
  }
  later.net = later.in - later.out
  return { weeks, later }
}
