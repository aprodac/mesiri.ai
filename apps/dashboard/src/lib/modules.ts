import { useAuth } from '@/lib/AuthContext'

/**
 * Product modules a company can have switched on (tracker BE-06 / WEB-02).
 * Mirrors the backend catalogue in domains/organizations/settings.py.
 * `dpr` is always on.
 */
export type ModuleKey = 'dpr' | 'labour' | 'materials' | 'finance' | 'automations'

export const MODULE_NAMES: Record<ModuleKey, string> = {
  dpr: 'Daily progress',
  labour: 'Labour',
  materials: 'Materials',
  finance: 'Finance',
  automations: 'Automations',
}

/**
 * Whether a module is switched on for the signed-in company. `/auth/me`
 * returns `enabled_modules`; if it is missing (an older API), nothing is
 * hidden -- the API's own MODULE_DISABLED check still applies.
 */
export function useModuleEnabled(): (module: ModuleKey | undefined) => boolean {
  const { me } = useAuth()
  const enabled = me?.enabled_modules
  return (module) => !module || module === 'dpr' || !enabled || enabled.includes(module)
}
