import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AS_ME, api } from './api'
import { inSandbox } from './sandbox'
import { useAuth } from './AuthContext'

// Guided onboarding (SS-27..SS-37, docs/plans/guided-onboarding-plan.md): how Mesiri guides this person, from
// their answer to "How would you like to start?". It changes help only, never what they may see or do.
//
// Rule 4 of the plan's section 6.7: the modes are data. What each mode gets is the one table below; a page or
// component asks the table ("does this mode show page strips?"), never "is the mode guided?". Changing what a mode
// shows, or adding one, is an edit here (and to START_MODES in the backend and migration 0553's check).

export type StartMode = 'new_to_construction' | 'guided' | 'bring_data' | 'switching' | 'free'

/**
 * UX-22: whose words the help panel and the page tours use. A tour step or a page's help can carry its own words for
 * each kind of person (lib/tours.ts `for`, lib/page-help.ts `for`); a page that has none for this person falls back
 * along WORDS_FALLBACK to the plain words, so every page works for everyone before it is written for them.
 * - basics: new to construction too: what the thing is in real life, the site words explained, one idea per step
 * - steps: new to tools like this, knows construction: what to do here, one step at a time
 * - data: has it in Excel or on paper: where their data goes and how it comes in
 * - expert: used other construction software: what is different here, in a line
 */
export type GuideWords = 'basics' | 'steps' | 'data' | 'expert'

/** Where words not written for a kind of person come from: the next in the list, then the plain words. */
export const WORDS_FALLBACK: Record<GuideWords, GuideWords[]> = {
  basics: ['basics', 'steps'],
  steps: ['steps'],
  data: ['data'],
  expert: ['expert'],
}

/** Which of the kinds written for in `own` speaks to this person, or null when none does. */
export function wordsKey(words: GuideWords | null, own: Partial<Record<GuideWords, unknown>> | undefined): GuideWords | null {
  if (!words || !own) return null
  return WORDS_FALLBACK[words].find((w) => own[w] !== undefined) ?? null
}

/** This person's own words from a set written per kind of person, or `plain` when none is written for them. */
export function wordsFor<T>(words: GuideWords | null, own: Partial<Record<GuideWords, T>> | undefined, plain: T): T {
  const key = wordsKey(words, own)
  return key ? (own![key] as T) : plain
}

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
  /** The Spark's guided tours (components/tour.tsx): the app tour and every page's, only the app tour, or none. */
  tours: 'all' | 'app' | 'none'
  /** UX-22: whose words help and tours use (GuideWords); null: the plain words. */
  words: GuideWords | null
  /** UX-22: the short name of this kind of person, as the help panel shows it ("Explained for: New to construction"). */
  forWho: string
}

export const MODES: Record<StartMode, ModeRules> = {
  // UX-22 (asked 17 Nov: "another role, a total beginner who does not even know construction much"): everything step
  // by step gets, plus the site itself explained (what a BOQ line, a cum, a margin is), in the help and the tours.
  new_to_construction: {
    label: "I'm new to construction",
    hint: 'Explain the site words too.',
    checklist: true,
    whyLines: true,
    dataSteps: false,
    whereThingsAre: false,
    shortSidebar: true,
    strips: 'all',
    termsUnderlined: true,
    bringDataInSidebar: true,
    tours: 'all',
    words: 'basics',
    forWho: 'New to construction',
  },
  guided: {
    label: 'Show me step by step',
    hint: "I know construction; I'm new to tools like this.",
    checklist: true,
    whyLines: true,
    dataSteps: false,
    whereThingsAre: false,
    shortSidebar: true,
    strips: 'all',
    termsUnderlined: true,
    bringDataInSidebar: true,
    tours: 'all',
    words: 'steps',
    forWho: 'New to tools like this',
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
    tours: 'app',
    words: 'data',
    forWho: 'Bringing data from Excel',
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
    tours: 'app',
    words: 'expert',
    forWho: 'Used other software',
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
    tours: 'none',
    words: null,
    forWho: 'Everyone',
  },
}

export const START_MODES = Object.keys(MODES) as StartMode[]

export interface Preferences {
  reply_language: string | null
  voice_transcript: boolean
  start_mode: string
  ask_start_mode: boolean
  guide_seen: Record<string, number>
  /** The number people message Mesiri on, for "Try it on WhatsApp"; null when not set. */
  whatsapp_number?: string | null
  /** UX-65: their own sidebar (lib/sidebar-prefs.ts); null: never changed, their role's default. */
  sidebar?: { pins: string[]; order: string[]; hidden: string[] } | null
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
    mutationFn: async (mode: StartMode) => {
      const out = (await api.put<Preferences>('/me/start-mode', { start_mode: mode })).data
      // Inside the sample company the choice is still the person's own: saved on their account too, which every person
      // in the sample company takes each time it is opened or the role changes (SS-66), so it is never put back.
      if (inSandbox()) await api.put('/me/start-mode', { start_mode: mode }, AS_ME)
      return out
    },
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
