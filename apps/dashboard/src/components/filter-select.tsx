import * as React from 'react'
import { CalendarDays } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import type { Period } from '@/lib/period'

// WEB-40: filters as compact dropdowns instead of rows of pill buttons, so a
// page's toolbar fits on one line: an icon, the chosen value, a caret.

export function FilterSelect<T extends string>({
  label,
  value,
  onChange,
  options,
  icon: Icon,
  className,
}: {
  /** What the filter is, for screen readers ("Period", "Direction"). */
  label: string
  value: T
  onChange: (value: T) => void
  options: { value: T; label: string }[]
  icon?: React.ComponentType<{ className?: string }>
  className?: string
}) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v as T)}>
      <SelectTrigger className={cn('h-8 gap-1.5 rounded-md bg-background [&>span]:flex-1 [&>span]:text-left', className)} aria-label={label}>
        {Icon && <Icon className="size-3.5 text-muted-foreground" />}
        <SelectValue />
      </SelectTrigger>
      <SelectContent align="end">
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

const PERIOD_WORDS: { value: Period; label: string }[] = [
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
  { value: 'month', label: 'This month' },
  { value: 'all', label: 'All time' },
  { value: 'custom', label: 'Pick dates…' },
]

/** The period dropdown; "Pick dates…" shows two date boxes beside it. */
export function PeriodSelect({
  value,
  onChange,
  from,
  to,
  onFrom,
  onTo,
}: {
  value: Period
  onChange: (value: Period) => void
  from: string
  to: string
  onFrom: (value: string) => void
  onTo: (value: string) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <FilterSelect label="Period" value={value} onChange={onChange} options={PERIOD_WORDS} icon={CalendarDays} className="w-[150px]" />
      {value === 'custom' && (
        <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <Input type="date" aria-label="From" value={from} max={to || undefined} onChange={(e) => onFrom(e.target.value)} className="h-8 w-[140px] dark:[color-scheme:dark]" />
          to
          <Input type="date" aria-label="To" value={to} min={from || undefined} onChange={(e) => onTo(e.target.value)} className="h-8 w-[140px] dark:[color-scheme:dark]" />
        </span>
      )}
    </div>
  )
}
