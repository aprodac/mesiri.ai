import * as React from 'react'
import { DayPicker, getDefaultClassNames } from 'react-day-picker'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { appNow } from '@/lib/clock'
import { cn } from '@/lib/utils'

// shadcn/ui Calendar (react-day-picker 9), in the app's colours. "Today" is the app's today (lib/clock.ts): in a sample
// company that is its own date (SS-74a), not the computer's.
export function Calendar({ className, classNames, ...props }: React.ComponentProps<typeof DayPicker>) {
  const d = getDefaultClassNames()
  return (
    <DayPicker
      today={appNow()}
      showOutsideDays
      className={cn('p-1', className)}
      classNames={{
        root: cn(d.root, 'w-fit'),
        months: 'relative flex flex-col gap-4',
        month: 'flex w-full flex-col gap-3',
        nav: 'absolute inset-x-0 top-0 flex items-center justify-between',
        button_previous: 'inline-flex size-8 items-center justify-center rounded-md hover:bg-muted disabled:opacity-40',
        button_next: 'inline-flex size-8 items-center justify-center rounded-md hover:bg-muted disabled:opacity-40',
        month_caption: 'flex h-8 items-center justify-center px-8 text-sm font-semibold',
        dropdowns: 'flex items-center gap-1.5 text-sm font-medium',
        dropdown_root: 'relative rounded-md border px-1 has-focus:ring-2 has-focus:ring-ring',
        dropdown: 'absolute inset-0 opacity-0',
        caption_label: 'flex items-center gap-1 text-sm font-semibold',
        month_grid: 'w-full border-collapse',
        weekdays: 'flex',
        weekday: 'w-9 text-center text-[0.75rem] font-normal text-muted-foreground',
        week: 'mt-1 flex w-full',
        day: 'relative size-9 p-0 text-center text-sm',
        day_button: 'inline-flex size-9 items-center justify-center rounded-md tabular-nums hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
        selected: '[&>button]:bg-primary [&>button]:font-semibold [&>button]:text-primary-foreground [&>button]:hover:bg-primary',
        today: '[&>button]:ring-1 [&>button]:ring-foreground/40',
        outside: 'text-muted-foreground/50',
        disabled: 'text-muted-foreground/40 [&>button]:pointer-events-none',
        hidden: 'invisible',
        ...classNames,
      }}
      components={{
        Chevron: ({ orientation, className: c }) =>
          orientation === 'left' ? <ChevronLeft className={cn('size-4', c)} /> : <ChevronRight className={cn('size-4', c)} />,
      }}
      {...props}
    />
  )
}
