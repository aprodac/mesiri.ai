import * as React from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, Check, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
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
  id,
}: {
  icon: React.ComponentType<{ className?: string }>
  title: string
  /** An anchor, for links to one section (?tab=…). */
  id?: string
  meta?: React.ReactNode
  action?: React.ReactNode
  children?: React.ReactNode
  className?: string
}) {
  return (
    <section id={id} className={cn('flex scroll-mt-20 flex-col gap-2 border-t py-4 first:border-t-0 first:pt-0', className)}>
      {/* The action drops under the title when the row is too narrow. */}
      <header className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
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

export type StatTone = 'default' | 'good' | 'info' | 'warn' | 'bad'

export type Stat = {
  label: string
  value: React.ReactNode
  tone?: StatTone
  /** A small icon beside the label (WEB-37). */
  icon?: React.ComponentType<{ className?: string }>
  /** A few words under the number: "of 4 sites", "2 critical". */
  hint?: React.ReactNode
}

// WEB-37: what each tone looks like. Colour carries meaning only: green is
// good, amber needs watching, red is a problem, blue is information.
const STAT_TONE: Record<StatTone, { value: string; icon: string; bar: string }> = {
  default: { value: '', icon: 'bg-muted text-muted-foreground', bar: '' },
  good: { value: 'text-success', icon: 'bg-success-soft text-success', bar: 'before:bg-success' },
  info: { value: 'text-info', icon: 'bg-info-soft text-info', bar: 'before:bg-info' },
  warn: { value: 'text-draft', icon: 'bg-draft-soft text-draft', bar: 'before:bg-draft' },
  bad: { value: 'text-destructive', icon: 'bg-destructive/10 text-destructive', bar: 'before:bg-destructive' },
}

/** The day's numbers in one bordered strip, split by dividers. A figure
 * that means something good or bad is coloured and gets a bar on top. */
export function StatStrip({
  stats,
  phoneCols,
}: {
  stats: Stat[]
  /** Columns on phones when the values are long (e.g. "+365 bags"). */
  phoneCols?: 2
}) {
  return (
    // One row; on phones more than four wrap to rows of three. The 1px gap
    // over a border-coloured ground draws the rules in either layout.
    <dl
      className={cn(
        'grid gap-px overflow-hidden rounded-xl border bg-border sm:flex',
        stats.length <= 2 || phoneCols === 2 ? 'grid-cols-2' : stats.length === 4 ? 'grid-cols-4' : 'grid-cols-3',
      )}
    >
      {stats.map((s, i) => {
        const t = STAT_TONE[s.tone ?? 'default']
        return (
          <div
            key={s.label}
            className={cn(
              'relative flex min-w-0 flex-1 flex-col bg-background px-2.5 py-1.5 sm:px-4 sm:py-2.5',
              s.tone && s.tone !== 'default' && "before:absolute before:inset-x-0 before:top-0 before:h-0.5 before:content-['']",
              t.bar,
              // In rows of three, the last one fills what is left of its row.
              i === stats.length - 1 && stats.length > 4 && stats.length % 3 === 2 && 'col-span-2',
              i === stats.length - 1 && stats.length > 4 && stats.length % 3 === 1 && 'col-span-3',
            )}
          >
            <dt className="flex min-w-0 items-center gap-1.5 text-[11px] text-muted-foreground sm:text-xs">
              {s.icon && (
                <span className={cn('hidden size-5 shrink-0 items-center justify-center rounded-md sm:flex', t.icon)} aria-hidden="true">
                  <s.icon className="size-3" />
                </span>
              )}
              <span className="truncate">{s.label}</span>
            </dt>
            <dd className={cn('truncate text-base font-semibold tabular-nums sm:text-lg', t.value)}>{s.value}</dd>
            {s.hint && <dd className="hidden truncate text-[11px] text-muted-foreground sm:block">{s.hint}</dd>}
          </div>
        )
      })}
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
  /** The day, or any one muted line beside the title. */
  date?: string
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
          {date && <span className="text-sm text-muted-foreground">{date}</span>}
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
    <header className="flex items-start justify-between gap-3 sm:items-end">
      <div className="flex min-w-0 flex-col gap-0.5">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="text-sm text-muted-foreground">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </header>
  )
}

/** Placeholder while a DPR page loads: the shape of the page, not a line of
 * text. */
export function DprPageSkeleton() {
  return (
    <div className="mx-auto flex w-full max-w-6xl animate-pulse flex-col gap-4 pb-4 sm:px-2" aria-busy="true" aria-label="Loading">
      <div className="h-4 w-48 rounded bg-muted" />
      <div className="h-7 w-72 rounded bg-muted" />
      <div className="h-9 rounded-lg bg-muted/60" />
      <div className="h-16 rounded-xl bg-muted/60" />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="flex flex-col gap-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-10 rounded-lg bg-muted/60" />
          ))}
        </div>
        <div className="h-64 rounded-xl bg-muted/60" />
      </div>
    </div>
  )
}

/** A page that could not load: what failed, Try again, and a way out. */
export function PageError({
  message,
  onRetry,
  back,
}: {
  message: string
  onRetry: () => void
  back: { to: string; label: string }
}) {
  return (
    <div className="mx-auto flex w-full max-w-md flex-col items-center gap-3 py-16 text-center">
      <TriangleAlert className="size-6 text-destructive" />
      <p className="font-medium">{message}</p>
      <p className="text-sm text-muted-foreground">Check your connection and try again.</p>
      <div className="flex gap-2">
        <Button onClick={onRetry}>Try again</Button>
        <Button asChild variant="outline">
          <Link to={back.to}>{back.label}</Link>
        </Button>
      </div>
    </div>
  )
}

/** A small one-of-several switch (filters on list pages). */
export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: T
  options: { value: T; label: string; count?: number }[]
  onChange: (value: T) => void
}) {
  return (
    <div className="flex w-fit max-w-full overflow-x-auto rounded-lg border p-0.5" role="group" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            'shrink-0 whitespace-nowrap rounded-md px-2.5 py-1 text-xs font-medium',
            value === o.value ? 'bg-foreground text-background' : 'text-muted-foreground hover:text-foreground',
          )}
        >
          {o.label}
          {o.count !== undefined && <span className="ml-1 tabular-nums opacity-70">{o.count}</span>}
        </button>
      ))}
    </div>
  )
}
