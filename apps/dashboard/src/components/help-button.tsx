import * as React from 'react'
import { Link, useLocation } from 'react-router-dom'
import { ArrowLeftRight, BookOpen, ChevronDown, CircleHelp, Crosshair, FileSpreadsheet, Footprints, GraduationCap, Info, Lightbulb, ListOrdered, MessageSquareText, Search, Sparkles, UserRound } from 'lucide-react'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { useAuth } from '@/lib/AuthContext'
import { useScope } from '@/lib/ScopeContext'
import { urlWithScope } from '@/lib/scope-url'
import { useModuleEnabled } from '@/lib/modules'
import { SECTION_TITLES, findPage } from '@/lib/module-map'
import { openJump } from '@/lib/jump'
import { helpFor, type HelpPart, type HelpTone } from '@/lib/page-help'
import { cn } from '@/lib/utils'
import { wordsFor, wordsKey, useResetGuides, useStartMode, type GuideWords } from '@/lib/start-mode'
import { StartChoices } from '@/components/onboarding/start-question'
import { WithTerms } from '@/components/term'
import { Spark } from '@/components/live/spark'
import { stepsFor, tourForPage } from '@/lib/tours'
import { HELP_EVENT, showMeAround, spotOnPage } from '@/lib/tour-events'
import { findTarget } from '@/components/tour'
import { splitTerms, type GlossaryTerm } from '@/lib/glossary'
import { SeeOnWhatsApp } from '@/components/whatsapp-page-button'

// UX-08 (asked 9 Nov: "a help icon in the top bar which for each page makes it easier to understand what that
// page is"): the page explains itself here instead of in paragraphs on the page. Everything comes from
// lib/module-map.ts (`about`, `example`, `whatsapp`, `related`, the module's other pages), so a page written into
// the map has its help, and pages stay free of descriptions.
//
// UX-22 (asked 17 Nov: "personalise help and Show me around for each type of person … the help section just has a
// lot of descriptions which is bad UX"): the panel speaks to this person (start mode → GuideWords): a line for them
// first, then the tour in their words as the one big button, then the page's parts in the order they sit, each lit
// up on the page when tapped. Words for a total beginner come with the site words they will meet. The rest (other
// pages, Learn, search) is folded under "More".

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

/** UX-22: the card at the top, per kind of person: its heading and icon. */
const FOR_YOU: Record<GuideWords, { title: string; icon: React.ComponentType<{ className?: string }> }> = {
  basics: { title: 'In plain words', icon: BookOpen },
  steps: { title: 'Where to start', icon: Footprints },
  data: { title: 'Bring yours in', icon: FileSpreadsheet },
  expert: { title: "What's different here", icon: ArrowLeftRight },
}

/** The glossary words in these texts, each once, in the order met. */
function termsIn(texts: string[]): GlossaryTerm[] {
  const seen = new Set<GlossaryTerm>()
  for (const text of texts) for (const part of splitTerms(text)) if (typeof part !== 'string') seen.add(part.term)
  return [...seen]
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

  // Close when the page changes; open again from a lit thing's "Back to help".
  React.useEffect(() => setOpen(false), [pathname])
  React.useEffect(() => {
    const reopen = () => setOpen(true)
    window.addEventListener(HELP_EVENT, reopen)
    return () => window.removeEventListener(HELP_EVENT, reopen)
  }, [])

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
  const related = (page?.related ?? []).filter((r) => !siblings.some((p) => p.url === r.url))
  // SS-28/SS-37/UX-22: how Mesiri guides this person, shown and changeable at the top (every role has this button).
  const guide = useStartMode()
  const words = guide.rules.words
  const resetGuides = useResetGuides()
  const [changing, setChanging] = React.useState(false)
  React.useEffect(() => setChanging(false), [open])
  const whatsNew = page?.guideNew
  const help = helpFor(page?.url, pathname)

  // This person's words (UX-22): falls back to the plain words when the page has none written for them.
  const forYouKind = wordsKey(words, help?.forYou)
  const forYou = forYouKind ? help?.forYou?.[forYouKind] : undefined
  const ForYouIcon = forYouKind ? FOR_YOU[forYouKind].icon : null
  const parts = (help?.parts ?? [])
    .map((p): HelpPart | null => {
      const own = wordsFor<string | null | undefined>(words, p.for, undefined)
      if (own === null) return null
      return own ? { ...p, means: own } : p
    })
    .filter((p): p is HelpPart => !!p)
  const steps = wordsFor(words, help?.stepsFor, help?.steps ?? [])
  const pageTour = tourForPage(pathname, search)
  const tourSteps = pageTour ? stepsFor(pageTour.tour, words, pageTour).filter((s) => !s.target || !open || findTarget(s.target)).length : 0
  // A total beginner gets the site words of this page together, so nothing in it is a word they don't know.
  const terms = words === 'basics' && open ? termsIn([about, forYou ?? '', ...parts.map((p) => `${p.name} ${p.means}`), ...steps]) : []
  const more = siblings.length + related.length

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
          <SheetHeader className="gap-1 border-b bg-primary/10 px-5 py-4">
            {where && <p className="text-xs font-medium text-muted-foreground">{where}</p>}
            <SheetTitle className="text-xl">{title}</SheetTitle>
            <SheetDescription className="text-sm text-foreground/80"><WithTerms text={about} /></SheetDescription>
            {guide.ready && (
              <button
                type="button"
                onClick={() => setChanging((c) => !c)}
                aria-expanded={changing}
                className="mt-1 inline-flex items-center gap-1.5 self-start rounded-full border border-foreground/15 bg-background/70 px-2.5 py-1 text-xs hover:bg-background"
              >
                <UserRound className="size-3.5 text-muted-foreground" aria-hidden />
                <span className="text-muted-foreground">Explained for</span>
                <span className="font-medium">{guide.rules.forWho}</span>
                <ChevronDown className={cn('size-3.5 text-muted-foreground transition-transform', changing && 'rotate-180')} aria-hidden />
              </button>
            )}
          </SheetHeader>
          <div className="flex flex-col gap-5 px-5 py-4">
            {changing && (
              <section className="flex flex-col gap-2">
                <h3 className="text-xs font-semibold text-muted-foreground">Who should Mesiri explain things for?</h3>
                <StartChoices current={guide.mode} onChosen={() => setChanging(false)} />
              </section>
            )}
            {forYou && forYouKind && ForYouIcon && (
              <section className="flex gap-3 rounded-xl border bg-card px-3.5 py-3">
                <ForYouIcon className="mt-0.5 size-4 shrink-0 text-primary-ink" />
                <div className="min-w-0">
                  <h3 className="text-xs font-semibold text-muted-foreground">{FOR_YOU[forYouKind].title}</h3>
                  <p className="m-0 text-sm"><WithTerms text={forYou} /></p>
                </div>
              </section>
            )}
            {pageTour && (
              <button
                type="button"
                onClick={() => {
                  setOpen(false)
                  showMeAround()
                }}
                className="flex items-center gap-3 rounded-xl border border-[#facc15] bg-[#facc15]/15 px-3 py-2.5 text-left hover:bg-[#facc15]/25"
              >
                <Spark mood="hello" size={36} quiet />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-semibold">Show me around this page</span>
                  <span className="block text-xs text-muted-foreground">
                    {tourSteps} {tourSteps === 1 ? 'thing' : 'things'}, one at a time{words ? ', in your words' : ''}
                  </span>
                </span>
              </button>
            )}
            {parts.length > 0 && (
              <section className="flex flex-col gap-1.5">
                <h3 className="flex items-baseline justify-between gap-2 text-xs font-semibold text-muted-foreground">
                  <span>On this page</span>
                  {parts.some((p) => p.find) && <span className="font-normal">Tap one to see it</span>}
                </h3>
                <ul className="flex flex-col divide-y rounded-xl border">
                  {parts.map((p) => {
                    const findable = !!p.find && open && !!findTarget(p.find)
                    const inner = (
                      <>
                        <span aria-hidden className={cn('mt-1.5 size-2 shrink-0 rounded-full', DOT[p.tone ?? 'none'])} />
                        <span className="min-w-0 flex-1">
                          <span className="block text-sm font-medium">{p.name}</span>
                          <span className="block text-sm text-muted-foreground"><WithTerms text={p.means} /></span>
                        </span>
                        {findable && <Crosshair className="mt-1 size-4 shrink-0 text-muted-foreground" aria-hidden />}
                      </>
                    )
                    return (
                      <li key={p.name}>
                        {findable ? (
                          <button
                            type="button"
                            onClick={() => {
                              setOpen(false)
                              spotOnPage({ target: p.find!, title: p.name, text: p.means })
                            }}
                            className="flex w-full items-start gap-2.5 px-3 py-2 text-left hover:bg-muted/60"
                            aria-label={`Show ${p.name} on the page`}
                          >
                            {inner}
                          </button>
                        ) : (
                          <div className="flex items-start gap-2.5 px-3 py-2">{inner}</div>
                        )}
                      </li>
                    )
                  })}
                </ul>
              </section>
            )}
            {steps.length > 0 && (
              <section className="flex flex-col gap-1.5">
                <h3 className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
                  <ListOrdered className="size-3.5" aria-hidden /> How to use it
                </h3>
                <ol className="flex flex-col gap-1.5">
                  {steps.map((step, i) => (
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
            {terms.length > 0 && (
              <section className="flex flex-col gap-1.5">
                <h3 className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
                  <BookOpen className="size-3.5" aria-hidden /> Site words on this page
                </h3>
                <dl className="flex flex-col divide-y rounded-xl border bg-muted/40">
                  {terms.map((t) => (
                    <div key={t.match[0]} className="px-3 py-2 text-sm">
                      <dt className="font-medium">{t.match[0]}</dt>
                      <dd className="m-0 text-muted-foreground">{t.meaning}</dd>
                    </div>
                  ))}
                </dl>
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
            {/* Everything that leads somewhere else, folded: the page's own help stays short. */}
            <details className="group border-t pt-3">
              <summary className="flex cursor-pointer list-none items-center gap-1.5 text-sm font-medium text-muted-foreground hover:text-foreground">
                <ChevronDown className="size-4 transition-transform group-open:rotate-180" aria-hidden />
                More{more > 0 ? `: ${more} connected ${more === 1 ? 'page' : 'pages'}, Learn, search` : ': Learn, search'}
              </summary>
              <div className="mt-3 flex flex-col gap-3">
                {more > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {[...siblings.map((p) => ({ title: p.title, url: p.url, about: p.about })), ...related.map((r) => ({ title: r.title, url: r.url, about: undefined }))].map((r) => (
                      <Link
                        key={r.url}
                        to={urlWithScope(r.url, scope)}
                        title={r.about}
                        className="inline-flex items-center rounded-lg border px-2.5 py-1 text-sm hover:bg-muted/60"
                      >
                        {r.title}
                      </Link>
                    ))}
                  </div>
                )}
                <div className="flex flex-wrap gap-1.5">
                  <Link to="/learn" onClick={() => setOpen(false)} className="inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-sm hover:bg-muted/60">
                    <GraduationCap className="size-4 text-muted-foreground" aria-hidden /> Learn Mesiri
                  </Link>
                  <button
                    type="button"
                    onClick={() => {
                      setOpen(false)
                      openJump()
                    }}
                    className="inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-sm hover:bg-muted/60"
                  >
                    <Search className="size-4 text-muted-foreground" aria-hidden /> Find a page
                    <kbd className="rounded border px-1 text-[10px] text-muted-foreground">Ctrl K</kbd>
                  </button>
                </div>
                {guide.ready && (guide.rules.strips !== 'none' || guide.rules.tours !== 'none') && (
                  <button
                    type="button"
                    disabled={resetGuides.isPending || Object.keys(guide.seen).length === 0}
                    onClick={() => resetGuides.mutate()}
                    className="self-start text-sm text-muted-foreground underline underline-offset-2 disabled:no-underline disabled:opacity-60"
                  >
                    {resetGuides.isSuccess ? 'Every page will show you around again' : 'Show me around every page again'}
                  </button>
                )}
              </div>
            </details>
          </div>
        </SheetContent>
      </Sheet>
    </>
  )
}
