import { getToken } from './api'
import type { AppScope } from './scope-types'

// SCP-01/05: what the browser remembers about the top-bar pick.
//   - The pick itself, for this login only: a new login (another person on the office computer, or the same person
//     next week) starts where their role works, not on yesterday's site.
//   - The person's recent picks and the project they said they mostly work on: per person, across logins.

const SCOPE_STORAGE_KEY = 'mesiri_dashboard_scope'
const RECENT_PREFIX = 'mesiri_dashboard_scope_recent:'
const START_PREFIX = 'mesiri_dashboard_start_project:'

/** A short fingerprint of this login's token, so a pick saved under another login is never restored. */
function loginKey(): string {
  const token = getToken() ?? ''
  let h = 5381
  for (let i = 0; i < token.length; i++) h = ((h << 5) + h + token.charCodeAt(i)) | 0
  return `${token.length}.${(h >>> 0).toString(36)}`
}

export function readStoredScope(): AppScope | null {
  try {
    const raw = JSON.parse(localStorage.getItem(SCOPE_STORAGE_KEY) || 'null')
    if (raw && raw.login === loginKey() && raw.scope && typeof raw.scope.mode === 'string') return raw.scope as AppScope
  } catch {
    // malformed: treated as nothing stored
  }
  return null
}

export function storeScope(scope: AppScope) {
  try {
    localStorage.setItem(SCOPE_STORAGE_KEY, JSON.stringify({ login: loginKey(), scope }))
  } catch {
    // storage unavailable: the scope still works from the address
  }
}

export function forgetStoredScope() {
  try {
    localStorage.removeItem(SCOPE_STORAGE_KEY)
  } catch {
    // storage unavailable: nothing to forget
  }
}

/** A pick in the scope panel's "Recent" list: a project, or a site of one. */
export type RecentScope = { projectId: string; siteId?: string }

export function readRecentScopes(userId: string | undefined): RecentScope[] {
  if (!userId) return []
  try {
    const raw = JSON.parse(localStorage.getItem(RECENT_PREFIX + userId) || '[]')
    return Array.isArray(raw) ? raw.filter((r) => r && typeof r.projectId === 'string').slice(0, 5) : []
  } catch {
    return []
  }
}

export function rememberRecent(userId: string | undefined, pick: RecentScope) {
  if (!userId) return
  try {
    const rest = readRecentScopes(userId).filter((r) => !(r.projectId === pick.projectId && (r.siteId ?? '') === (pick.siteId ?? '')))
    localStorage.setItem(RECENT_PREFIX + userId, JSON.stringify([pick, ...rest].slice(0, 5)))
  } catch {
    // storage unavailable: no recent list, nothing else changes
  }
}

/** The project a person said they mostly work on (asked once), 'skip' if they chose not to say, null if never asked. */
export function readStartProject(userId: string | undefined): string | null {
  if (!userId) return null
  try {
    return localStorage.getItem(START_PREFIX + userId)
  } catch {
    return 'skip' // storage unavailable: never ask (the answer could not be kept)
  }
}

export function saveStartProject(userId: string | undefined, projectId: string | 'skip') {
  if (!userId) return
  try {
    localStorage.setItem(START_PREFIX + userId, projectId)
  } catch {
    // storage unavailable: asked again next login
  }
}
