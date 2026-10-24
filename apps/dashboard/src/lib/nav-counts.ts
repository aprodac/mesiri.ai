import { useQuery } from '@tanstack/react-query'
import { fetchSiteDaysApi } from '@/lib/api'
import { useScope } from '@/lib/ScopeContext'
import { localIsoDate } from '@/lib/site-day'

/** Today's numbers for the sidebar and top bar badges (WEB-20): drafts still
 * to confirm and open issues, in the current scope. Same query key as the
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
  const items = data?.items ?? []
  return {
    drafts: items.reduce((n, s) => n + (s.drafts ?? 0), 0),
    openIssues: items.reduce((n, s) => n + s.open_issues, 0),
  }
}
