import { api } from './api'
import { decideRequest } from './requests'
import { decideBill, decideMeasurement } from './subcontracts'
import { raBillAction } from './billing'
import { answerSizeRequest } from './materials'

// GM-01: "Waiting for you" -- one list over each module's own statuses. The shapes mirror
// backend/src/mesiri/domains/approvals (inbox.py builds a row; router.py the routes). Deciding always goes through
// the module's own route (decideRequest, decideBill, ...): this file only picks which one.

export type InboxKind = 'material_request' | 'subcontract_bill' | 'measurement' | 'ra_bill' | 'size_request'
export type InboxTone = 'ok' | 'warn' | 'bad' | 'info'
export type InboxGroup = 'flagged' | 'older' | 'recent'

export interface InboxRow {
  key: string
  kind: InboxKind
  id: string
  ref: string | null
  title: string
  project_id: string | null
  project_name: string | null
  site_id: string | null
  site_name: string | null
  asked_by: string | null
  since: string
  /** Only for the roles that see spending. A material request's is an estimate at the last rates. */
  amount: string | null
  flagged: boolean
  /** The one fact that decides it. */
  fact: string
  tone: InboxTone
  actions: string[]
  link: string
  group: InboxGroup
  extra: Record<string, unknown>
}

export type InboxCounts = Record<'total' | InboxGroup | InboxKind, number>

export interface Inbox {
  items: InboxRow[]
  counts: InboxCounts
}

/** The page's query key; the count badge uses ['approvals-count']. */
export const INBOX_KEY = ['approvals-inbox'] as const

export async function fetchInbox(projectId?: string | null): Promise<Inbox> {
  return (await api.get<Inbox>('/approvals/inbox', { params: projectId ? { project_id: projectId } : {} })).data
}

export async function fetchInboxCount(projectId?: string | null): Promise<InboxCounts> {
  const res = await api.get<{ counts: InboxCounts }>('/approvals/inbox/count', { params: projectId ? { project_id: projectId } : {} })
  return res.data.counts
}

export const KIND_LOOK: Record<InboxKind, { label: string; plural: string; chip: string }> = {
  material_request: { label: 'Material request', plural: 'Requests', chip: 'bg-info-soft text-info' },
  subcontract_bill: { label: 'Subcontract bill', plural: 'Bills', chip: 'bg-ai-soft text-ai' },
  measurement: { label: 'Work to confirm', plural: 'Work', chip: 'bg-teal-100 text-teal-900 dark:bg-teal-950 dark:text-teal-100' },
  ra_bill: { label: 'RA bill to submit', plural: 'RA bills', chip: 'bg-success-soft text-success' },
  size_request: { label: 'Unit size', plural: 'Sizes', chip: 'bg-draft-soft text-draft' },
}

export const TONE_LOOK: Record<InboxTone, string> = {
  ok: 'bg-success-soft text-success',
  warn: 'bg-draft-soft text-draft',
  bad: 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200',
  info: 'bg-muted text-muted-foreground',
}

export const GROUP_LOOK: Record<InboxGroup, string> = {
  flagged: 'Flagged by a check',
  older: 'Waiting more than 2 days',
  recent: 'Recent',
}

/** What a button says and does. `reason`: the module refuses it without one. `primary`: the main yes. */
export interface InboxAction {
  action: string
  label: string
  /** What the toast says once it is done. */
  done: string
  primary?: boolean
  danger?: boolean
  reason?: 'required' | 'optional'
  /** The size answer: a number in the stock unit. */
  number?: boolean
}

export function actionsFor(row: InboxRow): InboxAction[] {
  switch (row.kind) {
    case 'material_request':
      return [
        { action: 'ordered', label: 'Mark ordered', done: 'marked ordered', primary: true },
        { action: 'sent', label: 'Sent from a site', done: 'marked sent from a site', reason: 'optional' },
        { action: 'rejected', label: 'Not ordering', done: 'not ordering it', danger: true, reason: 'required' },
      ]
    case 'subcontract_bill':
      return [
        { action: 'approve', label: row.flagged ? 'Approve anyway' : 'Approve', done: 'approved', primary: !row.flagged, reason: 'required' },
        { action: 'reject', label: 'Reject', done: 'rejected', danger: true, reason: 'required' },
      ]
    case 'measurement':
      return [
        { action: 'confirm', label: 'Confirm', done: 'confirmed', primary: true },
        { action: 'reject', label: 'Reject', done: 'rejected', danger: true, reason: 'optional' },
      ]
    case 'ra_bill':
      return [{ action: 'submit', label: 'Submit to client', done: 'submitted to the client', primary: true }]
    case 'size_request':
      return [{ action: 'answer', label: 'Set the size', done: 'size set; the held lines are saved', primary: true, number: true }]
  }
}

/** The primary yes, when it is safe to give for many rows at once (D-GM2): nothing flagged, no reason or number
 *  needed, no money sent out. A request's "ordered" and an RA bill's "submit" are decisions about one record each. */
export function batchAction(row: InboxRow): InboxAction | null {
  if (row.flagged || row.kind !== 'measurement') return null
  return actionsFor(row).find((a) => a.primary) ?? null
}

/** Decide through the module's own route. */
export async function decide(row: InboxRow, action: string, note?: string): Promise<void> {
  switch (row.kind) {
    case 'material_request':
      await decideRequest(row.id, action as 'ordered' | 'sent' | 'rejected', note)
      return
    case 'subcontract_bill':
      await decideBill(row.id, action as 'approve' | 'reject', note ?? '')
      return
    case 'measurement':
      await decideMeasurement(row.id, action as 'confirm' | 'reject', note)
      return
    case 'ra_bill':
      await raBillAction(row.id, 'submit')
      return
    case 'size_request':
      await answerSizeRequest(row.id, Number(note))
      return
  }
}

/** "2 h", "3 d": how long it has waited. */
export function waited(iso: string, now = new Date()): string {
  const mins = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 60000))
  if (mins < 60) return `${mins} min`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours} h`
  return `${Math.round(hours / 24)} d`
}
