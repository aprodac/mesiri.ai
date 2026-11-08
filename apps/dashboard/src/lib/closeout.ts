import { api } from './api'
import type { ProjectReceivable } from './billing'

// END-01 snag list and END-03 handover checklist. Backend: domains/closeout/router.py.
// Anyone on the project raises a snag and says it is fixed; owner, admin, finance and PM close or reopen it.

export type SnagStatus = 'open' | 'fixed' | 'closed'

export interface Snag {
  id: string
  ref: string
  project_id: string
  project_name: string
  site_id: string | null
  site_name: string | null
  number: number
  place: string | null
  description: string
  trade: string | null
  vendor_id: string | null
  vendor_name: string | null
  found_by: 'us' | 'client'
  phase: 'before_handover' | 'defects'
  status: SnagStatus
  status_label: string
  due_on: string | null
  fixed_note: string | null
  fixed_at: string | null
  closed_at: string | null
  reopened_note: string | null
  created_at: string
  raised_by_name: string | null
}

export interface SnagList {
  snags: Snag[]
  counts: Record<SnagStatus, number>
  can_manage: boolean
}

export interface SnagInput {
  description?: string
  place?: string | null
  site_id?: string | null
  trade?: string | null
  vendor_id?: string | null
  found_by?: 'us' | 'client'
  due_on?: string | null
}

export const SNAG_STATUS: Record<SnagStatus, { label: string; tone: string }> = {
  open: { label: 'Open', tone: 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200' },
  fixed: { label: 'Fixed, to check', tone: 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200' },
  closed: { label: 'Closed', tone: 'bg-success-soft text-success' },
}

export async function fetchSnags(params: { projectId?: string | null; status?: string | null }): Promise<SnagList> {
  return (await api.get<SnagList>('/snags', { params: { project_id: params.projectId || undefined, status: params.status || undefined } })).data
}

export async function raiseSnag(projectId: string, body: SnagInput): Promise<Snag> {
  return (await api.post<Snag>(`/projects/${projectId}/snags`, body)).data
}

export async function updateSnag(id: string, body: SnagInput): Promise<Snag> {
  return (await api.patch<Snag>(`/snags/${id}`, body)).data
}

export async function snagFixed(id: string, note?: string): Promise<Snag> {
  return (await api.post<Snag>(`/snags/${id}/fixed`, { note: note || null })).data
}

export async function closeSnag(id: string): Promise<Snag> {
  return (await api.post<Snag>(`/snags/${id}/close`)).data
}

export async function reopenSnag(id: string, reason: string): Promise<Snag> {
  return (await api.post<Snag>(`/snags/${id}/reopen`, { reason })).data
}

export async function deleteSnag(id: string) {
  await api.delete(`/snags/${id}`)
}

export type HandoverStepKey = 'work' | 'snags' | 'subcontracts' | 'final_bill' | 'paid' | 'handover' | 'defects' | 'retention'

export interface HandoverStep {
  key: HandoverStepKey
  title: string
  done: boolean
  detail: string
  link?: string
  optional?: boolean
}

export interface Handover {
  project: { id: string; name: string; stage: string; stage_label: string }
  today: string
  steps: HandoverStep[]
  next: HandoverStepKey | null
  done: number
  total: number
  ready_to_close: boolean
  handed_over_on: string | null
  defects_end: string | null
  defect_liability_months: number | null
  snags: { open: number; fixed: number; closed: number; total: number; defects_pending: number }
  money: ProjectReceivable | null
  can_edit: boolean
  can_see_money: boolean
}

export async function fetchHandover(projectId: string): Promise<Handover> {
  return (await api.get<Handover>(`/projects/${projectId}/handover`)).data
}

export async function setHandover(projectId: string, body: { handed_over_on?: string; clear?: boolean }): Promise<Handover> {
  return (await api.patch<Handover>(`/projects/${projectId}/handover`, body)).data
}
