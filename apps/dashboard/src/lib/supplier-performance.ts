import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import { useAuth } from './AuthContext'
import { MONEY_ROLES } from './module-map'

// PRC-50: supplier performance -- a 0-5 score worked out from orders, GRNs, rates and quotes, never typed.
// Backend: domains/vendors/performance.py, routes in procurement/rates_router.py. The roles that see rates only.

export type Measure = 'on_time' | 'complete' | 'quality' | 'price'

export interface SupplierPerformance {
  vendor_id: string
  deliveries: number
  orders_finished: number
  /** At least `min_deliveries` GRNs in the last 12 months; else no score ("Not enough orders yet"). */
  enough: boolean
  min_deliveries: number
  score: string | null
  measures: {
    on_time: { pct: string | null; of: number; score: string | null; weight: number }
    complete: { pct: string | null; of: number; score: string | null; weight: number }
    rejected: { pct: string | null; of: number; score: string | null; weight: number }
    price: { index: string | null; items: number; score: string | null; weight: number }
    quote_response: { pct: string | null; quoted: number; asked: number }
  }
  trend: { month: string; score: string | null }[]
  problems: { date: string; kind: 'late' | 'rejected' | 'short'; what: string; grn_id: string | null; grn_ref: string | null; order_id: string; order_ref: string }[]
  rating: { stars: string; count: number; last_note: string | null } | null
}

export async function fetchSupplierPerformance(vendorId: string): Promise<SupplierPerformance> {
  return (await api.get<SupplierPerformance>(`/procurement/rates/suppliers/${vendorId}/performance`)).data
}

export async function fetchSuppliersPerformance(): Promise<SupplierPerformance[]> {
  return (await api.get<{ items: SupplierPerformance[] }>('/procurement/rates/suppliers/performance')).data.items
}

export function useSeesScores(): boolean {
  const { me } = useAuth()
  return (MONEY_ROLES as readonly string[]).includes((me?.role || '').toUpperCase())
}

/** Every supplier's score by vendor id: one request shared by the list, the pickers and the comparison sheet. */
export function useSupplierScores(enabled = true): Map<string, SupplierPerformance> {
  const sees = useSeesScores()
  const { data } = useQuery({ queryKey: ['procurement', 'performance'], queryFn: fetchSuppliersPerformance, enabled: sees && enabled, staleTime: 5 * 60_000, retry: false })
  return new Map((data ?? []).map((p) => [p.vendor_id, p]))
}

/** "On time 66.7% (of 3) · 2.5 / 5 × 35%": the breakdown shown on hover. */
export function scoreBreakdown(p: SupplierPerformance): string {
  const m = p.measures
  const line = (label: string, value: string, part: { score: string | null; weight: number }) =>
    `${label}: ${value}${part.score !== null ? ` → ${part.score}/5 × ${part.weight}%` : ' (not counted)'}`
  return [
    line('On time', m.on_time.pct !== null ? `${m.on_time.pct}% of ${m.on_time.of}` : 'no dated deliveries', m.on_time),
    line('Complete', m.complete.pct !== null ? `${m.complete.pct}% of ${m.complete.of} finished orders` : 'no finished orders', m.complete),
    line('Rejected', m.rejected.pct !== null ? `${m.rejected.pct}%` : 'nothing received', m.rejected),
    line('Price', m.price.index !== null ? `${m.price.index}× the average on ${m.price.items} item${m.price.items === 1 ? '' : 's'}` : 'no item bought from another supplier too', m.price),
    `Quotes: ${m.quote_response.asked ? `${m.quote_response.quoted} of ${m.quote_response.asked} (shown, not scored)` : 'never asked'}`,
    p.enough ? '' : `Not enough orders yet: ${p.deliveries} of ${p.min_deliveries} deliveries`,
  ].filter(Boolean).join('\n')
}
