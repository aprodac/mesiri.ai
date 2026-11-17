import * as React from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'
import { KPI_ICON, guessKind, type KpiKind } from '@/lib/kpi-look'
import { cn } from '@/lib/utils'

// UX-15 (asked by Ilan 17 Nov 2026: "a better KPI design which can be used on every page"): one figure, one look,
// everywhere. It replaces four parts that did the same job differently: the DPR pages' StatStrip, the home screens'
// Tile, ui/kpi-card and the tile grids pages drew by hand. A figure reads at a glance by four things, never by a
// second line of words:
//   - an icon for what kind of figure it is (lib/kpi-look.ts: workers, money, issues ...),
//   - its state by colour (good, attention, bad, info; docs/DESIGN.md section 3), as a bar on top, a tinted ground,
//     the icon's tile and the figure itself,
//   - "x of y" drawn as y segments (up to 12) or a bar, and a share (0 to 1) as a bar,
//   - the figure large, the label short.
// Two containers: `KpiStrip` (the numbers of a page in one bordered strip; `StatStrip` is this) and `KpiGrid`
// (separate cards, for tiles that hold a list or lead to a page: `Tile`).

export type KpiTone = 'default' | 'good' | 'info' | 'attention' | 'bad'
/** `warn` is the strip's older name for `attention`. */
export type KpiToneIn = KpiTone | 'warn'

const tone = (t?: KpiToneIn): KpiTone => (t === 'warn' ? 'attention' : t ?? 'default')

export const KPI_TONE: Record<KpiTone, { value: string; icon: string; bar: string; ground: string; fill: string; dot: string }> = {
  default: { value: '', icon: 'bg-muted text-muted-foreground', bar: '', ground: '', fill: 'bg-foreground/45', dot: 'bg-muted-foreground/40' },
  good: { value: 'text-success', icon: 'bg-success-soft text-success', bar: 'before:bg-success', ground: 'bg-success-soft/35', fill: 'bg-success', dot: 'bg-success' },
  info: { value: 'text-info', icon: 'bg-info-soft text-info', bar: 'before:bg-info', ground: 'bg-info-soft/40', fill: 'bg-info', dot: 'bg-info' },
  attention: { value: 'text-draft', icon: 'bg-draft-soft text-draft', bar: 'before:bg-draft', ground: 'bg-draft-soft/50', fill: 'bg-draft', dot: 'bg-draft' },
  bad: { value: 'text-destructive', icon: 'bg-destructive/10 text-destructive', bar: 'before:bg-destructive', ground: 'bg-destructive/[0.05]', fill: 'bg-destructive', dot: 'bg-destructive' },
}

export type KpiProps = {
  label: string
  value?: React.ReactNode
  tone?: KpiToneIn
  /** What kind of figure it is; picks the icon from lib/kpi-look.ts. Guessed from the value and label if left out. */
  kind?: KpiKind
  /** An icon of the page's own, when no kind fits. `null` draws none. */
  icon?: React.ComponentType<{ className?: string }> | null
  /** A category's own colour for the icon tile (lib/expenses.ts PAID_VIA, lib/cost.ts), so the figure matches its
   * rows below. Only for categories; a state is `tone`. */
  iconClass?: string
  /** "x of y": the whole the figure is part of. Drawn as segments (up to 12) or a bar, and "of y" beside the figure. */
  of?: number
  /** How to write "of y" when it is not a plain number (₹ amounts). */
  ofLabel?: React.ReactNode
  /** A share from 0 to 1 drawn as a bar, when the figure is not a count of something. */
  share?: number
  /** A few words under the figure: "2 critical", "by work done". Hidden on phones. */
  hint?: React.ReactNode
  /** SCP-06: a figure wider than the pick says so: "Company", "Whole project". */
  tag?: string
  loading?: boolean
  /** The figure leads to its page. */
  to?: string
  /** The figure filters the list under it; `pressed` when it is the filter on. */
  onClick?: () => void
  pressed?: boolean
  /** A tour step's marker. */
  guide?: string
  className?: string
  children?: React.ReactNode
}

/** One figure in a strip: its props and a key when two share a label. */
export type KpiItem = KpiProps & { key?: string }

/** "x of y" as segments when y is small, else a bar; a share as a bar. */
export function KpiMeter({ value, of, share, tone: t }: { value?: number; of?: number; share?: number; tone?: KpiToneIn }) {
  const look = KPI_TONE[tone(t)]
  if (of !== undefined && value !== undefined && of > 0 && of <= 12 && Number.isInteger(of) && Number.isInteger(value)) {
    return (
      <span className="flex h-1.5 gap-0.5" role="img" aria-label={`${value} of ${of}`}>
        {Array.from({ length: of }, (_, i) => (
          <span key={i} className={cn('h-full flex-1 rounded-full', i < value ? look.fill : 'bg-muted')} />
        ))}
      </span>
    )
  }
  const part = share ?? (of !== undefined && value !== undefined && of > 0 ? value / of : undefined)
  if (part === undefined || !Number.isFinite(part)) return null
  const pct = Math.max(0, Math.min(100, part * 100))
  return (
    <span className="block h-1.5 overflow-hidden rounded-full bg-muted" role="img" aria-label={`${Math.round(pct)}%`}>
      <span className={cn('block h-full rounded-full', look.fill)} style={{ width: `${pct}%` }} />
    </span>
  )
}

const numberOf = (v: React.ReactNode): number | undefined => {
  if (typeof v === 'number') return v
  if (typeof v === 'string' && /^\s*[\d,]+(\.\d+)?\s*$/.test(v)) return Number(v.replace(/,/g, ''))
  return undefined
}

/** One figure. Inside a `KpiStrip` it is a cell; inside a `KpiGrid` a card. */
export function Kpi({ card = false, ...k }: KpiProps & { card?: boolean }) {
  const t = tone(k.tone)
  const look = KPI_TONE[t]
  const kind = k.kind ?? guessKind(k.label, k.value)
  const Icon = k.icon === null ? undefined : (k.icon ?? (kind && KPI_ICON[kind]))
  const n = numberOf(k.value)
  const showMeter = !k.loading && (k.share !== undefined || (k.of !== undefined && n !== undefined))
  const body = (
    <>
      <span className="flex min-w-0 items-center gap-1.5 text-[11px] font-medium text-muted-foreground sm:gap-2 sm:text-xs">
        {Icon && (
          <span className={cn('flex size-5 shrink-0 items-center justify-center rounded-md sm:size-6', k.iconClass ?? look.icon)} aria-hidden>
            <Icon className="size-3 sm:size-3.5" />
          </span>
        )}
        <span className="truncate">{k.label}</span>
        {k.tag && <span className="shrink-0 rounded bg-draft-soft px-1.5 py-px text-[10px] font-semibold text-draft">{k.tag}</span>}
        {k.to && <ArrowRight className="ml-auto size-3.5 shrink-0 opacity-0 transition-opacity group-hover:opacity-100" aria-hidden />}
      </span>
      {k.loading ? (
        <span className="h-6 w-16 animate-pulse rounded bg-muted sm:h-7" aria-label="Loading" />
      ) : (
        k.value !== undefined && (
          <span className={cn('flex min-w-0 items-baseline gap-1 text-lg leading-tight font-semibold tabular-nums sm:text-xl', look.value)}>
            <span className="truncate">{k.value}</span>
            {(k.ofLabel !== undefined || k.of !== undefined) && (
              <span className="shrink-0 text-xs font-normal text-muted-foreground">of {k.ofLabel ?? k.of?.toLocaleString('en-IN')}</span>
            )}
          </span>
        )
      )}
      {showMeter && <KpiMeter value={n} of={k.of} share={k.share} tone={t} />}
      {k.hint && <span className={cn('truncate text-[11px] text-muted-foreground sm:text-xs', !card && 'hidden sm:block')}>{k.hint}</span>}
      {k.children}
    </>
  )
  const cls = cn(
    'group relative flex min-w-0 flex-col gap-1 text-left',
    card ? 'overflow-hidden rounded-xl border bg-background px-3.5 py-3 sm:px-4' : 'flex-1 bg-background px-2.5 py-2 sm:px-4 sm:py-2.5',
    t !== 'default' && "before:absolute before:inset-x-0 before:top-0 before:h-[3px] before:content-['']",
    look.bar,
    look.ground,
    (k.to || k.onClick) && 'transition-colors hover:bg-muted/40',
    card && (k.to || k.onClick) && 'hover:border-foreground/25',
    k.pressed && 'ring-2 ring-foreground/70 ring-inset',
    k.className,
  )
  if (k.to) {
    return (
      <Link to={k.to} className={cls} data-guide={k.guide}>
        {body}
      </Link>
    )
  }
  if (k.onClick) {
    return (
      <button type="button" className={cls} onClick={k.onClick} aria-pressed={k.pressed} data-guide={k.guide}>
        {body}
      </button>
    )
  }
  return (
    <div className={cls} data-guide={k.guide}>
      {body}
    </div>
  )
}

/**
 * A page's key numbers in one bordered strip split by dividers (docs/DESIGN.md section 4): one row on a laptop,
 * rows of two to four on a phone.
 */
export function KpiStrip({
  stats,
  phoneCols,
  guide,
  className,
}: {
  stats: KpiItem[]
  /** Columns on phones when the values are long (e.g. "+365 bags"). */
  phoneCols?: 2
  guide?: string
  className?: string
}) {
  return (
    // The 1px gap over a border-coloured ground draws the rules in either layout.
    <div
      data-guide={guide}
      className={cn(
        'grid gap-px overflow-hidden rounded-xl border bg-border sm:flex',
        stats.length <= 2 || phoneCols === 2 ? 'grid-cols-2' : stats.length === 4 ? 'grid-cols-2 min-[420px]:grid-cols-4' : 'grid-cols-3',
        className,
      )}
    >
      {stats.map(({ key, ...s }, i) => (
        <Kpi
          key={key ?? s.label}
          {...s}
          className={cn(
            // In rows of three, the last one fills what is left of its row.
            phoneCols !== 2 && stats.length > 4 && i === stats.length - 1 && stats.length % 3 === 2 && 'col-span-2',
            phoneCols !== 2 && stats.length > 4 && i === stats.length - 1 && stats.length % 3 === 1 && 'col-span-3',
            phoneCols === 2 && stats.length % 2 === 1 && i === stats.length - 1 && 'col-span-2',
            s.className,
          )}
        />
      ))}
    </div>
  )
}

/** Figures as separate cards: one column on a phone, two on a tablet, three on a laptop (`cols` to change). */
export function KpiGrid({ children, className, guide }: { children: React.ReactNode; className?: string; guide?: string }) {
  return (
    <div data-guide={guide} className={cn('grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3', className)}>
      {children}
    </div>
  )
}
