import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { BarChart3, Copy, Send } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useToast } from '@/components/ui/toast-notification'
import { EmptyState, ModuleTitle, PageError, Segmented, StatStrip } from '@/components/page/page-kit'
import { ActionIcon } from '@/components/page/action-button'
import { DatePicker } from '@/components/ui/date-picker'
import { useAuth } from '@/lib/AuthContext'
import { appNow } from '@/lib/clock'
import { exportCsv } from '@/lib/export'
import { fetchLabourReport, fetchPayeeStatement, inr, n, periodLabel, type LabourReportRow, type ReportBy } from '@/lib/labour-pay'
import { MONEY_ROLES } from '@/lib/module-map'
import { usePageTitle } from '@/lib/page-title'
import { useScope } from '@/lib/ScopeContext'
import { useUrlState } from '@/lib/url-state'
import { cn } from '@/lib/utils'

// LW-10 (plan docs/plans/wages-and-labour-plan.md 4.10): labour for a period by who is paid, site, project or trade.
// Earned comes from attendance by the wage sheet's own rule; to pay, paid and owed from the wage sheets whose week ends
// in the period. A worker's or team's row opens their statement, shareable on WhatsApp. Backend: GET /labour/pay/report,
// GET /labour/pay/statement.

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const md = (v: unknown) => n(v).toLocaleString('en-IN', { maximumFractionDigits: 2 })

type Period = 'week' | 'four' | 'month' | 'custom'

/** The pay week ends on Saturday (D-W1); "four weeks" is this pay week and the three before it. */
function range(period: Period, from: string, to: string): { from: string; to: string } {
  const today = appNow()
  const end = new Date(today)
  end.setDate(end.getDate() + ((6 - end.getDay() + 7) % 7))
  const weekStart = new Date(end)
  weekStart.setDate(end.getDate() - 6)
  if (period === 'week') return { from: iso(weekStart), to: iso(today) }
  if (period === 'month') return { from: iso(new Date(today.getFullYear(), today.getMonth(), 1)), to: iso(today) }
  if (period === 'custom' && from && to) return { from, to }
  const start = new Date(weekStart)
  start.setDate(weekStart.getDate() - 21)
  return { from: iso(start), to: iso(today) }
}

const BY: { value: ReportBy; label: string; column: string }[] = [
  { value: 'payee', label: 'Who is paid', column: 'Worker or team' },
  { value: 'site', label: 'Site', column: 'Site' },
  { value: 'project', label: 'Project', column: 'Project' },
  { value: 'trade', label: 'Trade', column: 'Trade' },
]

export default function LabourReportsPage() {
  usePageTitle('Labour reports')
  const { me } = useAuth()
  const money = (MONEY_ROLES as readonly string[]).includes((me?.role || '').toUpperCase())
  const { scope } = useScope()
  const projectId = scope.mode === 'portfolio' ? null : scope.projectId
  const siteId = scope.mode === 'site' ? scope.siteId : null
  const [by, setBy] = useUrlState<string>('by', 'payee')
  const [period, setPeriod] = useUrlState<string>('period', 'four')
  const [from, setFrom] = useUrlState<string>('from', '')
  const [to, setTo] = useUrlState<string>('to', '')
  const [open, setOpen] = React.useState<LabourReportRow | null>(null)
  const span = range(period as Period, from, to)
  const kind = (BY.find((b) => b.value === by) ?? BY[0]).value

  const q = useQuery({
    queryKey: ['labour-report', kind, projectId, siteId, span.from, span.to],
    queryFn: () => fetchLabourReport({ by: kind, project_id: projectId, site_id: siteId, date_from: span.from, date_to: span.to }),
    enabled: money,
  })

  if (!money) {
    return <EmptyState icon={BarChart3} title="Labour reports are for the owner, finance and project managers" />
  }
  const r = q.data
  const paidKnown = kind !== 'trade'
  const exportIt = () => {
    if (!r) return
    const col = BY.find((b) => b.value === kind)!.column
    exportCsv(`labour-by-${kind}-${span.from}_to_${span.to}.csv`,
      [col, ...(kind === 'payee' ? ['Trades'] : []), 'Days', 'Man-days', 'Earned (INR)', ...(paidKnown ? ['To pay (INR)', 'Paid (INR)', 'Owed (INR)', 'Not approved (INR)'] : [])],
      r.rows.map((x) => [x.label, ...(kind === 'payee' ? [x.trades] : []), x.days, n(x.man_days), n(x.earned),
        ...(paidKnown ? [n(x.to_pay), n(x.paid), n(x.owed), n(x.waiting)] : [])]))
  }

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <ModuleTitle icon={BarChart3} title="Labour reports" />
        <Button variant="outline" size="sm" className="gap-1.5" disabled={!r?.rows.length} onClick={exportIt}>
          <ActionIcon kind="export-excel" className="size-4" /> Export
        </Button>
      </header>

      <div className="flex flex-wrap items-center gap-2" data-guide="labour-reports.filters">
        <Segmented label="Period" value={period as Period} onChange={(v) => setPeriod(v)} options={[
          { value: 'week', label: 'This week' }, { value: 'four', label: 'Last 4 weeks' },
          { value: 'month', label: 'This month' }, { value: 'custom', label: 'Pick dates' },
        ]} />
        {period === 'custom' && (
          <>
            <DatePicker value={from || span.from} onChange={(v) => setFrom(v)} className="w-36" />
            <span className="text-muted-foreground">–</span>
            <DatePicker value={to || span.to} onChange={(v) => setTo(v)} className="w-36" />
          </>
        )}
        <Segmented label="Group by" guide="labour-reports.by" value={kind} onChange={(v) => setBy(v)} options={BY.map(({ value, label }) => ({ value, label }))} />
      </div>
      <p className="-mt-2 text-xs text-muted-foreground">{periodLabel(span.from, span.to)}</p>

      {q.isError ? (
        <PageError message="The report could not be loaded." onRetry={() => q.refetch()} back={{ to: '/labour/wages', label: 'Wages' }} />
      ) : !r ? (
        <Skeleton className="h-64 rounded-xl" />
      ) : r.rows.length === 0 ? (
        <EmptyState icon={BarChart3} title="No labour in these dates" about="Attendance from the sites shows here." />
      ) : (
        <>
          <StatStrip guide="labour-reports.stats" stats={[
            { label: 'Man-days', value: md(r.totals.man_days), hint: n(r.totals.unpriced_man_days) ? `${md(r.totals.unpriced_man_days)} with no wage` : undefined },
            { label: 'Earned', value: inr(r.totals.earned), hint: 'days × wage, plus overtime' },
            ...(paidKnown ? [
              { label: 'Paid', value: inr(r.totals.paid), tone: 'good' as const },
              { label: 'Owed', value: inr(r.totals.owed), tone: n(r.totals.owed) > 0 ? 'warn' as const : undefined, hint: n(r.totals.waiting) ? `${inr(r.totals.waiting)} not approved yet` : 'approved, not paid' },
            ] : []),
          ]} />
          <div className="overflow-x-auto rounded-xl border bg-card" data-guide="labour-reports.table">
            <table className="w-full min-w-[640px] text-sm">
              <thead className="border-b text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium">{BY.find((b) => b.value === kind)!.column}</th>
                  <th className="px-3 py-2 text-right font-medium">Days</th>
                  <th className="px-3 py-2 text-right font-medium">Man-days</th>
                  <th className="px-3 py-2 text-right font-medium">Earned</th>
                  {paidKnown && <th className="px-3 py-2 text-right font-medium">To pay</th>}
                  {paidKnown && <th className="px-3 py-2 text-right font-medium">Paid</th>}
                  {paidKnown && <th className="px-3 py-2 text-right font-medium">Owed</th>}
                </tr>
              </thead>
              <tbody className="divide-y">
                {r.rows.map((x) => {
                  const noSheet = paidKnown && n(x.earned) > 0 && n(x.to_pay) === 0 && n(x.waiting) === 0
                  return (
                    <tr key={x.key} data-record-id={x.key}
                      className={cn(kind === 'payee' && 'cursor-pointer hover:bg-muted/40')}
                      onClick={kind === 'payee' ? () => setOpen(x) : undefined}>
                      <td className="px-3 py-2">
                        <p className="font-medium">{x.label}</p>
                        {kind === 'payee' && x.trades && <p className="text-xs capitalize text-muted-foreground">{x.trades.replace(/_/g, ' ')}</p>}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">{x.days}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{md(x.man_days)}</td>
                      <td className="px-3 py-2 text-right font-semibold tabular-nums">{inr(x.earned)}</td>
                      {paidKnown && (
                        <td className="px-3 py-2 text-right tabular-nums">
                          {noSheet ? <span className="text-xs text-muted-foreground">No wage sheet</span> : inr(x.to_pay)}
                          {n(x.waiting) > 0 && <p className="text-xs text-draft">{inr(x.waiting)} not approved</p>}
                        </td>
                      )}
                      {paidKnown && <td className="px-3 py-2 text-right tabular-nums text-success">{inr(x.paid)}</td>}
                      {paidKnown && <td className={cn('px-3 py-2 text-right tabular-nums', n(x.owed) > 0 && 'font-semibold text-draft')}>{inr(x.owed)}</td>}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {kind === 'payee' && <p className="text-xs text-muted-foreground">Tap a worker or team for their statement.</p>}
        </>
      )}

      {open && <StatementDialog row={open} projectId={projectId} from={span.from} to={span.to} onClose={() => setOpen(null)} />}
    </div>
  )
}

function StatementDialog({ row, projectId, from, to, onClose }: { row: LabourReportRow; projectId: string | null; from: string; to: string; onClose: () => void }) {
  const toast = useToast()
  const q = useQuery({
    queryKey: ['labour-statement', row.key, projectId, from, to],
    queryFn: () => fetchPayeeStatement({ payee_key: row.key, project_id: projectId, date_from: from, date_to: to }),
  })
  const s = q.data
  const copy = async () => {
    if (!s) return
    try {
      await navigator.clipboard.writeText(s.text)
      toast.success('Statement copied')
    } catch {
      toast.error('Could not copy it')
    }
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{row.label}</DialogTitle>
          <p className="text-xs text-muted-foreground">{periodLabel(from, to)}</p>
        </DialogHeader>
        {q.isError ? (
          <p className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2 text-sm">The statement could not be loaded. <Button variant="outline" size="sm" onClick={() => q.refetch()}>Try again</Button></p>
        ) : !s ? (
          <Skeleton className="h-40 rounded-lg" />
        ) : (
          <div className="flex flex-col gap-3 text-sm" data-guide="labour-reports.statement">
            {s.weeks.length === 0 ? (
              <p className="rounded-lg border bg-muted/30 px-3 py-2 text-muted-foreground">No wage sheet for these weeks yet: {inr(row.earned)} earned from attendance.</p>
            ) : (
              <ul className="divide-y rounded-lg border">
                {s.weeks.map((w) => (
                  <li key={`${w.period_from}-${w.project_name}-${w.site_name}`} className="flex items-start justify-between gap-3 px-3 py-2">
                    <div className="min-w-0">
                      <p className="font-medium">{periodLabel(w.period_from, w.period_to)}</p>
                      <p className="text-xs text-muted-foreground">
                        {w.project_name}{w.site_name ? ` › ${w.site_name}` : ''} · {md(w.man_days)} {n(w.man_days) > n(w.days) ? 'man-days' : 'days'}
                        {n(w.advances_recovered) > 0 && ` · advance −${inr(w.advances_recovered)}`}
                        {n(w.deductions) > 0 && ` · deductions −${inr(w.deductions)}`}
                      </p>
                    </div>
                    <div className="shrink-0 text-right tabular-nums">
                      <p className="font-semibold">{inr(w.net)}</p>
                      <p className={cn('text-xs', w.status !== 'approved' ? 'text-draft' : n(w.due) > 0 ? 'text-draft' : 'text-success')}>
                        {w.status !== 'approved' ? 'not approved' : n(w.due) > 0 ? `${inr(w.due)} due` : 'paid'}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            {s.advances.length > 0 && (
              <p className="text-xs text-muted-foreground">
                Advances: {s.advances.map((a) => `${inr(a.amount)} on ${new Date(`${a.given_on}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}`).join(', ')}
              </p>
            )}
            <div className="grid grid-cols-3 gap-2 rounded-lg bg-muted/40 px-3 py-2 text-center">
              <div><p className="text-xs text-muted-foreground">Paid</p><p className="font-semibold tabular-nums text-success">{inr(s.totals.paid)}</p></div>
              <div><p className="text-xs text-muted-foreground">Still to pay</p><p className={cn('font-semibold tabular-nums', n(s.totals.due) > 0 && 'text-draft')}>{inr(s.totals.due)}</p></div>
              <div><p className="text-xs text-muted-foreground">Advance to take back</p><p className="font-semibold tabular-nums">{inr(s.totals.advance_outstanding)}</p></div>
            </div>
          </div>
        )}
        <DialogFooter className="gap-2">
          <Button variant="outline" className="gap-1.5" disabled={!s} onClick={copy}><Copy className="size-4" /> Copy</Button>
          <Button className="gap-1.5" disabled={!s} asChild={!!s}>
            {s ? (
              <a href={`https://wa.me/?text=${encodeURIComponent(s.text)}`} target="_blank" rel="noreferrer"><Send className="size-4" /> Share on WhatsApp</a>
            ) : (
              <span><Send className="size-4" /> Share on WhatsApp</span>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
