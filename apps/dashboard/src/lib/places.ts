import { api } from './api'

// LP-01..05: a project's floors and rooms, progress by place, the work and photos at a place.
// Backend: backend/src/mesiri/domains/places/router.py. Work is put at a place by the work entry itself (WhatsApp or
// POST /progress/activities with `place`).

export interface Place {
  id: string
  parent_id: string | null
  name: string
  level_label: string
  /** "First Floor / Room-2" */
  label: string
  depth: number
  sort_order: number
}

export interface PlacesList {
  places: Place[]
  can_edit: boolean
  suggested: { floors: string[]; rooms: string[] }
}

export type CellState = 'done' | 'in_progress' | 'not_started'

export interface PlaceProgressRow extends Place {
  cells: Record<string, { state: CellState; last: string | null }>
  left: string[]
  done: string[]
  photos: number
  last_update: string | null
}

export interface PlacesProgress {
  place: string | null
  kinds: { key: string; name: string }[]
  places: PlaceProgressRow[]
  set_up?: boolean
}

export interface PlaceWork {
  id: string
  date: string
  work_type: string | null
  narrative: string | null
  finished: boolean
  place: string
  reported_by: string | null
  photos: string[]
}

const base = (projectId: string) => `/projects/${projectId}/places`

export async function fetchPlaces(projectId: string): Promise<PlacesList> {
  return (await api.get<PlacesList>(base(projectId))).data
}

export async function fetchPlacesProgress(projectId: string): Promise<PlacesProgress> {
  return (await api.get<PlacesProgress>(`${base(projectId)}/progress`)).data
}

export async function setupPlaces(projectId: string, floors: string[], rooms: string[]) {
  return (await api.post<{ made: { floors: number; rooms: number } }>(`${base(projectId)}/setup`, { floors, rooms })).data
}

export async function addPlace(projectId: string, name: string, parentId: string | null) {
  return (await api.post<Place>(base(projectId), { name, parent_id: parentId })).data
}

export async function renamePlace(projectId: string, placeId: string, name: string) {
  return (await api.patch(`${base(projectId)}/${placeId}`, { name })).data
}

export async function removePlace(projectId: string, placeId: string) {
  return (await api.delete<{ outcome: 'deleted' | 'archived' }>(`${base(projectId)}/${placeId}`)).data
}

export async function fetchPlaceWork(projectId: string, placeId: string) {
  return (await api.get<{ place: Place; work: PlaceWork[] }>(`${base(projectId)}/${placeId}/work`)).data
}

/** Lines of a textarea as names: trimmed, blank lines and repeats dropped. */
export function nameLines(text: string): string[] {
  const out: string[] = []
  for (const line of text.split('\n')) {
    const name = line.trim().replace(/\s+/g, ' ')
    if (name && !out.some((o) => o.toLowerCase() === name.toLowerCase())) out.push(name)
  }
  return out
}
