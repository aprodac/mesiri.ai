import * as React from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { loadToken, saveToken, whenSignedOut } from './api'
import { fetchMe, fetchProjects, fetchSites, type Me, type Project, type Site } from './mesiri'
import { getValue, setValue } from './storage'

// Who is signed in, and which site they are reporting for. The site is always on screen; the app
// picks it (the one they chose last, else their first site) and they change it from the site button.

type State = 'loading' | 'signed_out' | 'signed_in'

interface Session {
  state: State
  me: Me | null
  signedIn: () => Promise<void>
  signOut: () => Promise<void>
}

const SessionCtx = React.createContext<Session>({
  state: 'loading',
  me: null,
  signedIn: async () => undefined,
  signOut: async () => undefined,
})

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = React.useState<State>('loading')
  const client = useQueryClient()

  React.useEffect(() => {
    whenSignedOut(() => {
      client.clear()
      setState('signed_out')
    })
    void loadToken().then((token) => setState(token ? 'signed_in' : 'signed_out'))
  }, [client])

  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe, enabled: state === 'signed_in', staleTime: 5 * 60_000 })

  const value = React.useMemo<Session>(
    () => ({
      state,
      me: me.data ?? null,
      signedIn: async () => {
        client.clear()
        setState('signed_in')
      },
      signOut: async () => {
        await saveToken(null)
        client.clear()
        setState('signed_out')
      },
    }),
    [state, me.data, client],
  )
  return <SessionCtx.Provider value={value}>{children}</SessionCtx.Provider>
}

export const useSession = () => React.useContext(SessionCtx)

export function personName(me: Me | null): string {
  return me?.name || me?.full_name || ''
}

// ── The working site ──────────────────────────────────────────────────────

export interface Place {
  site: Site
  project: Project
}

interface SiteState {
  places: Place[]
  current: Place | null
  loading: boolean
  error: boolean
  choose: (siteId: string) => void
  reload: () => void
}

const SiteCtx = React.createContext<SiteState>({
  places: [],
  current: null,
  loading: true,
  error: false,
  choose: () => undefined,
  reload: () => undefined,
})

const SITE_KEY = 'mesiri_app_site'

async function loadPlaces(): Promise<Place[]> {
  const projects = await fetchProjects()
  const lists = await Promise.all(
    projects.map(async (project) => (await fetchSites(project.id)).map((site) => ({ site, project }))),
  )
  return lists.flat().filter((p) => !p.site.status || p.site.status === 'active')
}

export function SiteProvider({ children }: { children: React.ReactNode }) {
  const { state } = useSession()
  const query = useQuery({ queryKey: ['places'], queryFn: loadPlaces, enabled: state === 'signed_in', staleTime: 10 * 60_000 })
  const [chosen, setChosen] = React.useState<string | null>(null)

  React.useEffect(() => {
    void getValue<string>(SITE_KEY).then((id) => id && setChosen(id))
  }, [])

  const places = React.useMemo(() => query.data ?? [], [query.data])
  const current = places.find((p) => p.site.id === chosen) ?? places[0] ?? null

  const value = React.useMemo<SiteState>(
    () => ({
      places,
      current,
      loading: query.isLoading,
      error: query.isError,
      choose: (id) => {
        setChosen(id)
        void setValue(SITE_KEY, id)
      },
      reload: () => void query.refetch(),
    }),
    [places, current, query],
  )
  return <SiteCtx.Provider value={value}>{children}</SiteCtx.Provider>
}

export const useSite = () => React.useContext(SiteCtx)

/** Today as the company's day (a learning sample company has its own date). */
export function todayFor(me: Me | null): string {
  if (me?.today) return me.today
  const now = new Date()
  const y = now.getFullYear()
  const m = String(now.getMonth() + 1).padStart(2, '0')
  const d = String(now.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}
