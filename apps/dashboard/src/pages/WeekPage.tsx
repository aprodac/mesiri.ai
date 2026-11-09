import * as React from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarCheck, ChevronLeft, ChevronRight, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useToast } from '@/components/ui/toast-notification'
import { NewTaskDialog } from '@/components/tasks/new-task-dialog'
import { ProjectPickList, usePlanningProject } from '@/components/schedule/project-picker'
import { usePageTitle } from '@/lib/page-title'
import { useReadOnly } from '@/lib/trial'
import { api } from '@/lib/api'
import { moveTask } from '@/lib/tasks'
import { recordUrl } from '@/lib/links'
import { errorDetail } from '@/lib/site-day'
import { cn } from '@/lib/utils'

// GM-05 (plan docs/plans/gm-pm-plan.md): Planning > This week. One project's week, Monday to Saturday: the schedule's
// activities in it (their progress comes from site updates, so they tick themselves), the Tasks module's tasks due
// in it (ticked here or on WhatsApp, given with the Tasks module's own dialog), and what slipped from earlier weeks.
// Read from GET /projects/{id}/week; nothing is stored by this page.

interface WeekActivity { id: string; name: string; site_name: string | null; start: string; end: string; progress: number | null; state: string; done: boolean; critical: boolean; days: string[]; finishes_this_week: boolean }
interface WeekTask { id: string; ref: string | null; title: string; due_date: string; status: string; done: boolean; assignee_name: string | null; site_name: string | null }
interface Slipped { kind: 'activity' | 'task'; id: string; name?: string; title?: string; days_late: number; progress?: number | null; assignee_name?: string | null }
interface Week {
  week_start: string; days: string[]; today: string
  activities: WeekActivity[]; tasks: WeekTask[]; slipped: Slipped[]
  counts: { activities: number; finishing: number; finished: number; critical: number; tasks: number; tasks_done: number; slipped: number }
  project: { id: string; name: string }; tasks_module: boolean
}

const fmt = (iso: string, opts: Intl.DateTimeFormatOptions) => new Date(iso + 'T00:00:00').toLocaleDateString('en-IN', opts)
const shift = (iso: string, days: number) => new Date(new Date(iso + 'T00:00:00').getTime() + days * 86_400_000).toISOString().slice(0, 10)

export default function WeekPage() {
  usePageTitle('This week')
  const projectId = usePlanningProject()
  if (!projectId) {
    return (
      <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
        <h1 className="text-2xl font-semibold tracking-tight">This week</h1>
        <p className="text-sm text-muted-foreground">Pick a project to see its week.</p>
        <ProjectPickList to={(id) => `/planning/week?project=${id}`} empty="No projects yet. Add one in Projects & Sites." />
      </div>
    )
  }
  return <WeekView key={projectId} projectId={projectId} />
}

function WeekView({ projectId }: { projectId: string }) {
  const [params, setParams] = useSearchParams()
  const start = params.get('week') ?? undefined
  const readOnly = useReadOnly()
  const [giving, setGiving] = React.useState(false)
  const qc = useQueryClient()
  const toast = useToast()
  const { data, isLoading, isError } = useQuery({
    queryKey: ['week', projectId, start],
    queryFn: async () => (await api.get<Week>(`/projects/${projectId}/week`, { params: start ? { start } : {} })).data,
  })
  const tick = useMutation({
    mutationFn: (t: WeekTask) => moveTask(t.id, t.done ? 'open' : 'done'),
    onSuccess: (_, t) => { toast.success(t.done ? 'Opened again' : 'Done', t.title); void qc.invalidateQueries({ queryKey: ['week', projectId] }) },
    onError: (e) => toast.error('Not changed', errorDetail(e) ?? 'Try again.'),
  })
  const go = (week: string) => setParams((p) => { p.set('week', week); return p })

  if (isLoading) return <div className="h-64 animate-pulse rounded-xl bg-muted/40" />
  if (isError || !data || !Array.isArray(data.days) || !data.counts) return <p className="p-4 text-sm text-destructive">This week did not load. Refresh to try again.</p>
  const c = data.counts
  const thisWeek = data.days.includes(data.today)

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="inline-flex size-10 items-center justify-center rounded-xl bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-200"><CalendarCheck className="size-5" /></span>
          <div>
            <div className="text-xs text-muted-foreground"><Link to={`/projects/${projectId}`} className="hover:underline">{data.project.name}</Link></div>
            <h1 className="text-2xl leading-tight font-semibold tracking-tight">{thisWeek ? 'This week' : 'Week of'} · {fmt(data.days[0], { day: 'numeric', month: 'short' })} – {fmt(data.days[5], { day: 'numeric', month: 'short' })}</h1>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="icon" aria-label="Week before" onClick={() => go(shift(data.week_start, -7))}><ChevronLeft className="size-4" /></Button>
          {!thisWeek && <Button variant="outline" size="sm" onClick={() => setParams((p) => { p.delete('week'); return p })}>This week</Button>}
          <Button variant="outline" size="icon" aria-label="Week after" onClick={() => go(shift(data.week_start, 7))}><ChevronRight className="size-4" /></Button>
          {data.tasks_module && !readOnly && <Button className="gap-1.5" onClick={() => setGiving(true)}><Plus className="size-4" />Give a task</Button>}
        </div>
      </header>

      <div className="grid grid-cols-2 gap-2 sm:gap-3 lg:grid-cols-4">
        <Stat label="Should finish this week" value={`${c.finished}/${c.finishing}`} note="Activities on the schedule" />
        <Stat label="Tasks done" value={`${c.tasks_done}/${c.tasks}`} note={data.tasks_module ? 'Due this week' : 'Tasks module is off'} />
        <Stat label="Critical this week" value={String(c.critical)} note="A day late on these is a day late at handover" tone={c.critical ? 'warn' : undefined} />
        <Stat label="Slipped in" value={String(c.slipped)} note="Not done in an earlier week" tone={c.slipped ? 'bad' : 'ok'} />
      </div>

      <section className="overflow-x-auto rounded-xl border">
        <div className="grid min-w-[760px] grid-cols-[minmax(12rem,1.4fr)_repeat(6,minmax(0,1fr))] text-sm">
          <div className="border-b bg-muted/50 px-3 py-2 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">On the schedule</div>
          {data.days.map((d) => (
            <div key={d} className={cn('border-b border-l bg-muted/50 px-2 py-2 text-center text-[11px] font-semibold', d === data.today ? 'text-foreground' : 'text-muted-foreground')}>
              {fmt(d, { weekday: 'short' })} {fmt(d, { day: 'numeric' })}{d === data.today && <span className="ml-1 rounded bg-primary px-1 text-[10px] text-primary-foreground">Today</span>}
            </div>
          ))}
          {data.activities.length === 0 && <div className="col-span-7 px-3 py-6 text-center text-muted-foreground">Nothing on the schedule this week.</div>}
          {data.activities.map((a) => (
            <React.Fragment key={a.id}>
              <Link to={`/planning/schedule?project=${projectId}&activity=${a.id}`} className="flex flex-col border-b px-3 py-2 hover:bg-muted/30">
                <span className="flex items-center gap-1.5 font-medium">{a.name}{a.critical && !a.done && <Tag tone="bad">critical</Tag>}{a.state === 'late' && <Tag tone="bad">late</Tag>}</span>
                <span className="text-xs text-muted-foreground">{a.done ? 'Done' : `${a.progress ?? 0}% done`} · ends {fmt(a.end, { weekday: 'short', day: 'numeric' })}{a.site_name ? ` · ${a.site_name}` : ''}</span>
              </Link>
              {data.days.map((d) => (
                <div key={d} className="flex items-center border-b border-l px-1 py-2">
                  {a.days.includes(d) && (
                    <span className={cn('h-3 w-full', a.done ? 'bg-emerald-600' : a.state === 'late' ? 'bg-red-500' : a.state === 'behind' ? 'bg-amber-500' : 'bg-sky-500',
                      d === a.days[0] && 'rounded-l-full', d === a.days[a.days.length - 1] && 'rounded-r-full', d === a.end && 'ring-2 ring-foreground/30')} />
                  )}
                </div>
              ))}
            </React.Fragment>
          ))}
        </div>
      </section>

      {data.tasks_module && (
        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold">Tasks due this week</h2>
          <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
            {data.days.map((d) => {
              const due = data.tasks.filter((t) => t.due_date === d || (d === data.days[5] && t.due_date > d))
              return (
                <div key={d} className={cn('flex min-h-24 flex-col gap-1.5 rounded-xl bg-muted/50 p-2', d === data.today && 'ring-2 ring-primary/60')}>
                  <div className="px-1 text-[11px] font-semibold text-muted-foreground">{fmt(d, { weekday: 'short', day: 'numeric' })}</div>
                  {due.map((t) => (
                    <div key={t.id} className={cn('flex items-start gap-2 rounded-lg border bg-card p-2 text-xs', t.done && 'opacity-60')}>
                      <input type="checkbox" aria-label={`Done: ${t.title}`} checked={t.done} disabled={readOnly || tick.isPending} onChange={() => tick.mutate(t)} className="mt-0.5 size-4 accent-emerald-600" />
                      <Link to={recordUrl.task(t.id)} className={cn('min-w-0 hover:underline', t.done && 'line-through')}>
                        <span className="block font-medium">{t.title}</span>
                        {t.assignee_name && <span className="text-muted-foreground">{t.assignee_name}</span>}
                      </Link>
                    </div>
                  ))}
                </div>
              )
            })}
          </div>
        </section>
      )}

      {data.slipped.length > 0 && (
        <section className="flex flex-col gap-2 rounded-xl border border-red-200 p-3 dark:border-red-900">
          <h2 className="text-sm font-semibold text-red-800 dark:text-red-200">Slipped in from earlier weeks</h2>
          {data.slipped.map((s) => (
            <div key={`${s.kind}-${s.id}`} className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <Link to={s.kind === 'task' ? recordUrl.task(s.id) : `/planning/schedule?project=${projectId}&activity=${s.id}`} className="font-medium hover:underline">
                {s.kind === 'task' ? s.title : s.name}
              </Link>
              <span className="text-xs text-muted-foreground">
                {s.kind === 'task' ? `Task${s.assignee_name ? ` · ${s.assignee_name}` : ''}` : `Activity · ${s.progress ?? 0}% done`} · {s.days_late} days late
              </span>
            </div>
          ))}
        </section>
      )}

      {giving && <NewTaskDialog open={giving} onOpenChange={(o) => { setGiving(o); if (!o) void qc.invalidateQueries({ queryKey: ['week', projectId] }) }} scope={{ mode: 'project', projectId, projectName: data.project.name }} />}
    </div>
  )
}

function Tag({ tone, children }: { tone: 'bad'; children: React.ReactNode }) {
  return <span className={cn('rounded px-1 text-[10px] font-normal', tone === 'bad' && 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200')}>{children}</span>
}

function Stat({ label, value, note, tone }: { label: string; value: string; note: string; tone?: 'ok' | 'warn' | 'bad' }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5 rounded-xl border bg-card p-3">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-2xl font-semibold tabular-nums">{value}</span>
      <span className={cn('truncate text-xs', tone === 'bad' ? 'text-red-700 dark:text-red-300' : tone === 'warn' ? 'text-draft' : tone === 'ok' ? 'text-success' : 'text-muted-foreground')}>{note}</span>
    </div>
  )
}
