import { api } from './api'

// NXT-01 / NXT-02: client billing. Backend: domains/billing/router.py. Money arrives as exact strings.
// Who: owner, admin, finance (D-N3 default, backend may_manage_money).

export interface Client {
  id: string
  name: string
  contact_person: string | null
  phone: string | null
  email: string | null
  gstin: string | null
  address: string | null
  notes: string | null
  projects?: { id: string; name: string; contract_value: string | null }[]
}

export type ClientInput = Partial<Omit<Client, 'id' | 'projects'>>

export interface Contract {
  client_id: string | null
  client_name: string | null
  contract_no: string | null
  contract_value: string | null
  signed_on: string | null
  retention_pct: string | null
  mobilisation_advance: string | null
  advance_recovery_pct: string | null
  gst_pct: string | null
  tds_pct: string | null
  defect_liability_months: number | null
  payment_terms: string | null
  notes: string | null
}

export type ContractInput = Partial<Omit<Contract, 'client_name'>> & { new_client?: ClientInput | null }

export const BILLING_ROLES = ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE']
export const mayBill = (role: string | null | undefined) => BILLING_ROLES.includes(String(role ?? '').toUpperCase())

export async function fetchClients(): Promise<Client[]> {
  return (await api.get<Client[]>('/billing/clients')).data
}

export async function createClient(body: ClientInput): Promise<Client> {
  return (await api.post<Client>('/billing/clients', body)).data
}

export async function updateClient(id: string, body: ClientInput): Promise<Client> {
  return (await api.patch<Client>(`/billing/clients/${id}`, body)).data
}

export async function fetchContract(projectId: string): Promise<{ project: { id: string; name: string }; contract: Contract | null }> {
  return (await api.get(`/projects/${projectId}/contract`)).data
}

export async function putContract(projectId: string, body: ContractInput) {
  return (await api.put<{ project: { id: string; name: string }; contract: Contract }>(`/projects/${projectId}/contract`, body)).data
}

/** ₹ in Indian grouping; a dash when not set (not set is not zero). */
export function rupees(value: string | number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || value === '') return '—'
  const n = Number(value)
  if (Number.isNaN(n)) return '—'
  const s = `₹${Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: digits, minimumFractionDigits: digits })}`
  return n < 0 ? `−${s}` : s
}

// NXT-02: RA bills.
export type BillStatus = 'draft' | 'submitted' | 'certified' | 'cancelled'

export interface RaBillLine {
  id: string
  planned_item_id: string
  boq_code: string | null
  work: string
  unit: string
  client_rate: string
  measured_to_date: string
  previous_quantity: string
  suggested_quantity: string
  quantity: string
  amount: string
  upto_date: string
  /** The office changed the quantity from the measured one. */
  edited: boolean
}

export interface RaBill {
  id: string
  ref: string
  project_id: string
  project_name: string
  number: number
  status: BillStatus
  bill_date: string
  period_to: string | null
  client_id: string | null
  client_name: string | null
  client_gstin?: string | null
  client_address?: string | null
  contract_no?: string | null
  contract_value?: string | null
  retention_pct: string
  advance_recovery_pct: string
  gst_pct: string
  tds_pct: string
  gross: string | null
  retention: string | null
  advance_recovery: string | null
  gst: string | null
  tds: string | null
  net: string | null
  certified_amount: string | null
  certified_on: string | null
  notes: string | null
  submitted_at: string | null
  previous_billed?: string
  /** What the bill can't show by itself: unpriced work, work in another unit, billed more than measured. */
  warnings?: { kind: 'unpriced' | 'other_unit' | 'overbilled'; work: string; message: string }[]
  lines?: RaBillLine[]
}

export const BILL_STATUS: Record<BillStatus, { label: string; tone: string }> = {
  draft: { label: 'Draft', tone: 'bg-draft-soft text-draft' },
  submitted: { label: 'Submitted', tone: 'bg-info-soft text-info' },
  certified: { label: 'Certified', tone: 'bg-success-soft text-success' },
  cancelled: { label: 'Withdrawn', tone: 'bg-muted text-muted-foreground' },
}

export async function fetchRaBills(projectId?: string | null): Promise<RaBill[]> {
  return (await api.get<RaBill[]>('/billing/ra-bills', { params: { project_id: projectId || undefined } })).data
}

export async function fetchRaBill(id: string): Promise<RaBill> {
  return (await api.get<RaBill>(`/billing/ra-bills/${id}`)).data
}

export async function createRaBill(projectId: string, body: { bill_date?: string; period_to?: string } = {}): Promise<RaBill> {
  return (await api.post<RaBill>(`/projects/${projectId}/ra-bills`, body)).data
}

export async function updateRaBill(id: string, body: { bill_date?: string; period_to?: string | null; notes?: string | null }): Promise<RaBill> {
  return (await api.patch<RaBill>(`/billing/ra-bills/${id}`, body)).data
}

export async function setRaBillQuantity(id: string, lineId: string, quantity: string): Promise<RaBill> {
  return (await api.put<RaBill>(`/billing/ra-bills/${id}/lines/${lineId}`, { quantity })).data
}

export async function raBillAction(id: string, action: 'submit' | 'cancel'): Promise<RaBill> {
  return (await api.post<RaBill>(`/billing/ra-bills/${id}/${action}`)).data
}

export async function certifyRaBill(id: string, body: { certified_amount: string; certified_on?: string }): Promise<RaBill> {
  return (await api.post<RaBill>(`/billing/ra-bills/${id}/certify`, body)).data
}

export async function deleteRaBill(id: string) {
  await api.delete(`/billing/ra-bills/${id}`)
}

export function qty(v: string | number): string {
  return Number(v).toLocaleString('en-IN', { maximumFractionDigits: 3 })
}

export function billDay(d: string | null | undefined): string {
  if (!d) return '—'
  return new Date(`${d.slice(0, 10)}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
}
