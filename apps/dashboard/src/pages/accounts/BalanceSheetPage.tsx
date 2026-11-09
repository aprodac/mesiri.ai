import * as React from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { BadgeCheck, ChevronRight, CircleAlert, Scale } from 'lucide-react'
import { BooksClosed, BooksTabs } from '@/components/accounts/books'
import { NatureDot } from '@/components/accounts/visuals'
import { DprHeader, PageError, StatStrip } from '@/components/dpr-page'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { fetchBalanceSheet, formatDay, mayReadBooks, rupees, type BsGroup } from '@/lib/accounts'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'

// ACC-06: what the company owns against what it owes and its capital, on a day; the year's profit and earlier years'
// in capital. Company-wide (a project has its position: Accounts › Projects). Backend: GET /accounts/balance-sheet.

function Money({ v }: { v: string | number }) {
  const n = Number(v)
  return <span className={cn('tabular-nums', n < 0 && 'text-destructive')}>{n < 0 ? `(${rupees(n)})` : rupees(n)}</span>
}

function Side({ title, groups, total }: { title: string; groups: BsGroup[]; total: string }) {
  const [open, setOpen] = React.useState<Set<string>>(new Set(groups.slice(0, 2).map((g) => g.group_id)))
  return (
    <section className="flex flex-col overflow-hidden rounded-xl border">
      <h2 className="border-b bg-muted/40 px-4 py-2 text-sm font-semibold">{title}</h2>
      <ul className="flex-1 divide-y text-sm">
        {groups.map((g) => {
          const isOpen = open.has(g.group_id)
          return (
            <li key={g.group_id}>
              <button
                type="button"
                className="flex w-full items-center gap-2 px-4 py-2.5 text-left hover:bg-muted/40"
                onClick={() => setOpen((s) => {
                  const n = new Set(s)
                  if (n.has(g.group_id)) n.delete(g.group_id)
                  else n.add(g.group_id)
                  return n
                })}
              >
                <ChevronRight className={cn('size-3.5 text-muted-foreground transition-transform', isOpen && 'rotate-90')} />
                <NatureDot nature={g.nature} />
                <span className="flex-1 font-medium">{g.name}</span>
                <span className="font-medium">
                  <Money v={g.amount} />
                </span>
              </button>
              {isOpen && (
                <ul className="pb-2">
                  {g.subgroups.map((s) => (
                    <li key={s.group_id ?? s.name}>
                      <div className="flex justify-between gap-2 py-1 pl-11 pr-4 text-muted-foreground">
                        <span className={cn(!s.group_id && 'italic')}>{s.name}</span>
                        <Money v={s.amount} />
                      </div>
                      {(s.ledgers.length > 1 || (s.ledgers.length === 1 && s.ledgers[0].name !== s.name)) &&
                        s.ledgers.slice(0, 8).map((l) => (
                          <Link key={l.ledger_id} to={`/accounts/ledgers/${l.ledger_id}`} className="flex justify-between gap-2 py-0.5 pl-14 pr-4 text-xs text-muted-foreground hover:text-foreground">
                            <span className="truncate">{l.name}</span>
                            <Money v={l.amount} />
                          </Link>
                        ))}
                      {s.ledgers.length > 8 && <p className="pl-14 text-xs text-muted-foreground">and {s.ledgers.length - 8} more</p>}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          )
        })}
      </ul>
      <div className="flex justify-between border-t-2 bg-muted/30 px-4 py-2.5 font-semibold">
        <span>Total</span>
        <Money v={total} />
      </div>
    </section>
  )
}

export default function BalanceSheetPage() {
  usePageTitle('Balance sheet')
  const { me } = useAuth()
  const [params, setParams] = useSearchParams()
  const asOf = params.get('as_of') ?? undefined
  const allowed = mayReadBooks(me?.role)
  const q = useQuery({ queryKey: ['accounts', 'bs', asOf], queryFn: () => fetchBalanceSheet(asOf), enabled: allowed })
  if (!allowed) return <BooksClosed />
  if (q.isError) return <PageError message="The balance sheet could not be loaded." onRetry={() => q.refetch()} back={{ to: '/accounts', label: 'Accounts' }} />
  const d = q.data
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
        action={
          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            As on
            <Input
              type="date"
              value={asOf ?? d?.as_of ?? ''}
              onChange={(e) => setParams((p) => {
                const n = new URLSearchParams(p)
                if (e.target.value) n.set('as_of', e.target.value)
                else n.delete('as_of')
                return n
              }, { replace: true })}
              className="h-8 w-[150px] dark:[color-scheme:dark]"
            />
          </label>
        }
      />
      <BooksTabs current="/accounts/balance-sheet" />
      {!d ? (
        <Skeleton className="h-96 rounded-xl" />
      ) : (
        <>
          <StatStrip
            phoneCols={2}
            stats={[
              { label: 'What the company owns', value: rupees(d.total_assets), icon: Scale },
              { label: 'What it owes, and capital', value: rupees(d.total_liabilities), icon: Scale },
              { label: Number(d.year_profit) < 0 ? 'Loss this year' : 'Profit this year', value: rupees(d.year_profit), tone: Number(d.year_profit) < 0 ? 'bad' : 'good', hint: `since ${formatDay(d.year_start)}` },
            ]}
          />
          {!d.liabilities.length && !d.assets.length ? (
            <p className="rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground">Nothing in the books on this day yet.</p>
          ) : (
            <div className="grid gap-4 lg:grid-cols-2">
              <Side title="Capital and liabilities" groups={d.liabilities} total={d.total_liabilities} />
              <Side title="Assets" groups={d.assets} total={d.total_assets} />
            </div>
          )}
          <p className="text-xs text-muted-foreground">
            A supplier paid ahead shows under what is owed as a minus (an advance). A project has no balance sheet of its own: see its position under Projects.
          </p>
        </>
      )}
    </div>
  )
}
