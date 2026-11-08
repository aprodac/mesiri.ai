import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import { fetchProjects, fetchSites } from './projects'
import { rupees } from './orders'

// NXT-11 / NXT-13 / NXT-14 / NXT-15: machines and vehicles. Shapes mirror backend/src/mesiri/domains/equipment/router.py.
// Hours, idle, breakdown and diesel are for everyone who sees the site; rates, costs and bills only for the roles
// that see spending (the API sends null to the others).

export type MachineState = 'working' | 'idle' | 'breakdown' | 'not_logged' | 'no_site' | 'off_hire' | 'retired'
export type Ownership = 'owned' | 'hired'
export type RateUnit = 'hour' | 'day' | 'month'
export type Kind = 'machine' | 'vehicle'

export interface MachineLog {
  id: string
  equipment_id: string
  machine: string | null
  ref: string | null
  kind: Kind | null
  ownership: Ownership | null
  type: string | null
  event_type: 'day_log' | 'arrived' | 'moved' | 'departed' | 'serviced' | string
  date: string
  project_id: string | null
  project_name: string | null
  site_id: string | null
  site_name: string | null
  from_site_id: string | null
  from_site_name: string | null
  to_site_id: string | null
  to_site_name: string | null
  worked_hours: string | null
  idle_hours: string | null
  breakdown_hours: string | null
  breakdown_reason: string | null
  fuel_litres: string | null
  fuel_cost: string | null
  expense_id: string | null
  operator_name: string | null
  operator_worker_id: string | null
  trips: number | null
  meter_reading: string | null
  issue_id: string | null
  issue_status: string | null
  notes: string | null
  source: string | null
  created_by_name: string | null
  created_at: string | null
  voided: boolean
  utilisation: number | null
}

export interface HireCheck {
  recorded: { worked: string; idle: string; breakdown: string; days_on_site: number; charged_hours: string; expected: string }
  difference: string | null
  days_not_logged: number
  status: 'ok' | 'check' | 'over'
  flags: string[]
}

export interface HireBill {
  id: string
  equipment_id: string
  machine: string | null
  ref: string | null
  vendor_id: string | null
  vendor_name: string | null
  period_from: string
  period_to: string
  billed_hours: string | null
  billed_days: string | null
  amount: string | null
  bill_ref: string | null
  bill_date: string | null
  expense_id: string | null
  notes: string | null
  created_by_name: string | null
  created_at: string
  check?: HireCheck | null
}

export interface Machine {
  id: string
  number: number
  ref: string
  name: string
  type: string | null
  kind: Kind
  ownership: Ownership
  vendor_id: string | null
  vendor_name: string | null
  rate: string | null
  rate_unit: RateUnit | null
  min_hours_per_day: string | null
  registration_no: string | null
  make_model: string | null
  fuel_type: string | null
  project_id: string | null
  project_name: string | null
  site_id: string | null
  site_name: string | null
  status: 'active' | 'off_hire' | 'retired'
  on_hire_from: string | null
  off_hire_on: string | null
  service_every_hours: string | null
  last_service_on: string | null
  operator_name: string | null
  operator_worker_id: string | null
  notes: string | null
  created_at: string
  state: MachineState
  today: MachineLog | null
  last_log_date: string | null
  meter_reading: string | null
  month: {
    from: string
    worked: string
    idle: string
    breakdown: string
    fuel_litres: string
    days_logged: number
    trips: number
    utilisation: number | null
    litres_per_hour: string | null
    fuel_cost: string | null
    hire_cost: string | null
    cost: string | null
  }
  recent: { date: string; worked: string | null; idle: string | null; breakdown: string | null; fuel: string | null }[]
  service: { every: string; since: string; left: string; status: 'ok' | 'soon' | 'due'; last_on: string | null } | null
}

export interface MachineDetail extends Machine {
  period: {
    from: string
    to: string
    worked: string
    idle: string
    breakdown: string
    fuel_litres: string
    trips: number
    days_logged: number
    utilisation: number | null
    litres_per_hour: string | null
    hire_cost: string | null
    fuel_cost: string | null
  }
  logs: MachineLog[]
  events: MachineLog[]
  bills: HireBill[]
  breakdowns: MachineLog[]
}

export interface MachineList {
  items: Machine[]
  counts: Record<'on_site' | 'working' | 'idle' | 'breakdown' | 'not_logged' | 'service_due' | 'off_hire' | 'hired', number>
  today: string | null
  month_cost: string | null
}

export interface MissingMachine {
  id: string
  ref: string
  name: string
  type: string | null
  kind: Kind
  ownership: Ownership
  site_id: string
  site_name: string | null
  project_id: string
  project_name: string | null
  operator_name: string | null
}

export interface DayLogs {
  date_from: string
  date_to: string
  items: MachineLog[]
  totals: { worked: string; idle: string; breakdown: string; fuel_litres: string; fuel_cost: string | null; machines: number; logs: number }
  missing: MissingMachine[]
}

export interface HireCheckRow {
  id: string
  ref: string
  name: string
  type: string | null
  vendor_id: string | null
  vendor_name: string | null
  rate: string | null
  rate_unit: RateUnit | null
  min_hours_per_day: string | null
  site_name: string | null
  project_name: string | null
  status: Machine['status']
  worked: string
  idle: string
  breakdown: string
  days_on_site: number
  days_logged: number
  charged_hours: string
  expected: string
  billed: string
  unbilled: string
  bills: HireBill[]
  state: 'over' | 'unbilled' | 'check' | 'no_bill' | 'ok'
}

export interface Returnables {
  items: {
    material_id: string
    name: string
    category: string | null
    main_category: string | null
    unit: string
    total: string
    lost: string
    sites: { site_id: string; site_name: string | null; project_id: string; project_name: string | null; held: string; received: string; lost: string }[]
  }[]
  sites: { site_id: string; site_name: string | null; project_name: string | null }[]
  categories: { id: string; name: string; parent_id: string | null; parent_name: string | null; returnable: boolean; via_parent: boolean }[]
}

export interface MachineInput {
  name?: string
  type?: string | null
  kind?: Kind
  ownership?: Ownership
  vendor_id?: string | null
  hire_company?: string | null
  rate?: string | null
  rate_unit?: RateUnit | null
  min_hours_per_day?: string | null
  registration_no?: string | null
  make_model?: string | null
  fuel_type?: string | null
  site_id?: string | null
  on_hire_from?: string | null
  service_every_hours?: string | null
  operator_name?: string | null
  notes?: string | null
  status?: Machine['status']
}

export interface LogLineInput {
  equipment_id: string
  site_id?: string | null
  worked_hours?: string | null
  idle_hours?: string | null
  breakdown_hours?: string | null
  breakdown_reason?: string | null
  fuel_litres?: string | null
  fuel_cost?: string | null
  operator_name?: string | null
  trips?: number | null
  meter_reading?: string | null
  notes?: string | null
}

type Scope = { project_id?: string | null; site_id?: string | null }
const clean = (p: Record<string, unknown>) => Object.fromEntries(Object.entries(p).filter(([, v]) => v !== null && v !== undefined && v !== ''))

export async function fetchMachines(params: Scope & { status?: string; kind?: Kind | ''; vendor_id?: string } = {}): Promise<MachineList> {
  return (await api.get('/equipment', { params: clean(params) })).data
}
export async function fetchMachine(id: string, params: { date_from?: string; date_to?: string } = {}): Promise<MachineDetail> {
  return (await api.get(`/equipment/${id}`, { params: clean(params) })).data
}
export async function createMachine(body: MachineInput): Promise<Machine> {
  return (await api.post('/equipment', body)).data
}
export async function updateMachine(id: string, body: MachineInput): Promise<Machine> {
  return (await api.patch(`/equipment/${id}`, body)).data
}
export async function deleteMachine(id: string): Promise<void> {
  await api.delete(`/equipment/${id}`)
}
export async function moveMachine(id: string, body: { site_id: string; date?: string; notes?: string }): Promise<Machine> {
  return (await api.post(`/equipment/${id}/move`, body)).data
}
export async function offHire(id: string, body: { date?: string; notes?: string } = {}): Promise<Machine> {
  return (await api.post(`/equipment/${id}/off-hire`, body)).data
}
export async function onHire(id: string, body: { site_id: string; date?: string }): Promise<Machine> {
  return (await api.post(`/equipment/${id}/on-hire`, body)).data
}
export async function recordService(id: string, body: { date?: string; meter_reading?: string | null; notes?: string | null } = {}): Promise<Machine> {
  return (await api.post(`/equipment/${id}/service`, body)).data
}
export async function fetchLogs(params: Scope & { date?: string; date_from?: string; date_to?: string; equipment_id?: string }): Promise<DayLogs> {
  return (await api.get('/equipment/logs', { params: clean(params) })).data
}
export async function saveLogs(body: { occurred_date?: string; lines: LogLineInput[] }): Promise<{ date: string; items: MachineLog[]; replaced: unknown[]; moved: { machine: string }[]; issues: { machine: string }[] }> {
  return (await api.post('/equipment/logs', { ...body, source: 'dashboard' })).data
}
export async function voidLog(id: string): Promise<void> {
  await api.delete(`/equipment/logs/${id}`)
}
export async function fetchHireCheck(params: { date_from?: string; date_to?: string; vendor_id?: string } = {}): Promise<{ date_from: string; date_to: string; items: HireCheckRow[]; totals: { expected?: string; billed?: string; unbilled?: string; over: number } }> {
  return (await api.get('/equipment/hire-check', { params: clean(params) })).data
}
export async function createHireBill(body: { equipment_id: string; period_from: string; period_to: string; billed_hours?: string | null; billed_days?: string | null; amount: string; bill_ref?: string | null; bill_date?: string | null; notes?: string | null }): Promise<HireBill> {
  return (await api.post('/equipment/hire-bills', body)).data
}
export async function deleteHireBill(id: string): Promise<void> {
  await api.delete(`/equipment/hire-bills/${id}`)
}
export async function fetchReturnables(params: Scope = {}): Promise<Returnables> {
  return (await api.get('/equipment/returnables', { params: clean(params) })).data
}
export async function setReturnable(categoryId: string, returnable: boolean): Promise<void> {
  await api.put(`/equipment/returnables/categories/${categoryId}`, { returnable })
}

/** Every site the person can reach, with its project, for the site pickers. */
export function useSiteOptions() {
  return useQuery({
    queryKey: ['equipment', 'site-options'],
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const projects = await fetchProjects()
      const sites = await Promise.all(projects.map(async (p) => (await fetchSites(p.id)).map((s) => ({ ...s, projectName: p.name }))))
      return sites.flat()
    },
  })
}

/** What the API's error says, in words (a 409 / 422 with `detail.message` or a plain `detail`). */
export function errorWords(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object' && 'message' in detail) return String((detail as { message: unknown }).message)
  if (Array.isArray(detail)) return 'Some figures are not right: check the hours (0 to 24) and the numbers.'
  return 'Something went wrong. Try again.'
}

// ---- Words and looks ---------------------------------------------------------------------------------------------

export const STATE_LOOK: Record<MachineState, { label: string; chip: string; dot: string; bar: string }> = {
  working: { label: 'Working', chip: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100', dot: 'bg-emerald-500', bar: 'bg-emerald-500' },
  idle: { label: 'Idle', chip: 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-100', dot: 'bg-amber-500', bar: 'bg-amber-400' },
  breakdown: { label: 'Broken down', chip: 'bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-100', dot: 'bg-red-500', bar: 'bg-red-500' },
  not_logged: { label: 'Not logged today', chip: 'bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-100', dot: 'bg-slate-400', bar: 'bg-slate-300' },
  no_site: { label: 'At no site', chip: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200', dot: 'bg-slate-300', bar: 'bg-slate-200' },
  off_hire: { label: 'Off hire', chip: 'bg-zinc-200 text-zinc-800 dark:bg-zinc-800 dark:text-zinc-200', dot: 'bg-zinc-500', bar: 'bg-zinc-400' },
  retired: { label: 'Retired', chip: 'bg-zinc-100 text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400', dot: 'bg-zinc-300', bar: 'bg-zinc-200' },
}

export const RATE_WORDS: Record<RateUnit, string> = { hour: 'an hour', day: 'a day', month: 'a month' }

/** The common machines on Indian sites, for the type picker (any other is typed). */
export const MACHINE_TYPES = [
  'Backhoe loader (JCB)', 'Excavator', 'Concrete mixer', 'Transit mixer', 'Concrete pump', 'Needle vibrator', 'Road roller',
  'Plate compactor', 'Mobile crane (Hydra)', 'Tower crane', 'Air compressor', 'Rock breaker', 'Generator (DG set)',
  'Dewatering pump', 'Bar bending machine', 'Bar cutting machine', 'Bobcat (skid steer)', 'Motor grader', 'Hoist / lift',
] as const
export const VEHICLE_TYPES = ['Tipper', 'Tractor', 'Lorry', 'Pickup', 'Water tanker', 'Car', 'Two-wheeler'] as const

/** Money on the equipment pages, in whole rupees (a monthly hire spread per day has paise nobody pays). */
export function inr(v: string | number | null | undefined): string {
  return v === null || v === undefined || v === '' ? '—' : rupees(Math.round(Number(v)))
}

export function hrs(v: string | null | undefined): string {
  if (v === null || v === undefined || v === '') return '–'
  const n = Number(v)
  return `${Number.isInteger(n) ? n : n.toFixed(1)} h`
}

export function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? '–' : `${Math.round(v * 100)}%`
}

export function rateWords(m: Pick<Machine, 'rate' | 'rate_unit' | 'min_hours_per_day'>): string | null {
  if (!m.rate) return null
  const r = `₹${Number(m.rate).toLocaleString('en-IN')} ${RATE_WORDS[m.rate_unit ?? 'hour']}`
  return m.min_hours_per_day && m.rate_unit === 'hour' ? `${r}, min ${Number(m.min_hours_per_day)} h a day` : r
}

export function iso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function dayWords(date: string, today = iso(new Date())): string {
  if (date === today) return 'Today'
  const d = new Date(`${date}T00:00:00`)
  const t = new Date(`${today}T00:00:00`)
  const diff = Math.round((t.getTime() - d.getTime()) / 86_400_000)
  if (diff === 1) return 'Yesterday'
  return d.toLocaleDateString('en-IN', { weekday: diff < 7 && diff > 0 ? 'short' : undefined, day: 'numeric', month: 'short' })
}
