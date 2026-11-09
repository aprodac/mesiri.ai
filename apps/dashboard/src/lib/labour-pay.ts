import { api } from './api'

// Wages, advances, muster roll and labour teams (LW-01..LW-05, docs/plans/wages-and-labour-plan.md). The API is
// backend domains/workforce/pay_router.py; money figures arrive as numbers or strings, read with n().

export const n = (v: unknown): number => Number(v ?? 0) || 0
export const inr = (v: unknown) => `₹${Math.round(n(v)).toLocaleString('en-IN')}`

export interface Deduction {
  reason: string
  amount: string | number
  /** A difference carried from an earlier paid week (the system's line; negative adds to pay). */
  carry_from?: string
}

export interface WagePayment {
  id: string
  row_id: string
  amount: string | number
  paid_on: string
  account_name: string | null
  note: string | null
  source: string
  created_by_name: string | null
}

export interface WageRow {
  id: string
  payee_key: string
  worker_id: string | null
  vendor_id: string | null
  payee_name: string
  trades: string | null
  days: number | string
  man_days: number | string
  unpriced_man_days: number | string
  overtime_hours: number | string
  gross: number | string
  overtime_amount: number | string
  advances_recovered: number | string
  recovery_set: boolean
  deductions: Deduction[]
  net: number | string
  paid: number | string
  due: number | string
  advance_outstanding: number | string
  payments: WagePayment[]
  slip: string
}

export interface WageSheet {
  id: string
  project_id: string
  project_name: string
  site_id: string | null
  site_name: string | null
  period_from: string
  period_to: string
  status: 'draft' | 'approved'
  approved_by_name: string | null
  approved_at: string | null
  rows: WageRow[]
  totals: Record<'man_days' | 'gross' | 'overtime_amount' | 'advances_recovered' | 'net' | 'paid' | 'due' | 'deductions' | 'unpriced_man_days', number | string>
  changed: { payee_key: string; payee_name: string; was: number; now: number; difference: number }[]
}

export interface SheetListItem {
  id: string
  project_id: string
  project_name: string
  site_id: string | null
  site_name: string | null
  period_from: string
  period_to: string
  status: 'draft' | 'approved'
  net: number | string
  paid: number | string
  payees: number
}

export interface Advance {
  id: string
  project_id: string
  project_name: string
  site_id: string | null
  site_name: string | null
  worker_id: string | null
  vendor_id: string | null
  payee_name: string
  amount: number | string
  given_on: string
  account_name: string | null
  note: string | null
  source: string
  created_by_name: string | null
  voided_at: string | null
  void_reason: string | null
}

export interface AdvanceBalance {
  payee_key: string
  payee_name: string
  given: number | string
  recovered: number | string
  outstanding: number | string
  count: number
  last_given_on: string
  worker_id: string | null
  vendor_id: string | null
}

export interface MusterRow {
  key: string
  name: string
  trade: string | null
  team: string | null
  worker_id: string | null
  days: Record<string, { mark: string; count: number | string; ot: number | string }>
  man_days: number | string
  overtime_hours: number | string
}

export interface Muster {
  site_id: string
  project_id: string
  month: string
  days: number
  first: string
  rows: MusterRow[]
  man_days: number | string
}

export interface LabourTeam {
  id: string
  name: string
  phone: string | null
  workers: number
  man_days_30: number | string
}

export interface PaySummary {
  due: number | string
  due_rows: number
  drafts: number
  advances_outstanding: number | string
  advance_payees: number
}

const clean = (p: Record<string, unknown>) => Object.fromEntries(Object.entries(p).filter(([, v]) => v !== null && v !== undefined && v !== ''))

export async function fetchPaySummary(): Promise<PaySummary> {
  return (await api.get('/labour/pay/summary')).data
}
export async function openWageSheet(params: { project_id?: string | null; site_id?: string | null; date?: string }): Promise<WageSheet> {
  return (await api.get('/labour/wage-sheets/open', { params: clean(params) })).data
}
export async function fetchWageSheet(id: string): Promise<WageSheet> {
  return (await api.get(`/labour/wage-sheets/${id}`)).data
}
export async function fetchWageSheets(params: { project_id?: string | null; site_id?: string | null }): Promise<{ items: SheetListItem[] }> {
  return (await api.get('/labour/wage-sheets', { params: clean(params) })).data
}
export async function editWageRow(sheetId: string, rowId: string, body: { advances_recovered?: number; reset_recovery?: boolean; deductions?: Deduction[] }): Promise<WageSheet> {
  return (await api.patch(`/labour/wage-sheets/${sheetId}/rows/${rowId}`, body)).data
}
export async function approveWageSheet(id: string): Promise<WageSheet> {
  return (await api.post(`/labour/wage-sheets/${id}/approve`)).data
}
export async function reopenWageSheet(id: string): Promise<WageSheet> {
  return (await api.post(`/labour/wage-sheets/${id}/reopen`)).data
}
export async function payWages(id: string, body: { row_id?: string; amount?: number; account_id?: string | null; paid_on?: string; note?: string }): Promise<WageSheet> {
  return (await api.post(`/labour/wage-sheets/${id}/pay`, clean(body))).data
}
export async function fetchAdvances(params: { project_id?: string | null; site_id?: string | null }): Promise<{ items: Advance[] }> {
  return (await api.get('/labour/advances', { params: clean(params) })).data
}
export async function fetchAdvanceBalances(projectId?: string | null): Promise<{ items: AdvanceBalance[]; outstanding: number | string }> {
  return (await api.get('/labour/advances/balances', { params: clean({ project_id: projectId }) })).data
}
export async function giveAdvance(body: {
  project_id?: string | null
  site_id?: string | null
  worker_id?: string | null
  vendor_id?: string | null
  payee_name?: string | null
  amount: number
  given_on?: string
  account_id?: string | null
  note?: string
}): Promise<Advance> {
  return (await api.post('/labour/advances', clean(body))).data
}
export async function voidAdvance(id: string, reason?: string): Promise<Advance> {
  return (await api.post(`/labour/advances/${id}/void`, { reason })).data
}
export async function fetchMuster(siteId: string, month: string): Promise<Muster> {
  return (await api.get('/labour/muster', { params: { site_id: siteId, month } })).data
}
export async function fetchLabourTeams(): Promise<{ items: LabourTeam[] }> {
  return (await api.get('/labour/teams')).data
}
export async function createLabourTeam(body: { name: string; phone?: string }): Promise<{ id: string; name: string }> {
  return (await api.post('/finance/vendors', { ...clean(body), kind: 'labour' })).data
}

/** dd Mon – dd Mon, for a pay week. */
export function periodLabel(from: string, to: string): string {
  const f = new Date(`${from}T00:00:00`)
  const t = new Date(`${to}T00:00:00`)
  const day = (d: Date) => d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
  return `${day(f)} – ${day(t)}`
}

/** Shift an ISO date by whole days. */
export function shiftDate(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00`)
  d.setDate(d.getDate() + days)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** A WhatsApp link that opens a chat with the slip text (no number: the person picks the chat). */
export function slipLink(text: string, phone?: string | null): string {
  const to = (phone || '').replace(/[^\d]/g, '')
  return `https://wa.me/${to}?text=${encodeURIComponent(text)}`
}

// LW-01: the register fields shared by adding and editing a worker (components/workforce/register-fields.tsx).
export type RegisterValue = { phone: string; vendorId: string; siteId: string }

export const emptyRegister = (w?: { phone?: string | null; vendor_id?: string | null; site_id?: string | null } | null): RegisterValue => ({
  phone: w?.phone ?? '',
  vendorId: w?.vendor_id ?? '',
  siteId: w?.site_id ?? '',
})

export function registerPayload(v: RegisterValue) {
  return { phone: v.phone.trim() || null, vendor_id: v.vendorId || null, site_id: v.siteId || null }
}
