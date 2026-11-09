import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarCheck2, History, Lock, LockOpen } from 'lucide-react'
import { BooksClosed, BooksTabs } from '@/components/accounts/books'
import { Callout, DprHeader, DprSection, PageError, StatStrip } from '@/components/dpr-page'
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
  const lastClosed = d?.months.find((m) => m.status === 'closed')

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 pb-8 sm:px-2">
      <DprHeader back={{ to: '/accounts/trial-balance', label: 'Trial balance' }} crumb="Accounts" title="Months" date={d ? `Year ${d.financial_year}` : undefined} />
      <BooksTabs current="/accounts/periods" />
      {!d ? (
        <Skeleton className="h-72 rounded-xl" />
      ) : (
        <>
          <StatStrip
            stats={[
              { label: 'Closed months', value: String(closedCount), icon: Lock },
              { label: 'Last closed', value: lastClosed ? monthName(lastClosed) : 'None yet', icon: CalendarCheck2 },
              { label: 'Changed after close', value: String(late), icon: History, tone: late ? 'warn' : 'default' },
            ]}
          />
          <Callout tone="muted" icon={Lock}>
            Close a month once the CA has checked it: its books stay as they are. If a bill of that month is changed later, nothing on site is stopped; the difference is posted on the first open day and marked "changed after close", so you see it.
          </Callout>
          {[...years.entries()].map(([fy, list]) => (
            <DprSection key={fy} icon={CalendarCheck2} title={`Year ${fy}`} meta={`April to March`}>
              <ul className="divide-y rounded-lg border">
                {list.map((m) => (
                  <li key={m.id} className={cn('flex flex-col gap-2 px-4 py-3 text-sm sm:flex-row sm:items-center sm:gap-4', m.is_current && 'bg-muted/30')}>
                    <div className="min-w-0 flex-1">
                      <p className="flex flex-wrap items-center gap-2 font-medium">
                        {monthName(m)}
                        {m.is_current && <span className="rounded-full bg-info-soft px-2 py-0.5 text-xs font-normal text-info">This month</span>}
                        <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-normal', m.status === 'closed' ? 'bg-muted text-foreground' : 'bg-success-soft text-success')}>
                          {m.status === 'closed' ? <Lock className="size-3" /> : <LockOpen className="size-3" />}
                          {m.status === 'closed' ? 'Closed' : 'Open'}
                        </span>
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {[
                          `${m.entries} voucher${Number(m.entries) === 1 ? '' : 's'}`,
                          m.status === 'closed' && m.closed_at ? `closed ${formatDay(m.closed_at)}${m.closed_by ? ` by ${m.closed_by}` : ''}` : null,
                          m.status === 'open' && m.reopened_at ? `reopened ${formatDay(m.reopened_at)}${m.reopened_by ? ` by ${m.reopened_by}` : ''}: ${m.reopen_reason}` : null,
                        ]
                          .filter(Boolean)
                          .join(' · ')}
                      </p>
                      {Number(m.changed_after_close) > 0 && (
                        <Link to={`/accounts/day-book?late=1&range=custom&from=${m.starts_on}&to=${m.ends_on}`} className="mt-1 inline-flex items-center gap-1 text-xs text-draft underline">
                          <History className="size-3" /> {m.changed_after_close} change{Number(m.changed_after_close) === 1 ? '' : 's'} to closed months posted here
                        </Link>
                      )}
                    </div>
                    <div className="flex gap-2">
                      <Button asChild size="sm" variant="ghost">
                        <Link to={`/accounts/trial-balance?range=custom&from=${m.starts_on}&to=${m.ends_on}`}>Trial balance</Link>
                      </Button>
                      {m.status === 'open' ? (
                        <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setAsk({ month: m, action: 'close' })}>
                          <Lock className="size-3.5" /> Close
                        </Button>
                      ) : canReopen ? (
                        <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setAsk({ month: m, action: 'reopen' })}>
                          <LockOpen className="size-3.5" /> Reopen
                        </Button>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ul>
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
