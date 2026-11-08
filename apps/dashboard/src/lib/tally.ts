import { api } from './api'

// NXT-12: a period's expenses and payments as Tally vouchers. Backend: domains/finance/tally_router.py.

export interface TallySummary {
  date_from: string
  date_to: string
  ledgers: number
  journals: number
  payments: number
  sales: number
  receipts: number
  gst_split: number
  gst_not_split: number
}

export async function fetchTallySummary(period: { date_from: string; date_to: string }): Promise<TallySummary> {
  return (await api.get<TallySummary>('/finance/tally/summary', { params: period })).data
}

export async function downloadTallyXml(period: { date_from: string; date_to: string }): Promise<{ blob: Blob; filename: string }> {
  const res = await api.get('/finance/tally/export', { params: period, responseType: 'blob' })
  return { blob: res.data as Blob, filename: `mesiri-tally-${period.date_from}-to-${period.date_to}.xml` }
}
