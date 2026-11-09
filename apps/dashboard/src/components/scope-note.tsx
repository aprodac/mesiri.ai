import type { ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { Info, Link2, X } from 'lucide-react'
import { findPage } from '@/lib/module-map'
import { SCOPE_ICON, SCOPE_TONE } from '@/lib/scope-look'
import { useScope } from '@/lib/ScopeContext'
import { scopeLevelOf } from '@/lib/scope-levels'
import { cn } from '@/lib/utils'

// SCP-02: one line at the top of a page saying what its numbers are for, when a project or a site is picked. A page
// that cannot narrow as far as the pick says so, instead of passing a project's or the company's totals off as the
// site's. With all projects picked every page shows everything, so nothing is said. Levels: lib/scope-levels.ts.
export function ScopeNote() {
  const { pathname, search } = useLocation()
  const { scope, arrivedFrom, goBackFromLink, dismissArrival } = useScope()
  const level = scopeLevelOf(pathname)
  // SCP-07: a page of the module map with no row in lib/scope-levels.ts fails the screenshot check (a console error),
  // so a new page cannot ship without saying what it shows.
  if (import.meta.env.DEV && !level && findPage(pathname, search)?.page.status === 'built' && findPage(pathname, search)?.page.url.split('?')[0] === pathname) {
    console.error(`SCP-07: ${pathname} has no row in lib/scope-levels.ts`)
  }
  const arrival = arrivedFrom && scope.mode !== 'portfolio' && (
    <p className="-mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md bg-sky-50 px-2.5 py-1.5 text-xs leading-5 text-sky-900 dark:bg-sky-400/10 dark:text-sky-100" role="status">
      <Link2 className="size-3.5 shrink-0" aria-hidden />
      <span className="min-w-0 flex-1">
        Now showing <b className="font-semibold">{scope.mode === 'site' ? `${scope.siteName} (${scope.projectName})` : scope.projectName}</b> on every page, from a link or Back.
      </span>
      <button type="button" onClick={goBackFromLink} className="font-semibold underline underline-offset-2 hover:no-underline">
        Back to {arrivedFrom.mode === 'portfolio' ? 'all projects' : arrivedFrom.mode === 'site' ? arrivedFrom.siteName : arrivedFrom.projectName}
      </button>
      <button type="button" onClick={dismissArrival} className="rounded p-0.5 hover:bg-sky-100 dark:hover:bg-sky-400/20" aria-label="Keep this view">
        <X className="size-3.5" aria-hidden />
      </button>
    </p>
  )
  if (!level || scope.mode === 'portfolio') return arrival || null

  const where = scope.mode === 'site' ? `${scope.siteName} (${scope.projectName})` : scope.projectName
  let shows: 'portfolio' | 'project' | 'site'
  let text: ReactNode
  if (level === 'company') {
    shows = 'portfolio'
    text = (
      <>
        <b className="font-semibold">Company-wide.</b> This page shows every project, not only {where}.
      </>
    )
  } else if (level === 'project' && scope.mode === 'site') {
    shows = 'project'
    text = (
      <>
        Showing all of <b className="font-semibold">{scope.projectName}</b>. This page doesn’t split by site, so it
        includes more than {scope.siteName}.
      </>
    )
  } else {
    shows = scope.mode
    text = (
      <>
        Showing <b className="font-semibold">{where}</b> only.
      </>
    )
  }
  const wider = shows !== scope.mode
  const Icon = wider ? Info : SCOPE_ICON[shows]
  return (
    <>
    {arrival}
    <p
      className={cn(
        '-mt-1 flex items-start gap-2 rounded-md px-2.5 py-1.5 text-xs leading-5',
        wider ? 'bg-amber-50 text-amber-900 dark:bg-amber-400/10 dark:text-amber-200' : 'text-muted-foreground',
      )}
      role="status"
    >
      <span className={cn('mt-0.5 flex size-4 shrink-0 items-center justify-center rounded', wider ? '' : SCOPE_TONE[shows])}>
        <Icon className="size-3" aria-hidden />
      </span>
      <span className="min-w-0">{text}</span>
    </p>
    </>
  )
}
