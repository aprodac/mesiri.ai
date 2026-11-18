import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Building2, HandCoins, PieChart, Receipt, Target, TrendingUp } from 'lucide-react'
import { BooksClosed, PeriodBar, usePeriod } from '@/components/accounts/books'
import { FlowStrip } from '@/components/accounts/money-kit'
import { PlSimple } from '@/components/accounts/pl-simple'
import { PlTwoColumn } from '@/components/accounts/pl-two-column'
import { PartsBar, ShareBar, SplitBars, pctText } from '@/components/accounts/visuals'
import { Callout, DprHeader, DprSection, PageError, Segmented } from '@/components/dpr-page'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { fetchProjectBooks, formatDay, mayReadProjectBooks, rupees, short } from '@/lib/accounts'
import { useBooksView } from '@/lib/books-view'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'

// ACC-08 (plan §5.8): one project's books: its position (billed, received, owed, held back, owed to others), its P&L
// by group and cost centre, its months, and Cost control's BOQ budget and forecast beside the books. The project's
// manager sees it too. Backend: GET /accounts/projects/{id}.
// UXA-07: the period as a sum (billed − cost = profit, and what the client owes today); the position with its colour
// cues (money in green, owed to you amber, owed to others rose); the P&L as on Profit & loss, Simple (with every line
// opening to its entries and vouchers) or Tally, the same pick (lib/books-view.ts).

const VIEWS = ['simple', 'statement'] as const

const CENTRE: Record<string, string> = {
  materials: 'Materials',
  labour: 'Labour',
  subcontract: 'Subcontract',
  equipment: 'Machines',
  overheads: 'Site overheads',
  not_set: 'No cost centre',
}

function Row({ label, v, hint, strong, tone }: { label: string; v: string | number; hint?: string; strong?: boolean; tone?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 px-3 py-2">
      <dt className="text-muted-foreground">
        {label}
        {hint && <span className="block text-[11px]">{hint}</span>}
      </dt>
      <dd className={cn('tabular-nums', strong && 'font-semibold', tone)}>{rupees(v)}</dd>
    </div>
  )
}

export default function ProjectBooksPage() {
  const { id = '' } = useParams()
  const { me } = useAuth()
  const periodState = usePeriod()
  const { period } = periodState
  const allowed = mayReadProjectBooks(me?.role)
  const [view, pickView] = useBooksView('pl', VIEWS, { list: 'simple', months: 'simple' })
  const q = useQuery({ queryKey: ['accounts', 'project', id, period], queryFn: () => fetchProjectBooks(id, period), enabled: allowed && !!id })
  const name = q.data?.scope.replace(/^project /, '')
  usePageTitle(name ? `${name}: books` : 'Project books')
  if (!allowed) return <BooksClosed />
  if (q.isError) return <PageError message="This project's books could not be loaded." onRetry={() => q.refetch()} back={{ to: '/accounts/projects', label: 'Projects' }} />
  const d = q.data
  const p = d?.position
  const b = d?.budget
  const booksCost = d ? Number(d.pl.totals.direct) + Number(d.pl.totals.indirect) : 0
  const budgetMax = b ? Math.max(Number(b.budget ?? 0), Number(b.forecast ?? 0), Number(b.spent), booksCost) : 0

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader back={{ to: '/accounts/projects', label: 'Projects' }} crumb="Accounts · Projects" title={name ?? 'Project'} />
      <PeriodBar state={periodState} />
      {!d || !p ? (
        <Skeleton className="h-[32rem] rounded-xl" />
      ) : (
        <>
          {(() => {
            const np = Number(d.pl.totals.net_profit)
            return (
              <FlowStrip
                items={[
                  { label: 'Billed in the period', value: rupees(d.pl.totals.income), tone: 'in', sub: 'RA bills, before GST' },
                  { label: 'Cost in the period', value: rupees(booksCost), tone: 'out', op: '−', sub: 'bills, wages and expenses' },
                  { label: np < 0 ? 'Loss' : 'Profit', value: (np < 0 ? '−' : '') + rupees(np), tone: np < 0 ? 'out' : 'balance', op: '=', sub: d.pl.totals.net_margin ? `${pctText(d.pl.totals.net_margin)} of billing` : undefined },
                  { label: 'Client owes today', value: rupees(p.receivable), tone: 'plain', sub: `retention held ${short(p.retention_held_by_client)}` },
                ]}
              />
            )
          })()}
          {Number(d.pl.overheads) !== 0 && (
            <Callout tone="info" icon={Building2}>
              After its head-office share of {rupees(d.pl.overheads)}. Before it: {rupees(d.pl.net_before_overheads)}.
            </Callout>
          )}
          <div className="grid gap-4 lg:grid-cols-2">
            <DprSection icon={HandCoins} title="Position today">
              <div className="grid gap-3 sm:grid-cols-2">
                <dl className="divide-y rounded-xl border bg-card text-sm shadow-xs">
                  <p className="flex items-center gap-1.5 bg-emerald-500/[0.06] px-3 py-1.5 text-xs font-semibold text-emerald-700 dark:text-emerald-400">With the client</p>
                  <Row label="Billed so far" v={p.billed} hint={`+ GST ${short(p.gst_billed)}`} />
                  <Row label="Received" v={p.received} tone="text-emerald-700 dark:text-emerald-400" />
                  <Row label="Still owed" v={p.receivable} strong tone="text-draft" />
                  <Row label="Retention held back" v={p.retention_held_by_client} />
                  <Row label="TDS they deducted" v={p.tds_deducted_by_client} hint="claim it in the return" />
                  {Number(p.advance_received) !== 0 && <Row label="Advance not recovered" v={p.advance_received} />}
                </dl>
                <dl className="divide-y rounded-xl border bg-card text-sm shadow-xs">
                  <p className="flex items-center gap-1.5 bg-rose-500/[0.05] px-3 py-1.5 text-xs font-semibold text-rose-700 dark:text-rose-400">With others</p>
                  <Row label="Cost booked so far" v={p.cost} />
                  <Row label="Owed to suppliers" v={p.owed_to_suppliers} strong tone="text-rose-700 dark:text-rose-400" />
                  {Number(p.owed_to_staff) !== 0 && <Row label="Owed to staff" v={p.owed_to_staff} hint="paid from their pocket" />}
                  <Row label="Paid out" v={p.paid_out} />
                  <Row label="Cash: in less out" v={p.cash_in_hand} hint="received − paid out" />
                  <Row label={Number(p.profit) < 0 ? 'Loss so far' : 'Profit so far'} v={p.profit} strong tone={Number(p.profit) < 0 ? 'text-destructive' : 'text-success'} />
                </dl>
              </div>
            </DprSection>
            <div className="flex flex-col gap-4">
              {d.centres.length > 0 && (
                <DprSection icon={PieChart} title="Where the cost went (period)">
                  <PartsBar parts={d.centres.map((c) => ({ label: CENTRE[c.cost_centre] ?? c.cost_centre, value: Number(c.amount) }))} />
                </DprSection>
              )}
              {b && (b.budget || b.forecast) && (
                <DprSection icon={Target} title="Against the BOQ budget">
                  <ul className="flex flex-col gap-2 text-sm">
                    {[
                      { label: 'BOQ budget', v: Number(b.budget ?? 0), hint: 'Cost control' },
                      { label: 'Forecast at completion', v: Number(b.forecast ?? 0), hint: 'Cost control: spent + committed + still to do' },
                      { label: 'Full cost so far', v: Number(b.spent), hint: 'Cost control: with attendance and deliveries not billed' },
                      { label: 'Cost in the books', v: booksCost, hint: 'bills and expenses booked (period)' },
                    ]
                      .filter((r) => r.v)
                      .map((r) => (
                        <li key={r.label} className="flex flex-col gap-1">
                          <span className="flex justify-between gap-2">
                            <span>
                              {r.label} <span className="text-xs text-muted-foreground">· {r.hint}</span>
                            </span>
                            <span className="tabular-nums">{rupees(r.v)}</span>
                          </span>
                          <ShareBar value={r.v} max={budgetMax} />
                        </li>
                      ))}
                  </ul>
                  {Number(b.forecast ?? 0) > Number(b.budget ?? 0) && Number(b.budget ?? 0) > 0 && (
                    <p className="text-sm font-medium text-destructive">
                      Forecast {rupees(Number(b.forecast) - Number(b.budget))} over the budget ({pctText(((Number(b.forecast) - Number(b.budget)) / Number(b.budget)) * 100)}).
                    </p>
                  )}
                  <Link to={`/cost/budget?project=${d.project_id}`} className="inline-flex items-center gap-1 text-sm font-medium hover:underline">
                    Budget vs actual <ArrowRight className="size-3.5" />
                  </Link>
                </DprSection>
              )}
            </div>
          </div>
          {d.months.some((m) => Number(m.income) || Number(m.cost)) && (
            <DprSection icon={TrendingUp} title="This year, month by month">
              <div className="rounded-xl border bg-card px-4 py-3 shadow-xs">
                <SplitBars
                  up="Profit"
                  down="Loss"
                  items={d.months.map((m) => ({
                    key: m.month,
                    label: new Date(`${m.month}-01T00:00:00`).toLocaleDateString('en-IN', { month: 'short' }),
                    up: Math.max(0, Number(m.profit)),
                    down: Math.max(0, -Number(m.profit)),
                    detail: (
                      <>
                        {new Date(`${m.month}-01T00:00:00`).toLocaleDateString('en-IN', { month: 'long' })}: billed {short(m.income)}, cost {short(m.cost)}
                      </>
                    ),
                  }))}
                />
              </div>
            </DprSection>
          )}
          <DprSection
            icon={Receipt}
            title="Profit & loss (period)"
            meta={
              <Segmented<(typeof VIEWS)[number]>
                label="Show as"
                value={view}
                options={[
                  { value: 'simple', label: 'Simple' },
                  { value: 'statement', label: 'Tally' },
                ]}
                onChange={pickView}
              />
            }
          >
            {view === 'simple' ? (
              <PlSimple pl={d.pl} period={period} scope={{ project_id: d.project_id }} company={false} hero={false} periodLabel={`${formatDay(d.date_from)} – ${formatDay(d.date_to)}`} />
            ) : (
              <PlTwoColumn pl={d.pl} periodLabel={`${formatDay(d.date_from)} – ${formatDay(d.date_to)}`} />
            )}
          </DprSection>
        </>
      )}
    </div>
  )
}
