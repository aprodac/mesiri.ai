import { api } from './api'
import { fileBase64 } from './materials'

// ST-01..ST-05: a project's start (stage, dates, checklist), its schedule (Gantt) and the BOQ import.
// Backend: domains/schedule/router.py, domains/progress/boq_import.py. Dates are ISO days ("2026-12-01").

export type ActivityState = 'late' | 'behind' | 'on_track' | 'not_started' | 'done' | 'unscheduled'
export type Stage = 'tender' | 'won' | 'running' | 'handover' | 'defects' | 'closed'

export interface ScheduleLine {
  id: string
  work: string
  unit: string
  boq_code: string | null
  planned_quantity: string
  done_quantity: string
  progress: number | null
}

export interface Activity {
  id: string
  code: string | null
  name: string
  site_id: string | null
  site_name: string | null
  start: string | null
  end: string | null
  milestone: boolean
  done: boolean
  duration: number | null
  actual_start: string | null
  actual_end: string | null
  progress: number | null
  expected: number | null
  state: ActivityState
  days_late: number
  forecast_end: string | null
  slip_days: number
  pushed_days: number
  critical: boolean
  after: { id: string; lag: number }[]
  assigned_to: string | null
  last_update: string | null
  updates: number
  open_issues: number
  work_orders: { id: string; ref: string; vendor: string }[]
  lines: ScheduleLine[]
  sort_order: number
}

export interface ScheduleProject {
  id: string
  name: string
  client: string | null
  stage: Stage
  stage_label: string
  start_date: string | null
  planned_finish: string | null
}

export interface Schedule {
  project: ScheduleProject
  today: string
  activities: Activity[]
  links: { predecessor: string; successor: string; lag: number }[]
  conflicts: { predecessor: string; successor: string; days: number }[]
  summary: {
    activities: number
    scheduled: number
    counts: Partial<Record<ActivityState, number>>
    planned_finish: string | null
    contract_finish: string | null
    forecast_finish: string | null
    slip_days: number
    progress: number | null
    first_start: string | null
    conflicts: number
  }
  can_edit: boolean
}

export interface MovedActivity {
  id: string
  name: string
  from_start: string | null
  from_end: string | null
  start: string
  end: string
  days: number | null
}

export interface ScheduleChange {
  saved: boolean
  focus: string | null
  moved: MovedActivity[]
  finish_moves: number
  schedule: Schedule
}

export interface ActivityUpdate {
  name?: string
  start?: string
  end?: string
  clear_dates?: boolean
  milestone?: boolean
  done?: boolean
  site_id?: string | null
  after?: { id: string; lag: number }[]
  push?: boolean
  preview?: boolean
}

export const STATE_WORDS: Record<ActivityState, string> = {
  late: 'Late',
  behind: 'Behind',
  on_track: 'On track',
  not_started: 'Not started',
  done: 'Done',
  unscheduled: 'No dates',
}

const base = (projectId: string) => `/projects/${projectId}/schedule`

export async function fetchSchedule(projectId: string): Promise<Schedule> {
  return (await api.get<Schedule>(base(projectId))).data
}

export async function updateActivity(projectId: string, id: string, body: ActivityUpdate): Promise<ScheduleChange> {
  return (await api.patch<ScheduleChange>(`${base(projectId)}/activities/${id}`, body)).data
}

export async function createActivity(
  projectId: string,
  body: { name: string; start: string; end?: string; milestone?: boolean; site_id?: string | null; after?: { id: string; lag: number }[] },
): Promise<ScheduleChange> {
  return (await api.post<ScheduleChange>(`${base(projectId)}/activities`, body)).data
}

export async function deleteActivity(projectId: string, id: string): Promise<void> {
  await api.delete(`${base(projectId)}/activities/${id}`)
}

export async function sequenceActivities(
  projectId: string,
  body: { start: string; items: { id: string; days: number }[]; link?: boolean },
): Promise<ScheduleChange> {
  return (await api.post<ScheduleChange>(`${base(projectId)}/sequence`, body)).data
}

// -- project start ----------------------------------------------------------------------------------------------

export interface StartStep {
  key: 'dates' | 'boq' | 'schedule' | 'sites' | 'team' | 'suppliers' | 'work_orders'
  title: string
  done: boolean
  detail: string
  optional?: boolean
}

export interface ProjectStart {
  project: ScheduleProject
  steps: StartStep[]
  next: StartStep['key'] | null
  ready: boolean
  done: number
  total: number
  counts: Record<string, number>
  can_edit: boolean
  stages: { key: Stage; label: string }[]
}

export async function fetchProjectStart(projectId: string): Promise<ProjectStart> {
  return (await api.get<ProjectStart>(`/projects/${projectId}/start`)).data
}

export async function updateProjectStart(
  projectId: string,
  body: { stage?: Stage; start_date?: string; planned_finish?: string },
): Promise<ProjectStart> {
  return (await api.patch<ProjectStart>(`/projects/${projectId}/start`, body)).data
}

export interface ProjectLifecycle extends ScheduleProject {
  scheduled: number
  activities: number
  late: number
  behind: number
  slip_days: number
  forecast_finish: string | null
  progress: number | null
}

export async function fetchLifecycle(): Promise<ProjectLifecycle[]> {
  return (await api.get<ProjectLifecycle[]>('/lifecycle/projects')).data
}

// -- BOQ import ---------------------------------------------------------------------------------------------------

export interface BoqImportReport {
  saved: boolean
  sheet: string
  columns: Record<string, string>
  ignored_columns: string[]
  sections_added: number
  sections_found: number
  lines_added: number
  lines_kept: number
  problems: number
  contract_value: string
  budget_cost: string
  dated_sections: number
  links: number
  sections: { id: string; name: string; lines: number; contract_value: string; start: string | null; finish: string | null }[]
  rows: { row: number; result: 'added' | 'kept' | 'section' | 'problem'; what: string; section: string | null; message: string | null }[]
}

export async function downloadBoqTemplate(projectId: string): Promise<Blob> {
  return (await api.get(`/projects/${projectId}/boq/import/template`, { responseType: 'blob' })).data as Blob
}

export async function previewBoqImport(projectId: string, file: File): Promise<BoqImportReport> {
  return (await api.post<BoqImportReport>(`/projects/${projectId}/boq/import/preview`, { file_base64: await fileBase64(file) })).data
}

export async function runBoqImport(projectId: string, file: File): Promise<BoqImportReport> {
  return (await api.post<BoqImportReport>(`/projects/${projectId}/boq/import`, { file_base64: await fileBase64(file) })).data
}

// -- dates --------------------------------------------------------------------------------------------------------

const DAY_MS = 86_400_000

/** "2026-12-01" as a UTC midnight timestamp: day arithmetic never crosses a DST edge. */
export function dayNum(iso: string): number {
  const [y, m, d] = iso.split('-').map(Number)
  return Date.UTC(y, m - 1, d) / DAY_MS
}

export function isoOf(n: number): string {
  return new Date(n * DAY_MS).toISOString().slice(0, 10)
}

export function addDays(iso: string, days: number): string {
  return isoOf(dayNum(iso) + days)
}

export function daysBetween(a: string, b: string): number {
  return dayNum(b) - dayNum(a)
}

/** "Mon 9 Nov" (with the year when it is not this one). */
export function shortDay(iso: string | null | undefined, today?: string): string {
  if (!iso) return '—'
  const d = new Date(dayNum(iso) * DAY_MS)
  const sameYear = !today || today.slice(0, 4) === iso.slice(0, 4)
  return d.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short', year: sameYear ? undefined : 'numeric', timeZone: 'UTC' })
}

export function plural(n: number, word: string): string {
  if (n === 1) return `${n} ${word}`
  return `${n} ${/[^aeiou]y$/.test(word) ? `${word.slice(0, -1)}ies` : `${word}s`}`
}
