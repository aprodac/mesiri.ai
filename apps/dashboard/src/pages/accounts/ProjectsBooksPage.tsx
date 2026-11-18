import * as React from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Building2, ChevronRight, Settings2 } from 'lucide-react'
import { BooksClosed, PeriodBar, usePeriod } from '@/components/accounts/books'
import { FlowStrip } from '@/components/accounts/money-kit'
import { pctText } from '@/components/accounts/visuals'
import { DprHeader, PageError } from '@/components/dpr-page'
import { Hint } from '@/components/hint'
import { EmptyState, Legend } from '@/components/page/page-kit'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast-notification'
import { useAuth } from '@/lib/AuthContext'
import { fetchProjectsBooks, mayReadProjectBooks, mayReopen, rupees, saveOverheads, short, type OverheadSettings, type ProjectRow } from '@/lib/accounts'
import { maySeeBoq } from '@/lib/boq'
import { fetchPortfolio } from '@/lib/cost'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import { HEALTH_LOOK, HEALTH_ORDER, healthOf, realView, type Health, type RealView } from '@/lib/project-health'
import { cn } from '@/lib/utils'

// ACC-08 / ACC-23: which site makes money: every project's billing, cost, head-office share, profit and margin in
// the period, and what it is owed and owes today. A project manager sees their projects. The owner or an admin switches
// overhead sharing on (off by default). Backend: GET /accounts/projects, PUT /accounts/settings.
// UXA-07: the period as a sum (billed − cost = profit); each project's billing split into cost and profit.
// UX-57 (asked 18 Nov 2026): the books' profit is never read alone. Cost splits into direct (site) and indirect; each
// project also shows its real margin so far (Cost control's full cost, with deliveries and attendance not yet billed)
// and where it will finish against its BOQ budget (lib/project-health.ts); rows are coloured by health, worst first;
// a phone gets one card per project; the head-office setting sits behind a gear; a project picked in the top bar is
// lit up. No new backend but `direct` on the list.

type Row = ProjectRow & { real: RealView | null; health: Health; why: string }

function Overheads({ s, projects, open, onOpenChange }: { s: OverheadSettings; projects: ProjectRow[]; open: boolean; onOpenChange: (o: boolean) => void }) {
  const toast = useToast()
  const qc = useQueryClient()
  const [basis, setBasis] = React.useState<string>(s.overhead_basis ?? 'off')
  const [office, setOffice] = React.useState<string>(s.head_office_project_id ?? 'none')
  const save = useMutation({
    mutationFn: () => saveOverheads({ overhead_basis: basis === 'off' ? null : (basis as 'cost' | 'billing'), head_office_project_id: office === 'none' ? null : office }),
    onSuccess: () => {
      toast.success(basis === 'off' ? 'Overheads stay with the head office' : 'Overheads shared over the projects')
      qc.invalidateQueries({ queryKey: ['accounts'] })
      onOpenChange(false)
    },
    onError: (err: unknown) => toast.error('Not saved', apiErrorMessage(err)),
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Settings2 className="size-4" /> Head-office costs
            <Hint title="Head-office costs in project profit" text="On: office rent and salaries are shared over the projects each finished month, by each project's cost or billing. Off: they stay with the head office and project profit is site profit." />
          </DialogTitle>
          <DialogDescription className="sr-only">Share head-office costs over the projects.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
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
          <Button className="justify-self-end" onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? 'Saving…' : 'Save'}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function HealthPill({ health, why }: { health: Health; why: string }) {
  const look = HEALTH_LOOK[health]
  return (
    <span className={cn('inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap', look.pill)} title={why}>
      <span className={cn('size-1.5 rounded-full', look.dot)} aria-hidden /> {health === 'good' || health === 'unknown' ? look.label : why}
    </span>
  )
}

/** A margin as a coloured chip: red below 0, amber under 10%, green from 10%. */
function MarginChip({ v, title }: { v: number | null; title?: string }) {
  if (v === null) return <span className="text-xs text-muted-foreground">—</span>
  const cls = v < 0 ? 'bg-destructive/10 text-destructive' : v < 10 ? 'bg-draft-soft text-draft' : 'bg-success-soft text-success'
  return <span className={cn('rounded px-1.5 py-px text-[11px] font-semibold tabular-nums', cls)} title={title}>{pctText(v)}</span>
}

/** Budget, forecast and work done as one bar: grey to the budget, red past it; a tick where the work done is. */
function ForecastBar({ real }: { real: RealView }) {
  if (real.budget === null || real.forecast === null || !real.budget) return <span className="text-xs text-muted-foreground">—</span>
  const whole = Math.max(real.budget, real.forecast)
  const over = Math.max(0, real.forecast - real.budget)
  return (
    <span className="flex min-w-36 flex-col gap-1" title={`Budget ${rupees(real.budget)} · forecast ${rupees(real.forecast)}${real.done !== null ? ` · ${real.done}% built` : ''}`}>
      <span className="relative flex h-2 overflow-hidden rounded-full bg-muted">
        <span className="bg-foreground/25" style={{ width: `${(Math.min(real.forecast, real.budget) / whole) * 100}%` }} />
        {over > 0 && <span className="bg-destructive" style={{ width: `${(over / whole) * 100}%` }} />}
        {real.done !== null && <span className="absolute inset-y-0 w-0.5 bg-foreground" style={{ left: `${Math.min(100, (real.done / 100) * (real.budget / whole) * 100)}%` }} />}
      </span>
      <span className={cn('text-[11px] tabular-nums', over > 0 ? 'font-semibold text-destructive' : 'text-success')}>
        {over > 0 ? `${short(over)} over` : 'Within budget'}
        {real.done !== null && <span className="font-normal text-muted-foreground"> · {real.done}% built</span>}
      </span>
    </span>
  )
}

export default function ProjectsBooksPage() {
  usePageTitle('Projects: profit & loss')
  const { me } = useAuth()
  const [params] = useSearchParams()
  const picked = params.get('project')
  const periodState = usePeriod()
  const { period } = periodState
  const allowed = mayReadProjectBooks(me?.role)
  const [gear, setGear] = React.useState(false)
  const q = useQuery({ queryKey: ['accounts', 'projects', period], queryFn: () => fetchProjectsBooks(period), enabled: allowed })
  // Billed to date for the real margin, and Cost control's full cost and forecast (when this role may read them).
  const toDate = useQuery({ queryKey: ['accounts', 'projects', 'to-date'], queryFn: () => fetchProjectsBooks({ date_from: '2000-01-01', date_to: period.date_to }), enabled: allowed })
  const port = useQuery({ queryKey: ['cost', 'portfolio'], queryFn: fetchPortfolio, enabled: allowed && maySeeBoq(me?.role), retry: false })
  const pickedRef = React.useRef<HTMLElement | null>(null)
  React.useEffect(() => {
    if (picked && q.data) window.setTimeout(() => pickedRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 100)
  }, [picked, q.data])

  if (!allowed) return <BooksClosed />
  if (q.isError) return <PageError message="The projects could not be loaded." onRetry={() => q.refetch()} back={{ to: '/accounts', label: 'Accounts' }} />
  const d = q.data
  const billedToDate = new Map((toDate.data?.projects ?? []).map((p) => [p.project_id, Number(p.billed)]))
  const byPort = new Map((port.data?.projects ?? []).map((p) => [p.project_id, p]))
  const rows: Row[] = (d?.projects ?? [])
    .map((p) => {
      const real = realView(billedToDate.get(p.project_id) ?? Number(p.billed), byPort.get(p.project_id))
      return { ...p, real, ...healthOf(real, Number(p.profit)) }
    })
    .sort((a, b) => HEALTH_ORDER[a.health] - HEALTH_ORDER[b.health] || Number(b.profit) - Number(a.profit))
  const hasReal = rows.some((r) => r.real)
  const direct = Number(d?.total.direct ?? d?.total.cost ?? 0)
  const indirect = Number(d?.total.cost ?? 0) - direct + Number(d?.total.overheads ?? 0)
  const profit = Number(d?.total.profit ?? 0)
  const atRisk = rows.filter((r) => r.health === 'bad').length
  const href = (id: string) => `/accounts/projects/${id}${window.location.search}`

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader
        back={{ to: '/accounts', label: 'Accounts' }}
        crumb="Accounts"
        title="Projects"
        action={
          <div className="flex min-w-0 max-w-full flex-wrap items-center gap-2">
            <PeriodBar state={periodState} />
            {d && mayReopen(me?.role) && (
              <Button variant="outline" size="sm" className="h-8 gap-1.5 bg-card" onClick={() => setGear(true)} title="Head-office costs in project profit">
                <Settings2 className="size-3.5" /> <span className="hidden sm:inline">Head office</span>
              </Button>
            )}
          </div>
        }
      />
      {!d ? (
        <Skeleton className="h-96 rounded-xl" />
      ) : (
        <>
          <FlowStrip
            guide="proj.stats"
            items={[
              { label: 'Billed', value: rupees(d.total.billed), tone: 'in', sub: `${d.projects.length} projects` },
              { label: 'Direct cost', value: rupees(direct), tone: 'out', op: '−', sub: 'site: materials, labour, subcontract' },
              { label: 'Indirect cost', value: rupees(indirect), tone: indirect ? 'out' : 'plain', op: '−', sub: Number(d.total.overheads) ? `with ${short(d.total.overheads)} head-office share` : 'office costs on the projects' },
              { label: profit < 0 ? 'Loss (books)' : 'Profit (books)', value: (profit < 0 ? '−' : '') + rupees(profit), tone: profit < 0 ? 'out' : 'balance', op: '=', sub: d.total.margin ? `${pctText(d.total.margin)} of billing` : undefined },
            ]}
          />
          {hasReal && atRisk > 0 && (
            <div className="flex flex-wrap items-center gap-2 rounded-xl border border-destructive/25 bg-destructive/5 px-3 py-2 text-sm">
              <span className="font-semibold text-destructive">{atRisk} at risk</span>
              {rows.filter((r) => r.health === 'bad').map((r) => (
                <Link key={r.project_id} to={href(r.project_id)} className="inline-flex items-center gap-1 rounded-full bg-card px-2 py-0.5 text-xs font-medium hover:underline">
                  {r.name} · {r.why} <ChevronRight className="size-3" aria-hidden />
                </Link>
              ))}
              <Hint title="At risk" text="Real figures come from Cost control: the full cost so far, with materials delivered and attendance not yet billed, and the forecast at completion against the BOQ budget. The books' profit leaves those out until the bills come in." />
            </div>
          )}
          {d.overhead_basis && (
            <p className="flex items-center gap-1.5 px-1 text-xs text-muted-foreground">
              <Building2 className="size-3.5" aria-hidden /> Head-office costs shared by {d.overhead_basis}{d.head_office_project ? ` (from ${d.head_office_project})` : ''}
            </p>
          )}

          <section className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-1">
              <h2 className="text-base font-semibold">
                Projects <span className="text-sm font-normal text-muted-foreground">{rows.length}</span>
              </h2>
              {hasReal && (
                <Legend
                  className="ml-auto"
                  items={[
                    { tone: 'bad', label: 'At risk' },
                    { tone: 'attention', label: 'Watch' },
                    { tone: 'good', label: 'Healthy' },
                  ]}
                />
              )}
            </div>
            {rows.length === 0 ? (
              <EmptyState icon={Building2} title="No project has income or cost in this period" className="bg-card" />
            ) : (
              <>
                {/* Laptop: one table, the books for the period and the real picture to date side by side. */}
                <div className="hidden overflow-hidden rounded-xl border bg-card shadow-xs md:block">
                  <div className="overflow-x-auto">
                    <table data-guide="proj.list" className="w-full min-w-[980px] text-sm">
                      <thead>
                        <tr className="bg-muted text-[11px] text-muted-foreground">
                          <th className="px-3 pt-2 text-left font-medium" />
                          <th colSpan={4} className="border-l px-3 pt-2 text-left font-semibold">
                            Books · this period
                          </th>
                          {hasReal && (
                            <th colSpan={2} className="border-l px-3 pt-2 text-left font-semibold">
                              <span className="inline-flex items-center gap-1">Real · to date <Hint title="Real, to date" text="Billed so far against Cost control's full cost so far (with deliveries and attendance not yet billed), and where the job finishes against its BOQ budget. The tick on the bar is the work done." /></span>
                            </th>
                          )}
                          <th colSpan={2} className="border-l px-3 pt-2 text-left font-semibold">Owed today</th>
                        </tr>
                        <tr className="border-b bg-muted text-xs text-muted-foreground">
                          <th className="px-3 py-2 text-left font-medium">Project</th>
                          <th className="border-l px-3 py-2 text-right font-medium">Billed</th>
                          <th className="px-3 py-2 text-right font-medium">Direct</th>
                          <th className="px-3 py-2 text-right font-medium">Indirect</th>
                          <th className="px-3 py-2 text-right font-medium">Profit</th>
                          {hasReal && <th className="border-l px-3 py-2 text-right font-medium">Margin</th>}
                          {hasReal && <th className="px-3 py-2 text-left font-medium">Finish vs budget</th>}
                          <th className="border-l px-3 py-2 text-right font-medium">Client owes</th>
                          <th className="px-3 py-2 text-right font-medium">You owe</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((p) => {
                          const pdirect = Number(p.direct ?? p.cost)
                          const pindirect = Number(p.cost) - pdirect + Number(p.overheads)
                          const pprofit = Number(p.profit)
                          const look = HEALTH_LOOK[p.health]
                          const isPicked = picked === p.project_id
                          return (
                            <tr
                              key={p.project_id}
                              ref={isPicked ? (el) => { pickedRef.current = el } : undefined}
                              className={cn('group relative border-t border-border/60 first:border-t-0 hover:bg-muted/30', isPicked && 'bg-primary/10')}
                            >
                              <td className={cn("relative px-3 py-2.5 before:absolute before:inset-y-0 before:left-0 before:w-1 before:content-['']", hasReal ? look.edge : '')}>
                                <Link to={href(p.project_id)} className="font-medium after:absolute after:inset-0 hover:underline">
                                  {p.name}
                                </Link>
                                {hasReal && <div className="mt-0.5"><HealthPill health={p.health} why={p.why} /></div>}
                              </td>
                              <td className="border-l px-3 py-2.5 text-right whitespace-nowrap tabular-nums">{rupees(p.billed)}</td>
                              <td className="px-3 py-2.5 text-right whitespace-nowrap tabular-nums text-muted-foreground">{rupees(pdirect)}</td>
                              <td className="px-3 py-2.5 text-right whitespace-nowrap tabular-nums text-muted-foreground" title={Number(p.overheads) ? `with ${rupees(p.overheads)} head-office share` : undefined}>{pindirect ? rupees(pindirect) : '—'}</td>
                              <td className="px-3 py-2.5 text-right whitespace-nowrap">
                                <span className={cn('font-semibold tabular-nums', pprofit < 0 ? 'text-destructive' : 'text-foreground')}>
                                  {pprofit < 0 ? '−' : ''}
                                  {rupees(pprofit)}
                                </span>
                                <span className="ml-1.5"><MarginChip v={p.margin === null ? null : Number(p.margin)} title="Books margin, this period" /></span>
                              </td>
                              {hasReal && (
                                <td className="border-l px-3 py-2.5 text-right">
                                  {p.real ? <MarginChip v={p.real.margin} title={`Billed ${rupees(p.real.billed)} · full cost ${rupees(p.real.spent)}`} /> : <span className="text-xs text-muted-foreground">—</span>}
                                </td>
                              )}
                              {hasReal && <td className="px-3 py-2.5">{p.real ? <ForecastBar real={p.real} /> : <span className="text-xs text-muted-foreground">—</span>}</td>}
                              <td className={cn('border-l px-3 py-2.5 text-right whitespace-nowrap tabular-nums', Number(p.receivable) > 0 ? 'font-semibold text-draft' : 'text-muted-foreground')}>{Number(p.receivable) ? rupees(p.receivable) : '—'}</td>
                              <td className="px-3 py-2.5 text-right whitespace-nowrap tabular-nums text-muted-foreground">{Number(p.payable) ? rupees(p.payable) : '—'}</td>
                            </tr>
                          )
                        })}
                      </tbody>
                      <tfoot>
                        <tr className="border-t-[1.5px] border-foreground/25 bg-muted/30 font-semibold">
                          <td className="px-3 py-2.5">All projects</td>
                          <td className="border-l px-3 py-2.5 text-right whitespace-nowrap tabular-nums">{rupees(d.total.billed)}</td>
                          <td className="px-3 py-2.5 text-right whitespace-nowrap tabular-nums">{rupees(direct)}</td>
                          <td className="px-3 py-2.5 text-right whitespace-nowrap tabular-nums">{indirect ? rupees(indirect) : '—'}</td>
                          <td className={cn('px-3 py-2.5 text-right whitespace-nowrap tabular-nums', profit < 0 ? 'text-destructive' : 'text-foreground')}>{rupees(profit)}</td>
                          {hasReal && <td className="border-l" />}
                          {hasReal && <td />}
                          <td className="border-l px-3 py-2.5 text-right whitespace-nowrap tabular-nums">{rupees(d.total.receivable)}</td>
                          <td className="px-3 py-2.5 text-right whitespace-nowrap tabular-nums">{rupees(d.total.payable)}</td>
                        </tr>
                      </tfoot>
                    </table>
                  </div>
                </div>

                {/* Phone: one card per project. */}
                <ul className="flex flex-col gap-2 md:hidden">
                  {rows.map((p) => {
                    const pprofit = Number(p.profit)
                    const isPicked = picked === p.project_id
                    return (
                      <li key={p.project_id} ref={isPicked ? (el) => { if (window.innerWidth < 768) pickedRef.current = el } : undefined}>
                        <Link
                          to={href(p.project_id)}
                          className={cn("relative flex flex-col gap-2 overflow-hidden rounded-xl border bg-card p-3 pl-4 before:absolute before:inset-y-0 before:left-0 before:w-1 before:content-['']", hasReal ? HEALTH_LOOK[p.health].edge : '', isPicked && 'ring-2 ring-primary')}
                        >
                          <span className="flex items-start justify-between gap-2">
                            <span className="font-semibold">{p.name}</span>
                            {hasReal && <HealthPill health={p.health} why={p.why} />}
                          </span>
                          <span className="grid grid-cols-3 gap-2 text-xs">
                            <span className="flex flex-col"><span className="text-muted-foreground">Billed</span><span className="font-semibold tabular-nums">{short(p.billed)}</span></span>
                            <span className="flex flex-col"><span className="text-muted-foreground">Profit (books)</span><span className={cn('font-semibold tabular-nums', pprofit < 0 && 'text-destructive')}>{pprofit < 0 ? '−' : ''}{short(Math.abs(pprofit))}</span></span>
                            <span className="flex flex-col"><span className="text-muted-foreground">Client owes</span><span className={cn('font-semibold tabular-nums', Number(p.receivable) > 0 && 'text-draft')}>{Number(p.receivable) ? short(p.receivable) : '—'}</span></span>
                          </span>
                          {p.real && (
                            <span className="flex items-center gap-2 border-t pt-2 text-xs">
                              <span className="text-muted-foreground">Real margin</span> <MarginChip v={p.real.margin} />
                              <span className="ml-auto"><ForecastBar real={p.real} /></span>
                            </span>
                          )}
                        </Link>
                      </li>
                    )
                  })}
                </ul>
              </>
            )}
          </section>
          <Link to="/cost" className="inline-flex w-fit items-center gap-1 px-1 text-sm font-medium hover:underline">
            Cost control <ArrowRight className="size-3.5" aria-hidden />
          </Link>
          {mayReopen(me?.role) && <Overheads s={d} projects={d.projects} open={gear} onOpenChange={setGear} />}
        </>
      )}
    </div>
  )
}
