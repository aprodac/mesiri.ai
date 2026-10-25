import * as React from 'react'
import { inkDuration } from '@/lib/ink'
import { prefersReducedMotion } from '@/lib/timeline'
import { cn } from '@/lib/utils'

// The Live report's "writing itself" (WEB-37): text that appears letter by
// letter behind a caret, and numbers that count to their new value. With
// reduced motion everything is simply there.

export function Ink({
  text,
  writing,
  delay = 0,
  className,
}: {
  text: string
  /** True while this line is being written; false shows it whole. */
  writing: boolean
  /** Wait this long (ms) before the first letter. */
  delay?: number
  className?: string
}) {
  const [shown, setShown] = React.useState(writing ? 0 : text.length)

  React.useEffect(() => {
    if (!writing || prefersReducedMotion()) {
      setShown(text.length)
      return
    }
    setShown(0)
    const total = inkDuration(text)
    const start = performance.now() + delay
    let frame = 0
    const tick = () => {
      const p = Math.max(0, Math.min(1, (performance.now() - start) / total))
      setShown(Math.round(text.length * p))
      if (p < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [text, writing, delay])

  const done = shown >= text.length
  return (
    <span className={className} aria-label={text}>
      <span aria-hidden="true">{text.slice(0, shown)}</span>
      {writing && !done && shown > 0 && (
        <span aria-hidden="true" className="-mr-[2px] inline-block h-[1.05em] w-[2px] translate-y-[0.18em] bg-primary" />
      )}
      {/* The rest keeps its space, so the line doesn't reflow as it writes. */}
      <span aria-hidden="true" className="invisible">
        {text.slice(shown)}
      </span>
    </span>
  )
}

/** A number that counts from its last value to the new one. */
export function CountTo({ value, className }: { value: number; className?: string }) {
  const [shown, setShown] = React.useState(value)
  const from = React.useRef(value)

  React.useEffect(() => {
    const start = from.current
    from.current = value
    if (start === value || prefersReducedMotion()) {
      setShown(value)
      return
    }
    const began = performance.now()
    let frame = 0
    const tick = () => {
      const p = Math.min(1, (performance.now() - began) / 900)
      setShown(Math.round(start + (value - start) * (1 - Math.pow(1 - p, 3))))
      if (p < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [value])

  return <span className={cn('tabular-nums', className)}>{shown}</span>
}
