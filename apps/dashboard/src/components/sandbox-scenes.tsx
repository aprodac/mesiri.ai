import * as React from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'
import type { LucideIcon } from 'lucide-react'
import {
  AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, ClipboardList, Clock, FastForward, FileText, Flag, Hammer, HandCoins, Package, Rewind, Truck, Users, Volume2,
  VolumeX, Wallet, X,
} from 'lucide-react'
import { Ink } from '@/components/live/ink'
import { prefersReducedMotion } from '@/lib/timeline'
import { dayTitle, dayTitleSize, type DaysPassed, type ForYou } from '@/lib/sandbox'
import { typingIn } from '@/lib/keys'
import { sceneSoundOn, soundMs, useSceneSound, useSounds } from '@/lib/scene-sound'
import { cn } from '@/lib/utils'

// UX-71 (asked 18 Nov 2026: "in the simulation I want more cinematicness, like the bit we added when we move from
// Live"): the sample company's days as scenes, in the Live cut's language (a dark screen, a title rising letter by
// letter in the brand font, lines writing themselves, the page opening through an iris):
// - DayPassScene: Next day (dusk, night while the cast plays the day, dawn with the day's title and its moments),
//   Skip ahead (the day counter racing, the moments flashing past), Go back (a rewind: colour drains, the counter runs
//   down);
// - ArrivalIris: the page that loads on the new day opens through a circle;
// - Briefing: the morning: each person's card with what they did, then "Your part today";
// - EndCredits: Green Villa handed over: the cast and the run's numbers roll;
// - EpisodeCard: a chapter's title card in the guided project;
// - OpeningScene (UX-72): coming into the sample company: its name over the site at night, the sun coming up on the
//   cast (the person's own part marked "You"), then the day; opened again later, a short "back on site".
// Every scene can be skipped (a click on Skip, or Esc); with reduced motion none plays: the page simply goes.
// UX-73: each scene has its sound (lib/scene-sound.ts: the narrator's lines and the sound under them), on or off with
// the guide voice (the speaker button, or M); a scene with sound on waits for its line before it moves on.

export type SceneMode = 'next' | 'skip' | 'back'
export type Moment = NonNullable<DaysPassed['highlights']>[number]

const INK = '#0b0d10'

/** The cast as the scenes show them. */
const CAST: Record<string, { role: string; tone: string }> = {
  Ravi: { role: 'Site engineer', tone: 'bg-orange-500' },
  Anil: { role: 'Project manager', tone: 'bg-sky-500' },
  Meera: { role: 'Accounts', tone: 'bg-violet-500' },
  Owner: { role: 'Owner', tone: 'bg-yellow-400 text-black' },
}

const KIND: Record<string, { icon: LucideIcon; tone: string }> = {
  work: { icon: Hammer, tone: 'text-orange-300' },
  request: { icon: ClipboardList, tone: 'text-amber-300' },
  order: { icon: Package, tone: 'text-sky-300' },
  delivery: { icon: Truck, tone: 'text-emerald-300' },
  issue: { icon: AlertTriangle, tone: 'text-red-300' },
  issue_resolve: { icon: CheckCircle2, tone: 'text-emerald-300' },
  supplier_payment: { icon: Wallet, tone: 'text-violet-300' },
  sub_payment: { icon: Wallet, tone: 'text-violet-300' },
  wage_pay: { icon: Wallet, tone: 'text-violet-300' },
  advance: { icon: HandCoins, tone: 'text-violet-300' },
  client_receipt: { icon: HandCoins, tone: 'text-emerald-300' },
  ra_bill: { icon: FileText, tone: 'text-teal-300' },
  work_order: { icon: FileText, tone: 'text-teal-300' },
  stage: { icon: Flag, tone: 'text-yellow-300' },
  // UX-103: the briefing's story lines (routine kinds never reach the day-pass scene).
  attendance: { icon: Users, tone: 'text-sky-300' },
  use: { icon: Package, tone: 'text-sky-300' },
  expense: { icon: Wallet, tone: 'text-violet-300' },
  machine: { icon: Truck, tone: 'text-sky-300' },
  machine_log: { icon: Clock, tone: 'text-sky-300' },
  boq_count: { icon: ClipboardList, tone: 'text-teal-300' },
  boq_import: { icon: FileText, tone: 'text-teal-300' },
  boq_norms: { icon: FileText, tone: 'text-teal-300' },
  wage_approve: { icon: CheckCircle2, tone: 'text-emerald-300' },
}

/** The plan writes each entry as a to-do ("Order 100 bags cement…"); a scene tells it as done ("Ordered …"). */
function didIt(kind: string, what: string): string {
  if (kind === 'issue') return `Problem: ${what}`
  if (kind === 'work') return `Done: ${what}`
  const rules: [RegExp, string][] = [[/^Order /, 'Ordered '], [/^Ask for /, 'Asked for '], [/^Pay /, 'Paid '], [/^Send /, 'Sent '], [/^Close: /, 'Fixed: ']]
  for (const [re, to] of rules) if (re.test(what)) return what.replace(re, to)
  return what
}

function dayName(iso: string): string {
  const d = new Date(`${iso}T12:00:00`)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' })
}

function useOpen(delay = 0): boolean {
  const [open, setOpen] = React.useState(false)
  React.useLayoutEffect(() => {
    let frame = 0
    const t = window.setTimeout(() => {
      frame = requestAnimationFrame(() => requestAnimationFrame(() => setOpen(true)))
    }, delay)
    return () => {
      window.clearTimeout(t)
      cancelAnimationFrame(frame)
    }
  }, [delay])
  return open
}

const wait = (ms: number) => new Promise((r) => window.setTimeout(r, ms))

/** A title rising letter by letter (the Live cut's). */
export function RisingTitle({ text, show, delay = 0, className }: { text: string; show: boolean; delay?: number; className?: string }) {
  return (
    <h2 className={cn('m-0 flex flex-wrap gap-x-[0.28em] overflow-hidden font-brand leading-[1.05] tracking-[-0.02em]', className)} aria-label={text}>
      {/* Letters rise one by one, but a word never breaks across lines. */}
      {text.split(' ').map((word, w, words) => {
        const before = words.slice(0, w).join(' ').length + (w ? 1 : 0)
        return (
          <span key={w} className="inline-flex overflow-hidden whitespace-nowrap" aria-hidden="true">
            {[...word].map((ch, i) => (
              <span
                key={i}
                className="inline-block transition-[transform,opacity] duration-500 ease-out"
                style={{ transform: show ? 'none' : 'translateY(105%)', opacity: show ? 1 : 0, transitionDelay: `${delay + (before + i) * 35}ms` }}
              >
                {ch}
              </span>
            ))}
          </span>
        )
      })}
    </h2>
  )
}

function MomentLine({ m, index, compact }: { m: Moment; index: number; compact?: boolean }) {
  const look = KIND[m.kind] ?? KIND.work
  const show = useOpen(index * (compact ? 120 : 380))
  return (
    <li
      className="flex items-start gap-3 transition-[transform,opacity] duration-500 ease-out"
      style={{ transform: show ? 'none' : 'translateX(24px)', opacity: show ? 1 : 0 }}
    >
      <span className={cn('mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-white', CAST[m.who]?.tone ?? 'bg-white/20')} aria-hidden>
        {m.who.slice(0, 1)}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5 text-[11px] font-medium tracking-wide text-white/55 uppercase">
          <look.icon className={cn('size-3.5', look.tone)} aria-hidden /> {m.who} · day {m.day}
        </span>
        <span className="block text-[15px] leading-snug text-white/90">{didIt(m.kind, m.what)}</span>
      </span>
    </li>
  )
}

/** Sound on or off (M), and "Tap for sound" while the browser holds it until a tap. */
function SoundButton() {
  const sound = useSceneSound()
  const { toggle } = sound
  React.useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.key === 'm' || e.key === 'M') && !e.ctrlKey && !e.metaKey && !e.altKey && !typingIn(e)) toggle()
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [toggle])
  const Icon = sound.on ? Volume2 : VolumeX
  return (
    <button
      type="button"
      onClick={sound.held ? undefined : toggle}
      aria-label={sound.held ? 'Play the sound' : sound.on ? 'Sound off (M)' : 'Sound on (M)'}
      className={cn('absolute bottom-5 left-5 inline-flex items-center gap-1.5 rounded-full bg-white/10 px-3 py-1.5 text-xs font-medium text-white/80 ring-1 ring-white/15 backdrop-blur hover:bg-white/20', sound.held && 'animate-pulse text-white')}
    >
      <Icon className="size-3.5" aria-hidden /> {sound.held ? 'Tap for sound' : sound.on ? 'Sound on' : 'Sound off'}
    </button>
  )
}

/** Skip: a click on the button, or Esc. */
function SkipButton({ onSkip, label = 'Skip' }: { onSkip: () => void; label?: string }) {
  React.useEffect(() => {
    const key = (e: KeyboardEvent) => e.key === 'Escape' && onSkip()
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [onSkip])
  return (
    <>
    <SoundButton />
    <button type="button" onClick={onSkip} className="absolute right-5 bottom-5 inline-flex items-center gap-1 rounded-full bg-white/10 px-3 py-1.5 text-xs font-medium text-white/80 ring-1 ring-white/15 backdrop-blur hover:bg-white/20">
      {label} <ChevronRight className="size-3.5" aria-hidden />
    </button>
    </>
  )
}

/**
 * The days passing, shown while the cast plays them. `result` arrives when the server is done; the scene then tells
 * the day (its title, its moments) and calls `onFinished`, which loads the page on the new day.
 */
export function DayPassScene({ mode, fromDay, toDay, origin, result, onFinished }: {
  mode: SceneMode
  fromDay: number
  toDay: number
  origin: { x: number; y: number }
  result: DaysPassed | null
  onFinished: () => void
}) {
  const open = useOpen()
  const [phase, setPhase] = React.useState<'dusk' | 'night' | 'dawn'>('dusk')
  const [skip, setSkip] = React.useState(false)
  const [counter, setCounter] = React.useState(fromDay)
  const finished = React.useRef(false)
  const finish = React.useCallback(() => {
    if (finished.current) return
    finished.current = true
    onFinished()
  }, [onFinished])

  // Dusk turns to night while the cast plays; the counter creeps forward (Skip ahead) or back (Go back).
  React.useEffect(() => {
    const t = window.setTimeout(() => setPhase('night'), 1100)
    return () => window.clearTimeout(t)
  }, [])
  React.useEffect(() => {
    if (mode === 'next' || result) return
    const towards = mode === 'back' ? toDay : toDay - 1
    const id = window.setInterval(() => setCounter((c) => (c === towards ? c : c + Math.sign(towards - c))), mode === 'back' ? 260 : 420)
    return () => window.clearInterval(id)
  }, [mode, toDay, result])

  // The day is played: dawn, the title, its moments; then the page.
  const moments = React.useMemo(() => {
    const all = result?.highlights ?? []
    return mode === 'next' ? all.slice(0, 5) : all.slice(-8)
  }, [result, mode])
  React.useEffect(() => {
    if (!result) return
    if (skip) {
      finish()
      return
    }
    let cancelled = false
    void (async () => {
      setCounter(result.day)
      await wait(phase === 'dusk' ? 600 : 0)
      if (cancelled) return
      setPhase('dawn')
      const hold = mode === 'back' ? 1500 : 1900 + moments.length * (mode === 'next' ? 420 : 150) + 900
      await wait(hold)
      if (!cancelled) finish()
    })()
    return () => {
      cancelled = true
    }
    // phase is read once when the result lands, on purpose
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result, skip])

  const reveal = open ? `circle(150vmax at ${origin.x}px ${origin.y}px)` : `circle(0px at ${origin.x}px ${origin.y}px)`
  const dawn = phase === 'dawn'
  // UX-73: dusk with its line and the night under the cast's day; then morning. Skip ahead whirs, Go back rewinds.
  const night = mode === 'next'
    ? [{ id: 'sfx-whoosh', volume: 0.45 }, { id: 'pass-dusk', delay: 300 }, { id: 'sfx-night', volume: 0.35, loop: true, delay: 900 }]
    : mode === 'skip'
      ? [{ id: 'sfx-whoosh', volume: 0.45 }, { id: 'sfx-forward', volume: 0.4, loop: true }, { id: 'pass-skip', delay: 250 }]
      : [{ id: 'sfx-rewind', volume: 0.4, loop: true }, { id: 'pass-back', delay: 250 }]
  useSounds(dawn ? null : night, `pass-${mode}-${dawn}`)
  useSounds(dawn && mode !== 'back' ? [{ id: 'pass-dawn', delay: 150 }, { id: 'sfx-dawn', volume: 0.4 }] : null, `dawn-${mode}-${dawn}`)
  const titleDay = result?.day ?? (mode === 'next' ? toDay : counter)
  const title = dayTitle(titleDay)

  return createPortal(
    <div
      role="status"
      aria-live="assertive"
      className="fixed inset-0 z-[90] overflow-hidden text-white"
      style={{ clipPath: reveal, transition: 'clip-path 700ms cubic-bezier(.7,0,.2,1)', backgroundColor: INK }}
    >
      {mode === 'next' && <Sky phase={phase} />}
      {mode === 'skip' && <Speed />}
      {mode === 'back' && <Rewinding />}

      <div className={cn('relative mx-auto flex h-full max-w-3xl flex-col justify-center gap-5 px-6 [text-shadow:0_1px_12px_rgba(0,0,0,.45)]', mode === 'next' && 'pb-[26vh]')}>
        <span className="flex items-center gap-2 font-mono text-[12px] tracking-[0.12em] text-white/60 uppercase">
          {mode === 'skip' && <FastForward className="size-4" aria-hidden />}
          {mode === 'back' && <Rewind className="size-4" aria-hidden />}
          {mode === 'back' ? 'Going back' : mode === 'skip' ? `Skipping ahead · ${toDay - fromDay} days` : dawn ? 'Morning at Green Villa Builders' : 'Night falls on site'}
        </span>
        {mode === 'next' ? (
          <RisingTitle key={dawn ? 'dawn' : 'night'} text={dawn ? title : dayTitle(fromDay)} show={open} delay={dawn ? 100 : 350} className={dayTitleSize(dawn ? titleDay : fromDay, 'text-[clamp(56px,12vw,150px)]', 'text-[clamp(40px,8vw,96px)]')} />
        ) : (
          <div className={cn('font-brand leading-none tabular-nums transition-transform', dayTitleSize(titleDay, 'text-[clamp(64px,14vw,170px)]', 'text-[clamp(40px,8vw,96px)]'), !result && 'animate-pulse')}>{title}</div>
        )}
        {dawn && result && <Ink text={dayName(result.date)} writing delay={250} className="text-[clamp(16px,2.2vw,24px)] text-white/80" />}
        {!dawn && mode === 'next' && <p className="m-0 text-[15px] text-white/60">The team works through the day…</p>}
        {dawn && moments.length > 0 && mode !== 'back' && (
          <ul className={cn('m-0 mt-2 flex list-none flex-col gap-3 p-0', mode === 'skip' && 'gap-2')}>
            {moments.map((m, i) => <MomentLine key={`${m.day}-${i}`} m={m} index={i} compact={mode === 'skip'} />)}
          </ul>
        )}
        {dawn && result && mode !== 'back' && moments.length === 0 && <p className="m-0 text-[15px] text-white/60">A quiet day on site.</p>}
        <span
          className="h-[3px] bg-primary transition-[width] ease-in-out"
          style={{ width: dawn ? '100%' : open ? '20%' : '0%', transitionDuration: dawn ? '1600ms' : '900ms' }}
          aria-hidden="true"
        />
      </div>
      <SkipButton onSkip={() => (result ? finish() : setSkip(true))} label={skip ? 'Opening as soon as it is ready' : 'Skip'} />
    </div>,
    document.body,
  )
}

/** Next day: the sun sets, the stars come out while the cast plays the day, then the sun comes up. */
function Sky({ phase }: { phase: 'dusk' | 'night' | 'dawn' }) {
  const layer = 'absolute inset-0 transition-opacity duration-[1400ms] ease-in-out'
  return (
    <div aria-hidden className="absolute inset-0">
      <div className={layer} style={{ opacity: phase === 'dusk' ? 1 : 0, background: 'linear-gradient(180deg,#1e1b4b 0%,#7c2d12 62%,#f97316 100%)' }} />
      <div className={layer} style={{ opacity: phase === 'night' ? 1 : 0, background: 'linear-gradient(180deg,#05060a 0%,#0f172a 70%,#1e1b4b 100%)' }} />
      <div className={layer} style={{ opacity: phase === 'dawn' ? 1 : 0, background: 'linear-gradient(180deg,#0c4a6e 0%,#9a3412 70%,#fbbf24 100%)' }} />
      {/* Stars at night. */}
      <div className={layer} style={{ opacity: phase === 'night' ? 1 : 0 }}>
        {STARS.map(([x, y, s], i) => (
          <span key={i} className="absolute rounded-full bg-white animate-pulse" style={{ left: `${x}%`, top: `${y}%`, width: s, height: s, animationDelay: `${(i % 7) * 0.3}s` }} />
        ))}
      </div>
      {/* The sun: setting at the right, rising at the left. */}
      <div
        className="absolute size-40 rounded-full bg-[radial-gradient(circle,#fde68a_0%,#f59e0b_55%,transparent_70%)] blur-[1px] transition-all duration-[1600ms] ease-in-out"
        style={
          phase === 'dusk'
            ? { right: '12%', bottom: '8%', opacity: 1 }
            : phase === 'night'
              ? { right: '12%', bottom: '-30%', opacity: 0 }
              : { right: '70%', bottom: '6%', opacity: 1 }
        }
      />
      {/* The site against the sky: a block going up in its frame, the finished blocks, a tower crane. */}
      <svg className="absolute bottom-0 left-0 h-[30vh] w-full" viewBox="0 0 1440 300" preserveAspectRatio="xMidYMax slice" aria-hidden>
        <g fill="#05060a" opacity="0.92">
          <rect x="0" y="230" width="1440" height="70" />
          <rect x="70" y="150" width="170" height="150" />
          <rect x="260" y="185" width="120" height="115" />
          <rect x="420" y="120" width="210" height="180" />
          <rect x="980" y="170" width="160" height="130" />
          <rect x="1170" y="140" width="190" height="160" />
          {/* The crane: mast, jib, counter-jib, the hook's line. */}
          <rect x="806" y="40" width="14" height="260" />
          <rect x="640" y="40" width="380" height="9" />
          <rect x="820" y="49" width="70" height="16" />
          <rect x="700" y="49" width="2" height="90" />
          <rect x="690" y="139" width="22" height="12" />
          <path d="M806 40 L813 10 L820 40 Z" />
        </g>
        {/* The frame of the block going up: columns and slabs. */}
        <g stroke="#05060a" strokeWidth="6" opacity="0.92">
          <path d="M660 300V170M720 300V170M780 300V170M860 300V170M920 300V170M650 230H930M650 170H930" fill="none" />
        </g>
        {/* A few lit windows. */}
        <g fill="#fbbf24" opacity={phase === 'night' ? 0.85 : 0.35}>
          {WINDOWS.map(([x, y], i) => <rect key={i} x={x} y={y} width="10" height="12" />)}
        </g>
      </svg>
    </div>
  )
}

const WINDOWS: [number, number][] = [[95, 175], [140, 205], [185, 175], [460, 150], [520, 190], [580, 150], [460, 230], [1010, 200], [1090, 230], [1200, 165], [1260, 205], [1320, 165], [290, 215]]
const STARS: [number, number, number][] = Array.from({ length: 42 }, (_, i) => [(i * 37) % 100, (i * 53) % 60, i % 5 === 0 ? 3 : 2])

/** Skip ahead: the hazard stripe racing past, light streaks. */
function Speed() {
  return (
    <div aria-hidden className="absolute inset-0">
      <div className="absolute inset-x-0 top-0 h-2 bg-[repeating-linear-gradient(135deg,#1a1d21_0_8px,#facc15_8px_16px)] [background-size:22px_22px] motion-safe:animate-[stripe_0.6s_linear_infinite]" />
      {Array.from({ length: 14 }, (_, i) => (
        <span
          key={i}
          className="absolute h-px bg-gradient-to-r from-transparent via-white/40 to-transparent motion-safe:animate-[streak_0.9s_linear_infinite]"
          style={{ top: `${8 + i * 6.5}%`, width: `${20 + (i % 4) * 10}%`, animationDelay: `${(i % 5) * 0.17}s` }}
        />
      ))}
    </div>
  )
}

/** Go back: colour drains from the page beneath, and old-tape lines run across it. */
function Rewinding() {
  return (
    <div aria-hidden className="absolute inset-0">
      <div className="absolute inset-0 bg-[#0b0d10]/85" />
      <div className="absolute inset-0 opacity-30 [background:repeating-linear-gradient(0deg,rgba(255,255,255,.08)_0_1px,transparent_1px_4px)]" />
      <div className="absolute inset-x-0 h-24 bg-white/[0.04] motion-safe:animate-[tape_1.4s_linear_infinite]" />
    </div>
  )
}

/** The page that loads on a new day opens through a circle (the Live cut's reveal). */
export function ArrivalIris({ onDone }: { onDone: () => void }) {
  const open = useOpen(120)
  useSounds([{ id: 'sfx-whoosh', volume: 0.4, delay: 80 }], 'iris')
  React.useEffect(() => {
    const t = window.setTimeout(onDone, 1100)
    return () => window.clearTimeout(t)
  }, [onDone])
  return createPortal(
    <div aria-hidden className="pointer-events-none fixed inset-0 z-[90] grid place-items-center overflow-hidden">
      <span
        className="rounded-full transition-[width,height] duration-[900ms] ease-[cubic-bezier(.7,0,.2,1)]"
        style={{ width: open ? '260vmax' : 0, height: open ? '260vmax' : 0, boxShadow: `0 0 0 260vmax ${INK}` }}
      />
    </div>,
    document.body,
  )
}

/** UX-103: one thing the cast did on the day (backend sandbox_player.day_story). */
export type StoryEntry = NonNullable<DaysPassed['story']>[number]

/** UX-103: who each person is, told once at the top of their day. */
const ROLE_STORY: Record<string, string> = {
  Ravi: 'Ravi is the site engineer. Each evening he tells Mesiri what happened at every site: who came, what got built, what was used and spent, and what the site needs next.',
  Anil: 'Anil is the project manager. He turns what the sites need into orders, keeps the BOQ counted, gives out work and closes problems.',
  Meera: 'Meera keeps the accounts: supplier and subcontract bills in, payments out, wages, and the money the client pays.',
  Owner: 'You, the owner, sign off what needs you: wage sheets, stock counts, the contract and the bills sent to the client.',
}

/** UX-103: why a kind of entry matters, said once per person the first time it shows in their day. */
const WHY: Record<string, string> = {
  conditions: 'The site day: the weather and the notes, so the daily report tells the full day.',
  attendance: 'Who came to work: wages are worked out from it.',
  work: 'What got built: progress and the BOQ move with it.',
  use: 'Material used: the stock at the site goes down, and the BOQ can check it against the norm.',
  expense: 'Small spends paid on site: they show in the project cost.',
  issue: 'A problem raised: it stays open until someone closes it.',
  request: 'What the site needs: the office orders it.',
  delivery: 'Material arrived: the stock goes up and the order is ticked off.',
  order: 'An order to a supplier, from what the site asked for.',
  transfer: 'Material moved from one site to another: both stocks change.',
  rfq: 'Prices asked from suppliers before buying.',
  quote: 'A supplier sent its price.',
  award: 'The best quote was picked: it becomes the order.',
  return: 'Material sent back to the supplier.',
  return_settle: 'A return settled with the supplier.',
  bill_reverse: 'A wrong bill taken back.',
  stock_count: 'The stock counted by hand, to check what Mesiri says is there.',
  count_approve: 'A stock count signed off: the stock is set to what was counted.',
  machine: 'A machine taken on hire: its hours are billed.',
  machine_log: 'Machine hours logged: the hire bill is checked against them.',
  task: 'A job given to someone, with a date.',
  task_status: 'A job marked done.',
  hire_bill: 'A machine hire bill booked.',
  hire_bill_fix: 'A hire bill corrected to the hours logged.',
  boq_count: 'Work put on its BOQ line: what is done is measured against the estimate.',
  boq_import: 'The estimate put in as the BOQ: every line, quantity and rate.',
  boq_norms: 'How much material each unit of work takes: Mesiri warns when a site uses more.',
  issue_resolve: 'A problem closed.',
  work_order: 'Work given to a subcontractor at an agreed rate.',
  measurement: 'Subcontract work measured: the bill is checked against it.',
  supplier_bill: 'A supplier bill booked: what the company owes.',
  supplier_payment: 'A supplier paid.',
  sub_bill: 'A subcontractor bill booked.',
  sub_payment: 'A subcontractor paid.',
  sub_bill_reject: 'A subcontract bill turned down.',
  advance: 'An advance to a worker: it comes off their wages.',
  wage_pay: 'Wages paid for the week.',
  client_receipt: 'Money came in from the client.',
  wage_approve: 'A wage sheet approved: Meera can pay it.',
  ra_bill: 'A running bill sent to the client for the work done.',
  stage: 'The project moved to its next stage.',
  contract: 'The contract with the client: its value, dates and retention.',
}

/** The plan writes each entry as a to-do; the story tells it as done. */
function told(e: StoryEntry): string {
  if (e.kind === 'work') return `Built ${e.what.replace(/^(.)/, (c) => c.toLowerCase())}`
  if (e.kind === 'attendance') return e.what.replace(/^Attendance: /, '')
  if (e.kind === 'conditions') return `Weather: ${e.what.toLowerCase()}`
  if (e.kind === 'expense') return `Spent on ${e.what.replace(/^(.)/, (c) => c.toLowerCase())}`
  if (e.kind === 'machine_log') return `Logged ${e.what.replace(/^(.)/, (c) => c.toLowerCase())}`
  const rules: [RegExp, string][] = [
    [/^Count /, 'Counted '], [/^Approve /, 'Approved '], [/^Put /, 'Put '], [/^Set /, 'Set '], [/^Book /, 'Booked '],
    [/^Give /, 'Gave '], [/^Move /, 'Moved '], [/^Return /, 'Returned '], [/^Close /, 'Closed '], [/^Mark /, 'Marked '],
  ]
  for (const [re, to] of rules) if (re.test(e.what)) return e.what.replace(re, to)
  return didIt(e.kind, e.what)
}

/** Where an entry happened, as a heading: "Green Villa · Main block", "Green Villa", or "The company". */
function placeOf(e: StoryEntry): string {
  if (e.project && e.site) return `${e.project} · ${e.site}`
  return e.project ?? e.site ?? 'The company'
}

/** One line for a person's day: "4 sites · 32 people on site · 4 pieces of work · 4 requests". */
function headline(entries: StoryEntry[]): string {
  const n = (k: string) => entries.filter((e) => e.kind === k).length
  const sites = new Set(entries.filter((e) => e.site).map((e) => e.site)).size
  const people = entries.filter((e) => e.kind === 'attendance').reduce((t, e) => t + (Number(/(\d+)/.exec(e.what)?.[1]) || 0), 0)
  const parts: string[] = []
  if (sites > 1 && entries.some((e) => e.kind === 'attendance')) parts.push(`${sites} sites`)
  if (people) parts.push(`${people} people on site`)
  const counted: [string, string, string][] = [
    ['boq_import', 'BOQ put in', 'BOQs put in'], ['work', 'piece of work', 'pieces of work'], ['request', 'request', 'requests'], ['order', 'order', 'orders'],
    ['delivery', 'delivery', 'deliveries'], ['issue', 'problem', 'problems'], ['boq_count', 'BOQ count', 'BOQ counts'],
    ['supplier_payment', 'payment', 'payments'], ['wage_pay', 'wage payment', 'wage payments'], ['wage_approve', 'wage sheet', 'wage sheets'],
  ]
  for (const [k, one, many] of counted) if (n(k)) parts.push(`${n(k)} ${n(k) === 1 ? one : many}`)
  const rest = entries.length - parts.length
  if (!parts.length) return `${entries.length} ${entries.length === 1 ? 'thing' : 'things'} done`
  return parts.slice(0, 4).join(' · ') + (rest > 0 && parts.length > 4 ? ' · more' : '')
}

/** A person's day as lines under each place: material used is said once per place, the rest one line each. */
function storyLines(entries: StoryEntry[]): { place: string; lines: { kind: string; text: string }[] }[] {
  const places = new Map<string, StoryEntry[]>()
  for (const e of entries) places.set(placeOf(e), [...(places.get(placeOf(e)) ?? []), e])
  return [...places].map(([place, es]) => {
    const used = es.filter((e) => e.kind === 'use').map((e) => e.what.replace(/^Used /, '').replace(/ for .*$/, ''))
    const lines: { kind: string; text: string }[] = []
    const head = es.filter((e) => e.kind === 'attendance' || e.kind === 'conditions').map(told)
    if (head.length) lines.push({ kind: 'attendance', text: head.join(' · ') })
    for (const e of es) if (!['use', 'attendance', 'conditions'].includes(e.kind)) lines.push({ kind: e.kind, text: told(e) })
    if (used.length) lines.push({ kind: 'use', text: `Used ${used.join(', ')}` })
    return { place, lines }
  })
}

/** The morning: what each person did (each can be opened to read their day as a story), then the person's part. */
export function Briefing({ day, date, moments, summary, story, forYou, waiting, onClose }: {
  day: number
  date: string
  moments: Moment[]
  summary: { who: string; kind: string; count: number; said?: string; short?: string }[]
  story: StoryEntry[]
  forYou: ForYou[]
  waiting: { who: string; what: string }[]
  onClose: () => void
}) {
  const open = useOpen(150)
  const [shown, setShown] = React.useState<string | null>(null)
  const [showWaiting, setShowWaiting] = React.useState(false)
  useSounds([{ id: 'briefing', delay: 450 }], `briefing-${day}`)
  React.useEffect(() => {
    const key = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [onClose])
  // Everyone who did something: from the day's story, else (an older reply without it) the counts.
  const people = Object.keys(CAST).filter((who) => story.some((s) => s.who === who) || summary.some((s) => s.who === who))
  const todo = forYou.filter((f) => !f.done)
  return createPortal(
    <div className="fixed inset-0 z-[85] grid place-items-center bg-black/50 p-3 backdrop-blur-sm sm:p-4" role="dialog" aria-modal="true" aria-label={`Morning of day ${day}`} onClick={onClose}>
      <div
        className="relative flex max-h-[88vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border bg-card text-card-foreground shadow-2xl transition-[transform,opacity] duration-500 ease-out"
        style={{ transform: open ? 'none' : 'translateY(24px) scale(.98)', opacity: open ? 1 : 0 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div aria-hidden className="h-1 shrink-0 bg-primary" />
        <button type="button" onClick={onClose} className="absolute top-3.5 right-3.5 rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground" aria-label="Close">
          <X className="size-4" />
        </button>
        <div className="flex flex-col gap-1 border-b px-5 pt-5 pb-4 sm:px-6">
          <span className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Good morning · {dayTitle(day)}</span>
          <RisingTitle text={dayName(date)} show={open} delay={150} className="text-[clamp(24px,3.6vw,30px)]" />
          <p className="m-0 mt-1 text-sm text-muted-foreground">
            {people.length === 0
              ? 'A quiet day: nobody worked.'
              : `Here is what the team did. Open anyone to read their day, and why each thing matters.`}
          </p>
        </div>
        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-5 py-4 sm:px-6">
          {people.length > 0 && (
            <ul className="m-0 flex list-none flex-col gap-2 p-0" aria-label="What each person did">
              {people.map((who, i) => (
                <PersonCard
                  key={who}
                  who={who}
                  index={i}
                  entries={story.filter((s) => s.who === who)}
                  moments={moments.filter((m) => m.who === who)}
                  counts={summary.filter((s) => s.who === who)}
                  open={shown === who}
                  onToggle={() => setShown((s) => (s === who ? null : who))}
                />
              ))}
            </ul>
          )}
          {waiting.length > 0 && (
            <div className="rounded-xl border border-dashed px-3.5 py-2.5 text-sm">
              <button type="button" className="flex w-full items-center justify-between gap-2 text-left" onClick={() => setShowWaiting((v) => !v)} aria-expanded={showWaiting}>
                <span>
                  <span className="font-medium">{waiting.length} {waiting.length === 1 ? 'thing is' : 'things are'} waiting</span>
                  <span className="text-muted-foreground"> on an earlier step</span>
                </span>
                <ChevronDown className={cn('size-4 shrink-0 text-muted-foreground transition-transform', showWaiting && 'rotate-180')} aria-hidden />
              </button>
              {showWaiting && (
                <>
                  <p className="m-0 mt-1.5 text-xs text-muted-foreground">Each one needs something done first (a delivery needs its order). It happens once that is done.</p>
                  <ul className="m-0 mt-1.5 flex list-none flex-col gap-1 p-0 text-xs">
                    {waiting.map((w, i) => (
                      <li key={i}><span className="font-medium">{w.who}:</span> {w.what}</li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}
          <div className="rounded-xl bg-primary/10 p-3.5 ring-1 ring-primary/30">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-semibold">Your part today</span>
              <span className="rounded-full bg-primary px-2 py-0.5 text-xs font-bold text-primary-foreground tabular-nums">{todo.length}</span>
            </div>
            {todo.length === 0 ? (
              <p className="m-0 mt-1 text-sm text-muted-foreground">Nothing for you today. Look around.</p>
            ) : (
              <ul className="m-0 mt-2 flex list-none flex-col gap-1 p-0 text-sm">
                {todo.slice(0, 3).map((f) => (
                  <li key={f.id} className="flex gap-2"><span aria-hidden className="text-primary">•</span><span>{f.what}</span></li>
                ))}
                {todo.length > 3 && <li className="text-xs text-muted-foreground">and {todo.length - 3} more in For you</li>}
              </ul>
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center justify-end gap-2 border-t px-5 py-3 sm:px-6">
          <button type="button" onClick={onClose} className="h-9 rounded-lg px-3 text-sm text-muted-foreground hover:bg-muted hover:text-foreground">
            {todo.length ? 'Later' : 'Close'}
          </button>
          {todo.length > 0 && (
            <Link to={todo[0].page} onClick={onClose} className="inline-flex h-9 items-center gap-1 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90">
              Start <ChevronRight className="size-4" aria-hidden />
            </Link>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}


function PersonCard({ who, index, entries, moments, counts, open, onToggle }: {
  who: string
  index: number
  entries: StoryEntry[]
  moments: Moment[]
  counts: { kind: string; count: number; short?: string }[]
  open: boolean
  onToggle: () => void
}) {
  const show = useOpen(400 + index * 180)
  const cast = CAST[who]
  const name = who === 'Owner' ? 'You' : who
  const line = entries.length
    ? headline(entries)
    : counts.map((c) => `${c.count} ${c.short ?? c.kind.replace(/_/g, ' ')}`).join(' · ')
  const first = moments[0] ? didIt(moments[0].kind, moments[0].what) : null
  const said = new Set<string>()
  return (
    <li
      className="rounded-xl border bg-background transition-[transform,opacity] duration-500 ease-out"
      style={{ transform: show ? 'none' : 'translateY(10px)', opacity: show ? 1 : 0 }}
    >
      <button type="button" onClick={onToggle} aria-expanded={open} className="flex w-full items-start gap-3 rounded-xl p-3 text-left hover:bg-muted/50" disabled={!entries.length}>
        <span className={cn('flex size-9 shrink-0 items-center justify-center rounded-full text-sm font-bold text-white', cast?.tone)} aria-hidden>
          {who.slice(0, 1)}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-semibold">
            {name} <span className="font-normal text-muted-foreground">· {cast?.role}</span>
          </span>
          <span className="block text-sm text-foreground/80">{line}</span>
          {first && !open && <span className="mt-0.5 block truncate text-xs text-muted-foreground">{first}</span>}
        </span>
        {entries.length > 0 && (
          <span className="mt-0.5 inline-flex shrink-0 items-center gap-0.5 rounded-full border px-2 py-0.5 text-xs font-medium text-foreground/80">
            <span className="hidden sm:inline">{open ? 'Hide' : `What ${name === 'You' ? 'you' : name} did`}</span>
            <ChevronDown className={cn('size-4 transition-transform', open && 'rotate-180')} aria-hidden />
          </span>
        )}
      </button>
      {open && (
        <div className="flex flex-col gap-3 border-t px-3.5 pt-3 pb-3.5 text-sm">
          <p className="m-0 text-muted-foreground">{ROLE_STORY[who]}</p>
          {storyLines(entries).map(({ place, lines }) => (
            <div key={place}>
              <div className="mb-1 text-xs font-semibold tracking-wide text-muted-foreground uppercase">{place}</div>
              <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
                {lines.map((l, i) => {
                  const Icon = KIND[l.kind]?.icon ?? CheckCircle2
                  const why = !said.has(l.kind) && WHY[l.kind]
                  said.add(l.kind)
                  return (
                    <li key={i} className="flex gap-2">
                      <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
                      <span className="min-w-0">
                        <span className="block">{l.text}</span>
                        {why && <span className="block text-xs text-muted-foreground">{why}</span>}
                      </span>
                    </li>
                  )
                })}
              </ul>
            </div>
          ))}
        </div>
      )}
    </li>
  )
}

/** Green Villa handed over: the cast and the run's numbers roll. */
export function EndCredits({ finale, role, onClose }: { finale: NonNullable<DaysPassed['finale']>; role: string; onClose: () => void }) {
  const roll = useOpen(300)
  useSounds([{ id: 'music-credits', volume: 0.5 }, { id: 'credits', delay: 1400 }], 'credits')
  const k = (kind: string) => finale.by_kind[kind] ?? 0
  const numbers: [string, number][] = [
    ['days on site', finale.days],
    ['entries made', finale.entries],
    ['deliveries received', k('delivery')],
    ['orders placed', k('order')],
    ['problems fixed', k('issue_resolve')],
    ['supplier payments', k('supplier_payment')],
    ['wage weeks paid', k('wage_pay')],
  ]
  return createPortal(
    <div className="fixed inset-0 z-[95] overflow-hidden text-white" style={{ backgroundColor: INK }} role="dialog" aria-modal="true" aria-label="Green Villa handed over">
      <div aria-hidden className="absolute inset-x-0 top-0 h-1.5 bg-[repeating-linear-gradient(135deg,#1a1d21_0_8px,#facc15_8px_16px)]" />
      <div
        className="absolute inset-x-0 top-0 flex flex-col items-center gap-14 px-6 text-center ease-linear"
        style={{ transform: roll ? 'translateY(-100%)' : 'translateY(100vh)', transition: roll && !prefersReducedMotion() ? 'transform 26s linear' : 'none' }}
      >
        <div className="flex flex-col items-center gap-3">
          <span className="font-mono text-[12px] tracking-[0.14em] text-white/50 uppercase">Handed over on day {finale.days}</span>
          <h2 className="m-0 font-brand text-[clamp(56px,10vw,128px)] leading-none">Green Villa</h2>
          <span className="h-[3px] w-40 bg-primary" />
        </div>
        <Credit title="Starring">
          {Object.entries(CAST).map(([who, c]) => (
            <CreditRow key={who} left={c.role} right={who === 'Owner' ? 'The owner' : who} />
          ))}
          <CreditRow left="And" right={`You, as the ${role.toLowerCase().replace('_', ' ')}`} />
        </Credit>
        <Credit title="By the numbers">
          {numbers.filter(([, n]) => n > 0).map(([label, n]) => <CreditRow key={label} left={label} right={n.toLocaleString('en-IN')} />)}
        </Credit>
        <Credit title="Suppliers">
          {['Malabar Cements Agency', 'Kerala Steels', 'Periyar Sand & Aggregates', 'Thrissur Blocks', 'Joy Tiling Works'].map((s) => <CreditRow key={s} left="" right={s} />)}
        </Credit>
        <div className="flex flex-col items-center gap-2 pb-[40vh]">
          <span className="text-white/50">Kept by</span>
          <span className="font-brand text-4xl">Mesiri</span>
        </div>
      </div>
      <SkipButton onSkip={onClose} label="Close" />
    </div>,
    document.body,
  )
}

function Credit({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex w-full max-w-md flex-col gap-2">
      <h3 className="m-0 mb-2 font-mono text-[12px] tracking-[0.14em] text-primary uppercase">{title}</h3>
      {children}
    </section>
  )
}

function CreditRow({ left, right }: { left: string; right: string }) {
  return (
    <div className="grid grid-cols-2 gap-6 text-[17px]">
      <span className="text-right text-white/55 capitalize">{left}</span>
      <span className="text-left font-semibold">{right}</span>
    </div>
  )
}

/** A chapter's title card in the guided project: its number, its name, its first line. */
export function EpisodeCard({ number, of, title, line, film, onDone }: { number: number; of: number; title: string; line?: string; film?: string; onDone: () => void }) {
  const open = useOpen()
  const said = `chapter-${title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')}`
  useSounds([{ id: 'sfx-boom', volume: 0.5 }, { id: said, delay: 250 }], `chapter-${number}`)
  React.useEffect(() => {
    // The card stays until its line is said (UX-73), never less than before.
    const t = window.setTimeout(onDone, Math.max(2900, sceneSoundOn() ? soundMs(said) + 900 : 0))
    return () => window.clearTimeout(t)
  }, [onDone, said])
  return createPortal(
    <div
      className="fixed inset-0 z-[95] grid cursor-pointer place-items-center text-white"
      style={{ backgroundColor: INK, clipPath: open ? 'inset(0 0 0 0)' : 'inset(50% 0 50% 0)', transition: 'clip-path 550ms cubic-bezier(.7,0,.2,1)' }}
      onClick={onDone}
      role="status"
      aria-live="assertive"
    >
      <div className="grid max-w-[90vw] justify-items-start gap-4 px-6">
        <span className="font-mono text-[12px] tracking-[0.14em] text-white/55 uppercase">Chapter {number} of {of}{film ? ` · ${film}` : ''}</span>
        <RisingTitle text={title} show={open} delay={250} className="text-[clamp(44px,9vw,120px)]" />
        {line && open && <Ink text={line} writing delay={700} className="text-[clamp(16px,2vw,22px)] text-white/75" />}
        <span className="h-[3px] bg-primary transition-[width] duration-[2200ms] ease-in-out" style={{ width: open ? '100%' : '0%' }} aria-hidden />
      </div>
      <SkipButton onSkip={onDone} />
    </div>,
    document.body,
  )
}

/** UX-72: who each role plays in the cast (lib/sandbox SANDBOX_ROLES: the owner is the person themselves). */
const ROLE_IS: Record<string, string> = { ADMIN: 'Owner', PROJECT_MANAGER: 'Anil', SITE_ENGINEER: 'Ravi', FINANCE: 'Meera' }
const CAST_ORDER = ['Owner', 'Anil', 'Ravi', 'Meera'] as const

/**
 * Coming into the sample company. New: its name rises over the site at night, the sun comes up on the cast (the
 * person's own part marked "You"), then "Day 1" and its date. Opened again: the name, then the day it is on.
 * Skippable (Skip, Esc); the caller plays nothing with reduced motion.
 */
export function OpeningScene({ kind, name, role, day, date, onDone }: {
  kind: 'new' | 'back'
  name: string
  role: string
  day: number | null
  date: string | null
  onDone: () => void
}) {
  const [phase, setPhase] = React.useState<'title' | 'cast' | 'day'>('title')
  const open = useOpen(150)
  const done = React.useRef(false)
  const finish = React.useCallback(() => {
    if (done.current) return
    done.current = true
    onDone()
  }, [onDone])
  const me = ROLE_IS[role] ?? 'Owner'
  // UX-73: with sound on, each part lasts as long as its line (never shorter than without).
  const [voiced] = React.useState(sceneSoundOn)
  const castLine = `open-cast-${role in ROLE_IS ? role : 'ADMIN'}`
  React.useEffect(() => {
    const said = (id: string, lead: number, rest: number, least: number) => Math.max(least, voiced ? lead + soundMs(id) + rest : 0)
    const title = kind === 'new' ? said('open-title', 600, 500, 2700) : said('open-back', 300, 400, 1900)
    const cast = kind === 'new' ? said(castLine, 300, 700, 5400) : 0
    const day = kind === 'new' ? said('open-day', 200, 900, 2500) : 2300
    const plan: [number, () => void][] = kind === 'new'
      ? [[title, () => setPhase('cast')], [title + cast, () => setPhase('day')], [title + cast + day, finish]]
      : [[title, () => setPhase('day')], [title + day, finish]]
    const timers = plan.map(([ms, fn]) => window.setTimeout(fn, ms))
    return () => timers.forEach((t) => window.clearTimeout(t))
  }, [kind, finish, voiced, castLine])
  useSounds(
    phase === 'title'
      ? kind === 'new'
        ? [{ id: 'sfx-boom', volume: 0.55 }, { id: 'sfx-night', volume: 0.3, loop: true, delay: 300 }, { id: 'open-title', delay: 600 }]
        : [{ id: 'sfx-whoosh', volume: 0.45 }, { id: 'open-back', delay: 300 }]
      : phase === 'cast'
        ? [{ id: 'sfx-dawn', volume: 0.4 }, { id: castLine, delay: 300 }]
        : kind === 'new' ? [{ id: 'open-day', delay: 200 }] : [{ id: 'sfx-dawn', volume: 0.4 }],
    `opening-${kind}-${phase}`,
  )
  // The cast in the order the narrator names them: the others, then the person's own part.
  const order = [...CAST_ORDER.filter((w) => w !== me), me]
  const openingDay = day ?? 1
  const openingTitle = dayTitle(openingDay)
  return createPortal(
    <div className="fixed inset-0 z-[95] overflow-hidden text-white" style={{ backgroundColor: INK }} role="status" aria-live="polite" aria-label={`${name}, ${openingTitle}`}>
      <Sky phase={phase === 'title' ? 'night' : 'dawn'} />
      <div className="relative mx-auto flex h-full max-w-3xl flex-col justify-center gap-5 px-6 pb-[26vh] [text-shadow:0_1px_12px_rgba(0,0,0,.45)]">
        {phase === 'title' && (
          <>
            <span className="font-mono text-[12px] tracking-[0.14em] text-white/60 uppercase">{kind === 'new' ? 'Your sample company' : 'Back on site'}</span>
            <RisingTitle text={name} show={open} delay={200} className="text-[clamp(44px,9vw,120px)]" />
            {kind === 'new' && open && (
              <Ink text="Two projects on site, and Green Villa's last two months, to the handover." writing delay={1100} className="text-[clamp(16px,2vw,22px)] text-white/75" />
            )}
          </>
        )}
        {phase === 'cast' && (
          <>
            <span className="font-mono text-[12px] tracking-[0.14em] text-white/60 uppercase">Starring</span>
            <ul className="m-0 grid list-none grid-cols-2 gap-2.5 p-0 sm:grid-cols-4">
              {order.map((who, i) => <CastCard key={who} who={who} you={who === me} index={i} voiced={voiced} />)}
            </ul>
            <Ink text={`You play the ${CAST[me].role.toLowerCase()}. The others do their part each day.`} writing delay={voiced ? 6200 : 1300} className="text-[clamp(15px,1.8vw,20px)] text-white/80" />
          </>
        )}
        {phase === 'day' && (
          <>
            <span className="font-mono text-[12px] tracking-[0.14em] text-white/60 uppercase">Morning at {name}</span>
            <RisingTitle text={openingTitle} show delay={100} className={dayTitleSize(openingDay, 'text-[clamp(56px,12vw,150px)]', 'text-[clamp(40px,8vw,96px)]')} />
            {date && <Ink text={dayName(date)} writing delay={350} className="text-[clamp(16px,2.2vw,24px)] text-white/80" />}
          </>
        )}
        <span
          className="h-[3px] bg-primary transition-[width] ease-in-out"
          style={{ width: phase === 'day' ? '100%' : phase === 'cast' ? '55%' : open ? '15%' : '0%', transitionDuration: '1600ms' }}
          aria-hidden="true"
        />
      </div>
      <SkipButton onSkip={finish} />
    </div>,
    document.body,
  )
}

function CastCard({ who, you, index, voiced }: { who: string; you: boolean; index: number; voiced: boolean }) {
  // With the narrator, each card comes as it is named.
  const show = useOpen(voiced ? 1250 + index * 1350 : 200 + index * 320)
  const cast = CAST[who]
  return (
    <li
      className={cn('flex items-center gap-2.5 rounded-xl bg-black/35 p-3 ring-1 backdrop-blur-sm transition-[transform,opacity] duration-500 ease-out', you ? 'ring-primary' : 'ring-white/15')}
      style={{ transform: show ? 'none' : 'translateY(16px)', opacity: show ? 1 : 0 }}
    >
      <span className={cn('flex size-9 shrink-0 items-center justify-center rounded-full text-sm font-bold text-white', cast.tone)} aria-hidden>
        {who.slice(0, 1)}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5 text-sm font-semibold">
          <span className="truncate">{who}</span>
          {you && <span className="shrink-0 rounded-full bg-primary px-1.5 py-px text-[10px] font-bold text-primary-foreground uppercase">You</span>}
        </span>
        <span className="block truncate text-xs text-white/60">{who === 'Owner' ? 'The company' : cast.role}</span>
      </span>
    </li>
  )
}
