import { api } from './api'

// DR-10 / DR-11: Live plans. Every current drawing page with footings or rooms as a live map: each marker coloured by
// the work site reported there (overall and per trade), with its newest photos; plus the newest updates.
// Backend: backend/src/mesiri/domains/documents/live.py, GET /projects/{id}/live-maps, POST /documents/{id}/track.

export type LiveState = 'done' | 'in_progress' | 'not_started'

export interface LiveMarker {
  key: string
  label: string
  sub: string | null
  /** 0..1 of the page, from the left / top. */
  x: number
  y: number
  place_id: string | null
  state: LiveState
  /** Per trade (work kind key). */
  cells: Record<string, LiveState>
  last_work: string | null
  last_date: string | null
  updates: number
  photos: number
  thumbs: string[]
  /** Changed in the last 48 hours. */
  fresh: boolean
  area_sqm?: number | null
  area_sqft?: number | null
  concrete_cum?: number | null
  steel_kg?: number | null
}

export interface LiveMap {
  id: string
  kind: 'foundation' | 'floor'
  name: string
  document: { id: string; number: string | null; title: string; revision: string | null }
  page: number
  image_url: string | null
  image_width: number | null
  image_height: number | null
  tracked: boolean
  markers: LiveMarker[]
  kinds: { key: string; name: string; done: number; started: number; total: number }[]
  summary: { done: number; in_progress: number; not_started: number; count: number; photos: number; concrete_done_cum?: number; concrete_cum?: number; steel_done_kg?: number; steel_kg?: number }
}

export interface LiveFeedItem {
  id: string
  place: string | null
  place_id: string
  map_id: string | null
  work: string | null
  finished: boolean
  who: string | null
  date: string
  at: string
  via: 'WhatsApp' | 'Dashboard'
  photo: string | null
}

export interface LiveMaps {
  maps: LiveMap[]
  feed: LiveFeedItem[]
  can_track: boolean
  untracked: { id: string; number: string | null; title: string; revision: string | null }[]
}

export async function fetchLiveMaps(projectId: string): Promise<LiveMaps> {
  return (await api.get<LiveMaps>(`/projects/${projectId}/live-maps`)).data
}

export async function trackOnSite(documentId: string) {
  return (await api.post<{ made?: number; tracked?: number; rooms?: { made: number; tracked: number } }>(`/documents/${documentId}/track`)).data
}

export function timeAgo(iso: string, now = Date.now()): string {
  const s = Math.max(0, (now - new Date(iso).getTime()) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  const d = Math.floor(s / 86400)
  return d === 1 ? 'yesterday' : `${d} days ago`
}

export const STATE_WORD: Record<LiveState, string> = { done: 'Done', in_progress: 'In progress', not_started: 'Not started' }

/** A marker's state: overall, or for one trade when one is picked. */
export function stateFor(m: LiveMarker, trade: string | null): LiveState {
  return trade ? (m.cells[trade] ?? 'not_started') : m.state
}
