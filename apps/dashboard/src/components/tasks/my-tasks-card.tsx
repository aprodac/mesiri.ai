import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ChevronRight, ListChecks } from 'lucide-react'
import { useScope } from '@/lib/ScopeContext'
import { useTaskCounts } from '@/lib/nav-counts'
import { dueWords, fetchTasks } from '@/lib/tasks'
import { cn } from '@/lib/utils'
import { StatusChip } from './task-detail'

// TSK-06: the first thing on Today for anyone with tasks: the few given to me, late first (the API's own order),
// and how many are late in the projects I see. Hidden when there is nothing, and when Tasks is switched off
// (useTaskCounts asks nothing then).

const SHOWN = 3

export function MyTasksCard() {
  const counts = useTaskCounts()
  const { scope } = useScope()
  const projectFilter = scope.mode === 'portfolio' ? undefined : scope.projectId
  const mine = useQuery({
    queryKey: ['tasks', 'list', 'today-card', projectFilter],
    queryFn: () => fetchTasks({ assignee: 'me', project_id: projectFilter }),
    enabled: !!counts && counts.mine_open > 0,
    staleTime: 30_000,
  })
  if (!counts || (counts.mine_open === 0 && counts.overdue === 0)) return null
  const items = mine.data?.items.slice(0, SHOWN) ?? []
  const lateElsewhere = counts.overdue - counts.mine_overdue

  return (
    <section className="flex flex-col rounded-xl border bg-card text-sm" aria-label="My tasks">
      <Link to="/tasks" className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 hover:bg-muted/30">
        <ListChecks className="size-4 text-muted-foreground" />
        <span className="font-medium">My tasks</span>
        <span className="text-muted-foreground">
          {counts.mine_open ? `${counts.mine_open} open` : 'none for you'}
          {counts.mine_overdue > 0 && <span className="font-semibold text-destructive"> · {counts.mine_overdue} late</span>}
        </span>
        <span className="ml-auto flex items-center gap-0.5 text-xs font-semibold">Open <ChevronRight className="size-3.5" /></span>
      </Link>
      {items.length > 0 && (
        <ul className="flex flex-col divide-y border-t">
          {items.map((t) => (
            <li key={t.id}>
              <Link to={`/tasks?id=${t.id}`} className="flex items-center gap-2 px-3 py-2 hover:bg-muted/30">
                <span className="w-9 shrink-0 text-xs text-muted-foreground tabular-nums">{t.ref}</span>
                <span className="min-w-0 flex-1 truncate">{t.title}</span>
                {t.status !== 'open' && <StatusChip status={t.status} />}
                <span className={cn('shrink-0 text-xs tabular-nums', t.overdue ? 'font-semibold text-destructive' : 'text-muted-foreground')}>
                  {dueWords(t, mine.data!.today)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {lateElsewhere > 0 && (
        <Link to="/tasks?view=overdue" className="flex items-center gap-2 border-t px-3 py-2 text-destructive hover:bg-muted/30">
          <span className="font-semibold">{lateElsewhere} {lateElsewhere === 1 ? 'task' : 'tasks'} late</span>
          <span className="text-muted-foreground">for others in your projects</span>
          <ChevronRight className="ml-auto size-3.5" />
        </Link>
      )}
    </section>
  )
}
