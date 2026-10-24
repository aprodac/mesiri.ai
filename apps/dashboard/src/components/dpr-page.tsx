import * as React from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, Check } from 'lucide-react'
import { cn } from '@/lib/utils'

// The building blocks of the site and project DPR pages (WEB-04/05, reworked
// in WEB-25): one white page in flat sections split by rules, not a stack of
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
  children?: React.ReactNode
  className?: string
}) {
  return (
    <section className={cn('flex flex-col gap-2 border-t py-4 first:border-t-0 first:pt-0', className)}>
      <header className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-muted text-foreground/70">
            <Icon className="size-3.5" />
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
    <dl className="flex divide-x overflow-hidden rounded-xl border">
      {stats.map((s) => (
        <div key={s.label} className="flex min-w-0 flex-1 flex-col px-2.5 py-1.5 sm:px-4 sm:py-2">
          <dt className="truncate text-[11px] text-muted-foreground sm:text-xs">{s.label}</dt>
          <dd
            className={cn(
              'truncate text-base font-semibold tabular-nums sm:text-lg',
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
export function DprSteps({ steps }: { steps: { label: string; short?: string; hint?: string; state: StepState }[] }) {
  return (
    <ol className="flex items-center gap-2 rounded-lg bg-muted/50 px-3 py-2">
      {steps.map((step, i) => (
        <li key={step.label} className={cn('flex min-w-0 items-center gap-2', i < steps.length - 1 && 'flex-1')}>
          <span
              className={cn(
                'flex size-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold',
                step.state === 'done' && 'bg-success text-white dark:text-background',
                step.state === 'current' && 'bg-primary text-primary-foreground ring-3 ring-primary/15',
                step.state === 'todo' && 'border border-input bg-background text-muted-foreground',
              )}
            >
              {step.state === 'done' ? <Check className="size-3" strokeWidth={3} /> : i + 1}
          </span>
          <span className="flex min-w-0 flex-col leading-tight sm:flex-row sm:items-baseline sm:gap-1.5">
            <span className={cn('truncate text-xs font-medium sm:text-sm', step.state === 'todo' && 'text-muted-foreground')}>
              <span className="sm:hidden">{step.short ?? step.label}</span>
              <span className="hidden sm:inline">{step.label}</span>
            </span>
            {step.hint && <span className="truncate text-[11px] text-muted-foreground sm:text-xs">{step.hint}</span>}
          </span>
          {i < steps.length - 1 && (
            <span
              aria-hidden
              className={cn('mx-1 hidden h-px min-w-4 flex-1 sm:block', step.state === 'done' ? 'bg-success' : 'bg-border')}
            />
          )}
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
    <div className={cn('flex flex-col gap-2 rounded-lg border px-3 py-2 text-sm sm:flex-row sm:items-center', CALLOUT_TONES[tone])}>
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
    <aside className="flex flex-col divide-y rounded-xl border lg:sticky lg:top-4 lg:self-start [&>*]:p-4">{children}</aside>
  )
}

/** Back link, breadcrumb, title + status chip + date, and the one primary
 * action, in as few lines as fit. */
export function DprHeader({
  back,
  crumb,
  title,
  chip,
  date,
  action,
}: {
  back: { to: string; label: string }
  crumb: string
  title: string
  chip?: React.ReactNode
  date: string
  action?: React.ReactNode
}) {
  return (
    <header className="flex flex-col gap-1">
      <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
        <Link to={back.to} className="inline-flex items-center gap-1 hover:text-foreground">
          <ArrowLeft className="size-4" /> {back.label}
        </Link>
        <span aria-hidden>/</span>
        <span className="truncate">{crumb}</span>
      </p>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          {chip}
          <span className="text-sm text-muted-foreground">{date}</span>
        </div>
        {action}
      </div>
    </header>
  )
}

/** Title, one muted line under it, and the page's actions on the right:
 * the header for list pages (Activities, Gallery, ...). */
export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string
  subtitle?: React.ReactNode
  actions?: React.ReactNode
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
      <div className="flex min-w-0 flex-col gap-0.5">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="text-sm text-muted-foreground">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </header>
  )
}
