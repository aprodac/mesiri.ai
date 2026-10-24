import { cn } from '@/lib/utils'

// The Mesiri wordmark, set in the brand face (Unbounded, --font-brand) so it
// reads as a logo rather than UI text. Use these everywhere the Mesiri logo
// appears instead of typing "Mesiri" in a styled span.

/** Square "M" tile: the collapsed-sidebar / icon form of the logo. */
export function MesiriMark({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        'size-8 rounded-lg flex items-center justify-center font-brand font-bold text-sm shrink-0 leading-none',
        className
      )}
    >
      M
    </div>
  )
}

/** The "Mesiri" wordmark text. */
export function MesiriWordmark({ className }: { className?: string }) {
  return <span className={cn('font-brand font-bold tracking-tight leading-none', className)}>Mesiri</span>
}

/** Tile plus wordmark, for standalone pages (sign in, sign up). */
export function MesiriLogo({ className }: { className?: string }) {
  return (
    <div className={cn('flex items-center gap-2.5', className)} aria-label="Mesiri">
      <MesiriMark className="bg-[#3E3C3D] text-white dark:bg-foreground dark:text-background" />
      <MesiriWordmark className="text-xl text-foreground" />
    </div>
  )
}
