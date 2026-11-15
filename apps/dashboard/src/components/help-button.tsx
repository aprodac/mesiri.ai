import * as React from 'react'
import { Link, useLocation } from 'react-router-dom'
import { ArrowRight, CircleHelp, Compass, GraduationCap, Info, LayoutList, Lightbulb, ListOrdered, MessageSquareText, Search, Sparkles } from 'lucide-react'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { useAuth } from '@/lib/AuthContext'
import { useScope } from '@/lib/ScopeContext'
import { urlWithScope } from '@/lib/scope-url'
import { useModuleEnabled } from '@/lib/modules'
import { SECTION_TITLES, findPage } from '@/lib/module-map'
import { openJump } from '@/lib/jump'
import { helpFor, type HelpTone } from '@/lib/page-help'
import { cn } from '@/lib/utils'
import { MODES, useResetGuides, useStartMode } from '@/lib/start-mode'
import { StartChoices } from '@/components/onboarding/start-question'
import { WithTerms } from '@/components/term'
import { Spark } from '@/components/live/spark'
import { tourForPage } from '@/lib/tours'
import { showMeAround } from '@/lib/tour-events'
import { SeeOnWhatsApp } from '@/components/whatsapp-page-button'

// UX-08 (asked 9 Nov: "a help icon in the top bar which for each page makes it easier to understand what that
// page is"): the page explains itself here instead of in paragraphs on the page. Everything comes from
// lib/module-map.ts (`about`, `example`, `whatsapp`, `related`, the module's other pages), so a page written into
// the map has its help, and pages stay free of descriptions.

/** Help for the few pages outside the module map. */
const EXTRA: Record<string, { title: string; about: string; example?: string }> = {
  '/live': {
    title: 'Live',
    about: 'Every message to Mesiri as it lands, with what Mesiri understood and did, across all your sites.',
    example: 'A voice note in Malayalam from Compound wall turns into "6 masons, 4 helpers, plastering 120 sq ft".',
  },
  '/reports': { title: 'Daily reports', about: 'Every daily report (DPR), newest first: each site\'s day and each project\'s report that goes to the owner.' },
}

// UX-13: the same colours the page uses for a state, so "red" in the help is the red on the page.
const DOT: Record<HelpTone | 'none', string> = {
  good: 'bg-success',
  attention: 'bg-draft',
  bad: 'bg-destructive',
  info: 'bg-info',
  none: 'bg-muted-foreground/40',
}

export function HelpButton() {
  const [open, setOpen] = React.useState(false)
  const { pathname, search } = useLocation()
  const { me } = useAuth()
  const { scope } = useScope()
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
  const whatsapp = page?.whatsapp ?? []
  const whatsappNone = page?.whatsappNone
  const where = group ? (group.key === 'site' ? SECTION_TITLES.daily : (SECTION_TITLES[group.section] === group.title ? group.title : `${SECTION_TITLES[group.section]} › ${group.title}`)) : null
  const siblings =
    group?.pages.filter(
      (p) => p.status === 'built' && !p.shortcut && p.url !== page?.url && (!p.roles || p.roles.includes(role)) && (!p.module || isModuleEnabled(p.module)),
    ) ?? []
  const related = page?.related ?? []
  // SS-28/SS-37: how Mesiri guides this person, changeable here (every role has this button), and what changed.
  const guide = useStartMode()
  const resetGuides = useResetGuides()
  const [changing, setChanging] = React.useState(false)
  React.useEffect(() => setChanging(false), [open])
  const whatsNew = page?.guideNew
  const help = helpFor(page?.url, pathname)

  return (
    <>
      <button
        type="button"
        data-guide="app.help"
        onClick={() => setOpen(true)}
        className="inline-flex h-8 min-w-8 items-center justify-center gap-1.5 rounded-full border border-primary/40 bg-primary/10 px-2 text-sm font-medium text-foreground hover:bg-primary/20 sm:px-3"
        title={`What is ${title}?`}
        aria-label={`Help: what is ${title}?`}
      >
        <CircleHelp className="size-[18px] text-primary-ink" />
        <span className="hidden sm:inline">Help</span>
      </button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="right" className="flex w-full flex-col gap-0 overflow-y-auto p-0 sm:max-w-md">
          <SheetHeader className="border-b bg-primary/10 px-5 py-4">
            {where && <p className="text-xs font-medium text-muted-foreground">{where}</p>}
            <SheetTitle className="text-xl">{title}</SheetTitle>
            <SheetDescription className="text-sm text-foreground/80"><WithTerms text={about} /></SheetDescription>
          </SheetHeader>
          <div className="flex flex-col gap-5 px-5 py-4">
            {help?.parts && help.parts.length > 0 && (
              <section className="flex flex-col gap-1.5">
                <h3 className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
                  <LayoutList className="size-3.5" aria-hidden /> On this page
                </h3>
                <dl className="flex flex-col divide-y rounded-lg border">
                  {help.parts.map((p) => (
                    <div key={p.name} className="flex items-start gap-2.5 px-3 py-2">
                      <span aria-hidden className={cn('mt-1.5 size-2 shrink-0 rounded-full', DOT[p.tone ?? 'none'])} />
                      <dt className="w-32 shrink-0 text-sm font-medium">{p.name}</dt>
                      <dd className="min-w-0 flex-1 text-sm text-muted-foreground">
                        <WithTerms text={p.means} />
                      </dd>
                    </div>
                  ))}
                </dl>
              </section>
            )}
            {help?.steps && help.steps.length > 0 && (
              <section className="flex flex-col gap-1.5">
                <h3 className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
                  <ListOrdered className="size-3.5" aria-hidden /> How to use it
                </h3>
                <ol className="flex flex-col gap-1.5">
                  {help.steps.map((step, i) => (
                    <li key={step} className="flex items-start gap-2.5 text-sm">
                      <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary/20 text-[11px] font-semibold text-primary-ink">{i + 1}</span>
                      <span className="pt-px">
                        <WithTerms text={step} />
                      </span>
                    </li>
                  ))}
                </ol>
              </section>
            )}
            {help?.tip && (
              <section className="flex gap-3 rounded-lg bg-info-soft px-3 py-2.5 text-info">
                <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
                <p className="text-sm">{help.tip}</p>
              </section>
            )}
            {example && (
              <section className="flex gap-3">
                <Lightbulb className="mt-0.5 size-4 shrink-0 text-primary-ink" aria-hidden />
                <div>
                  <h3 className="text-xs font-semibold text-muted-foreground">For example</h3>
                  <p className="text-sm"><WithTerms text={example} /></p>
                </div>
              </section>
            )}
            {whatsapp.length > 0 && <SeeOnWhatsApp onOpen={() => setOpen(false)} />}
            {whatsapp.length === 0 && whatsappNone && (
              <section className="flex gap-3 rounded-lg bg-muted/60 px-3 py-2.5">
                <MessageSquareText className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
                <div>
                  <h3 className="text-xs font-semibold text-muted-foreground">From WhatsApp</h3>
                  <p className="text-sm">{whatsappNone}</p>
                </div>
              </section>
            )}
            {whatsNew && (
              <section className="flex gap-3">
                <Sparkles className="mt-0.5 size-4 shrink-0 text-primary-ink" aria-hidden />
                <div>
                  <h3 className="text-xs font-semibold text-muted-foreground">What's new</h3>
                  <p className="text-sm">{whatsNew}</p>
                </div>
              </section>
            )}
            {siblings.length > 0 && (
              <section className="flex flex-col gap-1.5">
                <h3 className="text-xs font-semibold text-muted-foreground">Also in {group?.title}</h3>
                <ul className="flex flex-col divide-y rounded-lg border">
                  {siblings.map((p) => (
                    <li key={p.url}>
                      <Link to={urlWithScope(p.url, scope)} className="flex items-start gap-2 px-3 py-2 text-sm hover:bg-muted/60">
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
                    <Link key={r.url} to={urlWithScope(r.url, scope)} className="inline-flex items-center gap-1 rounded-lg border px-2.5 py-1 text-sm hover:bg-muted/60">
                      {r.title} <ArrowRight className="size-3.5 text-muted-foreground" aria-hidden />
                    </Link>
                  ))}
                </div>
              </section>
            )}
            {tourForPage(pathname, search) && (
              <button
                type="button"
                onClick={() => {
                  setOpen(false)
                  showMeAround()
                }}
                className="flex items-center gap-2 self-start rounded-lg border border-[#facc15] bg-[#facc15]/15 px-3 py-1.5 text-sm font-medium hover:bg-[#facc15]/25"
              >
                <Spark mood="hello" size={26} quiet /> Show me around this page
              </button>
            )}
            <Link
              to="/learn"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2 self-start rounded-lg border px-3 py-1.5 text-sm hover:bg-muted/60"
            >
              <GraduationCap className="size-4 text-muted-foreground" aria-hidden /> Learn Mesiri: walkthroughs to try
            </Link>
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
            {guide.ready && (
              <section className="flex flex-col gap-2 border-t pt-4">
                <h3 className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
                  <Compass className="size-3.5" aria-hidden /> How Mesiri guides you
                </h3>
                {changing ? (
                  <StartChoices current={guide.mode} onChosen={() => setChanging(false)} />
                ) : (
                  <p className="m-0 text-sm">
                    {MODES[guide.mode].label}.{' '}
                    <button type="button" className="underline underline-offset-2" onClick={() => setChanging(true)}>
                      Change
                    </button>
                  </p>
                )}
                {(guide.rules.strips !== 'none' || guide.rules.tours !== 'none') && (
                  <button
                    type="button"
                    disabled={resetGuides.isPending || Object.keys(guide.seen).length === 0}
                    onClick={() => resetGuides.mutate()}
                    className="self-start text-sm text-muted-foreground underline underline-offset-2 disabled:no-underline disabled:opacity-60"
                  >
                    {resetGuides.isSuccess ? 'Every page will show you around again' : 'Show me around again'}
                  </button>
                )}
              </section>
            )}
          </div>
        </SheetContent>
      </Sheet>
    </>
  )
}
