import { api } from './api'
import { recordUrl } from './links'

// ADM-02 / ADM-03: the company activity log (who changed what, when) and handing over a person's open work.
// Backend: domains/audit/activity_router.py (GET /activity), domains/users/handover_router.py. Owner and admins.

export interface ActivityItem {
  id: string
  at: string
  actor_user_id: string | null
  actor_name: string | null
  actor_role: string | null
  source: 'web' | 'whatsapp'
  method: string
  route: string
  action: string
  record_kind: string | null
  record_id: string | null
  record_label: string | null
  path_ids: Record<string, string>
}

export interface ActivityPage {
  items: ActivityItem[]
  people: { id: string; name: string }[]
  next: string | null
}

export interface ActivityFilters {
  user_id?: string
  source?: 'web' | 'whatsapp'
  date_from?: string
  q?: string
}

export async function fetchActivity(filters: ActivityFilters, before?: string | null): Promise<ActivityPage> {
  const params = Object.fromEntries(Object.entries({ ...filters, before: before ?? undefined }).filter(([, v]) => v))
  const data = (await api.get<Partial<ActivityPage>>('/activity', { params })).data ?? {}
  return { items: data.items ?? [], people: data.people ?? [], next: data.next ?? null }
}

/** Where a logged record opens, for the kinds whose page opens one record (lib/links.ts); otherwise no link. */
export function activityUrl(item: ActivityItem): string | null {
  const id = item.record_id
  if (!id) return null
  switch (item.record_kind) {
    case 'task':
      return recordUrl.task(id)
    case 'request':
      return item.route.startsWith('/procurement/requests') ? recordUrl.request(id) : null
    case 'order':
      return item.route.startsWith('/procurement/orders') ? recordUrl.order(id) : null
    case 'work_order':
      return `/subcontract/work-orders/${id}`
    case 'user':
      return `/team/${id}`
    case 'project':
      return `/projects/${id}`
    default:
      return null
  }
}

// -- ADM-03: hand over open work -----------------------------------------------------------------------------

export interface HandoverTask { id: string; ref: string; title: string; status: string; due_date: string | null; project_name: string }
export interface HandoverActivity { id: string; name: string; project_name: string }
export interface Handover {
  from: { id: string; name: string }
  to: { id: string; name: string }
  tasks: HandoverTask[]
  activities: HandoverActivity[]
  left: { tasks: HandoverTask[]; activities: HandoverActivity[] }
  moved: { tasks: number; activities: number } | null
}

export async function handOver(userId: string, toUserId: string, preview: boolean): Promise<Handover> {
  return (await api.post<Handover>(`/users/${userId}/handover`, { to_user_id: toUserId, preview })).data
}
