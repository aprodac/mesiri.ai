import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarCheck2, History, Lock, LockOpen } from 'lucide-react'
import { BooksClosed } from '@/components/accounts/books'
import { FlowStrip } from '@/components/accounts/money-kit'
import { YearStrip } from '@/components/accounts/visuals'
import { DprHeader, DprSection, PageError } from '@/components/dpr-page'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast-notification'
import { useAuth } from '@/lib/AuthContext'
import { closeMonth, fetchMonths, formatDay, mayReadBooks, mayReopen, reopenMonth, type Month } from '@/lib/accounts'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'

// ACC-02 (D-ACC2, D-ACC6): the months of each financial year, open or closed. Closing a month keeps its books as
// they are: a record changed later is posted as the difference on the first open day, marked, and listed here. Nothing
// on site is ever blocked. Reopening is the owner's or an admin's, with a reason. Backend: /accounts/periods.
// UXA-07: the year's months as one table per year (status pill, vouchers, who closed or reopened it and why, the
// changes posted after close in amber, Trial balance / Close / Reopen), the year strip on white.

const monthName = (m: Month) => new Date(`${m.starts_on}T00:00:00`).toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })

export default function PeriodsPage() {
  usePageTitle('Months')
  const { me } = useAuth()
  const toast = useToast()
  const qc = useQueryClient()
  const allowed = mayReadBooks(me?.role)
  const canReopen = mayReopen(me?.role)
  const months = useQuery({ queryKey: ['accounts', 'periods'], queryFn: fetchMonths, enabled: allowed })
  const [ask, setAsk] = React.useState<{ month: Month; action: 'close' | 'reopen' } | null>(null)
  const [reason, setReason] = React.useState('')
  const act = useMutation({
    mutationFn: () => (ask!.action === 'close' ? closeMonth(ask!.month.month) : reopenMonth(ask!.month.month, reason.trim())),
    onSuccess: () => {
      toast.success(ask!.action === 'close' ? `${monthName(ask!.month)} closed` : `${monthName(ask!.month)} reopened`)
      qc.invalidateQueries({ queryKey: ['accounts'] })
      setAsk(null)
      setReason('')
    },
    onError: (err: unknown) => toast.error('Not done', apiErrorMessage(err)),
  })

  if (!allowed) return <BooksClosed />
  if (months.isError) return <PageError message="The months could not be loaded." onRetry={() => months.refetch()} back={{ to: '/accounts/trial-balance', label: 'Trial balance' }} />
  const d = months.data
  const years = new Map<string, Month[]>()
  for (const m of d?.months ?? []) years.set(m.financial_year, [...(years.get(m.financial_year) ?? []), m])
  const closedCount = d?.months.filter((m) => m.status === 'closed').length ?? 0
  const late = d?.months.reduce((n, m) => n + Number(m.changed_after_close), 0) ?? 0
  // The latest closed month (the list runs April first)
  const lastClosed = [...(d?.months ?? [])].reverse().find((m) => m.status === 'closed')

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader back={{ to: '/accounts/trial-balance', label: 'Trial balance' }} crumb="Accounts" title="Months" date={d ? `Year ${d.financial_year}` : undefined} />
      {!d ? (
        <Skeleton className="h-72 rounded-xl" />
      ) : (
        <>
          <FlowStrip
            guide="periods.stats"
            items={[
              { label: 'Closed months', value: String(closedCount), tone: 'balance', sub: `of ${d.months.length} this year` },
              { label: 'Last closed', value: lastClosed ? monthName(lastClosed) : 'None yet', tone: 'plain', sub: lastClosed?.closed_at ? `on ${formatDay(lastClosed.closed_at)}` : 'close a month once the CA has checked it' },
              { label: 'Changed after close', value: String(late), tone: late ? 'dr' : 'plain', sub: late ? 'posted on the first open day, marked' : 'nothing changed' },
            ]}
          />
          <div className="rounded-xl border bg-card px-3 py-3 shadow-xs">
            <p className="mb-2 text-xs text-muted-foreground">
              Year {d.financial_year}: closed months locked, open ones with their vouchers, this month ringed.
            </p>
            <YearStrip fyStart={Number(d.financial_year.slice(0, 4))} months={d.months.map((m) => ({ month: m.month, status: m.status, entries: Number(m.entries) }))} today={d.today} />
          </div>
          {[...years.entries()].map(([fy, list]) => (
            <DprSection key={fy} icon={CalendarCheck2} title={`Year ${fy}`} meta={`April to March`}>
              <div data-guide="periods.months" className="overflow-x-auto rounded-xl border bg-card shadow-xs">
                <table className="w-full min-w-[720px] text-sm">
                  <thead>
                    <tr className="border-b bg-muted text-xs text-muted-foreground">
                      <th className="px-3 py-2 text-left font-medium">Month</th>
                      <th className="px-3 py-2 text-left font-medium">Status</th>
                      <th className="px-3 py-2 text-right font-medium">Vouchers</th>
                      <th className="px-3 py-2 text-left font-medium">Closed or reopened</th>
                      <th className="px-3 py-2 text-left font-medium">After close</th>
                      <th className="px-3 py-2" />
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {list.map((m) => (
                      <tr key={m.id} className={cn(m.is_current && 'bg-info-soft/30')}>
                        <td className={cn('px-3 py-2.5 font-medium', m.is_current && 'border-l-4 border-l-info')}>
                          {monthName(m)}
                          {m.is_current && <span className="ml-2 rounded-full bg-info-soft px-2 py-0.5 text-[11px] font-normal text-info">This month</span>}
                        </td>
                        <td className="px-3 py-2.5">
                          <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs', m.status === 'closed' ? 'bg-muted text-foreground' : 'bg-success-soft text-success')}>
                            {m.status === 'closed' ? <Lock className="size-3" /> : <LockOpen className="size-3" />}
                            {m.status === 'closed' ? 'Closed' : 'Open'}
                          </span>
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-muted-foreground">{m.entries}</td>
                        <td className="px-3 py-2.5 text-xs text-muted-foreground">
                          {m.status === 'closed' && m.closed_at
                            ? `Closed ${formatDay(m.closed_at)}${m.closed_by ? ` by ${m.closed_by}` : ''}`
                            : m.status === 'open' && m.reopened_at
                              ? `Reopened ${formatDay(m.reopened_at)}${m.reopened_by ? ` by ${m.reopened_by}` : ''}: ${m.reopen_reason}`
                              : '—'}
                        </td>
                        <td className="px-3 py-2.5">
                          {Number(m.changed_after_close) > 0 ? (
                            <Link to={`/accounts/day-book?late=1&range=custom&from=${m.starts_on}&to=${m.ends_on}`} className="inline-flex items-center gap-1 rounded-full bg-draft-soft px-2 py-0.5 text-xs font-medium text-draft hover:underline">
                              <History className="size-3" /> {m.changed_after_close}
                            </Link>
                          ) : (
                            <span className="text-xs text-muted-foreground">—</span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-right">
                          <span className="inline-flex gap-1.5">
                            <Button asChild size="sm" variant="ghost" className="h-7 px-2 text-xs">
                              <Link to={`/accounts/trial-balance?range=custom&from=${m.starts_on}&to=${m.ends_on}`}>Trial balance</Link>
                            </Button>
                            {m.status === 'open' ? (
                              <Button data-guide="periods.close" size="sm" variant="outline" className="h-7 gap-1 px-2 text-xs" onClick={() => setAsk({ month: m, action: 'close' })}>
                                <Lock className="size-3.5" /> Close
                              </Button>
                            ) : canReopen ? (
                              <Button size="sm" variant="outline" className="h-7 gap-1 px-2 text-xs" onClick={() => setAsk({ month: m, action: 'reopen' })}>
                                <LockOpen className="size-3.5" /> Reopen
                              </Button>
                            ) : null}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </DprSection>
          ))}
        </>
      )}
      <Dialog open={!!ask} onOpenChange={(o) => !o && setAsk(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{ask ? `${ask.action === 'close' ? 'Close' : 'Reopen'} ${monthName(ask.month)}?` : ''}</DialogTitle>
            <DialogDescription>
              {ask?.action === 'close'
                ? `Everything recorded so far is posted first. Its ${ask.month.entries} vouchers then stay as they are; a later change to one of its records is posted on the first open day, marked.`
                : 'Its vouchers will change again when their records change. Say why, so the CA can see it.'}
            </DialogDescription>
          </DialogHeader>
          {ask?.action === 'reopen' && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="reopen-reason">Reason</Label>
              <Input id="reopen-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. supplier bill for October came late" autoFocus maxLength={500} />
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setAsk(null)}>
              Cancel
            </Button>
            <Button onClick={() => act.mutate()} disabled={act.isPending || (ask?.action === 'reopen' && reason.trim().length < 3)}>
              {act.isPending ? 'Working…' : ask?.action === 'close' ? 'Close the month' : 'Reopen'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
