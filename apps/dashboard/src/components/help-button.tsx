import * as React from 'react'
import { Link, useLocation } from 'react-router-dom'
import { ArrowRight, CircleHelp, Lightbulb, MessageSquareText, Search } from 'lucide-react'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { useAuth } from '@/lib/AuthContext'
import { useModuleEnabled } from '@/lib/modules'
import { SECTION_TITLES, findPage } from '@/lib/module-map'
import { openJump } from '@/lib/jump'

// UX-08 (asked 9 Nov: "a help icon in the top bar which for each page makes it easier to understand what that
// page is"): the page explains itself here instead of in paragraphs on the page. Everything comes from
// lib/module-map.ts (`about`, `example`, `whatsapp`, `related`, the module's other pages), so a page written into
// the map has its help, and pages stay free of descriptions.

/** Help for the few pages outside the module map. */
const EXTRA: Record<string, { title: string; about: string; example?: string; whatsapp?: string }> = {
  '/live': {
    title: 'Live',
    about: 'Every message to Mesiri as it lands, with what Mesiri understood and did, across all your sites.',
    example: 'A voice note in Malayalam from Compound wall turns into "6 masons, 4 helpers, plastering 120 sq ft".',
  },
  '/reports': { title: 'Daily reports', about: 'Every daily report (DPR), newest first: each site\'s day and each project\'s report that goes to the owner.' },
}

export function HelpButton() {
  const [open, setOpen] = React.useState(false)
  const { pathname, search } = useLocation()
  const { me } = useAuth()
  const role = (me?.role || '').toUpperCase()
  const isModuleEnabled = useModuleEnabled()
  const hit = findPage(pathname, search)
  const extra = EXTRA[pathname]

  // Close when the page changes.
  React.useEffect(() => setOpen(false), [pathname])

  const page = hit?.page
  const group = hit?.group
  const title = page?.title ?? extra?.title ?? 'Mesiri'
  const about = page?.about ?? extra?.about ?? 'Your sites, reported on WhatsApp: open any part of Mesiri from the sidebar or search.'
  const example = page?.example ?? extra?.example
  const whatsapp = page?.whatsapp ?? extra?.whatsapp
  const where = group ? (group.key === 'site' ? SECTION_TITLES.daily : `${SECTION_TITLES[group.section]} › ${group.title}`) : null
  const siblings =
    group?.pages.filter(
      (p) => p.status === 'built' && !p.shortcut && p.url !== page?.url && (!p.roles || p.roles.includes(role)) && (!p.module || isModuleEnabled(p.module)),
    ) ?? []
  const related = page?.related ?? []

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex size-8 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground"
        title={`What is ${title}?`}
        aria-label={`Help: what is ${title}?`}
      >
        <CircleHelp className="size-[18px]" />
      </button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="right" className="flex w-full flex-col gap-0 overflow-y-auto p-0 sm:max-w-md">
          <SheetHeader className="border-b bg-primary/10 px-5 py-4">
            {where && <p className="text-xs font-medium text-muted-foreground">{where}</p>}
            <SheetTitle className="text-xl">{title}</SheetTitle>
            <SheetDescription className="text-sm text-foreground/80">{about}</SheetDescription>
          </SheetHeader>
          <div className="flex flex-col gap-5 px-5 py-4">
            {example && (
              <section className="flex gap-3">
                <Lightbulb className="mt-0.5 size-4 shrink-0 text-primary-ink" aria-hidden />
                <div>
                  <h3 className="text-xs font-semibold text-muted-foreground">For example</h3>
                  <p className="text-sm">{example}</p>
                </div>
              </section>
            )}
            {whatsapp && (
              <section className="flex gap-3 rounded-lg bg-success-soft px-3 py-2.5 text-success">
                <MessageSquareText className="mt-0.5 size-4 shrink-0" aria-hidden />
                <div>
                  <h3 className="text-xs font-semibold">On WhatsApp</h3>
                  <p className="text-sm">“{whatsapp}”</p>
                </div>
              </section>
            )}
            {siblings.length > 0 && (
              <section className="flex flex-col gap-1.5">
                <h3 className="text-xs font-semibold text-muted-foreground">Also in {group?.title}</h3>
                <ul className="flex flex-col divide-y rounded-lg border">
                  {siblings.map((p) => (
                    <li key={p.url}>
                      <Link to={p.url} className="flex items-start gap-2 px-3 py-2 text-sm hover:bg-muted/60">
                        <span className="min-w-0 flex-1">
                          <span className="block font-medium">{p.title}</span>
                          <span className="block text-xs text-muted-foreground">{p.about}</span>
                        </span>
                        <ArrowRight className="mt-1 size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                      </Link>
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {related.length > 0 && (
              <section className="flex flex-col gap-1.5">
                <h3 className="text-xs font-semibold text-muted-foreground">Connected pages</h3>
                <div className="flex flex-wrap gap-1.5">
                  {related.map((r) => (
                    <Link key={r.url} to={r.url} className="inline-flex items-center gap-1 rounded-lg border px-2.5 py-1 text-sm hover:bg-muted/60">
                      {r.title} <ArrowRight className="size-3.5 text-muted-foreground" aria-hidden />
                    </Link>
                  ))}
                </div>
              </section>
            )}
            <button
              type="button"
              onClick={() => {
                setOpen(false)
                openJump()
              }}
              className="flex items-center gap-2 self-start rounded-lg border px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted/60 hover:text-foreground"
            >
              <Search className="size-4" aria-hidden /> Find any page or project
              <kbd className="ml-1 rounded border px-1 text-[10px]">Ctrl K</kbd>
            </button>
          </div>
        </SheetContent>
      </Sheet>
    </>
  )
}
