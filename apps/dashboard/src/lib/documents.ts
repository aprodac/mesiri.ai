import { api } from './api'

// DOC-01: a project's documents and drawings register. Backend: backend/src/mesiri/domains/documents/router.py.
// Who sees what (D-DOC1): contract, BOQ / estimate, work orders and restricted papers only for owner, admin, finance
// and project managers; the API filters every read.

export type Folder = 'contract' | 'drawing' | 'approval' | 'boq' | 'work_order' | 'test_report' | 'handover' | 'other'

export const FOLDER_NAMES: Record<Folder, string> = {
  drawing: 'Drawings',
  approval: 'Approvals & permits',
  contract: 'Contract',
  boq: 'BOQ & estimate',
  work_order: 'Work orders',
  test_report: 'Test reports',
  handover: 'Handover',
  other: 'Other',
}
export const FOLDER_ORDER: Folder[] = ['drawing', 'approval', 'contract', 'boq', 'work_order', 'test_report', 'handover', 'other']
export const DISCIPLINE_NAMES: Record<string, string> = { architectural: 'Architectural', structural: 'Structural', mep: 'MEP', other: 'Other' }

export interface ProjectDocument {
  id: string
  project_id: string
  folder: Folder
  discipline: string | null
  number: string | null
  title: string
  revision: string | null
  revision_date: string | null
  status: 'current' | 'superseded' | 'archived'
  valid_until: string | null
  restricted: boolean
  restricted_by_folder: boolean
  file_name: string
  content_type: string
  size_bytes: number
  pages: number | null
  source: 'web' | 'whatsapp'
  has_facts: boolean
  uploaded_by_name: string | null
  created_at: string
  /** PRC-52: a delivery's test certificate names its GRN. */
  goods_receipt_id?: string | null
  goods_receipt_number?: number | null
  notes?: string | null
}

export interface DocumentsList {
  project: { id: string; name: string }
  documents: ProjectDocument[]
  counts: Partial<Record<Folder, number>>
  expiring: { id: string; title: string; folder: Folder; valid_until: string }[]
  can_manage: boolean
  sees_restricted: boolean
}

export interface DocumentDetail extends ProjectDocument {
  url: string | null
  history: { id: string; revision: string | null; status: string; file_name: string; created_at: string }[]
  can_manage: boolean
  facts?: { floors: string[]; levels: { value: number; pages: number[] }[]; checks: { message?: string; text?: string }[]; pages: number; live_plan?: boolean }
}

export interface Uploaded extends ProjectDocument {
  guessed: string[]
  superseded: { id: string; revision: string | null } | null
  checks: number
}

export async function fetchDocuments(projectId: string, params: { folder?: string; q?: string; status?: string } = {}): Promise<DocumentsList> {
  return (await api.get<DocumentsList>(`/projects/${projectId}/documents`, { params })).data
}

export async function fetchDocument(id: string): Promise<DocumentDetail> {
  return (await api.get<DocumentDetail>(`/documents/${id}`)).data
}

export async function uploadDocument(projectId: string, file: File, fields: Record<string, string> = {}): Promise<Uploaded> {
  const form = new FormData()
  form.append('file', file)
  for (const [k, v] of Object.entries(fields)) if (v) form.append(k, v)
  return (await api.post<Uploaded>(`/projects/${projectId}/documents`, form)).data
}

export async function uploadRevision(id: string, file: File, revision?: string): Promise<Uploaded> {
  const form = new FormData()
  form.append('file', file)
  if (revision) form.append('revision', revision)
  return (await api.post<Uploaded>(`/documents/${id}/revisions`, form)).data
}

export async function updateDocument(id: string, body: Partial<Pick<ProjectDocument, 'folder' | 'discipline' | 'number' | 'title' | 'revision' | 'valid_until' | 'restricted'>>) {
  return (await api.patch<ProjectDocument>(`/documents/${id}`, body)).data
}

export async function archiveDocument(id: string) {
  return (await api.delete(`/documents/${id}`)).data
}

export function fileSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}

/** The register's limit (D-DOC4). */
export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024

/** The server's words for a refused upload or change (a string, a {message} or a list). */
export function documentError(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object' && 'message' in detail) return String((detail as { message: unknown }).message)
  if (Array.isArray(detail)) return detail.map((d) => (typeof d === 'string' ? d : (d as { msg?: string }).msg ?? '')).join(' ')
  return err instanceof Error ? err.message : 'Something went wrong.'
}
