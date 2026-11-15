import { useLocation } from 'react-router-dom'
import { Lightbulb, Sparkles, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { WithTerms } from '@/components/term'
import { SeeOnWhatsApp } from '@/components/whatsapp-page-button'
import { findPage } from '@/lib/module-map'
import { useGuideSeen, useStartMode } from '@/lib/start-mode'
import { guideKey, stripFor } from '@/lib/page-guide'

// SS-29 + SS-37 (guided-onboarding-plan.md 6.4, 6.7): a page explains itself once, at the top, for the people whose
// start mode asks for it. One component in the layout serves every page, and its words come only from
// lib/module-map.ts (`about`, `example`, `whatsapp`), the same text as the ? help button: a page added to the map
// has its strip with no onboarding work, and nothing here goes stale when a page's layout changes (no arrows at
// buttons). When a page changes, raising its `guideVersion` brings the strip back once as "Updated".

export function PageGuide() {
  const { pathname, search } = useLocation()
  const guide = useStartMode()
  const markSeen = useGuideSeen()
  const hit = findPage(pathname, search)
  if (!guide.ready || !hit) return null
  const { page } = hit
  const kind = stripFor(page, guide.rules, guide.seen)
  if (!kind) return null
  const close = () => markSeen.mutate({ page: guideKey(page), version: page.guideVersion ?? 1 })

  return (
    <aside
      aria-label={`About ${page.title}`}
      className="relative flex flex-col gap-2 rounded-lg border border-primary/30 bg-primary/10 px-4 py-3 pr-10 text-sm"
    >
      <button
        type="button"
        onClick={close}
        className="absolute top-2 right-2 inline-flex size-7 items-center justify-center rounded-full text-muted-foreground hover:bg-background/60 hover:text-foreground"
        aria-label="Close"
      >
        <X className="size-4" />
      </button>
      {kind === 'updated' ? (
        <p className="m-0 flex items-start gap-2">
          <Sparkles className="mt-0.5 size-4 shrink-0 text-primary-ink" aria-hidden />
          <span>
            <span className="font-semibold">Updated: </span>
            {page.guideNew}
          </span>
        </p>
      ) : (
        <>
          <p className="m-0">
            <span className="font-semibold">{page.title}: </span>
            <WithTerms text={page.about} />
          </p>
          <p className="m-0 flex items-start gap-2 text-muted-foreground">
            <Lightbulb className="mt-0.5 size-4 shrink-0 text-primary-ink" aria-hidden />
            <span>For example: <WithTerms text={page.example} /></span>
          </p>
          {page.whatsapp && page.whatsapp.length > 0 && <SeeOnWhatsApp />}
          <Button type="button" size="sm" variant="outline" className="self-start" onClick={close}>
            Got it
          </Button>
        </>
      )}
    </aside>
  )
}
