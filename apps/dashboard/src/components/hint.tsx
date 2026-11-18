import * as React from 'react'
import { createPortal } from 'react-dom'
import { CircleHelp, Pause, Volume2 } from 'lucide-react'
import { useGuideVoice } from '@/components/guide-voice'
import { glossaryTerm } from '@/lib/glossary'
import { useStartMode } from '@/lib/start-mode'
import { cn } from '@/lib/utils'
import { voiceWords } from '@/lib/voice'

/**
 * UX-27 (asked 17 Nov: "a hint button which when we hover or click gets text and can press voice on that"): a small
 * "?" beside a label. Tap it, or hover with a mouse, to read what the thing is; Listen reads it aloud in the guide's
 * voice. The words are a glossary word's (`term`) or the page's own (`title` + `text`) for what a part of the page
 * does. Shown to people who asked for explanations (new to construction, step by step, bringing data); hidden for
 * those who used other software or want no tips, who can still open Help.
 */
/** The explanation's width. */
const POP_W = 288

export function Hint({
  term,
  title,
  text,
  example,
  className,
  side = 'bottom',
}: {
  /** A glossary word (lib/glossary.ts): its meaning and example are used. */
  term?: string
  title?: string
  text?: string
  example?: string
  className?: string
  side?: 'bottom' | 'top'
}) {
  const { rules, ready } = useStartMode()
  const found = term ? glossaryTerm(term) : undefined
  const word = found?.match[0] ?? term ?? ''
  // Glossary words are written as they appear in a sentence ("retention"); as a heading they start with a capital.
  const heading = title ?? (word ? word.charAt(0).toUpperCase() + word.slice(1) : '')
  const meaning = text ?? found?.meaning ?? ''
  const eg = example ?? found?.example
  const [open, setOpen] = React.useState(false)
  const [pinned, setPinned] = React.useState(false)
  const pinnedNow = React.useRef(false)
  pinnedNow.current = pinned
  const box = React.useRef<HTMLSpanElement>(null)
  const pop = React.useRef<HTMLSpanElement>(null)
  const hoverable = typeof window !== 'undefined' && window.matchMedia?.('(hover: hover)').matches
  // Hover: the mouse crosses a small gap from the "?" to the explanation; a short grace keeps it open on the way.
  const leaving = React.useRef<number | undefined>(undefined)
  const enter = () => {
    window.clearTimeout(leaving.current)
    if (hoverable) setOpen(true)
  }
  const leave = () => {
    if (!hoverable) return
    window.clearTimeout(leaving.current)
    leaving.current = window.setTimeout(() => { if (!pinnedNow.current) setOpen(false) }, 180)
  }
  // Drawn over the page (a portal), placed from the "?" and kept on screen: a box that clips what overflows it (a
  // figures strip, a table) or a "?" at the screen's edge never cuts the explanation off (found 17 Nov on Schedule).
  const [place, setPlace] = React.useState<{ left: number; top: number } | null>(null)
  // Inside an open dialog the explanation is drawn in the dialog: a modal dialog makes everything outside it
  // unclickable (found 17 Nov: Listen on the contract's TDS could not be pressed), and a click outside closes it.
  const [host, setHost] = React.useState<HTMLElement | null>(null)
  React.useLayoutEffect(() => {
    if (!open) {
      setPlace(null)
      return
    }
    const into = (box.current?.closest('[role="dialog"]') as HTMLElement | null) ?? document.body
    setHost(into)
    const measure = () => {
      const r = box.current?.getBoundingClientRect()
      if (!r) return
      // Kept inside what it is drawn in (the dialog, or the screen). A dialog is placed with a transform, which makes
      // "fixed" relative to the dialog, so positions inside it are counted from its corner.
      const inDialog = into !== document.body
      const b = inDialog ? into.getBoundingClientRect() : { left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight }
      const w = Math.min(POP_W, b.right - b.left - 16)
      const h = pop.current?.offsetHeight ?? 160
      let left = Math.min(Math.max(b.left + 8, r.left + r.width / 2 - w / 2), b.right - w - 8)
      const below = r.bottom + 6
      let top = side === 'top' || below + h > b.bottom - 8 ? Math.max(b.top + 8, r.top - 6 - h) : below
      // Tailwind moves a dialog with `translate` (not `transform`); either makes "fixed" count from the dialog's corner.
      const cs = getComputedStyle(into)
      const moved = cs.transform !== 'none' || (cs.translate !== '' && cs.translate !== 'none') || cs.filter !== 'none'
      if (inDialog && moved) {
        left -= b.left
        top -= b.top
      }
      setPlace({ left, top })
    }
    measure()
    const frame = requestAnimationFrame(measure) // again once its height is known
    const close = () => {
      setOpen(false)
      setPinned(false)
    }
    window.addEventListener('scroll', close, true)
    window.addEventListener('resize', close)
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('resize', close)
    }
  }, [open, side])
  const id = React.useId()
  const voice = useGuideVoice()
  const words = [heading, meaning, eg].filter(Boolean).join('. ')
  const speaking = voice.playing && voice.said === voiceWords(words, 'guide')

  React.useEffect(() => {
    if (!open) return
    const away = (e: Event) => {
      if (box.current && !box.current.contains(e.target as Node) && !pop.current?.contains(e.target as Node)) {
        setOpen(false)
        setPinned(false)
      }
    }
    const esc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false)
        setPinned(false)
      }
    }
    document.addEventListener('pointerdown', away)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('pointerdown', away)
      document.removeEventListener('keydown', esc)
    }
  }, [open])

  if (!ready || !meaning || rules.words === null || rules.words === 'expert') return null
  return (
    <span
      ref={box}
      className={cn('inline-flex align-middle', className)}
      onMouseEnter={enter}
      onMouseLeave={leave}
    >
      <button
        type="button"
        onClick={(e) => {
          e.preventDefault()
          e.stopPropagation()
          setPinned((p) => !p || !open)
          setOpen((o) => !(o && pinned))
        }}
        aria-expanded={open}
        aria-describedby={open ? id : undefined}
        aria-label={`What is ${heading}?`}
        className="inline-flex size-5 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        <CircleHelp className="size-3.5" aria-hidden />
      </button>
      {open && place && host && createPortal(
        <span
          id={id}
          role="tooltip"
          ref={pop}
          onMouseEnter={enter}
          onMouseLeave={leave}
          style={{ position: 'fixed', left: place.left, top: place.top, width: POP_W, pointerEvents: 'auto' }}
          className="z-[70] block max-w-[calc(100vw-16px)] rounded-lg border bg-popover p-3 text-left text-sm font-normal normal-case tracking-normal text-popover-foreground shadow-lg"
        >
          <span className="block font-semibold">{heading}</span>
          <span className="mt-0.5 block text-foreground/85">{meaning}</span>
          {eg && <span className="mt-1.5 block text-xs text-muted-foreground">{eg}</span>}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              setPinned(true)
              if (speaking) voice.pause()
              else {
                if (!voice.on) voice.setOn(true)
                voice.say(words)
              }
            }}
            className="mt-2 inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium hover:bg-muted"
          >
            {speaking ? <Pause className="size-3.5" aria-hidden /> : <Volume2 className="size-3.5" aria-hidden />}
            {speaking ? 'Pause' : 'Listen'}
          </button>
        </span>,
        host,
      )}
    </span>
  )
}

/** A label with its hint beside it: `<Hinted term="retention">Retention %</Hinted>`. */
export function Hinted({ children, className, ...hint }: React.ComponentProps<typeof Hint> & { children: React.ReactNode }) {
  return (
    <span className={cn('inline-flex items-center gap-1', className)}>
      {children}
      <Hint {...hint} />
    </span>
  )
}
