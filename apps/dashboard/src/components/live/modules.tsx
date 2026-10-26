import * as React from 'react'
import { flushSync } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { Activity, AlertCircle, ArrowRight, Boxes, HardHat, type LucideIcon } from 'lucide-react'
import type { ModuleKey } from '@/lib/modules'
import { prefersReducedMotion } from '@/lib/timeline'
import { cn } from '@/lib/utils'
import { CountTo, Ink } from './ink'

// Where the Live report's facts go next (WEB-37): every line on the report
// is also a record in a module (a headcount in Labour, a delivery in
// Materials, an issue in Issues, a work item in the Site log). The rail
// shows those modules; each fact travels on to its own, and clicking one
// opens it with a cinematic cut. Navigation only: the modules are untouched.

export type ModuleSection = 'labour' | 'work' | 'materials' | 'issues'

export interface LiveModule {
  section: ModuleSection
  name: string
  /** What the module keeps, in a few words. */
  keeps: string
  path: string
  icon: LucideIcon
  module?: ModuleKey
}

export const LIVE_MODULES: LiveModule[] = [
  { section: 'labour', name: 'Labour', keeps: 'Attendance and workers', path: '/labour', icon: HardHat, module: 'labour' },
  { section: 'work', name: 'Site log', keeps: 'Work done, day by day', path: '/site-log', icon: Activity },
  { section: 'materials', name: 'Materials', keeps: 'Stock in and out', path: '/materials', icon: Boxes, module: 'materials' },
  { section: 'issues', name: 'Issues', keeps: 'Open problems on site', path: '/issues', icon: AlertCircle },
]

export const moduleOf = (section: ModuleSection) => LIVE_MODULES.find((m) => m.section === section)!

export function ModuleRail({
  counts,
  last,
  pulsing,
  enabled,
  nodeRef,
  onOpen,
  className,
}: {
  counts: Record<ModuleSection, number>
  /** The last line each module received, shown under its name. */
  last: Partial<Record<ModuleSection, string>>
  pulsing: Set<ModuleSection>
  enabled: (m: LiveModule) => boolean
  nodeRef: (section: ModuleSection, el: HTMLElement | null) => void
  onOpen: (m: LiveModule, el: HTMLElement, line?: string) => void
  className?: string
}) {
  return (
    <nav aria-label="Where it goes" className={className}>
      <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground">Where it goes</span>
      <ul className="m-0 mt-3 grid list-none grid-cols-2 gap-px bg-foreground/15 p-0 sm:grid-cols-4 xl:grid-cols-1">
        {LIVE_MODULES.map((m) => {
          const on = enabled(m)
          const pulse = pulsing.has(m.section) && !prefersReducedMotion()
          const Icon = m.icon
          return (
            <li key={m.section} className="bg-background">
              <button
                type="button"
                ref={(el) => nodeRef(m.section, el)}
                disabled={!on}
                onClick={(e) => onOpen(m, e.currentTarget, last[m.section])}
                className={cn(
                  'group grid w-full gap-1 px-3.5 py-3 text-left transition-colors duration-300',
                  on ? 'hover:bg-foreground hover:text-background' : 'cursor-default opacity-45',
                )}
                style={pulse ? { animation: 'live-glow 2.4s ease-out both' } : undefined}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-2 text-[14px] font-semibold">
                    <span
                      className="grid size-7 place-items-center rounded-full border border-current"
                      style={pulse ? { animation: 'live-ring 900ms ease-out 2' } : undefined}
                    >
                      <Icon className="size-3.5" aria-hidden="true" />
                    </span>
                    {m.name}
                  </span>
                  <span
                    className="inline-block text-[18px] font-semibold tabular-nums"
                    style={pulse ? { animation: 'live-slam 700ms cubic-bezier(.2,.9,.3,1.2) both' } : undefined}
                  >
                    <CountTo value={counts[m.section]} />
                  </span>
                </span>
                <span className="min-h-[1.4em] truncate text-[12.5px] text-current opacity-60">
                  {!on ? 'Not switched on' : last[m.section] ? (
                    <Ink key={last[m.section]} text={`+ ${last[m.section]}`} writing={pulse} />
                  ) : (
                    m.keeps
                  )}
                </span>
                {on && (
                  <span className="flex items-center gap-1 font-mono text-[10.5px] uppercase tracking-[0.08em] opacity-0 transition-opacity duration-200 group-hover:opacity-100 group-focus-visible:opacity-100">
                    Open <ArrowRight className="size-3" aria-hidden="true" />
                  </span>
                )}
              </button>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}

interface Cut {
  from: DOMRect
  to: string
  title: string
  kicker: string
  line?: string
}

const OPEN_MS = 650
const HOLD_MS = 650
const REVEAL_MS = 750

type StartViewTransition = (callback: () => void) => { ready: Promise<void> }

/** Opens a module the cinematic way: the clicked thing grows to fill the
 * screen, the module's name rises letter by letter, then the module's page
 * irises open through it. Reduced motion: it simply goes. */
export function useCinematicGo(): { go: (cut: Cut) => void; overlay: React.ReactNode } {
  const navigate = useNavigate()
  const [cut, setCut] = React.useState<Cut | null>(null)

  const go = React.useCallback(
    (next: Cut) => {
      if (prefersReducedMotion()) {
        navigate(next.to)
        return
      }
      setCut(next)
      window.setTimeout(() => {
        const start = (document as Document & { startViewTransition?: StartViewTransition }).startViewTransition
        if (!start) {
          navigate(next.to)
          return
        }
        const transition = start.call(document, () => flushSync(() => navigate(next.to)))
        transition.ready.then(() => {
          const r = Math.hypot(window.innerWidth, window.innerHeight) / 2 + 20
          document.documentElement.animate(
            { clipPath: [`circle(0px at 50% 50%)`, `circle(${r}px at 50% 50%)`] },
            { duration: REVEAL_MS, easing: 'cubic-bezier(.7,0,.2,1)', pseudoElement: '::view-transition-new(root)' },
          )
        })
      }, OPEN_MS + HOLD_MS)
    },
    [navigate],
  )

  return { go, overlay: cut ? <CutOverlay cut={cut} /> : null }
}

function CutOverlay({ cut }: { cut: Cut }) {
  const [open, setOpen] = React.useState(false)
  React.useLayoutEffect(() => {
    const frame = requestAnimationFrame(() => requestAnimationFrame(() => setOpen(true)))
    return () => cancelAnimationFrame(frame)
  }, [])
  const { from } = cut
  const inset = `inset(${from.top}px ${window.innerWidth - from.right}px ${window.innerHeight - from.bottom}px ${from.left}px)`
  return (
    <div
      aria-live="assertive"
      className="fixed inset-0 z-[70] grid place-items-center bg-foreground text-background"
      style={{
        clipPath: open ? 'inset(0px 0px 0px 0px)' : inset,
        transition: `clip-path ${OPEN_MS}ms cubic-bezier(.7,0,.2,1)`,
      }}
    >
      <div className="grid max-w-[90vw] justify-items-start gap-4 px-6">
        <span className="font-mono text-[12px] uppercase tracking-[0.12em] opacity-60">{cut.kicker}</span>
        <h2 className="m-0 flex overflow-hidden font-brand text-[clamp(52px,11vw,148px)] leading-[0.95] tracking-[-0.02em]" aria-label={cut.title}>
          {[...cut.title].map((ch, i) => (
            <span
              key={i}
              aria-hidden="true"
              className="inline-block whitespace-pre transition-[transform,opacity] duration-500 ease-out"
              style={{
                transform: open ? 'none' : 'translateY(105%)',
                opacity: open ? 1 : 0,
                transitionDelay: `${OPEN_MS * 0.45 + i * 35}ms`,
              }}
            >
              {ch}
            </span>
          ))}
        </h2>
        {cut.line && open && (
          <Ink text={cut.line} writing delay={OPEN_MS * 0.6} className="text-[clamp(16px,2vw,22px)] opacity-80" />
        )}
        <span
          className="h-[3px] bg-primary transition-[width] ease-in-out"
          style={{ width: open ? '100%' : '0%', transitionDuration: `${OPEN_MS + HOLD_MS}ms` }}
          aria-hidden="true"
        />
      </div>
    </div>
  )
}
