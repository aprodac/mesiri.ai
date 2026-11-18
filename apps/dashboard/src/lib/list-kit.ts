import * as React from 'react'

// UX-45: the list page kit's state and colour tables; drawn by components/page/list-kit.tsx. The recipe and rules are
// in docs/design/LIST_PAGE_KIT.md.

/** A state's look, the same everywhere: a pill, a dot or bar, and text. Never a raw palette colour on a page. */
export type Tone = 'good' | 'attention' | 'bad' | 'info' | 'muted'
export const TONE: Record<Tone, { pill: string; dot: string; text: string; soft: string }> = {
  good: { pill: 'bg-success-soft text-success', dot: 'bg-success', text: 'text-success', soft: 'bg-success-soft/60' },
  attention: { pill: 'bg-draft-soft text-draft', dot: 'bg-draft', text: 'text-draft', soft: 'bg-draft-soft/60' },
  bad: { pill: 'bg-destructive/10 text-destructive', dot: 'bg-destructive', text: 'text-destructive', soft: 'bg-destructive/[0.07]' },
  info: { pill: 'bg-info-soft text-info', dot: 'bg-info', text: 'text-info', soft: 'bg-info-soft/60' },
  muted: { pill: 'bg-muted text-muted-foreground', dot: 'bg-muted-foreground/40', text: 'text-muted-foreground', soft: 'bg-muted/60' },
}

/** "/" puts the cursor in this field, as in most tools (never while typing in another field or with a modifier). */
export function useSlashFocus(ref: React.RefObject<HTMLInputElement | null>, enabled = true) {
  React.useEffect(() => {
    if (!enabled) return
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey || t?.closest('input, textarea, select, [contenteditable="true"]')) return
      e.preventDefault()
      ref.current?.focus()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [ref, enabled])
}
