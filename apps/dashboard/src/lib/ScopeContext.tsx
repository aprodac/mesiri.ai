import * as React from 'react'
import { useSearchParams, useLocation, matchPath } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Loader2, ShieldAlert } from 'lucide-react'
import { useAuth } from './AuthContext'
import { allowedScopes } from './permissions'
import { fetchProjects, fetchSites } from './projects'
import type { AppScope, ProjectItem, SiteItem } from './scope-types'
import { Button } from '@/components/ui/button'

const SCOPE_STORAGE_KEY = 'mesiri_dashboard_scope'

type ScopeContextType = {
  scope: AppScope
  setPortfolioScope: () => void
  setProjectScope: (project: ProjectItem) => void
  setSiteScope: (project: ProjectItem, site: SiteItem) => void
  isPortfolioMode: boolean
  isProjectMode: boolean
  isSiteMode: boolean
}

const ScopeContext = React.createContext<ScopeContextType | null>(null)

export function useScope() {
  const context = React.useContext(ScopeContext)
  if (!context) {
    throw new Error('useScope must be used within a ScopeProvider')
  }
  return context
}

export function useAllowedScopes() {
  const { me } = useAuth()
  if (!me) return []
  return allowedScopes(me.role, me.access_policy)
}

function isScopeAllowed(scope: AppScope, allowed: string[]): boolean {
  return allowed.includes(scope.mode)
}

export function ScopeProvider({ children }: { children: React.ReactNode }) {
  const { me } = useAuth()
  const allowed = useAllowedScopes()
  const [searchParams, setSearchParams] = useSearchParams()
  const location = useLocation()

  const projectId = searchParams.get('project')
  const siteId = searchParams.get('site')

  // Detect project route parameter e.g. /projects/:id
  const projectRouteMatch = matchPath({ path: '/projects/:id' }, location.pathname)
  const routeProjectId = projectRouteMatch?.params.id

  // Fetch accessible projects to resolve names and validate access
  const {
    data: projects = [],
    isLoading: isProjectsLoading,
    isFetching: isProjectsFetching,
    refetch: refetchProjects,
  } = useQuery<ProjectItem[]>({
    queryKey: ['scope-projects'],
    queryFn: fetchProjects,
    enabled: !!me && (allowed.includes('project') || allowed.includes('site')),
    staleTime: 60_000,
  })

  const activeTargetProjectId = routeProjectId || projectId

  // Refetch projects if a target projectId is requested but missing from cached list
  const [hasAttemptedRefetch, setHasAttemptedRefetch] = React.useState(false)

  React.useEffect(() => {
    setHasAttemptedRefetch(false)
  }, [activeTargetProjectId])

  React.useEffect(() => {
    if (
      activeTargetProjectId &&
      !isProjectsLoading &&
      !isProjectsFetching &&
      !hasAttemptedRefetch &&
      !projects.some((p) => p.id === activeTargetProjectId)
    ) {
      setHasAttemptedRefetch(true)
      refetchProjects()
    }
  }, [
    activeTargetProjectId,
    projects,
    isProjectsLoading,
    isProjectsFetching,
    hasAttemptedRefetch,
    refetchProjects,
  ])

  // Synchronize route parameter /projects/:id with project scope parameter
  React.useEffect(() => {
    if (routeProjectId && searchParams.get('project') !== routeProjectId) {
      setSearchParams(
        (prev) => {
          prev.set('project', routeProjectId)
          return prev
        },
        { replace: true }
      )
    }
  }, [routeProjectId, searchParams, setSearchParams])

  // Fetch sites for the active project to resolve site name and validate
  const {
    data: sites = [],
    isLoading: isSitesLoading,
    isFetching: isSitesFetching,
    refetch: refetchSites,
  } = useQuery<SiteItem[]>({
    queryKey: ['scope-sites', projectId],
    queryFn: () => fetchSites(projectId!),
    enabled: !!projectId && allowed.includes('site'),
    staleTime: 60_000,
  })

  // Refetch sites if a siteId is requested but missing from cached sites list
  const [hasAttemptedSiteRefetch, setHasAttemptedSiteRefetch] = React.useState(false)

  React.useEffect(() => {
    setHasAttemptedSiteRefetch(false)
  }, [siteId])

  React.useEffect(() => {
    if (
      siteId &&
      projectId &&
      !isSitesLoading &&
      !isSitesFetching &&
      !hasAttemptedSiteRefetch &&
      !sites.some((s) => s.id === siteId)
    ) {
      setHasAttemptedSiteRefetch(true)
      refetchSites()
    }
  }, [
    siteId,
    projectId,
    sites,
    isSitesLoading,
    isSitesFetching,
    hasAttemptedSiteRefetch,
    refetchSites,
  ])

  // Restore scope from localStorage / apply role-based fallback on initial load
  const hasResolvedInitialScope = React.useRef(false)

  React.useEffect(() => {
    if (!me || projects.length === 0) return
    if (hasResolvedInitialScope.current) return

    if (routeProjectId) {
      hasResolvedInitialScope.current = true
      setSearchParams(
        (prev) => {
          prev.set('project', routeProjectId)
          return prev
        },
        { replace: true }
      )
      return
    }

    const urlProject = searchParams.get('project')
    if (urlProject) {
      hasResolvedInitialScope.current = true
      return // Scope is already explicitly set in URL
    }

    hasResolvedInitialScope.current = true

    // 1. Try restoring from localStorage
    try {
      const stored = localStorage.getItem(SCOPE_STORAGE_KEY)
      if (stored) {
        const parsed = JSON.parse(stored) as AppScope
        if (isScopeAllowed(parsed, allowed)) {
          setSearchParams((prev) => {
            if (parsed.mode === 'project' || parsed.mode === 'site') {
              prev.set('project', parsed.projectId)
            }
            if (parsed.mode === 'site') {
              prev.set('site', parsed.siteId)
            }
            return prev
          })
          return
        }
      }
    } catch {
      // ignore malformed scope
    }

    // 2. No localStorage or disallowed, fallback based on role permissions
    if (allowed.includes('portfolio')) {
      return
    }

    // For project-restricted roles, fall back to first accessible project
    const defaultProject = projects[0]
    if (defaultProject) {
      setSearchParams((prev) => {
        prev.set('project', defaultProject.id)
        return prev
      })
    }
  }, [me, projects, allowed, searchParams, setSearchParams, routeProjectId])

  // Derive scope state dynamically from the URL parameters
  const scope = React.useMemo<AppScope>(() => {
    if (!projectId) {
      return { mode: 'portfolio' }
    }

    const matchedProject = projects.find((p) => p.id === projectId)
    const projectName = matchedProject?.name || 'Loading Project...'

    if (!siteId) {
      return {
        mode: 'project',
        projectId,
        projectName,
      }
    }

    const matchedSite = sites.find((s) => s.id === siteId)
    const siteName = matchedSite?.name || 'Loading Site...'

    return {
      mode: 'site',
      projectId,
      projectName,
      siteId,
      siteName,
    }
  }, [projectId, siteId, projects, sites])

  // Persist resolved scope to localStorage as a convenience
  React.useEffect(() => {
    if (scope.mode !== 'portfolio') {
      try {
        localStorage.setItem(SCOPE_STORAGE_KEY, JSON.stringify(scope))
      } catch {}
    }
  }, [scope])

  // Validate scope parameters
  const validation = React.useMemo(() => {
    if (!projectId) {
      return { isValid: true, reason: '' }
    }

    // Wait until projects are fetched or being refetched before declaring invalid
    if ((isProjectsLoading || isProjectsFetching) && !projects.some((p) => p.id === projectId)) {
      return { isValid: true, reason: '' }
    }

    const hasProjectAccess = projects.some((p) => p.id === projectId)
    if (!hasProjectAccess) {
      return { isValid: false, reason: "This project doesn't exist, or you don't have access to it." }
    }

    if (siteId) {
      if ((isSitesLoading || isSitesFetching) && !sites.some((s) => s.id === siteId)) {
        return { isValid: true, reason: '' }
      }

      const hasSiteAccess = sites.some((s) => s.id === siteId)
      if (!hasSiteAccess) {
        return { isValid: false, reason: "This site doesn't exist, or it isn't part of this project." }
      }
    }

    return { isValid: true, reason: '' }
  }, [
    projectId,
    siteId,
    projects,
    sites,
    isProjectsLoading,
    isProjectsFetching,
    isSitesLoading,
    isSitesFetching,
  ])

  const setPortfolioScope = () => {
    setSearchParams((prev) => {
      prev.delete('project')
      prev.delete('site')
      return prev
    })
  }

  const setProjectScope = (project: ProjectItem) => {
    setSearchParams((prev) => {
      prev.set('project', project.id)
      prev.delete('site')
      return prev
    })
  }

  const setSiteScope = (project: ProjectItem, site: SiteItem) => {
    setSearchParams((prev) => {
      prev.set('project', project.id)
      prev.set('site', site.id)
      return prev
    })
  }

  // Render loading state while resolving initial scope or refetching
  const isResolving =
    (!!projectId && !projects.some((p) => p.id === projectId) && (isProjectsLoading || isProjectsFetching)) ||
    (!!siteId && !sites.some((s) => s.id === siteId) && (isSitesLoading || isSitesFetching))

  if (isResolving) {
    return (
      <div className="flex h-svh items-center justify-center text-sm text-muted-foreground gap-2">
        <Loader2 className="size-4 animate-spin text-primary" />
        Loading…
      </div>
    )
  }

  // Render error UI if scope parameters are invalid
  if (!validation.isValid) {
    return (
      <div className="flex h-svh items-center justify-center p-6 text-center">
        <div className="flex flex-col items-center gap-4 max-w-md bg-card p-6 rounded-lg border border-border shadow-xs">
          <ShieldAlert className="size-8 text-destructive" />
          <h2 className="text-base font-semibold text-foreground">This page isn't available</h2>
          <p className="text-sm text-muted-foreground leading-relaxed">
            {validation.reason}
          </p>
          <Button size="sm" onClick={setPortfolioScope} className="mt-2">
            Show all projects
          </Button>
        </div>
      </div>
    )
  }

  return (
    <ScopeContext.Provider
      value={{
        scope,
        setPortfolioScope,
        setProjectScope,
        setSiteScope,
        isPortfolioMode: scope.mode === 'portfolio',
        isProjectMode: scope.mode === 'project',
        isSiteMode: scope.mode === 'site',
      }}
    >
      {children}
    </ScopeContext.Provider>
  )
}
