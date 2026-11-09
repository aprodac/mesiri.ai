import { api } from './api'

// TSK-02: the Tasks module -- who does what, by when. The shapes mirror backend/src/mesiri/domains/tasks
// (router.py describes the routes; logic.py the status moves and who may do what). Plan: docs/plans/tasks-plan.md.

export type TaskStatus = 'open' | 'doing' | 'blocked' | 'done' | 'cancelled'
export type TaskPriority = 'normal' | 'high' | 'urgent'

export interface Task {
  id: string
  ref: string
  number: number
  project_id: string
  project_name: string
  site_id: string | null
  site_name: string | null
  title: string
  notes: string | null
  status: TaskStatus
  priority: TaskPriority
  due_date: string | null
  assignee_user_id: string | null
  assignee_name: string | null
  assignee_vendor_id: string | null
  assignee_vendor_name: string | null
  assignee_team: string | null
  /** Whoever it is for, as one name: a person, a subcontractor or a team. */
  assigned_to: string | null
  place_id: string | null
  place_name: string | null
  work_package_id: string | null
  activity_name: string | null
  planned_item_id: string | null
  expected_quantity: string | null
  site_issue_id: string | null
  blocked_reason: string | null
  started_at: string | null
  done_at: string | null
  done_by: string | null
  source: 'web' | 'whatsapp'
  created_by: string | null
  created_by_name: string | null
  created_at: string
  updated_at: string
  overdue: boolean
  days_late: number
  /** The site issue it fixes (TSK-03). */
  issue: { id: string; type: string | null; narrative: string | null; status: string | null } | null
  /** The BOQ line its work counts against. */
  line: { id: string; work: string | null; unit: string | null } | null
  /** Work site recorded on that line since the task started, at its site; never typed (D-T4). */
  progress: { done: string; expected: string | null; unit: string | null; other_unit: number; pct: number | null } | null
}

export interface TaskEvent {
  id: string
  kind: 'created' | 'changed' | 'status' | 'comment'
  from_status: TaskStatus | null
  to_status: TaskStatus | null
  text: string | null
  photo_url: string | null
  changes: Record<string, [unknown, unknown]> | null
  source: 'web' | 'whatsapp'
  created_at: string
  actor_user_id: string | null
  actor_name: string | null
}

export interface TaskDetail extends Task {
  history: TaskEvent[]
  may: { edit: boolean; cancel: boolean; move: boolean; comment: boolean }
}

export interface TaskOptions {
  sites: { id: string; name: string }[]
  people: { id: string; name: string; role: string }[]
  subcontractors: { id: string; name: string }[]
  places: { id: string; label: string; site_id: string | null }[]
  lines: { id: string; work: string; unit: string; planned_quantity: string; work_package_id: string; section: string | null }[]
  may_create: boolean
}

export async function fetchTasks(params: {
  project_id?: string | null
  site_id?: string | null
  assignee?: string | null
  status?: string
  due?: 'overdue' | 'today' | 'week' | null
}): Promise<{ items: Task[]; today: string }> {
  const { data } = await api.get<{ items: Task[]; today: string }>('/tasks', {
    params: {
      project_id: params.project_id || undefined,
      site_id: params.site_id || undefined,
      assignee: params.assignee || undefined,
      status: params.status || undefined,
      due: params.due || undefined,
    },
  })
  return data
}

export async function fetchTask(id: string): Promise<TaskDetail> {
  const { data } = await api.get<TaskDetail>(`/tasks/${id}`)
  return data
}

export async function fetchTaskOptions(projectId: string): Promise<TaskOptions> {
  const { data } = await api.get<TaskOptions>('/tasks/options', { params: { project_id: projectId } })
  return data
}

export interface NewTask {
  project_id: string
  title: string
  notes?: string | null
  site_id?: string | null
  due_date?: string | null
  priority?: TaskPriority
  assignee_user_id?: string | null
  assignee_vendor_id?: string | null
  assignee_team?: string | null
  place_id?: string | null
  work_package_id?: string | null
  planned_item_id?: string | null
  expected_quantity?: string | null
  site_issue_id?: string | null
}

/** What a "Make a task" button already knows (an issue, a schedule activity): filled into the new task. */
export type TaskPrefill = Partial<Pick<NewTask, 'project_id' | 'title' | 'notes' | 'site_id' | 'work_package_id' | 'site_issue_id'>> & {
  /** Shown above the form: what the task is made from ("From the issue: No shuttering plates"). */
  from?: string
}

export async function createTask(payload: NewTask): Promise<Task> {
  const { data } = await api.post<Task>('/tasks', payload)
  return data
}

export async function updateTask(id: string, payload: Partial<Omit<NewTask, 'project_id'>>): Promise<Task> {
  const { data } = await api.patch<Task>(`/tasks/${id}`, payload)
  return data
}

export async function moveTask(id: string, status: TaskStatus, note?: string | null): Promise<Task> {
  const { data } = await api.post<Task>(`/tasks/${id}/status`, { status, note: note || null })
  return data
}

export async function commentOnTask(id: string, text: string): Promise<void> {
  await api.post(`/tasks/${id}/comments`, { text })
}

/** "Which person / site?": the choices the API sent back when the words fit several or none. */
export function choicesOf(err: unknown): { message: string; options: string[] } | null {
  const res = (err as { response?: { status?: number; data?: { detail?: unknown } } })?.response
  const d = res?.status === 422 ? (res.data?.detail as { message?: string; options?: string[] } | undefined) : undefined
  return d && typeof d.message === 'string' && Array.isArray(d.options) ? { message: d.message, options: d.options } : null
}

export const STATUS_LOOK: Record<TaskStatus, { label: string; chip: string; dot: string }> = {
  open: { label: 'Open', chip: 'bg-stone-200 text-stone-800 dark:bg-stone-700 dark:text-stone-100', dot: 'bg-stone-500' },
  doing: { label: 'In progress', chip: 'bg-info-soft text-info', dot: 'bg-blue-600' },
  blocked: { label: 'Blocked', chip: 'bg-orange-200 text-orange-950 dark:bg-orange-900 dark:text-orange-100', dot: 'bg-orange-500' },
  done: { label: 'Done', chip: 'bg-success-soft text-success', dot: 'bg-green-700' },
  cancelled: { label: 'Cancelled', chip: 'bg-muted text-muted-foreground', dot: 'bg-muted-foreground/60' },
}

/** Who gives tasks (backend logic.CREATE_ROLES); the API refuses the rest. */
export const CREATE_ROLES = ['OWNER', 'ADMIN', 'SUPER_ADMIN', 'PROJECT_MANAGER', 'SITE_ENGINEER']

export const PRIORITY_LABEL: Record<TaskPriority, string> = { normal: 'Normal', high: 'High', urgent: 'Urgent' }

/** A due day as people say it: "Today", "Tomorrow", "Thu 12 Nov", "3 days late". */
export function dueWords(task: Pick<Task, 'due_date' | 'overdue' | 'days_late' | 'status'>, today: string): string {
  if (!task.due_date) return 'No date'
  if (task.overdue) return task.days_late === 1 ? '1 day late' : `${task.days_late} days late`
  const days = Math.round((Date.parse(task.due_date) - Date.parse(today)) / 86_400_000)
  if (task.status === 'done' || task.status === 'cancelled' || days > 6 || days < 0) {
    return new Date(`${task.due_date}T00:00:00`).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })
  }
  if (days === 0) return 'Today'
  if (days === 1) return 'Tomorrow'
  return new Date(`${task.due_date}T00:00:00`).toLocaleDateString('en-IN', { weekday: 'long' })
}

/** What happened, in a line, for the history. */
export function eventWords(e: TaskEvent): string {
  if (e.kind === 'created') return 'gave the task'
  if (e.kind === 'comment') return e.photo_url && !e.text ? 'sent a photo' : 'commented'
  if (e.kind === 'status' && e.to_status) {
    if (e.to_status === 'open') return e.from_status === 'done' || e.from_status === 'cancelled' ? 'reopened it' : 'moved it back to open'
    if (e.to_status === 'doing') return 'started it'
    if (e.to_status === 'blocked') return 'marked it blocked'
    if (e.to_status === 'done') return 'finished it'
    return 'cancelled it'
  }
  const fields = Object.keys(e.changes ?? {}).map((k) => FIELD_WORDS[k] ?? k.replace(/_/g, ' '))
  return fields.length ? `changed ${fields.join(', ')}` : 'changed it'
}

const FIELD_WORDS: Record<string, string> = {
  due_date: 'the due day', assignee_user_id: 'who it is for', assignee_vendor_id: 'who it is for',
  assignee_team: 'who it is for', site_id: 'the site', place_id: 'the place', title: 'the title', notes: 'the notes',
  priority: 'the priority',
}
