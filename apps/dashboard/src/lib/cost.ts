import { api } from './api'
import type { Boq, BoqLine, BoqSection } from './boq'

// The Cost control module (`cost`, CC-01 / CC-04). Backend: domains/costing/router.py.
// Money arrives as exact strings; a figure that cannot be worked out is null, never ₹0.

export type CentreKey = 'materials' | 'labour' | 'subcontract' | 'equipment' | 'fuel' | 'overhead' | 'other'

export interface CentrePart {
  source: string
  amount: string
  count?: number
  man_days?: string
  category_id?: string | null
}

export interface CostCentres {
  date_from: string
  date_to: string
  total: string
  centres: { key: CentreKey; label: string; amount: string; parts: CentrePart[] }[]
  not_set: { amount: string; parts: CentrePart[] }
  unpriced_deliveries: number
  man_days: string
  priced_man_days: string
}

export interface CostCategory {
  id: string
  name: string
  code: string | null
  status: string
  cost_centre: CentreKey | null
}

export interface BudgetKind {
  kind: 'labour' | 'material' | 'subcontract'
  label: string
  budget: string | null
  earned: string | null
  actual: string
  difference: string | null
  lines_priced: number
  /** CC-18: ordered or agreed and not yet delivered or billed (materials, subcontract); null for labour. */
  committed: string | null
  committed_detail: { unpriced_lines?: number; work_orders?: number } | null
  /** Forecast at completion at the rate so far; null with a basis saying why. */
  forecast: string | null
  /** Budget − forecast: negative is over. */
  forecast_difference: string | null
  forecast_basis: 'rate_so_far' | 'too_early' | 'no_budget'
}

/** CC-05: a BOQ line in Budget vs actual also carries the labour put on it. */
export interface BudgetLine extends BoqLine {
  labour_man_days: string
  /** null: no labour on the line, or none of it has a wage. */
  labour_cost: string | null
  labour_unpriced_man_days: string
  /** Labour earned − labour cost; negative is over. null when either is unknown. */
  labour_difference: string | null
}

export interface ProjectBudget {
  project_id: string
  date_from: string
  date_to: string
  kinds: BudgetKind[]
  other_spending: { key: CentreKey; label: string; amount: string }[]
  not_set: string
  total_spent: string
  work_not_on_a_line: number
  labour_on_lines: { man_days: string; cost: string }
  labour_not_on_a_line: { man_days: string; cost: string; unpriced_man_days: string }
  boq: Omit<Boq, 'sections'> & { sections: (Omit<BoqSection, 'lines'> & { lines: BudgetLine[] })[] }
}

/** CC-05: a site's day of one trade, from attendance, and the BOQ lines it was put on. */
export interface LabourGroup {
  site_id: string | null
  site_name: string | null
  date: string
  trade: string | null
  trade_key: string
  /** What the attendance lines said the people did. */
  activities: string[]
  man_days: string
  cost: string | null
  on_lines: { line_id: string; work: string | null; unit: string | null; man_days: string; cost: string | null }[]
  not_on_a_line: { man_days: string; cost: string | null }
  /** More man-days were put on lines than attendance now counts (the list was re-sent lower). */
  over_allocated: boolean
  suggested_line_id: string | null
}

export interface ProjectLabour {
  project_id: string
  date_from: string
  date_to: string
  total: { man_days: string; cost: string }
  not_on_a_line: { man_days: string; cost: string }
  groups: LabourGroup[]
}

export interface CentreFilters {
  date_from?: string
  date_to?: string
  project_id?: string
  site_id?: string
}

export async function fetchCentres(filters: CentreFilters): Promise<CostCentres> {
  return (await api.get<CostCentres>('/cost/centres', { params: filters })).data
}

export async function fetchCostCategories(): Promise<{ centres: { key: CentreKey; label: string }[]; categories: CostCategory[] }> {
  return (await api.get('/cost/categories')).data
}

export async function setCategoryCentre(categoryId: string, centre: CentreKey | null): Promise<CostCategory> {
  return (await api.patch<CostCategory>(`/cost/categories/${categoryId}`, { cost_centre: centre })).data
}

export async function fetchProjectBudget(projectId: string): Promise<ProjectBudget> {
  return (await api.get<ProjectBudget>(`/cost/projects/${projectId}/budget`)).data
}

export async function fetchProjectLabour(
  projectId: string,
  params: { date_from?: string; date_to?: string; unallocated?: boolean } = {},
): Promise<ProjectLabour> {
  return (await api.get<ProjectLabour>(`/cost/projects/${projectId}/labour`, { params })).data
}

/** Replaces the lines a site's day of one trade is on; an empty list takes it off every line. */
export async function putLabourOnLines(
  projectId: string,
  group: Pick<LabourGroup, 'site_id' | 'date' | 'trade_key'>,
  lines: { line_id: string; man_days: string }[],
): Promise<LabourGroup> {
  return (
    await api.put<LabourGroup>(`/cost/projects/${projectId}/labour`, {
      site_id: group.site_id,
      date: group.date,
      trade: group.trade_key,
      lines,
    })
  ).data
}

/** CC-07: green / amber / red per BOQ line. Grey: cannot be judged (the reason says why), never a colour. */
export type VarianceColour = 'green' | 'amber' | 'red' | 'grey'
export type VarianceReason =
  | 'within_budget'
  | 'near_budget'
  | 'over_budget'
  | 'labour_no_work'
  | 'no_labour'
  | 'no_labour_rate'
  | 'no_wage'

export interface VarianceLine {
  line_id: string
  boq_code: string | null
  work: string
  unit: string
  section: string | null
  done_quantity: string
  labour_man_days: string
  labour_unpriced_man_days: string
  labour_rate: string | null
  earned_labour: string | null
  labour_cost: string | null
  /** Earned − cost: negative is over. */
  difference: string | null
  cost_per_unit: string | null
  ratio: string | null
  colour: VarianceColour
  reason: VarianceReason
}

export interface VarianceSummary {
  earned_labour: string | null
  labour_cost: string | null
  difference: string | null
  ratio: string | null
  colour: VarianceColour
  lines: Record<VarianceColour, number>
}

export interface VarianceDay extends VarianceSummary {
  date: string
  attendance_cost: string
  not_on_a_line_cost: string
}

export interface ProjectVariance {
  project_id: string
  site_id: string | null
  date_from: string
  date_to: string
  thresholds: { green_at: string; amber_at: string }
  summary: VarianceSummary
  labour: { attendance_cost: string; man_days: string; not_on_a_line: { man_days: string; cost: string } }
  materials: { earned: string; bought: string }
  work_in_other_unit: number
  lines: VarianceLine[]
  days: VarianceDay[]
}

export async function fetchProjectVariance(
  projectId: string,
  params: { date_from?: string; date_to?: string; site_id?: string } = {},
): Promise<ProjectVariance> {
  return (await api.get<ProjectVariance>(`/cost/projects/${projectId}/variance`, { params })).data
}

/** CC-19: one row per project with a BOQ, worst forecast first. */
export interface PortfolioRow {
  project_id: string
  name: string
  budget: string | null
  earned: string | null
  spent: string
  committed: string
  percent_done: string | null
  percent_spent: string | null
  forecast: string | null
  forecast_budget: string | null
  forecast_difference: string | null
  forecast_kinds: string[]
  colour: VarianceColour
  week: { colour: VarianceColour; difference: string | null; red_lines: number }
  work_not_on_a_line: number
  labour_not_on_a_line: string
}

export async function fetchPortfolio(): Promise<{ date: string; projects: PortfolioRow[] }> {
  return (await api.get('/cost/portfolio')).data
}

/** CC-08: a material with a norm on a BOQ line, against what the work needed. Quantities in the stock unit. */
export interface MaterialReconciliation {
  material_id: string
  material: string
  unit: string
  stock_unit: string | null
  lines: number
  required_total: string
  should_have_used: string
  received: string
  used: string
  on_hand: string
  on_order: string
  /** Used − what the work done needed: above zero is more than the work accounts for. null when units differ. */
  used_over_work: string | null
  still_needed: string
  /** Needed to finish beyond on hand + on order. null when units differ. */
  short_by: string | null
  ratio: string | null
  colour: VarianceColour
  reason: 'within_norm' | 'near_norm' | 'over_norm' | 'used_no_work' | 'no_usage_recorded' | 'nothing_yet' | 'unit_differs'
}

export interface ProjectMaterials {
  project_id: string
  date: string
  materials: MaterialReconciliation[]
  lines_with_norms: number
  lines_without_norms: number
  summary: Record<VarianceColour, number>
  short_at_completion: number
}

export async function fetchProjectMaterials(projectId: string): Promise<ProjectMaterials> {
  return (await api.get<ProjectMaterials>(`/cost/projects/${projectId}/materials`)).data
}

/** CC-21: Summary, BOQ lines, Green-red (for the period; default the last 7 days) and Materials as one workbook. */
export async function downloadCostExcel(
  projectId: string,
  period?: { date_from: string; date_to: string },
  projectName?: string,
): Promise<{ blob: Blob; filename: string }> {
  const res = await api.get(`/cost/projects/${projectId}/export`, { params: period, responseType: 'blob' })
  // The API's own name when the browser may read it (same origin); else the same name made here, since the
  // dashboard's API host does not expose Content-Disposition to the page.
  const match = /filename="([^"]+)"/.exec(String(res.headers['content-disposition'] ?? ''))
  const slug = (projectName ?? 'project').replace(/[^A-Za-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40) || 'project'
  const day = period?.date_to ?? new Date().toISOString().slice(0, 10)
  return { blob: res.data as Blob, filename: match?.[1] ?? `mesiri-cost-${slug}-${day}.xlsx` }
}

// Mirrors backend MONEY_MANAGE_ROLES: who may change a category's cost centre.
export const mayManageMoney = (role: string | null | undefined) =>
  ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE'].includes(String(role ?? '').toUpperCase())

export const CENTRE_COLOURS: Record<CentreKey | 'not_set', string> = {
  materials: 'bg-emerald-500',
  labour: 'bg-amber-500',
  subcontract: 'bg-violet-500',
  equipment: 'bg-teal-500',
  fuel: 'bg-orange-500',
  overhead: 'bg-sky-500',
  other: 'bg-slate-400',
  not_set: 'bg-muted-foreground/40',
}
