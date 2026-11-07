import * as React from 'react'
import { findPage } from './module-map'

const APP = 'Mesiri'

/** The browser tab title for a page: "Tower 1 · Site DPR · Mesiri". AppLayout
 * sets a default per route in a layout effect; a page calling this (a passive
 * effect, so it runs after) can name the exact thing it shows. */
export function usePageTitle(title: string | null | undefined): void {
  React.useEffect(() => {
    if (title) document.title = `${title} · ${APP}`
  }, [title])
}

const ROUTE_TITLES: [string, string][] = [
  ['/today', 'Today'],
  ['/reports', 'Reports'],
  ['/issues', 'Issues'],
  ['/site-log', 'Site log'],
  ['/analytics', 'Analytics'],
  ['/labour/attendance', 'Attendance'],
  ['/labour/workers', 'Workers'],
  ['/labour', 'Labour'],
  ['/materials', 'Materials'],
  ['/projects', 'Projects & Sites'],
  ['/team', 'Team'],
  ['/company', 'Company'],
  ['/whatsapp', 'WhatsApp'],
  ['/finance', 'Finance'],
]

/** Default tab title for a path; see usePageTitle. */
export function routeTitle(pathname: string): string {
  // Planned module pages (WEB-72) are named by lib/module-map.ts.
  const page = findPage(pathname)
  if (page?.page.status === 'planned') return `${page.page.title} · ${APP}`
  const hit = ROUTE_TITLES.find(([prefix]) => pathname === prefix || pathname.startsWith(`${prefix}/`))
  return hit ? `${hit[1]} · ${APP}` : page ? `${page.page.title} · ${APP}` : APP
}
