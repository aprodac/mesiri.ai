import type { ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { Info, Undo2, X } from 'lucide-react'
import { findPage } from '@/lib/module-map'
import { useScope } from '@/lib/ScopeContext'
import { scopeLevelOf } from '@/lib/scope-levels'

// SCP-02: a page that cannot narrow as far as the project or site picked says so in one amber chip, instead of
// passing a project's or the company's totals off as the site's. A page that shows exactly the pick says nothing
// (UX-14): the top bar names it. Levels: lib/scope-levels.ts.
export function ScopeNote() {
  const { pathname, search } = useLocation()
  const { scope } = useScope()
  const level = scopeLevelOf(pathname)
  // SCP-07: a page of the module map with no row in lib/scope-levels.ts fails the screenshot check (a console error),
  // so a new page cannot ship without saying what it shows.
  if (import.meta.env.DEV && !level && findPage(pathname, search)?.page.status === 'built' && findPage(pathname, search)?.page.url.split('?')[0] === pathname) {
    console.error(`SCP-07: ${pathname} has no row in lib/scope-levels.ts`)
  }
  if (!level || scope.mode === 'portfolio') return null

  let wider: ReactNode = null
  if (level === 'company') wider = <><b className="font-semibold">Company-wide:</b> every project</>
  else if (level === 'project' && scope.mode === 'site') wider = <><b className="font-semibold">Whole project:</b> not split by site</>
  if (!wider) return null
  return (
      <p className="-mt-1 flex w-fit max-w-full items-center gap-1.5 rounded-full bg-draft-soft px-2.5 py-1 text-xs leading-5 text-draft" role="status">
        <Info className="size-3.5 shrink-0" aria-hidden />
        <span className="min-w-0 truncate">{wider}</span>
      </p>
  )
}

// A link moved the view to a project or site the person did not pick (they followed a record's link). The top bar's
// picker already names where they are now, so this sits beside it as one small way back, not a row on the page.
export function ArrivalBack() {
  const { scope, arrivedFrom, goBackFromLink, dismissArrival } = useScope()
  if (!arrivedFrom || scope.mode === 'portfolio') return null
  const to = arrivedFrom.mode === 'portfolio' ? 'All projects' : arrivedFrom.mode === 'site' ? arrivedFrom.siteName : arrivedFrom.projectName
  return (
    <span className="inline-flex shrink-0 items-center rounded-full border bg-background text-xs font-medium text-foreground/80" role="status">
      <button
        type="button"
        onClick={goBackFromLink}
        className="inline-flex items-center gap-1 rounded-l-full py-1 pr-1 pl-2 hover:bg-muted hover:text-foreground"
        title={`The link opened ${scope.mode === 'site' ? scope.siteName : scope.projectName}. Go back to ${to}.`}
      >
        <Undo2 className="size-3.5" aria-hidden />
        <span className="hidden max-w-32 truncate sm:inline">{to}</span>
        <span className="sr-only sm:hidden">Back to {to}</span>
      </button>
      <button type="button" onClick={dismissArrival} className="rounded-r-full py-1 pr-1.5 pl-0.5 text-muted-foreground hover:bg-muted hover:text-foreground" aria-label="Stay here">
        <X className="size-3" aria-hidden />
      </button>
    </span>
  )
}
