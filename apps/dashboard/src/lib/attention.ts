import { api } from './api'

// GM-04: the attention feed -- what crossed a line, for this person. Shapes mirror
// backend/src/mesiri/domains/attention (rules.py builds an alert; router.py the routes).

export type AlertKind = 'handover' | 'budget' | 'cost' | 'late' | 'order' | 'issue' | 'unreported' | 'hire'
export type AlertSeverity = 'bad' | 'warn'

export interface Alert {
  /** Names the thing (e.g. issue:<id>); a snooze holds on it. */
  key: string
  kind: AlertKind
  severity: AlertSeverity
  /** What crossed the line. */
  title: string
  /** By how much, in words. */
  detail: string
  project_id: string | null
  project_name: string | null
  site_name: string | null
  since: string | null
  action: { label: string; link: string }
}

export interface AttentionFeed {
  date: string
  items: Alert[]
  snoozed: Alert[]
  counts: { total: number; bad: number; warn: number; snoozed: number }
}

export const ATTENTION_KEY = ['attention'] as const

export async function fetchAttention(projectId?: string | null): Promise<AttentionFeed> {
  return (await api.get<AttentionFeed>('/attention', { params: projectId ? { project_id: projectId } : {} })).data
}

export async function fetchAttentionCount(projectId?: string | null): Promise<AttentionFeed['counts']> {
  const res = await api.get<{ counts: AttentionFeed['counts'] }>('/attention/count', { params: projectId ? { project_id: projectId } : {} })
  return res.data.counts
}

/** Not now: hidden for this person until `days` from today (1 = the rest of today). Back after, if still true. */
export async function snoozeAlert(key: string, days = 1): Promise<{ until: string }> {
  return (await api.post<{ key: string; until: string }>('/attention/snooze', { key, days })).data
}

export async function unsnoozeAlert(key: string): Promise<void> {
  await api.delete(`/attention/snooze/${encodeURIComponent(key)}`)
}

/** The page's tabs: what a GM thinks in, not the rule names. */
export const GROUPS: { key: string; label: string; kinds: AlertKind[] }[] = [
  { key: 'all', label: 'All', kinds: [] },
  { key: 'schedule', label: 'Schedule', kinds: ['handover', 'late'] },
  { key: 'cost', label: 'Cost', kinds: ['budget', 'cost'] },
  { key: 'materials', label: 'To order', kinds: ['order'] },
  { key: 'sites', label: 'Sites', kinds: ['unreported', 'issue'] },
  { key: 'machines', label: 'Machines', kinds: ['hire'] },
]

export const KIND_LABEL: Record<AlertKind, string> = {
  handover: 'Handover',
  budget: 'Budget',
  cost: 'Cost',
  late: 'Schedule',
  order: 'To order',
  issue: 'Issue',
  unreported: 'Not reported',
  hire: 'Hire bill',
}
