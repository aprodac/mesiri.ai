import * as React from 'react'

/** How often the onboarding conversation's clock moves (SS-18). */
const TICK_MS = 50

export function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

/**
 * Milliseconds since the sequence started, for the onboarding conversation
 * (SS-18): every reveal, the waveform and the count-up read this one clock,
 * so nothing drifts. Restarts whenever `run` changes; Infinity (everything
 * shown) once past `endMs`, when `run` is null, or with reduced motion.
 */
export function useTimeline(endMs: number, run: number | null): number {
  const still = run === null || prefersReducedMotion()
  // The clock remembers which run it belongs to, so the first render of a
  // new run never reads the last run's "finished" (that skipped scenes).
  const [clock, setClock] = React.useState<{ run: number | null; now: number }>({ run, now: still ? Infinity : 0 })

  React.useEffect(() => {
    if (still) {
      setClock({ run, now: Infinity })
      return
    }
    const start = performance.now()
    setClock({ run, now: 0 })
    const timer = window.setInterval(() => {
      const elapsed = performance.now() - start
      setClock({ run, now: elapsed >= endMs ? Infinity : elapsed })
      if (elapsed >= endMs) window.clearInterval(timer)
    }, TICK_MS)
    return () => window.clearInterval(timer)
  }, [endMs, run, still])

  if (clock.run !== run) return still ? Infinity : 0
  return clock.now
}

/** 0 → 1 over `ms` from `at`, eased out; for count-ups and the waveform. */
export function progress(now: number, at: number, ms: number): number {
  if (now >= at + ms) return 1
  if (now <= at) return 0
  const p = (now - at) / ms
  return 1 - Math.pow(1 - p, 3)
}

/**
 * A slideshow of scenes (SS-18): which scene is showing, its clock, and how
 * far it has run. When a scene's time is up, `next(index)` says where to go
 * (null stays put). Choosing a scene by hand stops the automatic changes,
 * and so does reduced motion.
 */
export function useScenes(
  durations: number[],
  next: (index: number) => number | null,
): { index: number; now: number; progress: number; select: (i: number) => void; go: (i: number) => void } {
  const [index, setIndex] = React.useState(0)
  const [run, setRun] = React.useState(0)
  const [manual, setManual] = React.useState(false)
  const duration = durations[index] ?? 0
  const now = useTimeline(duration, run)
  const nextRef = React.useRef(next)
  nextRef.current = next

  const go = React.useCallback((i: number) => {
    setIndex(i)
    setRun((r) => r + 1)
  }, [])

  React.useEffect(() => {
    if (now !== Infinity || manual || prefersReducedMotion()) return
    const to = nextRef.current(index)
    if (to !== null && to !== index) go(to)
  }, [now, manual, index, go])

  const select = React.useCallback(
    (i: number) => {
      setManual(true)
      go(i)
    },
    [go],
  )

  return { index, now, progress: now === Infinity ? 1 : Math.min(1, now / duration), select, go }
}
