import { api } from './api'

// A project's Bill of Quantities (CC-02). Backend: domains/progress/boq_router.py.
// Money arrives as strings (Decimal); a missing rate is null, meaning "not priced", never ₹0.

export interface BoqTotals {
  line_count: number
  contract_value: string | null
  budget_cost: string | null
  margin: string | null
  lines_without_client_rate: number
  lines_without_budget_rate: number
}

export interface BoqLine {
  id: string
  section_id: string
  boq_code: string | null
  work: string
  unit: string
  unit_name: string
  planned_quantity: string
  client_rate: string | null
  labour_rate: string | null
  material_rate: string | null
  subcontract_rate: string | null
  budget_rate: string | null
  contract_value: string | null
  budget_cost: string | null
  margin: string | null
  revision_no: number
  sort_order: number
}

export interface BoqSection {
  id: string
  project_id: string
  site_id: string | null
  code: string | null
  name: string
  sort_order: number
  lines: BoqLine[]
  totals: BoqTotals
}

export interface Boq {
  project_id: string
  sections: BoqSection[]
  totals: BoqTotals
}

export interface LineInput {
  work: string
  unit: string
  planned_quantity: string
  boq_code?: string | null
  client_rate?: string | null
  labour_rate?: string | null
  material_rate?: string | null
  subcontract_rate?: string | null
  revision_reason?: string | null
}

// Mirrors backend mesiri/authorization/roles.py EXPENSE_VIEW_ROLES: the BOQ carries rates and margins.
export const BOQ_ROLES = ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE', 'PROJECT_MANAGER']
export const maySeeBoq = (role: string | null | undefined) => BOQ_ROLES.includes(String(role ?? '').toUpperCase())

const base = (projectId: string) => `/projects/${projectId}/boq`

export async function fetchBoq(projectId: string): Promise<Boq> {
  return (await api.get<Boq>(base(projectId))).data
}

export async function createSection(projectId: string, body: { name: string; code?: string | null }) {
  return (await api.post(`${base(projectId)}/sections`, body)).data
}

export async function updateSection(projectId: string, sectionId: string, body: { name?: string; code?: string | null }) {
  return (await api.patch(`${base(projectId)}/sections/${sectionId}`, body)).data
}

export async function deleteSection(projectId: string, sectionId: string) {
  await api.delete(`${base(projectId)}/sections/${sectionId}`)
}

export async function createLine(projectId: string, sectionId: string, body: LineInput): Promise<BoqLine> {
  return (await api.post<BoqLine>(`${base(projectId)}/sections/${sectionId}/lines`, body)).data
}

export async function updateLine(projectId: string, lineId: string, body: Partial<LineInput>): Promise<BoqLine> {
  return (await api.patch<BoqLine>(`${base(projectId)}/lines/${lineId}`, body)).data
}

export async function deleteLine(projectId: string, lineId: string) {
  await api.delete(`${base(projectId)}/lines/${lineId}`)
}

/** "18,000" for a quantity; trailing zeros of the 3 decimals dropped. */
export function formatQuantity(value: string): string {
  const n = Number(value)
  return Number.isNaN(n) ? value : n.toLocaleString('en-IN', { maximumFractionDigits: 3 })
}

/** ₹ amount, or a dash where the rate was never given (not priced is not zero). */
export function formatRupees(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const n = Number(value)
  if (Number.isNaN(n)) return '—'
  const amount = `₹${Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
  return n < 0 ? `−${amount}` : amount
}
