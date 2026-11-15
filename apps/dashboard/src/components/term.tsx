import * as React from 'react'
import { splitTerms, type GlossaryTerm } from '@/lib/glossary'
import { useStartMode } from '@/lib/start-mode'
import { cn } from '@/lib/utils'

// SS-33: a construction word, explained on tap (lib/glossary.ts). Step-by-step mode underlines the words so they are
// seen; in the other modes they are still explained on tap, with a fainter underline.

export function Term({ term, children }: { term: GlossaryTerm; children: React.ReactNode }) {
  const [open, setOpen] = React.useState(false)
  const id = React.useId()
  const { rules } = useStartMode()
  const box = React.useRef<HTMLSpanElement>(null)
  React.useEffect(() => {
    if (!open) return
    const away = (e: Event) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false)
    }
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('pointerdown', away)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('pointerdown', away)
      document.removeEventListener('keydown', esc)
    }
  }, [open])
  return (
    <span ref={box} className="relative inline">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-describedby={open ? id : undefined}
        className={cn(
          'cursor-help underline decoration-dotted underline-offset-[3px]',
          rules.termsUnderlined ? 'decoration-foreground/60' : 'decoration-muted-foreground/40',
        )}
      >
        {children}
      </button>
      {open && (
        <span
          id={id}
          role="tooltip"
          className="absolute top-full left-0 z-30 mt-1 block w-64 max-w-[80vw] rounded-md border bg-popover px-3 py-2 text-left text-xs font-normal text-popover-foreground shadow-md"
        >
          <span className="block font-semibold">{term.match[0]}</span>
          <span className="block">{term.meaning}</span>
          {term.example && <span className="mt-1 block text-muted-foreground">{term.example}</span>}
        </span>
      )}
    </span>
  )
}

/** Plain text with its construction words explained on tap. */
export function WithTerms({ text }: { text: string }) {
  return (
    <>
      {splitTerms(text).map((part, i) =>
        typeof part === 'string' ? <React.Fragment key={i}>{part}</React.Fragment> : <Term key={i} term={part.term}>{part.text}</Term>,
      )}
    </>
  )
}
