import type { ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { Info, Link2, X } from 'lucide-react'
import { findPage } from '@/lib/module-map'
import { useScope } from '@/lib/ScopeContext'
import { scopeLevelOf } from '@/lib/scope-levels'

// SCP-02: a page that cannot narrow as far as the project or site picked says so in one amber chip, instead of
// passing a project's or the company's totals off as the site's. A page that shows exactly the pick says nothing
// (UX-14): the top bar names it. Levels: lib/scope-levels.ts.
export function ScopeNote() {
  const { pathname, search } = useLocation()
  const { scope, arrivedFrom, goBackFromLink, dismissArrival } = useScope()
  const level = scopeLevelOf(pathname)
  // SCP-07: a page of the module map with no row in lib/scope-levels.ts fails the screenshot check (a console error),
  // so a new page cannot ship without saying what it shows.
  if (import.meta.env.DEV && !level && findPage(pathname, search)?.page.status === 'built' && findPage(pathname, search)?.page.url.split('?')[0] === pathname) {
    console.error(`SCP-07: ${pathname} has no row in lib/scope-levels.ts`)
  }
  // UX-14: the top bar already names the project or site picked, so a page that shows exactly that says nothing.
  // Only two things are worth a line: the view changed without the person choosing it, or the page shows more
  // than the pick.
  const arrival = arrivedFrom && scope.mode !== 'portfolio' && (
    <p className="-mt-1 flex w-fit max-w-full flex-wrap items-center gap-x-2 gap-y-1 rounded-full bg-info-soft py-1 pr-1.5 pl-2.5 text-xs leading-5 text-info" role="status">
      <Link2 className="size-3.5 shrink-0" aria-hidden />
      <span className="min-w-0 truncate">
        Switched to <b className="font-semibold">{scope.mode === 'site' ? scope.siteName : scope.projectName}</b>
      </span>
      <button type="button" onClick={goBackFromLink} className="font-semibold underline underline-offset-2 hover:no-underline">
        Back to {arrivedFrom.mode === 'portfolio' ? 'all projects' : arrivedFrom.mode === 'site' ? arrivedFrom.siteName : arrivedFrom.projectName}
      </button>
      <button type="button" onClick={dismissArrival} className="rounded-full p-0.5 hover:bg-info/10" aria-label="Keep this view">
        <X className="size-3.5" aria-hidden />
      </button>
    </p>
  )
  if (!level || scope.mode === 'portfolio') return arrival || null

  let wider: ReactNode = null
  if (level === 'company') wider = <><b className="font-semibold">Company-wide:</b> every project</>
  else if (level === 'project' && scope.mode === 'site') wider = <><b className="font-semibold">Whole project:</b> not split by site</>
  if (!wider) return arrival || null
  return (
    <>
      {arrival}
      <p className="-mt-1 flex w-fit max-w-full items-center gap-1.5 rounded-full bg-draft-soft px-2.5 py-1 text-xs leading-5 text-draft" role="status">
        <Info className="size-3.5 shrink-0" aria-hidden />
        <span className="min-w-0 truncate">{wider}</span>
      </p>
    </>
  )
}
