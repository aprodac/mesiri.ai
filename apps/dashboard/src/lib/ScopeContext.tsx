import * as React from 'react'
import { useSearchParams, useLocation, matchPath } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, ShieldAlert } from 'lucide-react'
import { useAuth } from './AuthContext'
import { allowedScopes } from './permissions'
import { fetchProjects, fetchSites } from './projects'
import type { AppScope, ProjectItem, SiteItem } from './scope-types'
import { Button } from '@/components/ui/button'
import { forgetStoredScope, readStartProject, readStoredScope, rememberRecent, storeScope } from './scope-recent'

type ScopeContextType = {
  scope: AppScope
  setPortfolioScope: () => void
  setProjectScope: (project: ProjectItem) => void
  setSiteScope: (project: ProjectItem, site: SiteItem) => void
  isPortfolioMode: boolean
  isProjectMode: boolean
  isSiteMode: boolean
  /** SCP-05: the view before a link (WhatsApp, a notification, a record on another project) changed it; null otherwise. */
  arrivedFrom: AppScope | null
  /** Back to that view. */
  goBackFromLink: () => void
  dismissArrival: () => void
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
  const userId = me?.user_id
  const allowed = useAllowedScopes()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParamsRaw] = useSearchParams()
  // Every change the app makes on its own (restoring, landing a role, dropping a dead site) goes through here, so a
  // change that did not (a link, Back) can be told apart and announced (SCP-05).
  const internalChange = React.useRef(false)
  const setSearchParams: typeof setSearchParamsRaw = React.useCallback(
    (next, opts) => {
      internalChange.current = true
      return setSearchParamsRaw(next, opts)
    },
    [setSearchParamsRaw]
  )
  const [arrivedFrom, setArrivedFrom] = React.useState<AppScope | null>(null)
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
  // The site restored from storage: checked once the project's sites arrive, and dropped
  // quietly if it is gone, instead of blocking the page the person asked for.
  const restoredSiteId = React.useRef<string | null>(null)

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
      // Opened from a link that names a project: say so, with the way back to the whole company (SCP-05).
      if (allowed.includes('portfolio')) setArrivedFrom({ mode: 'portfolio' })
      return // Scope is already explicitly set in URL
    }

    hasResolvedInitialScope.current = true

    // 1. This login's own last pick (a pick from another login, or from before SCP-05, is never restored)
    try {
      const parsed = readStoredScope()
      if (parsed) {
        // A stored project that was deleted, or belongs to an account that used this browser
        // before, must not be put in the URL: it would block every page with "doesn't exist".
        const stillVisible =
          parsed.mode !== 'portfolio' && projects.some((p) => p.id === parsed.projectId)
        if (parsed.mode === 'portfolio' && allowed.includes('portfolio')) return
        if (stillVisible && isScopeAllowed(parsed, allowed)) {
          if (parsed.mode === 'site') restoredSiteId.current = parsed.siteId
          setSearchParams(
            (prev) => {
              prev.set('project', parsed.projectId)
              if (parsed.mode === 'site') {
                prev.set('site', parsed.siteId)
              }
              return prev
            },
            { replace: true }
          )
          return
        }
        forgetStoredScope()
      }
    } catch {
      // ignore malformed scope
    }

    // 2. Where the role works (SCP-05): owner and finance on all projects; a site engineer on the first project
    // where they have a site, and that site; a project manager on the project they said they mostly work on, else
    // their first.
    if (allowed.includes('portfolio')) {
      return
    }

    const land = (projectId: string, siteId?: string) =>
      setSearchParams(
        (prev) => {
          prev.set('project', projectId)
          if (siteId) prev.set('site', siteId)
          return prev
        },
        { replace: true }
      )

    if (!allowed.includes('project')) {
      void (async () => {
        for (const p of projects) {
          try {
            const own = await queryClient.fetchQuery({ queryKey: ['scope-sites', p.id], queryFn: () => fetchSites(p.id), staleTime: 60_000 })
            if (own.length) return land(p.id, own[0].id)
          } catch {
            // that project's sites did not load: try the next
          }
        }
        if (projects[0]) land(projects[0].id)
      })()
      return
    }

    const start = readStartProject(userId)
    const defaultProject = projects.find((p) => p.id === start) ?? projects[0]
    if (defaultProject) land(defaultProject.id)
  }, [me, userId, projects, allowed, searchParams, setSearchParams, routeProjectId, queryClient])

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

  // Persist the scope as a convenience, but only one that was checked: a dead id from a link
  // or a bookmark saved here came back on every reload and every later WhatsApp link.
  const scopeIsResolved =
    scope.mode === 'portfolio' ||
    (projects.some((p) => p.id === scope.projectId) &&
      (scope.mode === 'project' || sites.some((s) => s.id === scope.siteId)))

  React.useEffect(() => {
    // Not before the first restore has run: the empty address of a reload would overwrite the pick it is restoring.
    if (!hasResolvedInitialScope.current || !validation.isValid || !scopeIsResolved) return
    // All projects is stored too, so a later reload in this login does not jump to a project.
    storeScope(scope)
  }, [scope, validation.isValid, scopeIsResolved])

  // SCP-05: a change of view the app did not make (a link, Back, a notification) is announced on the page, with the
  // way back; any pick in the top bar clears it.
  const scopeKey = scope.mode === 'portfolio' ? 'all' : `${scope.projectId}:${scope.mode === 'site' ? scope.siteId : ''}`
  const lastScope = React.useRef<{ key: string; scope: AppScope } | null>(null)
  React.useEffect(() => {
    if (!scopeIsResolved) return
    const prev = lastScope.current
    lastScope.current = { key: scopeKey, scope }
    // Same view, new data (projects or sites reloaded): keep the mark for a change still on its way.
    if (prev?.key === scopeKey) return
    if (prev) setArrivedFrom(internalChange.current ? null : prev.scope)
    internalChange.current = false
  }, [scopeKey, scope, scopeIsResolved])

  // A site that came from storage and no longer exists: drop it, stay on the project.
  React.useEffect(() => {
    if (!siteId || siteId !== restoredSiteId.current) return
    if (sites.some((s) => s.id === siteId)) {
      restoredSiteId.current = null
      return
    }
    if (isSitesLoading || isSitesFetching || !hasAttemptedSiteRefetch) return
    restoredSiteId.current = null
    forgetStoredScope()
    setSearchParams(
      (prev) => {
        prev.delete('site')
        return prev
      },
      { replace: true }
    )
  }, [siteId, sites, isSitesLoading, isSitesFetching, hasAttemptedSiteRefetch, setSearchParams])

  // SCP-04: a role that works at site level only (site engineer) is never left looking at a whole project: with
  // only ?project= in the address (a project link, its first visit), it moves to the first of its sites there.
  const siteOnly = allowed.includes('site') && !allowed.includes('project') && !allowed.includes('portfolio')
  React.useEffect(() => {
    if (!siteOnly || !projectId || siteId || isSitesLoading || isSitesFetching) return
    const first = sites[0]
    if (!first || first.projectId !== projectId) return
    setSearchParams(
      (prev) => {
        prev.set('site', first.id)
        return prev
      },
      { replace: true }
    )
  }, [siteOnly, projectId, siteId, sites, isSitesLoading, isSitesFetching, setSearchParams])

  const setPortfolioScope = () => {
    setArrivedFrom(null)
    setSearchParams((prev) => {
      prev.delete('project')
      prev.delete('site')
      return prev
    })
  }

  const setProjectScope = (project: ProjectItem) => {
    rememberRecent(userId, { projectId: project.id })
    setArrivedFrom(null)
    setSearchParams((prev) => {
      prev.set('project', project.id)
      prev.delete('site')
      return prev
    })
  }

  const setSiteScope = (project: ProjectItem, site: SiteItem) => {
    rememberRecent(userId, { projectId: project.id, siteId: site.id })
    setArrivedFrom(null)
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
        <Loader2 className="size-4 animate-spin text-primary-ink" />
        Loading…
      </div>
    )
  }

  // The way out of a dead link: forget the stored scope too (or the next reload brings it
  // back), and land where the role may be: all projects, or the first project it can see.
  const leaveInvalidScope = () => {
    forgetStoredScope()
    const fallback = allowed.includes('portfolio') ? null : projects[0]
    setSearchParams(
      (prev) => {
        prev.delete('site')
        if (fallback) prev.set('project', fallback.id)
        else prev.delete('project')
        return prev
      },
      { replace: true }
    )
  }
  const canLeave = allowed.includes('portfolio') || projects.length > 0
  const siteOnlyBad = !!projectId && projects.some((p) => p.id === projectId)

  // Render error UI if scope parameters are invalid
  const isRestoredSitePending = !!siteId && siteId === restoredSiteId.current
  if (!validation.isValid && !isRestoredSitePending) {
    return (
      <div className="flex h-svh items-center justify-center p-6 text-center">
        <div className="flex flex-col items-center gap-4 max-w-md bg-card p-6 rounded-lg border border-border shadow-xs">
          <ShieldAlert className="size-8 text-destructive" />
          <h2 className="text-base font-semibold text-foreground">This page isn't available</h2>
          <p className="text-sm text-muted-foreground leading-relaxed">
            {validation.reason}
          </p>
          {siteOnlyBad ? (
            <Button
              size="sm"
              className="mt-2"
              onClick={() => {
                forgetStoredScope()
                setSearchParams(
                  (prev) => {
                    prev.delete('site')
                    return prev
                  },
                  { replace: true }
                )
              }}
            >
              Show the whole project
            </Button>
          ) : canLeave ? (
            <Button size="sm" onClick={leaveInvalidScope} className="mt-2">
              {allowed.includes('portfolio') ? 'Show all projects' : 'Go to my project'}
            </Button>
          ) : null}
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
        arrivedFrom,
        goBackFromLink: () => {
          const from = arrivedFrom
          setArrivedFrom(null)
          if (!from) return
          setSearchParams((prev) => {
            prev.delete('project')
            prev.delete('site')
            if (from.mode !== 'portfolio') prev.set('project', from.projectId)
            if (from.mode === 'site') prev.set('site', from.siteId)
            return prev
          })
        },
        dismissArrival: () => setArrivedFrom(null),
      }}
    >
      {children}
    </ScopeContext.Provider>
  )
}
