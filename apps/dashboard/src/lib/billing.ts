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
