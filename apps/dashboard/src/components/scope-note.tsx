import type { ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { Info } from 'lucide-react'
import { SCOPE_ICON, SCOPE_TONE } from '@/lib/scope-look'
import { useScope } from '@/lib/ScopeContext'
import { scopeLevelOf } from '@/lib/scope-levels'
import { cn } from '@/lib/utils'

// SCP-02: one line at the top of a page saying what its numbers are for, when a project or a site is picked. A page
// that cannot narrow as far as the pick says so, instead of passing a project's or the company's totals off as the
// site's. With all projects picked every page shows everything, so nothing is said. Levels: lib/scope-levels.ts.
export function ScopeNote() {
  const { pathname } = useLocation()
  const { scope } = useScope()
  const level = scopeLevelOf(pathname)
  if (!level || scope.mode === 'portfolio') return null

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
  )
}
