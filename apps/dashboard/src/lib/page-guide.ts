import type { ModulePage } from './module-map'
import type { ModeRules } from './start-mode'

// SS-29/SS-37: which page explains itself, for which start mode (components/page-guide.tsx draws it).

/** Pages that bring data in: the only strips `bring_data` mode shows. */
export const DATA_PAGES: readonly string[] = ['/bring-data', '/materials', '/boq', '/planning/documents', '/projects', '/team']

/** The key a page's strip is remembered by: its path, without ?view= (all views share one strip). */
export function guideKey(page: ModulePage): string {
  return page.url.split('?')[0]
}

export type StripKind = 'first' | 'updated' | null

/** Which strip a page gets for this mode, or none. Pure, so the rule reads in one place. */
export function stripFor(page: ModulePage, rules: ModeRules, seen: Record<string, number>): StripKind {
  if (page.status !== 'built') return null
  const key = guideKey(page)
  if (rules.strips === 'none' || (rules.strips === 'data' && !DATA_PAGES.includes(key))) return null
  const version = page.guideVersion ?? 1
  const closed = seen[key]
  if (closed === undefined) return 'first'
  if (closed < version && page.guideNew) return 'updated'
  return null
}
