import { api } from './api'

// MP-02: a project's material plan. Backend: domains/materials/plan_router.py (maths in plan.py).
// Quantities arrive as exact strings, in each material's stock unit.

export interface MaterialPlanLine {
  line_id: string
  site_id: string | null
  work: string
  need: string
  start: string | null
  end: string | null
  late: boolean
}

export interface MaterialPlanRow {
  material_id: string
  material: string
  unit: string
  /** What the whole BOQ takes (planned × norm × wastage). */
  required: string
  /** What the work still to do takes. */
  still_needed: string
  /** Of still_needed: lines whose activity has no dates (in no week). */
  unscheduled: string
  /** Of still_needed: after the last week shown. */
  later: string
  weeks: string[]
  on_hand: string
  on_order: string
  /** Stock is held in another unit: not counted, said instead. */
  stock_unit_differs: boolean
  /** Monday of the week it runs short; null when what is held and ordered covers the weeks shown. */
  short_from: string | null
  short_by: string
  /** The day it runs short (short_from is that week's Monday). */
  short_day: string | null
  /** MP-03: who last delivered it, their delivery time (3 days when not set) and the day to order by. */
  supplier: string | null
  supplier_id: string | null
  lead_days: number
  lead_known: boolean
  order_by: string | null
  order_now: boolean
  lines: MaterialPlanLine[]
}

export interface MaterialPlan {
  project_id: string
  today: string
  site_id: string | null
  weeks: string[]
  materials: MaterialPlanRow[]
  lines_with_norms: number
  lines_without_norms: number
}

export async function fetchMaterialPlan(projectId: string, weeks = 8, siteId?: string | null): Promise<MaterialPlan> {
  return (await api.get<MaterialPlan>(`/projects/${projectId}/material-plan`, { params: { weeks, site_id: siteId || undefined } })).data
}
