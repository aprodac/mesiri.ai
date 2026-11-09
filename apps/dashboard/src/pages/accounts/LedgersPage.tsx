import * as React from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { BookUser, Search } from 'lucide-react'
import { BooksClosed, BooksTabs } from '@/components/accounts/books'
import { DprHeader, DprSection, PageError, Segmented, StatStrip } from '@/components/dpr-page'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { LINK_LABEL, drCr, fetchChart, formatDay, mayReadBooks, rupees, type Ledger } from '@/lib/accounts'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'

// ACC-05: every ledger with its balance today, by kind (suppliers, clients, bank and cash, expenses, the rest), and a
// search. A module page links here with ?link=vendor:<id> and lands on that party's ledger. Backend: GET /accounts/chart.

type Kind = 'all' | 'vendor' | 'client' | 'money' | 'expense' | 'other'
const KINDS: { value: Kind; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'vendor', label: 'Suppliers' },
  { value: 'client', label: 'Clients' },
  { value: 'money', label: 'Bank & cash' },
  { value: 'expense', label: 'Expenses' },
  { value: 'other', label: 'Others' },
]

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

  // From a module page: ?link=vendor:<id> opens that record's ledger.
  const link = params.get('link')
  React.useEffect(() => {
    if (!link || !chart.data) return
    const [k, id] = link.split(':')
    const found = chart.data.ledgers.find((l) => l.link_kind === k && l.link_id === id)
    if (found) navigate(`/accounts/ledgers/${found.id}`, { replace: true })
  }, [link, chart.data, navigate])

  if (!allowed) return <BooksClosed />
  if (chart.isError) return <PageError message="The ledgers could not be loaded." onRetry={() => chart.refetch()} back={{ to: '/accounts/trial-balance', label: 'Trial balance' }} />
  const d = chart.data
  const groups = new Map((d?.groups ?? []).map((g) => [g.id, g.name]))
  const words = q.trim().toLowerCase()
  const list = (d?.ledgers ?? [])
    .filter((l) => (kind === 'all' || kindOf(l) === kind) && (!used || l.lines > 0 || words) && (!words || l.name.toLowerCase().includes(words)))
    .sort((a, b) => Math.abs(Number(b.balance)) - Math.abs(Number(a.balance)) || a.name.localeCompare(b.name))
  const count = (k: Kind) => (d?.ledgers ?? []).filter((l) => (k === 'all' || kindOf(l) === k) && l.lines > 0).length
  const sum = (k: Kind) => (d?.ledgers ?? []).filter((l) => kindOf(l) === k).reduce((s, l) => s + Number(l.balance), 0)

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 pb-8 sm:px-2">
      <DprHeader back={{ to: '/accounts/trial-balance', label: 'Trial balance' }} crumb="Accounts" title="Ledgers" date={d ? `Balances on ${formatDay(d.as_of)}` : undefined} />
      <BooksTabs current="/accounts/ledgers" />
      {!d ? (
        <Skeleton className="h-96 rounded-xl" />
      ) : (
        <>
          <StatStrip
            stats={[
              { label: 'Bank & cash', value: drCr(sum('money')), tone: sum('money') < 0 ? 'bad' : 'default' },
              { label: 'We owe suppliers', value: rupees(Math.max(-sum('vendor'), 0)), tone: sum('vendor') < 0 ? 'warn' : 'default' },
              { label: 'Clients owe us', value: rupees(Math.max(sum('client'), 0)), tone: sum('client') > 0 ? 'info' : 'default' },
            ]}
          />
          <DprSection icon={BookUser} title="Every ledger, largest balance first" meta={list.length || undefined}>
            <div className="flex flex-wrap items-center gap-2">
              <Segmented<Kind>
                label="Kind of ledger"
                value={kind}
                options={KINDS.map((k) => ({ ...k, count: count(k.value) }))}
                onChange={(k) => setParams((p) => {
                  const n = new URLSearchParams(p)
                  if (k === 'all') n.delete('kind')
                  else n.set('kind', k)
                  return n
                }, { replace: true })}
              />
              <div className="relative w-full sm:w-64">
                <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
                <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a ledger" className="h-9 pl-8" aria-label="Find a ledger" autoFocus />
              </div>
              <label className="flex items-center gap-1.5 text-sm text-muted-foreground">
                <input type="checkbox" checked={used} onChange={(e) => setUsed(e.target.checked)} className="size-4" /> Only with entries
              </label>
            </div>
            {list.length === 0 ? (
              <p className="rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground">
                {words ? 'No ledger by that name.' : 'No ledger of this kind has entries yet.'}
              </p>
            ) : (
              <ul className="divide-y rounded-lg border">
                {list.map((l) => (
                  <li key={l.id}>
                    <Link to={`/accounts/ledgers/${l.id}`} className="flex flex-col gap-0.5 px-4 py-2.5 text-sm hover:bg-muted/40 sm:flex-row sm:items-center sm:gap-4">
                      <span className="min-w-0 flex-1">
                        <span className={cn('block truncate font-medium', !l.is_active && 'text-muted-foreground line-through')}>{l.name}</span>
                        <span className="block truncate text-xs text-muted-foreground">
                          {[groups.get(l.group_id), l.link_kind ? LINK_LABEL[l.link_kind] : null, l.lines ? `${l.lines} ${l.lines === 1 ? 'entry' : 'entries'}` : 'no entries', l.last_used ? `last ${formatDay(l.last_used)}` : null]
                            .filter(Boolean)
                            .join(' · ')}
                        </span>
                      </span>
                      <span className="font-semibold tabular-nums">{drCr(l.balance)}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </DprSection>
        </>
      )}
    </div>
  )
}
