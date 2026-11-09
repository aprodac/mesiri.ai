import { useAuth } from '@/lib/AuthContext'

/**
 * Product modules a company can have switched on (tracker BE-06 / WEB-02).
 * Mirrors the backend catalogue in domains/organizations/settings.py.
 * `dpr` is always on.
 */
export type ModuleKey = 'dpr' | 'labour' | 'materials' | 'finance' | 'equipment' | 'automations' | 'cost' | 'accounts' | 'tasks'

export const MODULE_NAMES: Record<ModuleKey, string> = {
  dpr: 'Daily progress',
  labour: 'Labour',
  materials: 'Materials',
  equipment: 'Equipment',
  finance: 'Finance',
  cost: 'Cost control',
  accounts: 'Accounts',
  tasks: 'Tasks',
  automations: 'Automations',
}

/** Every module, in the order the Settings page lists them. Read from MODULE_NAMES (a Record over ModuleKey), so a
 *  new module is listed as soon as it has a name: Tasks was missing from a hand-kept copy (9 Nov 2026). */
export const MODULE_KEYS = Object.keys(MODULE_NAMES) as ModuleKey[]

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
