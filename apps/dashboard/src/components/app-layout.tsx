import * as React from 'react'
import { Link, Outlet, useLocation } from 'react-router-dom'
import { AlertCircle, CalendarDays, ChevronRight, Map as MapIcon } from 'lucide-react'
import { AppSidebar } from '@/components/app-sidebar'
import { ScopeBar } from '@/components/scope-bar'
import { SidebarInset, SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar'
import { Separator } from '@/components/ui/separator'
import { RequireAuth } from '@/lib/AuthContext'
import { TrialBanner } from '@/components/trial-banner'
import { JumpBox } from '@/components/jump-box'
import { HelpButton } from '@/components/help-button'
import { InboxBell } from '@/components/inbox-bell'
import { useNavCounts } from '@/lib/nav-counts'
import { findPage } from '@/lib/module-map'
import { usePlannedPreview } from '@/lib/preview'
import { routeTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'

// Top bar (WEB-20): stays put while the page scrolls; a thin site-colour
// stripe on top, the scope picker, today's date and the open-issues count.
/** Where you are (WEB-72): "Materials › Movements", from lib/module-map.ts. */
function Breadcrumb() {
  const { pathname, search } = useLocation()
  const hit = findPage(pathname, search)
  if (!hit) return null
  const showModule = hit.group.title !== hit.page.title && hit.group.key !== 'site'
  return (
    <nav aria-label="You are here" className="hidden min-w-0 items-center gap-1 text-sm md:flex">
      <ChevronRight className="size-4 shrink-0 text-muted-foreground/60" aria-hidden />
      {showModule && (
        <>
          <span className="truncate text-muted-foreground">{hit.group.title}</span>
          <ChevronRight className="size-3.5 shrink-0 text-muted-foreground/60" aria-hidden />
        </>
      )}
      <span className="truncate font-medium">{hit.page.title}</span>
      {hit.page.status === 'planned' && (
        <span className="ml-1 shrink-0 rounded-full bg-draft-soft px-2 py-px text-[11px] font-semibold text-draft">Planned</span>
      )}
    </nav>
  )
}

function TopBar() {
  const { drafts, openIssues } = useNavCounts()
  const [showPlanned, setShowPlanned] = usePlannedPreview()
  const today = new Date().toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })
  return (
    <header className="sticky top-0 z-20 shrink-0 border-b bg-background/90 backdrop-blur supports-[backdrop-filter]:bg-background/75">
      <div aria-hidden className="h-[3px] bg-[repeating-linear-gradient(135deg,#1a1d21_0_8px,#facc15_8px_16px)]" />
      <div className="flex h-12 items-center gap-2 px-3 sm:px-4">
        <SidebarTrigger />
        <Separator orientation="vertical" className="mr-1 h-4" />
        <ScopeBar />
        <Breadcrumb />
        <div className="ml-auto flex items-center gap-1.5">
          {showPlanned && (
            <button
              type="button"
              onClick={() => setShowPlanned(false)}
              className="hidden items-center gap-1.5 rounded-full border border-yellow-300/70 bg-yellow-50 px-2.5 py-1 text-xs font-medium text-yellow-900 hover:bg-yellow-100 sm:inline-flex dark:border-yellow-700/60 dark:bg-yellow-950/40 dark:text-yellow-200"
              title="Planned modules are shown. Click to hide them."
            >
              <MapIcon className="size-3.5" /> Preview
            </button>
          )}
          <Link
            to="/today"
            className="hidden items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium text-foreground/80 hover:bg-muted sm:inline-flex"
            title={drafts > 0 ? `${drafts} items to confirm today` : 'Today'}
          >
            <CalendarDays className="size-3.5 text-yellow-700 dark:text-yellow-400" />
            {today}
            {drafts > 0 && (
              <span className="rounded-full bg-orange-500 px-1.5 text-[11px] font-semibold text-white tabular-nums">{drafts}</span>
            )}
          </Link>
          <HelpButton />
          {/* NXT-08: everything waiting for me, each opening its record. */}
          <InboxBell />
          <Link
            to="/issues"
            className={cn(
              'relative inline-flex size-8 items-center justify-center rounded-full hover:bg-muted',
              openIssues > 0 ? 'text-rose-600 dark:text-rose-400' : 'text-muted-foreground',
            )}
            title={openIssues > 0 ? `${openIssues} open issues` : 'No open issues'}
            aria-label={openIssues > 0 ? `${openIssues} open issues` : 'Issues'}
          >
            <AlertCircle className="size-[18px]" />
            {openIssues > 0 && (
              <span className="absolute -top-0.5 -right-0.5 min-w-4 rounded-full bg-rose-500 px-1 text-center text-[10px] font-semibold leading-4 text-white ring-2 ring-background tabular-nums">
                {openIssues > 99 ? '99+' : openIssues}
              </span>
            )}
          </Link>
        </div>
      </div>
    </header>
  )
}

export function AppLayout() {
  const { pathname } = useLocation()
  // Default tab title per route; a page naming its exact subject overrides
  // it (usePageTitle runs in a passive effect, after this one).
  React.useLayoutEffect(() => {
    document.title = routeTitle(pathname)
  }, [pathname])
  return (
    <RequireAuth>
      {/* Keyboard users jump past the sidebar to the page. */}
      <a
        href="#main-content"
        className="sr-only z-50 rounded-md bg-primary px-3 py-2 text-sm font-semibold text-primary-foreground focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Skip to content
      </a>
      <JumpBox />
      <SidebarProvider>
        <AppSidebar />
        <SidebarInset>
          <TopBar />
          <div id="main-content" tabIndex={-1} className="flex flex-1 flex-col gap-4 p-4 outline-none">
            <TrialBanner />
            <Outlet />
          </div>
        </SidebarInset>
      </SidebarProvider>
    </RequireAuth>
  )
}
