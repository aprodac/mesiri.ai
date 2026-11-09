import { api } from './api'

// ACC-01..05: the company's books (backend domains/accounts). Money comes as exact strings ("1234.50"); a balance is
// signed: positive is a debit (Dr), negative a credit (Cr). Every read posts what changed first, so it is current.

export type Nature = 'asset' | 'liability' | 'equity' | 'income' | 'expense'
export type VoucherType = 'journal' | 'payment' | 'receipt' | 'contra' | 'sales' | 'purchase'
export type LinkKind = 'vendor' | 'client' | 'money_account' | 'expense_category' | 'staff'

export interface LedgerGroup {
  id: string
  parent_id: string | null
  name: string
  nature: Nature
  code: string | null
}

export interface Ledger {
  id: string
  group_id: string
  name: string
  code: string | null
  link_kind: LinkKind | null
  link_id: string | null
  notes: string | null
  purpose: string | null
  is_active: boolean
  nature: Nature
  balance: string
  lines: number
  last_used: string | null
  seeded: boolean
}

export interface Period {
  date_from: string
  date_to: string
}

export interface Scope {
  project_id?: string
  site_id?: string
}

export interface TrialRow {
  ledger_id: string | null
  name: string
  group_id: string
  nature: Nature
  code: string | null
  link_kind: LinkKind | null
  link_id: string | null
  opening: string
  debit: string
  credit: string
  closing: string
}

export interface TrialBalance extends Period {
  scope: string
  financial_year: string
  groups: LedgerGroup[]
  rows: TrialRow[]
  totals: {
    opening_debit: string
    opening_credit: string
    debit: string
    credit: string
    closing_debit: string
    closing_credit: string
    balanced: boolean
  }
  posted: { posted: number; reposted: number; removed: number; after_close: number }
}

export interface EntryLine {
  ledger_id: string
  ledger: string
  link_kind: LinkKind | null
  link_id: string | null
  debit: string
  credit: string
  project_id: string | null
  project: string | null
  site_id: string | null
  site: string | null
  cost_centre: string | null
}

export interface EntrySource {
  kind: 'expense' | 'money' | 'ra_bill' | 'opening_account' | 'opening_vendor' | string
  id: string | null
  money_source?: string | null
  expense_id?: string
  vendor_id?: string
  receipt_id?: string
}

export interface Entry {
  id: string
  date: string
  voucher_type: VoucherType
  number: number
  financial_year: string
  ref: string
  narration: string | null
  after_close: boolean
  project: string | null
  project_id: string | null
  source: EntrySource
  amount: string
  lines: EntryLine[]
  posted_at: string
}

export interface DayBook extends Period {
  scope: string
  entries: Entry[]
  count: number
  total: string
  limit: number
  offset: number
}

export interface StatementLine {
  line_id: string
  entry_id: string
  date: string
  ref: string
  voucher_type: VoucherType
  narration: string | null
  against: string | null
  debit: string
  credit: string
  balance: string
  project: string | null
  site: string | null
  cost_centre: string | null
  after_close: boolean
  source_kind: string
}

export interface Statement extends Period {
  scope: string
  ledger: {
    id: string
    name: string
    code: string | null
    link_kind: LinkKind | null
    link_id: string | null
    notes: string | null
    group_id: string
    group_name: string
    nature: Nature
  }
  opening: string
  debit: string
  credit: string
  closing: string
  lines: StatementLine[]
  year_start: string | null
}

export interface CheckRow {
  id: string | null
  name: string
  module: string
  books: string
  difference: string
}

export interface Checks {
  as_of: string
  accounts: { rows: CheckRow[]; agree: number; differ: number }
  suppliers: { rows: CheckRow[]; agree: number; differ: number }
  clients: { rows: CheckRow[]; agree: number; differ: number }
}

export interface Month {
  id: string
  month: string
  starts_on: string
  ends_on: string
  status: 'open' | 'closed'
  closed_at: string | null
  closed_by: string | null
  reopened_at: string | null
  reopened_by: string | null
  reopen_reason: string | null
  entries: number
  changed_after_close: number
  financial_year: string
  is_current: boolean
}

export const VOUCHER_LABEL: Record<VoucherType, string> = {
  purchase: 'Purchase',
  payment: 'Payment',
  receipt: 'Receipt',
  sales: 'Sales',
  contra: 'Contra',
  journal: 'Journal',
}

export const NATURE_LABEL: Record<Nature, string> = {
  asset: 'Assets',
  liability: 'Liabilities',
  equity: 'Capital',
  income: 'Income',
  expense: 'Expenses',
}

export const LINK_LABEL: Record<LinkKind, string> = {
  vendor: 'Supplier',
  client: 'Client',
  money_account: 'Money account',
  expense_category: 'Expense category',
  staff: 'Staff (own pocket)',
}

// Mirrors backend may_manage_money: the books are the owner's, an admin's and finance's.
export const mayReadBooks = (role: string | null | undefined) =>
  ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE'].includes(String(role ?? '').toUpperCase())
// Reopening a closed month (D-ACC6).
export const mayReopen = (role: string | null | undefined) =>
  ['ADMIN', 'OWNER', 'SUPER_ADMIN'].includes(String(role ?? '').toUpperCase())

const clean = (o: object) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined && v !== '' && v !== null))

export async function fetchChart(): Promise<{ as_of: string; groups: LedgerGroup[]; ledgers: Ledger[] }> {
  return (await api.get('/accounts/chart')).data
}

export async function fetchTrialBalance(period: Partial<Period>, scope: Scope): Promise<TrialBalance> {
  return (await api.get('/accounts/trial-balance', { params: clean({ ...period, ...scope }) })).data
}

export interface DayBookFilter extends Partial<Period>, Scope {
  voucher_type?: VoucherType | ''
  ledger_id?: string
  q?: string
  after_close?: boolean
  limit?: number
  offset?: number
}

export async function fetchDayBook(filter: DayBookFilter): Promise<DayBook> {
  return (await api.get('/accounts/day-book', { params: clean({ ...filter, after_close: filter.after_close || undefined }) })).data
}

export async function fetchEntry(id: string): Promise<Entry> {
  return (await api.get(`/accounts/entries/${id}`)).data
}

export async function fetchStatement(ledgerId: string, period: Partial<Period>, scope: Scope): Promise<Statement> {
  return (await api.get(`/accounts/ledgers/${ledgerId}/statement`, { params: clean({ ...period, ...scope }) })).data
}

export async function fetchChecks(): Promise<Checks> {
  return (await api.get('/accounts/checks')).data
}

export async function fetchMonths(): Promise<{ today: string; financial_year: string; months: Month[] }> {
  return (await api.get('/accounts/periods')).data
}

export async function closeMonth(month: string) {
  return (await api.post(`/accounts/periods/${month}/close`)).data
}

export async function reopenMonth(month: string, reason: string) {
  return (await api.post(`/accounts/periods/${month}/reopen`, { reason })).data
}

export async function addLedger(body: { name: string; group_id: string; notes?: string }) {
  return (await api.post('/accounts/ledgers', body)).data
}

export async function editLedger(id: string, body: { name?: string; group_id?: string; notes?: string; is_active?: boolean }) {
  return (await api.patch(`/accounts/ledgers/${id}`, body)).data
}

export async function addGroup(body: { name: string; parent_id: string }) {
  return (await api.post('/accounts/groups', body)).data
}

export async function renameGroup(id: string, name: string) {
  return (await api.patch(`/accounts/groups/${id}`, { name })).data
}

/** An Excel file of a report; the name is made here (the API host does not expose Content-Disposition). */
export async function downloadAccountsExcel(path: string, params: object, name: string): Promise<{ blob: Blob; filename: string }> {
  const res = await api.get(path, { params: clean(params), responseType: 'blob' })
  return { blob: res.data as Blob, filename: `${name.replace(/[^A-Za-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60) || 'books'}.xlsx` }
}

// --- figures ---------------------------------------------------------------------------------------------------

const INR = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** ₹1,23,456.00 (no sign). */
export function rupees(v: string | number | null | undefined): string {
  const n = Math.abs(Number(v ?? 0))
  return `₹${INR.format(Number.isFinite(n) ? n : 0)}`
}

/** A signed balance as "₹1,234.00 Dr" / "₹1,234.00 Cr", or "—" when nil. */
export function drCr(v: string | number | null | undefined): string {
  const n = Number(v ?? 0)
  if (!n) return '—'
  return `${rupees(n)} ${n > 0 ? 'Dr' : 'Cr'}`
}

/** A debit or credit cell: empty when zero, so the eye finds the figures. */
export function cell(v: string | number | null | undefined): string {
  const n = Number(v ?? 0)
  return n ? rupees(n) : ''
}

/** "This month", "This year" ... as dates (the year runs April to March). */
export type PresetKey = 'this_month' | 'last_month' | 'this_quarter' | 'fy' | 'last_fy' | 'custom'

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

export function presetPeriod(key: Exclude<PresetKey, 'custom'>, today = new Date()): Period {
  const y = today.getFullYear()
  const m = today.getMonth()
  const fyStart = m >= 3 ? y : y - 1
  switch (key) {
    case 'this_month':
      return { date_from: iso(new Date(y, m, 1)), date_to: iso(today) }
    case 'last_month':
      return { date_from: iso(new Date(y, m - 1, 1)), date_to: iso(new Date(y, m, 0)) }
    case 'this_quarter':
      // The year's quarters (Apr–Jun, Jul–Sep, Oct–Dec, Jan–Mar) fall on the calendar's.
      return { date_from: iso(new Date(y, m - (m % 3), 1)), date_to: iso(today) }
    case 'fy':
      return { date_from: iso(new Date(fyStart, 3, 1)), date_to: iso(today) }
    case 'last_fy':
      return { date_from: iso(new Date(fyStart - 1, 3, 1)), date_to: iso(new Date(fyStart, 2, 31)) }
  }
}

export const PRESET_LABEL: Record<PresetKey, string> = {
  this_month: 'This month',
  last_month: 'Last month',
  this_quarter: 'This quarter',
  fy: 'This year',
  last_fy: 'Last year',
  custom: 'Dates',
}

export function formatDay(value: string): string {
  const d = new Date(`${value.slice(0, 10)}T00:00:00`)
  return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
}

/** Where a voucher came from, as a page the dashboard has. */
export function sourceLink(s: EntrySource): { to: string; label: string } | null {
  if (s.kind === 'expense' && s.id) return { to: `/finance/expenses/${s.id}`, label: 'Open the expense' }
  if (s.kind === 'ra_bill' && s.id) return { to: `/billing/ra-bills/${s.id}/document`, label: 'Open the RA bill' }
  if (s.kind === 'opening_vendor' && s.id) return { to: `/finance/vendors/${s.id}`, label: 'Open the supplier' }
  if (s.kind === 'opening_account') return { to: '/finance/money', label: 'Open Money' }
  if (s.kind === 'money') {
    if (s.expense_id) return { to: `/finance/expenses/${s.expense_id}`, label: 'Open the expense it paid' }
    if (s.vendor_id) return { to: `/finance/vendors/${s.vendor_id}`, label: 'Open the supplier' }
    if (s.receipt_id) return { to: '/accounts/receivables', label: 'Open Receivables' }
    return { to: '/finance/money?view=transactions', label: 'Open the money movement' }
  }
  return null
}

/** The module page a linked ledger stands for. */
export function linkedRecord(kind: LinkKind | null, id: string | null): { to: string; label: string } | null {
  if (!kind || !id) return null
  switch (kind) {
    case 'vendor':
      return { to: `/finance/vendors/${id}`, label: 'Supplier page' }
    case 'client':
      return { to: '/accounts/receivables', label: 'Receivables' }
    case 'money_account':
      return { to: '/finance/money', label: 'Money' }
    case 'expense_category':
      return { to: '/finance/settings', label: 'Categories' }
    default:
      return null
  }
}

/** The scope bar's choice as report parameters. */
export function scopeParams(scope: { mode: string; projectId?: string; siteId?: string }): Scope {
  if (scope.mode === 'site') return { project_id: scope.projectId, site_id: scope.siteId }
  if (scope.mode === 'project') return { project_id: scope.projectId }
  return {}
}
