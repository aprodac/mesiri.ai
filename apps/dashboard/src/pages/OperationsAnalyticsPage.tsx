import * as React from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { BarChart3, ChevronRight, RefreshCw, Table2, TriangleAlert } from 'lucide-react'
import { HardHat as IcHardHat, Hammer as IcHammer, Camera as IcCamera, TriangleAlert as IcTriangleAlert, Clock as IcClock } from 'lucide-react'
import { useScope } from '@/lib/ScopeContext'
import { fetchAnalyticsApi, type AnalyticsDay, type AnalyticsSummary } from '@/lib/api'
import { longDate, plural } from '@/lib/site-day'
import { useUrlState } from '@/lib/url-state'
import { Callout, PageHeader, StatStrip } from '@/components/dpr-page'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn, toLocalISODate } from '@/lib/utils'

// Analytics (WEB-24): how the sites are doing over a date range. Every figure
// comes from GET /dpr/analytics, aggregated in SQL over the whole range with
// the Reports list's scope rules (the old page counted the first 50-100 rows
// of four lists in the browser and drew two charts from made-up numbers).
// Chart rules: docs/DESIGN.md and the dataviz method -- one hue per single
// series, severity as a validated one-hue ramp, thin bars, recessive grid,
// a tooltip on every mark and a table view of every chart.

const RANGES = { '7': 'Last 7 days', '30': 'Last 30 days', '90': 'Last 90 days' } as const
type Range = keyof typeof RANGES

const SEVERITIES = [
  { key: 'CRITICAL', label: 'Critical', color: 'var(--sev-critical)' },
  { key: 'HIGH', label: 'High', color: 'var(--sev-high)' },
  { key: 'MEDIUM', label: 'Medium', color: 'var(--sev-medium)' },
  { key: 'LOW', label: 'Low', color: 'var(--sev-low)' },
] as const

const SERIES = 'var(--chart-2)'

function shortDay(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString([], { day: 'numeric', month: 'short' })
}

function humanize(value: string): string {
  const text = value.replace(/_/g, ' ').toLowerCase()
  return text.charAt(0).toUpperCase() + text.slice(1)
}

function TooltipBox({ title, rows }: { title: string; rows: { label: string; value: React.ReactNode; color?: string }[] }) {
  return (
    <div className="rounded-lg border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-md">
      <p className="mb-1 font-medium">{title}</p>
      {rows.map((r) => (
        <p key={r.label} className="flex items-center gap-2">
          {r.color && <span className="size-2.5 rounded-sm" style={{ background: r.color }} />}
          <span className="text-muted-foreground">{r.label}</span>
          <span className="ml-auto pl-3 font-semibold tabular-nums">{r.value}</span>
        </p>
      ))}
    </div>
  )
}

/** A titled chart with a chart/table switch (the table is the accessible view). */
function ChartPanel({
  title,
  note,
  table,
  children,
}: {
  title: string
  note?: string
  table: React.ReactNode
  children: React.ReactNode
}) {
  const [asTable, setAsTable] = React.useState(false)
  return (
    <section className="flex flex-col gap-3 rounded-xl border p-4">
      <header className="flex items-start justify-between gap-2">
        <div>
          <h2 className="text-[15px] font-semibold">{title}</h2>
          {note && <p className="text-xs text-muted-foreground">{note}</p>}
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 gap-1 px-2 text-xs text-muted-foreground"
          onClick={() => setAsTable((v) => !v)}
          aria-pressed={asTable}
        >
          {asTable ? <BarChart3 className="size-3.5" /> : <Table2 className="size-3.5" />}
          {asTable ? 'Chart' : 'Table'}
        </Button>
      </header>
      {asTable ? <div className="max-h-64 overflow-auto rounded-lg border">{table}</div> : children}
    </section>
  )
}

function DaysTable({ days, field, unit }: { days: AnalyticsDay[]; field: keyof AnalyticsDay; unit: string }) {
  return (
    <table className="w-full text-sm">
      <thead className="sticky top-0 bg-muted text-xs text-muted-foreground">
        <tr>
          <th className="px-3 py-1.5 text-left font-medium">Day</th>
          <th className="px-3 py-1.5 text-right font-medium">{unit}</th>
        </tr>
      </thead>
      <tbody className="tabular-nums">
        {[...days].reverse().map((d) => (
          <tr key={d.day} className="border-t">
            <td className="px-3 py-1.5">{longDate(d.day)}</td>
            <td className="px-3 py-1.5 text-right">{d[field] || '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** One series per day: thin bars, one hue, grid and axes in the background. */
function DailyBars({ days, field, label }: { days: AnalyticsDay[]; field: 'workers' | 'work_items'; label: string }) {
  return (
    <div className="h-56 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={days} margin={{ top: 4, right: 4, left: -16, bottom: 0 }} barCategoryGap="25%">
          <CartesianGrid vertical={false} stroke="var(--border)" />
          <XAxis
            dataKey="day"
            tickFormatter={shortDay}
            tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }}
            tickLine={false}
            axisLine={{ stroke: 'var(--border)' }}
            minTickGap={16}
          />
          <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} tickLine={false} axisLine={false} width={40} />
          <Tooltip
            cursor={{ fill: 'var(--muted)', opacity: 0.6 }}
            content={({ active, payload }) =>
              active && payload?.length ? (
                <TooltipBox
                  title={longDate(String(payload[0].payload.day))}
                  rows={[{ label, value: Number(payload[0].value) || '—', color: SERIES }]}
                />
              ) : null
            }
          />
          <Bar dataKey={field} fill={SERIES} radius={[4, 4, 0, 0]} maxBarSize={28} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function Meter({ value, of }: { value: number; of: number }) {
  const pct = of > 0 ? Math.round((value / of) * 100) : 0
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-full max-w-28 overflow-hidden rounded-full bg-muted" aria-hidden>
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: SERIES }} />
      </div>
      <span className="w-14 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
        {value}/{of}
      </span>
    </div>
  )
}

export default function OperationsAnalyticsPage() {
  const { scope } = useScope()
  const [range, setRange] = useUrlState<Range>('range', '30')

  const projectId = scope.mode !== 'portfolio' ? scope.projectId : undefined
  const siteId = scope.mode === 'site' ? scope.siteId : undefined
  const dateTo = toLocalISODate(new Date())
  const dateFrom = toLocalISODate(new Date(Date.now() - (Number(range) - 1) * 86_400_000))

  const query = useQuery({
    queryKey: ['analytics', projectId, siteId, dateFrom, dateTo],
    queryFn: () => fetchAnalyticsApi({ dateFrom, dateTo, projectId, siteId }),
  })
  const data: AnalyticsSummary | undefined = query.data

  const totals = React.useMemo(() => {
    const days = data?.days ?? []
    const sum = (k: keyof AnalyticsDay) => days.reduce((n, d) => n + (Number(d[k]) || 0), 0)
    return {
      workerDays: sum('workers'),
      workItems: sum('work_items'),
      photos: sum('photos'),
      issues: sum('issues'),
      hoursLost: Math.round((sum('delay_minutes') / 60) * 10) / 10,
      daysWithWork: days.filter((d) => d.workers > 0 || d.work_items > 0).length,
    }
  }, [data])

  // Open issues: one row per type, stacked by severity (most open first).
  const issueRows = React.useMemo(() => {
    const byType = new Map<string, Record<string, number>>()
    for (const r of data?.open_issues ?? []) {
      const row = byType.get(r.issue_type) ?? {}
      row[r.severity] = (row[r.severity] ?? 0) + r.count
      byType.set(r.issue_type, row)
    }
    return [...byType.entries()]
      .map(([type, counts]) => {
        const total = Object.values(counts).reduce((a, b) => a + b, 0)
        // The count rides on the axis label: a direct label that can't collide.
        return { type: humanize(type), label: `${humanize(type)} · ${total}`, ...counts, total }
      })
      .sort((a, b) => b.total - a.total)
  }, [data])
  const openTotal = issueRows.reduce((n, r) => n + r.total, 0)

  const scopeLabel =
    scope.mode === 'portfolio' ? 'All projects' : scope.mode === 'project' ? scope.projectName : `${scope.projectName} / ${scope.siteName}`
  const nDays = data?.days.length ?? Number(range)

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 pb-8 sm:px-2">
      <PageHeader
        title="Analytics"
        subtitle={<>How the sites are doing · {scopeLabel}</>}
        actions={
          <>
            <Select value={range} onValueChange={(v) => setRange(v as Range)}>
              <SelectTrigger className="h-9 w-[140px]" aria-label="Date range">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(RANGES) as Range[]).map((r) => (
                  <SelectItem key={r} value={r}>
                    {RANGES[r]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button variant="ghost" size="icon" className="size-8" onClick={() => query.refetch()} disabled={query.isFetching} title="Refresh" aria-label="Refresh">
              <RefreshCw className={cn('size-4', query.isFetching && 'animate-spin')} />
            </Button>
          </>
        }
      />

      {query.isError ? (
        <Callout tone="draft" icon={TriangleAlert} action={<Button variant="outline" size="sm" className="bg-background" onClick={() => query.refetch()}>Try again</Button>}>
          Analytics could not be loaded.
        </Callout>
      ) : query.isLoading || !data ? (
        <div className="flex flex-col gap-4">
          <Skeleton className="h-16 rounded-xl" />
          <div className="grid gap-4 lg:grid-cols-2">
            <Skeleton className="h-72 rounded-xl" />
            <Skeleton className="h-72 rounded-xl" />
          </div>
        </div>
      ) : (
        <>
          <p className="-mt-2 text-xs text-muted-foreground">
            {longDate(data.date_from)} – {longDate(data.date_to)} · work on {totals.daysWithWork} of {plural(nDays, 'day')}
          </p>
          <StatStrip
            stats={[
              { label: 'Worker-days', value: totals.workerDays.toLocaleString() || '—', icon: IcHardHat },
              { label: 'Work items', value: totals.workItems || '—', icon: IcHammer },
              { label: 'Photos', value: totals.photos || '—', icon: IcCamera },
              { label: 'Issues reported', value: totals.issues || '—', tone: totals.issues > 0 ? 'warn' : 'good', icon: IcTriangleAlert },
              { label: 'Hours lost', value: totals.hoursLost || '—', tone: totals.hoursLost > 0 ? 'bad' : 'default', icon: IcClock },
            ]}
          />

          <div className="grid gap-4 lg:grid-cols-2">
            <ChartPanel title="Workers on site" note="People per day, all sites in view" table={<DaysTable days={data.days} field="workers" unit="Workers" />}>
              <DailyBars days={data.days} field="workers" label="Workers" />
            </ChartPanel>
            <ChartPanel title="Work reported" note="Work items per day" table={<DaysTable days={data.days} field="work_items" unit="Work items" />}>
              <DailyBars days={data.days} field="work_items" label="Work items" />
            </ChartPanel>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <ChartPanel
              title="Open issues by type"
              note={openTotal ? `${plural(openTotal, 'issue')} still open, any date` : 'Nothing open'}
              table={
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-muted text-xs text-muted-foreground">
                    <tr>
                      <th className="px-3 py-1.5 text-left font-medium">Type</th>
                      {SEVERITIES.map((s) => (
                        <th key={s.key} className="px-2 py-1.5 text-right font-medium">{s.label}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="tabular-nums">
                    {issueRows.map((r) => (
                      <tr key={r.type} className="border-t">
                        <td className="px-3 py-1.5">{r.type}</td>
                        {SEVERITIES.map((s) => (
                          <td key={s.key} className="px-2 py-1.5 text-right">{(r as Record<string, unknown>)[s.key] as number || '—'}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              }
            >
              {issueRows.length === 0 ? (
                <p className="py-10 text-center text-sm text-muted-foreground">No open issues.</p>
              ) : (
                <>
                  <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground" aria-label="Severity">
                    {SEVERITIES.map((s) => (
                      <span key={s.key} className="inline-flex items-center gap-1.5">
                        <span className="size-2.5 rounded-sm" style={{ background: s.color }} /> {s.label}
                      </span>
                    ))}
                  </div>
                  <div className="w-full" style={{ height: Math.max(120, issueRows.length * 36 + 24) }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={issueRows} layout="vertical" margin={{ top: 0, right: 8, left: 0, bottom: 0 }} barCategoryGap="30%">
                        <CartesianGrid horizontal={false} stroke="var(--border)" />
                        <XAxis type="number" allowDecimals={false} domain={[0, 'dataMax']} tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} tickLine={false} axisLine={false} />
                        <YAxis type="category" dataKey="label" width={168} tick={{ fontSize: 12, fill: 'var(--foreground)', width: 160 }} tickLine={false} axisLine={false} />
                        <Tooltip
                          cursor={{ fill: 'var(--muted)', opacity: 0.6 }}
                          content={({ active, payload }) =>
                            active && payload?.length ? (
                              <TooltipBox
                                title={String(payload[0].payload.type)}
                                rows={SEVERITIES.filter((s) => payload[0].payload[s.key]).map((s) => ({
                                  label: s.label,
                                  value: payload[0].payload[s.key],
                                  color: s.color,
                                }))}
                              />
                            ) : null
                          }
                        />
                        {SEVERITIES.map((s, i) => (
                          <Bar
                            key={s.key}
                            dataKey={s.key}
                            stackId="sev"
                            fill={s.color}
                            stroke="var(--background)"
                            strokeWidth={2}
                            maxBarSize={22}
                            radius={i === SEVERITIES.length - 1 ? [0, 4, 4, 0] : 0}
                          />
                        ))}
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                  <Link to="/issues" className="inline-flex items-center gap-0.5 self-start text-xs font-medium text-primary hover:underline">
                    All issues <ChevronRight className="size-3.5" />
                  </Link>
                </>
              )}
            </ChartPanel>

            <section className="flex flex-col gap-3 rounded-xl border p-4">
              <header>
                <h2 className="text-[15px] font-semibold">Site reporting</h2>
                <p className="text-xs text-muted-foreground">
                  Days each site sent updates, and days its report was confirmed, out of {plural(nDays, 'day')}
                </p>
              </header>
              {data.sites.length === 0 ? (
                <p className="py-10 text-center text-sm text-muted-foreground">No active sites in view.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="text-xs text-muted-foreground">
                      <tr>
                        <th className="py-1.5 pr-2 text-left font-medium">Site</th>
                        <th className="px-2 py-1.5 text-left font-medium">Sent updates</th>
                        <th className="py-1.5 pl-2 text-left font-medium">Confirmed</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.sites.map((s) => (
                        <tr key={s.site_id} className="border-t">
                          <td className="py-2 pr-2">
                            <span className="font-medium">{s.site_name}</span>
                            <span className="block text-xs text-muted-foreground">{s.project_name}</span>
                          </td>
                          <td className="px-2 py-2">
                            <Meter value={s.days_with_updates} of={nDays} />
                          </td>
                          <td className="py-2 pl-2">
                            <Meter value={s.days_confirmed} of={nDays} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  )
}
