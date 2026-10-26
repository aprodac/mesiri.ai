import * as React from 'react'
import { cn } from '@/lib/utils'

// The onboarding conversation's building blocks (SS-18): a Swiss grid on the
// page's own white, a narrow time column, what the site sent on the left and
// what Mesiri made of it on the right, hairlines between exchanges. Used by
// the signup intro (an example) and the welcome screen (the owner's own
// first update). Everything reveals off one clock (lib/timeline.ts) passed
// down as `now`; Infinity shows everything at rest.

const NowContext = React.createContext<number>(Infinity)

export function Conversation({ now, className, children }: { now: number; className?: string; children: React.ReactNode }) {
  return (
    <NowContext.Provider value={now}>
      <div className={cn('@container', className)}>{children}</div>
    </NowContext.Provider>
  )
}

function useSeen(at: number | undefined): boolean {
  const now = React.useContext(NowContext)
  return at === undefined || now >= at
}

const EASE = 'ease-[cubic-bezier(.2,.7,.2,1)] motion-reduce:transition-none'

/** Fades and lifts its children in at `at` ms. */
export function Reveal({
  at,
  className,
  children,
}: {
  at?: number
  className?: string
  children: React.ReactNode
}) {
  const seen = useSeen(at)
  return (
    <div className={cn('transition-[opacity,transform] duration-600', EASE, !seen && 'translate-y-2 opacity-0', className)}>
      {children}
    </div>
  )
}

/** A hairline drawn left to right. `strong` is the ink rule between sections. */
export function Rule({ at, strong, className }: { at?: number; strong?: boolean; className?: string }) {
  const seen = useSeen(at)
  return (
    <div
      aria-hidden="true"
      className={cn(
        'h-px origin-left transition-transform duration-1000 ease-[cubic-bezier(.6,0,.2,1)] motion-reduce:transition-none',
        strong ? 'bg-foreground' : 'bg-border',
        !seen && 'scale-x-0',
        className,
      )}
    />
  )
}

/** Text that arrives word by word, `step` ms apart from `at`. */
export function Words({ text, at, step = 70, className }: { text: string; at?: number; step?: number; className?: string }) {
  const now = React.useContext(NowContext)
  return (
    <span className={className}>
      {text.split(' ').map((word, i) => (
        <React.Fragment key={i}>
          {i > 0 && ' '}
          <span
            className={cn(
              'inline-block transition-[opacity,transform] duration-450',
              EASE,
              at !== undefined && now < at + i * step && 'translate-y-[0.35em] opacity-0',
            )}
          >
            {word}
          </span>
        </React.Fragment>
      ))}
    </span>
  )
}

/** The small uppercase mono label used for times and column heads. */
export function Label({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <span className={cn('font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground tabular-nums', className)}>
      {children}
    </span>
  )
}

const GRID = '@2xl:grid-cols-[72px_minmax(0,5fr)_minmax(24px,1fr)_minmax(0,6fr)]'

/** One exchange: time · from site · Mesiri. Narrow, the two sides stack with
 * Mesiri's indented, so they stay on their sides. */
export function Exchange({
  time,
  site,
  mesiri,
  className,
}: {
  time?: React.ReactNode
  site?: React.ReactNode
  mesiri?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn('grid grid-cols-1 gap-y-5 py-7 @2xl:gap-y-0', GRID, className)}>
      <div className="@2xl:col-start-1">{time}</div>
      <div className="min-w-0 @2xl:col-start-2">{site}</div>
      <div className="min-w-0 pl-[10%] @2xl:col-start-4 @2xl:pl-0">{mesiri}</div>
    </div>
  )
}

/** The column heads over the exchanges. */
export function ExchangeHeads({ at }: { at?: number }) {
  return (
    <Reveal at={at}>
      <div className={cn('grid grid-cols-1 py-3', GRID)}>
        <Label className="hidden @2xl:block">Time</Label>
        <Label className="@2xl:col-start-2">From site</Label>
        <Label className="hidden @2xl:col-start-4 @2xl:block">Mesiri</Label>
      </div>
    </Reveal>
  )
}

/** Something Mesiri understood: a big value, what it is, and a detail. */
export function Fact({
  at,
  value,
  big,
  title,
  detail,
}: {
  at?: number
  value: React.ReactNode
  /** Numbers set large; words a size down. */
  big?: boolean
  title: React.ReactNode
  detail?: React.ReactNode
}) {
  return (
    <Reveal at={at}>
      <div className="grid grid-cols-[minmax(84px,120px)_minmax(0,1fr)] items-baseline gap-4 border-b py-3">
        <span
          className={cn(
            'font-semibold leading-none tabular-nums',
            big ? 'text-[44px] tracking-[-0.03em]' : 'text-[22px] leading-tight tracking-[-0.02em]',
          )}
        >
          {value}
        </span>
        <span className="min-w-0">
          <span className="block font-semibold">{title}</span>
          {detail && <span className="text-[13px] text-muted-foreground">{detail}</span>}
        </span>
      </div>
    </Reveal>
  )
}

/** A voice note's waveform; `played` 0 → 1 inks it in from the left. */
export function Waveform({ played, className }: { played: number; className?: string }) {
  const bars = React.useMemo(() => {
    const count = 56
    return Array.from({ length: count }, (_, i) => {
      const edge = i < 3 || i > count - 4 ? 0.35 : 1
      return 4 + Math.abs(Math.sin(i * 0.61) * 14 + Math.sin(i * 1.7) * 8) * edge
    })
  }, [])
  const draw = (stroke: string) => (
    <svg viewBox="0 0 440 36" preserveAspectRatio="none" className="block h-9 w-full" aria-hidden="true">
      {bars.map((h, i) => {
        const x = (440 / bars.length) * (i + 0.5)
        return <line key={i} x1={x} x2={x} y1={18 - h / 2} y2={18 + h / 2} strokeWidth={2.4} strokeLinecap="round" className={stroke} />
      })}
    </svg>
  )
  return (
    <div className={cn('relative', className)}>
      {draw('stroke-border')}
      <div className="absolute inset-y-0 left-0 overflow-hidden" style={{ width: `${played * 100}%` }}>
        <div className="h-full" style={{ width: played > 0 ? `${100 / played}%` : '100%' }}>
          {draw('stroke-foreground')}
        </div>
      </div>
    </div>
  )
}

/** Words arriving one by one, with CSS only (no clock needed here). */
export function WordsIn({ text, className, lang }: { text: string; className?: string; lang?: string }) {
  return (
    <p className={cn('m-0', className)} lang={lang}>
      {text.split(' ').map((word, i) => (
        <React.Fragment key={i}>
          {i > 0 && ' '}
          <span
            className="inline-block animate-in fade-in slide-in-from-bottom-1 fill-mode-both duration-300 motion-reduce:animate-none"
            style={{ animationDelay: `${Math.min(i, 40) * 40}ms` }}
          >
            {word}
          </span>
        </React.Fragment>
      ))}
    </p>
  )
}
