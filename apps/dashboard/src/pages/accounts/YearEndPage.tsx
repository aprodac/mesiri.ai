import * as React from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarCheck2, CheckCircle2, CircleAlert, CircleDashed, Lock, LockOpen, TrendingUp } from 'lucide-react'
import { BooksClosed, BooksTabs, ExcelButton } from '@/components/accounts/books'
import { Callout, DprHeader, DprSection, PageError, StatStrip } from '@/components/dpr-page'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast-notification'
import { useAuth } from '@/lib/AuthContext'
import { closeYear, drCr, fetchYear, fetchYears, formatDay, mayReadBooks, mayReopen, reopenYear, rupees } from '@/lib/accounts'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'

// ACC-17: close a financial year (April to March) once it is over: every month closed and locked until the year is
// reopened (owner or admin, with a reason), and what it carries into the next year kept. Carry forward is Tally's way:
// income and expense ledgers start the new year at nil, the year's profit joins capital. The checklist says what is
// not done, each with where to fix it. Backend: /accounts/years.

export default function YearEndPage() {
  usePageTitle('Year end')
  const { me } = useAuth()
  const allowed = mayReadBooks(me?.role)
  const canClose = mayReopen(me?.role)
  const toast = useToast()
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const years = useQuery({ queryKey: ['accounts', 'years'], queryFn: fetchYears, enabled: allowed })
  const list = years.data?.years ?? []
  const fy = params.get('fy') ?? list.find((y) => y.over && y.status === 'open')?.financial_year ?? list[0]?.financial_year ?? ''
  const year = useQuery({ queryKey: ['accounts', 'years', fy], queryFn: () => fetchYear(fy), enabled: allowed && !!fy })
  const [ask, setAsk] = React.useState<'close' | 'reopen' | null>(null)
  const [reason, setReason] = React.useState('')
  const act = useMutation({
    mutationFn: () => (ask === 'close' ? closeYear(fy, true) : reopenYear(fy, reason.trim())),
    onSuccess: () => {
      toast.success(ask === 'close' ? `${fy} closed` : `${fy} reopened`)
      qc.invalidateQueries({ queryKey: ['accounts'] })
      setAsk(null)
      setReason('')
    },
    onError: (err: unknown) => toast.error('Not done', apiErrorMessage(err)),
  })
  if (!allowed) return <BooksClosed />
  if (years.isError || year.isError) return <PageError message="The years could not be loaded." onRetry={() => (years.isError ? years.refetch() : year.refetch())} back={{ to: '/accounts/periods', label: 'Months' }} />
  const y = year.data
  const open = y?.checklist.filter((c) => !c.ok) ?? []
  const blocking = open.filter((c) => c.blocks)
  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader
        back={{ to: '/accounts/periods', label: 'Months' }}
        crumb="Accounts"
        title="Year end"
        chip={y && <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium', y.status === 'closed' ? 'bg-muted' : 'bg-success-soft text-success')}>{y.status === 'closed' ? <Lock className="size-3" /> : <LockOpen className="size-3" />} {y.status === 'closed' ? 'Closed' : 'Open'}</span>}
        date={y ? `${formatDay(y.starts_on)} to ${formatDay(y.ends_on)}` : undefined}
        action={y && y.carried.length > 0 && <ExcelButton path={`/accounts/years/${fy}/export`} params={{}} name={`carried-forward-${fy}`} />}
      />
      <BooksTabs current="/accounts/year-end" />
      {list.length > 1 && (
        <nav aria-label="Years" className="flex flex-wrap gap-1.5">
          {list.map((x) => (
            <button key={x.financial_year} type="button" onClick={() => setParams({ fy: x.financial_year }, { replace: true })}
              className={cn('rounded-md border px-2.5 py-1 text-sm', x.financial_year === fy ? 'border-foreground font-medium' : 'text-muted-foreground')}>
              {x.financial_year} {x.status === 'closed' && <Lock className="inline size-3" />}
            </button>
          ))}
        </nav>
      )}
      {!y ? (
        <Skeleton className="h-96 rounded-xl" />
      ) : (
        <>
          <StatStrip
            stats={[
              { label: Number(y.profit) < 0 ? 'Loss of the year' : 'Profit of the year', value: rupees(y.profit), icon: TrendingUp, tone: Number(y.profit) < 0 ? 'bad' : 'good', hint: 'joins capital' },
              { label: 'Checks to do', value: String(open.length), icon: CircleAlert, tone: open.length ? 'warn' : 'good' },
              { label: 'Status', value: y.status === 'closed' ? 'Closed' : y.over ? 'Ready to close' : 'Running', icon: CalendarCheck2, hint: y.closed_at ? `by ${y.closed_by ?? 'someone'}, ${formatDay(y.closed_at)}` : undefined },
            ]}
          />
          {y.status === 'closed' && y.drift && Number(y.drift) > 0 && (
            <Callout tone="draft" icon={CircleAlert}>The closed year's balances differ from what it carried forward by {rupees(y.drift)}. Closed months never change, so tell Mesiri support.</Callout>
          )}
          {y.status === 'open' && y.reopen_reason && (
            <Callout tone="muted" icon={LockOpen}>Reopened {y.reopened_at ? formatDay(y.reopened_at) : ''}{y.reopened_by ? ` by ${y.reopened_by}` : ''}: {y.reopen_reason}</Callout>
          )}
          <DprSection icon={CheckCircle2} title="Before closing" meta={`${y.checklist.length - open.length} of ${y.checklist.length} done`}
            action={canClose && (y.status === 'open'
              ? <Button size="sm" className="gap-1.5" disabled={blocking.length > 0} onClick={() => setAsk('close')}><Lock className="size-3.5" /> Close {fy}</Button>
              : <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setAsk('reopen')}><LockOpen className="size-3.5" /> Reopen</Button>)}>
            <ul className="divide-y rounded-lg border text-sm">
              {y.checklist.map((c) => (
                <li key={c.key} className="flex items-start gap-3 px-3 py-2.5">
                  {c.ok ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" /> : c.blocks ? <Lock className="mt-0.5 size-4 shrink-0 text-muted-foreground" /> : <CircleDashed className="mt-0.5 size-4 shrink-0 text-draft" />}
                  <span className="min-w-0 flex-1">{c.words}{c.amount && Number(c.amount) ? ` (${rupees(c.amount)})` : ''}</span>
                  {!c.ok && c.to && <Link to={c.to} className="shrink-0 text-xs underline">Fix</Link>}
                </li>
              ))}
            </ul>
            {!canClose && <p className="text-xs text-muted-foreground">The owner or an admin closes the year.</p>}
          </DprSection>
          <DprSection icon={CalendarCheck2} title="Carried into the next year" meta={y.carried.length || undefined}>
            {y.carried.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nothing in the books on {formatDay(y.ends_on)}.</p>
            ) : (
              <ul className="divide-y rounded-lg border text-sm">
                {y.carried.map((r) => (
                  <li key={r.ledger_id} className="flex items-center gap-3 px-3 py-1.5">
                    <span className="min-w-0 flex-1"><span className="font-medium">{r.name}</span> <span className="text-xs text-muted-foreground">{r.group}</span></span>
                    <span className="tabular-nums">{drCr(r.balance)}</span>
                  </li>
                ))}
                {Number(y.earlier_profit) !== 0 && (
                  <li className="flex items-center gap-3 bg-muted/30 px-3 py-1.5">
                    <span className="flex-1">{Number(y.earlier_profit) < 0 ? 'Loss' : 'Profit'} of earlier years, in capital</span>
                    <span className="tabular-nums">{drCr(-Number(y.earlier_profit))}</span>
                  </li>
                )}
                <li className="flex items-center gap-3 bg-muted/30 px-3 py-1.5 font-medium">
                  <span className="flex-1">{Number(y.profit) < 0 ? 'Loss' : 'Profit'} of the year, to capital</span>
                  <span className="tabular-nums">{drCr(-Number(y.profit))}</span>
                </li>
              </ul>
            )}
          </DprSection>
        </>
      )}
      <Dialog open={!!ask} onOpenChange={(o) => !o && setAsk(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{ask === 'close' ? `Close ${fy}?` : `Reopen ${fy}?`}</DialogTitle>
            <DialogDescription>
              {ask === 'close'
                ? `Every month of ${fy} is closed and locked; a later change to a record is posted in the next year, marked.${open.filter((c) => c.key !== 'months').length ? ` ${open.filter((c) => c.key !== 'months').length} check(s) are not done: close only if the CA agrees.` : ''}`
                : 'Its months stay closed; you can then reopen a month on its own. Say why, for the CA.'}
            </DialogDescription>
          </DialogHeader>
          {ask === 'reopen' && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="y-reason">Reason</Label>
              <Input id="y-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. CA found a bill of March" maxLength={500} autoFocus />
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setAsk(null)}>Cancel</Button>
            <Button onClick={() => act.mutate()} disabled={act.isPending || (ask === 'reopen' && reason.trim().length < 3)}>{act.isPending ? 'Working…' : ask === 'close' ? 'Close the year' : 'Reopen'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
