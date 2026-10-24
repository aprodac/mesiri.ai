import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ChevronRight, Download, HardHat, MessageSquare, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { useToast } from '@/components/ui/toast-notification'
import { Callout, DprSection, Segmented, StatStrip } from '@/components/dpr-page'
import { fetchLabourStatementApi } from '@/lib/api'
import { downloadTextFile, toCsv } from '@/lib/export'
import { downloadStatement, fetchAllAttendance, rangeName, STATEMENTS } from '@/lib/labour'
import { PERIOD_OPTIONS, periodRange, type Period } from '@/lib/period'
import { useSiteNames } from '@/lib/site-names'
import { longDate, plural } from '@/lib/site-day'
import { useUrlState } from '@/lib/url-state'
import { apiErrorMessage } from '@/lib/logo-upload'
import { AttendanceDetailSheet } from './attendance-detail-sheet'

// WEB-22: who was on site, from the attendance reports (mostly sent on
// WhatsApp). One view instead of Overview, Attendance, Analytics and
// Reports: the figures, a daily chart, the trades, every report by day and
// site, and the four statements as exports.

const SERIES = 'var(--chart-2)'
const shortDay = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString([], { day: 'numeric', month: 'short' })
const trade = (value: string | null) => {
  if (!value) return 'Not said'
  const text = value.replace(/_/g, ' ').toLowerCase()
  return text.charAt(0).toUpperCase() + text.slice(1)
}

export function AttendanceView({ projectId, siteId }: { projectId: string | null; siteId: string | null }) {
  const toast = useToast()
  const siteNames = useSiteNames()
  const [period, setPeriod] = useUrlState<Period>('period', '30d')
  const [from, setFrom] = useUrlState<string>('from', '')
  const [to, setTo] = useUrlState<string>('to', '')
  const [openId, setOpenId] = React.useState<string | null>(null)
  const range = periodRange(period, from, to)
  const params = { project_id: projectId ?? undefined, site_id: siteId ?? undefined, date_from: range.from, date_to: range.to }

  const reports = useQuery({ queryKey: ['labour', 'attendance-all', params], queryFn: () => fetchAllAttendance(params) })
  // Man-days and cost from the backend statement for the same scope and
  // dates -- never summed from a page of the list.
  const byTrade = useQuery({
    queryKey: ['labour', 'statement', 'trade_breakdown', params],
    queryFn: () => fetchLabourStatementApi({ ...params, report_type: 'trade_breakdown' }),
  })

  const items = React.useMemo(() => reports.data?.items ?? [], [reports.data])
  const days = React.useMemo(() => {
    const byDay = new Map<string, typeof items>()
    for (const r of items) byDay.set(r.occurred_date, [...(byDay.get(r.occurred_date) ?? []), r])
    return [...byDay.entries()].sort(([a], [b]) => b.localeCompare(a))
  }, [items])
  const chart = React.useMemo(
    () => [...days].reverse().map(([day, list]) => ({ day, workers: list.reduce((s, r) => s + (r.total_headcount || 0), 0) })),
    [days],
  )
  const st = byTrade.data
  const manDays = st?.total_man_days ?? chart.reduce((s, d) => s + d.workers, 0)
  const tradeRows = [...(st?.rows ?? [])].sort((a, b) => b.man_days - a.man_days)
  const maxTrade = Math.max(1, ...tradeRows.map((r) => r.man_days))

  const exportReports = () => {
    downloadTextFile(
      `labour-attendance-${rangeName(range.from, range.to)}.csv`,
      toCsv(
        ['Date', 'Site', 'Project', 'Workers', 'Trades', 'Labour cost (INR)', 'Sent via', 'Note'],
        items.map((r) => {
          const s = r.site_id ? siteNames.get(r.site_id) : undefined
          return [r.occurred_date, s?.name ?? '', s?.project ?? '', r.total_headcount, r.line_count, r.total_cost || '', r.recorded_via?.includes('whatsapp') ? 'WhatsApp' : 'Dashboard', r.notes]
        }),
      ),
    )
  }
  const exportStatement = async (type: (typeof STATEMENTS)[number]['type']) => {
    try {
      await downloadStatement(type, params)
    } catch (err) {
      toast.error('Could not export', apiErrorMessage(err))
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Segmented<Period> label="Period" value={period} onChange={setPeriod} options={PERIOD_OPTIONS} />
        {period === 'custom' && (
          <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <Input type="date" aria-label="From" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} className="h-9 w-[150px] dark:[color-scheme:dark]" />
            to
            <Input type="date" aria-label="To" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} className="h-9 w-[150px] dark:[color-scheme:dark]" />
          </div>
        )}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" className="ml-auto gap-1.5" disabled={!reports.data}>
              <Download className="size-3.5" /> Export
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuItem onClick={exportReports}>Attendance reports (CSV)</DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">Man-days and cost</DropdownMenuLabel>
            {STATEMENTS.map((s) => (
              <DropdownMenuItem key={s.type} onClick={() => exportStatement(s.type)}>
                {s.label} (CSV)
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {reports.isError ? (
        <Callout
          tone="draft"
          icon={TriangleAlert}
          action={
            <Button variant="outline" size="sm" className="bg-background" onClick={() => reports.refetch()}>
              Try again
            </Button>
          }
        >
          Attendance could not be loaded.
        </Callout>
      ) : reports.isLoading ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-16 rounded-xl" />
          <Skeleton className="h-56 rounded-xl" />
          <Skeleton className="h-40 rounded-xl" />
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center">
          <HardHat className="size-6 text-muted-foreground" aria-hidden="true" />
          <p className="text-sm font-medium">No attendance in this period</p>
          <p className="max-w-sm text-sm text-muted-foreground">Site engineers send it on WhatsApp, e.g. "24 workers today: 8 mason, 12 helper, 4 carpenter".</p>
        </div>
      ) : (
        <>
          <StatStrip
            phoneCols={2}
            stats={[
              { label: 'Man-days', value: manDays.toLocaleString('en-IN') },
              { label: 'Average a day', value: days.length ? Math.round(manDays / days.length) : '—' },
              { label: 'Days reported', value: days.length },
              {
                label: st && st.unpriced_man_days > 0 && st.priced_man_days > 0 ? `Labour cost (${st.priced_man_days} of ${st.total_man_days} priced)` : 'Labour cost',
                value: st && st.total_cost > 0 ? `₹${st.total_cost.toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : st && st.unpriced_man_days > 0 ? 'No wages sent' : '—',
              },
            ]}
          />
          {reports.data?.truncated && (
            <Callout tone="muted" icon={TriangleAlert}>
              Only the newest 1,000 reports are listed. Pick shorter dates to see all of them; the figures above cover the whole period.
            </Callout>
          )}

          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
            <DprSection icon={HardHat} title="Workers a day" meta={`${chart.length} days`}>
              <div className="h-52 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chart} margin={{ top: 4, right: 4, left: -16, bottom: 0 }} barCategoryGap="25%">
                    <CartesianGrid vertical={false} stroke="var(--border)" />
                    <XAxis dataKey="day" tickFormatter={shortDay} tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} tickLine={false} axisLine={{ stroke: 'var(--border)' }} minTickGap={16} />
                    <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} tickLine={false} axisLine={false} width={40} />
                    <Tooltip
                      cursor={{ fill: 'var(--muted)', opacity: 0.6 }}
                      content={({ active, payload }) =>
                        active && payload?.length ? (
                          <div className="rounded-lg border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-md">
                            <p className="mb-1 font-medium">{longDate(String(payload[0].payload.day))}</p>
                            <p className="tabular-nums">
                              <span className="font-semibold">{Number(payload[0].value)}</span> workers
                            </p>
                          </div>
                        ) : null
                      }
                    />
                    <Bar dataKey="workers" fill={SERIES} radius={[4, 4, 0, 0]} maxBarSize={28} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </DprSection>

            <section className="flex flex-col gap-2">
              <h2 className="text-[15px] font-semibold">By trade</h2>
              {byTrade.isLoading ? (
                <Skeleton className="h-32 rounded-lg" />
              ) : tradeRows.length === 0 ? (
                <p className="text-sm text-muted-foreground">No trades recorded.</p>
              ) : (
                <ul className="flex flex-col gap-2 text-sm">
                  {tradeRows.map((r) => (
                    <li key={r.id} className="flex flex-col gap-1">
                      <div className="flex justify-between gap-2">
                        <span>{trade(r.title)}</span>
                        <span className="tabular-nums text-muted-foreground">
                          <strong className="font-semibold text-foreground">{r.man_days}</strong> man-days
                        </span>
                      </div>
                      <div className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden="true">
                        <div className="h-full rounded-full" style={{ width: `${(r.man_days / maxTrade) * 100}%`, background: SERIES }} />
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>

          <DprSection icon={MessageSquare} title="Attendance reports" meta={plural(items.length, 'report')}>
            <div className="flex flex-col gap-3">
              {days.map(([day, list]) => (
                <section key={day} className="flex flex-col gap-1.5">
                  <h3 className="flex items-baseline gap-2 text-sm">
                    <span className="font-semibold">{longDate(day)}</span>
                    <span className="text-muted-foreground">{plural(list.reduce((s, r) => s + (r.total_headcount || 0), 0), 'worker')}</span>
                  </h3>
                  <ul className="divide-y rounded-lg border">
                    {list.map((r) => {
                      const s = r.site_id ? siteNames.get(r.site_id) : undefined
                      return (
                        <li key={r.id}>
                          <button type="button" onClick={() => setOpenId(r.id)} className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-muted/40">
                            <div className="flex min-w-0 flex-1 flex-col">
                              <span className="truncate">
                                <strong className="font-semibold tabular-nums">{r.total_headcount}</strong> workers
                                <span className="text-muted-foreground"> · {plural(r.line_count, 'trade')}</span>
                              </span>
                              <span className="truncate text-xs text-muted-foreground">
                                {[!siteId && s?.name, !projectId && s?.project, r.notes && r.notes !== 'Daily site attendance log' ? r.notes : null].filter(Boolean).join(' · ') || '—'}
                              </span>
                            </div>
                            {r.total_cost > 0 && <span className="text-sm tabular-nums">₹{r.total_cost.toLocaleString('en-IN')}</span>}
                            {r.recorded_via?.includes('whatsapp') && <MessageSquare className="size-3.5 shrink-0 text-muted-foreground" aria-label="Sent on WhatsApp" />}
                            <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                          </button>
                        </li>
                      )
                    })}
                  </ul>
                </section>
              ))}
            </div>
          </DprSection>
        </>
      )}

      <AttendanceDetailSheet reportId={openId} open={openId !== null} onOpenChange={(open) => !open && setOpenId(null)} />
    </div>
  )
}
