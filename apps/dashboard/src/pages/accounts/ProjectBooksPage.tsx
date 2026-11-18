import * as React from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, ChevronDown, ChevronRight, Gauge, HandCoins, PieChart, Receipt, Scale, TrendingUp } from 'lucide-react'
import { BooksClosed, PeriodBar, usePeriod } from '@/components/accounts/books'
import { FlowStrip } from '@/components/accounts/money-kit'
import { PlSimple } from '@/components/accounts/pl-simple'
import { PlTwoColumn } from '@/components/accounts/pl-two-column'
import { PartsBar, SplitBars, pctText } from '@/components/accounts/visuals'
import { DprHeader, DprSection, PageError, Segmented } from '@/components/dpr-page'
import { Hint } from '@/components/hint'
import { Legend } from '@/components/page/page-kit'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { fetchProjectBooks, formatDay, mayReadProjectBooks, rupees, short, type Position } from '@/lib/accounts'
import { maySeeBoq } from '@/lib/boq'
import { useBooksView } from '@/lib/books-view'
import { fetchPortfolio } from '@/lib/cost'
import { usePageTitle } from '@/lib/page-title'
import { HEALTH_LOOK, healthOf, realView, type RealView } from '@/lib/project-health'
import { cn } from '@/lib/utils'

// ACC-08 (plan §5.8): one project's books: its position (billed, received, owed, held back, owed to others), its P&L
// by group and cost centre, its months, and Cost control's BOQ budget and forecast beside the books. The project's
// manager sees it too. Backend: GET /accounts/projects/{id}.
// UXA-07: the period as a sum; the P&L as on Profit & loss, Simple or Tally (lib/books-view.ts).
// UX-57 (asked 18 Nov 2026): the books' profit is never read alone. The sum splits cost into direct (site) and
// indirect (office, with the head-office share); "Books or real" puts the books' margin beside the real margin so far
// (Cost control's full cost) and the finish against the BOQ budget as one bar with the work done marked; the header
// carries the project's health and how much is built; the position is two bars (with the client, with others); the
// months show billed against cost. State tokens only.

const VIEWS = ['simple', 'statement'] as const

const CENTRE: Record<string, string> = {
  materials: 'Materials',
  labour: 'Labour',
  subcontract: 'Subcontract',
  equipment: 'Machines',
  overheads: 'Site overheads',
  not_set: 'No cost centre',
}

/** A whole split into parts as one bar, each part named under it with its amount. */
function SplitBar({ parts }: { parts: { label: string; v: number; cls: string; strong?: boolean }[] }) {
  const whole = parts.reduce((t, p) => t + Math.max(0, p.v), 0)
  return (
    <div className="flex flex-col gap-2">
      <span className="flex h-2.5 overflow-hidden rounded-full bg-muted" role="img" aria-label={parts.map((p) => `${p.label} ${rupees(p.v)}`).join(', ')}>
        {whole > 0 && parts.map((p) => p.v > 0 && <span key={p.label} className={p.cls} style={{ width: `${(p.v / whole) * 100}%` }} />)}
      </span>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-sm sm:grid-cols-3">
        {parts.map((p) => (
          <div key={p.label} className="flex flex-col">
            <dt className="flex items-center gap-1.5 text-xs text-muted-foreground"><span className={cn('size-2 rounded-full', p.cls)} aria-hidden /> {p.label}</dt>
            <dd className={cn('tabular-nums', p.strong && 'font-semibold')}>{rupees(p.v)}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

function PositionCards({ p }: { p: Position }) {
  const receivable = Number(p.receivable)
  const retention = Number(p.retention_held_by_client)
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <div className="flex flex-col gap-3 rounded-xl border bg-card p-3 shadow-xs">
        <p className="flex items-center justify-between text-xs font-semibold">
          <span className="text-success">With the client</span>
          <span className="font-normal text-muted-foreground tabular-nums">billed {short(p.billed)} + GST {short(p.gst_billed)}</span>
        </p>
        <SplitBar
          parts={[
            { label: 'Received', v: Number(p.received), cls: 'bg-success' },
            { label: 'Still owed', v: Math.max(0, receivable - retention), cls: 'bg-draft', strong: true },
            { label: 'Retention held', v: retention, cls: 'bg-draft/40' },
          ]}
        />
        {(Number(p.tds_deducted_by_client) !== 0 || Number(p.advance_received) !== 0) && (
          <p className="flex flex-wrap gap-1.5 text-[11px]">
            {Number(p.tds_deducted_by_client) !== 0 && <span className="rounded-full bg-info-soft px-2 py-0.5 text-info" title="Claim it in the return">TDS deducted {short(p.tds_deducted_by_client)}</span>}
            {Number(p.advance_received) !== 0 && <span className="rounded-full bg-muted px-2 py-0.5">Advance not recovered {short(p.advance_received)}</span>}
          </p>
        )}
      </div>
      <div className="flex flex-col gap-3 rounded-xl border bg-card p-3 shadow-xs">
        <p className="flex items-center justify-between text-xs font-semibold">
          <span className="text-destructive">With others</span>
          <span className="font-normal text-muted-foreground tabular-nums">cost booked {short(p.cost)}</span>
        </p>
        <SplitBar
          parts={[
            { label: 'Paid out', v: Number(p.paid_out), cls: 'bg-muted-foreground/50' },
            { label: 'Owed to suppliers', v: Number(p.owed_to_suppliers), cls: 'bg-destructive', strong: true },
            ...(Number(p.owed_to_staff) ? [{ label: 'Owed to staff', v: Number(p.owed_to_staff), cls: 'bg-destructive/40' }] : []),
          ]}
        />
        <p className="flex items-center justify-between border-t pt-2 text-xs">
          <span className="text-muted-foreground">Cash: received − paid out</span>
          <span className={cn('font-semibold tabular-nums', Number(p.cash_in_hand) < 0 ? 'text-destructive' : 'text-foreground')}>{rupees(p.cash_in_hand)}</span>
        </p>
      </div>
    </div>
  )
}

function MarginTile({ label, v, sub, hint }: { label: string; v: number | null; sub: string; hint: React.ReactNode }) {
  const cls = v === null ? 'text-muted-foreground' : v < 0 ? 'text-destructive' : v < 10 ? 'text-draft' : 'text-success'
  return (
    <div className="flex flex-col gap-0.5 rounded-lg border bg-card px-3 py-2.5">
      <span className="flex items-center gap-1 text-xs text-muted-foreground">{label} {hint}</span>
      <span className={cn('text-2xl font-semibold tabular-nums', cls)}>{v === null ? '—' : pctText(v)}</span>
      <span className="truncate text-[11px] text-muted-foreground">{sub}</span>
    </div>
  )
}

/** Books or real: the two margins side by side, and the finish against the BOQ budget with the work done marked. */
function BooksOrReal({ booksMargin, booksSub, real, projectId }: { booksMargin: number | null; booksSub: string; real: RealView; projectId: string }) {
  const gap = booksMargin !== null && real.margin !== null ? booksMargin - real.margin : null
  const whole = real.budget !== null && real.forecast !== null ? Math.max(real.budget, real.forecast, real.spent) : 0
  const over = real.over !== null ? Math.max(0, real.over) : 0
  const pct = (v: number) => `${whole ? (v / whole) * 100 : 0}%`
  return (
    <div className="grid gap-4 rounded-xl border bg-card p-4 shadow-xs lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <div className="flex flex-col gap-2">
        <div className="grid grid-cols-2 gap-2">
          <MarginTile label="Books margin" v={booksMargin} sub={booksSub} hint={<Hint title="Books margin" text="Billed less the cost booked in the accounts in the period. Deliveries not yet billed by the supplier and wages not yet paid are not in it yet." />} />
          <MarginTile label="Real margin" v={real.margin} sub={`to date · cost ${short(real.spent)}`} hint={<Hint title="Real margin, to date" text="Billed so far less Cost control's full cost so far: every delivery, attendance and bill, billed or not." />} />
        </div>
        {gap !== null && gap > 15 && (
          <p className="rounded-lg bg-draft-soft px-2.5 py-1.5 text-xs text-draft">
            <span className="font-semibold">Books look {Math.round(gap)} points better</span> · deliveries and wages not billed yet
          </p>
        )}
      </div>
      {whole > 0 && (
        <div className="flex flex-col justify-center gap-2">
          <span className="flex items-center justify-between text-xs text-muted-foreground">
            <span className="flex items-center gap-1">Finish against the BOQ budget <Hint title="Finish against the budget" text="Cost control's forecast at completion: spent + committed + the work still to do at its rate so far. The grey line is the budget; red is how far past it the job is heading; the dark tick is the work built so far." /></span>
            {real.done !== null && <span className="font-semibold text-foreground">{real.done}% built</span>}
          </span>
          <span className="relative flex h-4 overflow-hidden rounded-md bg-muted">
            <span className="bg-foreground/30" style={{ width: pct(Math.min(real.spent, real.budget ?? 0)) }} title={`Spent ${rupees(real.spent)}`} />
            <span className="bg-foreground/10" style={{ width: pct(Math.max(0, Math.min(real.forecast ?? 0, real.budget ?? 0) - real.spent)) }} />
            {over > 0 && <span className="bg-destructive" style={{ width: pct(over) }} title={`${rupees(over)} over`} />}
            {real.budget !== null && <span className="absolute inset-y-0 w-0.5 bg-foreground/60" style={{ left: pct(real.budget) }} />}
            {real.done !== null && real.budget !== null && <span className="absolute -inset-y-0.5 w-1 rounded bg-foreground" style={{ left: `calc(${pct((real.done / 100) * real.budget)} - 2px)` }} title={`${real.done}% built`} />}
          </span>
          <span className="flex flex-wrap items-center justify-between gap-2 text-xs tabular-nums">
            <span className="text-muted-foreground">Spent {short(real.spent)} · budget {short(real.budget ?? 0)} · forecast {short(real.forecast ?? 0)}</span>
            <span className={cn('rounded-full px-2 py-0.5 font-semibold', over > 0 ? 'bg-destructive/10 text-destructive' : 'bg-success-soft text-success')}>
              {over > 0 ? `${short(over)} over (${pctText(real.overPct)})` : 'Within budget'}
            </span>
          </span>
          <Legend items={[{ tone: 'default', label: 'Spent' }, { tone: 'bad', label: 'Over budget' }]} />
          <Link to={`/cost/budget?project=${projectId}`} className="inline-flex w-fit items-center gap-1 text-xs font-medium hover:underline">
            Budget vs actual <ArrowRight className="size-3" aria-hidden />
          </Link>
        </div>
      )}
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
  // UX-58: the line-by-line P&L is folded; a figure in the sum opens it at its part.
  const [lines, setLines] = React.useState(false)
  const [focusOn, setFocusOn] = React.useState<{ key: string; n: number } | null>(null)
  const linesRef = React.useRef<HTMLElement>(null)
  const openLines = (key?: string) => {
    setLines(true)
    if (key && view === 'simple') setFocusOn((f) => ({ key, n: (f?.n ?? 0) + 1 }))
    else window.setTimeout(() => linesRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
  }
  const q = useQuery({ queryKey: ['accounts', 'project', id, period], queryFn: () => fetchProjectBooks(id, period), enabled: allowed && !!id })
  const port = useQuery({ queryKey: ['cost', 'portfolio'], queryFn: fetchPortfolio, enabled: allowed && maySeeBoq(me?.role), retry: false })
  const name = q.data?.scope.replace(/^project /, '')
  usePageTitle(name ? `${name}: books` : 'Project books')
  if (!allowed) return <BooksClosed />
  if (q.isError) return <PageError message="This project's books could not be loaded." onRetry={() => q.refetch()} back={{ to: '/accounts/projects', label: 'Projects' }} />
  const d = q.data
  const p = d?.position
  const t = d?.pl.totals
  const np = Number(t?.net_profit ?? 0)
  const real = d && p ? realView(Number(p.billed), port.data?.projects.find((r) => r.project_id === d.project_id)) : null
  const health = d ? healthOf(real, np) : null

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader
        back={{ to: '/accounts/projects', label: 'Projects' }}
        crumb="Accounts · Projects"
        title={name ?? 'Project'}
        chip={
          health && real && (
            <span className="flex items-center gap-1.5">
              <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold', HEALTH_LOOK[health.health].pill)}>
                <span className={cn('size-1.5 rounded-full', HEALTH_LOOK[health.health].dot)} aria-hidden /> {health.why}
              </span>
              {real.done !== null && (
                <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs font-medium"><Gauge className="size-3" aria-hidden /> {real.done}% built</span>
              )}
            </span>
          )
        }
        action={<PeriodBar state={periodState} />}
      />
      {!d || !p || !t ? (
        <Skeleton className="h-[32rem] rounded-xl" />
      ) : (
        <>
          <FlowStrip
            items={[
              { label: 'Billed', value: rupees(t.income), tone: 'in', sub: 'RA bills, before GST', onClick: () => openLines('income'), title: 'Open the bills' },
              { label: 'Direct cost', value: rupees(t.direct), tone: 'out', op: '−', sub: 'site: materials, labour, subcontract', onClick: () => openLines('direct'), title: 'Open the site costs' },
              {
                label: 'Indirect cost',
                value: rupees(t.indirect),
                tone: Number(t.indirect) ? 'out' : 'plain',
                op: '−',
                sub: Number(d.pl.overheads) ? `with ${short(d.pl.overheads)} head-office share` : 'office costs on this project',
                onClick: Number(t.indirect) ? () => openLines('indirect') : undefined,
                title: 'Open the office costs',
              },
              { label: np < 0 ? 'Loss (books)' : 'Profit (books)', value: (np < 0 ? '−' : '') + rupees(np), tone: np < 0 ? 'out' : 'balance', op: '=', sub: t.net_margin ? `${pctText(t.net_margin)} of billing` : undefined, onClick: () => openLines(), title: 'Line by line' },
            ]}
          />

          {real && (
            <DprSection icon={Scale} title="Books or real">
              <BooksOrReal booksMargin={t.net_margin === null ? null : Number(t.net_margin)} booksSub={`${formatDay(d.date_from)} – ${formatDay(d.date_to)}`} real={real} projectId={d.project_id} />
            </DprSection>
          )}

          <div className="grid gap-4 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
            <DprSection icon={HandCoins} title="Position today">
              <PositionCards p={p} />
            </DprSection>
            {d.centres.length > 0 && (
              <DprSection icon={PieChart} title="Where the cost went (period)">
                <div className="rounded-xl border bg-card p-3 shadow-xs">
                  <PartsBar parts={d.centres.map((c) => ({ label: CENTRE[c.cost_centre] ?? c.cost_centre, value: Number(c.amount) }))} />
                </div>
              </DprSection>
            )}
          </div>

          {/* UX-58: the proof, folded: the sum at the top already says the totals. */}
          <section ref={linesRef} className="scroll-mt-20 overflow-hidden rounded-xl border bg-card shadow-xs" aria-label="Line by line">
            <div className="flex flex-wrap items-center gap-2 px-3 py-2.5">
              <button type="button" onClick={() => (lines ? setLines(false) : openLines())} aria-expanded={lines} className="flex min-w-0 flex-1 items-center gap-2 text-left">
                {lines ? <ChevronDown className="size-4 shrink-0" aria-hidden /> : <ChevronRight className="size-4 shrink-0" aria-hidden />}
                <Receipt className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                <span className="font-semibold">Line by line</span>
                <span className="truncate text-xs text-muted-foreground">every bill and expense, {formatDay(d.date_from)} – {formatDay(d.date_to)}</span>
              </button>
              {lines && (
                <Segmented<(typeof VIEWS)[number]>
                  label="Show as"
                  value={view}
                  options={[
                    { value: 'simple', label: 'Simple' },
                    { value: 'statement', label: 'Tally' },
                  ]}
                  onChange={pickView}
                />
              )}
            </div>
            {lines && (
              <div className="border-t p-3">
                {view === 'simple' ? (
                  <PlSimple pl={d.pl} period={period} scope={{ project_id: d.project_id }} company={false} hero={false} focusOn={focusOn} periodLabel={`${formatDay(d.date_from)} – ${formatDay(d.date_to)}`} />
                ) : (
                  <PlTwoColumn pl={d.pl} periodLabel={`${formatDay(d.date_from)} – ${formatDay(d.date_to)}`} />
                )}
              </div>
            )}
          </section>
          {d.months.some((m) => Number(m.income) || Number(m.cost)) && (
            <DprSection icon={TrendingUp} title="This year, month by month">
              <div className="rounded-xl border bg-card px-4 py-3 shadow-xs">
                <SplitBars
                  up="Billed"
                  down="Cost"
                  upClass="fill-success"
                  downClass="fill-destructive"
                  items={d.months.map((m) => ({
                    key: m.month,
                    label: new Date(`${m.month}-01T00:00:00`).toLocaleDateString('en-IN', { month: 'short' }),
                    up: Math.max(0, Number(m.income)),
                    down: Math.max(0, Number(m.cost)),
                    detail: (
                      <>
                        {new Date(`${m.month}-01T00:00:00`).toLocaleDateString('en-IN', { month: 'long' })}: billed {short(m.income)}, cost {short(m.cost)},{' '}
                        <span className={Number(m.profit) < 0 ? 'text-destructive' : 'text-success'}>{Number(m.profit) < 0 ? 'loss' : 'profit'} {short(Math.abs(Number(m.profit)))}</span>
                      </>
                    ),
                  }))}
                />
              </div>
            </DprSection>
          )}
        </>
      )}
    </div>
  )
}
