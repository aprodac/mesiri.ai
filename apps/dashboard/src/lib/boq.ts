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
  /** CC-04: budget earned by the work done; null when no priced line has work. */
  earned?: string | null
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
  // CC-04: work done against the line, in its own unit, and the budget it earned.
  done_quantity: string
  remaining_quantity: string
  percent_done: string | null
  over_planned: boolean
  earned_labour: string | null
  earned_material: string | null
  earned_subcontract: string | null
  earned: string | null
  /** Work put on the line in another unit: never added in, said instead. */
  done_in_other_unit: number
  /** MP-01: what one unit of the line uses (in each material's stock unit). */
  materials: BoqNorm[]
}

export interface BoqNorm {
  material_id: string
  material: string
  unit: string
  quantity_per_unit: string
  wastage_pct: string
  note: string | null
}

export interface NormInput {
  material_id: string
  quantity_per_unit: string
  wastage_pct?: string
  note?: string | null
}

/** A recorded work quantity (a site's work update) and the BOQ line it is counted on. */
export interface BoqWork {
  id: string
  date: string
  site_id: string | null
  site_name: string | null
  work: string | null
  quantity: string
  unit: string
  line_id: string | null
  on_work_order: boolean
  /** Offered for a person to confirm; never saved by itself. */
  suggested_line_id: string | null
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

export async function fetchBoqWork(projectId: string, unlinked = true): Promise<BoqWork[]> {
  return (await api.get<{ work: BoqWork[] }>(`${base(projectId)}/work`, { params: { unlinked } })).data.work
}

/** Count a work quantity on a BOQ line, or take it off (null). */
export async function putWorkOnLine(projectId: string, quantityId: string, lineId: string | null) {
  await api.put(`${base(projectId)}/work/${quantityId}`, { line_id: lineId })
}

/** MP-01: the line's materials become exactly these (an empty list clears them). */
export async function putLineNorms(projectId: string, lineId: string, norms: NormInput[]): Promise<BoqNorm[]> {
  return (await api.put<{ materials: BoqNorm[] }>(`${base(projectId)}/lines/${lineId}/norms`, { norms })).data.materials
}

/** MP-01: the same norms onto the project's other lines of the same work and unit. */
export async function copyLineNorms(projectId: string, lineId: string, overwrite = false) {
  return (await api.post<{ copied_to: string[]; kept: string[] }>(`${base(projectId)}/lines/${lineId}/norms/copy`, { overwrite })).data
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
