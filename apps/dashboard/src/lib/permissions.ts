import type { AccessPolicy } from './api'
import type { ScopeKind } from './scope-types'

// The V1 role vocabulary, matching backend/src/mesiri/domains/users/router.py's
// _VALID_ROLES exactly — do not invent new role strings here.
export type Role = 'ADMIN' | 'PROJECT_MANAGER' | 'SITE_ENGINEER' | 'FINANCE'

// What each role is called on screen. Codes stay in data and API calls.
export const ROLE_LABELS: Record<Role, string> = {
  ADMIN: 'Admin / Director',
  PROJECT_MANAGER: 'Project Manager',
  SITE_ENGINEER: 'Site Engineer',
  FINANCE: 'Finance / Accountant',
}

export function roleLabel(role: string | null | undefined): string {
  return ROLE_LABELS[role as Role] ?? (role || '—')
}

// V1 access matrix (Portfolio / Project / Site). Finance uses the same 3
// scopes as everyone else — there is no separate "Finance Mode."
const ROLE_SCOPES: Record<Role, ScopeKind[]> = {
  ADMIN: ['portfolio', 'project', 'site'],
  PROJECT_MANAGER: ['project', 'site'],
  SITE_ENGINEER: ['site'],
  FINANCE: ['portfolio', 'project', 'site'],
}

/**
 * Scopes a role is allowed to reach at all. Portfolio access for FINANCE is
 * further gated by whether their access_policy grants org-wide visibility
 * (mode === 'all_projects') — see allowedScopes() below, which is the one
 * function everything else (sidebar, scope bar, route guards) should call.
 */
export function scopesForRole(role: string): ScopeKind[] {
  return ROLE_SCOPES[role as Role] ?? []
}

export function allowedScopes(role: string, accessPolicy: AccessPolicy | null | undefined): ScopeKind[] {
  const base = scopesForRole(role)
  if (role === 'FINANCE' && accessPolicy?.mode !== 'all_projects') {
    return base.filter((scope) => scope !== 'portfolio')
  }
  return base
}

export function highestAllowedScope(role: string, accessPolicy: AccessPolicy | null | undefined): ScopeKind | null {
  const scopes = allowedScopes(role, accessPolicy)
  if (scopes.includes('portfolio')) return 'portfolio'
  if (scopes.includes('project')) return 'project'
  if (scopes.includes('site')) return 'site'
  return null
}
