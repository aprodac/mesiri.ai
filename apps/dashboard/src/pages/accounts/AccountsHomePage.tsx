import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowRight,
  BookOpen,
  BookOpenText,
  Building2,
  CalendarCheck,
  CircleAlert,
  FolderKanban,
  Landmark,
  ListTree,
  Percent,
  ReceiptIndianRupee,
  Scale,
  ScrollText,
  TrendingUp,
  Wallet,
  type LucideIcon,
} from 'lucide-react'
import { BooksClosed } from '@/components/accounts/books'
import { Change } from '@/components/accounts/change-chip'
import { SplitBars, pctText } from '@/components/accounts/visuals'
import { DprHeader, PageError } from '@/components/dpr-page'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { useScope } from '@/lib/ScopeContext'
import { fetchHome, formatDay, mayReadBooks, mayReadProjectBooks, rupees, short, type Home, type MonthFigure } from '@/lib/accounts'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'

// ACC-09: the owner's one screen, for the company or (scope bar) one project: cash and bank today, owed to us and by
// us, this month's profit against last, the year by month, GST this month, TDS to deposit, the projects best first,
// and what needs the accountant. Every card opens the page behind it. Backend: GET /accounts/home.
// UXA-07 (asked 18 Nov: the rest of Accounts in the new style): the money position as a sum (cash + clients owe − you
// owe = if everyone paid today), each figure opening its page; "for your accountant" as a to-do card; this month
// against last with the year's bars; cash and bank with each account's share; GST and TDS as tinted figures; the
// projects as a table with margin bars; every book as a tile, since the tab row is gone from the Accounts pages.

const tiny = 0.005
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

const TONE = {
  plain: { card: 'bg-card', fg: 'text-foreground' },
  in: { card: 'border-emerald-500/30 bg-emerald-500/[0.06]', fg: 'text-emerald-700 dark:text-emerald-400' },
  out: { card: 'border-rose-500/30 bg-rose-500/[0.05]', fg: 'text-rose-700 dark:text-rose-400' },
  balance: { card: 'border-sky-500/30 bg-sky-500/[0.06]', fg: 'text-sky-700 dark:text-sky-400' },
} as const

/** A figure that opens its page, in a row of figures joined by operators. */
function Figure({ to, label, value, sub, tone, icon: Icon }: { to: string; label: string; value: string; sub?: React.ReactNode; tone: keyof typeof TONE; icon: LucideIcon }) {
  return (
    <Link to={to} className={cn('group min-w-0 flex-1 rounded-lg border px-3 py-2.5 transition-colors hover:brightness-95', TONE[tone].card)}>
      <p className={cn('flex items-center gap-1.5 truncate text-xs font-medium', tone === 'plain' ? 'text-muted-foreground' : TONE[tone].fg)}>
        <Icon className="size-3.5 shrink-0" /> {label}
        <ArrowRight className="ml-auto size-3 opacity-0 transition-opacity group-hover:opacity-100" />
      </p>
      <p className={cn('mt-0.5 truncate text-lg font-semibold tabular-nums sm:text-xl', TONE[tone].fg)}>{value}</p>
      {sub && <div className="mt-0.5 truncate text-[11px] text-muted-foreground">{sub}</div>}
    </Link>
  )
}

const Op = ({ s }: { s: string }) => (
  <span aria-hidden="true" className="hidden shrink-0 self-center px-0.5 text-lg font-light text-muted-foreground lg:block">
    {s}
  </span>
)

const BOOKS: { to: string; label: string; hint: string; icon: LucideIcon; tile: string }[] = [
  { to: '/accounts/pl', label: 'Profit & loss', hint: 'Income, costs, profit', icon: TrendingUp, tile: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400' },
  { to: '/accounts/balance-sheet', label: 'Balance sheet', hint: 'Own, owe, worth', icon: Scale, tile: 'bg-violet-500/10 text-violet-700 dark:text-violet-400' },
  { to: '/accounts/cash-bank', label: 'Cash & bank', hint: 'Every account, in and out', icon: Wallet, tile: 'bg-sky-500/10 text-sky-700 dark:text-sky-400' },
  { to: '/accounts/projects', label: 'Projects', hint: 'Profit per project', icon: FolderKanban, tile: 'bg-amber-500/10 text-amber-800 dark:text-amber-400' },
  { to: '/accounts/gst', label: 'GST', hint: 'Collected, claimed, to pay', icon: Percent, tile: 'bg-orange-500/10 text-orange-700 dark:text-orange-400' },
  { to: '/accounts/tds', label: 'TDS', hint: 'To deposit', icon: ReceiptIndianRupee, tile: 'bg-orange-500/10 text-orange-700 dark:text-orange-400' },
  { to: '/accounts/day-book', label: 'Day book', hint: 'Every voucher, day by day', icon: BookOpenText, tile: 'bg-muted text-muted-foreground' },
  { to: '/accounts/ledgers', label: 'Ledgers', hint: 'Every account', icon: BookOpen, tile: 'bg-muted text-muted-foreground' },
  { to: '/accounts/trial-balance', label: 'Trial balance', hint: 'Debits equal credits', icon: ScrollText, tile: 'bg-muted text-muted-foreground' },
  { to: '/accounts/chart', label: 'Chart of accounts', hint: 'Groups, as in Tally', icon: ListTree, tile: 'bg-muted text-muted-foreground' },
  { to: '/accounts/periods', label: 'Months', hint: 'Close a month', icon: CalendarCheck, tile: 'bg-muted text-muted-foreground' },
]

function Books() {
  return (
    <section data-guide="books.tabs" className="flex flex-col gap-2">
      <h2 className="px-1 text-base font-semibold">Every book</h2>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
        {BOOKS.map((b) => (
          <Link key={b.to} to={b.to} className="flex items-center gap-2.5 rounded-xl border bg-card px-3 py-2.5 shadow-xs transition-colors hover:bg-muted/40">
            <span className={cn('flex size-8 shrink-0 items-center justify-center rounded-lg', b.tile)}>
              <b.icon className="size-4" />
            </span>
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium">{b.label}</span>
              <span className="block truncate text-[11px] text-muted-foreground">{b.hint}</span>
            </span>
          </Link>
        ))}
      </div>
    </section>
  )
}

/** This month against last, with the year's bars. */
function ThisMonth({ d }: { d: Home }) {
  const tm = d.this_month
  const lm = d.last_month
  const np = Number(tm.net_profit)
  const costs = (t: typeof tm) => Number(t.direct) + Number(t.indirect)
  return (
    <section data-guide="acc.year" className="flex flex-col gap-3 rounded-xl border bg-card p-4 shadow-xs">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-medium text-muted-foreground">{np < 0 ? 'Loss' : 'Profit'} this month</p>
          <p className={cn('text-3xl font-semibold tabular-nums tracking-tight', np < -tiny ? 'text-destructive' : 'text-success')}>
            {np < -tiny && '−'}
            {rupees(np)}
          </p>
          <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            <Change now={np} before={Number(lm.net_profit)} goodWhenUp />
            <span>against {rupees(lm.net_profit)} last month</span>
          </p>
        </div>
        <div className="grid grid-cols-3 gap-2">
          {[
            { label: 'Income', now: Number(tm.income), before: Number(lm.income), good: true, fg: 'text-emerald-700 dark:text-emerald-400' },
            { label: 'Costs', now: costs(tm), before: costs(lm), good: false, fg: 'text-rose-700 dark:text-rose-400' },
          ].map((c) => (
            <div key={c.label} className="rounded-lg border px-3 py-1.5">
              <p className="text-[11px] text-muted-foreground">{c.label}</p>
              <p className={cn('text-sm font-semibold tabular-nums', c.fg)}>{short(c.now)}</p>
              <Change now={c.now} before={c.before} goodWhenUp={c.good} className="mt-0.5" />
            </div>
          ))}
          <div className="rounded-lg border px-3 py-1.5">
            <p className="text-[11px] text-muted-foreground">Gross margin</p>
            <p className="text-sm font-semibold tabular-nums">{tm.gross_margin === null ? '—' : pctText(tm.gross_margin)}</p>
            <p className="mt-0.5 text-[11px] text-muted-foreground">last {lm.gross_margin === null ? '—' : pctText(lm.gross_margin)}</p>
          </div>
        </div>
      </div>
      <div className="border-t pt-3">
        <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
          <p className="text-[13px] font-semibold">Year {d.financial_year}, month by month</p>
          <p className="text-xs text-muted-foreground tabular-nums">
            {rupees(d.year.net_profit)} {Number(d.year.net_profit) < 0 ? 'loss' : 'profit'} so far
          </p>
        </div>
        <YearChart months={d.months} />
      </div>
      <Link to="/accounts/pl?range=this_month" className="inline-flex w-fit items-center gap-1 text-xs font-medium text-primary-ink hover:underline">
        Profit & loss <ArrowRight className="size-3" />
      </Link>
    </section>
  )
}

function ProjectsTable({ d }: { d: Home }) {
  const top = Math.max(1, ...d.projects.map((p) => Math.abs(Number(p.profit))))
  return (
    <section data-guide="acc.projects" className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-2 px-1">
        <h2 className="text-base font-semibold">Projects this year, most profit first</h2>
        <Link to="/accounts/projects" className="inline-flex items-center gap-1 text-xs font-medium text-primary-ink hover:underline">
          Every project's P&L <ArrowRight className="size-3" />
        </Link>
      </div>
      {d.projects.length === 0 ? (
        <p className="rounded-xl border border-dashed bg-card px-4 py-6 text-sm text-muted-foreground">No project has income or cost in the books yet.</p>
      ) : (
        <div className="overflow-hidden rounded-xl border bg-card shadow-xs">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="border-b bg-muted text-xs text-muted-foreground">
                  <th className="px-3 py-2 text-left font-medium">Project</th>
                  <th className="px-3 py-2 text-right font-medium">Billed</th>
                  <th className="px-3 py-2 text-right font-medium">Cost</th>
                  <th className="px-3 py-2 text-right font-medium">Profit</th>
                  <th className="px-3 py-2 text-left font-medium">Margin</th>
                  <th className="px-3 py-2 text-right font-medium">Client owes</th>
                </tr>
              </thead>
              <tbody>
                {d.projects.map((p) => {
                  const profit = Number(p.profit)
                  return (
                    <tr key={p.project_id} className="border-t border-border/60 first:border-t-0 hover:bg-muted/30">
                      <td className="px-3 py-2.5">
                        <Link to={`/accounts/projects/${p.project_id}`} className="font-medium hover:underline">
                          {p.name}
                        </Link>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums">{rupees(p.billed)}</td>
                      <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums text-muted-foreground">{rupees(Number(p.cost) + Number(p.overheads))}</td>
                      <td className={cn('whitespace-nowrap px-3 py-2.5 text-right font-semibold tabular-nums', profit < -tiny ? 'text-destructive' : 'text-success')}>
                        {profit < -tiny && '−'}
                        {rupees(profit)}
                      </td>
                      <td className="px-3 py-2.5">
                        <span className="flex items-center gap-2">
                          <span className="h-1.5 w-20 overflow-hidden rounded-full bg-muted">
                            <span className={cn('block h-full rounded-full', profit < 0 ? 'bg-destructive' : 'bg-success')} style={{ width: `${(Math.abs(profit) / top) * 100}%` }} />
                          </span>
                          <span className="text-xs tabular-nums text-muted-foreground">{p.margin === null ? '—' : pctText(p.margin)}</span>
                        </span>
                      </td>
                      <td className={cn('whitespace-nowrap px-3 py-2.5 text-right tabular-nums', Number(p.receivable) > 0 ? 'text-draft' : 'text-muted-foreground')}>{Number(p.receivable) > 0 ? rupees(p.receivable) : '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
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

  const cash = Number(d?.cash_bank?.total ?? 0)
  const recv = Number(d?.receivable ?? 0)
  const pay = Number(d?.payable ?? 0)
  const ifPaid = cash + recv - pay
  const cashAll = Math.max(tiny, ...[(d?.cash_bank?.accounts ?? []).reduce((t, a) => t + Math.max(0, Number(a.closing)), 0)])
  const gst = Number(d?.gst_this_month?.payable ?? 0)

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader back={{ to: '/finance/money', label: 'Money' }} crumb="Accounts" title="Accounts" date={d ? `${d.financial_year} · ${formatDay(d.today)}` : undefined} />
      {!d ? (
        <Skeleton className="h-[32rem] rounded-xl" />
      ) : d.position ? (
        <>
          {(() => {
            const p = d.position
            const profit = Number(p.profit)
            return (
              <div data-guide="acc.stats" className="grid grid-cols-2 gap-2 rounded-xl border bg-card p-2 shadow-xs lg:flex lg:items-stretch">
                <Figure to={`/accounts/projects/${projectId}`} label="Billed to the client" value={rupees(p.billed)} tone="in" icon={ReceiptIndianRupee} />
                <Op s="−" />
                <Figure to={`/accounts/projects/${projectId}`} label="Cost booked" value={rupees(Number(p.cost) + Number(p.overheads))} tone="out" icon={Building2} sub={Number(p.overheads) ? `with ${short(p.overheads)} head-office share` : undefined} />
                <Op s="=" />
                <Figure to={`/accounts/projects/${projectId}`} label={profit < 0 ? 'Loss' : 'Profit'} value={(profit < -tiny ? '−' : '') + rupees(profit)} tone={profit < 0 ? 'out' : 'balance'} icon={TrendingUp} sub={p.margin ? `${pctText(p.margin)} of billing` : undefined} />
                <Figure to="/accounts/receivables" label="Client owes" value={rupees(p.receivable)} tone="plain" icon={Landmark} sub={`retention held ${short(p.retention_held_by_client)}`} />
              </div>
            )
          })()}
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
            <ThisMonth d={d} />
            <section className="flex flex-col gap-2 rounded-xl border bg-card p-4 shadow-xs">
              <p className="text-[13px] font-semibold">Project position, {formatDay(d.position.as_of)}</p>
              <dl className="flex flex-col divide-y text-sm">
                {[
                  ['Received from the client', d.position.received, 'text-emerald-700 dark:text-emerald-400'],
                  ['Retention held by the client', d.position.retention_held_by_client, ''],
                  ['TDS deducted by the client', d.position.tds_deducted_by_client, ''],
                  ['Advance received', d.position.advance_received, ''],
                  ['Owed to suppliers', d.position.owed_to_suppliers, 'text-draft'],
                  ['Paid out for the project', d.position.paid_out, 'text-rose-700 dark:text-rose-400'],
                ].map(([k, v, cls]) => (
                  <div key={k} className="flex justify-between gap-2 py-2">
                    <dt className="text-muted-foreground">{k}</dt>
                    <dd className={cn('tabular-nums', cls)}>{rupees(v)}</dd>
                  </div>
                ))}
              </dl>
              <Link to={`/accounts/projects/${projectId}`} className="inline-flex w-fit items-center gap-1 text-xs font-medium text-primary-ink hover:underline">
                The project's books <ArrowRight className="size-3" />
              </Link>
            </section>
          </div>
          <Books />
        </>
      ) : (
        <>
          <div data-guide="acc.stats" className="grid grid-cols-2 gap-2 rounded-xl border bg-card p-2 shadow-xs lg:flex lg:items-stretch">
            <Figure to="/accounts/cash-bank" label="Cash & bank today" value={(cash < -tiny ? '−' : '') + rupees(cash)} tone="balance" icon={Wallet} sub={`${d.cash_bank?.accounts.length ?? 0} accounts`} />
            <Op s="+" />
            <Figure to="/accounts/receivables" label="Clients owe you" value={rupees(recv)} tone="in" icon={Landmark} sub="RA bills not yet paid" />
            <Op s="−" />
            <Figure to="/finance/vendors" label="You owe suppliers and staff" value={rupees(pay)} tone="out" icon={Building2} sub="bills and wages not yet paid" />
            <Op s="=" />
            <Figure to="/accounts/balance-sheet" label="If everyone paid today" value={(ifPaid < -tiny ? '−' : '') + rupees(ifPaid)} tone="plain" icon={Scale} sub={ifPaid < 0 ? 'you would still be short' : 'left in hand'} />
          </div>

          {(d.attention ?? []).length > 0 && (
            <section className="flex flex-col gap-2 rounded-xl border border-draft/30 bg-draft-soft/40 p-4">
              <p className="flex items-center gap-2 text-sm font-semibold text-draft">
                <CircleAlert className="size-4" /> For your accountant <span className="rounded-full bg-draft-soft px-2 text-xs tabular-nums">{d.attention!.length}</span>
              </p>
              <ul className="grid gap-1.5 sm:grid-cols-2">
                {d.attention!.map((a) => (
                  <li key={a.key}>
                    <Link to={a.ledger_id ? `/accounts/ledgers/${a.ledger_id}` : a.to} className="flex items-center gap-2 rounded-lg border bg-card px-3 py-2 text-sm hover:bg-muted/40">
                      <span className="size-1.5 shrink-0 rounded-full bg-draft" />
                      <span className="min-w-0 flex-1">{a.words}</span>
                      {a.amount && <span className="shrink-0 font-medium tabular-nums">{rupees(a.amount)}</span>}
                      <ArrowRight className="size-3.5 shrink-0 text-muted-foreground" />
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
            <ThisMonth d={d} />
            <div className="flex flex-col gap-4">
              <section data-guide="acc.cash" className="flex flex-col gap-2 rounded-xl border bg-card p-4 shadow-xs">
                <div className="flex items-baseline justify-between gap-2">
                  <p className="text-[13px] font-semibold">Cash & bank today</p>
                  <p className="text-sm font-semibold tabular-nums text-sky-700 dark:text-sky-400">{rupees(cash)}</p>
                </div>
                <ul className="flex flex-col gap-2">
                  {(d.cash_bank?.accounts ?? []).map((a) => {
                    const v = Number(a.closing)
                    const isCash = /cash/i.test(a.group)
                    return (
                      <li key={a.ledger_id}>
                        <Link to={`/accounts/ledgers/${a.ledger_id}`} className="flex flex-col gap-1 rounded-md px-1 py-0.5 hover:bg-muted/40">
                          <span className="flex items-baseline justify-between gap-2 text-sm">
                            <span className="flex min-w-0 items-center gap-1.5">
                              {isCash ? <Wallet className="size-3.5 shrink-0 text-amber-600" /> : <Landmark className="size-3.5 shrink-0 text-sky-600" />}
                              <span className="truncate">{a.name}</span>
                            </span>
                            <span className={cn('shrink-0 tabular-nums', v < 0 && 'text-destructive')}>{rupees(v)}</span>
                          </span>
                          <span className="h-1 w-full overflow-hidden rounded-full bg-muted">
                            <span className={cn('block h-full rounded-full', isCash ? 'bg-amber-500' : 'bg-sky-500')} style={{ width: `${(Math.max(0, v) / cashAll) * 100}%` }} />
                          </span>
                        </Link>
                      </li>
                    )
                  })}
                </ul>
                <Link to="/accounts/cash-bank" className="inline-flex w-fit items-center gap-1 text-xs font-medium text-primary-ink hover:underline">
                  Cash & bank books <ArrowRight className="size-3" />
                </Link>
              </section>
              <div data-guide="acc.taxes" className="grid grid-cols-2 gap-2">
                <Link to="/accounts/gst?range=this_month" className={cn('rounded-xl border px-3 py-2.5 shadow-xs hover:brightness-95', gst < 0 ? 'border-emerald-500/30 bg-emerald-500/[0.06]' : 'border-orange-500/30 bg-orange-500/[0.06]')}>
                  <p className="text-xs text-muted-foreground">GST {gst < 0 ? 'credit' : 'to pay'} this month</p>
                  <p className={cn('text-lg font-semibold tabular-nums', gst < 0 ? 'text-emerald-700 dark:text-emerald-400' : 'text-orange-700 dark:text-orange-400')}>{rupees(gst)}</p>
                  <p className="text-[11px] text-muted-foreground tabular-nums">
                    collected {short(d.gst_this_month?.output ?? 0)} − claimed {short(d.gst_this_month?.input ?? 0)}
                  </p>
                </Link>
                <Link to="/accounts/tds" className="rounded-xl border border-orange-500/30 bg-orange-500/[0.06] px-3 py-2.5 shadow-xs hover:brightness-95">
                  <p className="text-xs text-muted-foreground">TDS to deposit</p>
                  <p className="text-lg font-semibold tabular-nums text-orange-700 dark:text-orange-400">{rupees(d.tds_to_deposit ?? 0)}</p>
                  <p className="text-[11px] text-muted-foreground">deducted from subcontractors</p>
                </Link>
              </div>
            </div>
          </div>

          <ProjectsTable d={d} />
          <Books />
        </>
      )}
    </div>
  )
}
