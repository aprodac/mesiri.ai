import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { Building2 } from 'lucide-react'
import { BooksClosed, PeriodBar, usePeriod } from '@/components/accounts/books'
import { PlSimple } from '@/components/accounts/pl-simple'
import { PlMonths } from '@/components/accounts/pl-months'
import { PlFormulaStrip, PlTwoColumn } from '@/components/accounts/pl-two-column'
import { Callout, DprHeader, PageError, Segmented } from '@/components/dpr-page'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { useScope } from '@/lib/ScopeContext'
import { fetchPl, formatDay, mayReadBooks, rupees, scopeParams, type Compare } from '@/lib/accounts'
import { usePageTitle } from '@/lib/page-title'
import { useBooksView } from '@/lib/books-view'

// ACC-06 / ACC-22: profit and loss for a period, the company, a project or a site (scope bar), with a comparison
// against the period before or the same period last year. Backend: GET /accounts/pl.
// UX-30 / UX-31: the same numbers, three ways to read them. "Simple" (the owner's): the result in a sentence, where
// each ₹100 went, and the statement top to bottom in plain words. "Tally": the trading account and the profit and
// loss account in two columns, with the sum as a row of figures. "Month by month": each month in a column.
// Which one opens: the person's last pick (this browser) -> on a phone, Simple -> Tally for finance people and for
// those who came from other accounting software (start mode "switching") -> Simple.

const VIEWS = ['simple', 'statement', 'months'] as const

export default function ProfitLossPage() {
  usePageTitle('Profit & loss')
  const { me } = useAuth()
  const { scope } = useScope()
  const periodState = usePeriod('this_month')
  const { period } = periodState
  const [params, setParams] = useSearchParams()
  const compare = (params.get('compare') ?? 'previous') as Compare
  const [view, pickView] = useBooksView('pl', VIEWS, { list: 'simple' })
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
  const prior = d?.compare ? span(d.compare.date_from, d.compare.date_to) : undefined
  const overheadsNote =
    d && Number(d.overheads) !== 0 && scope.mode !== 'portfolio' ? (
      <Callout tone="info" icon={Building2}>
        Includes this project's share of head-office costs, {rupees(d.overheads)}. Before it: {rupees(d.net_before_overheads)} {Number(d.net_before_overheads) < 0 ? 'loss' : 'profit'}.
      </Callout>
    ) : null

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader back={{ to: '/accounts', label: 'Accounts' }} crumb="Accounts" title="Profit & loss" />
      <div className="flex flex-wrap items-center gap-2">
        <Segmented<(typeof VIEWS)[number]>
          guide="pl.view"
          label="Show as"
          value={view}
          options={[
            { value: 'simple', label: 'Simple' },
            { value: 'statement', label: 'Tally' },
            { value: 'months', label: 'Month by month' },
          ]}
          onChange={pickView}
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
      ) : view === 'simple' ? (
        <PlSimple
          pl={d}
          period={period}
          scope={sp}
          company={scope.mode === 'portfolio'}
          periodLabel={span(d.date_from, d.date_to)}
          priorLabel={prior}
          notice={overheadsNote}
        />
      ) : (
        <>
          <PlFormulaStrip pl={d} priorLabel={prior} />
          {overheadsNote}
          <div data-guide="pl.statement">
            {view === 'months' ? <PlMonths period={period} scope={sp} total={d} /> : <PlTwoColumn pl={d} periodLabel={span(d.date_from, d.date_to)} priorLabel={prior} />}
          </div>
        </>
      )}
    </div>
  )
}
