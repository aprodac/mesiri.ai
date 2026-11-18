import * as React from 'react'
import { useSearchParams } from 'react-router-dom'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ArrowDownLeft, ArrowRight, ArrowUpRight, BookOpenText, History, Plus, Search } from 'lucide-react'
import { BooksClosed, ExcelButton, PeriodBar, VoucherSheet, usePeriod } from '@/components/accounts/books'
import { FlowStrip } from '@/components/accounts/money-kit'
import { VOUCHER_LOOK, VoucherBadge } from '@/components/accounts/visuals'
import { NewVoucherDialog } from '@/components/accounts/new-voucher-dialog'
import { DprHeader, PageError } from '@/components/dpr-page'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { useScope } from '@/lib/ScopeContext'
import { VOUCHER_LABEL, fetchDayBook, mayReadBooks, rupees, scopeParams, type Entry, type VoucherType } from '@/lib/accounts'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'

// ACC-05: every voucher of a period, day by day, as the accountant reads a day book: what it was, the ledgers it
// moved, the amount. Filter by kind, search a party or a number, see what changed after a month was closed. ↑ ↓ to
// move, Enter to open. Backend: GET /accounts/day-book.
// UX-34 (Mercon's journal as the reference): the kinds as coloured tabs (with their counts when the whole period is
// loaded); the period's money in and out as figures; then one table, as an accountant reads a day book: a band per
// day (its money in and out), a row per voucher with a stripe in its kind's colour, its badge and number, the debit
// ledgers (amber) and credit ledgers (blue) in their own columns, the project and the amount (receipts green,
// payments rose); the total at the foot (UX-44, asked: "it should be a table, a ledger table is easier").

const TYPES: (VoucherType | '')[] = ['', 'purchase', 'payment', 'receipt', 'sales', 'contra', 'journal']
const PAGE = 200

/** A voucher's row accent and its amount's colour, by kind (the chips in visuals.tsx). */
const KIND_ACCENT: Record<VoucherType, { bar: string; amount: string }> = {
  receipt: { bar: 'bg-emerald-500', amount: 'text-emerald-700 dark:text-emerald-400' },
  payment: { bar: 'bg-rose-500', amount: 'text-rose-700 dark:text-rose-400' },
  purchase: { bar: 'bg-amber-500', amount: '' },
  sales: { bar: 'bg-sky-500', amount: '' },
  contra: { bar: 'bg-violet-500', amount: '' },
  journal: { bar: 'bg-muted-foreground/40', amount: '' },
}

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = React.useState(value)
  React.useEffect(() => {
    const id = setTimeout(() => setV(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return v
}

/** Debit ledgers → credit ledgers, as chips with an arrow. */
function Flow({ e }: { e: Entry }) {
  const dr = e.lines.filter((l) => Number(l.debit) > 0).map((l) => l.ledger)
  const cr = e.lines.filter((l) => Number(l.credit) > 0).map((l) => l.ledger)
  const chip = (names: string[], cls: string) => (
    <span className={cn('inline-flex max-w-[16rem] items-center truncate rounded px-1.5 py-px text-[11px] font-medium', cls)} title={names.join(', ')}>
      <span className="truncate">{names.join(', ')}</span>
    </span>
  )
  return (
    <span className="flex min-w-0 items-center gap-1">
      {chip(dr, 'bg-draft-soft text-draft')}
      <ArrowRight className="size-3 shrink-0 text-muted-foreground" aria-label="from" />
      {chip(cr, 'bg-info-soft text-info')}
    </span>
  )
}

function summary(e: Entry): string {
  const dr = e.lines.filter((l) => Number(l.debit) > 0).map((l) => l.ledger)
  const cr = e.lines.filter((l) => Number(l.credit) > 0).map((l) => l.ledger)
  return `${dr.join(', ')} → ${cr.join(', ')}`
}

/** A day's money in (receipts) and out (payments), each with its arrow; the rest is counted. */
function DayMoney({ list }: { list: Entry[] }) {
  const sum = (t: VoucherType) => list.filter((e) => e.voucher_type === t).reduce((s, e) => s + Number(e.amount), 0)
  const got = sum('receipt')
  const paid = sum('payment')
  return (
    <span className="flex flex-wrap items-center justify-end gap-x-3 text-xs text-muted-foreground tabular-nums">
      {got > 0 && (
        <span className="inline-flex items-center gap-0.5">
          <ArrowDownLeft className="size-3.5 text-success" /> in {rupees(got)}
        </span>
      )}
      {paid > 0 && (
        <span className="inline-flex items-center gap-0.5">
          <ArrowUpRight className="size-3.5 text-destructive" /> out {rupees(paid)}
        </span>
      )}
      <span>
        {list.length} voucher{list.length === 1 ? '' : 's'}
      </span>
    </span>
  )
}

export default function DayBookPage() {
  usePageTitle('Day book')
  const { me } = useAuth()
  const { scope } = useScope()
  const periodState = usePeriod('this_month')
  const { period } = periodState
  const [params, setParams] = useSearchParams()
  const type = (params.get('type') ?? '') as VoucherType | ''
  const late = params.get('late') === '1'
  const [q, setQ] = React.useState(params.get('q') ?? '')
  const search = useDebounced(q)
  const [limit, setLimit] = React.useState(PAGE)
  const [openId, setOpenId] = React.useState<string | null>(null)
  const [cursor, setCursor] = React.useState(-1)
  const [writing, setWriting] = React.useState(false)  // ACC-12
  const sp = scopeParams(scope)
  const allowed = mayReadBooks(me?.role)
  const filter = { ...period, ...sp, voucher_type: type, q: search, after_close: late, limit }
  const book = useQuery({ queryKey: ['accounts', 'day-book', filter], queryFn: () => fetchDayBook(filter), enabled: allowed, placeholderData: keepPreviousData })

  const setParam = (k: string, v: string | null) =>
    setParams(
      (p) => {
        const n = new URLSearchParams(p)
        if (v) n.set(k, v)
        else n.delete(k)
        return n
      },
      { replace: true },
    )
  const entries = React.useMemo(() => book.data?.entries ?? [], [book.data])
  const days = React.useMemo(() => {
    const m = new Map<string, Entry[]>()
    for (const e of entries) m.set(e.date, [...(m.get(e.date) ?? []), e])
    return [...m.entries()]
  }, [entries])

  // Keyboard: ↑ ↓ move through the vouchers, Enter opens one (not while typing in a field). Read through refs, so a
  // key pressed right after another sees the selection it made.
  const live = React.useRef({ entries, cursor, openId })
  live.current = { entries, cursor, openId }
  React.useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      const tag = (ev.target as HTMLElement | null)?.tagName
      const now = live.current
      if (now.openId || tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
        ev.preventDefault()
        const next = Math.max(0, Math.min(now.entries.length - 1, now.cursor + (ev.key === 'ArrowDown' ? 1 : -1)))
        live.current = { ...now, cursor: next }
        setCursor(next)
      } else if (ev.key === 'Enter' && now.cursor >= 0 && now.entries[now.cursor]) {
        ev.preventDefault()
        setOpenId(now.entries[now.cursor].id)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  React.useEffect(() => {
    if (cursor >= 0) document.getElementById(`voucher-${cursor}`)?.scrollIntoView({ block: 'nearest' })
  }, [cursor])

  if (!allowed) return <BooksClosed />
  if (book.isError) return <PageError message="The day book could not be loaded." onRetry={() => book.refetch()} back={{ to: '/accounts/trial-balance', label: 'Trial balance' }} />
  const d = book.data
  let index = -1
  // With the whole period loaded (no kind picked), the counts per kind and money in and out add up exactly
  const complete = !!d && d.count === entries.length
  const moneyIn = entries.filter((e) => e.voucher_type === 'receipt').reduce((t, e) => t + Number(e.amount), 0)
  const moneyOut = entries.filter((e) => e.voucher_type === 'payment').reduce((t, e) => t + Number(e.amount), 0)
  const counts =
    complete && !type
      ? new Map<VoucherType | '', number>([['', entries.length], ...TYPES.filter(Boolean).map((t) => [t, entries.filter((e) => e.voucher_type === t).length] as [VoucherType, number])])
      : null

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader
        back={{ to: '/accounts/trial-balance', label: 'Trial balance' }}
        crumb="Accounts"
        title="Day book"
        action={
          <div className="flex items-center gap-2">
            <ExcelButton path="/accounts/day-book/export" params={{ ...period, ...sp, voucher_type: type, q: search }} name={`day-book-${period.date_from}-to-${period.date_to}`} />
            <Button data-guide="daybook.new" size="sm" className="gap-1.5" onClick={() => setWriting(true)}><Plus className="size-3.5" /> New voucher</Button>
          </div>
        }
      />
      <PeriodBar state={periodState} />
      <div className="flex flex-wrap items-center gap-2">
        <div data-guide="daybook.types" role="tablist" aria-label="Kind of voucher" className="flex max-w-full gap-1 overflow-x-auto rounded-xl border bg-card p-1 shadow-xs">
          {TYPES.map((t) => {
            const Icon = t ? VOUCHER_LOOK[t].icon : BookOpenText
            const n = counts?.get(t)
            return (
              <button
                key={t || 'all'}
                type="button"
                role="tab"
                aria-selected={type === t}
                onClick={() => setParam('type', t || null)}
                className={cn('inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-2.5 text-xs font-medium', type === t ? (t ? VOUCHER_LOOK[t].chip : 'bg-foreground text-background') : 'text-muted-foreground hover:bg-muted hover:text-foreground')}
              >
                <Icon className="size-3.5" /> {t ? VOUCHER_LABEL[t] : 'All'}
                {n !== undefined && <span className="tabular-nums opacity-70">{n}</span>}
              </button>
            )
          })}
        </div>
        <div className="relative w-full sm:w-64">
          <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Party, ledger, words or number" className="h-9 bg-card pl-8" aria-label="Search the day book" />
        </div>
        <Button data-guide="daybook.late" size="sm" variant={late ? 'default' : 'outline'} className="gap-1.5" onClick={() => setParam('late', late ? null : '1')}>
          <History className="size-3.5" /> Changed after close
        </Button>
      </div>
      {!d ? (
        <Skeleton className="h-96 rounded-xl" />
      ) : (
        <>
          <FlowStrip
            guide="daybook.stats"
            items={[
              { label: 'Vouchers', value: String(d.count), tone: 'plain', sub: `${days.length} ${days.length === 1 ? 'day' : 'days'} with entries` },
              { label: 'Total moved', value: rupees(d.total), tone: 'balance', sub: type ? VOUCHER_LABEL[type] : 'every kind' },
              { label: 'Money in', value: complete ? rupees(moneyIn) : '—', tone: 'in', sub: complete ? 'receipts' : 'load all to add up' },
              { label: 'Money out', value: complete ? rupees(moneyOut) : '—', tone: 'out', sub: complete ? 'payments' : 'load all to add up' },
            ]}
          />
          <section data-guide="daybook.list" className="flex flex-col gap-3">
            {entries.length === 0 ? (
              <p className="rounded-xl border border-dashed bg-card px-4 py-6 text-sm text-muted-foreground">
                {late
                  ? 'Nothing has changed after its month was closed.'
                  : search || type
                    ? 'No voucher matches'
                    : 'Nothing in the books for this period'}
              </p>
            ) : (
              <div className={cn('flex flex-col gap-3', book.isFetching && 'opacity-70')}>
                <div className="overflow-hidden rounded-xl border bg-card shadow-xs">
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead className="sticky top-0 z-[1]">
                        <tr className="border-b bg-muted text-xs text-muted-foreground">
                          <th className="w-28 px-3 py-2 text-left font-medium">Voucher</th>
                          <th className="px-3 py-2 text-left font-medium">Particulars</th>
                          <th className="hidden px-3 py-2 text-left font-medium md:table-cell">
                            <span className="inline-flex items-center gap-1.5"><span className="size-1.5 rounded-full bg-draft" /> Debit</span>
                          </th>
                          <th className="hidden px-3 py-2 text-left font-medium md:table-cell">
                            <span className="inline-flex items-center gap-1.5"><span className="size-1.5 rounded-full bg-info" /> Credit</span>
                          </th>
                          <th className="hidden px-3 py-2 text-left font-medium lg:table-cell">Project</th>
                          <th className="px-3 py-2 text-right font-medium">Amount</th>
                        </tr>
                      </thead>
                      {days.map(([day, list]) => {
                        const date = new Date(`${day}T00:00:00`)
                        return (
                          <tbody key={day}>
                            <tr className="border-b bg-muted/50">
                              <td colSpan={6} className="px-3 py-1.5">
                                <span className="flex flex-wrap items-center justify-between gap-2">
                                  <span className="flex items-baseline gap-2">
                                    <span className="text-base font-semibold tabular-nums leading-none">{date.getDate()}</span>
                                    <span className="text-[13px] font-medium">{date.toLocaleDateString('en-IN', { weekday: 'long' })}</span>
                                    <span className="text-xs text-muted-foreground">{date.toLocaleDateString('en-IN', { month: 'short', year: 'numeric' })}</span>
                                  </span>
                                  <DayMoney list={list} />
                                </span>
                              </td>
                            </tr>
                            {list.map((e) => {
                              index += 1
                              const i = index
                              const accent = KIND_ACCENT[e.voucher_type]
                              const dr = e.lines.filter((l) => Number(l.debit) > 0).map((l) => l.ledger)
                              const cr = e.lines.filter((l) => Number(l.credit) > 0).map((l) => l.ledger)
                              return (
                                <tr
                                  key={e.id}
                                  id={`voucher-${i}`}
                                  tabIndex={-1}
                                  onClick={() => {
                                    setCursor(i)
                                    setOpenId(e.id)
                                  }}
                                  className={cn('cursor-pointer border-b border-border/60 align-top hover:bg-muted/40', cursor === i && 'bg-muted/60 outline outline-1 -outline-offset-1 outline-ring', e.after_close && 'bg-draft-soft/30')}
                                >
                                  <td className="relative py-2.5 pl-4 pr-3">
                                    <span className={cn('absolute inset-y-1.5 left-1 w-1 rounded-full', accent.bar)} aria-hidden="true" />
                                    <VoucherBadge type={e.voucher_type} label={VOUCHER_LABEL[e.voucher_type]} />
                                    <span className="mt-1 block text-xs tabular-nums text-muted-foreground">{e.ref}</span>
                                  </td>
                                  <td className="px-3 py-2.5">
                                    <span className="flex items-center gap-1.5 font-medium">
                                      {e.after_close && <History className="size-3.5 shrink-0 text-draft" aria-label="Changed after close" />}
                                      {e.narration || summary(e)}
                                    </span>
                                    <span className="mt-1 block md:hidden">
                                      <Flow e={e} />
                                    </span>
                                    {e.project && <span className="mt-0.5 block text-xs text-muted-foreground lg:hidden">{e.project}</span>}
                                  </td>
                                  <td className="hidden px-3 py-2.5 text-[13px] text-draft md:table-cell">{dr.join(', ')}</td>
                                  <td className="hidden px-3 py-2.5 text-[13px] text-info md:table-cell">{cr.join(', ')}</td>
                                  <td className="hidden px-3 py-2.5 text-[13px] text-muted-foreground lg:table-cell">{e.project ?? '—'}</td>
                                  <td className={cn('whitespace-nowrap px-3 py-2.5 text-right font-semibold tabular-nums', accent.amount)}>{rupees(e.amount)}</td>
                                </tr>
                              )
                            })}
                          </tbody>
                        )
                      })}
                      <tfoot>
                        <tr className="border-t-[1.5px] border-foreground/25 bg-muted/30 font-semibold">
                          <td colSpan={2} className="px-3 py-2.5">
                            {complete ? 'Total' : `Total of the ${entries.length} shown`}{' '}
                            <span className="font-normal text-muted-foreground">· {entries.length} vouchers</span>
                          </td>
                          <td className="hidden md:table-cell" />
                          <td className="hidden md:table-cell" />
                          <td className="hidden lg:table-cell" />
                          <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums">{rupees(entries.reduce((t, e) => t + Number(e.amount), 0))}</td>
                        </tr>
                      </tfoot>
                    </table>
                  </div>
                </div>
                {d.count > entries.length && (
                  <Button variant="outline" className="self-center bg-card" onClick={() => setLimit((l) => Math.min(1000, l + PAGE))} disabled={limit >= 1000}>
                    {limit >= 1000 ? `Showing ${entries.length} of ${d.count}: narrow the period or search` : `Show more (${entries.length} of ${d.count})`}
                  </Button>
                )}
                <p className="hidden text-xs text-muted-foreground sm:block">↑ ↓ to move, Enter to open a voucher.</p>
              </div>
            )}
          </section>
        </>
      )}
      <VoucherSheet entryId={openId} onClose={() => setOpenId(null)} onOpen={setOpenId} />
      <NewVoucherDialog open={writing} onClose={() => setWriting(false)} onSaved={(e) => setOpenId(e.id)} />
    </div>
  )
}
