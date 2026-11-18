import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Building2, Settings2 } from 'lucide-react'
import { BooksClosed, PeriodBar, usePeriod } from '@/components/accounts/books'
import { FlowStrip } from '@/components/accounts/money-kit'
import { pctText } from '@/components/accounts/visuals'
import { Callout, DprHeader, PageError } from '@/components/dpr-page'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast-notification'
import { useAuth } from '@/lib/AuthContext'
import { fetchProjectsBooks, mayReadProjectBooks, mayReopen, rupees, saveOverheads, short, type OverheadSettings, type ProjectRow } from '@/lib/accounts'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'

// ACC-08 / ACC-23: which site makes money: every project's billing, cost, head-office share, profit and margin in
// the period, and what it is owed and owes today, best first. A project manager sees their projects. The owner or an
// admin switches overhead sharing on (off by default). Backend: GET /accounts/projects, PUT /accounts/settings.
// UXA-07: the period as a sum (billed − cost = profit) with the projects at a loss; the table with each project's
// billing split into cost and profit as one bar, its margin, what it is owed and owes, and the total at the foot.

function Overheads({ s, projects }: { s: OverheadSettings; projects: ProjectRow[] }) {
  const toast = useToast()
  const qc = useQueryClient()
  const [basis, setBasis] = React.useState<string>(s.overhead_basis ?? 'off')
  const [office, setOffice] = React.useState<string>(s.head_office_project_id ?? 'none')
  const save = useMutation({
    mutationFn: () => saveOverheads({ overhead_basis: basis === 'off' ? null : (basis as 'cost' | 'billing'), head_office_project_id: office === 'none' ? null : office }),
    onSuccess: () => {
      toast.success(basis === 'off' ? 'Overheads stay with the head office' : 'Overheads shared over the projects')
      qc.invalidateQueries({ queryKey: ['accounts'] })
    },
    onError: (err: unknown) => toast.error('Not saved', apiErrorMessage(err)),
  })
  return (
    <div className="flex flex-col gap-3 rounded-xl border p-4">
      <p className="flex items-center gap-2 text-sm font-medium">
        <Settings2 className="size-4" /> Head-office costs in project profit
      </p>
      <p className="text-xs text-muted-foreground">
        On: rent and salaries are shared over the projects each month.
      </p>
      <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
        <div className="flex flex-col gap-1.5">
          <Label>Share them</Label>
          <Select value={basis} onValueChange={setBasis}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="off">Don't share (off)</SelectItem>
              <SelectItem value="cost">By each project's cost</SelectItem>
              <SelectItem value="billing">By each project's billing</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label>Office costs are recorded on</Label>
          <Select value={office} onValueChange={setOffice} disabled={basis === 'off'}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">No project (only costs without one)</SelectItem>
              {projects.map((p) => (
                <SelectItem key={p.project_id} value={p.project_id}>
                  {p.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button onClick={() => save.mutate()} disabled={save.isPending}>
          {save.isPending ? 'Saving…' : 'Save'}
        </Button>
      </div>
    </div>
  )
}

export default function ProjectsBooksPage() {
  usePageTitle('Projects: profit & loss')
  const { me } = useAuth()
  const periodState = usePeriod()
  const { period } = periodState
  const allowed = mayReadProjectBooks(me?.role)
  const q = useQuery({ queryKey: ['accounts', 'projects', period], queryFn: () => fetchProjectsBooks(period), enabled: allowed })
  if (!allowed) return <BooksClosed />
  if (q.isError) return <PageError message="The projects could not be loaded." onRetry={() => q.refetch()} back={{ to: '/accounts', label: 'Accounts' }} />
  const d = q.data
  const losing = (d?.projects ?? []).filter((p) => Number(p.profit) < 0)
  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader back={{ to: '/accounts', label: 'Accounts' }} crumb="Accounts" title="Projects" action={<PeriodBar state={periodState} />} />
      {!d ? (
        <Skeleton className="h-96 rounded-xl" />
      ) : (
        <>
          {(() => {
            const profit = Number(d.total.profit)
            return (
              <FlowStrip
                guide="proj.stats"
                items={[
                  { label: 'Billed', value: rupees(d.total.billed), tone: 'in', sub: `${d.projects.length} projects` },
                  { label: 'Cost', value: rupees(Number(d.total.cost) + Number(d.total.overheads)), tone: 'out', op: '−', sub: Number(d.total.overheads) ? `with ${short(d.total.overheads)} head-office share` : 'bills, wages and expenses' },
                  { label: profit < 0 ? 'Loss' : 'Profit', value: (profit < 0 ? '−' : '') + rupees(profit), tone: profit < 0 ? 'out' : 'balance', op: '=', sub: d.total.margin ? `${pctText(d.total.margin)} of billing` : undefined },
                  { label: 'Projects at a loss', value: String(losing.length), tone: losing.length ? 'out' : 'plain', sub: losing.length ? losing.map((p) => p.name).join(', ') : 'none' },
                ]}
              />
            )
          })()}
          {d.overhead_basis && (
            <Callout tone="info" icon={Building2}>
              Head-office costs{d.head_office_project ? ` (on ${d.head_office_project})` : ''} are shared over the projects by their {d.overhead_basis}, each finished month.
            </Callout>
          )}
          <section className="flex flex-col gap-2">
            <h2 className="px-1 text-base font-semibold">
              Projects, most profit first <span className="text-sm font-normal text-muted-foreground">{d.projects.length}</span>
            </h2>
            {d.projects.length === 0 ? (
              <p className="rounded-xl border border-dashed bg-card px-4 py-6 text-sm text-muted-foreground">No project has income or cost in the books in this period.</p>
            ) : (
              <div className="overflow-hidden rounded-xl border bg-card shadow-xs">
                <div className="overflow-x-auto">
                  <table data-guide="proj.list" className="w-full min-w-[820px] text-sm">
                    <thead>
                      <tr className="border-b bg-muted text-xs text-muted-foreground">
                        <th className="px-3 py-2 text-left font-medium">Project</th>
                        <th className="px-3 py-2 text-right font-medium">Billed</th>
                        <th className="px-3 py-2 text-right font-medium">Cost</th>
                        {d.overhead_basis && <th className="px-3 py-2 text-right font-medium">Head office</th>}
                        <th className="px-3 py-2 text-left font-medium">Where the billing went</th>
                        <th className="px-3 py-2 text-right font-medium">Profit</th>
                        <th className="px-3 py-2 text-right font-medium">Client owes</th>
                        <th className="px-3 py-2 text-right font-medium">You owe</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.projects.map((p) => {
                        const billed = Number(p.billed)
                        const cost = Number(p.cost) + Number(p.overheads)
                        const profit = Number(p.profit)
                        const whole = Math.max(billed, cost, 1)
                        return (
                          <tr key={p.project_id} className="border-t border-border/60 first:border-t-0 hover:bg-muted/30">
                            <td className="px-3 py-2.5">
                              <Link to={`/accounts/projects/${p.project_id}${window.location.search}`} className="font-medium hover:underline">
                                {p.name}
                              </Link>
                            </td>
                            <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums text-emerald-700 dark:text-emerald-400">{rupees(p.billed)}</td>
                            <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums text-rose-700 dark:text-rose-400">{rupees(p.cost)}</td>
                            {d.overhead_basis && <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums text-muted-foreground">{rupees(p.overheads)}</td>}
                            <td className="px-3 py-2.5">
                              <span className="flex h-2 w-40 gap-0.5 overflow-hidden rounded-full bg-muted" title={`cost ${rupees(cost)} · ${profit < 0 ? 'loss' : 'profit'} ${rupees(profit)}`}>
                                <span className="h-full rounded-l-full bg-rose-400" style={{ width: `${(Math.min(cost, billed || cost) / whole) * 100}%` }} />
                                {profit > 0 && <span className="h-full rounded-r-full bg-success" style={{ width: `${(profit / whole) * 100}%` }} />}
                                {profit < 0 && <span className="h-full rounded-r-full bg-destructive" style={{ width: `${(Math.abs(profit) / whole) * 100}%` }} />}
                              </span>
                            </td>
                            <td className="whitespace-nowrap px-3 py-2.5 text-right">
                              <span className={cn('font-semibold tabular-nums', profit < 0 ? 'text-destructive' : 'text-success')}>
                                {profit < 0 ? '−' : ''}
                                {rupees(profit)}
                              </span>
                              {p.margin !== null && <span className={cn('ml-1.5 rounded px-1 py-px text-[11px] tabular-nums', profit < 0 ? 'bg-destructive/10 text-destructive' : 'bg-success-soft text-success')}>{pctText(p.margin)}</span>}
                            </td>
                            <td className={cn('whitespace-nowrap px-3 py-2.5 text-right tabular-nums', Number(p.receivable) > 0 ? 'text-draft' : 'text-muted-foreground')}>{Number(p.receivable) ? rupees(p.receivable) : '—'}</td>
                            <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums text-muted-foreground">{Number(p.payable) ? rupees(p.payable) : '—'}</td>
                          </tr>
                        )
                      })}
                    </tbody>
                    <tfoot>
                      <tr className="border-t-[1.5px] border-foreground/25 bg-muted/30 font-semibold">
                        <td className="px-3 py-2.5">All projects</td>
                        <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums">{rupees(d.total.billed)}</td>
                        <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums">{rupees(d.total.cost)}</td>
                        {d.overhead_basis && <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums">{rupees(d.total.overheads)}</td>}
                        <td />
                        <td className={cn('whitespace-nowrap px-3 py-2.5 text-right tabular-nums', Number(d.total.profit) < 0 ? 'text-destructive' : 'text-success')}>{rupees(d.total.profit)}</td>
                        <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums">{rupees(d.total.receivable)}</td>
                        <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums">{rupees(d.total.payable)}</td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              </div>
            )}
          </section>
          {mayReopen(me?.role) && <Overheads s={d} projects={d.projects} />}
        </>
      )}
    </div>
  )
}
