import * as React from 'react'
import { CalendarDays, X } from 'lucide-react'
import { Calendar } from '@/components/ui/calendar'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { appNow } from '@/lib/clock'
import { cn } from '@/lib/utils'

/** "2026-11-14" as a local date (no time zone shift), or undefined. */
function parse(value: string | null | undefined): Date | undefined {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value ?? '')
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : undefined
}

/** A local date as "2026-11-14". */
function iso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const SHOW = new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })

/**
 * The one date field (asked 17 Nov: "the date component use a Radix or shadcn everywhere"): a button showing the date
 * ("14 Nov 2026") that opens the calendar (shadcn: Radix Popover + react-day-picker). Values are "YYYY-MM-DD" text,
 * exactly as the native date input gave them, so a form only swaps `<Input type="date" onChange={e => set(e.target.value)}>`
 * for `<DatePicker onChange={set}>`. `min` / `max` limit the days; `clearable` adds a clear button.
 */
export function DatePicker({
  id,
  value,
  onChange,
  min,
  max,
  placeholder = 'Pick a date',
  disabled,
  required,
  clearable = !required,
  className,
  'aria-label': ariaLabel,
  'data-guide': guide,
}: {
  id?: string
  value: string | null | undefined
  onChange: (value: string) => void
  min?: string
  max?: string
  placeholder?: string
  disabled?: boolean
  required?: boolean
  clearable?: boolean
  className?: string
  'aria-label'?: string
  'data-guide'?: string
}) {
  const [open, setOpen] = React.useState(false)
  const picked = parse(value)
  const from = parse(min)
  const to = parse(max)
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <div className={cn('relative inline-flex w-full min-w-0', className)} data-guide={guide}>
        <PopoverTrigger asChild>
          <button
            id={id}
            type="button"
            disabled={disabled}
            aria-label={ariaLabel}
            aria-required={required || undefined}
            className={cn(
              'flex h-9 w-full min-w-0 items-center gap-2 rounded-md border border-input bg-background px-3 text-left text-sm shadow-xs outline-none',
              'focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50',
              clearable && picked && 'pr-8',
            )}
          >
            <CalendarDays className="size-4 shrink-0 text-muted-foreground" aria-hidden />
            <span className={cn('truncate tabular-nums', !picked && 'text-muted-foreground')}>{picked ? SHOW.format(picked) : placeholder}</span>
          </button>
        </PopoverTrigger>
        {clearable && picked && !disabled && (
          <button
            type="button"
            onClick={() => onChange('')}
            className="absolute right-1.5 top-1/2 inline-flex size-6 -translate-y-1/2 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
            aria-label="Clear the date"
          >
            <X className="size-3.5" aria-hidden />
          </button>
        )}
      </div>
      <PopoverContent className="w-auto p-2" align="start">
        <Calendar
          mode="single"
          selected={picked}
          defaultMonth={picked ?? from ?? appNow()}
          captionLayout="dropdown"
          startMonth={new Date(2000, 0)}
          endMonth={new Date(2040, 11)}
          disabled={[...(from ? [{ before: from }] : []), ...(to ? [{ after: to }] : [])]}
          onSelect={(d) => {
            if (d) onChange(iso(d))
            setOpen(false)
          }}
          autoFocus
        />
      </PopoverContent>
    </Popover>
  )
}
