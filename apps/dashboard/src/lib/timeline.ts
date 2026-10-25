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
  const [now, setNow] = React.useState(() => (run === null || prefersReducedMotion() ? Infinity : 0))

  // Layout effect: a restart hides what's due later before it is painted.
  React.useLayoutEffect(() => {
    if (run === null || prefersReducedMotion()) {
      setNow(Infinity)
      return
    }
    const start = performance.now()
    setNow(0)
    const timer = window.setInterval(() => {
      const elapsed = performance.now() - start
      if (elapsed >= endMs) {
        setNow(Infinity)
        window.clearInterval(timer)
      } else {
        setNow(elapsed)
      }
    }, TICK_MS)
    return () => window.clearInterval(timer)
  }, [endMs, run])

  return now
}

/** 0 → 1 over `ms` from `at`, eased out; for count-ups and the waveform. */
export function progress(now: number, at: number, ms: number): number {
  if (now >= at + ms) return 1
  if (now <= at) return 0
  const p = (now - at) / ms
  return 1 - Math.pow(1 - p, 3)
}
