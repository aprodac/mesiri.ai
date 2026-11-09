import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { ListChecks, MapPin, Plus, Search, User } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { EmptyState, PageError, PageHeader } from '@/components/page/page-kit'
import { Avatar, FilterPill, ProjectDot, WhatsAppMark, type FilterOption } from '@/components/requests/parts'
import { NewTaskDialog } from '@/components/tasks/new-task-dialog'
import { StatusChip, TaskDetail } from '@/components/tasks/task-detail'
import { useIsMobile } from '@/hooks/use-mobile'
import { useAuth } from '@/lib/AuthContext'
import { usePageTitle } from '@/lib/page-title'
import { swatch } from '@/lib/requests'
import { useScope } from '@/lib/ScopeContext'
import { dueWords, fetchTasks, PRIORITY_LABEL, type Task } from '@/lib/tasks'
import { useReadOnly } from '@/lib/trial'
import { useUrlState } from '@/lib/url-state'
import { cn } from '@/lib/utils'

// TSK-02: the Tasks module. Four views by ?view= (the sidebar links to each): given to me, all open, overdue, done.
// A list on the left (late first, then by due day), the chosen task on the right (a sheet on a phone). The API
// sorts and decides who sees what (site scope, BE-42); this page only filters what came back.

type View = 'mine' | 'all' | 'overdue' | 'done'

const VIEWS: { value: View; label: string }[] = [
  { value: 'mine', label: 'My tasks' },
  { value: 'all', label: 'All open' },
  { value: 'overdue', label: 'Overdue' },
  { value: 'done', label: 'Done' },
]

const QUERY: Record<View, { assignee?: string; status?: string; due?: 'overdue' }> = {
  mine: { assignee: 'me' },
  all: {},
  overdue: { due: 'overdue' },
  done: { status: 'done' },
}

const CREATE_ROLES = ['OWNER', 'ADMIN', 'SUPER_ADMIN', 'PROJECT_MANAGER', 'SITE_ENGINEER']

export default function TasksPage() {
  const { scope } = useScope()
  const { me } = useAuth()
  const readOnly = useReadOnly()
  const isMobile = useIsMobile()
  const projectId = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : null
  const siteId = scope.mode === 'site' ? scope.siteId : null

  const [view, setView] = useUrlState<View>('view', 'mine')
  const [site, setSite] = useUrlState<string>('at', '')
  const [person, setPerson] = useUrlState<string>('who', '')
  const [selected, setSelected] = useUrlState<string>('id', '')
  const [search, setSearch] = React.useState('')
  const [creating, setCreating] = React.useState(false)
  usePageTitle(VIEWS.find((v) => v.value === view)?.label ?? 'Tasks')

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['tasks', 'list', view, projectId, siteId],
    queryFn: () => fetchTasks({ project_id: projectId, site_id: siteId, ...QUERY[view] }),
    refetchInterval: 60_000,
  })
  const all = React.useMemo(() => data?.items ?? [], [data])
  const today = data?.today ?? new Date().toISOString().slice(0, 10)

  const list = React.useMemo(() => all.filter((t) => {
    if (site && t.site_id !== site) return false
    if (person && (t.assignee_user_id ?? t.assignee_vendor_id ?? '') !== person) return false
    if (search) {
      const q = search.toLowerCase()
      if (!`${t.ref} ${t.title} ${t.assigned_to ?? ''}`.toLowerCase().includes(q)) return false
    }
    return true
  }), [all, site, person, search])

  const options = React.useMemo(() => {
    const unique = <T,>(items: T[], key: (t: T) => string) => [...new Map(items.map((t) => [key(t), t])).values()]
    const sites: FilterOption[] = unique(all.filter((t) => t.site_id), (t) => t.site_id!).map((t) => ({
      value: t.site_id!, label: `${t.project_name} › ${t.site_name}`, swatch: swatch(t.project_id), count: all.filter((x) => x.site_id === t.site_id).length,
    }))
    const people: FilterOption[] = unique(all.filter((t) => t.assignee_user_id || t.assignee_vendor_id), (t) => (t.assignee_user_id ?? t.assignee_vendor_id)!).map((t) => {
      const id = (t.assignee_user_id ?? t.assignee_vendor_id)!
      return { value: id, label: t.assigned_to ?? 'Someone', avatar: { id, name: t.assigned_to ?? '?' }, count: all.filter((x) => (x.assignee_user_id ?? x.assignee_vendor_id) === id).length }
    })
    return { sites, people }
  }, [all])

  const current = list.find((t) => t.id === selected) ?? (isMobile ? undefined : list[0])
  const canCreate = !!me && CREATE_ROLES.includes((me.role || '').toUpperCase()) && !readOnly
  const late = all.filter((t) => t.overdue).length

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <PageHeader
        title="Tasks"
        actions={canCreate && (
          <Button className="hidden gap-2 font-semibold md:inline-flex" onClick={() => setCreating(true)}>
            <Plus className="size-4" strokeWidth={2.6} /> New task
          </Button>
        )}
      />

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div role="tablist" aria-label="View" className="flex max-w-full gap-0.5 overflow-x-auto rounded-xl bg-muted p-1">
          {VIEWS.map((v) => {
            const on = view === v.value
            return (
              <button
                key={v.value}
                role="tab"
                type="button"
                aria-selected={on}
                onClick={() => { setSelected(''); setView(v.value) }}
                className={cn('inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-3 text-sm whitespace-nowrap', on ? 'bg-background font-semibold shadow-sm' : 'text-foreground/75 hover:text-foreground')}
              >
                {v.label}
                {on && <span className="rounded-full bg-foreground px-1.5 text-[11px] font-semibold text-background tabular-nums">{all.length}</span>}
              </button>
            )
          })}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!siteId && options.sites.length > 1 && <FilterPill icon={MapPin} label="Site" allLabel="All sites" value={site} options={options.sites} onChange={setSite} />}
          {view !== 'mine' && <FilterPill icon={User} label="For" allLabel="Anyone" value={person} options={options.people} onChange={setPerson} />}
          <label className="flex h-9 items-center gap-2 rounded-lg border bg-background px-2.5">
            <Search className="size-4 text-muted-foreground" />
            <span className="sr-only">Search tasks</span>
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search" className="w-24 bg-transparent text-sm outline-none sm:w-32" />
          </label>
        </div>
      </div>

      {view !== 'overdue' && view !== 'done' && late > 0 && (
        <button type="button" onClick={() => setView('overdue')} className="w-fit rounded-lg bg-destructive/10 px-3 py-1.5 text-sm font-semibold text-destructive">
          {late} late — see them
        </button>
      )}

      {isError ? <PageError message="Tasks did not load." onRetry={() => refetch()} back={{ to: '/today', label: 'Back to Today' }} /> : (
        <div className="flex flex-col items-start gap-5 lg:flex-row">
          <section aria-label="Tasks" className="w-full min-w-0 flex-1 overflow-hidden rounded-xl border empty:hidden">
            {isLoading && [0, 1, 2, 3].map((i) => <div key={i} className="h-20 animate-pulse border-b bg-muted/40" />)}
            {!isLoading && list.length === 0 && (
              <EmptyState
                className="m-3 border-0"
                icon={ListChecks}
                title={all.length ? 'No tasks with these filters' : EMPTY[view].title}
                about={all.length ? 'Clear a filter to see more.' : EMPTY[view].about}
                action={canCreate && !all.length && view !== 'done' ? <Button className="gap-2" onClick={() => setCreating(true)}><Plus className="size-4" /> New task</Button> : undefined}
              />
            )}
            {list.map((t) => <TaskRow key={t.id} task={t} today={today} selected={current?.id === t.id} onPick={() => setSelected(t.id)} />)}
          </section>

          {!isMobile && current && (
            <aside aria-label="Task detail" className="sticky top-4 w-full shrink-0 overflow-hidden rounded-xl border lg:w-[420px]">
              <TaskDetail task={current} today={today} />
            </aside>
          )}
        </div>
      )}

      {isMobile && (
        <Sheet open={!!current} onOpenChange={(o) => !o && setSelected('')}>
          <SheetContent side="bottom" className="max-h-[92vh] gap-0 overflow-y-auto rounded-t-2xl p-0">
            <SheetTitle className="sr-only">{current ? current.ref : 'Task'}</SheetTitle>
            {current && <TaskDetail task={current} today={today} inSheet />}
          </SheetContent>
        </Sheet>
      )}

      {canCreate && (
        <Button className="fixed right-4 bottom-5 z-30 h-12 gap-2 rounded-full px-5 font-semibold shadow-lg md:hidden" onClick={() => setCreating(true)}>
          <Plus className="size-5" strokeWidth={2.6} /> Task
        </Button>
      )}
      <NewTaskDialog open={creating} onOpenChange={setCreating} scope={scope} />
    </div>
  )
}

const EMPTY: Record<View, { title: string; about: string }> = {
  mine: { title: 'Nothing given to you', about: 'Tasks given to you show here, late first, then by the day they are due.' },
  all: { title: 'No open tasks', about: 'Give a task to someone on the project: what to do, by when. It stays here until it is done.' },
  overdue: { title: 'Nothing late', about: 'Every open task is on time.' },
  done: { title: 'Nothing done yet', about: 'Finished tasks show here with who closed them.' },
}

function TaskRow({ task: t, today, selected, onPick }: { task: Task; today: string; selected: boolean; onPick: () => void }) {
  return (
    <button
      type="button"
      onClick={onPick}
      aria-current={selected || undefined}
      className={cn('flex w-full gap-3 border-b px-3 py-3 text-left transition last:border-b-0 hover:bg-muted/40 sm:px-4', selected && 'bg-yellow-50 shadow-[inset_0_0_0_2px_theme(colors.yellow.300)] dark:bg-yellow-950/40')}
    >
      <span className="mt-0.5 w-11 shrink-0 text-xs font-semibold text-muted-foreground tabular-nums">{t.ref}</span>
      <span className="flex min-w-0 flex-1 flex-col gap-1.5">
        <span className="flex items-start justify-between gap-2">
          <span className="line-clamp-2 min-w-0 font-semibold">{t.title}</span>
          <span className={cn('shrink-0 text-sm tabular-nums', t.overdue ? 'font-semibold text-destructive' : 'text-muted-foreground')}>{dueWords(t, today)}</span>
        </span>
        <span className="flex items-center justify-between gap-2 text-sm text-muted-foreground">
          <span className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1">
            <span className="inline-flex items-center gap-1.5"><Avatar id={t.assignee_user_id ?? t.assignee_vendor_id} name={t.assigned_to} />{t.assigned_to ?? 'Nobody yet'}</span>
            <span className="inline-flex items-center gap-1.5"><ProjectDot id={t.project_id} />{t.site_name ?? t.project_name}</span>
            {t.place_name && <span className="inline-flex items-center gap-1"><MapPin className="size-3" />{t.place_name}</span>}
            {t.priority !== 'normal' && <span className="text-xs font-semibold text-destructive">{PRIORITY_LABEL[t.priority]}</span>}
            {t.source === 'whatsapp' && <WhatsAppMark />}
          </span>
          <StatusChip status={t.status} />
        </span>
        {t.status === 'blocked' && t.blocked_reason && <span className="truncate text-xs text-orange-800 dark:text-orange-200">Blocked: {t.blocked_reason}</span>}
      </span>
    </button>
  )
}
