import { api } from './api'

// DR-01..04: the drawing reader. Backend: domains/drawings (router.py, read.py). Nothing is stored.

export interface DrawingRoom {
  label: string
  a: number
  b: number
  size_text: string
  area: { value: number; unit: 'sqft' | 'sqm'; text: string } | null
  computed: { sqm: number; sqft: number }
  x: number
  top: number
}

export interface DrawingSheet {
  page: number
  has_text: boolean
  title: string | null
  kind: 'plan' | 'elevation' | 'section' | 'schedule' | 'detail' | 'site_plan' | null
  level: string | null
  discipline: string | null
  project: string | null
  client: string | null
  architect: string | null
  number: string | null
  revision: string | null
  drawn_by: string | null
  checked_by: string | null
  scale: string | null
  date: string | null
  units: string | null
  levels: { value: number; text: string }[]
  rooms: DrawingRoom[]
  fixtures: Record<string, number>
}

export interface DrawingCheck {
  kind: 'area_label' | 'level' | 'typical_floor' | 'missing' | 'no_text'
  severity: 'high' | 'medium' | 'low' | 'info'
  page: number | null
  sheet: string | null
  message: string
  why: string
}

export interface DrawingRead {
  file_name: string | null
  pages: number
  project: string | null
  client: string | null
  architect: string | null
  units: string | null
  sheets: DrawingSheet[]
  levels: { value: number; pages: number[] }[]
  floors: string[]
  fixtures: Record<string, number>
  checks: DrawingCheck[]
}

export async function readDrawing(file: File): Promise<DrawingRead> {
  const res = await api.post<DrawingRead>('/drawings/read', file, {
    headers: { 'Content-Type': 'application/pdf', 'X-File-Name': encodeURIComponent(file.name) },
    timeout: 120_000,
  })
  return res.data
}
