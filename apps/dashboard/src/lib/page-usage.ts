import * as React from 'react'
import { useLocation } from 'react-router-dom'
import { useAuth } from './AuthContext'
import { findPage } from './module-map'

// UX-70 (asked 18 Nov 2026: "track the routes they use the most and put it in top if that is a good idea"): which pages
// this person opens, kept in this browser per person. Used where it helps without moving anything under their hand:
// Search lists their most used pages first, and the sidebar offers to pin a page they keep opening that isn't pinned.
// The sidebar never reorders itself: rows that move are rows people mis-tap. Real time, not the sample company's clock.

const KEY = 'mesiri.page-use'
/** A visit counts once per page per half hour (filters and back-and-forth are one visit). */
const REVISIT_MS = 30 * 60_000
/** Older visits count less: a visit two weeks ago counts half. */
const HALF_LIFE_MS = 14 * 24 * 3_600_000
const KEEP = 60
const CHANGE = 'mesiri:page-use'

export type PageUse = { score: number; last: number; days: number; lastDay: string }
type Store = Record<string, Record<string, PageUse>>

function read(): Store {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? '{}') as Store
  } catch {
    return {}
  }
}

function decayed(u: PageUse, now: number): number {
  return u.score * Math.pow(0.5, (now - u.last) / HALF_LIFE_MS)
}

/** Count a visit to a page (its module-map url) for this person. */
export function recordVisit(person: string, url: string, now = Date.now()) {
  const store = read()
  const mine = store[person] ?? {}
  const old = mine[url]
  if (old && now - old.last < REVISIT_MS) return
  const day = new Date(now).toISOString().slice(0, 10)
  mine[url] = {
    score: (old ? decayed(old, now) : 0) + 1,
    last: now,
    days: (old?.days ?? 0) + (old?.lastDay === day ? 0 : 1),
    lastDay: day,
  }
  // Keep the list short: the least used go first.
  const kept = Object.entries(mine).sort((a, b) => decayed(b[1], now) - decayed(a[1], now)).slice(0, KEEP)
  store[person] = Object.fromEntries(kept)
  try {
    localStorage.setItem(KEY, JSON.stringify(store))
    window.dispatchEvent(new Event(CHANGE))
  } catch {
    // Private window or full storage: nothing is tracked, nothing breaks.
  }
}

/** Counts every page this person opens (mounted once, in the app layout). */
export function usePageTracking() {
  const { me } = useAuth()
  const person = me?.user_id ?? ''
  const { pathname, search } = useLocation()
  React.useEffect(() => {
    if (!person) return
    const hit = findPage(pathname, search)
    if (hit && hit.page.status === 'built') recordVisit(person, hit.page.url)
  }, [person, pathname, search])
}

export type UsedPage = { url: string; score: number; days: number }

/** This person's pages, most used first (score decays with time). */
export function usePageUsage(): UsedPage[] {
  const { me } = useAuth()
  const person = me?.user_id ?? ''
  const [tick, setTick] = React.useState(0)
  React.useEffect(() => {
    const on = () => setTick((t) => t + 1)
    window.addEventListener(CHANGE, on)
    window.addEventListener('storage', on)
    return () => {
      window.removeEventListener(CHANGE, on)
      window.removeEventListener('storage', on)
    }
  }, [])
  return React.useMemo(() => {
    void tick
    const now = Date.now()
    return Object.entries(read()[person] ?? {})
      .map(([url, u]) => ({ url, score: decayed(u, now), days: u.days }))
      .sort((a, b) => b.score - a.score)
  }, [person, tick])
}

/** Opened on at least this many different days, and lately: worth a pin. */
export const SUGGEST_DAYS = 3
export const SUGGEST_SCORE = 4

const DISMISS_KEY = 'mesiri.pin-suggest-no'

export function dismissedSuggestions(person: string): string[] {
  try {
    return (JSON.parse(localStorage.getItem(DISMISS_KEY) ?? '{}') as Record<string, string[]>)[person] ?? []
  } catch {
    return []
  }
}

export function dismissSuggestion(person: string, url: string) {
  try {
    const all = JSON.parse(localStorage.getItem(DISMISS_KEY) ?? '{}') as Record<string, string[]>
    all[person] = [...new Set([...(all[person] ?? []), url])]
    localStorage.setItem(DISMISS_KEY, JSON.stringify(all))
    window.dispatchEvent(new Event(CHANGE))
  } catch {
    // ignore
  }
}
