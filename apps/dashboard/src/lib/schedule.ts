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
  after: Link[]
  assigned_to: string | null
  assigned_user_id?: string | null
  /** The approved programme's dates for it (null: added since, or none approved), and how far its end moved. */
  baseline?: { start: string | null; end: string | null } | null
  baseline_slip_days?: number | null
  /** Its share of the BOQ's contract value (0..1), for the people who see money: Quick plan spreads days by it. */
  weight?: number | null
  last_update: string | null
  updates: number
  open_issues: number
  /** BOQ-03: the newest open issues holding this activity up (at most 3; `open_issues` counts them all). */
  issues?: { id: string; what: string; severity: string; since: string | null }[]
  work_orders: { id: string; ref: string; vendor: string }[]
  lines: ScheduleLine[]
  sort_order: number
}

/** "FS": starts after the other ends (+ lag working days); "SS": starts with it (+ lag working days). */
export type LinkKind = 'FS' | 'SS'
export interface Link { id: string; lag: number; kind?: LinkKind }

export interface ScheduleProject {
  id: string
  name: string
  client: string | null
  stage: Stage
  stage_label: string
  start_date: string | null
  planned_finish: string | null
  /** The days site works, Monday first, "1" worked ("1111110": Sunday off), and the holidays besides. */
  work_week?: string
  holidays?: string[]
}

export interface Schedule {
  project: ScheduleProject
  today: string
  activities: Activity[]
  links: { predecessor: string; successor: string; lag: number; kind?: LinkKind }[]
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
    /** BOQ-03: every open issue of the project, and those on no activity (their words name none of the work). */
    open_issues?: number
    issues_on_no_activity?: number
    /** The approved programme compared with, and how many days the planned finish moved from it. */
    baseline?: { id: string; name: string; note: string | null; locked_at: string; locked_by: string | null; finish: string | null; slip_days: number } | null
  }
  can_edit: boolean
  /** The project's sites (to plan an activity on one), and, for those who plan, who may run an activity. */
  sites?: { id: string; name: string }[]
  people?: { id: string; name: string; role: string }[]
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
  assigned_user_id?: string | null
  after?: Link[]
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
  body: { name: string; start: string; end?: string; milestone?: boolean; site_id?: string | null; assigned_user_id?: string | null; after?: Link[] },
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

/** QA Step 11: approve the programme as it stands; later moves show against it. */
export async function approveProgramme(projectId: string, body: { name?: string; note?: string } = {}): Promise<ScheduleChange> {
  return (await api.post<ScheduleChange>(`${base(projectId)}/baselines`, body)).data
}

/** The programme as an .xlsx (no money), to send the client or the architect. */
export async function exportProgramme(projectId: string): Promise<Blob> {
  return (await api.get(`${base(projectId)}/export`, { responseType: 'blob' })).data as Blob
}

// -- the working calendar (the backend's logic.Calendar, for the dialogs' previews) ------------------------------

const iso = (d: Date) => d.toISOString().slice(0, 10)
const parse = (day: string) => new Date(`${day}T00:00:00Z`)

export interface WorkCalendar { week: string; holidays: Set<string> }

export function workCalendar(project?: Pick<ScheduleProject, 'work_week' | 'holidays'> | null): WorkCalendar {
  const week = /^[01]{7}$/.test(project?.work_week ?? '') && project!.work_week!.includes('1') ? project!.work_week! : '1111111'
  return { week, holidays: new Set(project?.holidays ?? []) }
}

/** Monday first, as the backend: getUTCDay() is Sunday first. */
export function worksOn(cal: WorkCalendar, day: string): boolean {
  return cal.week[(parse(day).getUTCDay() + 6) % 7] === '1' && !cal.holidays.has(day)
}

export function nextWorkDay(cal: WorkCalendar, day: string): string {
  let d = parse(day)
  for (let i = 0; i < 400 && !worksOn(cal, iso(d)); i++) d = new Date(d.getTime() + DAY_MS)
  return iso(d)
}

/** The n-th working day after `day` (before it when negative); `day` itself when 0. */
export function shiftWorkDays(cal: WorkCalendar, day: string, n: number): string {
  let d = parse(day)
  let left = Math.abs(n)
  const step = n > 0 ? DAY_MS : -DAY_MS
  while (left > 0) {
    d = new Date(d.getTime() + step)
    if (worksOn(cal, iso(d))) left -= 1
  }
  return iso(d)
}

/** The last day of `days` working days from `start` (moved to a working day first). */
export function endForWorkDays(cal: WorkCalendar, start: string, days: number): string {
  const first = nextWorkDay(cal, start)
  return days <= 1 ? first : shiftWorkDays(cal, first, days - 1)
}

/** Working days from `first` to `last`, both counted. */
export function countWorkDays(cal: WorkCalendar, first: string, last: string): number {
  let n = 0
  for (let d = parse(first); d <= parse(last); d = new Date(d.getTime() + DAY_MS)) if (worksOn(cal, iso(d))) n += 1
  return n
}

export const WEEK_DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const

/** "Mon–Sat", "every day", "Mon–Fri": the working week in words. */
export function weekWords(week: string): string {
  if (week === '1111111') return 'every day'
  if (week === '1111110') return 'Mon–Sat'
  if (week === '1111100') return 'Mon–Fri'
  return WEEK_DAYS.filter((_, i) => week[i] === '1').join(', ')
}

// -- project start ----------------------------------------------------------------------------------------------

export interface StartStep {
  key: 'dates' | 'contract' | 'boq' | 'schedule' | 'sites' | 'team' | 'suppliers' | 'work_orders'
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
  body: { stage?: Stage; start_date?: string; planned_finish?: string; work_week?: string; holidays?: string[] },
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
  /** The lines with both a client rate and your own cost: their value and margin (an unpriced line is never margin). */
  priced_contract_value?: string
  margin_priced?: string
  lines_without_budget_rate?: number
  dated_sections: number
  links: number
  sections: { id: string; name: string; lines: number; contract_value: string; start: string | null; finish: string | null }[]
  /** CC-13: the "Materials per unit" sheet, if the file has one, and the lines whose materials it set / found already set. */
  materials_sheet?: string | null
  material_lines_set?: number
  material_lines_kept?: number
  /** `sheet` is set on the rows of the materials sheet (their row numbers are that sheet's). */
  rows: { row: number; result: 'added' | 'kept' | 'section' | 'problem'; what: string; section: string | null; message: string | null; sheet?: string | null }[]
  /** PS phase 2: the words above the header row, and whether they name another project (preview only). */
  title?: string[]
  other_project?: boolean
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
