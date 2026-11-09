import { api } from './api'

// PRC-19: the weekly / monthly report. One read (GET /reports/period) gives the headline, the key figures, "Needs
// you", one line per area, and each section; the PDF and the Excel are the same read rendered by the server
// (backend/src/mesiri/domains/reports/period). Money only reaches the roles that see spending (the API decides).

export type PeriodKind = 'week' | 'month' | 'custom'
export type Tone = 'good' | 'warn' | 'bad' | 'none'

export interface PeriodInfo {
  kind: PeriodKind
  from: string
  to: string
  days: number
  label: string
  range: string
}

export interface Kpi {
  key: string
  label: string
  value: string
  note: string
  tone: Tone
  section: string
  change_pct?: string | null
  trend?: string[]
}

export interface Area {
  key: string
  title: string
  status: Tone
  word: string
  note: string
}

export interface NeedsYou {
  kind: string
  level: 'bad' | 'warn' | 'info'
  title: string
  detail?: string | null
  action?: string | null
  link?: string | null
}

export interface WorkRow {
  activity_id: string
  activity: string
  site?: string | null
  progress: number | null
  expected: number | null
  state: string | null
  days_late: number
  slip_days: number
  critical: boolean
  done_in_period: { work: string; quantity: string; unit: string }[]
}

export interface Sections {
  work?: {
    status: Tone
    done_pct: string | null
    plan_pct: string | null
    progress_to_date: number | null
    expected_to_date: string | null
    has_plan: boolean
    work_in_other_unit: number
    lines_worked: number
    rows: WorkRow[]
    link: string
  }
  schedule?: {
    status: Tone
    forecast_finish: string | null
    planned_finish: string | null
    slip_days: number
    scheduled: number
    rows: (Omit<WorkRow, 'done_in_period'> & { forecast_end: string | null; end: string | null; assigned_to?: string | null; open_issues: number })[]
    link: string
  }
  labour?: {
    status: Tone
    man_days: string
    prev_man_days: string
    change_pct: string | null
    average_per_day: string | null
    wages?: string
    prev_wages?: string
    by_trade: { label: string; man_days: string; wages?: string }[]
    by_day: { date: string; man_days: string; wages?: string }[]
    by_site: { label: string; man_days: string; wages?: string }[]
    trend: { label: string; from: string; man_days: string }[]
    link: string
  }
  materials?: {
    status: Tone
    received_items: number
    used_items: number
    running_low: number
    spend?: string | null
    rows: { material: string; unit: string; category?: string | null; site?: string | null; opening: string; received: string; used: string; closing: string; days_left: number | null; running_low: boolean; spend?: string | null }[]
    link: string
  }
  money?: {
    status: Tone
    spent: string
    prev_spent: string
    change_pct: string | null
    centres: { key: string; label: string; amount: string }[]
    labour_colour: 'green' | 'amber' | 'red' | 'grey'
    worst_lines: { work: string; section: string | null; colour: string; done_quantity: string; unit: string; labour_cost: string | null; earned_labour: string | null; difference: string | null }[]
    materials_earned: string
    materials_bought: string
    billed?: string
    received?: string
    owed?: string
    overdue?: string
    overdue_bills?: { ref: string; left: string; days: number; bill_date: string }[]
    link: string
    bills_link?: string
  }
  issues?: {
    status: Tone
    raised: number
    closed: number
    open: number
    serious_open: number
    delay_hours: string
    rows: { id: string; type: string; severity: string; what: string | null; site: string | null; since: string; days_open: number }[]
    link: string
  }
  photos?: {
    status: Tone
    available: number
    rows: { url: string | null; caption: string | null; work: string | null; date: string | null; site: string | null }[]
    link: string
  }
  completeness?: {
    status: Tone
    days_total: number
    days_full: number
    days_missing: string[]
    days_no_attendance: string[]
    sites: number
    days: { date: string; weekday: string; reports: number; attendance: number; sites: number; weather: string | null }[]
    link: string
  }
}

export interface PeriodReport {
  project: { id: string; name: string; client: string | null }
  site: { id: string; name: string } | null
  period: PeriodInfo
  previous: PeriodInfo
  next: PeriodInfo | null
  today: string
  running: boolean
  generated_at: string
  headline: { lead: string; facts: string[]; more: string[] }
  kpis: Kpi[]
  areas: Area[]
  needs_you: NeedsYou[]
  sections: Sections
  order: (keyof Sections)[]
  unavailable: string[]
  sees_money: boolean
}

export interface PeriodQuery {
  project_id: string
  site_id?: string
  period: PeriodKind
  date?: string
  date_from?: string
  date_to?: string
}

function params(q: PeriodQuery): Record<string, string> {
  const out: Record<string, string> = { project_id: q.project_id, period: q.period }
  if (q.site_id) out.site_id = q.site_id
  if (q.period === 'custom') {
    if (q.date_from) out.date_from = q.date_from
    if (q.date_to) out.date_to = q.date_to
  } else if (q.date) out.date = q.date
  return out
}

export async function fetchPeriodReport(q: PeriodQuery): Promise<PeriodReport> {
  return (await api.get<PeriodReport>('/reports/period', { params: params(q) })).data
}

/** The same report as a PDF or an Excel file, with the API's own file name when the browser may read it. */
export async function downloadPeriodReport(q: PeriodQuery, kind: 'pdf' | 'xlsx', fallback: string): Promise<{ blob: Blob; filename: string }> {
  const res = await api.get(`/reports/period/${kind}`, { params: params(q), responseType: 'blob' })
  const match = /filename="([^"]+)"/.exec(String(res.headers['content-disposition'] ?? ''))
  return { blob: res.data as Blob, filename: match?.[1] ?? `${fallback}.${kind}` }
}

/** ₹12,400 · ₹4.2 L · ₹2.31 Cr: the same words the server uses (headline.inr). */
export function inr(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const v = Number(value)
  if (!Number.isFinite(v)) return '—'
  const sign = v < 0 ? '-' : ''
  const a = Math.abs(v)
  if (a >= 1e7) return `${sign}₹${(a / 1e7).toFixed(2)} Cr`
  if (a >= 1e5) return `${sign}₹${(a / 1e5).toFixed(1)} L`
  return `${sign}₹${Math.round(a).toLocaleString('en-IN')}`
}

export function shortDay(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
}
