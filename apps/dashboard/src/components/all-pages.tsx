import * as React from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Pin, Search, SlidersHorizontal } from 'lucide-react'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { SECTION_TITLES, type NavSection } from '@/lib/module-map'
import { MAX_PINS, openSidebarCustomise, usePinnable, useSidebarPrefs, type PinnablePage } from '@/lib/sidebar-prefs'
import { useScope } from '@/lib/ScopeContext'
import { urlWithScope } from '@/lib/scope-url'
import { useTrial } from '@/lib/trial'
import { cn } from '@/lib/utils'
import { ALL_PAGES_EVENT } from '@/lib/all-pages'

// UX-74 (asked 20 Nov 2026: "only what that user needs at that time should be there ... the need to scroll the
// sidebar should not be there"): the sidebar keeps the few pages a person uses now; every other page this role may
// open is here, one click from the sidebar's "All pages": by section in the order a project runs (the person's own
// order from Customise), then by module. The list is the sidebar's own (lib/sidebar-prefs usePinnable), so a page
// is never in one and missing from the other. Pin a page here to keep it in the sidebar.

type Group = { key: string; title: string; icon: React.ElementType; pages: PinnablePage[] }

export function AllPagesPanel() {
  const [open, setOpen] = React.useState(false)
  const [query, setQuery] = React.useState('')
  const { pathname } = useLocation()
  const { pages } = usePinnable()
  const sb = useSidebarPrefs()
  const { scope } = useScope()
  const trial = useTrial()

  React.useEffect(() => {
    const show = () => {
      setQuery('')
      setOpen(true)
    }
    window.addEventListener(ALL_PAGES_EVENT, show)
    return () => window.removeEventListener(ALL_PAGES_EVENT, show)
  }, [])
  React.useEffect(() => setOpen(false), [pathname])

  const q = query.trim().toLowerCase()
  const match = (p: PinnablePage) =>
    !q || p.title.toLowerCase().includes(q) || p.group.title.toLowerCase().includes(q) || (p.page.about ?? '').toLowerCase().includes(q)
  const order: NavSection[] = [...sb.prefs.order.filter((s) => !sb.prefs.hidden.includes(s)), ...sb.prefs.hidden]
  const sections = order
    .map((section) => {
      const groups: Group[] = []
      for (const p of pages.filter((x) => x.section === section && match(x))) {
        let g = groups.find((x) => x.key === p.group.key)
        if (!g) groups.push((g = { key: p.group.key, title: p.group.title, icon: p.group.icon, pages: [] }))
        g.pages.push(p)
      }
      return { section, hidden: sb.prefs.hidden.includes(section), groups }
    })
    .filter((s) => s.groups.length > 0)

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetContent side="left" className="flex w-full flex-col gap-0 p-0 sm:max-w-4xl" data-guide="app.allpages">
        <SheetHeader className="gap-2 border-b px-5 py-4">
          <SheetTitle className="text-xl">All pages</SheetTitle>
          <SheetDescription>Everything you can open, in the order a project runs. Pin a page to keep it in your sidebar.</SheetDescription>
          <label className="mt-1 flex h-10 items-center gap-2 rounded-lg border bg-background px-3 focus-within:ring-2 focus-within:ring-ring">
            <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Find a page: stock, wages, RA bills…"
              className="h-full w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
              aria-label="Find a page"
            />
          </label>
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {sections.length === 0 && <p className="text-sm text-muted-foreground">No page matches “{query}”.</p>}
          {/* One flowing set of cards (columns), each named with its section, so a section with one module leaves no gap. */}
          <div className="columns-1 gap-3 sm:columns-2 lg:columns-3">
            {sections.flatMap((s) =>
              s.groups.map((g) => (
                <div key={`${s.section}-${g.key}`} className="mb-3 break-inside-avoid rounded-xl border bg-card p-3">
                  <div className="mb-0.5 text-[10px] font-semibold tracking-wider text-muted-foreground uppercase">
                    {SECTION_TITLES[s.section]}
                    {s.hidden && ' · hidden'}
                  </div>
                  <div className="mb-1.5 flex items-center gap-2 text-sm font-semibold">
                    <g.icon className="size-4 text-muted-foreground" aria-hidden />
                    {g.title}
                  </div>
                  <ul className="m-0 flex list-none flex-col p-0">
                    {g.pages.map((p) => {
                      const pinned = sb.prefs.pins.includes(p.url)
                      const canPin = sb.ready && !trial.readOnly && (pinned || !sb.full)
                      return (
                        <li key={p.url} className="group/page flex items-center gap-1">
                          <Link
                            to={urlWithScope(p.url, scope)}
                            onClick={() => setOpen(false)}
                            title={p.page.about}
                            className={cn(
                              'min-w-0 flex-1 truncate rounded-md px-2 py-1.5 text-sm hover:bg-muted focus-visible:bg-muted focus-visible:outline-none',
                              p.page.status === 'planned' && 'text-muted-foreground',
                            )}
                          >
                            {p.page.navTitle ?? p.page.title}
                          </Link>
                          {canPin && (
                            <button
                              type="button"
                              onClick={() => sb.togglePin(p.url)}
                              aria-pressed={pinned}
                              aria-label={pinned ? `Unpin ${p.title} from your sidebar` : `Pin ${p.title} to your sidebar`}
                              title={pinned ? 'Unpin from your sidebar' : 'Pin to your sidebar'}
                              className={cn(
                                'flex size-7 shrink-0 items-center justify-center rounded-md transition-opacity hover:bg-muted focus-visible:opacity-100',
                                pinned ? 'text-yellow-600 dark:text-yellow-400' : 'text-muted-foreground opacity-0 group-hover/page:opacity-100 pointer-coarse:opacity-100',
                              )}
                            >
                              <Pin className={cn('size-3.5', pinned && 'rotate-45 fill-current')} />
                            </button>
                          )}
                        </li>
                      )
                    })}
                  </ul>
                </div>
              )),
            )}
          </div>
        </div>
        {!trial.readOnly && (
          <div className="flex items-center justify-between gap-2 border-t px-5 py-3 text-xs text-muted-foreground">
            <span>
              {sb.prefs.pins.length} of {MAX_PINS} pinned
            </span>
            <button
              type="button"
              onClick={() => {
                setOpen(false)
                openSidebarCustomise('pages')
              }}
              className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 font-medium text-foreground hover:bg-muted"
            >
              <SlidersHorizontal className="size-3.5" aria-hidden /> Customise your sidebar
            </button>
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}
