import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Building2, Settings2, TrendingUp } from 'lucide-react'
import { BooksClosed, BooksTabs, PeriodBar, usePeriod } from '@/components/accounts/books'
import { ShareBar, pctText } from '@/components/accounts/visuals'
import { Callout, DprHeader, DprSection, PageError, StatStrip } from '@/components/dpr-page'
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
        Off: office rent and salaries stay with the head office. On: each finished month, they are shared over the projects, so each project's profit is after its share (company profit does not change).
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
  const top = Math.max(0, ...(d?.projects ?? []).map((p) => Math.abs(Number(p.profit))))
  const losing = (d?.projects ?? []).filter((p) => Number(p.profit) < 0)
  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader back={{ to: '/accounts', label: 'Accounts' }} crumb="Accounts" title="Projects" date="Which site makes money" />
      <BooksTabs current="/accounts/projects" />
      <PeriodBar state={periodState} />
      {!d ? (
        <Skeleton className="h-96 rounded-xl" />
      ) : (
        <>
          <StatStrip
            phoneCols={2}
            stats={[
              { label: 'Billed', value: rupees(d.total.billed) },
              { label: 'Cost', value: rupees(Number(d.total.cost) + Number(d.total.overheads)) },
              { label: Number(d.total.profit) < 0 ? 'Loss' : 'Profit', value: rupees(d.total.profit), icon: TrendingUp, tone: Number(d.total.profit) < 0 ? 'bad' : 'good', hint: d.total.margin ? `${pctText(d.total.margin)} of billing` : undefined },
              { label: 'Projects at a loss', value: String(losing.length), tone: losing.length ? 'bad' : 'good' },
            ]}
          />
          {d.overhead_basis && (
            <Callout tone="info" icon={Building2}>
              Head-office costs{d.head_office_project ? ` (on ${d.head_office_project})` : ''} are shared over the projects by their {d.overhead_basis}, each finished month.
            </Callout>
          )}
          <DprSection icon={Building2} title="Projects, most profit first" meta={d.projects.length || undefined}>
            {d.projects.length === 0 ? (
              <p className="rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground">No project has income or cost in the books in this period.</p>
            ) : (
              <div className="overflow-x-auto rounded-lg border">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b bg-muted/40 text-xs text-muted-foreground">
                      <th className="px-3 py-2 text-left font-medium">Project</th>
                      <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">Billed</th>
                      <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">Cost</th>
                      {d.overhead_basis && <th className="hidden px-3 py-2 text-right font-medium md:table-cell">Head office</th>}
                      <th className="px-3 py-2 text-right font-medium">Profit</th>
                      <th className="hidden px-3 py-2 text-right font-medium lg:table-cell">Client owes</th>
                      <th className="hidden px-3 py-2 text-right font-medium lg:table-cell">We owe</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {d.projects.map((p) => (
                      <tr key={p.project_id} className="hover:bg-muted/40">
                        <td className="px-3 py-2">
                          <Link to={`/accounts/projects/${p.project_id}${window.location.search}`} className="font-medium hover:underline">
                            {p.name}
                          </Link>
                          <span className="block text-xs text-muted-foreground tabular-nums sm:hidden">
                            billed {short(p.billed)} · cost {short(Number(p.cost) + Number(p.overheads))}
                          </span>
                        </td>
                        <td className="hidden px-3 py-2 text-right tabular-nums sm:table-cell">{rupees(p.billed)}</td>
                        <td className="hidden px-3 py-2 text-right tabular-nums sm:table-cell">{rupees(p.cost)}</td>
                        {d.overhead_basis && <td className="hidden px-3 py-2 text-right tabular-nums text-muted-foreground md:table-cell">{rupees(p.overheads)}</td>}
                        <td className="px-3 py-2 text-right">
                          <span className={cn('font-semibold tabular-nums', Number(p.profit) < 0 ? 'text-destructive' : 'text-success')}>
                            {Number(p.profit) < 0 ? '−' : ''}
                            {rupees(p.profit)}
                          </span>
                          {p.margin !== null && <span className="ml-1.5 text-xs text-muted-foreground">{pctText(p.margin)}</span>}
                          <ShareBar value={Number(p.profit)} max={top} className="ml-auto mt-1 w-24" />
                        </td>
                        <td className="hidden px-3 py-2 text-right tabular-nums lg:table-cell">{Number(p.receivable) ? rupees(p.receivable) : '—'}</td>
                        <td className="hidden px-3 py-2 text-right tabular-nums lg:table-cell">{Number(p.payable) ? rupees(p.payable) : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="text-xs text-muted-foreground">Billed: RA bills sent, before GST. Cost: every bill and expense booked to the project. Tap a project for its P&L, position and budget.</p>
          </DprSection>
          {mayReopen(me?.role) && <Overheads s={d} projects={d.projects} />}
        </>
      )}
    </div>
  )
}
