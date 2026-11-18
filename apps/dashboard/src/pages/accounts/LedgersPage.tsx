import * as React from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Building2, Landmark, Layers, ReceiptIndianRupee, Search, Shapes, Users, Wallet, type LucideIcon } from 'lucide-react'
import { BooksClosed } from '@/components/accounts/books'
import { PartyAvatar } from '@/components/accounts/money-kit'
import { DrCr, NatureDot, ShareBar } from '@/components/accounts/visuals'
import { DprHeader, PageError } from '@/components/dpr-page'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { LINK_LABEL, drCr, fetchChart, formatDay, mayReadBooks, rupees, type Ledger } from '@/lib/accounts'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'
import { Pager } from '@/components/page/pager'
import { usePagedUrl } from '@/lib/paging'

// ACC-05: every ledger with its balance today, by kind (suppliers, clients, bank and cash, expenses, the rest), and a
// search. A module page links here with ?link=vendor:<id> and lands on that party's ledger. Backend: GET /accounts/chart.

type Kind = 'all' | 'vendor' | 'client' | 'money' | 'expense' | 'other'
// UXA-07: the three balances that matter as figures that pick their kind; the kinds as coloured tabs with counts; the
// ledgers as one table (party initials or the kind's icon, group, kind, entries, last used, balance with its bar).
const KINDS: { value: Kind; label: string; icon: LucideIcon; tab: string }[] = [
  { value: 'all', label: 'All', icon: Layers, tab: 'bg-foreground text-background' },
  { value: 'vendor', label: 'Suppliers', icon: Building2, tab: 'bg-amber-500/15 text-amber-800 dark:text-amber-300' },
  { value: 'client', label: 'Clients', icon: Users, tab: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300' },
  { value: 'money', label: 'Bank & cash', icon: Wallet, tab: 'bg-sky-500/15 text-sky-700 dark:text-sky-300' },
  { value: 'expense', label: 'Expenses', icon: ReceiptIndianRupee, tab: 'bg-rose-500/15 text-rose-700 dark:text-rose-300' },
  { value: 'other', label: 'Others', icon: Shapes, tab: 'bg-muted text-foreground' },
]
const KIND_OF = Object.fromEntries(KINDS.map((k) => [k.value, k])) as Record<Kind, (typeof KINDS)[number]>

function kindOf(l: Ledger): Kind {
  if (l.link_kind === 'vendor') return 'vendor'
  if (l.link_kind === 'client' || l.code === 'no_client') return 'client'
  if (l.link_kind === 'money_account') return 'money'
  if (l.nature === 'expense') return 'expense'
  return 'other'
}

export default function LedgersPage() {
  usePageTitle('Ledgers')
  const { me } = useAuth()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const allowed = mayReadBooks(me?.role)
  const chart = useQuery({ queryKey: ['accounts', 'chart'], queryFn: fetchChart, enabled: allowed })
  const kind = (params.get('kind') as Kind | null) ?? 'all'
  const [q, setQ] = React.useState('')
  const [used, setUsed] = React.useState(true)
  const setKind = (k: Kind) =>
    setParams(
      (p) => {
        const n = new URLSearchParams(p)
        if (k === 'all') n.delete('kind')
        else n.set('kind', k)
        return n
      },
      { replace: true },
    )

  // From a module page: ?link=vendor:<id> opens that record's ledger.
  const link = params.get('link')
  React.useEffect(() => {
    if (!link || !chart.data) return
    const [k, id] = link.split(':')
    const found = chart.data.ledgers.find((l) => l.link_kind === k && l.link_id === id)
    if (found) navigate(`/accounts/ledgers/${found.id}`, { replace: true })
  }, [link, chart.data, navigate])

  const d = chart.data
  const groups = new Map((d?.groups ?? []).map((g) => [g.id, g.name]))
  const words = q.trim().toLowerCase()
  const list = (d?.ledgers ?? [])
    .filter((l) => (kind === 'all' || kindOf(l) === kind) && (!used || l.lines > 0 || words) && (!words || l.name.toLowerCase().includes(words)))
    .sort((a, b) => Math.abs(Number(b.balance)) - Math.abs(Number(a.balance)) || a.name.localeCompare(b.name))
  // UX-37: numbered pages, kept in the address.
  const pagedList = usePagedUrl(list, { resetOn: `${kind}|${q}|${used}` })

  if (!allowed) return <BooksClosed />
  if (chart.isError) return <PageError message="The ledgers could not be loaded." onRetry={() => chart.refetch()} back={{ to: '/accounts/trial-balance', label: 'Trial balance' }} />
  const top = Math.max(0, ...list.map((l) => Math.abs(Number(l.balance))))
  const count = (k: Kind) => (d?.ledgers ?? []).filter((l) => (k === 'all' || kindOf(l) === k) && l.lines > 0).length
  const sum = (k: Kind) => (d?.ledgers ?? []).filter((l) => kindOf(l) === k).reduce((s, l) => s + Number(l.balance), 0)

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader back={{ to: '/accounts/trial-balance', label: 'Trial balance' }} crumb="Accounts" title="Ledgers" date={d ? `Balances on ${formatDay(d.as_of)}` : undefined} />
      {!d ? (
        <Skeleton className="h-96 rounded-xl" />
      ) : (
        <>
          <div data-guide="ledgers.stats" className="grid gap-2 sm:grid-cols-3">
            {[
              { k: 'money' as Kind, label: 'Bank & cash', value: drCr(sum('money')), icon: Wallet, card: 'border-sky-500/30 bg-sky-500/[0.06]', fg: 'text-sky-700 dark:text-sky-400' },
              { k: 'vendor' as Kind, label: 'You owe suppliers', value: rupees(Math.max(-sum('vendor'), 0)), icon: Building2, card: 'border-amber-500/30 bg-amber-500/[0.07]', fg: 'text-amber-800 dark:text-amber-400' },
              { k: 'client' as Kind, label: 'Clients owe you', value: rupees(Math.max(sum('client'), 0)), icon: Landmark, card: 'border-emerald-500/30 bg-emerald-500/[0.06]', fg: 'text-emerald-700 dark:text-emerald-400' },
            ].map((f) => (
              <button key={f.k} type="button" onClick={() => setKind(kind === f.k ? 'all' : f.k)} aria-pressed={kind === f.k} className={cn('rounded-xl border px-4 py-3 text-left shadow-xs transition-colors hover:brightness-95', f.card, kind === f.k && 'ring-2 ring-ring ring-offset-1 ring-offset-background')}>
                <p className={cn('flex items-center gap-1.5 text-xs font-medium', f.fg)}>
                  <f.icon className="size-3.5" /> {f.label}
                </p>
                <p className={cn('mt-0.5 text-xl font-semibold tabular-nums', f.fg)}>{f.value}</p>
                <p className="text-[11px] text-muted-foreground">{count(f.k)} ledgers · tap to see them</p>
              </button>
            ))}
          </div>
          <section className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <div data-guide="ledgers.kinds" role="tablist" aria-label="Kind of ledger" className="flex max-w-full gap-1 overflow-x-auto rounded-xl border bg-card p-1 shadow-xs">
                {KINDS.map((k) => (
                  <button
                    key={k.value}
                    type="button"
                    role="tab"
                    aria-selected={kind === k.value}
                    onClick={() => setKind(k.value)}
                    className={cn('inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-2.5 text-xs font-medium', kind === k.value ? k.tab : 'text-muted-foreground hover:bg-muted hover:text-foreground')}
                  >
                    <k.icon className="size-3.5" /> {k.label} <span className="tabular-nums opacity-70">{count(k.value)}</span>
                  </button>
                ))}
              </div>
              <div className="relative w-full sm:w-64">
                <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
                <Input data-guide="ledgers.search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a ledger" className="h-9 bg-card pl-8" aria-label="Find a ledger" autoFocus />
              </div>
              <label className="flex items-center gap-1.5 text-sm text-muted-foreground">
                <input type="checkbox" checked={used} onChange={(e) => setUsed(e.target.checked)} className="size-4" /> Only with entries
              </label>
            </div>
            {list.length === 0 ? (
              <p className="rounded-xl border border-dashed bg-card px-4 py-6 text-sm text-muted-foreground">
                {words ? 'No ledger by that name.' : 'No ledger of this kind has entries yet.'}
              </p>
            ) : (
              <>
                <div data-guide="ledgers.list" className="overflow-hidden rounded-xl border bg-card shadow-xs">
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[720px] text-sm">
                      <thead>
                        <tr className="border-b bg-muted text-xs text-muted-foreground">
                          <th className="px-3 py-2 text-left font-medium">Ledger</th>
                          <th className="px-3 py-2 text-left font-medium">Group</th>
                          <th className="px-3 py-2 text-left font-medium">Kind</th>
                          <th className="px-3 py-2 text-right font-medium">Entries</th>
                          <th className="px-3 py-2 text-left font-medium">Last used</th>
                          <th className="px-3 py-2 text-right font-medium">Balance today</th>
                        </tr>
                      </thead>
                      <tbody>
                        {pagedList.shown.map((l) => {
                          const k = KIND_OF[kindOf(l)]
                          const party = l.link_kind === 'vendor' || l.link_kind === 'client' || l.link_kind === 'staff'
                          return (
                            <tr key={l.id} onClick={() => navigate(`/accounts/ledgers/${l.id}`)} className={cn('cursor-pointer border-t border-border/60 first:border-t-0 hover:bg-muted/30', !l.is_active && 'opacity-60')}>
                              <td className="px-3 py-2.5">
                                <span className="flex items-center gap-2.5">
                                  {party ? (
                                    <PartyAvatar name={l.name} className="size-8 text-[11px]" />
                                  ) : (
                                    <span className={cn('flex size-8 shrink-0 items-center justify-center rounded-lg', k.value === 'all' ? 'bg-muted' : k.tab)}>
                                      <k.icon className="size-4" />
                                    </span>
                                  )}
                                  <Link to={`/accounts/ledgers/${l.id}`} onClick={(e) => e.stopPropagation()} className={cn('font-medium hover:underline', !l.is_active && 'line-through')}>
                                    {l.name}
                                  </Link>
                                </span>
                              </td>
                              <td className="px-3 py-2.5 text-muted-foreground">
                                <span className="inline-flex items-center gap-1.5">
                                  <NatureDot nature={l.nature} /> {groups.get(l.group_id)}
                                </span>
                              </td>
                              <td className="px-3 py-2.5">
                                <span className={cn('rounded px-1.5 py-0.5 text-[11px] font-medium', k.value === 'other' ? 'bg-muted text-muted-foreground' : k.tab)}>{l.link_kind ? LINK_LABEL[l.link_kind] : k.label}</span>
                              </td>
                              <td className="px-3 py-2.5 text-right tabular-nums text-muted-foreground">{l.lines || '—'}</td>
                              <td className="whitespace-nowrap px-3 py-2.5 tabular-nums text-muted-foreground">{l.last_used ? formatDay(l.last_used) : '—'}</td>
                              <td className="px-3 py-2.5 text-right">
                                <DrCr value={l.balance} strong />
                                <ShareBar value={Number(l.balance)} max={top} className="ml-auto mt-1 w-28" />
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
                <Pager {...pagedList.pager} noun="ledgers" />
              </>
            )}
          </section>
        </>
      )}
    </div>
  )
}
