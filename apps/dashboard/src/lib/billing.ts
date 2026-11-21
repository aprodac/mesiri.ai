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
  /** FB-01: measured (bills from the BOQ's measured work) or lump_sum (bills from the payment stages reached). */
  contract_type: ContractType
}

export type ContractType = 'measured' | 'lump_sum'

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
  /** The BOQ line billed; empty on a lump-sum bill's stage line (FB-01). */
  planned_item_id: string | null
  payment_stage_id?: string | null
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

/** WEB-91 / UX-60: measured work on no client bill yet, at the client rate (before retention and GST), per project. */
export interface ToBill {
  amount: string
  projects: { project_id: string; project: string; lines: number; amount: string }[]
}
export async function fetchToBill(): Promise<ToBill> {
  return (await api.get<ToBill>('/billing/to-bill')).data
}

// FB-01: payment stages. The client's payment schedule, each stage reached when its schedule activity is done.
export interface PaymentStage {
  id: string
  project_id: string
  name: string
  amount: string
  work_package_id: string | null
  activity_name: string | null
  reached: boolean
  reached_on: string | null
  /** Covered by the money received so far (stages in the order they were reached). */
  paid: boolean
  bill_ref: string | null
  sort_order: number
  notes: string | null
}

export interface StageRef { id: string; name: string; reached_on: string }

export interface PaymentStages {
  project: { id: string; name: string }
  contract_type: ContractType | null
  stages: PaymentStage[]
  total: string
  due: string
  received: string
  short: string
  behind_since: StageRef | null
  latest_reached: StageRef | null
}

export interface PaymentAlert {
  project_id: string
  project: string
  due: string
  received: string
  short: string
  behind_since: StageRef | null
  latest_reached: StageRef | null
}

export type StageInput = Partial<Pick<PaymentStage, 'name' | 'amount' | 'work_package_id' | 'reached_on' | 'notes' | 'sort_order'>>

export async function fetchPaymentStages(projectId: string): Promise<PaymentStages> {
  return (await api.get<PaymentStages>(`/projects/${projectId}/payment-stages`)).data
}

export async function createPaymentStage(projectId: string, body: StageInput): Promise<PaymentStage> {
  return (await api.post<PaymentStage>(`/projects/${projectId}/payment-stages`, body)).data
}

export async function updatePaymentStage(id: string, body: StageInput): Promise<PaymentStage> {
  return (await api.patch<PaymentStage>(`/billing/payment-stages/${id}`, body)).data
}

export async function deletePaymentStage(id: string): Promise<void> {
  await api.delete(`/billing/payment-stages/${id}`)
}

export async function fetchPaymentAlerts(projectId?: string | null): Promise<{ short: string; projects: PaymentAlert[] }> {
  return (await api.get('/billing/payment-alerts', { params: { project_id: projectId || undefined } })).data
}
