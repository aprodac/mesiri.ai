import * as React from 'react'
import { Link, useLocation } from 'react-router-dom'
import { findPage } from '@/lib/module-map'
import { ArrowRight, ChevronRight, MessageSquareText } from 'lucide-react'
import { cn } from '@/lib/utils'

// The page kit (UX-05, docs/DESIGN.md "Page kit"): the parts every dashboard page is built from, in one
// import. The header, stat strip, callout, error and view switch already existed in components/dpr-page.tsx
// (72 pages use them) and are re-exported here unchanged; this file adds what pages kept rebuilding on their
// own: a plain section, an empty state that leads somewhere, a tile for home screens, and the Linked strip
// that joins a record to the ones before and after it (UX-09).

export { PageHeader, StatStrip, Callout, PageError, Segmented, DprSection as IconSection } from '@/components/dpr-page'

/**
 * A module page's title (UX-08): one icon tile in the brand colour, the module's name above the title taken from
 * lib/module-map.ts (so it always matches the sidebar and breadcrumb), and the title. Pages put their actions
 * beside it in their own header row. Replaces ~20 hand-made headers that each picked their own tile colour and
 * typed their own module name.
 */
export function ModuleTitle({
  icon: Icon,
  title,
  chip,
  module: moduleName,
  className,
}: {
  icon: React.ComponentType<{ className?: string }>
  title: React.ReactNode
  chip?: React.ReactNode
  /** Only for a page outside the module map. */
  module?: string
  className?: string
}) {
  const { pathname, search } = useLocation()
  const hit = findPage(pathname, search)
  const eyebrow = moduleName ?? (hit && hit.group.key !== 'site' ? hit.group.title : undefined)
  return (
    <div className={cn('flex min-w-0 items-center gap-3', className)}>
      <span className="inline-flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/20 text-primary-ink" aria-hidden>
        <Icon className="size-5" />
      </span>
      <div className="min-w-0">
        {eyebrow && <div className="text-xs text-muted-foreground">{eyebrow}</div>}
        <h1 className="flex flex-wrap items-center gap-2 text-xl leading-tight font-semibold tracking-tight sm:text-2xl">
          <span className="truncate">{title}</span>
          {chip}
        </h1>
      </div>
    </div>
  )
}

/** A flat section: title, an optional note beside it, an optional action, a thin rule above. */
export function Section({
  title,
  note,
  action,
  children,
  className,
  id,
}: {
  title: string
  note?: React.ReactNode
  action?: React.ReactNode
  children?: React.ReactNode
  className?: string
  id?: string
}) {
  return (
    <section id={id} className={cn('flex scroll-mt-20 flex-col gap-2 border-t pt-4 first:border-t-0 first:pt-0', className)}>
      <header className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <div className="flex min-w-0 flex-wrap items-baseline gap-x-2">
          <h2 className="flex items-center gap-2 text-[15px] font-semibold">
            <span aria-hidden className="h-4 w-1 shrink-0 self-center rounded-full bg-primary" />
            {title}
          </h2>
          {note && <span className="text-sm text-muted-foreground">{note}</span>}
        </div>
        {action}
      </header>
      {children}
    </section>
  )
}

/**
 * Nothing here yet (UX-07): what the page is for, the one thing to do first, and the WhatsApp sentence that
 * fills it, so an empty page is the next step instead of a dead end.
 */
export function EmptyState({
  icon: Icon,
  title,
  about,
  action,
  whatsapp,
  className,
}: {
  icon?: React.ComponentType<{ className?: string }>
  title: string
  about: React.ReactNode
  /** The one thing to do first: a button or link. */
  action?: React.ReactNode
  /** A message the site can send on WhatsApp that fills this page. */
  whatsapp?: string
  className?: string
}) {
  return (
    <div className={cn('flex flex-col items-center gap-3 rounded-xl border border-dashed px-5 py-8 text-center', className)}>
      {Icon && (
        <span className="flex size-10 items-center justify-center rounded-full bg-muted text-muted-foreground" aria-hidden>
          <Icon className="size-5" />
        </span>
      )}
      <div className="flex max-w-md flex-col gap-1">
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="text-sm text-muted-foreground">{about}</p>
      </div>
      {whatsapp && (
        <p className="inline-flex max-w-md items-start gap-2 rounded-lg bg-success-soft px-3 py-2 text-left text-sm text-success">
          <MessageSquareText className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>
            Or send on WhatsApp: <span className="font-semibold">“{whatsapp}”</span>
          </span>
        </p>
      )}
      {action}
    </div>
  )
}

export type TileTone = 'default' | 'attention' | 'good' | 'bad' | 'info'

// UX-08 (asked 9 Nov: "increase visual cues"): a tile's state reads at a glance: a bar, a tinted ground and the
// figure in the state's colour. Default tiles stay plain so the coloured ones stand out.
const TILE_TONE: Record<TileTone, string> = {
  default: '',
  attention: 'before:bg-draft bg-draft-soft/50 border-draft/25',
  good: 'before:bg-success bg-success-soft/40 border-success/20',
  bad: 'before:bg-destructive bg-destructive/[0.06] border-destructive/25',
  info: 'before:bg-info bg-info-soft/50 border-info/20',
}
const TILE_VALUE: Record<TileTone, string> = {
  default: '',
  attention: 'text-draft',
  good: 'text-success',
  bad: 'text-destructive',
  info: 'text-info',
}

/**
 * One question on a home screen (UX-11): a label, a figure or short list, and the page that answers it in full.
 * The whole tile is the link, so every number on Home leads to its page.
 */
export function Tile({
  label,
  value,
  hint,
  to,
  tone = 'default',
  children,
  loading,
  className,
}: {
  label: string
  value?: React.ReactNode
  hint?: React.ReactNode
  to: string
  tone?: TileTone
  children?: React.ReactNode
  loading?: boolean
  className?: string
}) {
  return (
    <Link
      to={to}
      className={cn(
        'group relative flex min-w-0 flex-col gap-1 overflow-hidden rounded-xl border bg-background px-4 py-3 transition-colors hover:border-foreground/25',
        tone !== 'default' && "before:absolute before:inset-y-0 before:left-0 before:w-1 before:content-['']",
        TILE_TONE[tone],
        className,
      )}
    >
      <span className="flex items-center justify-between gap-2 text-xs font-medium text-muted-foreground">
        <span className="truncate">{label}</span>
        <ArrowRight className="size-3.5 shrink-0 opacity-0 transition-opacity group-hover:opacity-100" aria-hidden />
      </span>
      {loading ? (
        <span className="h-7 w-20 animate-pulse rounded bg-muted" aria-label="Loading" />
      ) : (
        value !== undefined && <span className={cn('truncate text-xl font-semibold tabular-nums', TILE_VALUE[tone])}>{value}</span>
      )}
      {hint && <span className="truncate text-xs text-muted-foreground">{hint}</span>}
      {children}
    </Link>
  )
}

/** A grid of tiles: one column on a phone, two on a tablet, three or four on a laptop. */
export function TileGrid({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn('grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3', className)}>{children}</div>
}

export type LinkedRecord = {
  /** What it is: "Request", "Order", "Delivery", "Bill", "Payment". */
  kind: string
  /** Its name or number: "PO-0042". */
  label: string
  /** Its state, short: "150 of 200 delivered". */
  status?: string
  url: string
  /** Before or after this record in its chain. */
  side: 'before' | 'after'
}

/**
 * The Linked strip (UX-09): where this record came from and what happened next, one tap each. Records reach
 * each other along four chains (docs/plans/ui-story-plan.md section 4c); a detail panel shows the steps it knows.
 */
export function LinkedStrip({ records, title = 'Linked', className }: { records: LinkedRecord[]; title?: string; className?: string }) {
  if (records.length === 0) return null
  const before = records.filter((r) => r.side === 'before')
  const after = records.filter((r) => r.side === 'after')
  const chip = (r: LinkedRecord) => (
    <Link
      key={`${r.kind}-${r.url}`}
      to={r.url}
      className="inline-flex max-w-full items-center gap-1.5 rounded-lg border bg-background px-2.5 py-1.5 text-sm transition-colors hover:border-foreground/30 hover:bg-muted/50"
    >
      <span className="shrink-0 text-xs text-muted-foreground">{r.kind}</span>
      <span className="truncate font-medium">{r.label}</span>
      {r.status && <span className="truncate text-xs text-muted-foreground">· {r.status}</span>}
      <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
    </Link>
  )
  return (
    <nav aria-label={title} className={cn('flex flex-col gap-1.5', className)}>
      <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{title}</h3>
      {before.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-muted-foreground">From</span>
          {before.map(chip)}
        </div>
      )}
      {after.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-muted-foreground">Then</span>
          {after.map(chip)}
        </div>
      )}
    </nav>
  )
}
