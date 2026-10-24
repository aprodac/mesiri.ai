import { cn } from '@/lib/utils'

// The Mesiri wordmark, set in the brand face (Unbounded, --font-brand) so it
// reads as a logo rather than UI text. Use these everywhere the Mesiri logo
// appears instead of typing "Mesiri" in a styled span. No tile/box around it.

/** The "Mesiri" wordmark text. */
export function MesiriWordmark({ className }: { className?: string }) {
  return <span className={cn('font-brand font-bold tracking-tight leading-none', className)}>Mesiri</span>
}

/** Just the "M", for tight spots such as the collapsed sidebar. */
export function MesiriMark({ className }: { className?: string }) {
  return (
    <span aria-hidden="true" className={cn('font-brand font-bold leading-none', className)}>
      M
    </span>
  )
}

/** The wordmark at page-header size, for standalone pages (sign in, sign up). */
export function MesiriLogo({ className }: { className?: string }) {
  return <MesiriWordmark className={cn('text-2xl text-foreground', className)} />
}
