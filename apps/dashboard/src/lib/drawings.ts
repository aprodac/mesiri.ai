import { api } from './api'

// DR-01..04: the drawing reader. Backend: domains/drawings (router.py, read.py). Nothing is stored.

export interface DrawingRoom {
  label: string
  a: number
  b: number
  size_text: string
  area: { value: number; unit: 'sqft' | 'sqm'; text: string } | null
  computed: { sqm: number; sqft: number }
  x: number
  top: number
}

export interface DrawingSheet {
  page: number
  has_text: boolean
  title: string | null
  kind: 'plan' | 'elevation' | 'section' | 'schedule' | 'detail' | 'site_plan' | null
  level: string | null
  discipline: string | null
  project: string | null
  client: string | null
  architect: string | null
  number: string | null
  revision: string | null
  drawn_by: string | null
  checked_by: string | null
  scale: string | null
  date: string | null
  units: string | null
  levels: { value: number; text: string }[]
  rooms: DrawingRoom[]
  fixtures: Record<string, number>
}

export interface DrawingCheck {
  kind: 'area_label' | 'level' | 'typical_floor' | 'missing' | 'no_text'
  severity: 'high' | 'medium' | 'low' | 'info'
  page: number | null
  sheet: string | null
  message: string
  why: string
}

export interface DrawingRead {
  file_name: string | null
  pages: number
  project: string | null
  client: string | null
  architect: string | null
  units: string | null
  sheets: DrawingSheet[]
  levels: { value: number; pages: number[] }[]
  floors: string[]
  fixtures: Record<string, number>
  checks: DrawingCheck[]
  /** DR-09: a structural set's schedules and the foundation's quantities (null for other sets). */
  structure?: StructureTakeoff | null
}

export interface StructureTakeoff {
  notes: { concrete?: string; steel?: string; sbc_t_per_sqm?: number; designed_for?: string }
  foundation: { footings: number; concrete_cum: number; concrete_grade: string; pcc_cum: number; pcc_mix: string; steel_kg: number; steel_by_dia: Record<string, number>; cement_bags: number }
  footings: { mark: string; count: number; columns: string[]; size?: string; depth_cm?: number; concrete_cum?: number; pcc_cum?: number; steel_kg?: number; bars?: string; basis: string; combined?: boolean }[]
  columns: { mark: string; size: string | null; bars: string | null; ties: string | null; kg_per_m: number; count_on_plan: number }[]
  columns_kg_per_m: number
  slabs: { floor: string | null; page: number; mark: string; kind: string; thickness_cm: number; steel_kg_per_sqm: number; basis: string }[]
  assumptions: string[]
  plan_page: number | null
}

export async function readDrawing(file: File): Promise<DrawingReadWithDrafts> {
  const res = await api.post<DrawingReadWithDrafts>('/drawings/read', file, {
    headers: { 'Content-Type': 'application/pdf', 'X-File-Name': encodeURIComponent(file.name) },
    timeout: 120_000,
  })
  return res.data
}

// DR-05 / DR-06: the drafts in a read result, and adding them to a project (never overwrites).
export interface DraftActivity { name: string; days: number }
export interface DraftBoqLine { work: string; unit: string; quantity: number; basis: string }
export interface DraftBoq { clear_height_m: number; height_note: string; sections: { name: string; page: number; lines: DraftBoqLine[]; area_sqm: number; warning: string | null }[] }

export interface DrawingReadWithDrafts extends DrawingRead {
  draft_schedule: DraftActivity[]
  draft_boq: DraftBoq
}

export async function addDraftSchedule(projectId: string, start: string, activities: DraftActivity[]) {
  return (await api.post<{ added: string[]; skipped: string[] }>(`/projects/${projectId}/schedule/from-drawing`, { start, activities })).data
}

export async function addDraftBoq(projectId: string, sections: { name: string; lines: { work: string; unit: string; quantity: number }[] }[]) {
  return (await api.post<{ added: number; skipped: number }>(`/projects/${projectId}/boq/from-drawing`, { sections })).data
}
