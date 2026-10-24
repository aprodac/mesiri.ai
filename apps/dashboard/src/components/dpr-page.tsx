import * as React from 'react'
import { Check } from 'lucide-react'
import { cn } from '@/lib/utils'

// The building blocks of the site and project DPR pages (WEB-04/05, reworked
// in WEB-19): one white page in flat sections split by rules, not a stack of
// cards. See docs/DESIGN.md.

/** A titled part of the page. `icon` sits in a small tinted square. */
export function DprSection({
  icon: Icon,
  title,
  meta,
  action,
  children,
  className,
}: {
  icon: React.ComponentType<{ className?: string }>
  title: string
  meta?: React.ReactNode
  action?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <section className={cn('flex flex-col gap-3 border-t py-6 first:border-t-0 first:pt-0', className)}>
      <header className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-muted text-foreground/70">
            <Icon className="size-4" />
          </span>
          <h2 className="text-[15px] font-semibold">{title}</h2>
          {meta && <span className="text-sm text-muted-foreground">{meta}</span>}
        </div>
        {action}
      </header>
      {children}
    </section>
  )
}

/** The day's numbers in one bordered strip, split by dividers. */
export function StatStrip({
  stats,
}: {
  stats: { label: string; value: React.ReactNode; tone?: 'default' | 'warn' | 'bad' }[]
}) {
  return (
    <dl className="grid grid-cols-2 overflow-hidden rounded-xl border sm:flex sm:divide-x">
      {stats.map((s, i) => (
        <div
          key={s.label}
          className={cn(
            'flex flex-1 flex-col gap-0.5 px-4 py-3',
            // Phone: a 2-column grid, so draw the inner rules by hand.
            i % 2 === 1 && 'border-l sm:border-l-0',
            i >= 2 && 'border-t sm:border-t-0',
          )}
        >
          <dt className="text-xs text-muted-foreground">{s.label}</dt>
          <dd
            className={cn(
              'text-xl font-semibold tabular-nums',
              s.tone === 'warn' && 'text-draft',
              s.tone === 'bad' && 'text-destructive',
            )}
          >
            {s.value}
          </dd>
        </div>
      ))}
    </dl>
  )
}

export type StepState = 'done' | 'current' | 'todo'

/** Where the day is: updates in -> engineer confirms -> sent. */
export function DprSteps({ steps }: { steps: { label: string; hint?: string; state: StepState }[] }) {
  return (
    <ol className="flex flex-col gap-3 sm:flex-row sm:items-start sm:gap-0">
      {steps.map((step, i) => (
        <li key={step.label} className="flex flex-1 items-start gap-2.5 sm:flex-col sm:gap-2">
          <div className="flex items-center sm:w-full">
            <span
              className={cn(
                'flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
                step.state === 'done' && 'bg-success text-white dark:text-background',
                step.state === 'current' && 'bg-primary text-primary-foreground ring-4 ring-primary/15',
                step.state === 'todo' && 'border border-input bg-background text-muted-foreground',
              )}
            >
              {step.state === 'done' ? <Check className="size-3.5" strokeWidth={3} /> : i + 1}
            </span>
            {i < steps.length - 1 && (
              <span
                aria-hidden
                className={cn('mx-2 hidden h-0.5 flex-1 rounded sm:block', step.state === 'done' ? 'bg-success' : 'bg-border')}
              />
            )}
          </div>
          <div className="flex flex-col sm:pr-4">
            <span className={cn('text-sm font-medium', step.state === 'todo' && 'text-muted-foreground')}>{step.label}</span>
            {step.hint && <span className="text-xs text-muted-foreground">{step.hint}</span>}
          </div>
        </li>
      ))}
    </ol>
  )
}

const CALLOUT_TONES = {
  draft: 'border-draft/25 bg-draft-soft text-draft',
  success: 'border-success/20 bg-success-soft text-success',
  info: 'border-info/20 bg-info-soft text-info',
  muted: 'border-border bg-muted/60 text-muted-foreground',
} as const

/** One line that needs the reader's eye, with an optional action. */
export function Callout({
  tone,
  icon: Icon,
  children,
  action,
}: {
  tone: keyof typeof CALLOUT_TONES
  icon: React.ComponentType<{ className?: string }>
  children: React.ReactNode
  action?: React.ReactNode
}) {
  return (
    <div className={cn('flex flex-col gap-2 rounded-lg border px-3.5 py-2.5 text-sm sm:flex-row sm:items-center', CALLOUT_TONES[tone])}>
      <div className="flex flex-1 items-start gap-2.5">
        <Icon className="mt-0.5 size-4 shrink-0" />
        <div className="min-w-0">{children}</div>
      </div>
      {action}
    </div>
  )
}

/** The right-hand column on wide screens; stacks under the page on phones. */
export function DprAside({ children }: { children: React.ReactNode }) {
  return (
    <aside className="flex flex-col divide-y rounded-xl border lg:sticky lg:top-6 lg:self-start [&>*]:p-5">{children}</aside>
  )
}
