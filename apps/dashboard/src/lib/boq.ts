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
  /** PS phase 2: the margin of the lines priced both ways ("on 31 of 34 lines"); `margin` needs every line priced. */
  priced_lines?: number
  priced_margin?: string | null
  priced_contract_value?: string | null
  /** PS phase 2 (0564): the project's overheads (% of budget cost) and the margin after them; null when not set. */
  overhead_pct?: string | null
  overhead_cost?: string | null
  margin_after_overheads?: string | null
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
  /** PS phase 2 (0564): machines (mixer, JCB, crane hire) per unit, the fourth budget rate. */
  machinery_rate?: string | null
  /** PS phase 2b (0565): the fifth budget rate (temporary works, testing, small tools), and a provisional sum. */
  other_rate?: string | null
  is_provisional?: boolean
  /** PS phase 2b: the quantity split by site, with each site's work done; empty = the whole project. */
  sites?: { site_id: string; site: string; quantity: string; done: string }[]
  /** PS phase 2b: the line as approved (null = added since); absent when no budget is approved. */
  baseline?: { planned_quantity: string; client_rate: string | null; budget_rate: string | null; budget_cost: string | null; contract_value: string | null } | null
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
  /** Has schedule dates: an empty one is a schedule activity, not a BOQ section waiting for lines. */
  scheduled?: boolean
  lines: BoqLine[]
  totals: BoqTotals
}

export interface Boq {
  project_id: string
  sections: BoqSection[]
  totals: BoqTotals & { gst_pct?: string | null; contract_value_with_gst?: string | null }
  /** PS phase 2b: the project's sites, and the latest approved budget compared with now. */
  sites?: { id: string; name: string }[]
  baseline?: BoqBaseline | null
}

export interface BoqBaseline {
  id: string
  name: string
  note: string | null
  locked_at: string
  locked_by: string | null
  contract_value: string | null
  budget_cost: string | null
  lines_changed: number
  lines_added: number
  lines_removed: number
}

export interface LibraryItem {
  id: string
  work: string
  unit: string
  client_rate: string | null
  labour_rate: string | null
  material_rate: string | null
  subcontract_rate: string | null
  machinery_rate: string | null
  other_rate: string | null
  materials: unknown[]
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
  machinery_rate?: string | null
  other_rate?: string | null
  is_provisional?: boolean
  sites?: { site_id: string; quantity: string }[]
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
/** A table cell's money: ₹21.4 L, ₹1.85 Cr (how owners read it); under a lakh the full figure. Put the full
 *  amount (formatRupees) in the cell's title. */
export function formatRupeesShort(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const n = Number(value)
  if (Number.isNaN(n)) return '—'
  const a = Math.abs(n)
  const sign = n < 0 ? '−' : ''
  const trim = (x: number, d: number) => Number(x.toFixed(d)).toLocaleString('en-IN', { maximumFractionDigits: d })
  if (a >= 1e7) return `${sign}₹${trim(a / 1e7, 2)} Cr`
  if (a >= 1e5) return `${sign}₹${trim(a / 1e5, 1)} L`
  return formatRupees(value)
}

export function formatRupees(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const n = Number(value)
  if (Number.isNaN(n)) return '—'
  // Whole rupees stay whole (₹13,640); an amount with paise always shows two places (₹9,836.80, never ₹9,836.8).
  const whole = Number.isInteger(Math.round(Math.abs(n) * 100) / 100)
  const amount = `₹${Math.abs(n).toLocaleString('en-IN', { minimumFractionDigits: whole ? 0 : 2, maximumFractionDigits: 2 })}`
  return n < 0 ? `−${amount}` : amount
}

/** BOQ-04: the usual materials per unit for a line with none yet, in the company's own materials. */
export interface StandardNormLine {
  line_id: string
  work: string
  unit: string
  /** The assumption, e.g. "M20 / 1:1.5:3 nominal". */
  standard: string
  norms: { material_id: string; material: string; unit: string; quantity_per_unit: string; wastage_pct: string; note: string }[]
  /** Kinds the company has no material for, or buys in a unit that can't be converted. */
  missing: string[]
}

export async function fetchStandardNorms(projectId: string): Promise<StandardNormLine[]> {
  return (await api.get<{ lines: StandardNormLine[] }>(`${base(projectId)}/norms/standard`)).data.lines
}

/** BOQ-04: put them on every line they fit (never a line that has materials). */
export async function applyStandardNorms(projectId: string, lineIds?: string[]): Promise<{ line_id: string }[]> {
  return (await api.post<{ lines: { line_id: string }[] }>(`${base(projectId)}/norms/standard`, { line_ids: lineIds ?? null })).data.lines
}

/** PS phase 2: start this project's BOQ from an earlier project's (sections, lines, rates, materials per unit). */
export interface BoqCopyResult {
  sections_added: number
  lines_added: number
  lines_kept: number
  material_lines: number
}

export async function copyBoqFrom(
  projectId: string,
  body: { source_project_id: string; with_quantities: boolean; with_rates: boolean },
): Promise<BoqCopyResult> {
  return (await api.post<BoqCopyResult>(`${base(projectId)}/copy-from`, body)).data
}

/** PS phase 2b: the BOQ as an .xlsx (for the client; `withCosts` adds our cost split and margin). */
export async function exportBoq(projectId: string, withCosts: boolean): Promise<Blob> {
  return (await api.get(`${base(projectId)}/export`, { params: { with_costs: withCosts }, responseType: 'blob' })).data as Blob
}

/** PS phase 2b: lock the BOQ as it is now as the approved budget. */
export async function approveBudget(projectId: string, body: { name?: string; note?: string }) {
  return (await api.post(`${base(projectId)}/baselines`, body)).data
}

export async function fetchLibrary(projectId: string): Promise<LibraryItem[]> {
  return (await api.get<LibraryItem[]>(`${base(projectId)}/library`)).data
}

export async function saveToLibrary(projectId: string, lineId: string) {
  return (await api.post(`${base(projectId)}/lines/${lineId}/to-library`)).data
}

export async function addFromLibrary(projectId: string, sectionId: string, body: { item_id: string; planned_quantity: string; boq_code?: string | null }) {
  return (await api.post(`${base(projectId)}/sections/${sectionId}/from-library`, body)).data
}

export async function deleteLibraryItem(projectId: string, itemId: string) {
  await api.delete(`${base(projectId)}/library/${itemId}`)
}
