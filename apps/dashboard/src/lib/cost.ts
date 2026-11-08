import { api } from './api'
import type { Boq } from './boq'

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
  boq: Boq
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
