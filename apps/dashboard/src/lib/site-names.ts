import * as React from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { fetchProjects, fetchSites } from '@/lib/projects'

/** Site id -> its name and project name, for pages whose rows carry only
 * ids (Activities, Gallery). Same cached lists the scope picker uses. */
export function useSiteNames(): Map<string, { name: string; project: string }> {
  const projectsQuery = useQuery({ queryKey: ['scope-projects'], queryFn: fetchProjects, staleTime: 60_000 })
  const siteQueries = useQueries({
    queries: (projectsQuery.data ?? []).map((p) => ({
      queryKey: ['scope-sites', p.id],
      queryFn: () => fetchSites(p.id),
      staleTime: 60_000,
    })),
  })
  // Changes only when a site list is (re)fetched.
  const sitesVersion = siteQueries.map((q) => q.dataUpdatedAt).join(',')
  return React.useMemo(() => {
    const projectName = new Map((projectsQuery.data ?? []).map((p) => [p.id, p.name]))
    const sites = new Map<string, { name: string; project: string }>()
    for (const q of siteQueries) for (const st of q.data ?? []) sites.set(st.id, { name: st.name, project: projectName.get(st.projectId) ?? '' })
    return sites
    // eslint-disable-next-line react-hooks/exhaustive-deps -- siteQueries is a new array each render; sitesVersion tracks its data
  }, [projectsQuery.data, sitesVersion])
}
