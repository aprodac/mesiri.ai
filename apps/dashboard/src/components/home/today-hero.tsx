import * as React from 'react'
import type { LucideIcon } from 'lucide-react'
import { ChevronLeft, ChevronRight, Clock, MessageSquarePlus, RefreshCw, TriangleAlert } from 'lucide-react'
import { appNow } from '@/lib/clock'
import { openTellMesiri } from '@/lib/tell-mesiri-events'
import { cn } from '@/lib/utils'

// UX-66 (asked 18 Nov 2026: "the Today page looks so boring"; a dark day card was tried and rejected, then this look
// was picked from three; UX-68 moved the greeting to Home): the day on the page itself, the day's moves beside it, then five figure
// cards: sites reported (with a bar and the time left to the cutoff), workers, work done, photos, open issues, each
// with its own icon colour. What the day still needs follows as chips. It replaces the page header, the figures strip
// and the "Needs your attention" box (the same figures and lines).

export interface HeroFigure {
  label: string
  value: number
  icon: LucideIcon
  /** Red when above zero (open issues). */
  bad?: boolean
}

export interface HeroLine {
  key: string
  text: string
  note?: string
}

/** "2h 10m to 6:00 pm" before the cutoff ("18:00"), "Reports closed at 6:00 pm" after it; null without one. */
function cutoffLine(cutoff: string | null, now: Date): { text: string; late: boolean } | null {
  if (!cutoff) return null
  const [h, m] = cutoff.split(':').map(Number)
  if (Number.isNaN(h)) return null
  const at = new Date(now)
  at.setHours(h, m || 0, 0, 0)
  const clock = at.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  const left = Math.round((at.getTime() - now.getTime()) / 60_000)
  if (left <= 0) return { text: `Reports closed at ${clock}`, late: false }
  const text = left >= 60 ? `${Math.floor(left / 60)}h ${left % 60}m to ${clock}` : `${left} min to ${clock}`
  return { text, late: left <= 60 }
}

/** One icon colour per figure, the same in every role's Today. */
const FIG_TONE = [
  'bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300',
  'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300',
  'bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-300',
  'bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300',
]

export function TodayHero({
  isToday,
  dateLabel,
  scopeLabel,
  reported,
  sites,
  figures,
  cutoff,
  lines,
  onDay,
  onToday,
  onRefresh,
  refreshing,
  canTell,
}: {
  isToday: boolean
  dateLabel: string
  scopeLabel: string | null
  reported: number
  sites: number
  figures: HeroFigure[]
  cutoff: string | null
  lines: HeroLine[]
  onDay: (delta: number) => void
  onToday: () => void
  onRefresh: () => void
  refreshing: boolean
  canTell: boolean
}) {
  const [now] = React.useState(() => appNow())
  const left = isToday ? cutoffLine(cutoff, now) : null
  const all = sites > 0 && reported >= sites
  const btn = 'flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-30 disabled:hover:bg-transparent'
  return (
    <section aria-label="Your day" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">{isToday ? 'Today' : 'A past day'}</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {dateLabel}
            {scopeLabel ? ` · ${scopeLabel}` : ''}
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          {isToday && canTell && (
            <button
              type="button"
              onClick={() => openTellMesiri()}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-primary px-3 text-sm font-semibold text-primary-foreground shadow-xs transition-colors hover:bg-primary/90"
            >
              <MessageSquarePlus className="size-4" /> <span className="hidden sm:inline">Tell Mesiri</span>
            </button>
          )}
          <div className="flex items-center rounded-lg border bg-card" data-guide="today.day">
            <button type="button" className={btn} onClick={() => onDay(-1)} title="Previous day" aria-label="Previous day">
              <ChevronLeft className="size-4" />
            </button>
            {!isToday && (
              <button type="button" className="h-8 rounded-lg px-2 text-sm hover:bg-muted" onClick={onToday}>
                Today
              </button>
            )}
            <button type="button" className={btn} onClick={() => onDay(1)} disabled={isToday} title="Next day" aria-label="Next day">
              <ChevronRight className="size-4" />
            </button>
          </div>
          <button type="button" className={cn(btn, 'border bg-card')} onClick={onRefresh} disabled={refreshing} title="Refresh" aria-label="Refresh">
            <RefreshCw className={cn('size-4', refreshing && 'animate-spin')} />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <div className="col-span-2 flex flex-col justify-between rounded-xl border bg-card p-3.5 shadow-xs sm:col-span-1">
          <div className="flex items-center justify-between gap-2 text-xs font-medium text-muted-foreground">
            Sites reported
            {sites > 0 && (
              <span className={cn('rounded-full px-1.5 py-px text-[11px] font-semibold', all ? 'bg-success-soft text-success' : 'bg-draft-soft text-draft')}>
                {all ? 'All in' : `${sites - reported} to go`}
              </span>
            )}
          </div>
          <div className="mt-1 text-2xl font-semibold tabular-nums">
            {reported}
            <span className="text-base text-muted-foreground">/{sites}</span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted" role="img" aria-label={`${reported} of ${sites} sites reported`}>
            <div className={cn('h-full rounded-full transition-[width] duration-700', all ? 'bg-success' : 'bg-primary')} style={{ width: `${sites ? (reported / sites) * 100 : 0}%` }} />
          </div>
          {left && (
            <p className={cn('mt-2 flex items-center gap-1 text-xs', left.late ? 'font-medium text-draft' : 'text-muted-foreground')}>
              <Clock className="size-3" aria-hidden /> {left.text}
            </p>
          )}
        </div>
        {figures.map((f, i) => (
          <div key={f.label} className="flex items-center gap-3 rounded-xl border bg-card p-3.5 shadow-xs">
            <span className={cn('flex size-10 shrink-0 items-center justify-center rounded-lg', FIG_TONE[i % FIG_TONE.length])} aria-hidden>
              <f.icon className="size-5" />
            </span>
            <div className="min-w-0">
              <div className={cn('text-2xl font-semibold tabular-nums', !f.value && 'text-muted-foreground/50', f.bad && f.value > 0 && 'text-destructive')}>{f.value}</div>
              <div className="truncate text-xs text-muted-foreground">{f.label}</div>
            </div>
          </div>
        ))}
      </div>

      {lines.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {lines.slice(0, 4).map((l) => (
            <span key={l.key} className="inline-flex max-w-full items-center gap-1.5 rounded-full bg-draft-soft px-2.5 py-1 text-xs font-medium text-draft" title={l.note}>
              <TriangleAlert className="size-3.5 shrink-0" aria-hidden />
              <span className="truncate">{l.text}</span>
            </span>
          ))}
          {lines.length > 4 && <span className="self-center text-xs text-muted-foreground">+{lines.length - 4} more</span>}
        </div>
      )}
    </section>
  )
}
