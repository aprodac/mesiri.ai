import * as React from 'react'
import { useSearchParams } from 'react-router-dom'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ArrowDownLeft, ArrowUpRight, BookOpenText, CalendarDays, History, Plus, Search } from 'lucide-react'
import { BooksClosed, BooksTabs, ExcelButton, PeriodBar, VoucherSheet, usePeriod } from '@/components/accounts/books'
import { VoucherBadge } from '@/components/accounts/visuals'
import { NewVoucherDialog } from '@/components/accounts/new-voucher-dialog'
import { DprHeader, DprSection, PageError, Segmented, StatStrip } from '@/components/dpr-page'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { useScope } from '@/lib/ScopeContext'
import { VOUCHER_LABEL, fetchDayBook, formatDay, mayReadBooks, rupees, scopeParams, type Entry, type VoucherType } from '@/lib/accounts'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'

// ACC-05: every voucher of a period, day by day, as the accountant reads a day book: what it was, the ledgers it
// moved, the amount. Filter by kind, search a party or a number, see what changed after a month was closed. ↑ ↓ to
// move, Enter to open. Backend: GET /accounts/day-book.

const TYPES: (VoucherType | '')[] = ['', 'purchase', 'payment', 'receipt', 'sales', 'contra', 'journal']
const PAGE = 200

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = React.useState(value)
  React.useEffect(() => {
    const id = setTimeout(() => setV(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return v
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

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader
        back={{ to: '/accounts/trial-balance', label: 'Trial balance' }}
        crumb="Accounts"
        title="Day book"
        date={d?.scope}
        action={
          <div className="flex items-center gap-2">
            <ExcelButton path="/accounts/day-book/export" params={{ ...period, ...sp, voucher_type: type, q: search }} name={`day-book-${period.date_from}-to-${period.date_to}`} />
            <Button size="sm" className="gap-1.5" onClick={() => setWriting(true)}><Plus className="size-3.5" /> New voucher</Button>
          </div>
        }
      />
      <BooksTabs current="/accounts/day-book" />
      <PeriodBar state={periodState} />
      <div className="flex flex-wrap items-center gap-2">
        <Segmented<VoucherType | ''>
          label="Kind of voucher"
          value={type}
          options={TYPES.map((t) => ({ value: t, label: t ? VOUCHER_LABEL[t] : 'All' }))}
          onChange={(t) => setParam('type', t || null)}
        />
        <div className="relative w-full sm:w-64">
          <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Party, ledger, words or number" className="h-9 pl-8" aria-label="Search the day book" />
        </div>
        <Button size="sm" variant={late ? 'default' : 'outline'} className="gap-1.5" onClick={() => setParam('late', late ? null : '1')}>
          <History className="size-3.5" /> Changed after close
        </Button>
      </div>
      {!d ? (
        <Skeleton className="h-96 rounded-xl" />
      ) : (
        <>
          <StatStrip
            stats={[
              { label: 'Vouchers', value: String(d.count), icon: BookOpenText },
              { label: 'Total moved', value: rupees(d.total) },
              { label: 'Days with entries', value: String(days.length), icon: CalendarDays },
            ]}
          />
          <DprSection icon={BookOpenText} title="Vouchers, day by day" meta={d.count || undefined}>
            {entries.length === 0 ? (
              <p className="rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground">
                {late
                  ? 'Nothing has changed after its month was closed.'
                  : search || type
                    ? 'No voucher matches. Try fewer words or another kind.'
                    : 'Nothing in the books for this period. Expenses, payments, transfers, RA bills and money from clients appear here on their own.'}
              </p>
            ) : (
              <div className={cn('flex flex-col gap-3', book.isFetching && 'opacity-70')}>
                {days.map(([day, list]) => (
                  <section key={day} className="rounded-lg border">
                    <header className="flex items-baseline justify-between border-b bg-muted/30 px-4 py-2 text-sm">
                      <h3 className="font-medium">{formatDay(day)}</h3>
                      <DayMoney list={list} />
                    </header>
                    <ul className="divide-y">
                      {list.map((e) => {
                        index += 1
                        const i = index
                        return (
                          <li key={e.id} id={`voucher-${i}`}>
                            <button
                              type="button"
                              onClick={() => {
                                setCursor(i)
                                setOpenId(e.id)
                              }}
                              className={cn('flex w-full flex-col gap-1 px-4 py-2.5 text-left text-sm hover:bg-muted/40 sm:flex-row sm:items-center sm:gap-4', cursor === i && 'bg-muted/60 ring-1 ring-inset ring-ring')}
                            >
                              <span className="flex shrink-0 items-center gap-2 sm:w-44">
                                <VoucherBadge type={e.voucher_type} label={VOUCHER_LABEL[e.voucher_type]} />
                                <span className="text-xs text-muted-foreground tabular-nums">{e.ref}</span>
                              </span>
                              <span className="min-w-0 flex-1">
                                <span className="block truncate">{e.narration || summary(e)}</span>
                                <span className="block truncate text-xs text-muted-foreground">
                                  {summary(e)}
                                  {e.project ? ` · ${e.project}` : ''}
                                </span>
                              </span>
                              <span className="flex shrink-0 items-center gap-2 font-semibold tabular-nums">
                                {e.after_close && <History className="size-3.5 text-draft" aria-label="Changed after close" />}
                                {rupees(e.amount)}
                              </span>
                            </button>
                          </li>
                        )
                      })}
                    </ul>
                  </section>
                ))}
                {d.count > entries.length && (
                  <Button variant="outline" className="self-center" onClick={() => setLimit((l) => Math.min(1000, l + PAGE))} disabled={limit >= 1000}>
                    {limit >= 1000 ? `Showing ${entries.length} of ${d.count}: narrow the period or search` : `Show more (${entries.length} of ${d.count})`}
                  </Button>
                )}
                <p className="hidden text-xs text-muted-foreground sm:block">↑ ↓ to move, Enter to open a voucher.</p>
              </div>
            )}
          </DprSection>
        </>
      )}
      <VoucherSheet entryId={openId} onClose={() => setOpenId(null)} onOpen={setOpenId} />
      <NewVoucherDialog open={writing} onClose={() => setWriting(false)} onSaved={(e) => setOpenId(e.id)} />
    </div>
  )
}
