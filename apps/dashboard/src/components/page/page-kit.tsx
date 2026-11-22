import * as React from 'react'
import { Link, useLocation } from 'react-router-dom'
import { findPage } from '@/lib/module-map'
import { ChevronRight, Lock, MessageSquareText } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useLook } from '@/lib/look'
import { KPI_TONE, Kpi, KpiGrid, type KpiProps, type KpiTone } from '@/components/page/kpi'

// The page kit (UX-05, docs/DESIGN.md "Page kit"): the parts every dashboard page is built from, in one
// import. The header, stat strip, callout, error and view switch already existed in components/dpr-page.tsx
// (72 pages use them) and are re-exported here unchanged; this file adds what pages kept rebuilding on their
// own: a plain section, an empty state that leads somewhere, a tile for home screens, and the Linked strip
// that joins a record to the ones before and after it (UX-09).

export { PageHeader, StatStrip, Callout, PageError, Segmented, DprSection as IconSection } from '@/components/dpr-page'
export { Kpi, KpiStrip, KpiGrid, KpiMeter, type KpiItem, type KpiProps, type KpiTone } from '@/components/page/kpi'
export { ActionButton, ActionIcon, ActionMenuItem } from '@/components/page/action-button'
// UX-45: the list page kit, the pager and the Numbers view (recipe: docs/design/LIST_PAGE_KIT.md).
export { ActionChip, BulkBar, ClearButton, ListToolbar, NoMatch, NoteChip, Pill, ReasonChip, SearchBox, SortSelect, StateBar, ToggleChip, type StateItem } from '@/components/page/list-kit'
export { Pager } from '@/components/page/pager'
export { NumbersTable, ShowSwitch, type NumberColumn } from '@/components/page/numbers-view'

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
      <span className="inline-flex size-10 shrink-0 items-center justify-center rounded-[14px] bg-blueprint-pale text-blueprint" aria-hidden>
        <Icon className="size-5" />
      </span>
      <div className="min-w-0">
        {eyebrow && <div className="font-mono text-[10px] font-medium tracking-[0.12em] text-muted-foreground uppercase">{eyebrow}</div>}
        <h1 className="flex flex-wrap items-center gap-2 text-2xl leading-tight font-bold sm:text-[28px]">
          <span className="truncate">{title}</span>
          {chip}
        </h1>
      </div>
    </div>
  )
}

/**
 * The title block (WEB-102, the phone's Today title block): the drawing's corner box on squared blueprint paper, for
 * the one page a person lands on (Home, Today). Never behind a list: the grid is used sparingly. `eyebrow` is the
 * small mono line (date, scope), `aside` the controls or the status on the right, `children` a line under the title.
 * In the Classic look (WEB-103) it is the plain page header it replaced.
 */
export function TitleBlock({
  eyebrow,
  title,
  aside,
  children,
  className,
}: {
  eyebrow?: React.ReactNode
  title: React.ReactNode
  aside?: React.ReactNode
  children?: React.ReactNode
  className?: string
}) {
  const [look] = useLook()
  if (look === 'classic')
    return (
      <header className={cn('flex flex-wrap items-end justify-between gap-3', className)}>
        <div className="flex min-w-0 flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          {eyebrow && <p className="text-sm text-muted-foreground">{eyebrow}</p>}
          {children}
        </div>
        {aside && <div className="flex shrink-0 items-center gap-2">{aside}</div>}
      </header>
    )
  return (
    <header className={cn('blueprint-grid relative overflow-hidden rounded-[22px] px-5 py-5 text-white sm:px-7 sm:py-6', className)}>
      <span aria-hidden className="pointer-events-none absolute inset-2.5 rounded-[16px] border border-white/15" />
      <div className="relative flex flex-wrap items-end justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1.5">
          {eyebrow && <div className="font-mono text-[10px] font-medium tracking-[0.14em] text-[#b9c8e6] uppercase sm:text-[11px]">{eyebrow}</div>}
          <h1 className="text-[30px] leading-[1.05] font-bold text-white sm:text-[38px]">{title}</h1>
          {children}
        </div>
        {aside && <div className="relative flex shrink-0 items-center gap-2">{aside}</div>}
      </div>
    </header>
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
          <h2 className="flex items-center gap-2 text-[17px] font-semibold">
            <span aria-hidden className="h-4 w-1 shrink-0 self-center rounded-full bg-blueprint" />
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
  /** One short line at most (UX-13): the page's help says the rest. */
  about?: React.ReactNode
  /** The one thing to do first: a button or link. */
  action?: React.ReactNode
  /** A message the site can send on WhatsApp that fills this page. */
  whatsapp?: string
  className?: string
}) {
  return (
    <div className={cn('flex flex-col items-center gap-3 rounded-2xl border-2 border-dashed border-blueprint-soft bg-card/60 px-5 py-8 text-center', className)}>
      {Icon && (
        <span className="flex size-10 items-center justify-center rounded-[14px] bg-blueprint-pale text-blueprint" aria-hidden>
          <Icon className="size-5" />
        </span>
      )}
      <div className="flex max-w-md flex-col gap-1">
        <h2 className="text-base font-semibold">{title}</h2>
        {about && <p className="text-sm text-muted-foreground">{about}</p>}
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

/**
 * UX-13: a page this role cannot open, without a paragraph about why: a lock, one line, the roles that can as
 * chips, and a way back. Replaces the two-sentence "X shows the company's rates. Only owners, ... can open it."
 */
export function NoAccess({ roles, back, className }: { roles: string[]; back?: React.ReactNode; className?: string }) {
  return (
    <div className={cn('flex flex-col items-center gap-3 py-16 text-center', className)}>
      <span className="flex size-10 items-center justify-center rounded-full bg-muted text-muted-foreground" aria-hidden>
        <Lock className="size-5" />
      </span>
      <p className="font-medium">Not open to your role</p>
      <ul className="flex flex-wrap justify-center gap-1.5" aria-label="Who can open it">
        {roles.map((r) => (
          <li key={r} className="rounded-full border px-2.5 py-0.5 text-xs text-muted-foreground">
            {r}
          </li>
        ))}
      </ul>
      {back}
    </div>
  )
}

/** UX-13: the WhatsApp message that does this, as a green chip instead of a sentence about it. */
export function SayOnWhatsApp({ text, className }: { text: string; className?: string }) {
  return (
    <p className={cn('inline-flex max-w-md items-start gap-2 rounded-lg bg-success-soft px-3 py-1.5 text-left text-sm text-success', className)}>
      <MessageSquareText className="mt-0.5 size-4 shrink-0" aria-hidden />
      <span className="font-medium">“{text}”</span>
    </p>
  )
}

export type TileTone = KpiTone

/**
 * UX-14: what the colours on a list mean, as dots with two or three words each, never a sentence
 * ("Green: the work measured earned at least..."). The longer meaning is in the page's help.
 */
export function Legend({ items, className }: { items: { tone: TileTone; label: string }[]; className?: string }) {
  return (
    <ul className={cn('flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground', className)} aria-label="What the colours mean">
      {items.map((i) => (
        <li key={i.label} className="inline-flex items-center gap-1.5">
          <span className={cn('size-2 shrink-0 rounded-full', KPI_TONE[i.tone].dot)} aria-hidden />
          {i.label}
        </li>
      ))}
    </ul>
  )
}

/**
 * One question on a home screen (UX-11): a label, a figure or short list, and the page that answers it in full.
 * The whole tile is the link, so every number on Home leads to its page. UX-15: drawn by the page kit's `Kpi`
 * (icon for the kind of figure, state by colour, "x of y" segments), as a card.
 */
export function Tile(props: Omit<KpiProps, 'to'> & { to: string }) {
  return <Kpi card {...props} />
}

/** A grid of tiles: one column on a phone, two on a tablet, three on a laptop. */
export const TileGrid = KpiGrid

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
      <h3 className="font-mono text-[10px] font-medium tracking-[0.12em] text-muted-foreground uppercase">{title}</h3>
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
