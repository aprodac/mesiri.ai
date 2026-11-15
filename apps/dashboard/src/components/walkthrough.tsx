import * as React from 'react'
import { createPortal } from 'react-dom'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Check, Copy, Loader2, Send, Undo2 } from 'lucide-react'
import { Spark } from '@/components/live/spark'
import { TourOverlay, findTarget, useRect } from '@/components/tour'
import { api } from '@/lib/api'
import { ALL_PAGES } from '@/lib/module-map'
import { useAuth } from '@/lib/AuthContext'
import { useGuideSeen, usePreferences, useStartMode } from '@/lib/start-mode'
import { Button } from '@/components/ui/button'
import { WALKTHROUGH_EVENT, setWalkthroughRunning, startWalkthrough } from '@/lib/tour-events'
import { useTrial } from '@/lib/trial'
import {
  OUTCOME_WALKS, findWalkthrough, learnKey, pageOpenFor, walkFor, type WalkCheck, type WalkStep, type Walkthrough,
} from '@/lib/walkthroughs'
import { waLink } from '@/lib/whatsapp-modal'

// The walkthrough engine (SS-42, learning-centre-plan.md section 4): runs any walkthrough from lib/walkthroughs.ts,
// across pages, with practice on WhatsApp or here and a take-back after each practice. It draws with the page tours'
// overlay (components/tour.tsx). One instance, in the layout; the Learn page starts it (lib/tour-events.ts).

/** How long a step waits for its page to draw its target before it is skipped. */
const WAIT_MS = 4000
const POLL_MS = 4000

interface Run {
  walk: Walkthrough
  index: number
  /** The way we were moving, so a step that can't be shown is skipped in the same direction. */
  dir: 1 | -1
}

/** Is the browser on this page (its path, and its ?view= when it has one)? No ?view= is the page's first view. */
function onPage(url: string, pathname: string, search: string): boolean {
  const [path, query = ''] = url.split('?')
  if (pathname !== path) return false
  const want = new URLSearchParams(query).get('view')
  if (!want) return true
  const view = new URLSearchParams(search).get('view')
  if (view) return view === want
  const first = ALL_PAGES.find(({ page }) => page.url.split('?')[0] === path)?.page.url
  return first === url
}

/** The ids in an existing list route's answer ({ items: [...] } or a bare list). */
async function readIds(check: WalkCheck): Promise<Set<string>> {
  const data = (await api.get(check.path, { params: check.params })).data as unknown
  const rows = Array.isArray(data) ? data : ((data as { items?: unknown[] })?.items ?? [])
  return new Set(rows.map((r) => String((r as { id?: unknown })?.id ?? '')).filter(Boolean))
}

/** A dialog or sheet of the page is open (not the tour's own bubble). */
function pageDialogOpen(): boolean {
  return !!document.querySelector('[role="dialog"][data-state="open"]:not([data-tour])')
}

/** Watches a list for a new record: `got` turns true when one appears that was not there at the start. */
function useCheck(check: WalkCheck | undefined, active: boolean, poll: boolean, onFresh: (id: string) => void) {
  const qc = useQueryClient()
  const [got, setGot] = React.useState(false)
  const before = React.useRef<Set<string> | null>(null)
  const lookNow = React.useCallback(async (): Promise<boolean> => {
    if (!check || !before.current) return false
    try {
      const now = await readIds(check)
      const added = [...now].find((id) => !before.current!.has(id))
      const fresh = !!added
      if (added) {
        setGot(true)
        onFresh(added)
        // The page under the tour read its lists before the record existed: read them again, so the next step
        // ("There it is") shows it.
        void qc.invalidateQueries()
      }
      return fresh
    } catch {
      return false
    }
  }, [check, qc, onFresh])

  React.useEffect(() => {
    setGot(false)
    before.current = null
    if (!check || !active) return
    let stopped = false
    readIds(check)
      .then((ids) => {
        if (!stopped) before.current = ids
      })
      .catch(() => {
        // The list could not be read: the practice still works, just without "Got it".
      })
    return () => {
      stopped = true
    }
  }, [check, active])

  React.useEffect(() => {
    if (!check || !active || !poll || got) return
    const timer = window.setInterval(() => void lookNow(), POLL_MS)
    return () => window.clearInterval(timer)
  }, [check, active, poll, got, lookNow])

  return { got, lookNow, watching: !!check }
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = React.useState(false)
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text)
          setCopied(true)
          window.setTimeout(() => setCopied(false), 1600)
        } catch {
          setCopied(false)
        }
      }}
      className="inline-flex items-center gap-1 rounded-lg border px-2 py-0.5 text-xs font-medium hover:bg-muted"
    >
      {copied ? <Check className="size-3.5" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
      {copied ? 'Copied' : 'Copy'}
    </button>
  )
}

/** A message to send Mesiri: the words, Copy, and Try it on WhatsApp (when Mesiri's number is known). */
function SayThis({ say, number }: { say: string; number: string | null }) {
  return (
    <div className="flex flex-col gap-1.5 rounded-xl bg-[#ece9e1] p-2.5 dark:bg-[#101214]">
      <div className="self-end rounded-xl rounded-tr-sm bg-[#fff3b8] px-3 py-1.5 text-[13px] text-[#1a1d21] dark:bg-[#3a3313] dark:text-[#ecebe6]">
        {say}
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <CopyButton text={say} />
        {number && (
          <a
            href={waLink(number, say)}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 rounded-lg bg-success px-2 py-0.5 text-xs font-medium text-background hover:opacity-90"
          >
            <Send className="size-3.5" aria-hidden /> Try it on WhatsApp
          </a>
        )}
      </div>
    </div>
  )
}

/** After an outcome, the role's next outcome not done yet; after anything else, the first such outcome. */
function nextWalk(walk: Walkthrough, role: string | undefined, seen: Record<string, number>): Walkthrough | undefined {
  const mine = OUTCOME_WALKS.filter((w) => walkFor(w, role))
  const done = (w: Walkthrough) => w.id === walk.id || (seen[learnKey(w.id)] ?? 0) >= (w.version ?? 1)
  const at = mine.findIndex((w) => w.id === walk.id)
  return [...mine.slice(at + 1), ...mine.slice(0, Math.max(at, 0))].find((w) => !done(w))
}

/** "Done": the Spark says so, and offers the next thing worth learning. */
function Finished({ walk, next, onClose }: { walk: Walkthrough; next?: Walkthrough; onClose: () => void }) {
  return createPortal(
    <div
      role="status"
      data-tour=""
      className="fixed inset-x-3 bottom-4 z-[60] mx-auto flex max-w-md items-start gap-3 rounded-2xl border bg-background p-4 shadow-xl sm:inset-x-auto sm:right-6"
    >
      <Spark mood="happy" size={52} className="shrink-0" />
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <p className="m-0 text-sm font-semibold">Done: {walk.title}</p>
        {next ? (
          <p className="m-0 text-sm text-muted-foreground">Next: {next.title}</p>
        ) : (
          <p className="m-0 text-sm text-muted-foreground">You can play it again any time from Learn Mesiri.</p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          {next && (
            <Button size="sm" onClick={() => startWalkthrough(next.id)}>
              Start
            </Button>
          )}
          <Button size="sm" variant="outline" asChild>
            <Link to="/learn" onClick={onClose}>Learn Mesiri</Link>
          </Button>
          <button type="button" onClick={onClose} className="text-xs text-muted-foreground underline underline-offset-2">
            Close
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

export function WalkthroughRunner() {
  const { me } = useAuth()
  const trial = useTrial()
  const prefs = usePreferences()
  const markSeen = useGuideSeen()
  const navigate = useNavigate()
  const { pathname, search } = useLocation()
  const [run, setRun] = React.useState<Run | null>(null)
  /** The step that is on screen (its page open, its target drawn), as walk id:index; a step change hides it at once. */
  const [shownKey, setShownKey] = React.useState<string | null>(null)
  const [dialogOpen, setDialogOpen] = React.useState(false)
  const [note, setNote] = React.useState<string | null>(null)
  /** The record the last practice saved, to light up its row ("There it is"). */
  const [newRecord, setNewRecord] = React.useState<string | null>(null)
  /** Just finished: "Done", and the next one to do. */
  const [finished, setFinished] = React.useState<{ walk: Walkthrough; next?: Walkthrough } | null>(null)
  const guide = useStartMode()
  const next = React.useRef<HTMLButtonElement>(null)
  const number = prefs.data?.whatsapp_number ?? null
  const role = me?.role

  const stop = React.useCallback(() => {
    setRun(null)
    setWalkthroughRunning(false)
  }, [])

  // Start from the Learn page (or anywhere): lib/tour-events.ts startWalkthrough(id).
  React.useEffect(() => {
    const begin = (e: Event) => {
      const walk = findWalkthrough((e as CustomEvent<string>).detail)
      if (!walk) return
      setWalkthroughRunning(true)
      setNewRecord(null)
      setFinished(null)
      setRun({ walk, index: 0, dir: 1 })
    }
    window.addEventListener(WALKTHROUGH_EVENT, begin)
    return () => window.removeEventListener(WALKTHROUGH_EVENT, begin)
  }, [])
  React.useEffect(() => () => setWalkthroughRunning(false), [])

  const step: WalkStep | undefined = run?.walk.steps[run.index]
  const stepKey = run ? `${run.walk.id}:${run.index}` : null
  const shown = !!stepKey && shownKey === stepKey
  // Practice adds real data (D-L3): never on a company whose account is read-only.
  const practiceOff = trial.readOnly

  const finish = React.useCallback(() => {
    if (!run) return
    markSeen.mutate({ page: learnKey(run.walk.id), version: run.walk.version ?? 1 })
    setFinished({ walk: run.walk, next: nextWalk(run.walk, role, guide.seen) })
    stop()
  }, [run, markSeen, stop, role, guide.seen])

  const go = React.useCallback(
    (dir: 1 | -1) => {
      if (!run) return
      const index = run.index + dir
      if (index >= run.walk.steps.length) finish()
      else if (index >= 0) setRun({ ...run, index, dir })
    },
    [run, finish],
  )

  // Enter a step: skip it if this role can't open its page or it is practice on a read-only account; else go to its
  // page and wait for its target. A target that never shows (no data yet, a button this role doesn't have) is never
  // pointed at: a page-tour step is skipped, a workflow step is told in the middle of the screen.
  const navigated = React.useRef<string | null>(null)
  const goRef = React.useRef(go)
  goRef.current = go
  // useNavigate changes with the address; the step must not start over when it does.
  const navigateRef = React.useRef(navigate)
  navigateRef.current = navigate
  React.useEffect(() => {
    setShownKey(null)
    setNote(null)
    setDialogOpen(false)
    if (!run || !step) return
    const here = `${run.walk.id}:${run.index}`
    const skipThis = (step.page && !pageOpenFor(step.page, role)) || (practiceOff && (step.try || step.takeBack))
    if (skipThis) {
      goRef.current(run.dir)
      return
    }
    if (step.page && navigated.current !== here && !onPage(step.page, window.location.pathname, window.location.search)) {
      navigated.current = here
      navigateRef.current(step.page)
    }
    const startedAt = Date.now()
    const timer = window.setInterval(() => {
      const arrived = !step.page || onPage(step.page, window.location.pathname, window.location.search)
      const drawn = !step.target || !!findTarget(step.target)
      if (arrived && drawn && Date.now() - startedAt > 250) {
        window.clearInterval(timer)
        setShownKey(here)
      } else if (Date.now() - startedAt > WAIT_MS) {
        window.clearInterval(timer)
        // Its element never drew: a page-tour step is skipped; a workflow step is told without the light.
        if (arrived && (!step.target || !step.optional)) setShownKey(here)
        else goRef.current(run.dir)
      }
    }, 150)
    return () => window.clearInterval(timer)
  }, [run, step, role, practiceOff])

  // Leaving the walkthrough's pages by hand (the sidebar, a link) ends it: the person went their own way.
  React.useEffect(() => {
    if (!run || !step?.page || !shown) return
    if (!onPage(step.page, pathname, search)) stop()
  }, [pathname, search, run, step, shown, stop])

  const tryIt = step?.try
  const check = useCheck(tryIt?.check, shown, tryIt?.kind === 'whatsapp', setNewRecord)

  // Try here: the person opens the real dialog; the tour steps aside, and comes back when the dialog closes.
  React.useEffect(() => {
    if (!shown || tryIt?.kind !== 'here') return
    let wasOpen = false
    const timer = window.setInterval(() => {
      const open = pageDialogOpen()
      setDialogOpen(open)
      if (open) wasOpen = true
      else if (wasOpen) {
        wasOpen = false
        if (!tryIt.check) goRef.current(1)
        else
          void check.lookNow().then((saved) => {
            if (saved) goRef.current(1)
            else setNote('Nothing saved yet. Try again, or press Next to go on.')
          })
      }
    }, 250)
    return () => window.clearInterval(timer)
  }, [shown, tryIt, check])

  // "There it is": the row of what the practice just saved, else the step's own target.
  const target = step?.showNew && newRecord ? [`record:${newRecord}`, step.target].filter(Boolean).join('|') : step?.target
  const rect = useRect(shown && !dialogOpen ? target : undefined, run?.index ?? -1)

  // A step that waits for its page's content (a project to pick first): watch for it while the person picks.
  const [pageShows, setPageShows] = React.useState(true)
  React.useEffect(() => {
    const wanted = step?.waitFor
    if (!shown || !wanted?.length) {
      setPageShows(true)
      return
    }
    const look = () => setPageShows(wanted.some((id) => !!findTarget(id)))
    look()
    const timer = window.setInterval(look, 500)
    return () => window.clearInterval(timer)
  }, [shown, step])

  React.useEffect(() => {
    if (!run || !shown || dialogOpen) return
    if (tryIt?.kind !== 'here') next.current?.focus()
    const keys = (e: KeyboardEvent) => {
      if (e.key === 'Escape') stop()
    }
    window.addEventListener('keydown', keys)
    return () => window.removeEventListener('keydown', keys)
  }, [run, shown, dialogOpen, tryIt, stop])

  if (finished && !run) return <Finished walk={finished.walk} next={finished.next} onClose={() => setFinished(null)} />
  if (!run || !step) return null

  if (!shown) {
    return createPortal(
      <div className="fixed inset-x-0 bottom-4 z-[60] flex justify-center" data-tour="">
        <span className="inline-flex items-center gap-2 rounded-full border bg-background px-3 py-1.5 text-xs text-muted-foreground shadow">
          <Loader2 className="size-3.5 animate-spin" aria-hidden /> Going there…
        </span>
      </div>,
      document.body,
    )
  }

  if (dialogOpen) {
    // A small Spark in the corner while the person fills the real dialog.
    return createPortal(
      <div
        className="pointer-events-auto fixed bottom-4 left-4 z-[70] flex items-center gap-2 rounded-full border bg-background py-1 pr-3 pl-1 text-sm shadow-lg"
        style={{ pointerEvents: 'auto' }}
        data-tour=""
        role="status"
      >
        <Spark mood="look" size={36} quiet />
        Fill it in and save. I'm waiting.
      </div>,
      document.body,
    )
  }

  const last = run.index === run.walk.steps.length - 1
  const counter = `${run.walk.title} · ${run.index + 1} of ${run.walk.steps.length}`
  let nextLabel = last ? 'Done' : 'Next'
  const cardOnly = tryIt?.kind === 'whatsapp' && tryIt.save === false
  if (tryIt?.kind === 'whatsapp' && !check.got) nextLabel = cardOnly ? 'I tapped Cancel' : "I've sent it"
  if (tryIt?.kind === 'here' && !note) nextLabel = 'Skip this'

  return (
    <TourOverlay
      step={step}
      rect={rect}
      sparkKey={`${run.walk.id}-${run.index}${check.got ? '-got' : ''}`}
      counter={counter}
      nextRef={next}
      onBack={run.index > 0 ? () => go(-1) : undefined}
      onNext={() => go(1)}
      nextLabel={nextLabel}
      onSkip={stop}
      skipLabel="Stop"
      passThrough={tryIt?.kind === 'here' || !pageShows}
      nextDisabled={!pageShows}
    >
      {!pageShows && (
        <p className="m-0 text-xs font-medium" role="status">
          Pick a project on this page first. I'll carry on when it opens.
        </p>
      )}
      {tryIt?.kind === 'whatsapp' && (
        <div className="flex flex-col gap-1.5">
          <SayThis say={tryIt.say} number={number} />
          {cardOnly && (
            <p className="m-0 text-xs text-muted-foreground">Practice only: tap Cancel on the card, so nothing is saved.</p>
          )}
          {check.watching && (
            <p className="m-0 flex items-center gap-1.5 text-xs" role="status">
              {check.got ? (
                <span className="font-medium text-success">
                  <Check className="mr-1 inline size-3.5" aria-hidden />
                  Got it. It's saved.
                </span>
              ) : (
                <span className="text-muted-foreground">
                  <Loader2 className="mr-1 inline size-3.5 animate-spin" aria-hidden />
                  Waiting for you to tap Save…
                </span>
              )}
            </p>
          )}
        </div>
      )}
      {tryIt?.kind === 'here' && note && <p className="m-0 text-xs text-muted-foreground" role="status">{note}</p>}
      {step.takeBack && (
        <div className="flex flex-col gap-1.5 rounded-xl border border-dashed p-2.5">
          <p className="m-0 flex items-center gap-1.5 text-xs font-semibold">
            <Undo2 className="size-3.5" aria-hidden /> To take it back
          </p>
          {step.takeBack.say && <SayThis say={step.takeBack.say} number={number} />}
          {step.takeBack.here && <p className="m-0 text-xs text-foreground/85">{step.takeBack.here}</p>}
        </div>
      )}
    </TourOverlay>
  )
}
