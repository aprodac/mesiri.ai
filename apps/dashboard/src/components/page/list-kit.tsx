import * as React from 'react'
import { Link } from 'react-router-dom'
import type { LucideIcon } from 'lucide-react'
import { ArrowDownWideNarrow, ArrowRight, Search, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { TONE, useSlashFocus, type Tone } from '@/lib/list-kit'
import { cn } from '@/lib/utils'

// UX-45: the list page kit. Every list page (Cost control first, Planning next) is built from these parts, so they
// look and behave the same: a search box ("/" to jump, Esc to clear), a sort menu, a Clear button, a bar of states
// whose chips filter, action chips for what needs a person, pills for a row's state, and a "nothing matches" box.
// With Pager (pager.tsx), NumbersTable and ShowSwitch (numbers-view.tsx), KpiStrip (kpi.tsx) and ActionButton.
// The recipe, rules and a page skeleton: docs/design/LIST_PAGE_KIT.md.

/** A search box: "/" jumps here (one per page: `slash`), Esc clears. */
export function SearchBox({
  value,
  onChange,
  placeholder = 'Search',
  label,
  slash = true,
  size = 'md',
  className,
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  /** Read by screen readers: "Search materials". */
  label?: string
  slash?: boolean
  size?: 'sm' | 'md'
  className?: string
}) {
  const ref = React.useRef<HTMLInputElement>(null)
  useSlashFocus(ref, slash)
  return (
    <label className={cn('flex items-center gap-2 rounded-lg border bg-card px-2.5', size === 'sm' ? 'h-8' : 'h-9', className)}>
      <Search className="size-4 text-muted-foreground" aria-hidden />
      <span className="sr-only">{label ?? placeholder}</span>
      <input
        ref={ref}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => e.key === 'Escape' && onChange('')}
        placeholder={placeholder}
        className="w-36 bg-transparent text-sm outline-none sm:w-44"
      />
      {slash && (
        <kbd className="hidden rounded border bg-muted px-1 text-[10px] text-muted-foreground sm:inline" title="Press / to search">
          /
        </kbd>
      )}
    </label>
  )
}

/** The sort menu: the page's own orders ("Worst first", "Most spent", "Name"). */
export function SortSelect({
  value,
  options,
  onChange,
  label = 'Sort',
  size = 'md',
}: {
  value: string
  options: { value: string; label: string }[]
  onChange: (v: string) => void
  label?: string
  size?: 'sm' | 'md'
}) {
  return (
    <label className={cn('flex items-center gap-1.5 rounded-lg border bg-card px-2.5 text-sm', size === 'sm' ? 'h-8' : 'h-9')}>
      <ArrowDownWideNarrow className="size-4 text-muted-foreground" aria-hidden />
      <select value={value} onChange={(e) => onChange(e.target.value)} className="bg-transparent outline-none" aria-label={label}>
        {options.map((x) => (
          <option key={x.value} value={x.value}>
            {x.label}
          </option>
        ))}
      </select>
    </label>
  )
}

/** Shown only while a filter or search is on. */
export function ClearButton({ show, onClick, size = 'md' }: { show: boolean; onClick: () => void; size?: 'sm' | 'md' }) {
  if (!show) return null
  return (
    <Button variant="ghost" size="sm" className={cn('gap-1', size === 'sm' ? 'h-8' : 'h-9')} onClick={onClick}>
      <X className="size-3.5" aria-hidden /> Clear
    </Button>
  )
}

/** One state of a list: its count, word, icon and tone (a red / amber / green / grey, a stage, a status). */
export interface StateItem {
  value: string
  label: string
  count: number
  icon?: LucideIcon
  tone: Tone
  /** A colour class for its part of the bar when the tone's is not right (a cost centre's own colour). */
  bar?: string
}

/**
 * How the rows split by state: one bar, and a chip per state that filters the list (pressed again, all).
 * `extra` holds more chips (a dashed "need a fix"), `right` the search, sort and switches.
 */
export function StateBar({
  items,
  value,
  onChange,
  extra,
  right,
  guide,
}: {
  items: StateItem[]
  value: string
  onChange: (v: string) => void
  extra?: React.ReactNode
  right?: React.ReactNode
  guide?: string
}) {
  const total = items.reduce((t, i) => t + i.count, 0)
  return (
    <div className="flex flex-col gap-2 rounded-xl border bg-card p-3" data-guide={guide}>
      <div className="flex h-2.5 overflow-hidden rounded-full bg-muted" role="img" aria-label={items.map((i) => `${i.count} ${i.label}`).join(', ')}>
        {items.map((i) => i.count > 0 && <span key={i.value} className={i.bar ?? TONE[i.tone].dot} style={{ width: `${(i.count / Math.max(total, 1)) * 100}%` }} />)}
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        {items
          .filter((i) => i.count > 0)
          .map((i) => {
            const on = value === i.value
            return (
              <button
                key={i.value}
                type="button"
                aria-pressed={on}
                onClick={() => onChange(on ? '' : i.value)}
                className={cn('inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold transition', TONE[i.tone].pill, on ? 'ring-2 ring-foreground/70' : 'hover:ring-1 hover:ring-foreground/20')}
              >
                {i.icon && <i.icon className="size-3.5" aria-hidden />}
                <span className="tabular-nums">{i.count}</span> {i.label}
              </button>
            )
          })}
        {extra}
        {right && <span className="ml-auto flex flex-wrap items-center gap-2">{right}</span>}
      </div>
    </div>
  )
}

/** A dashed chip that filters to rows needing something ("3 need a fix", "8 short to finish"). */
export function ToggleChip({ on, onClick, icon: Icon, count, label, tone = 'muted', title }: { on: boolean; onClick: () => void; icon: LucideIcon; count: number; label: string; tone?: Tone; title?: string }) {
  if (count <= 0) return null
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      title={title}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border border-dashed px-2.5 py-1 text-xs font-semibold transition',
        on ? 'border-foreground bg-foreground text-background' : tone === 'muted' ? 'hover:border-foreground/40' : cn(TONE[tone].text, 'border-current/50 hover:border-current'),
      )}
    >
      <Icon className="size-3.5" aria-hidden />
      <span className="tabular-nums">{count}</span> {label}
    </button>
  )
}

/** Something a person should do, as one line: an icon, the figure in bold, a few words, the link. */
export function ActionChip({ icon: Icon, to, action, tone = 'attention', children }: { icon: LucideIcon; to: string; action: string; tone?: Tone; children: React.ReactNode }) {
  const body = (
    <>
      <span className={cn('flex size-7 shrink-0 items-center justify-center rounded-md', TONE[tone].pill)} aria-hidden>
        <Icon className="size-3.5" />
      </span>
      <span className="min-w-0 flex-1 text-sm">{children}</span>
      <span className="inline-flex shrink-0 items-center gap-1 text-xs font-semibold">
        {action} <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden />
      </span>
    </>
  )
  const cls = 'group flex items-center gap-2.5 rounded-xl border bg-card px-3 py-2 transition-colors hover:bg-muted/40'
  return to.startsWith('#') ? <a href={to} className={cls}>{body}</a> : <Link to={to} className={cls}>{body}</Link>
}

/** A note about the figures (what they leave out), as a small chip; a link when it can be fixed. */
export function NoteChip({ icon: Icon, tone = 'muted', to, children }: { icon: LucideIcon; tone?: Tone; to?: string; children: React.ReactNode }) {
  const cls = cn('inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs', tone === 'muted' ? 'border bg-card text-muted-foreground' : TONE[tone].pill, to && 'hover:ring-1 hover:ring-foreground/20')
  const body = (
    <>
      <Icon className="size-3.5 shrink-0" aria-hidden />
      <span>{children}</span>
      {to && <ArrowRight className="size-3" aria-hidden />}
    </>
  )
  if (!to) return <span className={cls}>{body}</span>
  return to.startsWith('#') ? <a href={to} className={cls}>{body}</a> : <Link to={to} className={cls}>{body}</Link>
}

/** A row's state in a word or a figure: "₹3.6 L over", "Enough", "Too early". */
export function Pill({ tone, icon: Icon, children, size = 'sm', title }: { tone: Tone; icon?: LucideIcon; children: React.ReactNode; size?: 'xs' | 'sm'; title?: string }) {
  return (
    <span
      title={title}
      className={cn(
        'inline-flex shrink-0 items-center gap-1 rounded-full font-semibold whitespace-nowrap tabular-nums',
        size === 'xs' ? 'px-1.5 py-px text-[11px]' : 'px-2 py-0.5 text-xs',
        TONE[tone].pill,
      )}
    >
      {Icon && <Icon className="size-3" aria-hidden />}
      {children}
    </span>
  )
}

/** Why a row is its state, in a few words (the full sentence on hover), and its fix as a link. */
export function ReasonChip({ tone, icon: Icon, label, title, fix }: { tone: Tone; icon?: LucideIcon; label: string; title?: string; fix?: { to: string; label: string } | null }) {
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <span className={cn('inline-flex items-center gap-1 rounded-md px-1.5 py-px text-[11px] font-medium', TONE[tone].pill)} title={title}>
        {Icon && <Icon className="size-3" aria-hidden />}
        {label}
      </span>
      {fix && (
        <Link to={fix.to} className="inline-flex items-center gap-0.5 text-[11px] font-semibold hover:underline" onClick={(e) => e.stopPropagation()}>
          {fix.label} <ArrowRight className="size-3" aria-hidden />
        </Link>
      )}
    </span>
  )
}

/** Filters left nothing: say so, offer Clear. (An empty page with no filters is EmptyState in the page kit.) */
export function NoMatch({ noun, onClear }: { noun: string; onClear: () => void }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed bg-card py-10 text-center">
      <Search className="size-5 text-muted-foreground" aria-hidden />
      <p className="text-sm font-medium">No {noun} matches</p>
      <Button variant="outline" size="sm" onClick={onClear}>
        Clear filters
      </Button>
    </div>
  )
}

/** The row of search, filters and sort above a list. `right` sits at the end (sort, switches, export). */
export function ListToolbar({ children, right, guide }: { children: React.ReactNode; right?: React.ReactNode; guide?: string }) {
  return (
    <div className="flex flex-wrap items-center gap-2" data-guide={guide}>
      {children}
      {right && <span className="ml-auto flex flex-wrap items-center gap-2">{right}</span>}
    </div>
  )
}

/** Rows ticked: how many, what to do with them, and a way to untick all. Shown only while some are ticked. */
export function BulkBar({ count, onClear, children }: { count: number; onClear: () => void; children: React.ReactNode }) {
  if (count <= 0) return null
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-foreground/20 bg-foreground px-3 py-2 text-sm text-background" role="region" aria-label="Picked rows">
      <span className="font-semibold tabular-nums">{count} picked</span>
      {children}
      <button type="button" className="ml-auto inline-flex items-center gap-1 text-xs opacity-80 hover:opacity-100" onClick={onClear}>
        <X className="size-3.5" aria-hidden /> Clear
      </button>
    </div>
  )
}
