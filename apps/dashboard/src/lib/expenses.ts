import { api } from './api'

// PRC-18: an expense as the Expenses and Money pages read it, and how it was paid (decision D3: from the account it
// was paid from; backend domains/expenses/paid_via.py decides, the pages only show it).

export type PaidVia = 'petty_cash' | 'direct' | 'own_pocket' | 'unpaid'

export const PAID_VIA: Record<PaidVia, { label: string; short: string; chip: string; dot: string }> = {
  petty_cash: { label: 'Petty cash', short: 'Petty cash', chip: 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-100', dot: 'bg-amber-500' },
  direct: { label: 'Paid direct', short: 'Direct', chip: 'bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-100', dot: 'bg-sky-500' },
  own_pocket: { label: 'Owed to staff', short: 'Owed back', chip: 'bg-violet-100 text-violet-900 dark:bg-violet-950 dark:text-violet-100', dot: 'bg-violet-500' },
  unpaid: { label: 'Unpaid', short: 'Unpaid', chip: 'bg-draft-soft text-draft', dot: 'bg-orange-500' },
}

export interface Expense {
  id: string
  number: string | null
  amount: number
  category_id: string
  category: string
  vendor_id: string | null
  vendor: string | null
  project_id: string | null
  project: string | null
  site_id: string | null
  site: string | null
  description: string | null
  date: string
  payment: string
  paid_via: PaidVia
  account_id: string | null
  account: string | null
  recorded_by: string | null
  source: 'whatsapp' | 'web'
  reversed: boolean
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function toExpense(raw: any): Expense {
  const via = (['petty_cash', 'direct', 'own_pocket', 'unpaid'] as const).includes(raw.paid_via)
    ? (raw.paid_via as PaidVia)
    : raw.payment_status === 'reimbursable'
      ? 'own_pocket'
      : 'unpaid'
  return {
    id: String(raw.id),
    number: raw.expense_number ?? null,
    amount: Number(raw.amount) || 0,
    category_id: String(raw.category_id ?? ''),
    category: raw.category_name || 'No category',
    vendor_id: raw.vendor_id ? String(raw.vendor_id) : null,
    vendor: raw.vendor_name ?? null,
    project_id: raw.project_id ? String(raw.project_id) : null,
    project: raw.project_name ?? null,
    site_id: raw.site_id ? String(raw.site_id) : null,
    site: raw.site_name ?? null,
    description: raw.description ?? null,
    date: raw.occurred_date,
    payment: raw.payment_status,
    paid_via: via,
    account_id: raw.account_id ? String(raw.account_id) : null,
    account: raw.account_name ?? null,
    recorded_by: raw.created_by_name ?? null,
    source: raw.source === 'whatsapp' ? 'whatsapp' : 'web',
    reversed: raw.workflow_status === 'reversed',
  }
}

/** How it was paid, in words: "Petty cash · Villa box", "Owed to Ravi", "Part paid · SBI", "Unpaid". */
export function paidWords(e: Expense): string {
  if (e.paid_via === 'own_pocket') return e.recorded_by ? `Owed to ${e.recorded_by.split(' ')[0]}` : 'Owed back to who paid'
  if (e.paid_via === 'unpaid') return 'Unpaid'
  const part = e.payment === 'partially_paid' ? 'Part paid' : PAID_VIA[e.paid_via].label
  return e.account ? `${part} · ${e.account}` : part
}

export interface ExpenseFilters {
  project_id?: string
  site_id?: string
  vendor_id?: string
  date_from?: string
  date_to?: string
}

export async function fetchExpenses(filters: ExpenseFilters = {}): Promise<Expense[]> {
  const res = await api.get('/expenses', { params: filters })
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (res.data as any[]).map(toExpense)
}

export const rupees = (n: number) => `₹${Math.round(n).toLocaleString('en-IN')}`

/** ₹4.87 L / ₹1.2 Cr for tiles. */
export function compact(n: number): string {
  if (n >= 1e7) return `₹${(n / 1e7).toLocaleString('en-IN', { maximumFractionDigits: 2 })} Cr`
  if (n >= 1e5) return `₹${(n / 1e5).toLocaleString('en-IN', { maximumFractionDigits: 2 })} L`
  return rupees(n)
}

// PRC-35: pay an expense (or repay who paid it) from an account; the owner, an admin or finance only (SEC-03).
export const MONEY_MANAGERS = ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE']
export const MONEY_MOVERS = [...MONEY_MANAGERS, 'PROJECT_MANAGER']
export const mayManageMoney = (role: string | null | undefined) => MONEY_MANAGERS.includes((role ?? '').toUpperCase())
export const mayMoveMoney = (role: string | null | undefined) => MONEY_MOVERS.includes((role ?? '').toUpperCase())

export interface ExpensePayment {
  id: string
  amount: string
  paid_date: string
  status: 'confirmed' | 'reversed' | 'pending'
  reference: string | null
  account_id: string
  account_name: string
  account_type: string
  recorded_by: string | null
}

export interface ExpensePayments {
  expense_id: string
  amount: string
  paid: string
  left: string
  payment_status: string
  payments: ExpensePayment[]
}

export async function fetchExpensePayments(expenseId: string): Promise<ExpensePayments> {
  return (await api.get(`/expenses/${expenseId}/payments`)).data
}

export async function payExpense(expenseId: string, body: { account_id: string; amount?: string; paid_date?: string; reference?: string }): Promise<ExpensePayments> {
  return (await api.post(`/expenses/${expenseId}/payments`, body)).data
}

export async function undoExpensePayment(expenseId: string, paymentId: string): Promise<ExpensePayments> {
  return (await api.post(`/expenses/${expenseId}/payments/${paymentId}/reverse`)).data
}
