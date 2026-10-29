import * as React from 'react'
import { SheetDescription, SheetTitle } from '@/components/ui/sheet'
import { cn } from '@/lib/utils'

// WEB-36: the parts every side panel is built from, so they read alike: a
// tinted head that says what this is (a kicker, the big line, the facts
// under it), then short titled sections of label/value rows. Used inside
// <SheetContent className="gap-0 p-0 …">; the head carries the sheet's
// title and description for screen readers.

export type SheetTone = 'in' | 'out' | 'warn' | 'neutral'

const TONES: Record<SheetTone, { band: string; kicker: string }> = {
  in: { band: 'bg-success-soft/60', kicker: 'bg-success text-background' },
  out: { band: 'bg-destructive/[0.07]', kicker: 'bg-destructive text-white' },
  warn: { band: 'bg-draft-soft/70', kicker: 'bg-draft text-white' },
  neutral: { band: 'bg-muted/50', kicker: 'bg-foreground text-background' },
}

export function SheetHero({
  tone = 'neutral',
  kicker,
  title,
  lead,
  children,
}: {
  tone?: SheetTone
  /** What kind of thing this is ("Received", "Used", "Invoice"). */
  kicker: string
  /** The big line: the quantity, the amount, the name. */
  lead?: React.ReactNode
  /** The sheet's title (what it is about). */
  title: React.ReactNode
  /** Facts under the title, e.g. site · day. */
  children?: React.ReactNode
}) {
  const t = TONES[tone]
  return (
    <div className={cn('flex flex-col gap-2 border-b px-5 pt-5 pb-4', t.band)}>
      <span className={cn('w-fit rounded-full px-2 py-0.5 text-[11px] font-semibold tracking-wide uppercase', t.kicker)}>{kicker}</span>
      {lead && <div className="text-3xl leading-tight font-semibold tracking-tight tabular-nums">{lead}</div>}
      <SheetTitle className={cn('pr-6', lead ? 'text-base font-medium' : 'text-xl')}>{title}</SheetTitle>
      {children && <SheetDescription asChild><div className="flex flex-wrap items-center gap-x-3 gap-y-1">{children}</div></SheetDescription>}
    </div>
  )
}

/** A titled group of facts. */
export function SheetSection({ title, action, children, className }: { title: string; action?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn('flex flex-col gap-2 px-5 py-4', className)}>
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  )
}

/** Label/value rows. A missing value shows as a muted dash with a reason. */
export function Facts({ children }: { children: React.ReactNode }) {
  return <dl className="grid grid-cols-[minmax(84px,auto)_1fr] gap-x-4 gap-y-2 text-sm">{children}</dl>
}

export function Fact({ label, children, missing }: { label: string; children?: React.ReactNode; missing?: string }) {
  const empty = children === null || children === undefined || children === '' || children === false
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={cn('min-w-0 break-words', empty && 'text-muted-foreground')}>{empty ? (missing ?? '—') : children}</dd>
    </>
  )
}

/** A small "who did it" line: initials, name, how and when. */
export function ByLine({ name, detail }: { name?: string; detail: string }) {
  const initials = (name ?? '?')
    .split(/\s+/)
    .map((p) => p[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
  return (
    <div className="flex items-center gap-3">
      <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold" aria-hidden="true">
        {initials}
      </span>
      <div className="min-w-0 text-sm">
        <p className="truncate font-medium">{name ?? 'Someone on the team'}</p>
        <p className="truncate text-xs text-muted-foreground">{detail}</p>
      </div>
    </div>
  )
}
