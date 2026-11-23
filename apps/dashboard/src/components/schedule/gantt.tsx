import * as React from 'react'
import { CalendarPlus, Diamond, Flame, GripVertical } from 'lucide-react'
import { cn } from '@/lib/utils'
import { dayNum, isoOf, shortDay, STATE_WORDS, workCalendar, worksOn, type Activity, type ActivityState, type Schedule } from '@/lib/schedule'

// ST-04: the Gantt chart. One row per activity: the planned bar, the part done (measured from site reports),
// the overrun the site's pace forecasts (striped), today's line, milestones as diamonds, the "starts after"
// links, the critical path outlined. A bar can be dragged to new days by those who plan (the page asks before
// moving the ones after it).

/** QA Step 11: "fit" shows the whole job, start to handover, in the width there is. */
export type Zoom = 'week' | 'month' | 'fit'
const DAY_WIDTH: Record<Exclude<Zoom, 'fit'>, number> = { week: 30, month: 9 }
const ROW = 46
const HEAD = 46
export const NAME_COL = 300

// UX-53: the state tokens (docs/DESIGN.md §3), so the bars match every other page and read in dark mode too.
export const STATE_BAR: Record<ActivityState, { bar: string; fill: string; chip: string; dot: string; row: string; edge: string }> = {
  late: { bar: 'bg-destructive/15', fill: 'bg-destructive', chip: 'bg-destructive/10 text-destructive', dot: 'bg-destructive', row: 'bg-destructive/[0.04]', edge: 'before:bg-destructive' },
  behind: { bar: 'bg-draft/25', fill: 'bg-draft', chip: 'bg-draft-soft text-draft', dot: 'bg-draft', row: 'bg-draft-soft/40', edge: 'before:bg-draft' },
  on_track: { bar: 'bg-info-soft', fill: 'bg-info', chip: 'bg-info-soft text-info', dot: 'bg-info', row: '', edge: 'before:bg-info' },
  not_started: { bar: 'bg-muted', fill: 'bg-muted-foreground', chip: 'bg-muted text-muted-foreground', dot: 'bg-muted-foreground/50', row: '', edge: 'before:bg-muted-foreground/40' },
  done: { bar: 'bg-success-soft', fill: 'bg-success', chip: 'bg-success-soft text-success', dot: 'bg-success', row: '', edge: 'before:bg-success' },
  unscheduled: { bar: 'bg-muted', fill: 'bg-muted-foreground', chip: 'bg-muted text-muted-foreground', dot: 'bg-muted-foreground/50', row: '', edge: 'before:bg-muted-foreground/40' },
}

export function range(schedule: Schedule, acts: Activity[]): { from: number; to: number } {
  const days: number[] = [dayNum(schedule.today)]
  for (const a of acts) {
    if (a.start) days.push(dayNum(a.start))
    if (a.end) days.push(dayNum(a.end))
    if (a.forecast_end) days.push(dayNum(a.forecast_end))
  }
  if (schedule.project.start_date) days.push(dayNum(schedule.project.start_date))
  if (schedule.project.planned_finish) days.push(dayNum(schedule.project.planned_finish))
  return { from: Math.min(...days) - 4, to: Math.max(...days) + 10 }
}

export function Gantt({
  schedule,
  activities,
  zoom,
  selectedId,
  onSelect,
  canEdit,
  onMove,
  onAddDates,
  scrollToToday,
}: {
  schedule: Schedule
  activities: Activity[]
  zoom: Zoom
  selectedId: string | null
  onSelect: (id: string) => void
  canEdit: boolean
  onMove: (id: string, days: number) => void
  onAddDates: (id: string) => void
  scrollToToday: number
}) {
  const { from, to } = React.useMemo(() => range(schedule, schedule.activities), [schedule])
  const cal = React.useMemo(() => workCalendar(schedule.project), [schedule.project])
  const scroller = React.useRef<HTMLDivElement>(null)
  const [room, setRoom] = React.useState(0)
  React.useEffect(() => {
    const el = scroller.current
    if (!el) return
    const watch = new ResizeObserver(() => setRoom(el.clientWidth))
    watch.observe(el)
    setRoom(el.clientWidth)
    return () => watch.disconnect()
  }, [])
  const dayW = zoom === 'fit' ? Math.max(room / (to - from + 1), 0.8) : DAY_WIDTH[zoom]
  const width = (to - from + 1) * dayW
  const today = dayNum(schedule.today)
  const [drag, setDrag] = React.useState<{ id: string; x0: number; dx: number } | null>(null)
  const x = (iso: string) => (dayNum(iso) - from) * dayW
  const row = new Map(activities.map((a, i) => [a.id, i]))

  // Open where the eye is needed: the start of the earliest late / behind work, or a little before today.
  const anchor = React.useMemo(() => {
    const starts = schedule.activities.filter((a) => (a.state === 'late' || a.state === 'behind') && a.start).map((a) => dayNum(a.start!))
    return Math.min(today, ...starts)
  }, [schedule, today])
  React.useEffect(() => {
    const el = scroller.current
    if (!el) return
    if (zoom === 'fit') { el.scrollLeft = 0; return }
    const toToday = (today - from) * dayW - el.clientWidth * 0.3
    const toAnchor = (anchor - from) * dayW - 24
    el.scrollLeft = Math.max(0, scrollToToday ? toToday : Math.min(toToday, toAnchor))
  }, [scrollToToday, zoom, today, anchor, from, dayW])

  // Header: months on top; days (week zoom) or week starts (month zoom) below.
  const months: { left: number; width: number; label: string }[] = []
  // weekend: a day site does not work (the project's days off and holidays), shaded.
  const ticks: { left: number; label: string; weekend: boolean; monday: boolean }[] = []
  for (let n = from; n <= to; n++) {
    const iso = isoOf(n)
    const d = new Date(n * 86_400_000)
    const dow = d.getUTCDay()
    if (n === from || d.getUTCDate() === 1) {
      months.push({ left: (n - from) * dayW, width: 0, label: d.toLocaleDateString('en-IN', { month: 'short', year: zoom === 'fit' ? '2-digit' : 'numeric', timeZone: 'UTC' }) })
    }
    const label = zoom === 'week' ? String(d.getUTCDate()) : zoom === 'month' && dow === 1 ? String(d.getUTCDate()) : ''
    ticks.push({ left: (n - from) * dayW, label, weekend: zoom !== 'fit' && !worksOn(cal, iso), monday: zoom !== 'fit' && dow === 1 })
  }
  months.forEach((m, i) => (m.width = (i + 1 < months.length ? months[i + 1].left : width) - m.left))

  const links = schedule.links.filter((l) => row.has(l.predecessor) && row.has(l.successor))
  const byId = new Map(schedule.activities.map((a) => [a.id, a]))
  const conflicted = new Set(schedule.conflicts.map((c) => `${c.predecessor}>${c.successor}`))

  const finishPlanned = schedule.project.planned_finish
  const forecast = schedule.summary.forecast_finish

  return (
    // contain: the timeline is wider than the screen and scrolls inside; without this, its width becomes the page's
    // minimum width and the whole app scrolls sideways.
    <div className="flex min-w-0 overflow-hidden rounded-xl border bg-card [contain:inline-size]">
      {/* Names */}
      <div className="shrink-0 border-r bg-card" style={{ width: NAME_COL }}>
        <div className="flex items-end border-b bg-muted/40 px-3 pb-1.5 text-[11px] font-medium text-muted-foreground" style={{ height: HEAD }}>
          <span className="flex-1">Activity</span>
          <span className="w-14 text-right">Done</span>
        </div>
        {activities.map((a) => {
          const tone = STATE_BAR[a.state]
          return (
            <button
              key={a.id}
              type="button"
              onClick={() => onSelect(a.id)}
              aria-current={selectedId === a.id || undefined}
              className={cn('flex w-full items-center gap-2 border-b px-3 text-left transition hover:bg-muted/50', tone.row, selectedId === a.id && 'bg-primary/10')}
              style={{ height: ROW }}
            >
              <span className={cn('h-7 w-1 shrink-0 rounded-full', tone.dot)} title={STATE_WORDS[a.state]} />
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1 truncate text-sm font-medium">
                  {a.milestone && <Diamond className="size-3 shrink-0 fill-current text-foreground" />}
                  {a.code && <span className="shrink-0 text-xs font-normal text-muted-foreground">{a.code}</span>}
                  <span className="truncate">{a.name}</span>
                  {a.critical && a.state !== 'done' && <Flame className="size-3 shrink-0 text-draft" aria-label="Critical path" />}
                </span>
                <span className="block truncate text-[11px] text-muted-foreground">
                  {a.start ? `${shortDay(a.start, schedule.today)}${a.milestone ? '' : ` → ${shortDay(a.end, schedule.today)}`}` : 'No dates yet'}
                  {a.site_name ? ` · ${a.site_name}` : ''}
                </span>
              </span>
              <span className="flex w-14 flex-col items-end gap-1">
                <span className={cn('text-sm font-semibold tabular-nums', a.progress === null && 'font-normal text-muted-foreground')}>{a.progress === null ? '—' : `${a.progress}%`}</span>
                {a.progress !== null && (
                  <span className="h-1 w-12 overflow-hidden rounded-full bg-muted"><span className={cn('block h-full rounded-full', tone.fill)} style={{ width: `${a.progress}%` }} /></span>
                )}
              </span>
            </button>
          )
        })}
      </div>

      {/* Timeline */}
      <div ref={scroller} className="relative min-w-0 flex-1 overflow-x-auto" aria-label="Timeline">
        <div className="relative" style={{ width, height: HEAD + activities.length * ROW }}>
          {/* Head */}
          <div className="sticky top-0 z-10 border-b bg-muted/40" style={{ height: HEAD }}>
            {months.map((m) => (
              <div key={m.left} className="absolute top-0 truncate border-l px-1.5 pt-1 text-[11px] font-semibold" style={{ left: m.left, width: m.width }}>{m.label}</div>
            ))}
            {ticks.map((t) => t.label && (
              <div key={t.left} className={cn('absolute bottom-1 text-center text-[10px] tabular-nums text-muted-foreground', t.weekend && 'text-destructive/70')} style={{ left: t.left, width: zoom === 'week' ? dayW : dayW * 7 }}>{t.label}</div>
            ))}
          </div>
          {/* Grid: Sundays shaded, Mondays ruled */}
          {ticks.map((t) => (t.weekend || t.monday) && (
            <div key={`g${t.left}`} className={cn('absolute bottom-0', t.weekend ? 'bg-muted/50' : 'border-l border-dashed border-border/70')} style={{ left: t.left, width: t.weekend ? dayW : 0, top: HEAD }} />
          ))}
          {activities.map((a, i) => (
            <div key={`r${a.id}`} className={cn('absolute inset-x-0 border-b', STATE_BAR[a.state].row, selectedId === a.id && 'bg-primary/5')} style={{ top: HEAD + i * ROW, height: ROW }} />
          ))}
          {/* Contract finish and forecast finish */}
          {finishPlanned && (
            <Marker left={x(finishPlanned) + dayW} flip={x(finishPlanned) + dayW > width - 140} label={`Handover ${shortDay(finishPlanned, schedule.today)}`} className="border-foreground text-foreground" />
          )}
          {forecast && schedule.summary.slip_days > 0 && (
            <Marker left={x(forecast) + dayW} flip={x(forecast) + dayW > width - 140} label={`Forecast ${shortDay(forecast, schedule.today)}`} className="border-destructive text-destructive" dashed />
          )}
          {/* Today */}
          <div className="pointer-events-none absolute bottom-0 z-[5] w-0.5 bg-primary" style={{ left: (today - from) * dayW + dayW / 2, top: HEAD - 6 }}>
            <span className="absolute -top-0.5 left-1/2 -translate-x-1/2 rounded bg-primary px-1 text-[9px] font-bold text-primary-foreground">TODAY</span>
          </div>

          {/* Links */}
          <svg className="pointer-events-none absolute left-0 z-[4]" style={{ top: 0 }} width={width} height={HEAD + activities.length * ROW}>
            <defs>
              <marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L8,4 L0,8 z" className="fill-muted-foreground" /></marker>
              <marker id="arrow-bad" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L8,4 L0,8 z" className="fill-destructive" /></marker>
            </defs>
            {links.map((l) => {
              const p = byId.get(l.predecessor)!
              const s = byId.get(l.successor)!
              if (!p.end || !p.start || !s.start) return null
              // "With it" (SS) links leave from the start of the bar; "after it ends" from its end.
              const x1 = l.kind === 'SS' ? x(p.start) : p.milestone ? x(p.end) + dayW / 2 : x(p.end) + dayW
              const y1 = HEAD + row.get(p.id)! * ROW + ROW / 2
              const x2 = s.milestone ? x(s.start) + dayW / 2 - 7 : x(s.start)
              const y2 = HEAD + row.get(s.id)! * ROW + ROW / 2
              const bad = conflicted.has(`${p.id}>${s.id}`)
              const mid = y1 + (y2 > y1 ? ROW / 2 : -ROW / 2)
              const d = l.kind === 'SS'
                ? `M${x1},${y1} h-6 V${y2} H${x2}`
                : x2 - 8 >= x1 + 4
                  ? `M${x1},${y1} H${x2 - 8} V${y2} H${x2}`
                  : `M${x1},${y1} h6 V${mid} H${x2 - 10} V${y2} H${x2}`
              return <path key={`${p.id}>${s.id}`} d={d} fill="none" strokeWidth={1.4} className={bad ? 'stroke-destructive' : 'stroke-muted-foreground/60'} strokeDasharray={bad ? '4 3' : undefined} markerEnd={`url(#${bad ? 'arrow-bad' : 'arrow'})`} />
            })}
          </svg>

          {/* Bars */}
          {activities.map((a, i) => {
            const top = HEAD + i * ROW
            if (!a.start || !a.end) {
              return (
                <div key={a.id} className="absolute flex items-center" style={{ top, height: ROW, left: (today - from) * dayW + 8 }}>
                  {canEdit ? (
                    <button type="button" onClick={() => onAddDates(a.id)} className="inline-flex items-center gap-1 rounded-md border border-dashed px-2 py-1 text-xs text-muted-foreground hover:border-primary hover:text-foreground">
                      <CalendarPlus className="size-3.5" /> Add dates
                    </button>
                  ) : (
                    <span className="text-xs text-muted-foreground">No dates yet</span>
                  )}
                </div>
              )
            }
            const tone = STATE_BAR[a.state]
            const dx = drag?.id === a.id ? drag.dx : 0
            const left = x(a.start) + dx
            const span = (dayNum(a.end) - dayNum(a.start) + 1) * dayW
            const over = a.forecast_end && a.slip_days > 0 && !a.done ? (dayNum(a.forecast_end) - dayNum(a.end)) * dayW : 0
            const pointer = canEdit
              ? {
                  onPointerDown: (e: React.PointerEvent) => {
                    if (e.button !== 0) return
                    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
                    setDrag({ id: a.id, x0: e.clientX, dx: 0 })
                  },
                  onPointerMove: (e: React.PointerEvent) => drag?.id === a.id && setDrag({ ...drag, dx: e.clientX - drag.x0 }),
                  onPointerUp: () => {
                    const days = drag?.id === a.id ? Math.round(drag.dx / dayW) : 0
                    setDrag(null)
                    if (days !== 0) onMove(a.id, days)
                    else onSelect(a.id)
                  },
                }
              : { onClick: () => onSelect(a.id) }
            const label = `${a.name}: ${shortDay(a.start)}${a.milestone ? '' : ` to ${shortDay(a.end)}`}${a.progress !== null ? `, ${a.progress}% done` : ''}`
            if (a.milestone) {
              return (
                <button key={a.id} type="button" aria-label={label} title={label} {...pointer}
                  className={cn('absolute z-[6] flex items-center gap-1.5 touch-none', canEdit && 'cursor-grab active:cursor-grabbing')}
                  style={{ top: top + ROW / 2 - 9, left: left + dayW / 2 - 9 }}>
                  <span className={cn('size-[18px] rotate-45 rounded-[3px] border-2 border-background shadow', a.state === 'done' ? 'bg-success' : a.state === 'late' ? 'bg-destructive' : 'bg-foreground', selectedId === a.id && 'ring-2 ring-primary ring-offset-1')} />
                  <span className="whitespace-nowrap text-[11px] font-medium text-foreground/80">{shortDay(a.start)}</span>
                </button>
              )
            }
            const base = a.baseline?.start && a.baseline.end ? a.baseline : null
            return (
              <React.Fragment key={a.id}>
                {base && (
                  // The approved programme's dates: a thin grey bar under the planned one.
                  <div className="pointer-events-none absolute z-[5] rounded-full bg-foreground/35" title={`Approved ${shortDay(base.start)} to ${shortDay(base.end)}`}
                    style={{ top: top + ROW - 8, height: 3, left: x(base.start!), width: Math.max((dayNum(base.end!) - dayNum(base.start!) + 1) * dayW, 3) }} />
                )}
                <button type="button" aria-label={label} title={label} {...pointer}
                  className={cn(
                    'group absolute z-[6] flex items-center overflow-hidden rounded-md text-left shadow-sm transition-[box-shadow] touch-none',
                    tone.bar,
                    a.critical && a.state !== 'done' && 'ring-2 ring-orange-500/70',
                    selectedId === a.id && 'ring-2 ring-primary',
                    canEdit && 'cursor-grab active:cursor-grabbing',
                    drag?.id === a.id && 'opacity-80 shadow-lg',
                  )}
                  style={{ top: top + 9, height: ROW - 18, left, width: Math.max(span, 6) }}>
                  <span className={cn('absolute inset-y-0 left-0', tone.fill)} style={{ width: `${a.progress ?? 0}%` }} />
                  {a.expected !== null && a.state !== 'done' && a.expected > 0 && a.expected < 100 && (
                    <span className="absolute inset-y-0 w-px bg-foreground/50" style={{ left: `${a.expected}%` }} title={`Should be ${a.expected}% by today`} />
                  )}
                  {canEdit && span > 40 && <GripVertical className="relative ml-0.5 size-3 shrink-0 text-foreground/40 opacity-0 group-hover:opacity-100" />}
                  {span > 70 && (
                    <span className={cn('relative truncate px-1.5 text-[11px] font-semibold', (a.progress ?? 0) > 45 ? 'text-background' : 'text-foreground/80')}>
                      {a.progress !== null ? `${a.progress}%` : a.name}
                    </span>
                  )}
                </button>
                {over > 0 && (
                  <div className="pointer-events-none absolute z-[5] flex items-center rounded-r-md border border-dashed border-destructive bg-[repeating-linear-gradient(135deg,color-mix(in_oklab,var(--destructive)_25%,transparent)_0_4px,transparent_4px_8px)]"
                    style={{ top: top + 12, height: ROW - 24, left: left + span, width: over }}>
                    {over > 34 && <span className="px-1 text-[10px] font-bold text-destructive">+{a.slip_days}d</span>}
                  </div>
                )}
                {span <= 70 && (
                  <span className="pointer-events-none absolute z-[5] whitespace-nowrap text-[11px] text-muted-foreground" style={{ top: top + ROW / 2 - 8, left: left + Math.max(span, 6) + over + 6 }}>
                    {a.progress !== null ? `${a.progress}%` : ''}
                  </span>
                )}
              </React.Fragment>
            )
          })}
          {drag && drag.dx !== 0 && (() => {
            const a = byId.get(drag.id)
            if (!a?.start) return null
            const days = Math.round(drag.dx / dayW)
            return (
              <div className="pointer-events-none absolute z-20 rounded-md bg-foreground px-2 py-1 text-xs font-semibold text-background shadow-lg" style={{ top: HEAD + (row.get(a.id) ?? 0) * ROW - 22, left: x(a.start) + drag.dx }}>
                {days > 0 ? `+${days}` : days} day{Math.abs(days) === 1 ? '' : 's'} → starts {shortDay(isoOf(dayNum(a.start) + days))}
              </div>
            )
          })()}
        </div>
      </div>
    </div>
  )
}

function Marker({ left, label, className, dashed, flip }: { left: number; label: string; className: string; dashed?: boolean; flip?: boolean }) {
  return (
    <div className={cn('pointer-events-none absolute bottom-0 z-[3] border-l-2', dashed && 'border-dashed', className)} style={{ left, top: HEAD }}>
      {/* Near the right edge the label sits on the line's left, so it is never cut off. */}
      <span className={cn('absolute top-1 whitespace-nowrap rounded bg-background/90 px-1 text-[10px] font-semibold', flip ? 'right-1' : 'left-1')}>{label}</span>
    </div>
  )
}
