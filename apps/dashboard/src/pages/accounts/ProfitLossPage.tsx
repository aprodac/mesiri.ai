import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { Building2 } from 'lucide-react'
import { BooksClosed, BooksTabs, PeriodBar, usePeriod } from '@/components/accounts/books'
import { PlStatement } from '@/components/accounts/pl-statement'
import { PlFormulaStrip, PlTwoColumn } from '@/components/accounts/pl-two-column'
import { Callout, DprHeader, PageError, Segmented } from '@/components/dpr-page'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { useScope } from '@/lib/ScopeContext'
import { fetchPl, formatDay, mayReadBooks, rupees, scopeParams, type Compare } from '@/lib/accounts'
import { usePageTitle } from '@/lib/page-title'

// ACC-06 / ACC-22: profit and loss for a period, the company, a project or a site (scope bar), with a comparison
// against the period before or the same period last year. Backend: GET /accounts/pl.
// UX-30: the statement reads in Tally's two columns by default (trading account, then profit and loss account), with
// the sum above it as a row of figures; "List" keeps the one-column statement.

type View = 'statement' | 'list'

export default function ProfitLossPage() {
  usePageTitle('Profit & loss')
  const { me } = useAuth()
  const { scope } = useScope()
  const periodState = usePeriod('this_month')
  const { period } = periodState
  const [params, setParams] = useSearchParams()
  const compare = (params.get('compare') ?? 'previous') as Compare
  const view: View = params.get('view') === 'list' ? 'list' : 'statement'
  const setParam = (k: string, v: string) =>
    setParams((p) => {
      const n = new URLSearchParams(p)
      n.set(k, v)
      return n
    }, { replace: true })
  const sp = scopeParams(scope)
  const allowed = mayReadBooks(me?.role)
  const q = useQuery({ queryKey: ['accounts', 'pl', period, sp, compare], queryFn: () => fetchPl(period, sp, compare), enabled: allowed })
  if (!allowed) return <BooksClosed />
  if (q.isError) return <PageError message="The profit and loss could not be loaded." onRetry={() => q.refetch()} back={{ to: '/accounts', label: 'Accounts' }} />
  const d = q.data
  const t = d?.totals
  const span = (a: string, b: string) => (a.slice(0, 7) === b.slice(0, 7) && a.endsWith('-01') ? new Date(`${a}T00:00:00`).toLocaleDateString('en-IN', { month: 'short', year: 'numeric' }) : `${formatDay(a)} – ${formatDay(b)}`)

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader back={{ to: '/accounts', label: 'Accounts' }} crumb="Accounts" title="Profit & loss" />
      <BooksTabs current="/accounts/pl" />
      <div className="flex flex-wrap items-center gap-2">
        <Segmented<View>
          label="Show as"
          value={view}
          options={[
            { value: 'statement', label: 'Statement' },
            { value: 'list', label: 'List' },
          ]}
          onChange={(v) => setParam('view', v)}
        />
        <PeriodBar state={periodState} />
        <Segmented<Compare>
          guide="pl.compare"
          label="Compare with"
          value={compare}
          options={[
            { value: '', label: 'No comparison' },
            { value: 'previous', label: 'Period before' },
            { value: 'last_year', label: 'Last year' },
          ]}
          onChange={(c) => setParam('compare', c)}
        />
      </div>
      {!d || !t ? (
        <Skeleton className="h-96 rounded-xl" />
      ) : (
        <>
          <PlFormulaStrip pl={d} priorLabel={d.compare ? span(d.compare.date_from, d.compare.date_to) : undefined} />
          {Number(d.overheads) !== 0 && scope.mode !== 'portfolio' && (
            <Callout tone="info" icon={Building2}>
              Includes this project's share of head-office costs, {rupees(d.overheads)}. Before it: {rupees(d.net_before_overheads)} {Number(d.net_before_overheads) < 0 ? 'loss' : 'profit'}.
            </Callout>
          )}
          <div data-guide="pl.statement">
            {view === 'statement' ? (
              <PlTwoColumn pl={d} periodLabel={span(d.date_from, d.date_to)} priorLabel={d.compare ? span(d.compare.date_from, d.compare.date_to) : undefined} />
            ) : (
              <PlStatement pl={d} periodLabel={span(d.date_from, d.date_to)} priorLabel={d.compare ? span(d.compare.date_from, d.compare.date_to) : undefined} />
            )}
          </div>
        </>
      )}
    </div>
  )
}
