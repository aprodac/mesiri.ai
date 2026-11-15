import { findPage } from './module-map'

// SS-37 (guided-onboarding-plan.md 6.7 rule 3): a guide never links to a page that is gone. Every link the
// guidance uses (checklist steps, "Bring your data" rows, tips) goes through guideLink, which checks it against
// lib/module-map.ts. In development a dead or planned link is a console error, which fails the UX-10 screenshot
// run (scripts/screens.mjs fails on any console error), so a page renamed or removed without fixing its guidance
// is caught before the push. In production the link is returned unchanged and nothing is logged.

/** Pages outside the module map that guidance may link to. */
const OUTSIDE_MAP = new Set(['/welcome', '/live', '/company'])

export function guideLinkProblem(url: string): string | null {
  const [path, query = ''] = url.split('?')
  if (OUTSIDE_MAP.has(path)) return null
  const hit = findPage(path, query ? `?${query}` : '')
  if (!hit) return `${url} is not a page in lib/module-map.ts`
  if (hit.page.status !== 'built') return `${url} is a planned page, not built yet`
  return null
}

export function guideLink(url: string): string {
  if (import.meta.env.DEV) {
    const problem = guideLinkProblem(url)
    if (problem) console.error(`[guide] ${problem}: fix the guidance that links to it (SS-37)`)
  }
  return url
}
