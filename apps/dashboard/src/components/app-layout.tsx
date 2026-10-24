import { Link, Outlet } from 'react-router-dom'
import { AlertCircle, CalendarDays } from 'lucide-react'
import { AppSidebar } from '@/components/app-sidebar'
import { ScopeBar } from '@/components/scope-bar'
import { SidebarInset, SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar'
import { Separator } from '@/components/ui/separator'
import { RequireAuth } from '@/lib/AuthContext'
import { TrialBanner } from '@/components/trial-banner'
import { useNavCounts } from '@/lib/nav-counts'
import { cn } from '@/lib/utils'

// Top bar (WEB-20): stays put while the page scrolls; a thin site-colour
// stripe on top, the scope picker, today's date and the open-issues count.
function TopBar() {
  const { drafts, openIssues } = useNavCounts()
  const today = new Date().toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })
  return (
    <header className="sticky top-0 z-20 shrink-0 border-b bg-background/90 backdrop-blur supports-[backdrop-filter]:bg-background/75">
      <div aria-hidden className="h-[3px] bg-gradient-to-r from-orange-600 via-amber-500 to-yellow-400" />
      <div className="flex h-12 items-center gap-2 px-3 sm:px-4">
        <SidebarTrigger />
        <Separator orientation="vertical" className="mr-1 h-4" />
        <ScopeBar />
        <div className="ml-auto flex items-center gap-1.5">
          <Link
            to="/today"
            className="hidden items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium text-foreground/80 hover:bg-muted sm:inline-flex"
            title={drafts > 0 ? `${drafts} items to confirm today` : 'Today'}
          >
            <CalendarDays className="size-3.5 text-orange-600 dark:text-orange-400" />
            {today}
            {drafts > 0 && (
              <span className="rounded-full bg-orange-500 px-1.5 text-[11px] font-semibold text-white tabular-nums">{drafts}</span>
            )}
          </Link>
          <Link
            to="/operations/issues"
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
  return (
    <RequireAuth>
      <SidebarProvider>
        <AppSidebar />
        <SidebarInset>
          <TopBar />
          <div className="flex flex-1 flex-col gap-4 p-4">
            <TrialBanner />
            <Outlet />
          </div>
        </SidebarInset>
      </SidebarProvider>
    </RequireAuth>
  )
}
