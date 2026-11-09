import * as React from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { Building2, Globe, MapPin } from 'lucide-react'
import { useAllowedScopes } from './ScopeContext'
import { fetchProjects, fetchSites } from './projects'
import type { ProjectItem, SiteItem } from './scope-types'

// SCP-01: the look of each scope level (WEB-20 colours) and the project/site tree the top-bar panel lists.

export const SCOPE_TONE = {
  portfolio: 'bg-sky-100 text-sky-700 dark:bg-sky-400/15 dark:text-sky-300',
  project: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-400/15 dark:text-emerald-300',
  site: 'bg-orange-100 text-orange-700 dark:bg-orange-400/15 dark:text-orange-300',
} as const
export const SCOPE_ICON = { portfolio: Globe, project: Building2, site: MapPin } as const

export type Tree = { project: ProjectItem; sites: SiteItem[] }[]

/** Every project this person can see, with the sites they can see in it (the same queries ScopeContext checks). */
export function useScopeTree(): { tree: Tree; loading: boolean } {
  const allowed = useAllowedScopes()
  const projects = useQuery({
    queryKey: ['scope-projects'],
    queryFn: fetchProjects,
    enabled: allowed.includes('project') || allowed.includes('site'),
    staleTime: 60_000,
  })
  const list = React.useMemo(() => projects.data ?? [], [projects.data])
  const sites = useQueries({
    queries: list.map((p) => ({
      queryKey: ['scope-sites', p.id],
      queryFn: () => fetchSites(p.id),
      enabled: allowed.includes('site'),
      staleTime: 60_000,
    })),
  })
  // Cheap to rebuild: a few projects, their cached site lists.
  const tree = list.map((project, i) => ({ project, sites: sites[i]?.data ?? [] }))
  return { tree, loading: projects.isLoading || sites.some((q) => q.isLoading) }
}

