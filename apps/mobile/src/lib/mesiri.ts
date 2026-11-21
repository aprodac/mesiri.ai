import { get, patch, post, request, saveToken } from './api'
export { newKey } from './keys'

// The routes the app uses, all the dashboard's own (shapes mirror apps/dashboard/src/lib).

// ── Signing in ────────────────────────────────────────────────────────────

export interface Me {
  user_id: string
  org_id?: string
  role: string
  name?: string
  full_name?: string
  org_name?: string
  organization_name?: string | null
  /** A learning sample company's own date (YYYY-MM-DD); null for a real company. */
  today?: string | null
}

export const fetchMe = () => get<Me>('/auth/me')

export interface CodeRequested {
  resend_after_s: number
  expires_in_s: number
  /** Only from a test server that sends nothing. */
  dev_code: string | null
}

export const requestCode = (phone: string) => post<CodeRequested>('/auth/code/request', { phone, purpose: 'login' })

export async function loginWithCode(phone: string, code: string): Promise<void> {
  const res = await post<{ access_token: string }>('/auth/code/login', { phone, code })
  await saveToken(res.access_token)
}

export async function loginWithEmail(email: string, password: string): Promise<void> {
  const res = await post<{ access_token: string }>('/auth/login', { email, password })
  await saveToken(res.access_token)
}

// ── Projects and sites ────────────────────────────────────────────────────

export interface Project {
  id: string
  name: string
}

export interface Site {
  id: string
  name: string
  project_id: string
  status?: string
}

export const fetchProjects = () => get<Project[]>('/projects')
export const fetchSites = (projectId: string) => get<Site[]>(`/projects/${projectId}/sites`)

// ── The site's day (the site DPR page's data) ─────────────────────────────

export type SiteDayStatus = 'draft' | 'needs_details' | 'ready' | 'in_review' | 'approved' | 'published' | 'not_reported'

export interface SiteDayItem {
  site_id: string
  site_name: string
  project_id: string
  project_name: string
  status: SiteDayStatus
  missing_sections: { blocking: string[]; optional: string[] } | null
  site_working: 'full' | 'half' | 'none' | null
  workers: number
  work_items: number
  photos: number
  open_issues: number
  materials: number
  issues_today: number
  progress_updates: number
  last_update_at: string | null
  last_update_by: string | null
  latest_update: string | null
}

export interface SiteDayMaterialLine {
  material_name: string | null
  unit: string | null
  received: string
  used: string
  adjusted: string
  closing: string | null
  beyond_stock: boolean
}

export interface SiteDayReport {
  activity_count: number
  evidence_count: number
  labour: { headcount: number; named_count: number; trades: { trade: string; headcount: number }[] }
  materials: SiteDayMaterialLine[]
  conditions: {
    weather: 'sunny' | 'cloudy' | 'rainy' | 'windy' | 'extreme_heat' | null
    site_working: 'full' | 'half' | 'none' | null
    tomorrow_plan: string | null
    hours_lost: string | null
  }
}

export interface ReviewItem {
  id: string
  section: 'work' | 'labour' | 'materials' | 'issues'
  title: string | null
  detail: string | null
  review: 'draft' | 'confirmed'
  quantities?: { work_type: string | null; quantity: string; unit: string }[]
  evidence_count?: number
  severity?: string | null
  status?: string | null
}

export interface SiteDayDetail {
  date: string
  site_id: string
  project_id: string
  day: SiteDayItem | null
  report: SiteDayReport
  report_with_drafts?: SiteDayReport
  items: ReviewItem[]
  drafts: number
}

export const fetchSiteDay = (siteId: string, date: string) => get<SiteDayDetail>(`/dpr/site-days/${siteId}`, { date })

export type Weather = NonNullable<SiteDayReport['conditions']['weather']>

export const setConditions = (
  siteId: string,
  date: string,
  conditions: { weather?: Weather | null; site_working?: 'full' | 'half' | 'none' | null; tomorrow_plan?: string | null },
) => patch<unknown>(`/dpr/site-days/${siteId}/conditions`, conditions, { date })

export const sendDprNow = (projectId: string) => post<unknown>(`/dpr/projects/${projectId}/send`)

// ── Stock and requests ────────────────────────────────────────────────────

export interface StockRow {
  site_id: string | null
  material_id: string
  material_name: string
  unit: string
  closing: string
  used: string
  received: string
  days_left: number | null
  on_order?: string
  running_low: boolean
}

// A site filter is refused for a site-scoped person (a site engineer) unless the project comes with it.
export const fetchStock = (projectId: string, siteId: string) =>
  get<StockRow[]>('/materials/stock-summary', { project_id: projectId, site_id: siteId })

export type RequestStatus = 'waiting' | 'ordered' | 'sent' | 'done' | 'rejected' | 'cancelled'

export interface MaterialRequest {
  id: string
  ref: string
  site_id: string
  site_name: string
  requested_by_name: string | null
  needed_by: string | null
  purpose: string | null
  status: RequestStatus
  decision_note: string | null
  created_at: string
  lines: { id: string; material: string; quantity: string; unit_name: string; unit: string }[]
  orders: { id: string; ref: string; vendor_name: string; status: string }[]
}

export const fetchRequests = (projectId: string, siteId: string) =>
  get<{ items: MaterialRequest[] }>('/procurement/requests', { status: 'all', project_id: projectId, site_id: siteId })

// ── Mesiri: the same assistant as WhatsApp (the dashboard's Tell Mesiri door) ──

export interface ReplyOption {
  id: string
  title: string
  description?: string | null
}

export interface AssistantReply {
  type: 'text' | 'buttons' | 'list'
  text: string
  buttons: ReplyOption[]
  list_rows: ReplyOption[]
  button_label?: string | null
}

/** MOB-05: one entry on the person's list waiting for Save, as data (web_assistant ReadyEntry). */
export interface ReadyEntry {
  line: number
  tool: string
  method: string
  path: string
  params: Record<string, unknown>
  body: Record<string, unknown>
  summary: string
  /** Sent as Idempotency-Key when the app saves it, so the assistant's own Save later can't record it twice. */
  key: string
  /** The assistant's own Remove tap for this line. */
  remove_id: string | null
}

export interface AssistantResponse {
  message_id: string
  replies: AssistantReply[]
  /** A voice note's words, as Mesiri heard them. */
  transcript: string | null
  /** The list waiting for Save after this message; null when it could not be read. */
  ready?: ReadyEntry[] | null
}

/** A voice note plus the model usually answers in 5–20 s; the door waits up to a minute. */
const ASSISTANT_TIMEOUT_MS = 90_000

export const sendText = (text: string) => post<AssistantResponse>('/assistant/messages', { text }, ASSISTANT_TIMEOUT_MS)

export const sendTap = (id: string) =>
  post<AssistantResponse>('/assistant/messages', { interactive_reply_id: id }, ASSISTANT_TIMEOUT_MS)

/** A recording from the phone: AAC in MP4 (.m4a) on Android and iPhone; Ogg from a browser. */
export const sendVoice = (audio: Blob, contentType: string) =>
  request<AssistantResponse>('POST', '/assistant/messages/voice', {
    body: audio,
    contentType,
    timeoutMs: ASSISTANT_TIMEOUT_MS,
  })

// ── Forms (MOB-05): the routes the dashboard's own forms post to ─────────

export interface CatalogMaterial {
  id: string
  name: string
  default_unit: string | null
  default_unit_id: string | null
  category?: string | null
}

export interface Unit {
  id: string
  code: string
  display_name: string
}

export const fetchMaterials = () => get<{ items: CatalogMaterial[]; total: number }>('/materials', { is_active: true, limit: 200 })
export const fetchUnits = () => get<{ items: Unit[] }>('/materials/units-of-measure')

/** Save one record as the dashboard does; the key makes a second send (a retry, or the assistant's Save of the
 * same entry) answer with the first instead of recording it again. */
export const saveRecord = (method: string, path: string, body: Record<string, unknown>, key: string) =>
  request<unknown>(method, path, { json: body, headers: { 'Idempotency-Key': key } })
