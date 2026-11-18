import * as React from 'react'
import { Link } from 'react-router-dom'
import type { LucideIcon } from 'lucide-react'
import { ChevronLeft, ChevronRight, Clock, MessageSquarePlus, Radio, RefreshCw, TriangleAlert } from 'lucide-react'
import { appNow } from '@/lib/clock'
import { openTellMesiri } from '@/lib/tell-mesiri-events'
import { cn } from '@/lib/utils'

// UX-66 (asked 18 Nov 2026: "the Today page looks so boring"): the day at a glance in one card, in the brand's
// charcoal with the hazard stripe. The greeting and the day; a ring of sites reported; the day's figures; the time
// left before reports close; what the day still needs as chips; the day's moves (previous, next, Live, Tell Mesiri).
// It replaces the page header, the figures strip and the "Needs your attention" box (the same figures and lines).

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

function greeting(now: Date): string {
  const h = now.getHours()
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening'
}

/** "2h 10m left" before the cutoff ("18:00"), "closed at 6:00 pm" after it; null without one. */
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

function Ring({ done, of }: { done: number; of: number }) {
  const r = 34
  const c = 2 * Math.PI * r
  const share = of ? done / of : 0
  const full = of > 0 && done >= of
  return (
    <div className="relative size-[88px] shrink-0" role="img" aria-label={`${done} of ${of} sites reported`}>
      <svg viewBox="0 0 80 80" className="size-full -rotate-90">
        <circle cx="40" cy="40" r={r} fill="none" stroke="currentColor" strokeWidth="7" className="text-white/10" />
        <circle
          cx="40"
          cy="40"
          r={r}
          fill="none"
          strokeWidth="7"
          strokeLinecap="round"
          stroke={full ? '#4ADE80' : '#FACC15'}
          strokeDasharray={c}
          strokeDashoffset={c * (1 - share)}
          className="transition-[stroke-dashoffset] duration-700 ease-out"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center leading-none">
        <span className="text-2xl font-semibold tabular-nums text-white">
          {done}
          <span className="text-sm font-medium text-white/50">/{of}</span>
        </span>
        <span className="mt-1 text-[10px] font-medium tracking-wide text-white/60 uppercase">sites in</span>
      </div>
    </div>
  )
}

export function TodayHero({
  name,
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
  showLive,
  canTell,
}: {
  name: string
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
  showLive: boolean
  canTell: boolean
}) {
  const [now] = React.useState(() => appNow())
  const first = name.trim().split(/\s+/)[0]
  const left = isToday ? cutoffLine(cutoff, now) : null
  const dayBtn = 'flex size-8 items-center justify-center rounded-lg text-white/80 transition-colors hover:bg-white/10 hover:text-white disabled:opacity-30 disabled:hover:bg-transparent focus-visible:outline-2 focus-visible:outline-[#FACC15]'
  return (
    <section
      aria-label="Your day"
      className="relative overflow-hidden rounded-2xl border border-[#34302A] bg-[#1F1D1A] text-white shadow-sm dark:border-border dark:bg-[#141517]"
    >
      <div aria-hidden className="h-1.5 bg-[repeating-linear-gradient(135deg,#1a1d21_0_8px,#facc15_8px_16px)]" />
      {/* A soft glow in the corner, so the card is not a flat slab. */}
      <div aria-hidden className="pointer-events-none absolute -top-24 -right-16 size-72 rounded-full bg-[#FACC15]/10 blur-3xl" />
      <div className="relative flex flex-col gap-5 p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-sm text-white/60">
              {dateLabel}
              {scopeLabel && <span className="text-white/40"> · {scopeLabel}</span>}
            </p>
            <h1 className="mt-0.5 text-2xl font-semibold tracking-tight sm:text-[28px]">
              {isToday ? `${greeting(now)}${first ? `, ${first}` : ''}` : 'A past day'}
            </h1>
          </div>
          <div className="flex items-center gap-1.5">
            {isToday && canTell && (
              <button
                type="button"
                onClick={() => openTellMesiri()}
                className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[#FACC15] px-3 text-sm font-semibold text-[#1F1D1A] shadow-sm transition-colors hover:bg-[#FDE047] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#FACC15]"
              >
                <MessageSquarePlus className="size-4" /> <span className="hidden sm:inline">Tell Mesiri</span>
              </button>
            )}
            {showLive && (
              <Link to="/live" className="hidden h-8 items-center gap-1.5 rounded-lg border border-white/15 px-2.5 text-sm text-white/90 hover:bg-white/10 sm:inline-flex" title="Watch every message to Mesiri land">
                <Radio className="size-4 text-[#FACC15]" /> Live
              </Link>
            )}
            <div className="flex items-center rounded-lg border border-white/15" data-guide="today.day">
              <button type="button" className={dayBtn} onClick={() => onDay(-1)} title="Previous day" aria-label="Previous day">
                <ChevronLeft className="size-4" />
              </button>
              {!isToday && (
                <button type="button" className="h-8 rounded-lg px-2 text-sm text-white/90 hover:bg-white/10" onClick={onToday}>
                  Today
                </button>
              )}
              <button type="button" className={dayBtn} onClick={() => onDay(1)} disabled={isToday} title="Next day" aria-label="Next day">
                <ChevronRight className="size-4" />
              </button>
            </div>
            <button type="button" className={cn(dayBtn, 'border border-white/15')} onClick={onRefresh} disabled={refreshing} title="Refresh" aria-label="Refresh">
              <RefreshCw className={cn('size-4', refreshing && 'animate-spin')} />
            </button>
          </div>
        </div>

        <div className="flex flex-col gap-5 md:flex-row md:items-center">
          <div className="flex items-center gap-4">
            <Ring done={reported} of={sites} />
            <div className="min-w-0">
              <p className="text-base font-semibold">
                {sites === 0 ? 'No sites yet' : reported >= sites ? 'Every site has reported' : `${sites - reported} still to report`}
              </p>
              {left ? (
                <p className={cn('mt-1 inline-flex items-center gap-1.5 text-sm', left.late ? 'text-[#FACC15]' : 'text-white/60')}>
                  <Clock className="size-3.5" aria-hidden /> {left.text}
                </p>
              ) : (
                <p className="mt-1 text-sm text-white/60">{isToday ? 'Updates come in from WhatsApp' : 'What the sites sent that day'}</p>
              )}
            </div>
          </div>
          <div className="grid flex-1 grid-cols-2 gap-2 sm:grid-cols-4 md:ml-4 md:border-l md:border-white/10 md:pl-6">
            {figures.map((f) => (
              <div key={f.label} className="rounded-xl bg-white/[0.04] px-3 py-2.5 ring-1 ring-white/[0.06]">
                <div className="flex items-center gap-1.5 text-[11px] font-medium tracking-wide text-white/55 uppercase">
                  <f.icon className={cn('size-3.5', f.bad && f.value > 0 ? 'text-red-400' : 'text-[#FACC15]')} aria-hidden />
                  <span className="truncate">{f.label}</span>
                </div>
                <div className={cn('mt-1 text-2xl font-semibold tabular-nums', f.value === 0 && 'text-white/35', f.bad && f.value > 0 && 'text-red-400')}>
                  {f.value === 0 ? '–' : f.value}
                </div>
              </div>
            ))}
          </div>
        </div>

        {lines.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 border-t border-white/10 pt-4">
            {lines.slice(0, 4).map((l) => (
              <span key={l.key} className="inline-flex max-w-full items-center gap-1.5 rounded-full bg-[#FACC15]/12 px-2.5 py-1 text-xs text-[#FDE68A] ring-1 ring-[#FACC15]/25" title={l.note}>
                <TriangleAlert className="size-3.5 shrink-0" aria-hidden />
                <span className="truncate">{l.text}</span>
              </span>
            ))}
            {lines.length > 4 && <span className="text-xs text-white/50">+{lines.length - 4} more</span>}
          </div>
        )}
      </div>
    </section>
  )
}
