import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import { useAuth } from './AuthContext'

// Guided onboarding (SS-27..SS-37, docs/plans/guided-onboarding-plan.md): how Mesiri guides this person, from
// their answer to "How would you like to start?". It changes help only, never what they may see or do.
//
// Rule 4 of the plan's section 6.7: the modes are data. What each mode gets is the one table below; a page or
// component asks the table ("does this mode show page strips?"), never "is the mode guided?". Changing what a mode
// shows, or adding one, is an edit here (and to START_MODES in the backend and migration 0553's check).

export type StartMode = 'guided' | 'bring_data' | 'switching' | 'free'

export interface ModeRules {
  /** The answer as the person reads it. */
  label: string
  /** The line under it. */
  hint: string
  /** The getting-started card on Today shows by itself (else only from "Finish setup"). */
  checklist: boolean
  /** The checklist steps carry a "why" line. */
  whyLines: boolean
  /** The checklist adds the "bring your materials list / BOQ" steps. */
  dataSteps: boolean
  /** The checklist adds "Where things are" (the sidebar, search, the help button). */
  whereThingsAre: boolean
  /** The sidebar shows only the everyday pages, with "Show everything". */
  shortSidebar: boolean
  /** A page explains itself in a strip at the top, once: every page, only the data pages, or none. */
  strips: 'all' | 'data' | 'none'
  /** Construction words are underlined (always explained on tap). */
  termsUnderlined: boolean
  /** "Bring your data" is in the sidebar's everyday pages. */
  bringDataInSidebar: boolean
}

export const MODES: Record<StartMode, ModeRules> = {
  guided: {
    label: 'Show me step by step',
    hint: "I'm new to tools like this.",
    checklist: true,
    whyLines: true,
    dataSteps: false,
    whereThingsAre: false,
    shortSidebar: true,
    strips: 'all',
    termsUnderlined: true,
    bringDataInSidebar: true,
  },
  bring_data: {
    label: 'I have my data in Excel or on paper',
    hint: 'Help me bring it in.',
    checklist: true,
    whyLines: false,
    dataSteps: true,
    whereThingsAre: false,
    shortSidebar: false,
    strips: 'data',
    termsUnderlined: false,
    bringDataInSidebar: true,
  },
  switching: {
    label: "I've used other construction software",
    hint: 'Show me where things are.',
    checklist: true,
    whyLines: false,
    dataSteps: true,
    whereThingsAre: true,
    shortSidebar: false,
    strips: 'none',
    termsUnderlined: false,
    bringDataInSidebar: false,
  },
  free: {
    label: "I'll find my way",
    hint: 'No tips.',
    checklist: false,
    whyLines: false,
    dataSteps: false,
    whereThingsAre: false,
    shortSidebar: false,
    strips: 'none',
    termsUnderlined: false,
    bringDataInSidebar: false,
  },
}

export const START_MODES = Object.keys(MODES) as StartMode[]

export interface Preferences {
  reply_language: string | null
  voice_transcript: boolean
  start_mode: string
  ask_start_mode: boolean
  guide_seen: Record<string, number>
}

const KEY = ['me-preferences']

function asMode(value: string | undefined): StartMode {
  // Plan 6.7 rule 7: an answer that no longer exists falls back to the safe side.
  return value && value in MODES ? (value as StartMode) : 'guided'
}

/** The person's preferences (GET /me/preferences), read once and shared. */
export function usePreferences() {
  const { me } = useAuth()
  return useQuery({
    queryKey: KEY,
    queryFn: async () => (await api.get<Preferences>('/me/preferences')).data,
    enabled: !!me && !me.is_platform_admin,
    staleTime: 5 * 60_000,
  })
}

/** How Mesiri guides this person. While loading, nothing is shown (`ready` false), so no tip flashes up. */
export function useStartMode(): { mode: StartMode; rules: ModeRules; ask: boolean; ready: boolean; seen: Record<string, number> } {
  const prefs = usePreferences()
  // A platform admin, or preferences that could not be read: no guidance at all.
  const mode = prefs.data ? asMode(prefs.data.start_mode) : 'free'
  return { mode, rules: MODES[mode], ask: !!prefs.data?.ask_start_mode, ready: !!prefs.data, seen: prefs.data?.guide_seen ?? {} }
}

function merge(qc: ReturnType<typeof useQueryClient>, patch: Partial<Preferences>) {
  qc.setQueryData<Preferences>(KEY, (old) => (old ? { ...old, ...patch } : old))
}

export function useSetStartMode() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (mode: StartMode) => (await api.put<Preferences>('/me/start-mode', { start_mode: mode })).data,
    onSuccess: (out) => merge(qc, { start_mode: out.start_mode, ask_start_mode: false }),
  })
}

export function useGuideSeen() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ page, version }: { page: string; version: number }) =>
      (await api.post<Preferences>('/me/guide-seen', { page, version })).data,
    onMutate: ({ page, version }) => {
      // Closed at once; the server agrees a moment later.
      const old = qc.getQueryData<Preferences>(KEY)
      if (old) merge(qc, { guide_seen: { ...old.guide_seen, [page]: version } })
    },
    onSuccess: (out) => merge(qc, { guide_seen: out.guide_seen }),
  })
}

/** "Show me around again": every page strip shows once more. */
export function useResetGuides() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => (await api.delete<Preferences>('/me/guide-seen')).data,
    onSuccess: () => merge(qc, { guide_seen: {} }),
  })
}

// SS-31: "Show everything" in the short sidebar, kept per browser (like the planned-modules preview). It never
// hides a page from someone allowed to see it: search (Ctrl K) and every link still reach every page.
const SHOW_ALL_KEY = 'mesiri_show_everything'
const SHOW_ALL_EVENT = 'mesiri-show-everything'

function readShowAll(): boolean {
  try {
    return localStorage.getItem(SHOW_ALL_KEY) === '1'
  } catch {
    return false
  }
}

export function useShowEverything(): [boolean, (on: boolean) => void] {
  const [on, setOn] = React.useState(readShowAll)
  React.useEffect(() => {
    const sync = () => setOn(readShowAll())
    window.addEventListener(SHOW_ALL_EVENT, sync)
    window.addEventListener('storage', sync)
    return () => {
      window.removeEventListener(SHOW_ALL_EVENT, sync)
      window.removeEventListener('storage', sync)
    }
  }, [])
  const set = React.useCallback((next: boolean) => {
    try {
      localStorage.setItem(SHOW_ALL_KEY, next ? '1' : '0')
    } catch {
      // Private window: kept for this page only.
    }
    setOn(next)
    window.dispatchEvent(new Event(SHOW_ALL_EVENT))
  }, [])
  return [on, set]
}
