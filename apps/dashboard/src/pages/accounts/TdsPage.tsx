import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { CalendarClock, CircleAlert, HandCoins, Landmark, Scissors, UserX } from 'lucide-react'
import { BooksClosed, BooksTabs, ExcelButton, PeriodBar, usePeriod } from '@/components/accounts/books'
import { Callout, DprHeader, DprSection, PageError, StatStrip } from '@/components/dpr-page'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { fetchTds, formatDay, mayReadBooks, rupees } from '@/lib/accounts'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'

// ACC-11: TDS. What the company deducted from subcontractors' bills (194C) and holds for the government, deposited
// or still due by the 7th; and what clients deducted from our RA bills (to match with 26AS and claim). Backend:
// GET /accounts/tds.

const STATUS = {
  deposited: { word: 'Deposited', cls: 'bg-success-soft text-success' },
  due: { word: 'Due', cls: 'bg-info-soft text-info' },
  overdue: { word: 'Late', cls: 'bg-destructive/10 text-destructive' },
} as const

export default function TdsPage() {
  usePageTitle('TDS')
  const { me } = useAuth()
  const periodState = usePeriod('fy')
  const { period } = periodState
  const allowed = mayReadBooks(me?.role)
  const q = useQuery({ queryKey: ['accounts', 'tds', period], queryFn: () => fetchTds(period), enabled: allowed })
  if (!allowed) return <BooksClosed />
  if (q.isError) return <PageError message="TDS could not be loaded." onRetry={() => q.refetch()} back={{ to: '/accounts', label: 'Accounts' }} />
  const d = q.data
  const deducted = d ? d.deducted.reduce((s, x) => s + Number(x.amount), 0) : 0
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 pb-8 sm:px-2">
      <DprHeader
        back={{ to: '/accounts', label: 'Accounts' }}
        crumb="Accounts"
        title="TDS"
        date="194C: deducted from subcontractors, and by clients"
        action={d && <ExcelButton path="/accounts/tds/export" params={period} name={`tds-${period.date_from}-to-${period.date_to}`} />}
      />
      <BooksTabs current="/accounts/tds" />
      <PeriodBar state={periodState} />
      {!d ? (
        <Skeleton className="h-96 rounded-xl" />
      ) : (
        <>
          <StatStrip
            phoneCols={2}
            stats={[
              { label: 'Deducted from subcontractors', value: rupees(deducted), icon: Scissors },
              { label: 'To deposit', value: rupees(d.to_deposit), icon: Landmark, tone: Number(d.to_deposit) > 0 ? 'warn' : 'good', hint: d.next_due ? `next due ${formatDay(d.next_due)}` : undefined },
              { label: 'Late', value: rupees(d.overdue), icon: CalendarClock, tone: Number(d.overdue) > 0 ? 'bad' : 'good', hint: Number(d.overdue) ? 'interest runs from the due date' : 'nothing late' },
              { label: 'Deducted by clients', value: rupees(d.by_clients_total), icon: HandCoins, tone: 'info', hint: 'claim it against your tax' },
            ]}
          />
          {Number(d.overdue) > 0 && (
            <Callout tone="draft" icon={CircleAlert}>
              <span className="font-medium">{rupees(d.overdue)} of TDS is past its due date.</span> Deposit it (a transfer into the TDS payable account in Finance › Money) and the month shows deposited.
            </Callout>
          )}
          {d.missing_pan.length > 0 && (
            <Callout tone="draft" icon={UserX} action={<Link to="/finance/vendors" className="text-sm underline">Suppliers</Link>}>
              No PAN (GSTIN) for {d.missing_pan.join(', ')}: the return needs it. Add their GSTIN on the supplier.
            </Callout>
          )}
          <DprSection icon={CalendarClock} title="Month by month" meta={d.months.length || undefined}>
            {d.months.length === 0 ? (
              <p className="rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground">No TDS deducted in this period. It is deducted when a subcontractor's bill is checked (Subcontract › Bills).</p>
            ) : (
              <ul className="divide-y rounded-lg border text-sm">
                {d.months.map((m) => (
                  <li key={m.month} className="flex flex-col gap-1 px-3 py-2.5 sm:flex-row sm:items-center sm:gap-4">
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2 font-medium">
                        {new Date(`${m.month}-01T00:00:00`).toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })}
                        <span className={cn('rounded-full px-2 py-0.5 text-xs font-normal', STATUS[m.status].cls)}>{STATUS[m.status].word}</span>
                      </span>
                      <span className="block text-xs text-muted-foreground tabular-nums">
                        deducted {rupees(m.deducted)} · deposited {rupees(m.deposited)} · due by {formatDay(m.due)}
                      </span>
                    </span>
                    <span className={cn('font-semibold tabular-nums', Number(m.left) ? '' : 'text-muted-foreground')}>{Number(m.left) ? `${rupees(m.left)} to deposit` : 'Nil'}</span>
                  </li>
                ))}
              </ul>
            )}
          </DprSection>
          {d.by_party.length > 0 && (
            <DprSection icon={Scissors} title="By subcontractor" meta={d.by_party.length}>
              <ul className="divide-y rounded-lg border text-sm">
                {d.by_party.map((p) => (
                  <li key={p.party} className="flex items-center gap-4 px-3 py-2">
                    <span className="min-w-0 flex-1">
                      <span className="block font-medium">{p.party}</span>
                      <span className={cn('block text-xs', p.pan ? 'text-muted-foreground' : 'text-destructive')}>
                        {p.pan ? `PAN ${p.pan}` : 'No PAN'} · {p.bills} bill{p.bills === 1 ? '' : 's'} of {rupees(p.bill_amount)}
                      </span>
                    </span>
                    <span className="font-medium tabular-nums">{rupees(p.amount)}</span>
                  </li>
                ))}
              </ul>
            </DprSection>
          )}
          <DprSection icon={HandCoins} title="Deducted by clients from our RA bills" meta={d.by_clients.length || undefined}>
            {d.by_clients.length === 0 ? (
              <p className="text-sm text-muted-foreground">No RA bill with TDS in this period.</p>
            ) : (
              <ul className="divide-y rounded-lg border text-sm">
                {d.by_clients.map((r) => (
                  <li key={r.id} className="flex items-center gap-4 px-3 py-2">
                    <span className="min-w-0 flex-1">
                      <Link to={`/billing/ra-bills/${r.id}/document`} className="font-medium hover:underline">
                        {r.ref} · {r.client ?? 'No client'}
                      </Link>
                      <span className="block text-xs text-muted-foreground">
                        {[formatDay(r.date), r.project, r.rate ? `${Number(r.rate)}% of ${rupees(r.gross)}` : null, r.pan ? `client PAN ${r.pan}` : null].filter(Boolean).join(' · ')}
                      </span>
                    </span>
                    <span className="font-medium tabular-nums">{rupees(r.amount)}</span>
                  </li>
                ))}
              </ul>
            )}
            <p className="text-xs text-muted-foreground">Match these with Form 26AS / the client's Form 16A before claiming them against the company's tax.</p>
          </DprSection>
        </>
      )}
    </div>
  )
}
