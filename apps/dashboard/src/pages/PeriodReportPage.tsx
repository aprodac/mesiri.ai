import * as React from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  CalendarRange,
  Camera,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  Send,
  FileSpreadsheet,
  FileText,
  HardHat,
  IndianRupee,
  Package,
  Ruler,
  TriangleAlert,
} from 'lucide-react'
import { DprHeader, DprSection, PageError, Segmented } from '@/components/dpr-page'
import { SendReportDialog, SentAndScheduled } from '@/components/reports/send-report'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast-notification'
import { downloadBlob } from '@/lib/export'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import {
  downloadBrief,
  downloadPeriodReport,
  fetchBrief,
  fetchPeriodReport,
  inr,
  shortDay,
  type Area,
  type Brief,
  type BriefQuery,
  type Kpi,
  type NeedsYou,
  type PeriodKind,
  type PeriodQuery,
  type PeriodReport,
  type Sections,
  type Tone,
} from '@/lib/period-report'
import { fetchProjects } from '@/lib/projects'
import { useScope } from '@/lib/ScopeContext'
import { cn } from '@/lib/utils'

// PRC-19 (reports plan R1): a week or a month of one project in ten seconds. The headline sentence (made by fixed
// rules from the figures, D-R7), the key figures against plan and the last period, what needs you, one line per
// area, then each section. Every figure is the owning module's own (GET /reports/period); every section links to
// its module's page. Week / Month / Dates, ← and → step periods; the address keeps the view, so a link opens it.

const TONE_TEXT: Record<Tone, string> = {
  good: 'text-success',
  warn: 'text-draft',
  bad: 'text-destructive',
  none: 'text-muted-foreground',
}
const TONE_SOFT: Record<Tone, string> = {
  good: 'bg-success-soft text-success',
  warn: 'bg-draft-soft text-draft',
  bad: 'bg-destructive/10 text-destructive',
  none: 'bg-muted text-muted-foreground',
}
const TONE_BAR: Record<Tone, string> = {
  good: 'before:bg-success',
  warn: 'before:bg-draft',
  bad: 'before:bg-destructive',
  none: '',
}
const LEVEL_STRIPE = { bad: 'bg-destructive', warn: 'bg-draft', info: 'bg-info' } as const

const STATE: Record<string, { word: string; tone: Tone }> = {
  late: { word: 'Late', tone: 'bad' },
  behind: { word: 'Behind', tone: 'warn' },
  on_track: { word: 'On track', tone: 'good' },
  not_started: { word: 'Not started', tone: 'none' },
  done: { word: 'Done', tone: 'good' },
  unscheduled: { word: 'No dates', tone: 'none' },
}

const SECTION_META: Record<keyof Sections, { title: string; icon: React.ComponentType<{ className?: string }>; tile: string }> = {
  work: { title: 'Work', icon: Ruler, tile: 'bg-info-soft text-info' },
  schedule: { title: 'Schedule', icon: CalendarRange, tile: 'bg-draft-soft text-draft' },
  labour: { title: 'Labour', icon: HardHat, tile: 'bg-muted text-foreground/70' },
  materials: { title: 'Materials', icon: Package, tile: 'bg-muted text-foreground/70' },
  stock_value: { title: 'Stock value', icon: IndianRupee, tile: 'bg-muted text-foreground/70' },
  money: { title: 'Money', icon: IndianRupee, tile: 'bg-success-soft text-success' },
  issues: { title: 'Issues', icon: TriangleAlert, tile: 'bg-destructive/10 text-destructive' },
  photos: { title: 'Photos', icon: Camera, tile: 'bg-muted text-foreground/70' },
  completeness: { title: 'Data check', icon: ClipboardCheck, tile: 'bg-muted text-foreground/70' },
}

function Pill({ tone, children }: { tone: Tone; children: React.ReactNode }) {
  return (
    <span className={cn('inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium', TONE_SOFT[tone])}>
      <span className="size-1.5 rounded-full bg-current" aria-hidden="true" />
      {children}
    </span>
  )
}

/** The last eight periods' figures, drawn to scale (real numbers only, never decoration). */
function Spark({ values }: { values: string[] }) {
  const nums = values.map(Number)
  const max = Math.max(...nums, 1)
  if (nums.length < 2 || nums.every((n) => n === 0)) return null
  const step = 100 / (nums.length - 1)
  const pts = nums.map((n, i) => `${(i * step).toFixed(1)},${(24 - (n / max) * 20).toFixed(1)}`)
  return (
    <svg viewBox="0 0 100 26" preserveAspectRatio="none" className="mt-1 h-6 w-full" aria-hidden="true">
      <polygon points={`0,26 ${pts.join(' ')} 100,26`} className="fill-muted" />
      <polyline points={pts.join(' ')} className="fill-none stroke-muted-foreground" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
      <circle cx={100 - 1.5} cy={Number(pts[pts.length - 1].split(',')[1])} r={2} className="fill-foreground" />
    </svg>
  )
}

function KpiTile({ k, onOpen }: { k: Kpi; onOpen: (section: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => onOpen(k.section)}
      className={cn(
        'relative flex min-w-0 flex-1 flex-col rounded-xl border bg-background px-3 py-2.5 text-left hover:bg-muted/40',
        k.tone !== 'none' && "overflow-hidden before:absolute before:inset-x-0 before:top-0 before:h-0.5 before:content-['']",
        TONE_BAR[k.tone],
      )}
    >
      <span className="truncate text-xs text-muted-foreground">{k.label}</span>
      <span className="truncate text-xl font-semibold tabular-nums">{k.value}</span>
      <span className={cn('truncate text-xs', k.tone === 'none' ? 'text-muted-foreground' : TONE_TEXT[k.tone])}>{k.note || ' '}</span>
      {k.trend && <Spark values={k.trend} />}
    </button>
  )
}

function Headline({ h }: { h: PeriodReport['headline'] }) {
  const [more, setMore] = React.useState(false)
  return (
    <div className="rounded-r-lg border-l-4 border-primary bg-muted/60 px-4 py-3 text-[15px] leading-relaxed">
      <b className="font-semibold">{h.lead}</b> {h.facts.join(' ')}
      {h.more.length > 0 && (
        <>
          {more && <span> {h.more.join(' ')}</span>}
          <button type="button" className="ml-2 text-sm text-primary-ink underline underline-offset-2" onClick={() => setMore((v) => !v)}>
            {more ? 'Less' : `${h.more.length} more`}
          </button>
        </>
      )}
    </div>
  )
}

function NeedsList({ items }: { items: NeedsYou[] }) {
  const [all, setAll] = React.useState(false)
  const shown = all ? items : items.slice(0, 5)
  return (
    <section className="flex flex-col rounded-xl border">
      <header className="flex items-center justify-between border-b px-4 py-2.5">
        <h2 className="text-[15px] font-semibold">Needs you{items.length > 0 && <span className="ml-1.5 text-muted-foreground">{items.length}</span>}</h2>
      </header>
      {items.length === 0 ? (
        <p className="px-4 py-6 text-sm text-muted-foreground">Nothing is waiting on you for this period.</p>
      ) : (
        <ul className="divide-y">
          {shown.map((n, i) => (
            <li key={`${n.kind}-${i}`} className="grid grid-cols-[4px_minmax(0,1fr)_auto] items-center gap-3 px-4 py-2.5">
              <span className={cn('self-stretch rounded-full', LEVEL_STRIPE[n.level])} aria-hidden="true" />
              <div className="min-w-0">
                <p className="text-sm">{n.title}</p>
                {n.detail && <p className="truncate text-xs text-muted-foreground">{n.detail}</p>}
              </div>
              {n.link && (
                <Button asChild size="sm" variant="outline">
                  <Link to={n.link}>{n.action ?? 'Open'}</Link>
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {items.length > 5 && (
        <button type="button" className="border-t px-4 py-2 text-left text-sm text-primary-ink" onClick={() => setAll((v) => !v)}>
          {all ? 'Show fewer' : `Show all ${items.length}`}
        </button>
      )}
    </section>
  )
}

function Glance({ areas, onOpen }: { areas: Area[]; onOpen: (key: string) => void }) {
  return (
    <section className="flex flex-col rounded-xl border">
      <header className="border-b px-4 py-2.5">
        <h2 className="text-[15px] font-semibold">At a glance</h2>
      </header>
      <ul className="divide-y">
        {areas.map((a) => (
          <li key={a.key}>
            <button type="button" onClick={() => onOpen(a.key)} className="grid w-full grid-cols-[88px_minmax(0,1fr)] items-start gap-3 px-4 py-2 text-left hover:bg-muted/40 sm:grid-cols-[96px_110px_minmax(0,1fr)]">
              <span className="text-sm font-medium">{SECTION_META[a.key as keyof Sections]?.title ?? a.title}</span>
              <span className={cn('flex items-center gap-1.5 text-sm', TONE_TEXT[a.status])}>
                <span className="size-2 rounded-full bg-current" aria-hidden="true" />
                {a.word}
              </span>
              <span className="col-span-2 text-sm text-muted-foreground sm:col-span-1">{a.note}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

function Bar({ value, max, mark, tone = 'none' }: { value: number; max: number; mark?: number | null; tone?: Tone }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0
  return (
    <div className="relative h-2 min-w-20 rounded-full border bg-muted/60" aria-hidden="true">
      <div className={cn('absolute inset-y-0 left-0 rounded-full', tone === 'none' ? 'bg-foreground/80' : tone === 'bad' ? 'bg-destructive' : tone === 'warn' ? 'bg-draft' : 'bg-success')} style={{ width: `${pct}%` }} />
      {mark !== null && mark !== undefined && max > 0 && (
        <div className="absolute -inset-y-1 w-0.5 bg-primary-ink" style={{ left: `${Math.min((mark / max) * 100, 100)}%` }} />
      )}
    </div>
  )
}

function SectionLink({ to, label = 'Open' }: { to?: string; label?: string }) {
  if (!to) return null
  return (
    <Link to={to} className="inline-flex items-center gap-0.5 text-sm text-primary-ink hover:underline">
      {label} <ChevronRight className="size-3.5" />
    </Link>
  )
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="rounded-lg border border-dashed px-4 py-5 text-sm text-muted-foreground">{children}</p>
}

function WorkSection({ w }: { w: NonNullable<Sections['work']> }) {
  const [all, setAll] = React.useState(false)
  const quiet = w.rows.filter((r) => r.done_in_period.length === 0 && r.state === 'on_track')
  const rows = all ? w.rows : w.rows.filter((r) => !quiet.includes(r))
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground">
        {w.done_pct !== null ? `${w.done_pct}% of the job done this period` : 'No BOQ lines to measure against yet'}
        {w.plan_pct !== null && ` against ${w.plan_pct}% planned`}. {w.progress_to_date ?? 0}% done to date
        {w.expected_to_date !== null && `, ${w.expected_to_date}% expected by now`}.
        {w.work_in_other_unit > 0 && ` ${w.work_in_other_unit} record(s) in another unit are not added in.`}
      </p>
      {w.rows.length === 0 ? (
        <Empty>No work was recorded on a BOQ line in this period.</Empty>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="text-xs text-muted-foreground">
              <tr className="border-b">
                <th className="px-3 py-2 text-left font-medium">Activity</th>
                <th className="px-3 py-2 text-left font-medium">Done this period</th>
                <th className="px-3 py-2 text-left font-medium">Done vs plan</th>
                <th className="px-3 py-2 text-left font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {rows.map((r) => {
                const s = STATE[r.state ?? ''] ?? { word: r.state ?? '', tone: 'none' as Tone }
                const late = r.days_late || r.slip_days
                return (
                  <tr key={r.activity_id}>
                    <td className="px-3 py-2">
                      <p className="font-medium">{r.activity}</p>
                      {r.site && <p className="text-xs text-muted-foreground">{r.site}</p>}
                    </td>
                    <td className="px-3 py-2 tabular-nums">
                      {r.done_in_period.length === 0 ? <span className="text-muted-foreground">—</span> : r.done_in_period.map((d) => (
                        <p key={d.work}>{d.quantity} {d.unit} <span className="text-muted-foreground">{d.work}</span></p>
                      ))}
                    </td>
                    <td className="px-3 py-2">
                      <Bar value={r.progress ?? 0} max={100} mark={r.expected} />
                      <p className="mt-1 text-xs tabular-nums text-muted-foreground">{r.progress ?? 0}%{r.expected !== null && ` · plan ${r.expected}%`}</p>
                    </td>
                    <td className="px-3 py-2">
                      <Pill tone={s.tone}>{s.word}{late ? ` · ${late} d` : ''}</Pill>
                      {r.critical && <p className="mt-1 text-xs text-muted-foreground">Critical path</p>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {quiet.length > 0 && (
            <button type="button" onClick={() => setAll((v) => !v)} className="flex w-full items-center gap-1 border-t px-3 py-2 text-sm text-primary-ink">
              <ChevronDown className={cn('size-4 transition-transform', all && 'rotate-180')} />
              {all ? 'Hide' : `${quiet.length} more on track, nothing recorded this period`}
            </button>
          )}
        </div>
      )}
      <p className="text-xs text-muted-foreground">The bar is done to date; the gold mark is where the plan says it should be today.</p>
    </div>
  )
}

function ScheduleSection({ s }: { s: NonNullable<Sections['schedule']> }) {
  if (!s.scheduled) return <Empty>No activity has plan dates yet. Set them in Schedule to compare work with the plan.</Empty>
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground">
        Finish {s.forecast_finish ? shortDay(s.forecast_finish) : 'not forecast'}
        {s.slip_days ? `, ${s.slip_days} days after plan (${shortDay(s.planned_finish)}).` : ', on plan.'}
      </p>
      {s.rows.length === 0 ? (
        <Empty>Nothing is late or behind.</Empty>
      ) : (
        <ul className="divide-y rounded-lg border">
          {s.rows.map((r) => {
            const st = STATE[r.state ?? ''] ?? { word: r.state ?? '', tone: 'none' as Tone }
            return (
              <li key={r.activity_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm">
                <span className="min-w-0 flex-1 font-medium">{r.activity}{r.critical && <span className="ml-2 text-xs font-normal text-muted-foreground">critical path</span>}</span>
                <Pill tone={st.tone}>{st.word}</Pill>
                <span className="tabular-nums text-muted-foreground">
                  {r.days_late ? `${r.days_late} days late` : `on pace to end ${r.slip_days} days late`} · now ends {shortDay(r.forecast_end)}
                </span>
                {r.assigned_to && <span className="text-xs text-muted-foreground">{r.assigned_to}</span>}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

function LabourSection({ l }: { l: NonNullable<Sections['labour']> }) {
  const maxDay = Math.max(...l.by_day.map((d) => Number(d.man_days)), 1)
  const maxTrade = Math.max(...l.by_trade.map((d) => Number(d.man_days)), 1)
  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        {l.man_days} man-days ({l.prev_man_days} the period before){l.average_per_day && `, ${l.average_per_day} a working day`}
        {l.wages !== undefined && `; wages ${inr(l.wages)}`}.
      </p>
      {l.by_day.length > 0 && (
        <div className="flex h-28 items-end gap-1 rounded-lg border px-3 pb-6 pt-3" role="img" aria-label="Man-days each day">
          {l.by_day.map((d) => (
            <div key={d.date} className="relative flex h-full flex-1 flex-col justify-end" title={`${shortDay(d.date)}: ${d.man_days} man-days`}>
              <div className={cn('rounded-t', Number(d.man_days) > 0 ? 'bg-foreground/70' : 'bg-transparent')} style={{ height: `${(Number(d.man_days) / maxDay) * 100}%` }} />
              {l.by_day.length <= 14 && <span className="absolute -bottom-5 left-1/2 -translate-x-1/2 whitespace-nowrap text-[10px] text-muted-foreground">{shortDay(d.date)}</span>}
            </div>
          ))}
        </div>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-medium">By trade</h3>
          {l.by_trade.length === 0 ? <Empty>No attendance in this period.</Empty> : l.by_trade.map((t) => (
            <div key={t.label} className="grid grid-cols-[100px_minmax(0,1fr)_auto] items-center gap-3 text-sm">
              <span className="truncate">{t.label}</span>
              <Bar value={Number(t.man_days)} max={maxTrade} />
              <span className="tabular-nums">{t.man_days}{t.wages !== undefined && <span className="ml-2 text-muted-foreground">{inr(t.wages)}</span>}</span>
            </div>
          ))}
        </div>
        {l.by_site.length > 1 && (
          <div className="flex flex-col gap-2">
            <h3 className="text-sm font-medium">By site</h3>
            {l.by_site.map((t) => (
              <div key={t.label} className="flex justify-between text-sm"><span>{t.label}</span><span className="tabular-nums">{t.man_days}</span></div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function StockValueSection({ v }: { v: NonNullable<Sections['stock_value']> }) {
  if (!v.items) return <Empty>No stock on hand at the end of this period.</Empty>
  return (
    <div className="flex flex-col gap-2 text-sm">
      <p>
        <strong className="tabular-nums">{inr(v.total)}</strong> on hand ({v.items} items)
        {v.slow_moving > 0 && <> · <span className="text-draft">{inr(v.slow_moving_value)} not used in 30 days ({v.slow_moving})</span></>}
        {v.unpriced > 0 && <span className="text-muted-foreground"> · {v.unpriced} with no rate yet</span>}
      </p>
      <ul className="divide-y rounded-lg border">
        {v.top.slice(0, 5).map((r) => (
          <li key={`${r.site_name}:${r.material}`} className="flex items-center justify-between gap-2 px-3 py-1.5">
            <span className="min-w-0 truncate">{r.material} <span className="text-muted-foreground">· {r.site_name}</span></span>
            <span className="shrink-0 tabular-nums">{r.value ? inr(r.value) : '—'}</span>
          </li>
        ))}
      </ul>
      <Link to={v.link} className="text-xs font-medium underline-offset-2 hover:underline">Stock value →</Link>
    </div>
  )
}

function MaterialsSection({ m }: { m: NonNullable<Sections['materials']> }) {
  if (m.rows.length === 0) return <Empty>Nothing was received or used in this period.</Empty>
  const money = m.rows.some((r) => r.spend !== undefined)
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-sm">
        <thead className="text-xs text-muted-foreground">
          <tr className="border-b">
            <th className="px-3 py-2 text-left font-medium">Material</th>
            <th className="px-3 py-2 text-right font-medium">In</th>
            <th className="px-3 py-2 text-right font-medium">Used</th>
            <th className="px-3 py-2 text-right font-medium">Left</th>
            <th className="px-3 py-2 text-left font-medium">Lasts</th>
            {money && <th className="px-3 py-2 text-right font-medium">Spend</th>}
          </tr>
        </thead>
        <tbody className="divide-y tabular-nums">
          {m.rows.map((r, i) => (
            <tr key={`${r.material}-${r.site}-${i}`}>
              <td className="px-3 py-2"><p className="font-medium">{r.material}</p>{r.site && <p className="text-xs text-muted-foreground">{r.site}</p>}</td>
              <td className="px-3 py-2 text-right">{r.received}</td>
              <td className="px-3 py-2 text-right">{r.used}</td>
              <td className="px-3 py-2 text-right">{r.closing} <span className="text-muted-foreground">{r.unit}</span></td>
              <td className="px-3 py-2">{r.running_low ? <Pill tone="warn">{r.days_left ? `${r.days_left} days` : 'Running low'}</Pill> : r.days_left ? `${r.days_left} days` : '—'}</td>
              {money && <td className="px-3 py-2 text-right">{r.spend ? inr(r.spend) : '—'}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function MoneySection({ m }: { m: NonNullable<Sections['money']> }) {
  const max = Math.max(...m.centres.map((c) => Number(c.amount)), 1)
  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 md:grid-cols-2">
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-medium">Spent {inr(m.spent)} <span className="font-normal text-muted-foreground">({inr(m.prev_spent)} the period before)</span></h3>
          {m.centres.length === 0 ? <Empty>Nothing spent in this period.</Empty> : m.centres.map((c) => (
            <div key={c.key} className="grid grid-cols-[110px_minmax(0,1fr)_auto] items-center gap-3 text-sm">
              <span className="truncate">{c.label}</span>
              <Bar value={Number(c.amount)} max={max} />
              <span className="tabular-nums">{inr(c.amount)}</span>
            </div>
          ))}
        </div>
        {m.billed !== undefined && [m.billed, m.received, m.owed].some((v) => Number(v ?? 0) !== 0) && (
          <div className="grid grid-cols-2 gap-2 self-start">
            {[
              ['Billed', m.billed],
              ['Received', m.received],
              ['Client owes', m.owed],
              ['Over 30 days', m.overdue],
            ].map(([label, v]) => (
              <div key={label} className="rounded-lg border px-3 py-2">
                <p className="text-xs text-muted-foreground">{label}</p>
                <p className={cn('text-lg font-semibold tabular-nums', label === 'Over 30 days' && Number(v) > 0 && 'text-destructive')}>{inr(v)}</p>
              </div>
            ))}
          </div>
        )}
      </div>
      {m.worst_lines.length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-medium">Labour against the work it earned</h3>
          <ul className="divide-y rounded-lg border">
            {m.worst_lines.map((ln) => (
              <li key={`${ln.work}-${ln.section}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm">
                <span className="min-w-0 flex-1">{ln.work}{ln.section && <span className="ml-2 text-xs text-muted-foreground">{ln.section}</span>}</span>
                <Pill tone={ln.colour === 'red' ? 'bad' : 'warn'}>{ln.colour === 'red' ? 'Over' : 'Watch'}</Pill>
                <span className="tabular-nums text-muted-foreground">{inr(ln.labour_cost)} for {ln.done_quantity} {ln.unit}{ln.earned_labour && ` · earned ${inr(ln.earned_labour)}`}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {(m.overdue_bills ?? []).length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-medium">Unpaid over 30 days</h3>
          <ul className="divide-y rounded-lg border">
            {(m.overdue_bills ?? []).map((b) => (
              <li key={b.ref} className="flex items-center justify-between px-3 py-2 text-sm">
                <span>{b.ref} <span className="text-muted-foreground">billed {shortDay(b.bill_date)}</span></span>
                <span className="tabular-nums">{inr(b.left)} · <span className={b.days > 60 ? 'text-destructive' : 'text-draft'}>{b.days} days</span></span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function IssuesSection({ i }: { i: NonNullable<Sections['issues']> }) {
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground">{i.raised} raised, {i.closed} closed in the period; {i.open} still open.</p>
      {i.rows.length === 0 ? <Empty>Nothing open.</Empty> : (
        <ul className="divide-y rounded-lg border">
          {i.rows.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm">
              <Pill tone={r.severity === 'critical' || r.severity === 'high' ? 'bad' : r.severity === 'medium' ? 'warn' : 'none'}>{r.severity}</Pill>
              <span className="min-w-0 flex-1">{r.what || r.type.replace(/_/g, ' ').toLowerCase()}</span>
              <span className="text-xs text-muted-foreground">{r.site ? `${r.site} · ` : ''}open {r.days_open} days</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function PhotosSection({ p }: { p: NonNullable<Sections['photos']> }) {
  if (p.rows.length === 0) return <Empty>No photos from confirmed site days in this period. Photos show once the evening report is confirmed.</Empty>
  return (
    <div className="flex flex-col gap-2">
      <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {p.rows.map((ph, idx) => (
          <li key={idx} className="flex flex-col gap-1">
            {ph.url ? <img src={ph.url} alt={ph.caption ?? ph.work ?? 'Site photo'} className="aspect-[4/3] w-full rounded-lg border object-cover" loading="lazy" /> : <div className="aspect-[4/3] rounded-lg bg-muted" />}
            <p className="truncate text-xs text-muted-foreground">{shortDay(ph.date)} · {ph.caption || ph.work || ph.site}</p>
          </li>
        ))}
      </ul>
      {p.available > p.rows.length && <p className="text-xs text-muted-foreground">{p.rows.length} of {p.available}, spread over the period.</p>}
    </div>
  )
}

function DataCheck({ c }: { c: NonNullable<Sections['completeness']> }) {
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground">
        {c.days_full} of {c.days_total} days with every site report confirmed
        {c.days_no_attendance.length > 0 && `; ${c.days_no_attendance.length} without attendance`}. A day without its report makes the figures short.
      </p>
      <ul className="flex flex-wrap gap-1.5">
        {c.days.map((d) => {
          const full = d.reports >= d.sites
          const tone: Tone = full && d.attendance > 0 ? 'good' : d.reports > 0 || d.attendance > 0 ? 'warn' : 'none'
          return (
            <li key={d.date}>
              <Link
                to={`/reports?date=${d.date}`}
                title={`${d.weekday} ${shortDay(d.date)}: ${d.reports} of ${d.sites} site reports confirmed, attendance at ${d.attendance}${d.weather ? `, ${d.weather}` : ''}`}
                className={cn('flex w-12 flex-col items-center rounded-md border px-1 py-1 text-xs', TONE_SOFT[tone])}
              >
                <span className="font-medium">{d.weekday}</span>
                <span className="tabular-nums">{new Date(`${d.date}T00:00:00`).getDate()}</span>
              </Link>
            </li>
          )
        })}
      </ul>
      <p className="text-xs text-muted-foreground">Green: confirmed with attendance. Amber: part of it. Grey: nothing confirmed.</p>
    </div>
  )
}

function SectionBody({ k, s }: { k: keyof Sections; s: Sections }) {
  switch (k) {
    case 'work': return s.work ? <WorkSection w={s.work} /> : null
    case 'schedule': return s.schedule ? <ScheduleSection s={s.schedule} /> : null
    case 'labour': return s.labour ? <LabourSection l={s.labour} /> : null
    case 'materials': return s.materials ? <MaterialsSection m={s.materials} /> : null
    case 'stock_value': return s.stock_value ? <StockValueSection v={s.stock_value} /> : null
    case 'money': return s.money ? <MoneySection m={s.money} /> : null
    case 'issues': return s.issues ? <IssuesSection i={s.issues} /> : null
    case 'photos': return s.photos ? <PhotosSection p={s.photos} /> : null
    case 'completeness': return s.completeness ? <DataCheck c={s.completeness} /> : null
  }
}

function ProjectPicker() {
  const projects = useQuery({ queryKey: ['scope-projects'], queryFn: fetchProjects })
  if (projects.isLoading) return <Skeleton className="h-32 rounded-lg" />
  if ((projects.data ?? []).length === 0) return <p className="text-sm text-muted-foreground">No projects yet.</p>
  return (
    <ul className="divide-y rounded-lg border">
      {(projects.data ?? []).map((p) => (
        <li key={p.id}>
          <Link to={`/reports/period?project=${p.id}`} className="flex items-center gap-3 px-4 py-3 hover:bg-muted/60">
            <span className="flex size-8 items-center justify-center rounded-md bg-muted"><CalendarRange className="size-4" /></span>
            <span className="flex-1 font-medium">{p.name}</span>
            <ChevronRight className="size-4 text-muted-foreground" />
          </Link>
        </li>
      ))}
    </ul>
  )
}

function DownloadButton({ q, kind, fallback }: { q: PeriodQuery; kind: 'pdf' | 'xlsx'; fallback: string }) {
  const toast = useToast()
  const [busy, setBusy] = React.useState(false)
  const Icon = kind === 'pdf' ? FileText : FileSpreadsheet
  const go = async () => {
    setBusy(true)
    try {
      const { blob, filename } = await downloadPeriodReport(q, kind, fallback)
      downloadBlob(filename, blob)
    } catch (err) {
      toast.error(kind === 'pdf' ? 'Could not make the PDF' : 'Could not make the Excel file', apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Button size="sm" variant="outline" onClick={go} disabled={busy}>
      <Icon className="size-3.5" /> {busy ? 'Preparing…' : kind === 'pdf' ? 'PDF' : 'Excel'}
    </Button>
  )
}

function BriefDownload({ q, kind }: { q: BriefQuery; kind: 'pdf' | 'xlsx' }) {
  const toast = useToast()
  const [busy, setBusy] = React.useState(false)
  const Icon = kind === 'pdf' ? FileText : FileSpreadsheet
  const go = async () => {
    setBusy(true)
    try {
      const { blob, filename } = await downloadBrief(q, kind)
      downloadBlob(filename, blob)
    } catch (err) {
      toast.error(kind === 'pdf' ? 'Could not make the PDF' : 'Could not make the Excel file', apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Button size="sm" variant="outline" onClick={go} disabled={busy}>
      <Icon className="size-3.5" /> {busy ? 'Preparing…' : kind === 'pdf' ? 'PDF' : 'Excel'}
    </Button>
  )
}

const COST_WORD: Record<string, { word: string; tone: Tone }> = {
  red: { word: 'Over', tone: 'bad' },
  amber: { word: 'Watch', tone: 'warn' },
  green: { word: 'On budget', tone: 'good' },
  grey: { word: 'No budget', tone: 'none' },
}

/** RPT-01: every running project on one page, the one that needs you most first. Each row opens its own report. */
function BriefView({ b, linkFor }: { b: Brief; linkFor: (projectId: string) => string }) {
  return (
    <div className="flex flex-col gap-4">
      <Headline h={b.headline} />
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
        {b.kpis.map((k, i) => (
          <div key={k.key} className={cn('flex', b.kpis.length % 2 === 1 && i === b.kpis.length - 1 && 'col-span-2 sm:col-span-1')}>
            <KpiTile k={k} onOpen={() => undefined} />
          </div>
        ))}
      </div>
      {b.projects.length === 0 ? (
        <Empty>No running projects you can see.</Empty>
      ) : (
        <div className="overflow-x-auto rounded-xl border">
          <table className="w-full text-sm">
            <thead className="text-xs text-muted-foreground">
              <tr className="border-b">
                <th className="px-3 py-2 text-left font-medium">Project</th>
                <th className="px-3 py-2 text-left font-medium">Done vs plan</th>
                {b.sees_money && <th className="px-3 py-2 text-left font-medium">Cost</th>}
                <th className="px-3 py-2 text-left font-medium">Finish</th>
                <th className="px-3 py-2 text-right font-medium">Man-days</th>
                {b.has_bills && <th className="px-3 py-2 text-right font-medium">Clients owe</th>}
                <th className="px-3 py-2 text-left font-medium">Top item</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {b.projects.map((p) => {
                const cost = COST_WORD[p.labour_colour ?? 'grey'] ?? COST_WORD.grey
                const expected = p.expected_to_date === null ? null : Number(p.expected_to_date)
                return (
                  <tr key={p.project_id} className="hover:bg-muted/40">
                    <td className="px-3 py-2">
                      <Link to={linkFor(p.project_id)} className="flex items-center gap-2 font-medium hover:underline">
                        <span className={cn('size-2 shrink-0 rounded-full', p.status === 'bad' ? 'bg-destructive' : p.status === 'warn' ? 'bg-draft' : p.status === 'good' ? 'bg-success' : 'bg-muted-foreground/40')} aria-hidden="true" />
                        {p.name}
                      </Link>
                      {p.client && <p className="pl-4 text-xs text-muted-foreground">{p.client}</p>}
                    </td>
                    <td className="px-3 py-2">
                      <Bar value={p.progress_to_date ?? 0} max={100} mark={expected} />
                      <p className="mt-1 text-xs tabular-nums text-muted-foreground">{p.progress_to_date ?? 0}%{expected !== null && ` · plan ${Math.round(expected)}%`}</p>
                    </td>
                    {b.sees_money && <td className="px-3 py-2"><Pill tone={cost.tone}>{cost.word}</Pill></td>}
                    <td className="px-3 py-2 tabular-nums">
                      {p.forecast_finish ? <>{shortDay(p.forecast_finish)}{p.slip_days > 0 && <span className="ml-1 text-xs text-draft">+{p.slip_days} d</span>}</> : <span className="text-muted-foreground">No plan</span>}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">{p.man_days ?? '0'}</td>
                    {b.has_bills && (
                      <td className="px-3 py-2 text-right tabular-nums">
                        {inr(p.owed)}
                        {Number(p.overdue ?? 0) > 0 && <p className="text-xs text-destructive">{inr(p.overdue)} over 30 d</p>}
                      </td>
                    )}
                    <td className="max-w-64 px-3 py-2 text-xs text-muted-foreground">{p.top ?? '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      {b.unavailable.length > 0 && <p className="text-sm text-draft">Could not be read just now: {b.unavailable.join(', ')}.</p>}
    </div>
  )
}

const KIND_OPTIONS: { value: PeriodKind; label: string }[] = [
  { value: 'week', label: 'Week' },
  { value: 'month', label: 'Month' },
  { value: 'custom', label: 'Dates' },
]

export default function PeriodReportPage() {
  const { scope } = useScope()
  const [params, setParams] = useSearchParams()
  usePageTitle('Weekly & monthly')
  const projectId = scope.mode !== 'portfolio' ? scope.projectId : null
  const siteId = scope.mode === 'site' ? scope.siteId : undefined
  const kind = (['week', 'month', 'custom'].includes(params.get('period') ?? '') ? params.get('period') : 'week') as PeriodKind
  const query: PeriodQuery | null = projectId
    ? { project_id: projectId, site_id: siteId, period: kind, date: params.get('date') ?? undefined, date_from: params.get('from') ?? undefined, date_to: params.get('to') ?? undefined }
    : null
  const ready = !!query && (kind !== 'custom' || (!!query.date_from && !!query.date_to))
  const q = useQuery({
    queryKey: ['period-report', query],
    queryFn: () => fetchPeriodReport(query!),
    enabled: ready,
    placeholderData: (prev) => prev,
  })
  // RPT-01: with no project picked, the page is the owner's brief across every project.
  const briefQuery: BriefQuery = { period: kind, date: params.get('date') ?? undefined, date_from: params.get('from') ?? undefined, date_to: params.get('to') ?? undefined }
  const briefReady = !projectId && (kind !== 'custom' || (!!briefQuery.date_from && !!briefQuery.date_to))
  const bq = useQuery({
    queryKey: ['portfolio-report', briefQuery],
    queryFn: () => fetchBrief(briefQuery),
    enabled: briefReady,
    placeholderData: (prev) => prev,
  })
  const [sending, setSending] = React.useState(false)
  const [tab, setTab] = React.useState<keyof Sections>('work')
  const sectionsRef = React.useRef<HTMLDivElement>(null)

  const set = React.useCallback((changes: Record<string, string | null>) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev)
      for (const [k, v] of Object.entries(changes)) {
        if (v === null) next.delete(k)
        else next.set(k, v)
      }
      return next
    }), [setParams])

  const r = projectId ? q.data : undefined
  const info = projectId ? q.data : bq.data
  const step = React.useCallback((dir: -1 | 1) => {
    if (!info) return
    const target = dir < 0 ? info.previous : info.next
    if (!target) return
    if (info.period.kind === 'custom') set({ from: target.from, to: target.to })
    else set({ date: target.from })
  }, [info, set])

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)) return
      if (e.metaKey || e.ctrlKey || e.altKey) return
      if (e.key === 'ArrowLeft') step(-1)
      if (e.key === 'ArrowRight') step(1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [step])

  // A section the person cannot see (or a module switched off) falls back to the first one shown.
  const active: keyof Sections = r && !r.order.includes(tab) ? (r.order[0] ?? 'work') : tab

  const open = (key: string) => {
    if (r?.order.includes(key as keyof Sections)) {
      setTab(key as keyof Sections)
      sectionsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }

  const where = scope.mode === 'site' ? `${scope.projectName} · ${scope.siteName}` : scope.mode === 'project' ? scope.projectName : 'All projects'
  const fallbackName = `mesiri-${(r?.project.name ?? 'project').replace(/[^A-Za-z0-9]+/g, '-').toLowerCase()}-${r?.period.from ?? ''}`
  const target = projectId ? { scope: 'project' as const, project_id: projectId, site_id: siteId } : { scope: 'portfolio' as const }
  const sendButton = info ? (
    <Button size="sm" onClick={() => setSending(true)}>
      <Send className="size-3.5" /> Send
    </Button>
  ) : null
  const header = (
    <DprHeader
      back={{ to: '/reports', label: 'Daily reports' }}
      crumb="Reports"
      title="Weekly & monthly"
      date={where}
      action={ready && query ? (
        <div className="flex gap-2">
          <DownloadButton q={query} kind="xlsx" fallback={fallbackName} />
          <DownloadButton q={query} kind="pdf" fallback={fallbackName} />
          {sendButton}
        </div>
      ) : briefReady ? (
        <div className="flex gap-2">
          <BriefDownload q={briefQuery} kind="xlsx" />
          <BriefDownload q={briefQuery} kind="pdf" />
          {sendButton}
        </div>
      ) : undefined}
    />
  )
  const sendDialog = info ? (
    <SendReportDialog
      target={target}
      query={briefQuery}
      what={`${where}: ${info.period.kind === 'custom' ? info.period.range : `${info.period.label}, ${info.period.range}`}`}
      open={sending}
      onOpenChange={setSending}
    />
  ) : null

  const controls = (
    <div className="flex flex-wrap items-center gap-2">
      <Segmented label="Period" value={kind} options={KIND_OPTIONS} onChange={(v) => set({ period: v, date: null, ...(v === 'custom' && info ? { from: info.period.from, to: info.period.to } : { from: null, to: null }) })} />
      {kind === 'custom' ? (
        <div className="flex items-center gap-1.5 text-sm">
          <label className="sr-only" htmlFor="report-from">From</label>
          <input id="report-from" type="date" className="h-8 rounded-md border bg-background px-2" value={params.get('from') ?? ''} onChange={(e) => set({ from: e.target.value })} />
          <span className="text-muted-foreground">to</span>
          <label className="sr-only" htmlFor="report-to">To</label>
          <input id="report-to" type="date" className="h-8 rounded-md border bg-background px-2" value={params.get('to') ?? ''} onChange={(e) => set({ to: e.target.value })} />
        </div>
      ) : null}
      {info && (
        <div className="flex items-center gap-1">
          <Button size="icon" variant="ghost" className="size-8" aria-label={`Previous: ${info.previous.label}`} title={`${info.previous.label} (←)`} onClick={() => step(-1)}>
            <ChevronLeft className="size-4" />
          </Button>
          <Button size="icon" variant="ghost" className="size-8" aria-label={info.next ? `Next: ${info.next.label}` : 'No next period yet'} title={info.next ? `${info.next.label} (→)` : 'Not started yet'} onClick={() => step(1)} disabled={!info.next}>
            <ChevronRight className="size-4" />
          </Button>
        </div>
      )}
    </div>
  )

  if (!projectId) {
    const b = bq.data
    const linkFor = (id: string) => {
      const next = new URLSearchParams(params)
      next.set('project', id)
      return `/reports/period?${next.toString()}`
    }
    return (
      <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
        {header}
        {controls}
        {sendDialog}
        {kind === 'custom' && !briefReady ? (
          <Empty>Choose the first and last day (at most 92 days).</Empty>
        ) : bq.isError && !b ? (
          <PageError message="The report could not be loaded." onRetry={() => bq.refetch()} back={{ to: '/reports', label: 'Daily reports' }} />
        ) : !b ? (
          <div className="flex flex-col gap-3" aria-busy="true">
            <Skeleton className="h-16 rounded-lg" />
            <Skeleton className="h-64 rounded-xl" />
          </div>
        ) : (
          <div className={cn('flex flex-col gap-4 transition-opacity', bq.isFetching && 'opacity-60')}>
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h2 className="text-xl font-semibold tracking-tight">{b.period.kind === 'custom' ? b.period.range : b.period.label}</h2>
              {b.period.kind !== 'custom' && <span className="text-sm text-muted-foreground">{b.period.range}</span>}
              {b.running && <Pill tone="none">So far: the period is still running</Pill>}
            </div>
            <BriefView b={b} linkFor={linkFor} />
            <SentAndScheduled target={target} />
          </div>
        )}
        <details className="rounded-lg border px-4 py-2">
          <summary className="cursor-pointer text-sm font-medium">Open one project's report</summary>
          <div className="pt-3"><ProjectPicker /></div>
        </details>
      </div>
    )
  }

  if (kind === 'custom' && !ready) {
    return (
      <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
        {header}
        {controls}
        <Empty>Choose the first and last day (at most 92 days).</Empty>
      </div>
    )
  }
  if (q.isError && !r) {
    const detail = (q.error as { response?: { data?: { detail?: string } } } | null)?.response?.data?.detail
    return (
      <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
        {header}
        {controls}
        {typeof detail === 'string' ? <Empty>{detail}</Empty> : (
          <PageError message="The report could not be loaded." onRetry={() => q.refetch()} back={{ to: '/reports', label: 'Daily reports' }} />
        )}
      </div>
    )
  }

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      {header}
      {controls}
      {sendDialog}
      {!r ? (
        <div className="flex flex-col gap-3" aria-busy="true">
          <Skeleton className="h-6 w-60" />
          <Skeleton className="h-16 rounded-lg" />
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-24 rounded-xl" />)}</div>
          <Skeleton className="h-64 rounded-xl" />
        </div>
      ) : (
        <div className={cn('flex flex-col gap-4 transition-opacity', q.isFetching && 'opacity-60')}>
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h2 className="text-xl font-semibold tracking-tight">{r.period.kind === 'custom' ? r.period.range : r.period.label}</h2>
            {r.period.kind !== 'custom' && <span className="text-sm text-muted-foreground">{r.period.range}</span>}
            {r.running && <Pill tone="none">So far: the period is still running</Pill>}
          </div>
          <Headline h={r.headline} />
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
            {r.kpis.map((k, i) => (
              <div key={k.key} className={cn('flex', r.kpis.length % 2 === 1 && i === r.kpis.length - 1 && 'col-span-2 sm:col-span-1')}>
                <KpiTile k={k} onOpen={open} />
              </div>
            ))}
          </div>
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
            <NeedsList items={r.needs_you} />
            <Glance areas={r.areas} onOpen={open} />
          </div>
          {r.unavailable.length > 0 && (
            <p className="rounded-lg border border-draft/30 bg-draft-soft px-3 py-2 text-sm text-draft">
              Could not be read just now: {r.unavailable.map((k) => SECTION_META[k as keyof Sections]?.title ?? k).join(', ')}. The rest of the report is complete.
            </p>
          )}
          <div ref={sectionsRef} className="scroll-mt-20">
            <div className="mb-3 overflow-x-auto">
              <Segmented
                label="Section"
                value={active}
                options={r.order.map((k) => ({ value: k, label: SECTION_META[k].title }))}
                onChange={(v) => setTab(v)}
              />
            </div>
            {r.order.includes(active) && (
              <DprSection
                icon={SECTION_META[active].icon}
                iconClass={SECTION_META[active].tile}
                title={SECTION_META[active].title}
                meta={r.areas.find((a) => a.key === active)?.word}
                action={<SectionLink to={(r.sections[active] as { link?: string } | undefined)?.link} />}
              >
                <SectionBody k={active} s={r.sections} />
              </DprSection>
            )}
          </div>
          <SentAndScheduled target={target} />
          <p className="text-xs text-muted-foreground">
            Every figure comes from the module that records it: the BOQ and schedule, attendance, stock, expenses and bills. Rupees only show for the roles that see spending.
          </p>
        </div>
      )}
    </div>
  )
}
