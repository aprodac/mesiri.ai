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
  /** ACC-12: entered by hand (not posted from a record), who entered it, and its reversal link either way. */
  manual?: boolean
  created_by_name?: string | null
  reverses_id?: string | null
  reversed_by_id?: string | null
  reversal_reason?: string | null
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

// --- ACC-12: manual vouchers -------------------------------------------------------------------------------------------

export type ManualType = 'journal' | 'contra'

export interface VoucherLedger { id: string; name: string; group: string; nature: string; code: string | null; contra: boolean }

export interface VoucherLineIn { ledger_id: string; debit: string; credit: string; project_id?: string | null; site_id?: string | null; cost_centre?: string | null }

export interface VoucherIn { date: string; voucher_type: ManualType; narration: string; lines: VoucherLineIn[] }

export async function fetchVoucherLedgers(): Promise<{ ledgers: VoucherLedger[]; cost_centres: string[] }> {
  return (await api.get('/accounts/vouchers/ledgers')).data
}

export async function postVoucher(body: VoucherIn): Promise<Entry> {
  return (await api.post('/accounts/vouchers', body)).data
}

export async function reverseVoucher(id: string, reason: string): Promise<Entry> {
  return (await api.post(`/accounts/entries/${id}/reverse`, { reason })).data
}

export async function correctVoucher(id: string, reason: string, voucher: VoucherIn): Promise<Entry & { reversal_id: string }> {
  return (await api.post(`/accounts/entries/${id}/correct`, { reason, voucher })).data
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

// --- Phase B: statements (ACC-06..09, ACC-22, ACC-23) -------------------------------------------------------

export interface PlLedger {
  ledger_id: string
  name: string
  amount: string
  prior: string | null
  is_overheads: boolean
}
export interface PlGroup {
  group_id: string | null
  name: string
  amount: string
  prior: string | null
  ledgers: PlLedger[]
}
export interface PlTotals {
  income: string
  direct: string
  gross_profit: string
  other_income: string
  indirect: string
  net_profit: string
  gross_margin: string | null
  net_margin: string | null
}
export interface ProfitLoss {
  sections: { income: PlGroup[]; direct: PlGroup[]; other_income: PlGroup[]; indirect: PlGroup[] }
  totals: PlTotals
  prior_totals: PlTotals | null
  overheads: string
  net_before_overheads: string
  compare: { kind: string; date_from: string; date_to: string } | null
}
export type Compare = '' | 'previous' | 'last_year'

export async function fetchPl(period: Partial<Period>, scope: Scope, compare: Compare): Promise<ProfitLoss & Period & { scope: string }> {
  return (await api.get('/accounts/pl', { params: clean({ ...period, ...scope, compare }) })).data
}

export interface BsSub {
  group_id: string | null
  name: string
  amount: string
  ledgers: { ledger_id: string; name: string; amount: string }[]
}
export interface BsGroup {
  group_id: string
  name: string
  code: string | null
  nature: Nature
  amount: string
  subgroups: BsSub[]
}
export interface BalanceSheet {
  as_of: string
  year_start: string
  liabilities: BsGroup[]
  assets: BsGroup[]
  total_assets: string
  total_liabilities: string
  balanced: boolean
  year_profit: string
  earlier_profit: string
}
export async function fetchBalanceSheet(asOf?: string): Promise<BalanceSheet> {
  return (await api.get('/accounts/balance-sheet', { params: clean({ as_of: asOf }) })).data
}

export interface CashAccount {
  ledger_id: string
  name: string
  account_id: string
  group: string
  opening: string
  in: string
  out: string
  closing: string
  lines: number
}
export interface CashBank extends Period {
  scope: string
  accounts: CashAccount[]
  days: { date: string; in: string; out: string }[]
  total: { opening: string; in: string; out: string; closing: string }
}
export async function fetchCashBank(period: Partial<Period>, scope: Scope): Promise<CashBank> {
  return (await api.get('/accounts/cash-bank', { params: clean({ ...period, ...scope }) })).data
}

export interface ProjectRow {
  project_id: string
  name: string
  billed: string
  cost: string
  overheads: string
  profit: string
  margin: string | null
  receivable: string
  payable: string
}
export interface OverheadSettings {
  overhead_basis: 'cost' | 'billing' | null
  head_office_project_id: string | null
  head_office_project: string | null
}
export async function fetchProjectsBooks(period: Partial<Period>): Promise<Period & OverheadSettings & { projects: ProjectRow[]; total: Omit<ProjectRow, 'project_id' | 'name'> }> {
  return (await api.get('/accounts/projects', { params: clean(period) })).data
}

export interface Position {
  as_of: string
  billed: string
  gst_billed: string
  receivable: string
  retention_held_by_client: string
  tds_deducted_by_client: string
  advance_received: string
  received: string
  paid_out: string
  owed_to_suppliers: string
  owed_to_staff: string
  cost: string
  overheads: string
  profit: string
  margin: string | null
  cash_in_hand: string
}
export interface MonthFigure {
  month: string
  income: string
  cost: string
  profit: string
}
export interface ProjectBooks extends Period {
  scope: string
  project_id: string
  pl: ProfitLoss
  centres: { cost_centre: string; amount: string }[]
  position: Position
  months: MonthFigure[]
  budget: { budget: string | null; forecast: string | null; spent: string; kinds: { label: string; budget: string | null; actual: string | null; forecast: string | null }[] } | null
}
export async function fetchProjectBooks(projectId: string, period: Partial<Period>): Promise<ProjectBooks> {
  return (await api.get(`/accounts/projects/${projectId}`, { params: clean(period) })).data
}

export interface Home {
  today: string
  financial_year: string
  scope: string
  this_month: PlTotals & Period
  last_month: PlTotals & Period
  year: PlTotals & Period
  months: MonthFigure[]
  projects: ProjectRow[]
  cash_bank?: { accounts: CashAccount[]; total: string }
  receivable?: string
  payable?: string
  gst_this_month?: { output: string; input: string; payable: string }
  tds_to_deposit?: string
  attention?: { key: string; words: string; amount: string | null; ledger_id: string | null; to: string }[]
  position?: Position
}
export async function fetchHome(projectId?: string): Promise<Home> {
  return (await api.get('/accounts/home', { params: clean({ project_id: projectId }) })).data
}

export async function fetchOverheads(): Promise<OverheadSettings> {
  return (await api.get('/accounts/settings')).data
}
export async function saveOverheads(body: { overhead_basis: 'cost' | 'billing' | null; head_office_project_id: string | null }) {
  return (await api.put('/accounts/settings', body)).data
}

/** Who may open a project's books (D-ACC6): the money roles, and a project's manager. */
export const mayReadProjectBooks = (role: string | null | undefined) =>
  mayReadBooks(role) || String(role ?? '').toUpperCase() === 'PROJECT_MANAGER'

/** ₹12.4 L / ₹1.2 cr: a figure short enough for a chart label or a tile. */
export function short(v: string | number): string {
  const n = Number(v)
  const a = Math.abs(n)
  const sign = n < 0 ? '−' : ''
  if (a >= 1e7) return `${sign}₹${(a / 1e7).toFixed(a >= 1e8 ? 0 : 1)} cr`
  if (a >= 1e5) return `${sign}₹${(a / 1e5).toFixed(a >= 1e6 ? 0 : 1)} L`
  if (a >= 1e3) return `${sign}₹${(a / 1e3).toFixed(0)}k`
  return `${sign}₹${a.toFixed(0)}`
}

/** Change against a prior figure, as a percentage (null when there is nothing to compare). */
export function change(now: string | number, before: string | number | null | undefined): number | null {
  const b = Number(before ?? 0)
  if (!b) return null
  return ((Number(now) - b) / Math.abs(b)) * 100
}

// --- Phase C: GST and TDS (ACC-10, ACC-11) ------------------------------------------------------------------

export interface TaxSplit {
  igst: string
  cgst: string
  sgst: string
  unknown: string
}
export interface GstSale extends TaxSplit {
  id: string
  ref: string
  date: string
  client: string | null
  gstin: string | null
  project: string
  rate: string | null
  taxable: string
  gst: string
}
export interface GstPurchase extends TaxSplit {
  id: string
  number: string | null
  date: string
  supplier: string | null
  gstin: string | null
  project: string | null
  category: string | null
  rate: string | null
  taxable: string
  gst: string
  claimable: boolean
  reason: 'no_gstin' | 'not_included' | 'tax_not_below_amount' | null
}
export interface Gst extends Period {
  company_gstin: string | null
  company_state: string | null
  sales: GstSale[]
  purchases: GstPurchase[]
  output: TaxSplit & { taxable: string; gst: string }
  input: TaxSplit & { taxable: string; gst: string }
  payable: string
  missed: string
  months: { month: string; output: string; input: string; missed: string; payable: string }[]
  by_supplier: { supplier: string; gstin: string | null; bills: number; taxable: string; gst: string; claimable: string }[]
  warnings: { key: string; count: number; amount: string; words: string }[]
  tie: { output_books: string; input_books: string; agrees: boolean }
}
export async function fetchGst(period: Partial<Period>): Promise<Gst> {
  return (await api.get('/accounts/gst', { params: clean(period) })).data
}

export interface Tds extends Period {
  today: string
  deducted: { id: string; date: string; party: string | null; pan: string | null; section: string; bill: string | null; reference: string | null; bill_amount: string; amount: string; project: string | null }[]
  deposits: { id: string; date: string; amount: string; from: string | null; words: string | null }[]
  months: { month: string; deducted: string; deposited: string; left: string; due: string; status: 'deposited' | 'due' | 'overdue' }[]
  by_party: { party: string; pan: string | null; bills: number; bill_amount: string; amount: string }[]
  to_deposit: string
  overdue: string
  next_due: string | null
  by_clients: { id: string; ref: string; date: string; client: string | null; pan: string | null; project: string; gross: string; rate: string | null; amount: string }[]
  by_clients_total: string
  missing_pan: string[]
}
export async function fetchTds(period: Partial<Period>): Promise<Tds> {
  return (await api.get('/accounts/tds', { params: clean(period) })).data
}
