import * as React from 'react'
import { Link, useLocation } from 'react-router-dom'
import { ArrowLeft, Check, ChevronDown, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { findPage } from '@/lib/module-map'
import { useScopeNames } from '@/lib/ScopeContext'
import { KpiStrip, type KpiProps, type KpiToneIn } from '@/components/page/kpi'

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
  iconClass,
  open,
  onToggle,
}: {
  icon: React.ComponentType<{ className?: string }>
  title: string
  /** Collapsible: with onToggle the title opens and closes the section, and `open` false hides its body. */
  open?: boolean
  onToggle?: () => void
  /** The icon tile's colours (WEB-41), e.g. 'bg-info-soft text-info'. */
  iconClass?: string
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
          {onToggle ? (
            <button type="button" onClick={onToggle} aria-expanded={open !== false} className="-ml-1 flex items-center gap-1.5 rounded-md px-1 py-0.5 text-left hover:bg-muted">
              <ChevronDown className={cn('size-4 shrink-0 text-muted-foreground transition-transform', open === false && '-rotate-90')} aria-hidden />
              <h2 className="text-[15px] font-semibold">{title}</h2>
            </button>
          ) : (
            <>
              <span className={cn('flex size-6 shrink-0 items-center justify-center rounded-md', iconClass ?? 'bg-muted text-foreground/70')}>
                <Icon className="size-3.5" />
              </span>
              <h2 className="text-[15px] font-semibold">{title}</h2>
            </>
          )}
          {meta && <span className="text-sm text-muted-foreground">{meta}</span>}
        </div>
        {action}
      </header>
      {open !== false && children}
    </section>
  )
}

// UX-15: the stat strip is the page kit's KPI strip (components/page/kpi.tsx): one KPI design on every page.
// `Stat` keeps its fields (label, value, tone, icon, hint) and gains kind, of, share, to, onClick.
export type StatTone = KpiToneIn
export type Stat = KpiProps
export const StatStrip = KpiStrip

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
  // UX-08: a module's own page (its address is the page's address in lib/module-map.ts) is reached from the
  // sidebar, and the top bar already says "Module › Page" on a laptop; its back line then names the module as
  // the map does, on phones only (the top bar hides its breadcrumb there). A detail page (one project, one
  // ledger) keeps its real "up" link everywhere.
  const { pathname, search } = useLocation()
  const hit = findPage(pathname, search)
  const modulePage = !!hit && hit.page.url.split('?')[0] === pathname
  const up = modulePage && hit && hit.group.key !== 'site' ? { to: hit.group.pages.find((p) => p.status === 'built' && !p.shortcut)?.url ?? back.to, label: hit.group.title } : back
  // UX-14: nothing said twice. The top bar names the project or site picked, and the h1 names the page: the back
  // line is only where Back goes (the kind of place, when its name is the one already in the top bar), and a
  // subtitle that is that name again is left out.
  const picked = useScopeNames()
  const sub = date && !picked.includes(date) ? date : undefined
  return (
    // One row: Back is an arrow beside the title (named in full for screen readers and on hover), so the header
    // does not spend a line on it.
    <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <Link
          to={up.to}
          className={cn('-ml-1.5 inline-flex size-8 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground', modulePage && 'md:hidden')}
          title={`Back to ${up.label}`}
          aria-label={`Back to ${up.label}`}
        >
          <ArrowLeft className="size-[18px]" />
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {chip}
        {sub && <span className="text-sm text-muted-foreground">{sub}</span>}
      </div>
      {action}
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
    <div className="mx-auto flex w-full animate-pulse flex-col gap-4 pb-4 sm:px-2" aria-busy="true" aria-label="Loading">
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
  guide,
}: {
  label: string
  value: T
  options: { value: T; label: string; count?: number }[]
  onChange: (value: T) => void
  /** A tour step's marker (lib/tours.ts). */
  guide?: string
}) {
  return (
    <div className="flex w-fit max-w-full overflow-x-auto rounded-lg border p-0.5" role="group" aria-label={label} data-guide={guide}>
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
