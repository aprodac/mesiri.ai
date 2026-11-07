import * as React from 'react'
import { Check, Clock } from 'lucide-react'
import type { ProjectDayItem, SiteDayItem } from '@/lib/api'
import { longDate } from '@/lib/site-day'
import { prefersReducedMotion } from '@/lib/timeline'
import { cn } from '@/lib/utils'
import { Count } from './meet'

// The company Live's evening (WEB-61): a strip under the header with each
// project's report time, the time left, and each site's state (ready, or
// what it still waits for), ticking off as messages land; and when a
// project's report goes out, its sheet builds on the stage from the day's
// sites, then folds into the PDF and drops into WhatsApp (the site Live's
// Finale, reused). Read from the site-days list the page already polls.

const still = () => prefersReducedMotion()
const at = (name: string, s: number, ms = 500) => (still() ? undefined : { animation: `${name} ${ms}ms cubic-bezier(.2,.9,.3,1) ${s}s both` })

const PART: Record<string, string> = { labour: 'Manpower', manpower: 'Manpower', work: 'Work done', materials: 'Materials', photos: 'Photos', issues: 'Issues' }
const part = (k: string) => PART[k] ?? k.replace(/_/g, ' ')

/** "21:00" (the project's local send time) today, as a Date. */
function todayAt(hhmm: string | null): Date | null {
  const m = (hhmm ?? '').match(/^(\d{1,2}):(\d{2})/)
  if (!m) return null
  const d = new Date()
  d.setHours(Number(m[1]), Number(m[2]), 0, 0)
  return d
}
function left(ms: number): string {
  const mins = Math.max(0, Math.round(ms / 60_000))
  const h = Math.floor(mins / 60)
  return h ? `${h}h ${mins % 60}m` : `${mins}m`
}
function clockOf(hhmm: string | null): string {
  const d = todayAt(hhmm)
  return d ? d.toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' }) : ''
}

/** Each project's report: when it goes, the time left, and each site ready or waiting. */
export function ReportStrip({
  projects,
  sites,
  isToday,
  onSite,
}: {
  projects: ProjectDayItem[]
  sites: SiteDayItem[]
  isToday: boolean
  onSite: (s: SiteDayItem) => void
}) {
  const [now, setNow] = React.useState(() => Date.now())
  React.useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 30_000)
    return () => window.clearInterval(t)
  }, [])
  if (!projects.length) return null
  return (
    <div className="grid gap-2 border-b border-foreground/15 py-3" aria-label="Today's reports">
      {projects.slice(0, 3).map((p) => {
        const mine = sites.filter((s) => s.project_id === p.project_id)
        const ready = mine.filter((s) => !(s.missing_sections?.blocking?.length ?? 0) && s.last_update_at)
        const due = todayAt(p.dpr_send_deadline)
        const late = due ? due.getTime() - now : null
        return (
          <div key={p.project_id} className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
            <span className="font-semibold">{p.project_name}</span>
            {p.sent ? (
              <span className="flex items-center gap-1.5 font-medium text-[var(--success)]">
                <Check className="size-4" /> Report sent{p.dpr_send_deadline ? ` · ${clockOf(p.dpr_send_deadline)}` : ''}
              </span>
            ) : p.send_requested ? (
              <span className="font-medium text-primary-ink">Report going out now…</span>
            ) : (
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <Clock className="size-3.5" />
                {due ? `Report at ${clockOf(p.dpr_send_deadline)}` : 'Report today'}
                {isToday && late != null && late > 0 && (
                  <b className={cn('tabular-nums', late < 60 * 60_000 ? 'text-primary-ink' : 'text-foreground')}>in {left(late)}</b>
                )}
                {isToday && late != null && late <= 0 && <b className="text-primary-ink">due now</b>}
              </span>
            )}
            <span className="font-mono text-[12px] text-muted-foreground">
              {ready.length} of {mine.length} sites ready
            </span>
            <span className="flex flex-wrap gap-1.5">
              {mine.map((s) => {
                const waiting = s.missing_sections?.blocking ?? []
                const ok = !waiting.length && !!s.last_update_at
                return (
                  <button
                    key={s.site_id}
                    type="button"
                    onClick={() => onSite(s)}
                    title={ok ? 'Ready' : waiting.length ? `Waiting for ${waiting.map(part).join(', ')}` : 'Nothing from site yet'}
                    className={cn(
                      'flex items-center gap-1 border px-2 py-0.5 text-[12px] transition-colors duration-500 hover:border-foreground',
                      ok ? 'border-[var(--success)] text-[var(--success)]' : 'border-foreground/25 text-muted-foreground',
                    )}
                  >
                    {ok && <Check className="size-3" />}
                    {s.site_name}
                    {!ok && <span className="text-[11px]">· {waiting.length ? waiting.map(part).join(', ') : 'nothing yet'}</span>}
                  </button>
                )
              })}
            </span>
          </div>
        )
      })}
    </div>
  )
}

/** A project's report, built on the stage from its sites' day, before it folds into the PDF. */
export const ProjectSheet = React.forwardRef<HTMLDivElement, { project: ProjectDayItem; sites: SiteDayItem[]; company: string | null; date: string }>(
  function ProjectSheet({ project, sites, company, date }, ref) {
    const mine = sites.filter((s) => s.project_id === project.project_id)
    const sum = (f: (s: SiteDayItem) => number) => mine.reduce((n, s) => n + (f(s) || 0), 0)
    const kpis: [number, string, boolean?][] = [
      [sum((s) => s.workers), 'workers'],
      [sum((s) => s.work_items + s.progress_updates), 'work items'],
      [sum((s) => s.materials), 'materials'],
      [sum((s) => s.photos), 'photos'],
      [sum((s) => s.open_issues), 'open issues', true],
    ]
    const attention = mine.flatMap((s) => [
      ...(s.open_issues ? [`${s.site_name}: ${s.open_issues} open ${s.open_issues === 1 ? 'issue' : 'issues'}`] : []),
      ...((s.missing_sections?.blocking?.length ?? 0) ? [`${s.site_name}: no ${s.missing_sections!.blocking.map(part).join(', ').toLowerCase()} today`] : []),
    ])
    return (
      <div ref={ref} className="w-full max-w-[40rem] border border-foreground/30 bg-background px-5 py-4 text-left shadow-[8px_8px_0_0_var(--primary)]" style={at('meet-pop', 0, 600)}>
        <div className="flex items-start justify-between gap-3 border-b border-foreground pb-2">
          <span>
            <span className="block text-xs text-muted-foreground">{company ?? 'Your company'} · Daily Progress Report</span>
            <span className="block text-[22px] font-bold tracking-[-0.02em]">{project.project_name}</span>
          </span>
          <span className="text-right text-xs text-muted-foreground">{longDate(date)}</span>
        </div>
        <div className="grid grid-cols-5 gap-2 py-3">
          {kpis.map(([n, w, red], i) => (
            <span key={w} style={at('meet-rise', 0.3 + i * 0.12)}>
              <span className={cn('block text-[26px] font-bold leading-none tabular-nums', red && n > 0 && 'text-[var(--destructive)]')}>
                <Count to={n} delay={0.4 + i * 0.12} ms={700} />
              </span>
              <span className="text-[11px] text-muted-foreground">{w}</span>
            </span>
          ))}
        </div>
        {attention.length > 0 && (
          <div className="border border-[var(--destructive)]/40 bg-[color-mix(in_srgb,var(--destructive)_6%,transparent)] px-3 py-2" style={at('meet-rise', 1)}>
            <span className="font-mono text-[10px] uppercase tracking-[0.08em] text-[var(--destructive)]">Needs attention</span>
            {attention.slice(0, 4).map((l, i) => (
              <p key={l} className="m-0 mt-1 text-[13px] font-medium" style={at('meet-deal', 1.1 + i * 0.25)}>
                <span className="mr-2 text-[var(--destructive)]">{i + 1}</span>
                {l}
              </p>
            ))}
          </div>
        )}
        <table className="mt-3 w-full border-collapse text-[12px]">
          <thead>
            <tr className="font-mono text-[10px] uppercase tracking-[0.06em] text-muted-foreground">
              <th className="py-1 text-left font-normal">Site</th>
              <th className="py-1 text-right font-normal">Workers</th>
              <th className="py-1 text-right font-normal">Work</th>
              <th className="py-1 text-right font-normal">Materials</th>
              <th className="py-1 text-right font-normal">Issues</th>
            </tr>
          </thead>
          <tbody>
            {mine.map((s, i) => (
              <tr key={s.site_id} className="border-t border-foreground/10" style={at('meet-deal', 1.6 + i * 0.2)}>
                <td className="py-1">{s.site_name}</td>
                <td className="py-1 text-right tabular-nums">{s.workers}</td>
                <td className="py-1 text-right tabular-nums">{s.work_items + s.progress_updates}</td>
                <td className="py-1 text-right tabular-nums">{s.materials}</td>
                <td className={cn('py-1 text-right tabular-nums', s.open_issues > 0 && 'text-[var(--destructive)]')}>{s.open_issues}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="m-0 mt-2 font-mono text-[10px] text-muted-foreground">Made by Mesiri from the day’s messages</p>
      </div>
    )
  },
)

/** How long the sheet builds before it folds into the PDF. */
export const SHEET_MS = 4_200
