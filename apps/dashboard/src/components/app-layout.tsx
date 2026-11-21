import * as React from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { ChevronRight, Map as MapIcon, Pin, Search } from 'lucide-react'
import { AppSidebar } from '@/components/app-sidebar'
import { ScopeBar } from '@/components/scope-bar'
import { ArrivalBack, ScopeNote } from '@/components/scope-note'
import { StartProjectDialog } from '@/components/start-project-dialog'
import { SidebarInset, SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar'
import { Separator } from '@/components/ui/separator'
import { RequireAuth } from '@/lib/AuthContext'
import { TrialBanner } from '@/components/trial-banner'
import { SandboxBanner } from '@/components/sandbox-banner'
import { JumpBox } from '@/components/jump-box'
import { usePageTracking } from '@/lib/page-usage'
import { HelpButton } from '@/components/help-button'
import { WhatsAppPageButton, WhatsAppPreviewModal } from '@/components/whatsapp-page-button'
import { TellMesiriDock } from '@/components/tell-mesiri/tell-mesiri-dock'
import { NewButton } from '@/components/new-button'
import { AllPagesPanel } from '@/components/all-pages'
import { openJump } from '@/lib/jump'
import { InboxBell } from '@/components/inbox-bell'
import { PageGuide } from '@/components/page-guide'
import { GuidedTour } from '@/components/tour'
import { WalkthroughRunner } from '@/components/walkthrough'
import { StartQuestionDialog } from '@/components/onboarding/start-question'
import { findPage } from '@/lib/module-map'
import { SidebarCustomise } from '@/components/sidebar-customise'
import { openSidebarCustomise, usePinnable, useSidebarPrefs } from '@/lib/sidebar-prefs'
import { useTrial } from '@/lib/trial'
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
      <PinThisPage url={hit.page.url} title={hit.page.navTitle ?? hit.page.title} />
      {hit.page.status === 'planned' && (
        <span className="ml-1 shrink-0 rounded-full bg-draft-soft px-2 py-px text-[11px] font-semibold text-draft">Planned</span>
      )}
    </nav>
  )
}

/** UX-65: pin the page you are on to "Your pages" (or unpin it), beside its name. */
function PinThisPage({ url, title }: { url: string; title: string }) {
  const sb = useSidebarPrefs()
  const { byUrl } = usePinnable()
  const trial = useTrial()
  if (!sb.ready || trial.readOnly || !byUrl.has(url)) return null
  const pinned = sb.prefs.pins.includes(url)
  if (!pinned && sb.full)
    return (
      <button type="button" onClick={() => openSidebarCustomise('pages')} className="ml-0.5 flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground/70 hover:bg-muted hover:text-foreground" title="Your pages are full: open Customise" aria-label="Your pages are full: customise">
        <Pin className="size-3.5" />
      </button>
    )
  return (
    <button
      type="button"
      onClick={() => sb.togglePin(url)}
      aria-pressed={pinned}
      className={cn(
        'ml-0.5 flex size-7 shrink-0 items-center justify-center rounded-md transition-colors',
        pinned ? 'text-yellow-600 hover:bg-muted dark:text-yellow-400' : 'text-muted-foreground/70 hover:bg-muted hover:text-foreground',
      )}
      title={pinned ? `Unpin ${title} from your sidebar` : `Pin ${title} to your sidebar`}
      aria-label={pinned ? `Unpin ${title} from your sidebar` : `Pin ${title} to your sidebar`}
    >
      <Pin className={cn('size-3.5', pinned && 'rotate-45 fill-current')} />
    </button>
  )
}

function TopBar() {
  const [showPlanned, setShowPlanned] = usePlannedPreview()
  // UX-74 (asked 20 Nov 2026: "On WhatsApp, then a help, then an issues icon ... very messy"): only what is global
  // stays here (SAP Fiori, Salt: a page's own actions belong on the page): where you are on the left; Search, the
  // page's WhatsApp way in (an icon, only where the page has one), New (Tell Mesiri), Help and one bell on the right.
  // The date chip went (the page says its day; the sample company's banner its own); open issues are the sidebar's
  // red badge on Issues and in the bell.
  return (
    <header className="sticky top-0 z-20 shrink-0 border-b bg-background/90 backdrop-blur supports-[backdrop-filter]:bg-background/75">
      <div aria-hidden className="h-[3px] bg-[repeating-linear-gradient(135deg,#1a1d21_0_8px,#facc15_8px_16px)]" />
      <div className="flex h-12 items-center gap-2 px-3 sm:px-4">
        <SidebarTrigger />
        <Separator orientation="vertical" className="mr-1 h-4" />
        <ScopeBar />
        <ArrivalBack />
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
          <button
            type="button"
            onClick={openJump}
            data-guide="app.search"
            className="inline-flex h-8 items-center gap-2 rounded-full border bg-muted/40 px-3 text-sm text-muted-foreground hover:bg-muted md:w-56"
            title="Search pages, projects and records (Ctrl K)"
            aria-label="Search"
          >
            <Search className="size-4 shrink-0" aria-hidden />
            <span className="hidden md:inline">Search</span>
            <kbd className="ml-auto hidden rounded border px-1 text-[10px] md:inline">Ctrl K</kbd>
          </button>
          <WhatsAppPageButton />
          <NewButton />
          <HelpButton />
          {/* NXT-08: everything waiting for me, each opening its record. */}
          <InboxBell />
        </div>
      </div>
    </header>
  )
}

/** UX-70: counts the pages this person opens (Search's "Most used", the sidebar's pin suggestion). */
function PageTracker() {
  usePageTracking()
  return null
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
      <PageTracker />
      <StartProjectDialog />
      {/* SS-28: "How would you like to start?" for anyone not asked yet. */}
      <StartQuestionDialog />
      {/* The current page's WhatsApp preview, opened from the top bar, the ? panel or the page strip. */}
      <WhatsAppPreviewModal />
      {/* Tell Mesiri on every page (16 Nov). */}
      <TellMesiriDock />
      {/* The Spark's guided tours (lib/tours.ts). */}
      <GuidedTour />
      {/* SS-42: walkthroughs started from Learn Mesiri (lib/walkthroughs.ts). */}
      <WalkthroughRunner />
      <SidebarProvider>
        <AppSidebar />
        <SidebarCustomise />
        <AllPagesPanel />
        <SidebarInset>
          <TopBar />
          <div id="main-content" tabIndex={-1} className="flex flex-1 flex-col gap-4 p-4 outline-none">
            <SandboxBanner />
            <TrialBanner />
            <ScopeNote />
            {/* SS-29: the page explains itself once, for the start modes that want it. */}
            <PageGuide />
            <Outlet />
          </div>
        </SidebarInset>
      </SidebarProvider>
    </RequireAuth>
  )
}
