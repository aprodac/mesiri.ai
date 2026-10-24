import { useQueries, useQuery } from '@tanstack/react-query'
import type { User } from './api'
import { fetchProjectMembers, fetchProjects } from './projects'

// Shared by the Team list and a person's page (WEB-28).

/**
 * Who is on which project, from `project_members` -- the table access is
 * actually checked against (REST and WhatsApp). `users.access_policy` is not
 * enough: adding someone from a project page writes only `project_members`,
 * so the policy can be stale. Same queries as the Projects list (cached).
 */
export function useMemberships(): { byUser: Map<string, string[]>; names: Map<string, string>; loading: boolean } {
  const projectsQuery = useQuery({ queryKey: ['filter-projects-list'], queryFn: fetchProjects })
  const projects = projectsQuery.data ?? []
  const members = useQueries({
    queries: projects.map((p) => ({ queryKey: ['project-members-count', p.id], queryFn: () => fetchProjectMembers(p.id) })),
  })
  const byUser = new Map<string, string[]>()
  projects.forEach((p, i) => {
    for (const m of members[i]?.data ?? []) byUser.set(m.userId, [...(byUser.get(m.userId) ?? []), p.id])
  })
  return {
    byUser,
    names: new Map(projects.map((p) => [p.id, p.name])),
    loading: projectsQuery.isLoading || members.some((m) => m.isLoading),
  }
}

/** Admins, and anyone given "all projects", reach every project -- by role
 * (backend `roles.ORG_WIDE_ROLES`) or as a standing grant. */
export function isOrgWide(user: User): boolean {
  return user.role === 'ADMIN' || user.access_policy?.mode === 'all_projects'
}

/** The projects a person reaches, in a few words, with the sites when they
 * were limited to some (from the access settings that limited them). */
export function projectAccessText(user: User, projectIds: string[], names: Map<string, string>): { text: string; none: boolean } {
  if (isOrgWide(user)) return { text: 'All projects', none: false }
  if (projectIds.length === 0) return { text: 'No projects yet', none: true }
  const grants = new Map((user.access_policy?.projects ?? []).map((g) => [g.projectId, g]))
  return {
    text: projectIds
      .map((pid) => {
        const name = names.get(pid) ?? 'A project'
        const site = grants.get(pid)?.siteAccess
        const n = site?.mode === 'custom_sites' ? site.siteIds?.length ?? 0 : null
        return n === null ? name : `${name} (${n} site${n === 1 ? '' : 's'})`
      })
      .join(', '),
    none: false,
  }
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join('')
}
