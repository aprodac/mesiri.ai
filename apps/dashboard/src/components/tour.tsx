import * as React from 'react'
import { createPortal } from 'react-dom'
import { useLocation } from 'react-router-dom'
import { Spark } from '@/components/live/spark'
import { WithTerms } from '@/components/term'
import { Button } from '@/components/ui/button'
import { prefersReducedMotion } from '@/lib/timeline'
import { cn } from '@/lib/utils'
import { useGuideSeen, useStartMode } from '@/lib/start-mode'
import { APP_TOUR, PAGE_TOURS, tourForPage, type Tour, type TourStep } from '@/lib/tours'
import { VOICED, spokenWords } from '@/lib/walkthroughs'
import { VoicePlayer, useGuideVoice } from '@/components/guide-voice'
import { TOUR_EVENT, walkthroughRunning } from '@/lib/tour-events'

// The guided tour, game style (asked 15 Nov): the screen dims, one thing lights up, and the Spark (Mesiri's
// character from Live) says what it is; Next, Back, Skip. Content and rules: lib/tours.ts. One component in the
// layout runs every tour. Who gets which tour is the start mode's `tours` rule (lib/start-mode.ts).

interface Running {
  tour: Tour
  steps: TourStep[]
  index: number
  /** Run this tour next, when this one ends (the page's tour after the app tour). */
  then?: { tour: Tour; steps: TourStep[] }
}

const PAD = 6
const GAP = 12
const BUBBLE_W = 340
/** The bubble's usual height, to place it where it fits. */
const BUBBLE_H = 190

/** The first marked element that is on screen (a hidden sidebar on a phone does not count). */
export function findTarget(id: string): HTMLElement | null {
  // `a|b`: the first of them that is on screen. `record:<id>`: a list row of that record (`data-record-id`), so a
  // walkthrough can light up what was just saved.
  if (id.includes('|')) {
    for (const one of id.split('|')) {
      const hit = findTarget(one)
      if (hit) return hit
    }
    return null
  }
  const selector = id.startsWith('record:') ? `[data-record-id="${CSS.escape(id.slice(7))}"]` : `[data-guide="${id}"]`
  for (const el of document.querySelectorAll<HTMLElement>(selector)) {
    const r = el.getBoundingClientRect()
    if (r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden') return el
  }
  return null
}

/** Whether the page shows what its tour is about (its startWhen markers), not a picker or a skeleton. */
function pageReady(tour: Tour): boolean {
  return !tour.startWhen || tour.startWhen.some((id) => findTarget(id))
}

/** The tour's steps that can be shown now: the page's hello first, then each step whose element is on screen. */
function resolve(tour: Tour, intro?: { title: string; about: string }): TourStep[] {
  const steps = tour.steps.filter((s) => !s.target || findTarget(s.target))
  return tour.introFromPage && intro ? [{ title: intro.title, text: intro.about, mood: 'hello' }, ...steps] : steps
}

export function useRect(target: string | undefined, index: number): DOMRect | null {
  const [rect, setRect] = React.useState<DOMRect | null>(null)
  React.useEffect(() => {
    if (!target) {
      setRect(null)
      return
    }
    const el = findTarget(target)
    el?.scrollIntoView({ block: 'center', inline: 'nearest', behavior: prefersReducedMotion() ? 'auto' : 'smooth' })
    let frame = 0
    const measure = () => {
      const now = findTarget(target)
      setRect((old) => {
        const r = now?.getBoundingClientRect() ?? null
        if (!r || !old) return r
        return r.top === old.top && r.left === old.left && r.width === old.width && r.height === old.height ? old : r
      })
      frame = requestAnimationFrame(measure)
    }
    measure()
    return () => cancelAnimationFrame(frame)
  }, [target, index])
  return rect
}

export function GuidedTour() {
  const guide = useStartMode()
  const markSeen = useGuideSeen()
  const { pathname, search } = useLocation()
  const [running, setRunning] = React.useState<Running | null>(null)
  const next = React.useRef<HTMLButtonElement>(null)

  // Tours ended in this visit, so one is never started twice while its "seen" is still on its way to the server.
  const ended = React.useRef(new Set<string>())
  const unseen = React.useCallback(
    (tour: Tour) => !ended.current.has(tour.key) && (guide.seen[tour.key] ?? 0) < tour.version,
    [guide.seen],
  )

  const start = React.useCallback(
    (force: boolean) => {
      if (walkthroughRunning()) return
      const page = tourForPage(pathname, search)
      const pageRun = page && (force || (guide.rules.tours === 'all' && unseen(page.tour) && pageReady(page.tour)))
        ? { tour: page.tour, steps: resolve(page.tour, page) }
        : undefined
      if (!force && guide.rules.tours !== 'none' && unseen(APP_TOUR)) {
        const steps = resolve(APP_TOUR)
        setRunning({ tour: APP_TOUR, steps, index: 0, then: pageRun })
        return
      }
      if (pageRun && pageRun.steps.length > 0) setRunning({ ...pageRun, index: 0 })
    },
    [pathname, search, guide.rules.tours, unseen],
  )

  // On a page change: start what this person has not seen yet, once the page has drawn. Never over the start question.
  const startRef = React.useRef(start)
  startRef.current = start
  React.useEffect(() => {
    setRunning(null)
    if (!guide.ready || guide.ask || guide.rules.tours === 'none') return
    const timer = window.setTimeout(() => startRef.current(false), 900)
    return () => window.clearTimeout(timer)
  }, [pathname, guide.ready, guide.ask, guide.rules.tours])

  // A page whose tour waits for its content (a project to be picked, the data to load): start it when that shows.
  // The address can change without a new page (picking a project adds ?project=), so this watches the screen.
  React.useEffect(() => {
    if (running || !guide.ready || guide.ask || guide.rules.tours !== 'all') return
    const page = tourForPage(pathname, search)
    if (!page?.tour.startWhen || !unseen(page.tour)) return
    const timer = window.setInterval(() => {
      if (pageReady(page.tour)) startRef.current(false)
    }, 1000)
    return () => window.clearInterval(timer)
  }, [running, pathname, search, guide.ready, guide.ask, guide.rules.tours, unseen])

  // "Show me around this page" from Help.
  React.useEffect(() => {
    const replay = () => window.setTimeout(() => startRef.current(true), 250)
    window.addEventListener(TOUR_EVENT, replay)
    return () => window.removeEventListener(TOUR_EVENT, replay)
  }, [])

  const step = running?.steps[running.index]
  const rect = useRect(step?.target, running?.index ?? -1)

  const finish = React.useCallback(() => {
    if (!running) return
    ended.current.add(running.tour.key)
    markSeen.mutate({ page: running.tour.key, version: running.tour.version })
    if (running.then && running.then.steps.length > 0) setRunning({ ...running.then, index: 0 })
    else setRunning(null)
  }, [running, markSeen])

  const skip = React.useCallback(() => {
    if (!running) return
    // Skipping the app tour skips this page's tour too, for now; both are remembered as seen.
    ended.current.add(running.tour.key)
    if (running.then) ended.current.add(running.then.tour.key)
    markSeen.mutate({ page: running.tour.key, version: running.tour.version })
    if (running.then) markSeen.mutate({ page: running.then.tour.key, version: running.then.tour.version })
    setRunning(null)
  }, [running, markSeen])

  const go = React.useCallback(
    (delta: number) => {
      if (!running) return
      const index = running.index + delta
      if (index >= running.steps.length) finish()
      else if (index >= 0) setRunning({ ...running, index })
    },
    [running, finish],
  )

  React.useEffect(() => {
    if (!running) return
    next.current?.focus()
    const keys = (e: KeyboardEvent) => {
      if (e.key === 'Escape') skip()
      else if (e.key === 'ArrowRight') go(1)
      else if (e.key === 'ArrowLeft') go(-1)
    }
    window.addEventListener('keydown', keys)
    return () => window.removeEventListener('keydown', keys)
  }, [running, go, skip])

  // SS-61: a page whose walkthrough has a voice (`page-<path>` in VOICED) speaks its tour too, with the same player.
  const voiced = !!running && VOICED.has(pageWalkId(running.tour))
  const voice = useGuideVoice()
  const words = step ? spokenWords(step) : ''
  const { say: speak, hush, prefetch } = voice
  React.useEffect(() => {
    if (!voiced || !running) {
      hush()
      return
    }
    speak(words)
    const following = running.steps[running.index + 1]
    if (following) prefetch(spokenWords(following))
  }, [voiced, running, words, speak, hush, prefetch])

  if (!running || !step) return null
  const last = running.index === running.steps.length - 1
  return (
    <TourOverlay
      step={step}
      rect={rect}
      sparkKey={`${running.tour.key}-${running.index}`}
      counter={`${running.index + 1} of ${running.steps.length}`}
      nextRef={next}
      onBack={running.index > 0 ? () => go(-1) : undefined}
      onNext={() => go(1)}
      nextLabel={last ? (running.then ? 'Next: this page' : 'Done') : 'Next'}
      onSkip={skip}
    >
      {voiced && <VoicePlayer voice={voice} words={words} />}
    </TourOverlay>
  )
}

/** The Learn page's id for a page tour's walkthrough (`page-boq` for /boq), as walkthroughs.ts names it. */
function pageWalkId(tour: Tour): string {
  const path = Object.entries(PAGE_TOURS).find(([, t]) => t === tour)?.[0]
  return path ? `page${path.replace(/\//g, '-')}` : ''
}

export interface TourOverlayProps {
  step: TourStep
  rect: DOMRect | null
  /** Changes per step, so the Spark plays its entrance again. */
  sparkKey: string
  counter: string
  nextRef?: React.Ref<HTMLButtonElement>
  onBack?: () => void
  onNext: () => void
  nextLabel: string
  nextDisabled?: boolean
  onSkip: () => void
  skipLabel?: string
  /** Let clicks reach the page (a "try it here" step: the person clicks the lit button). */
  passThrough?: boolean
  /** More in the bubble, under the text (a WhatsApp practice, a take-back). */
  children?: React.ReactNode
}

/** The dimmed screen, the lit window and the Spark's bubble: one look for the page tours and the walkthroughs
 *  (components/walkthrough.tsx). */
export function TourOverlay({
  step, rect, sparkKey, counter, nextRef, onBack, onNext, nextLabel, nextDisabled, onSkip, skipLabel = 'Skip tour', passThrough, children,
}: TourOverlayProps) {
  const phone = window.innerWidth < 640
  const spot = rect
    ? { top: rect.top - PAD, left: rect.left - PAD, width: rect.width + PAD * 2, height: rect.height + PAD * 2 }
    : null
  const bubbleH = children ? BUBBLE_H + 110 : BUBBLE_H

  // Where the bubble goes: under the lit thing if there is room, else above it; on a phone, docked at the bottom.
  let bubble: React.CSSProperties
  if (phone || !spot) {
    bubble = phone
      ? { left: 12, right: 12, bottom: `calc(12px + env(safe-area-inset-bottom, 0px))` }
      : { left: '50%', top: '50%', transform: 'translate(-50%, -50%)', width: BUBBLE_W + 40 }
  } else {
    // Below, above, or beside a tall thing (the sidebar); always fully on screen.
    const W = window.innerWidth
    const H = window.innerHeight
    const left = Math.min(Math.max(12, spot.left), W - BUBBLE_W - 12)
    const top = (t: number) => Math.min(Math.max(12, t), H - bubbleH - 12)
    const below = spot.top + spot.height + GAP
    if (H - below >= bubbleH + 12) bubble = { left, top: below, width: BUBBLE_W }
    else if (spot.top - GAP >= bubbleH + 12) bubble = { left, top: spot.top - GAP - bubbleH, width: BUBBLE_W }
    else if (W - (spot.left + spot.width + GAP) >= BUBBLE_W + 12) bubble = { left: spot.left + spot.width + GAP, top: top(spot.top), width: BUBBLE_W }
    else if (spot.left - GAP >= BUBBLE_W + 12) bubble = { left: spot.left - GAP - BUBBLE_W, top: top(spot.top), width: BUBBLE_W }
    else bubble = { left: '50%', top: top(H / 2 - bubbleH / 2), transform: 'translateX(-50%)', width: BUBBLE_W }
  }

  return createPortal(
    <div className={cn('fixed inset-0 z-[60]', passThrough && 'pointer-events-none')} role="presentation" data-tour="">
      {/* The dimmed screen with one lit window; clicks on the page are held while the tour runs, except on a
          "try it here" step. */}
      {spot ? (
        <div
          aria-hidden
          // The lit edge is an outline: a ring is a box-shadow, which the dimming shadow below replaces (it never showed,
          // and on a dark page nothing marked what was lit).
          className="pointer-events-none fixed rounded-xl outline-2 outline-[#facc15] transition-all duration-300 ease-out motion-reduce:transition-none"
          style={{ ...spot, boxShadow: '0 0 0 9999px rgba(15, 17, 20, 0.58)' }}
        />
      ) : (
        <div aria-hidden className={cn('fixed inset-0 bg-[rgba(15,17,20,0.58)]', passThrough && 'pointer-events-none')} />
      )}

      <div
        role="dialog"
        aria-modal={passThrough ? undefined : true}
        aria-labelledby="tour-title"
        aria-describedby="tour-text"
        data-tour=""
        className="pointer-events-auto fixed flex gap-3 rounded-2xl border bg-background p-4 text-foreground shadow-xl"
        style={bubble}
      >
        <Spark key={sparkKey} mood={step.mood ?? 'idle'} size={phone ? 52 : 64} className="shrink-0 self-start" />
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <div aria-live="polite">
            <h2 id="tour-title" className="m-0 text-base font-semibold">{step.title}</h2>
            <p id="tour-text" className="m-0 mt-1 text-sm text-foreground/85">
              <WithTerms text={step.text} />
            </p>
          </div>
          {children}
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <span className="text-xs tabular-nums text-muted-foreground">{counter}</span>
            <button type="button" onClick={onSkip} className="text-xs text-muted-foreground underline underline-offset-2">
              {skipLabel}
            </button>
            <span className="ml-auto flex gap-1.5">
              {onBack && (
                <Button type="button" size="sm" variant="outline" onClick={onBack}>
                  Back
                </Button>
              )}
              <Button ref={nextRef} type="button" size="sm" onClick={onNext} disabled={nextDisabled}>
                {nextLabel}
              </Button>
            </span>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  )
}
