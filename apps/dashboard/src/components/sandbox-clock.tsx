import * as React from 'react'
import { Link } from 'react-router-dom'
import { CalendarClock, ChevronDown, ClipboardList, FastForward, History, Loader2, SkipForward, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { apiErrorMessage } from '@/lib/logo-upload'
import {
  PLAY_TO_EVENT, catchUp, clearSandboxTarget, dayTitle, goBackTo, openingDone, passDays, sandboxTarget, setSandboxSceneBusy, sandboxSession, takeArrival, takeDaysPassed, takeOpening, useSandboxClock, type DaysPassed, type ForYou,
} from '@/lib/sandbox'
import { ArrivalIris, Briefing, DayPassScene, EndCredits, OpeningScene, type SceneMode } from '@/components/sandbox-scenes'
import { prefersReducedMotion } from '@/lib/timeline'
import { findPage } from '@/lib/module-map'

// SS-74e (guided-demo-plan.md section 18): the sample company's days, in its banner. Next day and Skip ahead play the
// planned simulation (backend application/learn/sandbox_player.py): everyone else does their part; what is the
// person's to do waits for them under "For you", each with a link to the page it is done on.

const SKIPS = [2, 3, 7] as const

/** The words for what the cast did, by kind of entry (the plan's kinds, sample_plan.py KINDS). */

function dayName(iso: string): string {
  const d = new Date(`${iso}T12:00:00`)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })
}

function pageName(url: string): string {
  const [path, query = ''] = url.split('?')
  return findPage(path, query ? `?${query}` : '')?.page.title ?? path
}

/** The person's to-dos grouped by the page each is done on, in order of the first one. */
function byPage(items: ForYou[]): { page: string; items: ForYou[] }[] {
  const groups = new Map<string, ForYou[]>()
  for (const item of items) groups.set(item.page, [...(groups.get(item.page) ?? []), item])
  return [...groups].map(([page, list]) => ({ page, items: list }))
}

export function SandboxClock() {
  const session = sandboxSession()
  const clock = useSandboxClock()
  /** Days passing (1..7), or going back (-1). */
  const [busy, setBusy] = React.useState<number | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [away, setAway] = React.useState(takeDaysPassed)
  // UX-71: the scenes. `scene` plays while days pass; after the page loads again it opens through an iris, then the
  // morning briefing (or, on handover, the end credits). Reduced motion: no scene, the briefing still comes.
  const [arrival, setArrival] = React.useState(takeArrival)
  const [scene, setScene] = React.useState<{ mode: SceneMode; from: number; to: number; origin: { x: number; y: number }; result: DaysPassed | null } | null>(null)
  const finishScene = React.useRef<(() => void) | null>(null)
  // The guided project playing on to its chapter's day: no briefing on the way, only when the day is reached.
  const [briefing, setBriefing] = React.useState(() => {
    const target = sandboxTarget()
    return !!(arrival?.kind === 'day' && away) && (target === null || (away?.day ?? 0) >= target)
  })
  const [credits, setCredits] = React.useState(() => !!(arrival?.kind === 'day' && away?.finale))
  const [iris, setIris] = React.useState(() => !!arrival && !prefersReducedMotion())
  // UX-72: coming into the sample company, its opening plays, then the page opens through the iris; the guided
  // project waits for it (lib/sandbox `whenOpeningDone`). Reduced motion: no scene, the project starts at once.
  const [opening, setOpening] = React.useState(() => (session ? takeOpening() : null))
  const reduced = prefersReducedMotion()
  const playOpening = !!opening && !reduced && !clock.isError
  React.useEffect(() => {
    if (opening && !playOpening) openingDone()
  }, [opening, playOpening])
  const openingEl = playOpening && opening && session && (
    <OpeningScene
      kind={opening.kind}
      name={opening.name || session.name}
      role={session.role}
      day={clock.data?.day ?? null}
      date={clock.data?.date ?? session.today ?? null}
      onDone={() => {
        setOpening(null)
        setIris(true)
      }}
    />
  )
  const playScene = (mode: SceneMode, from: number, to: number, el?: HTMLElement | null) => {
    if (prefersReducedMotion()) return undefined
    const r = el?.getBoundingClientRect()
    setScene({ mode, from, to, origin: r ? { x: r.left + r.width / 2, y: r.top + r.height / 2 } : { x: window.innerWidth / 2, y: 80 }, result: null })
    return (d: DaysPassed) => new Promise<void>((resolve) => {
      finishScene.current = resolve
      setScene((s) => (s ? { ...s, result: d } : s))
    })
  }

  // The guided project asked for a day (lib/sandbox playToDay): play on to it a week at a time, through reloads.
  const day = clock.data?.day
  const lastDay = clock.data?.last_day
  const playing = React.useRef(false)
  /** A scene, the opening or the briefing is on screen now. */
  const visual = React.useRef(false)
  React.useEffect(() => {
    const go = () => {
      const target = sandboxTarget()
      if (target === null || day === undefined || lastDay === undefined || playing.current) return
      const to = Math.min(target, lastDay)
      if (day >= to) {
        // Reached: only the request goes; the briefing (or any scene) still on screen keeps the project waiting.
        clearSandboxTarget()
        setSandboxSceneBusy(visual.current)
        return
      }
      playing.current = true
      setSandboxSceneBusy(true)
      const days = Math.min(7, to - day)
      void passDays(days, playScene(days === 1 ? 'next' : 'skip', day, day + days)).catch((e) => {
        playing.current = false
        clearSandboxTarget()
        setSandboxSceneBusy(false)
        setScene(null)
        setError(apiErrorMessage(e))
      })
    }
    go()
    window.addEventListener(PLAY_TO_EVENT, go)
    return () => window.removeEventListener(PLAY_TO_EVENT, go)
  }, [day, lastDay]) // eslint-disable-line react-hooks/exhaustive-deps
  // The guided project waits while the opening, a scene or the morning briefing is up.
  React.useEffect(() => {
    visual.current = !!(scene || iris || briefing || credits || (opening && !reduced))
    setSandboxSceneBusy(visual.current || sandboxTarget() !== null)
  }, [scene, iris, briefing, credits, opening, reduced])

  // Another tab moved the days on: this one opens the sample again on the current date (once).
  const date = clock.data?.date
  React.useEffect(() => {
    if (date && session?.today && date !== session.today && !clock.data?.old) void catchUp(date)
  }, [date, session?.today, clock.data?.old])

  if (!session || clock.isError) return null
  if (clock.data?.old) {
    return (
      <>
        <p className="m-0 text-xs text-muted-foreground">Older sample: Start over (in ⋯) to play its days.</p>
        {openingEl}
      </>
    )
  }
  const c = clock.data
  const done = !!c && c.day >= c.last_day
  const late = c ? c.for_you.filter((f) => f.day < c.day).length : 0

  const pass = async (days: number, el?: HTMLElement | null) => {
    setBusy(days)
    setError(null)
    try {
      await passDays(days, c ? playScene(days === 1 ? 'next' : 'skip', c.day, Math.min(c.day + days, c.last_day), el) : undefined)
    } catch (e) {
      setScene(null)
      setError(apiErrorMessage(e))
      setBusy(null)
    }
  }

  const back = async (day: number, date: string) => {
    const today = c && day === c.day
    if (!window.confirm(today
      ? `Try today again? Everything done since this morning (${dayName(date)}) is undone.`
      : `Go back to day ${day} (${dayName(date)})? Your sample company becomes exactly what it was that morning; the days after it are gone, and Next day plays them again.`)) return
    setBusy(-1)
    setError(null)
    try {
      await goBackTo(day, c ? playScene('back', c.day, day) : undefined)
    } catch (e) {
      setScene(null)
      setError(apiErrorMessage(e))
      setBusy(null)
    }
  }
  const saved = [...(c?.can_go_back_to ?? [])].reverse()

  return (
    <div className="flex flex-col gap-2" data-guide="sandbox.clock">
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1.5 text-sm font-semibold">
          <CalendarClock className="size-4" aria-hidden />
          {c ? (
            <>
              {c.day > 0 ? `Day ${c.day} of ${c.last_day}` : `${dayTitle(c.day)} · ${c.last_day} days to handover`} · {dayName(c.date)}
            </>
          ) : (
            'Day …'
          )}
        </span>
        {done ? (
          <span className="text-xs">Green Villa is handed over. Start over to play it again.</span>
        ) : (
          <>
            <Button size="sm" className="gap-1.5" disabled={!c || busy !== null} onClick={(e) => void pass(1, e.currentTarget)} data-guide="sandbox.next-day"
              aria-label="Move the sample company on to the next day">
              {busy === 1 ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <SkipForward className="size-3.5" aria-hidden />}
              {busy === 1 ? 'A day passes…' : 'Next day'}
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size="sm" variant="outline" className="gap-1.5 bg-background" disabled={!c || busy !== null}>
                  {busy && busy > 1 ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <FastForward className="size-3.5" aria-hidden />}
                  {busy && busy > 1 ? `${busy} days pass…` : 'Skip ahead'}
                  <ChevronDown className="size-3.5" aria-hidden />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-64">
                <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
                  Everyone works through these days, you too; you land on the last with its work waiting for you.
                </DropdownMenuLabel>
                {SKIPS.map((n) => (
                  <DropdownMenuItem key={n} onSelect={() => void pass(n)}>
                    {n === 7 ? 'A week' : `${n} days`}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        )}
        {saved.length > 0 && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="sm" variant="outline" className="gap-1.5 bg-background" disabled={busy !== null} data-guide="sandbox.go-back">
                {busy === -1 ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <History className="size-3.5" aria-hidden />}
                {busy === -1 ? 'Going back…' : 'Go back'}
                <ChevronDown className="size-3.5" aria-hidden />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-64">
              <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
                Back to the morning of a day you were on. Everything after it is undone.
              </DropdownMenuLabel>
              {saved.map((p) => (
                <DropdownMenuItem key={p.day} onSelect={() => void back(p.day, p.date)}>
                  {c && p.day === c.day ? 'Try today again' : `${dayTitle(p.day)} · ${dayName(p.date)}`}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
        {c && c.for_you.length > 0 && <ForYouMenu items={c.for_you} late={late} />}
        {c && c.for_you.length === 0 && !done && <span className="text-xs text-muted-foreground">Nothing for you today</span>}
      </div>
      {error && <p className="m-0 text-sm text-destructive">{error}</p>}
      {away && !briefing && !credits && <Away away={away} onClose={() => setAway(null)} onRead={() => setBriefing(true)} />}
      {scene && (
        <DayPassScene mode={scene.mode} fromDay={scene.from} toDay={scene.to} origin={scene.origin} result={scene.result} onFinished={() => finishScene.current?.()} />
      )}
      {openingEl}
      {iris && <ArrivalIris onDone={() => { setIris(false); setArrival(null); openingDone() }} />}
      {!iris && credits && away?.finale && <EndCredits finale={away.finale} role={session.role} onClose={() => setCredits(false)} />}
      {!iris && !credits && briefing && away && (
        <Briefing
          day={away.day}
          date={away.date}
          moments={(away.highlights ?? []).filter((h) => h.day === away.day)}
          summary={away.summary}
          story={away.story ?? []}
          forYou={away.for_you}
          waiting={away.waiting}
          onClose={() => setBriefing(false)}
        />
      )}
    </div>
  )
}

function ForYouMenu({ items, late }: { items: ForYou[]; late: number }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="sm" variant="outline" className="gap-1.5 bg-background" data-guide="sandbox.for-you">
          <ClipboardList className="size-3.5" aria-hidden />
          For you ({items.length}){late > 0 && <span className="text-destructive">· {late} late</span>}
          <ChevronDown className="size-3.5" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="max-h-[70svh] w-[min(92vw,26rem)] overflow-y-auto">
        <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
          Your part of the day. Do each on its page; it is ticked off when it is saved. Left undone, what needs it waits.
        </DropdownMenuLabel>
        {byPage(items).map((group, i) => (
          <React.Fragment key={group.page}>
            {i > 0 && <DropdownMenuSeparator />}
            <DropdownMenuItem asChild>
              <Link to={group.page} className="flex flex-col items-start gap-0.5">
                <span className="text-sm font-medium">
                  {pageName(group.page)} <span className="font-normal text-muted-foreground">({group.items.length})</span>
                </span>
                {group.items.slice(0, 4).map((item) => (
                  <span key={item.id} className="text-xs text-muted-foreground">
                    {item.what}
                    {item.day < Math.max(...items.map((x) => x.day)) && <span className="text-destructive"> · from day {item.day}</span>}
                  </span>
                ))}
                {group.items.length > 4 && <span className="text-xs text-muted-foreground">and {group.items.length - 4} more</span>}
              </Link>
            </DropdownMenuItem>
          </React.Fragment>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function Away({ away, onClose, onRead }: { away: NonNullable<ReturnType<typeof takeDaysPassed>>; onClose: () => void; onRead: () => void }) {
  const byWho = new Map<string, string[]>()
  for (const s of away.summary) byWho.set(s.who, [...(byWho.get(s.who) ?? []), `${s.said ?? s.kind.replace(/_/g, ' ')} ${s.count}`])
  const days = away.day - away.from
  return (
    <div className="rounded-lg border border-info/20 bg-background/70 p-2.5 text-sm text-foreground" role="status" data-guide="sandbox.away">
      <div className="flex items-start justify-between gap-2">
        <p className="m-0 font-medium">
          {days === 1 ? `Day ${away.day} at Green Villa Builders` : `Days ${away.from + 1} to ${away.day} passed`}
        </p>
        <span className="flex items-center gap-2">
          {/* UX-103: the briefing again, to read what each person did. */}
          <button type="button" className="text-xs font-medium underline underline-offset-2 hover:text-foreground" onClick={onRead}>
            Read the day
          </button>
          <button type="button" className="text-muted-foreground hover:text-foreground" aria-label="Close" onClick={onClose}>
            <X className="size-4" aria-hidden />
          </button>
        </span>
      </div>
      {byWho.size === 0 ? (
        <p className="m-0 text-xs text-muted-foreground">A quiet day: nobody works on Sunday.</p>
      ) : (
        <ul className="m-0 mt-1 flex list-none flex-col gap-0.5 p-0 text-xs">
          {[...byWho].map(([who, did]) => (
            <li key={who}>
              <span className="font-medium">{who}:</span> <span className="text-muted-foreground">{did.join(', ')}</span>
            </li>
          ))}
        </ul>
      )}
      {away.waiting.length > 0 && (
        <p className="m-0 mt-1 text-xs text-draft">
          Waiting on something not done yet ({away.waiting.length}): {away.waiting.slice(0, 3).map((w) => `${w.who}: ${w.what}`).join('; ')}
          {away.waiting.length > 3 ? '…' : ''}
        </p>
      )}
      {away.failed.length > 0 && (
        <p className="m-0 mt-1 text-xs text-destructive">
          {away.failed.length} could not be saved: {away.failed.slice(0, 2).map((f) => f.what).join('; ')}
        </p>
      )}
    </div>
  )
}
