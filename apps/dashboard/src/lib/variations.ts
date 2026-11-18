import { api } from './api'

// NXT-04 / CC-24: extra or changed work the client asked for. Backend: domains/billing/variations.py. An approved one
// becomes a BOQ line (new work, code VO-xx in the "Variations" section) or more of a line, so the site's work on it is
// measured and billed on RA bills like any line.

export type VariationStatus = 'draft' | 'sent' | 'approved' | 'rejected' | 'cancelled'
export type VariationKind = 'new' | 'more'

export interface Variation {
  id: string
  ref: string
  number: number
  project_id: string
  project: string
  site_id: string | null
  site: string | null
  kind: VariationKind
  title: string
  description: string | null
  line: { id: string; code: string | null; work: string | null } | null
  unit: string
  quantity: string
  client_rate: string
  amount: string
  cost_estimate: string | null
  margin: string | null
  margin_pct: string | null
  days_added: number | null
  asked_by: string | null
  asked_on: string
  status: VariationStatus
  sent_on: string | null
  decided_on: string | null
  decided_by: string | null
  decision_note: string | null
  /** Days since it was sent (or asked, while a draft); null once decided. */
  waiting_days: number | null
  planned_item_id: string | null
  /** An approved new item: work measured on its BOQ line, and what RA bills took of it. */
  done: string | null
  billed: string | null
  billed_amount: string | null
  created_by_name: string | null
  created_at: string
}

export interface VariationSummary {
  counts: Record<VariationStatus, number>
  waiting: string
  draft: string
  approved: string
  rejected: string
  billed: string
  days_added: number
  not_priced: number
}

export interface VariationInput {
  kind?: VariationKind
  title?: string
  description?: string | null
  line_id?: string | null
  site_id?: string | null
  unit?: string | null
  quantity?: string
  client_rate?: string | null
  cost_estimate?: string | null
  days_added?: number | null
  asked_by?: string | null
  asked_on?: string | null
  send?: boolean
}

export async function fetchVariations(projectId?: string | null): Promise<{ date: string; items: Variation[]; summary: VariationSummary }> {
  return (await api.get('/billing/variations', { params: { project_id: projectId || undefined } })).data
}

export async function createVariation(projectId: string, body: VariationInput): Promise<Variation> {
  return (await api.post(`/projects/${projectId}/variations`, body)).data
}

export async function updateVariation(id: string, body: VariationInput): Promise<Variation> {
  const { kind: _k, line_id: _l, send: _s, ...rest } = body
  return (await api.patch(`/billing/variations/${id}`, rest)).data
}

export type VariationAct = 'send' | 'approve' | 'reject' | 'cancel'

export async function actOnVariation(id: string, act: VariationAct, body: { decided_by?: string | null; decided_on?: string | null; note?: string | null } = {}): Promise<Variation> {
  return (await api.post(`/billing/variations/${id}/${act}`, act === 'approve' || act === 'reject' ? body : undefined)).data
}

export async function deleteVariation(id: string): Promise<void> {
  await api.delete(`/billing/variations/${id}`)
}
