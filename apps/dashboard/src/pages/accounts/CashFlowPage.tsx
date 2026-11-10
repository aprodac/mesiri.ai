import { useQuery } from '@tanstack/react-query'
import { ArrowDownLeft, ArrowUpRight, CircleAlert, Landmark, Waves } from 'lucide-react'
import { BooksClosed, BooksTabs, ExcelButton, PeriodBar, usePeriod } from '@/components/accounts/books'
import { Callout, DprHeader, DprSection, PageError, StatStrip } from '@/components/dpr-page'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { useScope } from '@/lib/ScopeContext'
import { fetchCashFlow, mayReadBooks, rupees, scopeParams, type CashFlowSection } from '@/lib/accounts'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'

// ACC-18: where the money came from and where it went in a period (the direct method, from the books' own cash and
// bank lines): operating (clients, suppliers, labour, staff, taxes), investing (assets), financing (capital, loans).
// Opening + net = closing, the same as Cash & bank; a move between your own accounts is not a flow. For the company, a
// project or a site (scope bar). Backend: GET /accounts/cash-flow.

const SECTIONS = [
  ['operating', 'Running the business'],
  ['investing', 'Fixed assets'],
  ['financing', 'Capital and loans'],
  ['other', 'Other'],
] as const

const signed = (v: string) => `${Number(v) < 0 ? '−' : '+'}${rupees(v)}`

export default function CashFlowPage() {
  usePageTitle('Cash flow')
  const { me } = useAuth()
  const { scope } = useScope()
  const periodState = usePeriod('this_month')
  const { period } = periodState
  const sp = scopeParams(scope)
  const allowed = mayReadBooks(me?.role)
  const q = useQuery({ queryKey: ['accounts', 'cash-flow', period, sp], queryFn: () => fetchCashFlow(period, sp), enabled: allowed })
  if (!allowed) return <BooksClosed />
  if (q.isError) return <PageError message="The cash flow could not be loaded." onRetry={() => q.refetch()} back={{ to: '/accounts/cash-bank', label: 'Cash & bank' }} />
  const d = q.data
  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader back={{ to: '/accounts/cash-bank', label: 'Cash & bank' }} crumb="Accounts" title="Cash flow" date={d?.scope}
        action={d && <ExcelButton path="/accounts/cash-flow/export" params={{ ...period, ...sp }} name={`cash-flow-${period.date_from}-to-${period.date_to}`} />} />
      <BooksTabs current="/accounts/cash-flow" />
      <PeriodBar state={periodState} />
      {!d ? (
        <Skeleton className="h-96 rounded-xl" />
      ) : (
        <>
          <StatStrip
            phoneCols={2}
            stats={[
              { label: 'Opening cash and bank', value: rupees(d.opening), icon: Landmark },
              { label: 'From running the business', value: signed(d.sections.operating.net), icon: Waves, tone: Number(d.sections.operating.net) < 0 ? 'bad' : 'good' },
              { label: 'Net change', value: signed(d.net), icon: Number(d.net) < 0 ? ArrowUpRight : ArrowDownLeft, tone: Number(d.net) < 0 ? 'warn' : 'good' },
              { label: 'Closing cash and bank', value: rupees(d.closing), icon: Landmark, tone: 'info' },
            ]}
          />
          {!d.agrees && (
            <Callout tone="draft" icon={CircleAlert}>The flows add up to {rupees(d.closing)} but Cash & bank closes at {rupees(d.books_closing)}. Tell Mesiri support.</Callout>
          )}
          {SECTIONS.map(([key, title]) => {
            const s: CashFlowSection = d.sections[key]
            if (!s.items.length) return null
            return (
              <DprSection key={key} icon={Waves} title={title} meta={signed(s.net)}>
                <ul className="divide-y rounded-lg border text-sm">
                  {s.items.map((i) => (
                    <li key={i.key} className="flex flex-col gap-1 px-3 py-2 sm:flex-row sm:items-center sm:gap-4">
                      <span className="min-w-0 flex-1 font-medium">{i.label}</span>
                      <span className="text-xs text-muted-foreground tabular-nums">in {rupees(i.in)} · out {rupees(i.out)}</span>
                      <span className={cn('w-32 text-right font-semibold tabular-nums', Number(i.net) < 0 ? 'text-destructive' : 'text-success')}>{signed(i.net)}</span>
                    </li>
                  ))}
                </ul>
              </DprSection>
            )
          })}
          {d.months.length > 1 && (
            <DprSection icon={Landmark} title="Month by month" meta={d.months.length}>
              <ul className="divide-y rounded-lg border text-sm">
                {d.months.map((m) => (
                  <li key={m.month} className="flex items-center gap-4 px-3 py-1.5">
                    <span className="flex-1">{new Date(`${m.month}-01T00:00:00`).toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })}</span>
                    <span className="text-xs text-muted-foreground tabular-nums">in {rupees(m.in)} · out {rupees(m.out)}</span>
                    <span className={cn('w-32 text-right tabular-nums', Number(m.net) < 0 ? 'text-destructive' : '')}>{signed(m.net)}</span>
                  </li>
                ))}
              </ul>
            </DprSection>
          )}
        </>
      )}
    </div>
  )
}
