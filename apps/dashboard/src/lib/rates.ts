import { api } from './api'
import { swatch } from './requests'

// PRC-14 / PRC-16: what each item cost, from which supplier, over time. Backend: domains/procurement/rates_router.py.
// Rates are per the item's stock unit, as recorded (with or without GST as entered). Only the roles that see spending.

export type RateTrend = 'up' | 'down' | 'same' | null

export interface RateVendor {
  /** The vendor record's id, or "name:<typed name>" for a supplier typed without one. */
  key: string
  vendor_id: string | null
  name: string
  purchases: number
  quantity: string
  spend: string
  avg_rate: string
  min_rate: string
  max_rate: string
  last_rate: string
  last_date: string
  /** The cheapest supplier's average in the period (only when more than one supplied it). */
  best: boolean
}

export interface RateItem {
  material_id: string
  material_name: string
  unit: string
  category_id: string | null
  category: string | null
  main_category: string | null
  purchases: number
  /** PRC-34: purchases compared as entered because their GST was not said. */
  gst_unknown: number
  quantity: string
  spend: string
  avg_rate: string
  min_rate: string
  max_rate: string
  last: { rate: string; date: string; vendor_key: string; vendor_name: string; site_name: string }
  /** The purchase before the last one (in the period, or the last one before it). */
  previous: { rate: string; date: string; vendor_name: string; in_period: boolean } | null
  change_pct: string | null
  trend: RateTrend
  best: { vendor_key: string; vendor_name: string; avg_rate: string } | null
  /** Paid above the cheapest supplier's average for what was bought in the period. */
  above_best: string
  vendors: RateVendor[]
  points: { date: string; rate: string; vendor_key: string }[]
}

export interface RatesResponse {
  date_from: string
  date_to: string
  items: RateItem[]
  summary: { items: number; purchases: number; spend: string; rising: number; falling: number; above_best: string }
}

export interface RatePurchase {
  id: string
  date: string
  vendor_key: string
  vendor_id: string | null
  vendor_name: string
  project_id: string
  project_name: string
  site_id: string | null
  site_name: string
  quantity: string
  unit: string
  rate: string
  amount: string
  source: 'bill' | 'order' | 'delivery'
  order_id: string | null
  order_ref: string | null
  ordered_rate: string | null
  differs_from_order: boolean
  invoice_number: string | null
  /** PRC-34: `rate` is what a unit costs the company (before GST when the supplier has a GSTIN, else with GST). */
  rate_entered: string
  rate_with_gst: string
  rate_before_gst: string
  gst_percent: string | null
  rate_includes_gst: boolean | null
  gst_known: boolean
  gst_claimable: boolean
}

export interface RateFilters {
  date_from?: string
  date_to?: string
  project_id?: string
  site_id?: string
  vendor_id?: string
}

export async function fetchRates(filters: RateFilters = {}): Promise<RatesResponse> {
  const res = await api.get<RatesResponse>('/procurement/rates', { params: filters })
  return res.data
}

export async function fetchRatePurchases(materialId: string, filters: RateFilters = {}): Promise<RatePurchase[]> {
  const res = await api.get<{ purchases: RatePurchase[] }>(`/procurement/rates/${materialId}`, { params: filters })
  return res.data.purchases
}

/** "₹410" / "₹1,250.50": rates keep their paise, amounts round to rupees elsewhere. */
export function rate(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  return `₹${Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
}

/** "3 Nov" (this year) or "3 Nov 25". */
export function shortDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`)
  const sameYear = d.getFullYear() === new Date().getFullYear()
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', ...(sameYear ? {} : { year: '2-digit' }) })
}

export type RatePeriod = '30d' | '90d' | '180d' | '365d' | 'custom'

export const RATE_PERIODS: { value: RatePeriod; label: string }[] = [
  { value: '30d', label: 'Last 30 days' },
  { value: '90d', label: 'Last 3 months' },
  { value: '180d', label: 'Last 6 months' },
  { value: '365d', label: 'Last 12 months' },
  { value: 'custom', label: 'Pick dates…' },
]

export function ratePeriodRange(period: RatePeriod, from: string, to: string): { date_from?: string; date_to?: string } {
  if (period === 'custom') return { date_from: from || undefined, date_to: to || undefined }
  const days = { '30d': 30, '90d': 90, '180d': 180, '365d': 365 }[period]
  const d = new Date()
  d.setDate(d.getDate() - (days - 1))
  return { date_from: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}` }
}

/** A supplier keeps one colour everywhere (chart dot, bar, filter). */
export const vendorColour = (key: string) => swatch(key)
