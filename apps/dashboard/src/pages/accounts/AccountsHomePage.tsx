import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, BadgeIndianRupee, BookOpenCheck, Building2, CircleAlert, Landmark, Receipt, Scale, TrendingUp, Wallet } from 'lucide-react'
import { BooksClosed, BooksTabs } from '@/components/accounts/books'
import { Delta, DrCr, ShareBar, SplitBars, pctText } from '@/components/accounts/visuals'
import { Callout, DprHeader, DprSection, PageError, StatStrip } from '@/components/dpr-page'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { useScope } from '@/lib/ScopeContext'
import { change, fetchHome, formatDay, mayReadBooks, mayReadProjectBooks, rupees, short, type Home, type MonthFigure } from '@/lib/accounts'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'

// ACC-09: the owner's one screen, for the company or (scope bar) one project: cash and bank today, owed to us and by
// us, this month's profit against last, the year by month, GST this month, TDS to deposit, the projects best first,
// and what needs the accountant. Every card opens the page behind it. Backend: GET /accounts/home.

const monthLabel = (m: string) => new Date(`${m}-01T00:00:00`).toLocaleDateString('en-IN', { month: 'short' })

function YearChart({ months }: { months: MonthFigure[] }) {
  return (
    <SplitBars
      up="Profit"
      down="Loss"
      items={months.map((m) => ({
        key: m.month,
        label: monthLabel(m.month),
        up: Math.max(0, Number(m.profit)),
        down: Math.max(0, -Number(m.profit)),
        detail: (
          <>
            {new Date(`${m.month}-01T00:00:00`).toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })}: income {short(m.income)}, cost {short(m.cost)},{' '}
            <span className="font-medium text-foreground">{Number(m.profit) < 0 ? 'loss' : 'profit'} {short(Math.abs(Number(m.profit)))}</span>
          </>
        ),
      }))}
    />
  )
}

function ProjectHome({ d }: { d: Home }) {
  const p = d.position!
  return (
    <>
      <StatStrip
        phoneCols={2}
        stats={[
          { label: 'Billed to the client', value: rupees(p.billed), icon: Receipt },
          { label: 'Cost booked', value: rupees(p.cost), icon: BadgeIndianRupee },
          { label: Number(p.profit) < 0 ? 'Loss' : 'Profit', value: rupees(p.profit), tone: Number(p.profit) < 0 ? 'bad' : 'good', hint: p.margin ? `${pctText(p.margin)} of billing` : undefined, icon: TrendingUp },
          { label: 'Client owes', value: rupees(p.receivable), tone: Number(p.receivable) > 0 ? 'info' : 'default', icon: Landmark },
        ]}
      />
      <Callout tone="info" icon={Building2} action={<Button asChild size="sm" variant="outline"><Link to="/accounts/projects">All projects</Link></Button>}>
        A project's own books: its position below, and the full P&L and position under Projects.
      </Callout>
    </>
  )
}

export default function AccountsHomePage() {
  usePageTitle('Accounts')
  const { me } = useAuth()
  const { scope } = useScope()
  const projectId = scope.mode === 'portfolio' ? undefined : scope.projectId
  const companyReader = mayReadBooks(me?.role)
  const allowed = companyReader || (!!projectId && mayReadProjectBooks(me?.role))
  const q = useQuery({ queryKey: ['accounts', 'home', projectId], queryFn: () => fetchHome(projectId), enabled: allowed })
  if (!allowed) return <BooksClosed />
  if (q.isError) return <PageError message="The accounts home could not be loaded." onRetry={() => q.refetch()} back={{ to: '/finance/money', label: 'Money' }} />
  const d = q.data
  const tm = d?.this_month
  const lm = d?.last_month
  const topProfit = Math.max(0, ...(d?.projects ?? []).map((p) => Math.abs(Number(p.profit))))

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 pb-8 sm:px-2">
      <DprHeader back={{ to: '/finance/money', label: 'Money' }} crumb="Accounts" title="Accounts" date={d ? `${d.financial_year} · ${d.scope} · ${formatDay(d.today)}` : undefined} />
      <BooksTabs current="/accounts" />
      {!d || !tm || !lm ? (
        <Skeleton className="h-[32rem] rounded-xl" />
      ) : (
        <>
          {d.position ? (
            <ProjectHome d={d} />
          ) : (
            <StatStrip
              phoneCols={2}
              stats={[
                { label: 'Cash & bank today', value: rupees(d.cash_bank?.total ?? 0), icon: Wallet, tone: Number(d.cash_bank?.total) < 0 ? 'bad' : 'default' },
                { label: 'Clients owe us', value: rupees(d.receivable ?? 0), icon: Landmark, tone: Number(d.receivable) > 0 ? 'info' : 'default' },
                { label: 'We owe suppliers & staff', value: rupees(d.payable ?? 0), icon: Scale, tone: Number(d.payable) > 0 ? 'warn' : 'default' },
                {
                  label: `${Number(tm.net_profit) < 0 ? 'Loss' : 'Profit'} this month`,
                  value: rupees(tm.net_profit),
                  icon: TrendingUp,
                  tone: Number(tm.net_profit) < 0 ? 'bad' : 'good',
                  hint: Number(lm.net_profit) ? `last month ${short(lm.net_profit)}` : undefined,
                },
              ]}
            />
          )}

          {(d.attention ?? []).length > 0 && (
            <Callout tone="draft" icon={CircleAlert}>
              <span className="font-medium">For the accountant</span>
              <ul className="mt-1 flex flex-col gap-0.5 text-xs">
                {d.attention!.map((a) => (
                  <li key={a.key}>
                    <Link to={a.ledger_id ? `/accounts/ledgers/${a.ledger_id}` : a.to} className="underline">
                      {a.words}
                    </Link>
                    {a.amount && <span className="tabular-nums"> {rupees(a.amount)}</span>}
                  </li>
                ))}
              </ul>
            </Callout>
          )}

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
            <DprSection icon={TrendingUp} title={`Year ${d.financial_year}, month by month`} meta={<span className="tabular-nums">{rupees(d.year.net_profit)} {Number(d.year.net_profit) < 0 ? 'loss' : 'profit'} so far</span>}>
              <div className="rounded-xl border px-4 py-3">
                <YearChart months={d.months} />
              </div>
              <div className="grid gap-2 sm:grid-cols-3">
                {[
                  { label: 'Income this month', now: tm.income, before: lm.income, good: true },
                  { label: 'Costs this month', now: Number(tm.direct) + Number(tm.indirect), before: Number(lm.direct) + Number(lm.indirect), good: false },
                  { label: 'Gross margin', now: tm.gross_margin ?? 0, before: lm.gross_margin, good: true, pct: true },
                ].map((c) => (
                  <div key={c.label} className="rounded-lg border px-3 py-2">
                    <p className="text-xs text-muted-foreground">{c.label}</p>
                    <p className="flex items-baseline gap-2 text-lg font-semibold tabular-nums">
                      {c.pct ? (tm.gross_margin === null ? '—' : pctText(c.now)) : rupees(c.now)}
                      <Delta pct={change(c.now, c.before)} goodWhenUp={c.good} />
                    </p>
                    <p className="text-[11px] text-muted-foreground">against last month</p>
                  </div>
                ))}
              </div>
              <Link to="/accounts/pl?range=this_month" className="inline-flex items-center gap-1 text-sm font-medium hover:underline">
                Profit & loss <ArrowRight className="size-3.5" />
              </Link>
            </DprSection>

            {d.position ? (
              <DprSection icon={Building2} title="Project position">
                <dl className="flex flex-col divide-y rounded-lg border text-sm">
                  {[
                    ['Received from the client', d.position.received],
                    ['Retention held by the client', d.position.retention_held_by_client],
                    ['TDS deducted by the client', d.position.tds_deducted_by_client],
                    ['Advance received', d.position.advance_received],
                    ['Owed to suppliers', d.position.owed_to_suppliers],
                    ['Paid out for the project', d.position.paid_out],
                  ].map(([k, v]) => (
                    <div key={k} className="flex justify-between gap-2 px-3 py-2">
                      <dt className="text-muted-foreground">{k}</dt>
                      <dd className="tabular-nums">{rupees(v)}</dd>
                    </div>
                  ))}
                </dl>
                <Link to={`/accounts/projects/${projectId}`} className="inline-flex items-center gap-1 text-sm font-medium hover:underline">
                  The project's books <ArrowRight className="size-3.5" />
                </Link>
              </DprSection>
            ) : (
              <DprSection icon={Wallet} title="Cash & bank today" meta={d.cash_bank?.accounts.length || undefined}>
                <ul className="flex flex-col divide-y rounded-lg border text-sm">
                  {(d.cash_bank?.accounts ?? []).map((a) => (
                    <li key={a.ledger_id}>
                      <Link to={`/accounts/ledgers/${a.ledger_id}`} className="flex items-center justify-between gap-2 px-3 py-2 hover:bg-muted/40">
                        <span className="min-w-0 truncate">{a.name}</span>
                        <DrCr value={a.closing} />
                      </Link>
                    </li>
                  ))}
                </ul>
                <div className="grid grid-cols-2 gap-2">
                  <Link to="/accounts/gst?range=this_month" className="rounded-lg border px-3 py-2 hover:bg-muted/40">
                    <p className="text-xs text-muted-foreground">GST payable this month</p>
                    <p className={cn('text-lg font-semibold tabular-nums', Number(d.gst_this_month?.payable) < 0 && 'text-success')}>
                      {Number(d.gst_this_month?.payable) < 0 ? `${rupees(d.gst_this_month?.payable ?? 0)} credit` : rupees(d.gst_this_month?.payable ?? 0)}
                    </p>
                    <p className="text-[11px] text-muted-foreground">
                      out {short(d.gst_this_month?.output ?? 0)} − in {short(d.gst_this_month?.input ?? 0)}
                    </p>
                  </Link>
                  <Link to="/accounts/tds" className="rounded-lg border px-3 py-2 hover:bg-muted/40">
                    <p className="text-xs text-muted-foreground">TDS to deposit</p>
                    <p className="text-lg font-semibold tabular-nums">{rupees(d.tds_to_deposit ?? 0)}</p>
                    <p className="text-[11px] text-muted-foreground">deducted from subcontractors</p>
                  </Link>
                </div>
                <Link to="/accounts/cash-bank" className="inline-flex items-center gap-1 text-sm font-medium hover:underline">
                  Cash & bank books <ArrowRight className="size-3.5" />
                </Link>
              </DprSection>
            )}
          </div>

          {!d.position && (
            <DprSection icon={Building2} title="Projects this year, most profit first" meta={d.projects.length || undefined}>
              {d.projects.length === 0 ? (
                <p className="text-sm text-muted-foreground">No project has income or cost in the books yet.</p>
              ) : (
                <ul className="flex flex-col divide-y rounded-lg border text-sm">
                  {d.projects.map((p) => (
                    <li key={p.project_id}>
                      <Link to={`/accounts/projects/${p.project_id}`} className="flex flex-col gap-1 px-3 py-2.5 hover:bg-muted/40 sm:flex-row sm:items-center sm:gap-4">
                        <span className="min-w-0 flex-1">
                          <span className="block truncate font-medium">{p.name}</span>
                          <span className="block text-xs text-muted-foreground tabular-nums">
                            billed {short(p.billed)} · cost {short(Number(p.cost) + Number(p.overheads))}
                            {Number(p.receivable) > 0 ? ` · client owes ${short(p.receivable)}` : ''}
                          </span>
                        </span>
                        <span className="flex w-full flex-col items-end gap-1 sm:w-48">
                          <span className={cn('font-semibold tabular-nums', Number(p.profit) < 0 ? 'text-destructive' : 'text-success')}>
                            {Number(p.profit) < 0 ? 'Loss ' : ''}
                            {rupees(p.profit)}
                            {p.margin !== null && <span className="ml-1.5 text-xs font-normal text-muted-foreground">{pctText(p.margin)}</span>}
                          </span>
                          <ShareBar value={Number(p.profit)} max={topProfit} className="w-full sm:w-36" />
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
              <Link to="/accounts/projects" className="inline-flex items-center gap-1 text-sm font-medium hover:underline">
                Every project's P&L <ArrowRight className="size-3.5" />
              </Link>
            </DprSection>
          )}
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <BookOpenCheck className="size-3.5" /> Posted from the records on their own: nothing to type. Every figure opens the entries behind it.
          </p>
        </>
      )}
    </div>
  )
}
