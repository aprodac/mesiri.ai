import { api } from './api'

// PRC-48 (Materials > Stock count) and PRC-49 (Materials > Stock value): typed boundary for /materials/stock-counts
// and /materials/stock-value. The rules (frozen book, differences, approval into the ledger, the average rate) are the
// API's.

export type CountStatus = 'open' | 'approved' | 'cancelled'
export type CountReason = 'wastage' | 'theft' | 'wrong_entry' | 'unrecorded_use' | 'found' | 'other'

export const COUNT_REASONS: { value: CountReason; label: string }[] = [
  { value: 'wastage', label: 'Wastage' },
  { value: 'unrecorded_use', label: 'Use not recorded' },
  { value: 'wrong_entry', label: 'Wrong entry' },
  { value: 'theft', label: 'Theft' },
  { value: 'found', label: 'Found extra' },
  { value: 'other', label: 'Other' },
]

export interface CountLine {
  material_id: string
  material: string
  unit: string
  unit_id: string
  main_category: string
  book: string
  counted: string | null
  difference: string | null
  reason: CountReason | null
  rate?: string | null
  difference_value?: string | null
}

export interface StockCount {
  id: string
  number: number
  ref: string
  status: CountStatus
  project_id: string
  project_name: string
  site_id: string
  site_name: string
  scope: 'all' | 'category' | 'top'
  category_name: string | null
  created_by_name: string | null
  created_at: string
  approved_by_name: string | null
  approved_at: string | null
  counts: { lines: number; counted: number; not_counted: number; differing: number }
  net_value?: string
  gross_value?: string
  may_count: boolean
  may_approve: boolean
  lines?: CountLine[]
}

export interface CountList {
  items: StockCount[]
  total: number
  due: { site_id: string; site_name: string; project_name: string; last_counted: string | null }[]
  last_counted: Record<string, string>
}

export async function fetchCounts(): Promise<CountList> {
  return (await api.get<CountList>('/materials/stock-counts')).data
}

export async function fetchCount(id: string): Promise<StockCount> {
  return (await api.get<StockCount>(`/materials/stock-counts/${id}`)).data
}

export async function startCount(body: { site_id: string; scope: 'all' | 'category' | 'top'; category_id?: string | null }): Promise<StockCount> {
  return (await api.post<StockCount>('/materials/stock-counts', body)).data
}

export async function saveCountLines(id: string, lines: { material_id: string; counted: string | null; reason?: CountReason | null }[]): Promise<StockCount> {
  return (await api.put<StockCount>(`/materials/stock-counts/${id}/lines`, { lines })).data
}

export async function approveCount(id: string): Promise<StockCount> {
  return (await api.post<StockCount>(`/materials/stock-counts/${id}/approve`)).data
}

export async function cancelCount(id: string, reason: string): Promise<StockCount> {
  return (await api.post<StockCount>(`/materials/stock-counts/${id}/cancel`, { reason })).data
}

export interface ValueRow {
  site_id: string | null
  site_name: string
  project_id: string
  material_id: string
  material: string
  unit: string
  category: string | null
  main_category: string
  on_hand: string
  rate: string | null
  value: string | null
  used_30d: string
  slow_moving: boolean
}

export interface StockValue {
  as_of: string | null
  total: string
  items: number
  unpriced: number
  slow_moving: number
  slow_moving_value: string
  by_category: { category: string; value: string }[]
  top: ValueRow[]
  rows: ValueRow[]
}

export async function fetchStockValue(params: { project_id?: string | null; site_id?: string | null }): Promise<StockValue> {
  const clean = Object.fromEntries(Object.entries(params).filter(([, v]) => v))
  return (await api.get<StockValue>('/materials/stock-value', { params: clean })).data
}
