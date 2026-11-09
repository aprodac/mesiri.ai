import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { BadgeIndianRupee, Building2, Receipt, TrendingUp } from 'lucide-react'
import { BooksClosed, BooksTabs, PeriodBar, usePeriod } from '@/components/accounts/books'
import { PlStatement } from '@/components/accounts/pl-statement'
import { pctText } from '@/components/accounts/visuals'
import { Callout, DprHeader, DprSection, PageError, Segmented, StatStrip } from '@/components/dpr-page'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { useScope } from '@/lib/ScopeContext'
import { fetchPl, formatDay, mayReadBooks, rupees, scopeParams, type Compare } from '@/lib/accounts'
import { usePageTitle } from '@/lib/page-title'

// ACC-06 / ACC-22: profit and loss for a period, the company, a project or a site (scope bar), with a comparison
// against the period before or the same period last year. Backend: GET /accounts/pl.

export default function ProfitLossPage() {
  usePageTitle('Profit & loss')
  const { me } = useAuth()
  const { scope } = useScope()
  const periodState = usePeriod('this_month')
  const { period } = periodState
  const [params, setParams] = useSearchParams()
  const compare = (params.get('compare') ?? 'previous') as Compare
  const sp = scopeParams(scope)
  const allowed = mayReadBooks(me?.role)
  const q = useQuery({ queryKey: ['accounts', 'pl', period, sp, compare], queryFn: () => fetchPl(period, sp, compare), enabled: allowed })
  if (!allowed) return <BooksClosed />
  if (q.isError) return <PageError message="The profit and loss could not be loaded." onRetry={() => q.refetch()} back={{ to: '/accounts', label: 'Accounts' }} />
  const d = q.data
  const t = d?.totals
  const span = (a: string, b: string) => (a.slice(0, 7) === b.slice(0, 7) && a.endsWith('-01') ? new Date(`${a}T00:00:00`).toLocaleDateString('en-IN', { month: 'short', year: 'numeric' }) : `${formatDay(a)} – ${formatDay(b)}`)

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 pb-8 sm:px-2">
      <DprHeader back={{ to: '/accounts', label: 'Accounts' }} crumb="Accounts" title="Profit & loss" date={d?.scope} />
      <BooksTabs current="/accounts/pl" />
      <div className="flex flex-wrap items-center gap-2">
        <PeriodBar state={periodState} />
        <Segmented<Compare>
          label="Compare with"
          value={compare}
          options={[
            { value: '', label: 'No comparison' },
            { value: 'previous', label: 'Period before' },
            { value: 'last_year', label: 'Last year' },
          ]}
          onChange={(c) => setParams((p) => {
            const n = new URLSearchParams(p)
            n.set('compare', c)
            return n
          }, { replace: true })}
        />
      </div>
      {!d || !t ? (
        <Skeleton className="h-96 rounded-xl" />
      ) : (
        <>
          <StatStrip
            phoneCols={2}
            stats={[
              { label: 'Income', value: rupees(t.income), icon: Receipt },
              { label: 'Costs', value: rupees(Number(t.direct) + Number(t.indirect) - Number(t.other_income)), icon: BadgeIndianRupee, hint: 'less other income' },
              { label: 'Gross profit', value: rupees(t.gross_profit), tone: Number(t.gross_profit) < 0 ? 'bad' : 'default', hint: t.gross_margin ? `${pctText(t.gross_margin)} of income` : undefined },
              { label: Number(t.net_profit) < 0 ? 'Net loss' : 'Net profit', value: rupees(t.net_profit), icon: TrendingUp, tone: Number(t.net_profit) < 0 ? 'bad' : 'good', hint: t.net_margin ? `${pctText(t.net_margin)} of income` : undefined },
            ]}
          />
          {Number(d.overheads) !== 0 && scope.mode !== 'portfolio' && (
            <Callout tone="info" icon={Building2}>
              Includes this project's share of head-office costs, {rupees(d.overheads)}. Before it: {rupees(d.net_before_overheads)} {Number(d.net_before_overheads) < 0 ? 'loss' : 'profit'}.
            </Callout>
          )}
          <DprSection icon={TrendingUp} title="Statement">
            <PlStatement
              pl={d}
              periodLabel={span(d.date_from, d.date_to)}
              priorLabel={d.compare ? span(d.compare.date_from, d.compare.date_to) : undefined}
            />
            <p className="text-xs text-muted-foreground">
              Income is RA bills sent (before GST); costs are bills and expenses as booked, net of GST the company can claim. Labour reaches the books when wages are paid. Tap a group for its ledgers, a ledger for its entries.
            </p>
          </DprSection>
        </>
      )}
    </div>
  )
}
