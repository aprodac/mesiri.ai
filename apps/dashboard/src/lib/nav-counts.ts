import { useQuery } from '@tanstack/react-query'
import { fetchSiteDaysApi } from '@/lib/api'
import { useScope } from '@/lib/ScopeContext'
import { localIsoDate } from '@/lib/site-day'
import { useModuleEnabled } from '@/lib/modules'
import { fetchTaskSummary, type TaskSummary } from '@/lib/tasks'

/** Today's numbers for the sidebar and top bar badges (WEB-20): drafts still
 * to confirm and open issues, in the current scope (project or site). Same query key as the
 * Today page, so on that page it costs no extra request. */
export function useNavCounts(): { drafts: number; openIssues: number } {
  const { scope } = useScope()
  const date = localIsoDate(new Date())
  const projectFilter = scope.mode === 'portfolio' ? undefined : scope.projectId
  const { data } = useQuery({
    queryKey: ['site-days', date, projectFilter],
    queryFn: () => fetchSiteDaysApi(date, projectFilter),
    refetchInterval: 60_000,
    staleTime: 30_000,
  })
  // SCP-06: with a site picked, that site's counts (the request is per project).
  const items = (data?.items ?? []).filter((s) => scope.mode !== 'site' || s.site_id === scope.siteId)
  return {
    drafts: items.reduce((n, s) => n + (s.drafts ?? 0), 0),
    openIssues: items.reduce((n, s) => n + s.open_issues, 0),
  }
}

/** TSK-06: tasks for the sidebar and the Today card: mine still open, mine late, late in the projects I see, in
 * the current scope. Nothing is asked when the company has Tasks switched off. Writes to a task invalidate
 * ['tasks'], so the counts follow at once. */
export function useTaskCounts(): TaskSummary | null {
  const { scope } = useScope()
  const isModuleEnabled = useModuleEnabled()
  const projectFilter = scope.mode === 'portfolio' ? undefined : scope.projectId
  const { data } = useQuery({
    queryKey: ['tasks', 'summary', projectFilter],
    queryFn: () => fetchTaskSummary(projectFilter),
    enabled: isModuleEnabled('tasks'),
    refetchInterval: 60_000,
    staleTime: 30_000,
    retry: false,
  })
  return data ?? null
}
