import * as React from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { BadgeCheck, CircleAlert } from 'lucide-react'
import { BooksClosed } from '@/components/accounts/books'
import { figures } from '@/components/accounts/bs-model'
import { BsSimple } from '@/components/accounts/bs-simple'
import { BsEquation, BsTwoColumn } from '@/components/accounts/bs-two-column'
import { DprHeader, PageError, Segmented } from '@/components/dpr-page'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { fetchBalanceSheet, formatDay, mayReadBooks } from '@/lib/accounts'
import { useBooksView } from '@/lib/books-view'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'

// ACC-06: what the company owns against what it owes and its capital, on a day; the year's profit and earlier years'
// in capital. Company-wide (a project has its position: Accounts › Projects). Backend: GET /accounts/balance-sheet.
// UX-33: two ways to read it, as on Profit & loss (lib/books-view.ts picks which opens). "Simple" (the owner's): what
// the company is worth, what it owns and owes in plain words, whether it can pay what is due, each line opening down
// to its entries and vouchers. "Tally": the accounting equation and Tally's two columns. Either can sit beside an
// earlier day (the month end before, or the end of last year): the same call for that day.

const VIEWS = ['simple', 'statement'] as const
type CompareTo = '' | 'month' | 'year'

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

/** The day to set beside ``asOf``: the last day of the month before, or the day before the financial year began. */
function compareDate(kind: CompareTo, asOf: string, yearStart: string): string | null {
  if (!kind) return null
  if (kind === 'month') {
    const [y, m] = asOf.split('-').map(Number)
    return iso(new Date(y, m - 1, 0))
  }
  const [y, m, d] = yearStart.split('-').map(Number)
  return iso(new Date(y, m - 1, d - 1))
}

export default function BalanceSheetPage() {
  usePageTitle('Balance sheet')
  const { me } = useAuth()
  const [params, setParams] = useSearchParams()
  const asOf = params.get('as_of') ?? undefined
  const compare = (params.get('compare') ?? '') as CompareTo
  const [view, pickView] = useBooksView('bs', VIEWS)
  const [open, setOpen] = React.useState<Set<string>>(new Set())
  const set = (k: string, v: string | null) =>
    setParams((p) => {
      const n = new URLSearchParams(p)
      if (v) n.set(k, v)
      else n.delete(k)
      return n
    }, { replace: true })
  const allowed = mayReadBooks(me?.role)
  const q = useQuery({ queryKey: ['accounts', 'bs', asOf], queryFn: () => fetchBalanceSheet(asOf), enabled: allowed })
  const d = q.data
  const thenDay = d ? compareDate(compare, d.as_of, d.year_start) : null
  const pq = useQuery({ queryKey: ['accounts', 'bs', thenDay], queryFn: () => fetchBalanceSheet(thenDay!), enabled: allowed && !!thenDay })
  if (!allowed) return <BooksClosed />
  if (q.isError) return <PageError message="The balance sheet could not be loaded." onRetry={() => q.refetch()} back={{ to: '/accounts', label: 'Accounts' }} />
  const prior = thenDay ? figures(pq.data) : null
  const priorLabel = thenDay ? formatDay(thenDay) : undefined
  const toggle = (id: string) =>
    setOpen((s) => {
      const next = new Set(s)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  // The equation's terms open their groups in the two columns
  const onTerm = (nature: 'asset' | 'liability' | 'equity') => {
    if (!d) return
    const gs = [...d.assets, ...d.liabilities].filter((g) => (nature === 'liability' ? g.nature !== 'asset' && g.nature !== 'equity' : g.nature === nature))
    setOpen((s) => {
      const next = new Set(s)
      for (const g of gs) next.add(`g:${g.group_id}`)
      return next
    })
    if (gs[0]) window.setTimeout(() => document.getElementById(`bsg-${gs[0].group_id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 50)
  }

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader
        back={{ to: '/accounts', label: 'Accounts' }}
        crumb="Accounts"
        title="Balance sheet"
        chip={
          d && (
            <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium', d.balanced ? 'bg-success-soft text-success' : 'bg-destructive/10 text-destructive')}>
              {d.balanced ? <BadgeCheck className="size-3.5" /> : <CircleAlert className="size-3.5" />} {d.balanced ? 'Balances' : 'Does not balance'}
            </span>
          )
        }
        date={d ? `as on ${formatDay(d.as_of)} · whole company` : undefined}
      />
      <div className="flex flex-wrap items-center gap-2">
        <Segmented<(typeof VIEWS)[number]>
          guide="bs.view"
          label="Show as"
          value={view}
          options={[
            { value: 'simple', label: 'Simple' },
            { value: 'statement', label: 'Tally' },
          ]}
          onChange={pickView}
        />
        <label data-guide="bs.asof" className="flex items-center gap-2 text-xs text-muted-foreground">
          As on
          <Input type="date" value={asOf ?? d?.as_of ?? ''} onChange={(e) => set('as_of', e.target.value || null)} className="h-8 w-[150px] dark:[color-scheme:dark]" />
        </label>
        <Segmented<CompareTo>
          guide="bs.compare"
          label="Compare with"
          value={compare}
          options={[
            { value: '', label: 'No comparison' },
            { value: 'month', label: 'Month end before' },
            { value: 'year', label: 'End of last year' },
          ]}
          onChange={(c) => set('compare', c || null)}
        />
      </div>
      {!d || (thenDay && pq.isLoading) ? (
        <Skeleton className="h-96 rounded-xl" />
      ) : view === 'simple' ? (
        <BsSimple bs={d} prior={prior} priorLabel={priorLabel} />
      ) : (
        <>
          <BsEquation bs={d} prior={prior} priorLabel={priorLabel} onTerm={onTerm} />
          <BsTwoColumn bs={d} prior={prior} priorLabel={priorLabel} open={open} toggle={toggle} />
        </>
      )}
    </div>
  )
}
