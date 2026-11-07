import type { LucideIcon } from 'lucide-react'
import { ArrowUpDown, BrickWall, Droplet, Flame, Fuel, Package, PaintRoller, Zap } from 'lucide-react'
import { api } from './api'

// PRC-22: material requests -- what a site asks for, before anyone orders it. The shapes mirror
// backend/src/mesiri/domains/procurement (requests.py describes a request; router.py the routes).

export type RequestStatus = 'waiting' | 'ordered' | 'sent' | 'done' | 'rejected' | 'cancelled'
export type Urgency = 'late' | 'soon' | 'later' | 'closed'
export type Decision = 'ordered' | 'sent' | 'rejected' | 'done'

export interface RequestLine {
  id: string
  material_id: string
  material: string
  category: string | null
  main_category: string | null
  category_id: string | null
  main_category_id: string | null
  unit: string
  unit_name: string
  quantity: string
  /** What was said when it was asked in another unit ("1.2 Tons"). */
  said: string | null
  at_site: string
  on_order: string
  to_buy: string
  elsewhere: { site_id: string; site_name: string; project_id: string; quantity: string }[]
  /** Only for the roles that see the company's spending. */
  last_rate: { unit_cost: string; unit: string | null; occurred_date: string | null; supplier: string | null } | null
}

export interface MaterialRequest {
  id: string
  number: number
  ref: string
  project_id: string
  project_name: string
  site_id: string
  site_name: string
  requested_by: string | null
  requested_by_name: string | null
  requested_by_role: string | null
  source: 'dashboard' | 'whatsapp'
  needed_by: string | null
  purpose: string | null
  status: RequestStatus
  urgency: Urgency
  raised_over_duplicate: boolean
  decision_note: string | null
  decided_by_name: string | null
  decided_at: string | null
  done_at: string | null
  created_at: string
  lines: RequestLine[]
  duplicates: { id: string; ref: string; status: RequestStatus; requested_by_name: string | null; created_at: string }[]
  /** PRC-23: the purchase orders behind it ("PO-0003 · Malabar · 150 of 160 came"), cancelled ones too. */
  orders: RequestOrder[]
  /** PRC-23: an order covers it: it moves with the order, so the office's buttons here are off. */
  follows_order: boolean
  may_act: boolean
  may_cancel: boolean
  may_decide: boolean
  /** PRC-31: the asker or the office may change it (waiting); bring it back (said no to, taken back). */
  may_edit: boolean
  may_reopen: boolean
}

export interface RequestOrder {
  id: string
  ref: string
  vendor_name: string
  status: 'open' | 'part' | 'received' | 'closed' | 'cancelled'
  lines: { material: string; unit: string; quantity: string; received: string; pending: string }[]
}

export interface RequestList {
  items: MaterialRequest[]
  counts: Partial<Record<'waiting' | 'ordered' | 'done' | 'rejected' | 'all' | 'late' | 'soon' | 'duplicates', number>>
}

export interface DuplicateConflict {
  code: 'possible_duplicate'
  message: string
  duplicates: { id: string; ref: string; status: RequestStatus; site_name: string; requested_by_name: string | null }[]
  /** PRC-23: open orders in the project already bringing the material (no request behind them). */
  orders?: { id: string; ref: string; vendor_name: string; lines: { material: string; pending: string; unit: string }[] }[]
  /** PRC-23 (a new order): a site's waiting request for the same material, which the order does not cover. */
  requests?: { id: string; ref: string; site_name: string; requested_by_name: string | null }[]
}

export async function fetchRequests(params: { project_id?: string | null; site_id?: string | null }): Promise<RequestList> {
  const { data } = await api.get<RequestList>('/procurement/requests', {
    params: { status: 'all', project_id: params.project_id || undefined, site_id: params.site_id || undefined },
  })
  return data
}

export interface CreateRequestPayload {
  project_id: string
  site_id: string
  lines: { material_id: string; quantity: string; unit_id: string }[]
  needed_by?: string | null
  purpose?: string | null
  confirm_duplicate?: boolean
}

export async function createRequest(payload: CreateRequestPayload): Promise<MaterialRequest> {
  const { data } = await api.post<MaterialRequest>('/procurement/requests', payload)
  return data
}

export function asDuplicateConflict(err: unknown): DuplicateConflict | null {
  const detail = (err as { response?: { status?: number; data?: { detail?: unknown } } })?.response
  if (detail?.status !== 409) return null
  const d = detail.data?.detail as DuplicateConflict | undefined
  return d && d.code === 'possible_duplicate' ? d : null
}

export async function updateRequest(id: string, payload: {
  lines?: { id?: string; material_id: string; quantity: string; unit_id: string }[]
  needed_by?: string | null
  purpose?: string | null
}): Promise<MaterialRequest> {
  const { data } = await api.patch<MaterialRequest>(`/procurement/requests/${id}`, payload)
  return data
}

/** PRC-30: got it (or the rest of it) outside Mesiri: its open orders stop, the request is ordered outside. */
export async function boughtOutside(id: string, note?: string): Promise<MaterialRequest> {
  const { data } = await api.post<MaterialRequest>(`/procurement/requests/${id}/outside`, { note: note || null })
  return data
}

export async function reopenRequest(id: string): Promise<MaterialRequest> {
  const { data } = await api.post<MaterialRequest>(`/procurement/requests/${id}/reopen`)
  return data
}

export async function decideRequest(id: string, action: Decision, note?: string): Promise<MaterialRequest> {
  const { data } = await api.post<MaterialRequest>(`/procurement/requests/${id}/decide`, { action, note: note || null })
  return data
}

export async function cancelRequest(id: string): Promise<MaterialRequest> {
  const { data } = await api.post<MaterialRequest>(`/procurement/requests/${id}/cancel`)
  return data
}

// ---------------------------------------------------------------------------
// Visual language (the approved Requests design, 7 Nov 2026). Each colour means one thing:
// status = where it is; urgency = how soon; the cover bar = what still has to be bought.
// ---------------------------------------------------------------------------

export const STATUS_LOOK: Record<RequestStatus, { label: string; chip: string; dot: string }> = {
  waiting: { label: 'Waiting', chip: 'bg-stone-200 text-stone-800 dark:bg-stone-700 dark:text-stone-100', dot: 'bg-stone-600 dark:bg-stone-300' },
  ordered: { label: 'Ordered', chip: 'bg-info-soft text-info', dot: 'bg-blue-600' },
  sent: { label: 'Sent from site', chip: 'bg-fuchsia-100 text-fuchsia-800 dark:bg-fuchsia-950 dark:text-fuchsia-200', dot: 'bg-fuchsia-600' },
  done: { label: 'Received', chip: 'bg-success-soft text-success', dot: 'bg-green-700' },
  rejected: { label: 'Not ordered', chip: 'bg-destructive/10 text-destructive', dot: 'bg-destructive' },
  cancelled: { label: 'Cancelled', chip: 'bg-muted text-muted-foreground', dot: 'bg-muted-foreground/60' },
}

export const URGENCY_LOOK: Record<Urgency, { chip: string; dot: string }> = {
  late: { chip: 'bg-destructive text-white', dot: 'bg-destructive' },
  soon: { chip: 'bg-orange-200 text-orange-950 dark:bg-orange-900 dark:text-orange-100', dot: 'bg-orange-500' },
  later: { chip: 'bg-muted text-foreground/80', dot: 'bg-muted-foreground/50' },
  closed: { chip: 'bg-muted text-muted-foreground', dot: 'bg-muted-foreground/30' },
}

/** "Still to buy": black and yellow hazard stripes. */
export const HAZARD = 'bg-[repeating-linear-gradient(135deg,#1a1d21_0_4px,#facc15_4px_8px)]'

const CATEGORY_LOOKS: { match: RegExp; icon: LucideIcon; tile: string }[] = [
  { match: /struct|civil|concrete|steel/i, icon: BrickWall, tile: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300' },
  { match: /electric/i, icon: Zap, tile: 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300' },
  { match: /plumb|sanit|water/i, icon: Droplet, tile: 'bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300' },
  { match: /fire/i, icon: Flame, tile: 'bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300' },
  { match: /gas/i, icon: Fuel, tile: 'bg-teal-100 text-teal-700 dark:bg-teal-950 dark:text-teal-300' },
  { match: /lift|elevat/i, icon: ArrowUpDown, tile: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-950 dark:text-cyan-300' },
  { match: /finish|paint/i, icon: PaintRoller, tile: 'bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-300' },
]
const NO_CATEGORY = { icon: Package, tile: 'bg-muted text-muted-foreground' }

/** A main category's icon and tile colour, by its name (the builder's standard list, PRC-03). */
export function categoryLook(mainCategory: string | null | undefined): { icon: LucideIcon; tile: string } {
  if (!mainCategory) return NO_CATEGORY
  return CATEGORY_LOOKS.find((c) => c.match.test(mainCategory)) ?? NO_CATEGORY
}

const SWATCHES = ['#0e7490', '#0369a1', '#be123c', '#15803d', '#a21caf', '#b45309', '#4338ca', '#57534e']

function hash(text: string): number {
  let h = 0
  for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) | 0
  return Math.abs(h)
}

/** A steady colour for a project or person (same id, same colour, everywhere on the page). */
export function swatch(id: string): string {
  return SWATCHES[hash(id) % SWATCHES.length]
}

export function initials(name: string | null | undefined): string {
  const parts = (name || '?').trim().split(/\s+/)
  return ((parts[0]?.[0] ?? '?') + (parts[1]?.[0] ?? '')).toUpperCase()
}

const DAY = 86_400_000

/** "2 days late", "Tomorrow", "Fri 14 Nov": the needed-by date in words. */
export function neededWords(r: Pick<MaterialRequest, 'needed_by' | 'urgency' | 'status'>, today = new Date()): string {
  if (r.status === 'done') return 'Received'
  if (r.status === 'rejected' || r.status === 'cancelled') return 'Closed'
  if (!r.needed_by) return 'No date'
  const due = new Date(`${r.needed_by}T00:00:00`)
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  const days = Math.round((due.getTime() - start.getTime()) / DAY)
  if (days < 0) return `${-days} day${days === -1 ? '' : 's'} late`
  if (days === 0) return 'Today'
  if (days === 1) return 'Tomorrow'
  return due.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })
}

export function ago(iso: string, now = new Date()): string {
  const mins = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 60_000))
  if (mins < 1) return 'now'
  if (mins < 60) return `${mins}m`
  if (mins < 24 * 60) return `${Math.round(mins / 60)}h`
  return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
}

/** The share of what was asked that is here, already ordered, and still to buy (for the cover bar). */
export function cover(line: RequestLine): { here: number; ordered: number; buy: number } {
  const asked = Number(line.quantity) || 0
  if (asked <= 0) return { here: 0, ordered: 0, buy: 0 }
  const here = Math.min(Math.max(Number(line.at_site) || 0, 0), asked)
  const ordered = Math.min(Number(line.on_order) || 0, asked - here)
  const buy = Math.max(asked - here - ordered, 0)
  return { here: (here / asked) * 100, ordered: (ordered / asked) * 100, buy: (buy / asked) * 100 }
}

export function qty(value: string, unit: string): string {
  return `${Number(value).toLocaleString('en-IN', { maximumFractionDigits: 3 })} ${unit}`
}
