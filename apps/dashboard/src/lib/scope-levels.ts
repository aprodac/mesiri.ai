import { matchPath } from 'react-router-dom'

// SCP-02: how far each page narrows when a project or a site is picked in the top bar, so the page can say what
// it is showing instead of letting a company-wide total pass for one site's. One table, by route; a new page adds
// its row here. Record pages (one bill, one machine, one person) have no row: they are about that record.
//   site     follows the project and the site picked
//   project  follows the project; with a site picked it still shows the whole project
//   company  the whole company whatever is picked

export type ScopeLevel = 'site' | 'project' | 'company'

const LEVELS: [string, ScopeLevel][] = [
  // Daily
  ['/today', 'site'],
  ['/reports', 'site'],
  ['/issues', 'site'],
  ['/site-log', 'site'],
  ['/analytics', 'site'],
  ['/tasks', 'site'],
  // Site
  ['/labour', 'site'],
  ['/labour/wages', 'site'],
  ['/labour/advances', 'site'],
  ['/materials', 'site'],
  ['/materials/requests', 'site'],
  ['/equipment', 'site'],
  ['/equipment/vehicles', 'site'],
  ['/equipment/log', 'site'],
  ['/equipment/assets', 'site'],
  ['/equipment/hire', 'company'],
  // Buy
  ['/procurement/orders', 'site'],
  ['/procurement/grn', 'site'],
  ['/procurement/rates', 'site'],
  ['/subcontract/work-orders', 'site'],
  ['/subcontract/bills', 'site'],
  ['/subcontract/teams', 'project'],
  // Money
  ['/finance/expenses', 'site'],
  ['/finance/money', 'site'],
  ['/finance/vendors', 'project'],
  ['/finance/reports', 'company'],
  ['/finance/settings', 'company'],
  ['/billing/clients', 'project'],
  ['/billing/ra-bills', 'project'],
  ['/billing/client-view', 'company'],
  ['/accounts', 'project'],
  ['/accounts/receivables', 'company'],
  ['/accounts/pl', 'site'],
  ['/accounts/trial-balance', 'site'],
  ['/accounts/cash-bank', 'site'],
  ['/accounts/day-book', 'site'],
  ['/accounts/ledgers', 'company'],
  ['/accounts/balance-sheet', 'company'],
  ['/accounts/projects', 'company'],
  ['/accounts/gst', 'company'],
  ['/accounts/tds', 'company'],
  ['/accounts/chart', 'company'],
  ['/accounts/periods', 'company'],
  ['/accounts/tally', 'company'],
  ['/cost', 'project'],
  ['/cost/green-red', 'site'],
  ['/cost/centres', 'site'],
  ['/cost/materials', 'project'],
  ['/cost/budget', 'project'],
  // Plan
  ['/boq', 'project'],
  ['/planning/setup', 'project'],
  ['/planning/schedule', 'project'],
  ['/planning/materials', 'project'],
  ['/planning/places', 'project'],
  ['/planning/documents', 'project'],
  ['/planning/live', 'project'],
  ['/planning/drawing-check', 'project'],
  // Settings
  ['/projects', 'company'],
  ['/team', 'company'],
  ['/settings', 'company'],
  ['/settings/activity', 'company'],
  ['/company', 'company'],
  ['/whatsapp', 'company'],
]

const BY_PATH = new Map(LEVELS)

/** The level a page follows, or null for a record page (or a page not in the table). */
export function scopeLevelOf(pathname: string): ScopeLevel | null {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname
  if (BY_PATH.has(path)) return BY_PATH.get(path)!
  if (matchPath('/projects/:id/*', path)) return 'project'
  return null
}

/** Every route in the table, for the check that keeps it in step with App.tsx. */
export const SCOPE_LEVEL_PATHS = LEVELS.map(([p]) => p)
