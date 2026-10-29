import * as React from 'react'
import { AlertCircle, ClipboardCheck, IndianRupee, TrendingUp } from 'lucide-react'
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'
import { Fact, Facts, SheetHero, SheetSection } from '@/components/detail-sheet'
import { StatStrip } from '@/components/dpr-page'
import { longDate } from '@/lib/site-day'
import { fetchOneWorkerStatisticsApi, type WorkerStatistics } from '@/lib/api'

// WEB-39: the side-panel layout (detail-sheet.tsx): days worked in the head,
// money in a number strip, the calendar in green.

interface WorkerStatisticsSheetProps {
  workerId: string | null
  workerName?: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

/** Months to render in the calendar, ending on the worker's last recorded day.
 *  Bounded so a worker with three years of history does not render 36 grids. */
const CALENDAR_MONTHS = 3

/** Builds the month grids to display, anchored on the worker's own history
 *  rather than on today: someone who last worked in March should open on
 *  March, not on an empty current month. */
function buildMonths(dates: string[]): { label: string; year: number; month: number }[] {
  if (dates.length === 0) return []
  const last = new Date(`${dates[dates.length - 1]}T00:00:00`)
  const months: { label: string; year: number; month: number }[] = []
  for (let i = CALENDAR_MONTHS - 1; i >= 0; i--) {
    const d = new Date(last.getFullYear(), last.getMonth() - i, 1)
    months.push({
      label: d.toLocaleDateString('en-IN', { month: 'short', year: 'numeric' }),
      year: d.getFullYear(),
      month: d.getMonth(),
    })
  }
  return months
}

function MonthGrid({
  year,
  month,
  label,
  worked,
}: {
  year: number
  month: number
  label: string
  worked: Set<string>
}) {
  const first = new Date(year, month, 1)
  const daysInMonth = new Date(year, month + 1, 0).getDate()
  // Monday-first, matching how a site week is read.
  const leading = (first.getDay() + 6) % 7

  const cells: (number | null)[] = [
    ...Array.from({ length: leading }, () => null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ]

  return (
    <div className="flex flex-col gap-1.5">
      <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">
        {label}
      </div>
      <div className="grid grid-cols-7 gap-1">
        {['M', 'T', 'W', 'T', 'F', 'S', 'S'].map((d, i) => (
          <div key={i} className="text-[9px] text-muted-foreground text-center font-medium">
            {d}
          </div>
        ))}
        {cells.map((day, i) => {
          if (day === null) return <div key={`pad-${i}`} />
          const iso = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
          const present = worked.has(iso)
          return (
            <div
              key={iso}
              title={present ? `Present on ${iso}` : iso}
              className={`aspect-square rounded-sm flex items-center justify-center text-[9px] font-mono ${
                present
                  ? 'bg-success text-background font-bold'
                  : 'bg-muted/60 text-muted-foreground/60'
              }`}
            >
              {day}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function WorkerStatisticsSheet({
  workerId,
  workerName,
  open,
  onOpenChange,
}: WorkerStatisticsSheetProps) {
  const [stats, setStats] = React.useState<WorkerStatistics | null>(null)
  const [loading, setLoading] = React.useState(false)
  // "No history" and "the request failed" are different claims and must not
  // render as the same empty sheet.
  const [error, setError] = React.useState<string | null>(null)
  const [notFound, setNotFound] = React.useState(false)

  React.useEffect(() => {
    if (!open || !workerId) return
    let cancelled = false
    setLoading(true)
    setError(null)
    setNotFound(false)
    setStats(null)

    fetchOneWorkerStatisticsApi(workerId)
      .then((data) => {
        if (!cancelled) setStats(data)
      })
      .catch((err) => {
        if (cancelled) return
        // The endpoint 404s when a registered worker has never appeared in
        // attendance -- a real, ordinary state, not a failure.
        if (err?.response?.status === 404) setNotFound(true)
        else setError('Could not load this worker’s attendance history.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [open, workerId])

  const worked = React.useMemo(
    () => new Set(stats?.dates_worked ?? []),
    [stats]
  )
  const months = React.useMemo(() => buildMonths(stats?.dates_worked ?? []), [stats])

  const money = (n: number) => `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
  const day = (iso: string | null) => (iso ? longDate(iso) : null)

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full gap-0 overflow-y-auto p-0 sm:max-w-lg">
        {stats ? (
          <SheetHero
            tone={stats.is_registered ? 'neutral' : 'warn'}
            kicker={stats.is_registered ? 'On the register' : 'Not on the register'}
            lead={
              <>
                {stats.days_worked} <span className="text-xl font-medium text-muted-foreground">{stats.days_worked === 1 ? 'day' : 'days'} worked</span>
              </>
            }
            title={stats.name || workerName || 'Worker'}
          >
            {stats.trades.length > 0 && <span>{stats.trades.join(', ')}</span>}
            {stats.last_seen && <span>Last on site {day(stats.last_seen)}</span>}
          </SheetHero>
        ) : (
          <div className="border-b px-5 pt-5 pb-4">
            <SheetTitle>{workerName || 'Worker'}</SheetTitle>
            <SheetDescription>Attendance history, from recorded attendance.</SheetDescription>
          </div>
        )}

        {loading && <p className="py-12 text-center text-sm text-muted-foreground">Loading…</p>}

        {error && (
          <p className="m-5 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
            <AlertCircle className="size-4 shrink-0" />
            {error}
          </p>
        )}

        {notFound && (
          <p className="m-5 flex items-start gap-2 rounded-lg bg-muted/50 px-3 py-3 text-sm text-muted-foreground">
            <ClipboardCheck className="mt-0.5 size-4 shrink-0" />
            On the register, but not in any attendance yet, so there is no history to show.
          </p>
        )}

        {stats && (
          <>
            <div className="px-5 pt-4">
              <StatStrip
                phoneCols={2}
                stats={[
                  {
                    label: 'Earned',
                    value: stats.total_earnings > 0 ? money(stats.total_earnings) : '—',
                    icon: IndianRupee,
                    tone: stats.unpriced_man_days > 0 ? 'warn' : 'default',
                    hint: stats.unpriced_man_days > 0 ? `${stats.unpriced_man_days} day${stats.unpriced_man_days === 1 ? '' : 's'} without a wage` : 'from recorded wages',
                  },
                  { label: 'Wage a day', value: stats.priced_man_days > 0 ? money(stats.avg_daily_wage) : '—', icon: TrendingUp, hint: 'average' },
                  {
                    label: 'Reports',
                    value: stats.attendance_count,
                    icon: ClipboardCheck,
                    tone: stats.attendance_count > stats.days_worked ? 'info' : 'default',
                    hint: stats.attendance_count > stats.days_worked ? 'some days on two sites' : 'they appear in',
                  },
                ]}
              />
            </div>

            <SheetSection title="Details">
              <Facts>
                <Fact label="First seen">{day(stats.first_seen)}</Fact>
                <Fact label="Last seen">{day(stats.last_seen)}</Fact>
                <Fact label="Trades" missing="None recorded">
                  {stats.trades.length > 0 && (
                    <span className="flex flex-wrap gap-1.5">
                      {stats.trades.map((t) => (
                        <span key={t} className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium">
                          {t}
                        </span>
                      ))}
                    </span>
                  )}
                </Fact>
                <Fact label="Contractors" missing="None recorded">
                  {stats.contractors.length > 0 && (
                    <span className="flex flex-wrap gap-1.5">
                      {stats.contractors.map((c) => (
                        <span key={c} className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium">
                          {c}
                        </span>
                      ))}
                    </span>
                  )}
                </Fact>
              </Facts>
            </SheetSection>

            {months.length > 0 && (
              <SheetSection
                title="Days on site"
                className="border-t"
                action={
                  <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <span className="inline-block size-2.5 rounded-sm bg-success" /> Present
                  </span>
                }
              >
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                  {months.map((m) => (
                    <MonthGrid key={`${m.year}-${m.month}`} year={m.year} month={m.month} label={m.label} worked={worked} />
                  ))}
                </div>
                <p className="text-xs text-muted-foreground">
                  The {CALENDAR_MONTHS} months up to {day(stats.last_seen)}. Earlier days count in the totals above.
                </p>
              </SheetSection>
            )}
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}
