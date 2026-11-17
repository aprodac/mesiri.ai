import * as React from 'react'
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
  const box = React.useRef<HTMLSpanElement>(null)
  const id = React.useId()
  const voice = useGuideVoice()
  const words = [heading, meaning, eg].filter(Boolean).join('. ')
  const speaking = voice.playing && voice.said === voiceWords(words, 'guide')

  React.useEffect(() => {
    if (!open) return
    const away = (e: Event) => {
      if (box.current && !box.current.contains(e.target as Node)) {
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
  const hoverable = typeof window !== 'undefined' && window.matchMedia?.('(hover: hover)').matches
  return (
    <span
      ref={box}
      className={cn('relative inline-flex align-middle', className)}
      onMouseEnter={() => hoverable && setOpen(true)}
      onMouseLeave={() => hoverable && !pinned && setOpen(false)}
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
      {open && (
        <span
          id={id}
          role="tooltip"
          className={cn(
            'absolute left-1/2 z-50 block w-72 max-w-[80vw] -translate-x-1/2 rounded-lg border bg-popover p-3 text-left text-sm font-normal normal-case tracking-normal text-popover-foreground shadow-lg',
            side === 'bottom' ? 'top-full mt-1.5' : 'bottom-full mb-1.5',
          )}
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
        </span>
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
