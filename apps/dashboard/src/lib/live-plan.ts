import { api } from './api'

// DR-10: a structural drawing's footing plan, each footing coloured by the work site reported at it.
// Backend: backend/src/mesiri/domains/documents/router.py (track, live). Footings are places (Foundation / B3), so
// "B3 footing concreted" on WhatsApp lands on B3.

export type FootingState = 'done' | 'in_progress' | 'not_started'

export interface LiveMarker {
  grid: string | null
  mark: string
  column: string | null
  size: string | null
  /** Position on the page, 0..1 from the left / top. */
  x: number
  y: number
  state: FootingState
  place_id: string | null
  last_work: string | null
  last_date: string | null
  updates: number
  photos: number
}

export interface LivePlan {
  document: { id: string; number: string | null; title: string; revision: string | null }
  project_id: string
  image_url: string | null
  image_width: number | null
  image_height: number | null
  page: number
  tracked: boolean
  can_track: boolean
  markers: LiveMarker[]
  summary: { done: number; in_progress: number; not_started: number; footings: number; concrete_done_cum: number; concrete_cum: number; steel_done_kg: number; steel_kg: number }
}

export async function fetchProjectLivePlan(projectId: string): Promise<LivePlan | null> {
  return (await api.get<{ live: LivePlan | null }>(`/projects/${projectId}/live-plan`)).data.live
}

export async function fetchDocumentLivePlan(documentId: string): Promise<LivePlan> {
  return (await api.get<LivePlan>(`/documents/${documentId}/live`)).data
}

export async function trackFootings(documentId: string) {
  return (await api.post<{ made: number; tracked: number; untracked: number }>(`/documents/${documentId}/track`)).data
}
