import { api } from './api'
import { rupees } from './expenses'
import { day } from './vendors'

// NXT-05/06/07, CC-04: subcontracts. Rules live in the backend (domains/subcontracts/rules.py): a bill is checked
// against the work measured and the agreed rates; a payable bill holds retention, recovers the advance and deducts TDS.

export type WoStatus = 'draft' | 'issued' | 'completed' | 'closed' | 'cancelled'
export type CheckStatus = 'waiting' | 'passed' | 'flagged' | 'approved' | 'rejected'

export const WO_LOOK: Record<WoStatus, { label: string; chip: string }> = {
  draft: { label: 'Draft', chip: 'bg-stone-200 text-stone-800 dark:bg-stone-800 dark:text-stone-100' },
  issued: { label: 'Issued', chip: 'bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-100' },
  completed: { label: 'Work done', chip: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100' },
  closed: { label: 'Closed', chip: 'bg-muted text-muted-foreground' },
  cancelled: { label: 'Cancelled', chip: 'bg-muted text-muted-foreground line-through' },
}

export const CHECK_LOOK: Record<CheckStatus, { label: string; chip: string }> = {
  waiting: { label: 'Waiting for a check', chip: 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-100' },
  passed: { label: 'Passed', chip: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100' },
  flagged: { label: 'Flagged', chip: 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200' },
  approved: { label: 'Approved', chip: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100' },
  rejected: { label: 'Rejected', chip: 'bg-muted text-muted-foreground line-through' },
}

export interface WoLine {
  id: string
  planned_item_id: string | null
  boq_code: string | null
  description: string
  unit: string
  quantity: string
  rate?: string
  amount?: string
  measured: string
  proposed: string
  last_measured: string | null
  billed: string
  billed_amount?: string
  to_bill: string
  remaining: string
  over_measured: boolean
  over_agreed: boolean
}

export interface Flag { code: string; line_id: string | null; words: string }

export interface WoBill {
  id: string
  work_order_id: string
  wo_ref: string
  vendor_id: string
  expense_id: string
  number: number
  ref: string
  their_bill_no: string | null
  bill_date: string
  gross: string
  check_status: CheckStatus
  flags: Flag[]
  retention_amount: string
  retention_released: string
  retention_held: string
  advance_recovered: string
  tds_pct: string | null
  tds_amount: string
  net_payable: string | null
  paid_cash: string
  left: string
  payable_now: string
  payment_status: string
  decided_by_name: string | null
  decided_at: string | null
  decision_reason: string | null
  submitted_by_name: string | null
  submitted_by_contact: string | null
  source: string
  created_at: string
  lines: { line_id: string; description: string; unit: string; quantity: string; rate: string; agreed_rate: string; amount: string }[]
  vendor_name?: string
  project_name?: string
  site_name?: string | null
}

export interface WoTotals {
  value?: string
  measured_value?: string
  billed?: string
  approved?: string
  paid?: string
  retention_held?: string
  advance_given?: string
  advance_recovered?: string
  advance_left?: string
  progress_pct: string
  billed_pct?: string
  bills: number
  to_check: number
  payable_now?: string
}

export interface WorkOrder {
  id: string
  number: number
  ref: string
  status: WoStatus
  title: string | null
  vendor_id: string
  vendor_name: string
  vendor_phone: string | null
  vendor_gstin: string | null
  vendor_tds_pct?: string | null
  project_id: string
  project_name: string
  site_id: string | null
  site_name: string | null
  start_date: string | null
  end_date: string | null
  completed_on: string | null
  retention_pct?: string
  defect_days: number
  advance_agreed?: string | null
  advance_recovery_pct?: string | null
  tds_pct?: string | null
  their_ref: string | null
  terms: string | null
  notes: string | null
  status_note: string | null
  created_by_name: string | null
  created_at: string
  issued_at: string | null
  lines: WoLine[]
  totals: WoTotals
  flags: number
  bills?: WoBill[]
  with_money: boolean
}

export interface Measurement {
  id: string
  line_id: string
  description: string
  unit: string
  measured_on: string
  quantity: string
  notes: string | null
  status: 'confirmed' | 'proposed' | 'rejected'
  source: string
  who: string | null
  decided_by_name: string | null
  has_photo: boolean
  from_activity: boolean
}

export interface WorkOrderDetail extends WorkOrder {
  measurements: Measurement[]
  history: { kind: string; what: string; at: string; who: string | null }[]
  team: { man_days: string; days: number; last: string | null }
}

export interface WoList {
  work_orders: WorkOrder[]
  summary: { open: number; drafts: number; to_check: number; flagged_lines: number; value?: string; retention_held?: string; advance_left?: string; payable_now?: string }
  with_money: boolean
}

export interface LineIn { id?: string; planned_item_id?: string | null; description?: string; unit?: string; quantity: string; rate: string }

export interface WorkOrderIn {
  vendor_id?: string
  vendor_name?: string
  project_id: string
  site_id?: string | null
  name?: string | null
  start_date?: string | null
  end_date?: string | null
  retention_pct?: string | null
  defect_days?: number | null
  advance_agreed?: string | null
  advance_recovery_pct?: string | null
  tds_pct?: string | null
  their_ref?: string | null
  terms?: string | null
  notes?: string | null
  lines: LineIn[]
  issue?: boolean
}

export interface BillIn {
  lines: { line_id: string; quantity: string; rate?: string }[]
  amount?: string
  their_bill_no?: string
  bill_date?: string
  notes?: string
  retention_pct?: string
  advance_recover?: string
  tds_pct?: string
}

export interface BillCheck {
  gross: string
  flags: Flag[]
  status: 'passed' | 'flagged'
  deductions: { gross: string; retention: string; advance: string; tds: string; net: string }
  tds_pct: string | null
}

export interface SiteWork { activity_quantity_id: string; date: string; quantity: string; unit: string; work: string | null; contractor: string | null; site: string | null; line_id: string | null; line: string | null; likely: boolean }

const B = '/subcontracts'

export const fetchWorkOrders = async (params: { project_id?: string; vendor_id?: string } = {}): Promise<WoList> => (await api.get(`${B}/work-orders`, { params })).data
export const fetchWorkOrder = async (id: string): Promise<WorkOrderDetail> => (await api.get(`${B}/work-orders/${id}`)).data
export const createWorkOrder = async (body: WorkOrderIn): Promise<WorkOrder> => (await api.post(`${B}/work-orders`, body)).data
export const editWorkOrder = async (id: string, body: Partial<WorkOrderIn>): Promise<WorkOrder> => (await api.patch(`${B}/work-orders/${id}`, body)).data
export const moveWorkOrder = async (id: string, move: 'issue' | 'complete' | 'close' | 'cancel' | 'reopen', body: { note?: string; completed_on?: string } = {}): Promise<WorkOrder> =>
  (await api.post(`${B}/work-orders/${id}/${move}`, body)).data
export const addMeasurement = async (id: string, body: { line_id: string; quantity: string; measured_on?: string; notes?: string }) => (await api.post(`${B}/work-orders/${id}/measurements`, body)).data
export const decideMeasurement = async (mid: string, decision: 'confirm' | 'reject' | 'remove', reason?: string) => (await api.post(`${B}/measurements/${mid}/${decision}`, { reason })).data
export const fetchSiteWork = async (id: string): Promise<SiteWork[]> => (await api.get(`${B}/work-orders/${id}/site-work`)).data
export const countSiteWork = async (id: string, activity_quantity_id: string, line_id: string) => (await api.post(`${B}/work-orders/${id}/site-work`, { activity_quantity_id, line_id })).data
export const checkBill = async (id: string, body: BillIn): Promise<BillCheck> => (await api.post(`${B}/work-orders/${id}/bills/check`, body)).data
export const recordBill = async (id: string, body: BillIn): Promise<{ bill: WoBill; check: BillCheck }> => (await api.post(`${B}/work-orders/${id}/bills`, body)).data
export const decideBill = async (billId: string, decision: 'approve' | 'reject', reason: string) => (await api.post(`${B}/bills/${billId}/${decision}`, { reason })).data
export const releaseRetention = async (id: string, body: { amount?: string; note?: string }) => (await api.post(`${B}/work-orders/${id}/retention/release`, body)).data
export const giveAdvance = async (id: string, body: { account_id: string; amount: string; paid_date?: string; reference?: string; method?: string }) => (await api.post(`${B}/work-orders/${id}/advance`, body)).data
export const fetchTeamLines = async (id: string): Promise<{ id: string; date: string; trade: string; headcount: number; site: string | null; theirs: boolean; other_team: boolean }[]> => (await api.get(`${B}/work-orders/${id}/attendance`)).data
export const markTeam = async (id: string, line_ids: string[], theirs: boolean) => (await api.post(`${B}/work-orders/${id}/attendance`, { line_ids, theirs })).data
export const fetchBillsWaiting = async (): Promise<WoBill[]> => (await api.get(`${B}/bills/waiting`)).data

export interface Statement {
  vendor: { id: string; name: string; phone: string | null; gstin: string | null }
  as_of: string
  totals: Record<'value' | 'measured_value' | 'billed' | 'approved' | 'paid' | 'retention_held' | 'advance_given' | 'advance_recovered' | 'advance_left' | 'payable_now' | 'tds', string>
  work_orders: (Pick<WorkOrder, 'id' | 'ref' | 'status' | 'title' | 'project_name' | 'site_name' | 'lines' | 'totals' | 'retention_pct' | 'start_date' | 'end_date' | 'completed_on'> & { bills: WoBill[] })[]
}
export const fetchStatement = async (vendorId: string): Promise<Statement> => (await api.get(`${B}/vendors/${vendorId}/statement`)).data

export const n = (s: string | null | undefined) => Number(s ?? 0) || 0
export const woUrl = (id: string, tab?: string) => `/subcontract/work-orders/${id}${tab ? `?tab=${tab}` : ''}`

/** The text sent to the subcontractor on WhatsApp for a work order (opened in the sender's own WhatsApp). */
export function workOrderText(wo: WorkOrder, company: string): string {
  const lines = wo.lines.map((l, i) => `${i + 1}. ${l.description}: ${l.quantity} ${l.unit}${l.rate ? ` @ ₹${Number(l.rate).toLocaleString('en-IN')}` : ''}`).join('\n')
  return [`*${company} — Work order ${wo.ref}*`, wo.title ?? '', `${wo.project_name}${wo.site_name ? ` › ${wo.site_name}` : ''}`,
    wo.start_date ? `From ${wo.start_date}${wo.end_date ? ` to ${wo.end_date}` : ''}` : '', '', lines, '',
    wo.retention_pct ? `Retention ${Number(wo.retention_pct)}% of each bill, released after completion${wo.defect_days ? ` + ${wo.defect_days} days` : ''}.` : '',
    wo.terms ?? ''].filter((x, i, a) => x !== '' || (a[i - 1] ?? '') !== '').join('\n').trim()
}

export function waLink(phone: string | null | undefined, body: string): string {
  const digits = (phone ?? '').replace(/\D/g, '').replace(/^(\d{10})$/, '91$1')
  return `https://wa.me/${digits}?text=${encodeURIComponent(body)}`
}

/** Mirrors backend MATERIAL_REQUEST_ROLES: who gives work orders (owner, admin, project manager). */
export const OFFICE_ROLES = ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'PROJECT_MANAGER']
export const mayGiveWork = (role: string | null | undefined) => OFFICE_ROLES.includes((role ?? '').toUpperCase())

export function statementText(s: Statement, company: string): string {
  const t = s.totals
  const lines = s.work_orders.map((w) => `${w.ref} ${w.title ?? ''}: ${w.totals.progress_pct}% done, billed ${rupees(n(w.totals.billed))}, paid ${rupees(n(w.totals.paid))}`)
  return [`*${company} — statement for ${s.vendor.name}* (as of ${day(s.as_of)})`, ...lines, '',
    `Work orders ${rupees(n(t.value))} · billed ${rupees(n(t.billed))} · approved ${rupees(n(t.approved))}`,
    `Paid ${rupees(n(t.paid))} · TDS ${rupees(n(t.tds))} · advance still to recover ${rupees(n(t.advance_left))}`,
    `Retention held ${rupees(n(t.retention_held))} · *payable now ${rupees(n(t.payable_now))}*`].join('\n')
}
