import * as React from 'react'
import { cn } from '@/lib/utils'

// WEB-48: one figure, its label and a short muted line -- the stat strip look of DESIGN.md. No trend arrow and no
// sparkline: the old card drew hard-coded lines ("+12.4% MoM", made-up arrays) that read as real data. A trend comes
// back only when it is computed from real numbers.
export interface KpiCardProps extends React.HTMLAttributes<HTMLDivElement> {
  title: string
  value: React.ReactNode
  description?: React.ReactNode
  icon?: React.ReactNode
  //: "warn" draws the figure in the draft colour (something needs doing), "bad" in red, "good" in green.
  tone?: 'warn' | 'bad' | 'good'
}

const TONE = { warn: 'text-draft', bad: 'text-destructive', good: 'text-success' } as const

export function KpiCard({ title, value, description, icon, tone, className, ...props }: KpiCardProps) {
  return (
    <div className={cn('flex min-w-0 flex-col gap-1 rounded-lg border bg-card px-3 py-2.5', className)} {...props}>
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-xs font-medium text-muted-foreground">{title}</span>
        {icon && (
          <span className="shrink-0 text-muted-foreground [&_svg]:size-3.5" aria-hidden="true">
            {icon}
          </span>
        )}
      </div>
      <div className={cn('truncate text-lg font-semibold tabular-nums leading-tight', tone && TONE[tone])}>{value}</div>
      {description && <div className="truncate text-xs text-muted-foreground">{description}</div>}
    </div>
  )
}
