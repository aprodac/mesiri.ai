import { localIsoDate } from './site-day'

// The period filter shared by list pages (Materials ledger, Labour): a few
// presets plus a custom range, resolved against the browser's local date.

export type Period = '7d' | '30d' | 'month' | 'all' | 'custom'

export const PERIOD_OPTIONS: { value: Period; label: string }[] = [
  { value: '7d', label: '7 days' },
  { value: '30d', label: '30 days' },
  { value: 'month', label: 'This month' },
  { value: 'all', label: 'All' },
  { value: 'custom', label: 'Dates' },
]

/** The dates a period covers; `undefined` for an open end. */
export function periodRange(period: Period, from: string, to: string): { from?: string; to?: string } {
  const today = new Date()
  const back = (days: number) => localIsoDate(new Date(today.getFullYear(), today.getMonth(), today.getDate() - days))
  if (period === '7d') return { from: back(6) }
  if (period === '30d') return { from: back(29) }
  if (period === 'month') return { from: localIsoDate(new Date(today.getFullYear(), today.getMonth(), 1)) }
  if (period === 'custom') return { from: from || undefined, to: to || undefined }
  return {}
}
