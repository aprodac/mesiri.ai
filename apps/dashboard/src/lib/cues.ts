// WEB-37: small shared visual cues for list rows and ledgers.

/** A thin coloured bar on a row's left edge that says its state (WEB-37).
 * An inset shadow, so it never shifts the row's content. */
export const ROW_ACCENT: Record<'good' | 'info' | 'warn' | 'bad' | 'none', string> = {
  good: 'shadow-[inset_3px_0_0_var(--success)]',
  info: 'shadow-[inset_3px_0_0_var(--info)]',
  warn: 'shadow-[inset_3px_0_0_var(--draft)]',
  bad: 'shadow-[inset_3px_0_0_var(--destructive)]',
  none: '',
}

/** Alternate shading for a ledger's day groups, so days read as blocks. */
export const dayBand = (dayIndex: number) => (dayIndex % 2 === 1 ? 'bg-muted/60' : '')
