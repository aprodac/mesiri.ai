import * as React from 'react'
import { cn } from '@/lib/utils'

// The Live report's entrance for each update (WEB-41): it comes up full
// size in the middle of the screen, the page dimmed behind it, holds a beat
// with its number slamming in, then shrinks and flies into its exact place
// on the report. One card, moved by transform only: it is laid out at the
// centre and scaled from the chip it came from, and to the line it lands on.

export interface SpotlightFact {
  /** "Manpower", "Work done", "Photo", … */
  kind: string
  main: string
  sub?: string | null
  value?: string | null
  /** A correction: what it said before, struck out above the new value. */
  was?: string | null
  image?: string | null
  warn?: boolean
}

export const SPOT_IN_MS = 650
export const SPOT_HOLD_MS = 1500
export const SPOT_OUT_MS = 750
export const SPOT_MS = SPOT_IN_MS + SPOT_HOLD_MS + SPOT_OUT_MS

type Stage = 'from' | 'center' | 'to'

function place(card: DOMRect, at: DOMRect): string {
  // One scale that fits the card inside the place (words never stretch),
  // centred on it, so it lands as big as the line it becomes.
  const scale = Math.max(0.02, Math.min(at.width / card.width, at.height / card.height))
  const x = at.left + (at.width - card.width * scale) / 2
  const y = at.top + (at.height - card.height * scale) / 2
  return `translate(${x - card.left}px, ${y - card.top}px) scale(${scale})`
}

export function Spotlight({ fact, from, to }: { fact: SpotlightFact; from: DOMRect; to: DOMRect }) {
  const card = React.useRef<HTMLDivElement>(null)
  const [stage, setStage] = React.useState<Stage>('from')
  const [box, setBox] = React.useState<DOMRect | null>(null)

  React.useLayoutEffect(() => {
    if (card.current) setBox(card.current.getBoundingClientRect())
  }, [])
  React.useEffect(() => {
    if (!box) return
    const timers = [
      window.setTimeout(() => setStage('center'), 30),
      window.setTimeout(() => setStage('to'), 30 + SPOT_IN_MS + SPOT_HOLD_MS),
    ]
    return () => timers.forEach(window.clearTimeout)
  }, [box])

  const transform = !box ? undefined : stage === 'from' ? place(box, from) : stage === 'to' ? place(box, to) : 'none'
  const ms = stage === 'to' ? SPOT_OUT_MS : SPOT_IN_MS

  return (
    <div className="pointer-events-none fixed inset-0 z-[55]" aria-live="polite" aria-label={`${fact.kind}: ${[fact.value, fact.main].filter(Boolean).join(' ')}`}>
      <div
        aria-hidden="true"
        className="absolute inset-0 bg-background/75 backdrop-blur-[3px] transition-opacity"
        style={{ opacity: stage === 'center' ? 1 : 0, transitionDuration: `${ms}ms` }}
      />
      <div className="absolute inset-0 grid place-items-center px-4">
        <div
          ref={card}
          aria-hidden="true"
          className={cn(
            'grid w-[min(760px,92vw)] gap-4 border bg-white p-8 text-[#1a1d21] shadow-[0_40px_90px_-30px_rgba(0,0,0,0.5)] sm:p-10',
            fact.warn ? 'border-red-700/60' : 'border-black/15',
          )}
          style={{
            transformOrigin: '0 0',
            transform,
            opacity: !box ? 0 : stage === 'to' ? 0.15 : 1,
            visibility: box ? 'visible' : 'hidden',
            transition: box
              ? `transform ${ms}ms cubic-bezier(.7,0,.2,1), opacity ${ms}ms ${stage === 'to' ? 'ease-in' : 'ease-out'}`
              : undefined,
          }}
        >
          <span className={cn('font-mono text-[12px] uppercase tracking-[0.12em]', fact.warn ? 'text-red-700' : 'text-black/50')}>
            {fact.kind}
          </span>
          {fact.image ? (
            <img src={fact.image} alt="" className="max-h-[52vh] w-full object-cover" />
          ) : (
            fact.value && (
              <>
              {fact.was && (
                <span className="flex items-baseline gap-3 text-[clamp(22px,3vw,34px)] text-black/45">
                  <span className="font-mono text-[12px] uppercase tracking-[0.12em]">was</span>
                  <s className="decoration-red-700 decoration-[3px]">{fact.was}</s>
                </span>
              )}
              <span
                className={cn('inline-block justify-self-start font-brand text-[clamp(64px,11vw,132px)] leading-[0.9] tabular-nums tracking-[-0.02em]', fact.warn && 'text-red-700')}
                style={{
                  animation: stage === 'center' ? `live-slam 800ms ${SPOT_IN_MS * 0.6}ms cubic-bezier(.2,.9,.3,1.2) both, live-marker 600ms ${SPOT_IN_MS}ms ease-out both` : undefined,
                  backgroundImage: 'linear-gradient(transparent 60%, color-mix(in srgb, var(--primary) 30%, transparent) 60%)',
                  backgroundRepeat: 'no-repeat',
                  backgroundSize: stage === 'from' ? '0% 100%' : undefined,
                }}
              >
                {fact.value}
              </span>
              </>
            )
          )}
          <span className="text-[clamp(24px,3.4vw,40px)] font-semibold leading-tight">{fact.main}</span>
          {fact.sub && <span className="text-[clamp(15px,1.8vw,20px)] leading-snug text-black/55">{fact.sub}</span>}
        </div>
      </div>
    </div>
  )
}
