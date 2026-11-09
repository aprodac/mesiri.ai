// SCP-01: the last few projects and sites picked in the top bar, for the panel's "Recent" list. Per browser.

const RECENT_STORAGE_KEY = 'mesiri_dashboard_scope_recent'

/** A pick in the scope panel's "Recent" list (SCP-01): a project, or a site of one. */
export type RecentScope = { projectId: string; siteId?: string }

export function readRecentScopes(): RecentScope[] {
  try {
    const raw = JSON.parse(localStorage.getItem(RECENT_STORAGE_KEY) || '[]')
    return Array.isArray(raw) ? raw.filter((r) => r && typeof r.projectId === 'string').slice(0, 5) : []
  } catch {
    return []
  }
}

export function rememberRecent(pick: RecentScope) {
  try {
    const rest = readRecentScopes().filter((r) => !(r.projectId === pick.projectId && (r.siteId ?? '') === (pick.siteId ?? '')))
    localStorage.setItem(RECENT_STORAGE_KEY, JSON.stringify([pick, ...rest].slice(0, 5)))
  } catch {
    // storage unavailable: no recent list, nothing else changes
  }
}
