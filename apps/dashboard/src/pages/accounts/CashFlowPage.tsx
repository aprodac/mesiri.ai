import * as React from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import type { LucideIcon } from 'lucide-react'
import {
  ArrowDownLeft, ArrowUpRight, Banknote, CalendarClock, ChevronDown, ChevronRight, Hammer, HardHat, Landmark,
  ReceiptText, ShoppingCart, TrendingDown, TriangleAlert, Truck, Wallet,
} from 'lucide-react'
import { DprHeader, PageError, Segmented } from '@/components/dpr-page'
import { ActionButton, ActionChip, KpiStrip, NoAccess, NoteChip, Pill } from '@/components/page/page-kit'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { formatRupees, formatRupeesShort } from '@/lib/boq'
import { IN_KINDS, KIND_TITLE, KIND_WORD, OUT_KINDS, fetchCashFlow, sumWeeks, type FlowItem, type FlowKind, type WeekSum } from '@/lib/cash-flow'
import { mayManageMoney } from '@/lib/cost'
import { exportCsv } from '@/lib/export'
import { TONE } from '@/lib/list-kit'
import { usePageTitle } from '@/lib/page-title'
import { BOOKS_PEOPLE } from '@/lib/permissions'
import { useScope } from '@/lib/ScopeContext'
import { useUrlState } from '@/lib/url-state'
import { cn } from '@/lib/utils'

// ACC-18 / MP-06: what comes in and goes out in the coming weeks, from what is already recorded (client bills owed,
// supplier and subcontractor bills, deliveries not billed, open orders, wages), and the cash it leaves each week.
// Owner, admin and finance (the books' people). The figures first, the week it runs short as a to-do, one chart (in up,
// out down, the balance as a line), the kinds as switches, then the weeks as rows that open into their payments.

const KIND_ICON: Record<FlowKind, LucideIcon> = {
  client_bills: ReceiptText,
  to_bill: Hammer,
  supplier_bills: Landmark,
  delivered: Truck,
  orders: ShoppingCart,
  wages_due: HardHat,
  wages_ahead: CalendarClock,
}

const HORIZONS = [
  { value: '8', label: '8 weeks' },
  { value: '12', label: '12 weeks' },
  { value: '26', label: '6 months' },
]
const CLIENT_DAYS = [7, 15, 30, 45, 60, 90]
const SUPPLIER_DAYS = [0, 7, 15, 30, 45, 60]

const day = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
const money = (n: number) => formatRupeesShort(String(Math.round(n)))
const full = (n: number) => formatRupees(String(Math.round(n)))

export default function CashFlowPage() {
  const { me } = useAuth()
  const { scope } = useScope()
  const [params] = useSearchParams()
  usePageTitle('Cash flow')
  const allowed = mayManageMoney(me?.role)
  const projectId = scope.mode !== 'portfolio' ? scope.projectId : undefined

  // All of it in the address: the weeks shown, the assumptions, the kinds switched on, the week opened.
  const [horizon, setHorizon] = useUrlState<string>('weeks', '8')
  const [clientDays, setClientDays] = useUrlState<string>('client', '30')
  const [supplierDays, setSupplierDays] = useUrlState<string>('supplier', '30')
  const [kindsRaw, setKinds] = useUrlState<string>('kinds', '')
  const [openWeek, setOpenWeek] = useUrlState<string>('wk', '')

  const q = useQuery({
    queryKey: ['cash-flow', projectId ?? null, horizon, clientDays, supplierDays],
    queryFn: () => fetchCashFlow({ projectId, weeks: Number(horizon), clientDays: Number(clientDays), supplierDays: Number(supplierDays) }),
    enabled: allowed,
    placeholderData: (prev) => prev,
  })
  const cf = q.data
  const on = React.useMemo(() => new Set<FlowKind>((kindsRaw ? kindsRaw.split(',') : cf?.default_on ?? []) as FlowKind[]), [kindsRaw, cf?.default_on])
  const toggle = (k: FlowKind) => {
    const next = new Set(on)
    if (next.has(k)) next.delete(k)
    else next.add(k)
    const list = [...IN_KINDS, ...OUT_KINDS].filter((x) => next.has(x))
    const isDefault = cf && list.length === cf.default_on.length && list.every((x) => cf.default_on.includes(x))
    setKinds(isDefault ? '' : list.join(',') || 'none')
  }
  const sums = React.useMemo(() => (cf ? sumWeeks(cf, on) : null), [cf, on])

  if (!allowed) return <NoAccess roles={BOOKS_PEOPLE} />
  if (q.isError) return <PageError message="The cash flow could not be worked out." onRetry={() => q.refetch()} back={{ to: '/accounts', label: 'Accounts' }} />

  const header = (
    <DprHeader
      back={{ to: '/accounts', label: 'Accounts' }}
      crumb="Accounts"
      title="Cash flow"
      date={cf ? `From ${day(cf.as_of)}, week by week` : undefined}
      action={
        cf && (
          <ActionButton kind="export-excel" size="sm" onClick={() => exportItems(cf.items.filter((i) => on.has(i.kind)))} title="Every payment counted, as a CSV file (opens in Excel)">
            <span className="hidden sm:inline">Export</span>
          </ActionButton>
        )
      }
    />
  )
  if (!cf || !sums) {
    return (
      <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
        {header}
        <Skeleton className="h-24 rounded-xl" />
        <Skeleton className="h-64 rounded-xl" />
      </div>
    )
  }

  const totalIn = sums.weeks.reduce((t, w) => t + w.in, 0)
  const totalOut = sums.weeks.reduce((t, w) => t + w.out, 0)
  const withBalance = cf.opening !== null
  const lowest = withBalance ? sums.weeks.reduce((lo, w) => (w.balance! < lo.balance! ? w : lo), sums.weeks[0]) : null
  const short = withBalance ? sums.weeks.find((w) => (w.balance ?? 0) < 0) : undefined
  const overdueIn = cf.items.filter((i) => i.overdue && on.has(i.kind) && IN_KINDS.includes(i.kind)).reduce((t, i) => t + Number(i.amount), 0)
  const overdueOut = cf.items.filter((i) => i.overdue && on.has(i.kind) && OUT_KINDS.includes(i.kind)).reduce((t, i) => t + Number(i.amount), 0)
  const kindTotal = (k: FlowKind) => cf.items.filter((i) => i.kind === k && i.week !== null).reduce((t, i) => t + Number(i.amount), 0)
  const link = (set: Record<string, string>) => {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(set)) next.set(k, v)
    return `/accounts/cash-flow?${next}`
  }

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      {header}

      <KpiStrip
        guide="cashflow.stats"
        stats={[
          withBalance
            ? { label: 'Cash and bank today', icon: Wallet, value: money(Number(cf.opening)), tone: Number(cf.opening) < 0 ? 'bad' : 'default', hint: `${cf.accounts.length} ${cf.accounts.length === 1 ? 'account' : 'accounts'}`, to: '/accounts/cash-bank' }
            : { label: 'Net over these weeks', icon: Wallet, value: money(totalIn - totalOut), tone: totalIn - totalOut < 0 ? 'bad' : 'good', tag: 'This project' },
          { label: 'Coming in', icon: ArrowDownLeft, value: money(totalIn), tone: 'good', hint: overdueIn ? `${money(overdueIn)} overdue` : `in ${cf.horizon} weeks` },
          { label: 'Going out', icon: ArrowUpRight, value: money(totalOut), tone: totalOut > totalIn ? 'attention' : 'default', hint: overdueOut ? `${money(overdueOut)} overdue` : `in ${cf.horizon} weeks` },
          ...(lowest
            ? [{ label: 'Lowest point', icon: TrendingDown, value: money(lowest.balance!), tone: (lowest.balance! < 0 ? 'bad' : lowest.balance! < Number(cf.opening) * 0.25 ? 'attention' : 'good') as 'bad' | 'attention' | 'good', hint: `week of ${day(lowest.start)}` }]
            : []),
        ]}
      />

      {short ? (
        <ActionChip icon={TriangleAlert} tone="bad" to={link({ wk: short.start })} action="See that week">
          Cash runs short in the week of <span className="font-semibold">{day(short.start)}</span>: <span className="font-semibold tabular-nums">{money(-(short.balance ?? 0))}</span> short
        </ActionChip>
      ) : overdueIn > 0 ? (
        <ActionChip icon={ReceiptText} to="/accounts/receivables" action="Chase it">
          <span className="font-semibold tabular-nums">{money(overdueIn)}</span> from clients is past its expected day
        </ActionChip>
      ) : null}

      <section className="flex flex-col gap-3 rounded-xl border bg-card p-3" data-guide="cashflow.chart">
        <div className="flex flex-wrap items-center gap-2">
          <Segmented label="How far ahead" value={horizon} options={HORIZONS} onChange={setHorizon} />
          <span className="ml-auto flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground" data-guide="cashflow.assume">
            <DaysSelect label="Clients pay in" value={clientDays} options={CLIENT_DAYS} onChange={setClientDays} title="Days after an RA bill that the client usually pays" />
            <DaysSelect label="Suppliers with no credit set" value={supplierDays} options={SUPPLIER_DAYS} onChange={setSupplierDays} title="Credit days for a supplier with none on their page" />
          </span>
        </div>
        <FlowChart weeks={sums.weeks} opening={withBalance ? Number(cf.opening) : null} openWeek={openWeek} onPick={(s) => setOpenWeek(openWeek === s ? '' : s)} />
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-success" aria-hidden /> Coming in</span>
          <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-destructive/80" aria-hidden /> Going out</span>
          {withBalance && <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 rounded-full bg-foreground" aria-hidden /> Cash at the week's end</span>}
        </div>
      </section>

      {/* The kinds as switches: what is counted (the balance follows at once). */}
      <div className="flex flex-col gap-2 rounded-xl border bg-card p-3" data-guide="cashflow.kinds">
        <KindRow title="In" kinds={IN_KINDS} on={on} toggle={toggle} total={kindTotal} side="in" />
        <KindRow title="Out" kinds={OUT_KINDS} on={on} toggle={toggle} total={kindTotal} side="out" />
      </div>

      {!withBalance && (
        <div>
          <NoteChip icon={Banknote}>One project: its own money in and out, without the bank</NoteChip>
        </div>
      )}

      <div className="overflow-hidden rounded-xl border bg-card" data-guide="cashflow.weeks">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Week of</th>
              <th className="px-3 py-2 text-right font-medium">In</th>
              <th className="px-3 py-2 text-right font-medium">Out</th>
              <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">Net</th>
              {withBalance && <th className="px-3 py-2 text-right font-medium">Cash after</th>}
            </tr>
          </thead>
          <tbody className="divide-y">
            {sums.weeks.map((w, i) => (
              <WeekRow key={w.start} week={w} label={i === 0 ? `This week · ${day(w.start)}` : day(w.start)} open={openWeek === w.start} onToggle={() => setOpenWeek(openWeek === w.start ? '' : w.start)} withBalance={withBalance} opening={withBalance ? Number(cf.opening) : 0} />
            ))}
            {(sums.later.in > 0 || sums.later.out > 0) && (
              <WeekRow week={sums.later} label={`After ${day(sums.weeks[sums.weeks.length - 1].start)}`} open={openWeek === 'later'} onToggle={() => setOpenWeek(openWeek === 'later' ? '' : 'later')} withBalance={false} opening={0} later />
            )}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">≈ a guessed date (no credit days, no expected day, or an estimate)</p>
    </div>
  )
}

function exportItems(items: FlowItem[]) {
  exportCsv(
    'cash-flow.csv',
    ['Expected on', 'In or out', 'Kind', 'What', 'Who', 'Project', 'Amount', 'Overdue', 'Date guessed'],
    items.map((i) => [i.date, IN_KINDS.includes(i.kind) ? 'In' : 'Out', KIND_WORD[i.kind], i.title, i.who ?? '', i.project ?? '', i.amount, i.overdue ? 'yes' : '', i.assumed ? 'yes' : '']),
  )
}

function DaysSelect({ label, value, options, onChange, title }: { label: string; value: string; options: number[]; onChange: (v: string) => void; title: string }) {
  return (
    <label className="flex items-center gap-1.5" title={title}>
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)} className="h-7 rounded-md border bg-card px-1.5 text-xs font-medium text-foreground outline-none">
        {options.map((d) => <option key={d} value={d}>{d} days</option>)}
      </select>
    </label>
  )
}

function KindRow({ title, kinds, on, toggle, total, side }: { title: string; kinds: FlowKind[]; on: Set<FlowKind>; toggle: (k: FlowKind) => void; total: (k: FlowKind) => number; side: 'in' | 'out' }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className={cn('w-8 text-xs font-semibold', side === 'in' ? 'text-success' : 'text-destructive')}>{title}</span>
      {kinds.map((k) => {
        const Icon = KIND_ICON[k]
        const pressed = on.has(k)
        const n = total(k)
        if (pressed && !n) return null // nothing of this kind: no chip (switched off, it stays so it can come back)
        return (
          <button
            key={k}
            type="button"
            aria-pressed={pressed}
            onClick={() => toggle(k)}
            title={KIND_TITLE[k]}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition',
              pressed ? cn('font-semibold', side === 'in' ? 'border-success/40 bg-success-soft text-success' : 'border-destructive/30 bg-destructive/10 text-destructive') : 'border-dashed text-muted-foreground line-through decoration-muted-foreground/40 hover:border-foreground/40',
            )}
          >
            <Icon className="size-3.5" aria-hidden />
            {KIND_WORD[k]}
            <span className="tabular-nums">{n ? money(n) : '—'}</span>
          </button>
        )
      })}
    </div>
  )
}

/** In up (green), out down (red) from one zero line, and the cash at each week's end as a line: one rupee axis. */
function FlowChart({ weeks, opening, openWeek, onPick }: { weeks: WeekSum[]; opening: number | null; openWeek: string; onPick: (start: string) => void }) {
  const [hover, setHover] = React.useState<number | null>(null)
  const values = weeks.flatMap((w) => [w.in, -w.out, w.balance ?? 0])
  if (opening !== null) values.push(opening)
  const top = Math.max(0, ...values)
  const bottom = Math.min(0, ...values)
  const span = top - bottom || 1
  const y = (v: number) => ((top - v) / span) * 100 // % from the top
  const zero = y(0)
  const H = 200
  const points = opening === null ? '' : weeks.map((w, i) => `${((i + 0.5) / weeks.length) * 100},${y(w.balance ?? 0)}`).join(' ')
  const h = hover !== null ? weeks[hover] : null

  return (
    <div className="relative" onMouseLeave={() => setHover(null)}>
      <div className="relative" style={{ height: H }} role="img" aria-label={`Money in and out for ${weeks.length} weeks; the weeks are listed in the table below`}>
        {/* Zero line and the top value, recessive. */}
        <div className="absolute inset-x-0 border-t border-border" style={{ top: `${zero}%` }} aria-hidden />
        <span className="absolute top-0 left-0 text-[10px] text-muted-foreground tabular-nums" aria-hidden>{money(top)}</span>
        {bottom < 0 && <span className="absolute bottom-0 left-0 text-[10px] text-muted-foreground tabular-nums" aria-hidden>{money(bottom)}</span>}
        <div className="absolute inset-y-0 right-0 left-10 flex gap-[2px]">
          {weeks.map((w, i) => {
            const picked = openWeek === w.start
            return (
              <button
                key={w.start}
                type="button"
                className={cn('relative flex-1 rounded-sm transition-colors', (hover === i || picked) && 'bg-muted/60')}
                onMouseEnter={() => setHover(i)}
                onFocus={() => setHover(i)}
                onClick={() => onPick(w.start)}
                aria-label={`Week of ${day(w.start)}: ${full(w.in)} in, ${full(w.out)} out${w.balance !== null ? `, ${full(w.balance)} after` : ''}`}
              >
                {w.in > 0 && (
                  <span className="absolute left-1/2 w-[38%] max-w-7 -translate-x-[105%] rounded-t-[4px] bg-success" style={{ top: `${y(w.in)}%`, height: `${zero - y(w.in)}%` }} aria-hidden />
                )}
                {w.out > 0 && (
                  <span className="absolute left-1/2 w-[38%] max-w-7 translate-x-[5%] rounded-b-[4px] bg-destructive/80" style={{ top: `${zero}%`, height: `${y(-w.out) - zero}%` }} aria-hidden />
                )}
              </button>
            )
          })}
        </div>
        {opening !== null && (
          <div className="pointer-events-none absolute inset-y-0 right-0 left-10" aria-hidden>
            <svg className="size-full overflow-visible" viewBox="0 0 100 100" preserveAspectRatio="none">
              <polyline points={points} fill="none" className="stroke-foreground" strokeWidth={2} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
            </svg>
            {weeks.map((w, i) => (
              <span
                key={w.start}
                className={cn('absolute size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-card', (w.balance ?? 0) < 0 ? 'bg-destructive' : 'bg-foreground')}
                style={{ left: `${((i + 0.5) / weeks.length) * 100}%`, top: `${y(w.balance ?? 0)}%` }}
              />
            ))}
          </div>
        )}
        {h && hover !== null && (
          <div
            className="pointer-events-none absolute z-10 w-44 rounded-lg border bg-popover p-2 text-xs shadow-md"
            style={{ left: `clamp(0px, calc(2.5rem + (100% - 2.5rem) * ${(hover + 0.5) / weeks.length} - 5.5rem), calc(100% - 11rem))`, top: 4 }}
          >
            <p className="mb-1 font-semibold">Week of {day(h.start)}</p>
            <p className="flex justify-between"><span className="text-muted-foreground">In</span><span className="tabular-nums">{full(h.in)}</span></p>
            <p className="flex justify-between"><span className="text-muted-foreground">Out</span><span className="tabular-nums">{full(h.out)}</span></p>
            {h.balance !== null && <p className="mt-1 flex justify-between border-t pt-1 font-semibold"><span>Cash after</span><span className={cn('tabular-nums', h.balance < 0 && 'text-destructive')}>{full(h.balance)}</span></p>}
          </div>
        )}
      </div>
      <div className="mt-1 flex gap-[2px] pl-10 text-[10px] text-muted-foreground" aria-hidden>
        {weeks.map((w, i) => (
          <span key={w.start} className={cn('flex-1 truncate text-center', weeks.length > 12 && i % 2 === 1 && 'invisible')}>{i === 0 ? 'Now' : day(w.start)}</span>
        ))}
      </div>
    </div>
  )
}

function WeekRow({ week: w, label, open, onToggle, withBalance, opening, later }: { week: WeekSum; label: string; open: boolean; onToggle: () => void; withBalance: boolean; opening: number; later?: boolean }) {
  const Chevron = open ? ChevronDown : ChevronRight
  const tone = w.balance === null ? null : w.balance < 0 ? 'bad' : w.balance < opening * 0.25 ? 'attention' : null
  const byKind = React.useMemo(() => {
    const m = new Map<FlowKind, FlowItem[]>()
    for (const it of [...w.items].sort((a, b) => Number(b.amount) - Number(a.amount))) m.set(it.kind, [...(m.get(it.kind) ?? []), it])
    return [...m.entries()].sort(([a], [b]) => [...IN_KINDS, ...OUT_KINDS].indexOf(a) - [...IN_KINDS, ...OUT_KINDS].indexOf(b))
  }, [w.items])
  const empty = w.items.length === 0
  return (
    <>
      <tr className={cn(!empty && 'cursor-pointer hover:bg-muted/30', open && 'bg-muted/30', later && 'text-muted-foreground')} onClick={empty ? undefined : onToggle} id={`week-${w.start || 'later'}`}>
        <td className="relative px-3 py-2.5">
          {tone && <span className={cn('absolute top-2 bottom-2 left-0 w-1 rounded-full', TONE[tone].dot)} aria-hidden />}
          <span className="flex flex-wrap items-center gap-1.5 font-medium">
            {!empty ? <Chevron className="size-3.5 text-muted-foreground" aria-hidden /> : <span className="size-3.5" aria-hidden />}
            {label}
            {w.items.some((i) => i.overdue) && <Pill tone="attention" size="xs">overdue in it</Pill>}
          </span>
        </td>
        <td className="px-3 py-2.5 text-right whitespace-nowrap tabular-nums text-success" title={full(w.in)}>{w.in ? money(w.in) : '—'}</td>
        <td className="px-3 py-2.5 text-right whitespace-nowrap tabular-nums text-destructive" title={full(w.out)}>{w.out ? money(w.out) : '—'}</td>
        <td className={cn('hidden px-3 py-2.5 text-right tabular-nums sm:table-cell', w.net < 0 && 'text-destructive')} title={full(w.net)}>{w.in || w.out ? money(w.net) : '—'}</td>
        {withBalance && (
          <td className={cn('px-3 py-2.5 text-right font-semibold whitespace-nowrap tabular-nums', tone && TONE[tone].text)} title={w.balance !== null ? full(w.balance) : undefined}>
            {w.balance !== null ? money(w.balance) : ''}
          </td>
        )}
      </tr>
      {open && (
        <tr className="bg-muted/20">
          <td colSpan={withBalance ? 5 : 4} className="px-3 py-2">
            <div className="flex flex-col gap-3 py-1">
              {byKind.map(([k, items]) => {
                const Icon = KIND_ICON[k]
                const inSide = IN_KINDS.includes(k)
                return (
                  <div key={k}>
                    <p className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
                      <Icon className="size-3.5" aria-hidden /> {KIND_WORD[k]}
                      <span className="tabular-nums">· {money(items.reduce((t, i) => t + Number(i.amount), 0))}</span>
                    </p>
                    <ul className="flex flex-col divide-y rounded-lg border bg-card">
                      {items.map((it, n) => (
                        <li key={`${it.title}-${n}`}>
                          <Link to={it.link} className="flex items-center gap-2 px-3 py-1.5 text-sm hover:bg-muted/40">
                            <span className="min-w-0 flex-1">
                              <span className="block truncate">{it.who ? <span className="font-medium">{it.who} · </span> : null}{it.title}</span>
                              <span className="block text-[11px] text-muted-foreground">
                                {it.assumed && <span title="A guessed date">≈ </span>}{day(it.date)}{it.project ? ` · ${it.project}` : ''}
                              </span>
                            </span>
                            {it.overdue && <Pill tone="attention" size="xs">overdue</Pill>}
                            <span className={cn('shrink-0 font-semibold tabular-nums', inSide ? 'text-success' : 'text-destructive')} title={full(Number(it.amount))}>
                              {inSide ? '+' : '−'}{money(Number(it.amount))}
                            </span>
                          </Link>
                        </li>
                      ))}
                    </ul>
                  </div>
                )
              })}
            </div>
          </td>
        </tr>
      )}
    </>
  )
}
