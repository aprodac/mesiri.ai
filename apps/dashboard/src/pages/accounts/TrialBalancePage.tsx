import * as React from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { BadgeCheck, ChevronRight, CircleAlert, ListTree, Scale, Search, TriangleAlert } from 'lucide-react'
import { BooksClosed, BooksTabs, ExcelButton, PeriodBar, usePeriod } from '@/components/accounts/books'
import { DrCr, NATURE_DOT, NatureDot, ShareBar } from '@/components/accounts/visuals'
import { Callout, DprHeader, DprSection, PageError, StatStrip } from '@/components/dpr-page'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { useScope } from '@/lib/ScopeContext'
import {
  NATURE_LABEL,
  cell,
  drCr,
  fetchChecks,
  fetchTrialBalance,
  mayReadBooks,
  rupees,
  scopeParams,
  type Checks,
  type LedgerGroup,
  type TrialRow,
} from '@/lib/accounts'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'

// ACC-05 / ACC-22: every ledger's opening, debits, credits and closing for a period, in the chart's groups, for the
// whole company, a project or a site (the scope bar). Debits equal credits, said at the top; the books are checked
// against Finance › Money, the supplier ledger and Receivables. Backend: GET /accounts/trial-balance, /checks.

interface Node {
  group: LedgerGroup
  children: Node[]
  rows: TrialRow[]
  opening: number
  debit: number
  credit: number
  closing: number
}

function buildTree(groups: LedgerGroup[], rows: TrialRow[], q: string): Node[] {
  const words = q.trim().toLowerCase()
  const kept = words ? rows.filter((r) => r.name.toLowerCase().includes(words)) : rows
  const nodes = new Map<string, Node>(groups.map((g) => [g.id, { group: g, children: [], rows: [], opening: 0, debit: 0, credit: 0, closing: 0 }]))
  for (const r of kept) nodes.get(r.group_id)?.rows.push(r)
  const roots: Node[] = []
  for (const g of groups) {
    const n = nodes.get(g.id)!
    const parent = g.parent_id ? nodes.get(g.parent_id) : undefined
    if (parent) parent.children.push(n)
    else roots.push(n)
  }
  const total = (n: Node): boolean => {
    for (const c of n.children) total(c)
    n.children = n.children.filter((c) => c.rows.length || c.children.length)
    for (const r of n.rows) {
      n.opening += Number(r.opening)
      n.debit += Number(r.debit)
      n.credit += Number(r.credit)
      n.closing += Number(r.closing)
    }
    for (const c of n.children) {
      n.opening += c.opening
      n.debit += c.debit
      n.credit += c.credit
      n.closing += c.closing
    }
    return n.rows.length > 0 || n.children.length > 0
  }
  return roots.filter(total)
}

function Amounts({ opening, debit, credit, closing, strong, bar }: { opening: number | string; debit: number | string; credit: number | string; closing: number | string; strong?: boolean; bar?: number }) {
  return (
    <>
      <td className="hidden px-3 py-2 text-right tabular-nums text-muted-foreground md:table-cell">{drCr(opening)}</td>
      <td className="hidden px-3 py-2 text-right tabular-nums sm:table-cell">{cell(debit)}</td>
      <td className="hidden px-3 py-2 text-right tabular-nums sm:table-cell">{cell(credit)}</td>
      <td className="px-3 py-2 text-right">
        <DrCr value={closing} strong={strong} />
        {bar && <ShareBar value={Number(closing)} max={bar} className="ml-auto mt-1 w-24" />}
      </td>
    </>
  )
}

function GroupRows({ node, depth, open, toggle, onLedger, forceOpen, max }: { node: Node; depth: number; open: Set<string>; toggle: (id: string) => void; onLedger: (r: TrialRow) => void; forceOpen: boolean; max: number }) {
  const isOpen = forceOpen || open.has(node.group.id)
  const pad = { paddingLeft: `${0.75 + depth * 1}rem` }
  return (
    <>
      <tr className={cn('cursor-pointer hover:bg-muted/40', depth === 0 && 'bg-muted/30')} onClick={() => toggle(node.group.id)}>
        <td className="py-2 pr-3 font-medium" style={pad}>
          <span className="inline-flex items-center gap-1">
            <ChevronRight className={cn('size-3.5 text-muted-foreground transition-transform', isOpen && 'rotate-90')} />
            {depth === 0 && <NatureDot nature={node.group.nature} />}
            {node.group.name}
          </span>
        </td>
        <Amounts opening={node.opening} debit={node.debit} credit={node.credit} closing={node.closing} strong bar={depth === 0 ? max : undefined} />
      </tr>
      {isOpen && (
        <>
          {node.children.map((c) => (
            <GroupRows key={c.group.id} node={c} depth={depth + 1} open={open} toggle={toggle} onLedger={onLedger} forceOpen={forceOpen} max={max} />
          ))}
          {node.rows.map((r) => (
            <tr
              key={r.ledger_id ?? r.code ?? r.name}
              className={cn(r.ledger_id ? 'cursor-pointer hover:bg-muted/40' : 'text-muted-foreground')}
              onClick={() => r.ledger_id && onLedger(r)}
              title={r.ledger_id ? 'Open the ledger' : undefined}
            >
              <td className="py-2 pr-3" style={{ paddingLeft: `${1.9 + depth * 1}rem` }}>
                {r.ledger_id ? <span className="hover:underline">{r.name}</span> : <span className="italic">{r.name}</span>}
              </td>
              <Amounts opening={r.opening} debit={r.debit} credit={r.credit} closing={r.closing} />
            </tr>
          ))}
        </>
      )}
    </>
  )
}

function ChecksCallout({ checks }: { checks: Checks }) {
  const [open, setOpen] = React.useState(false)
  const parts = [
    { key: 'accounts', label: 'money accounts', page: 'Finance › Money', data: checks.accounts },
    { key: 'suppliers', label: 'suppliers', page: 'the supplier ledger', data: checks.suppliers },
    { key: 'clients', label: 'clients', page: 'Receivables', data: checks.clients },
  ] as const
  const differ = parts.reduce((n, p) => n + p.data.differ, 0)
  const counted = parts.map((p) => `${p.data.agree + p.data.differ} ${p.label}`).join(', ')
  if (!differ) {
    return (
      <Callout tone="success" icon={BadgeCheck}>
        <span className="font-medium">The books agree with every module.</span>{' '}
        <span className="text-muted-foreground">{counted}: each balance is the same in the books as in Finance › Money, the supplier ledger and Receivables.</span>
      </Callout>
    )
  }
  return (
    <Callout
      tone="draft"
      icon={TriangleAlert}
      action={
        <Button size="sm" variant="outline" onClick={() => setOpen((o) => !o)}>
          {open ? 'Hide' : 'Show'} them
        </Button>
      }
    >
      <span className="font-medium">
        {differ === 1 ? '1 balance differs from its module.' : `${differ} balances differ from their modules.`}
      </span>{' '}
      <span className="text-muted-foreground">Usually a payment saved without its money leaving an account (older records), or a record dated before an opening balance. The books follow the money in the accounts.</span>
      {open && (
        <ul className="mt-2 flex flex-col gap-1 text-xs">
          {parts.flatMap((p) =>
            p.data.rows
              .filter((r) => Number(r.difference))
              .map((r) => (
                <li key={`${p.key}-${r.id ?? r.name}`} className="tabular-nums">
                  {r.name}: books {rupees(r.books)}, {p.page} {rupees(r.module)} (difference {rupees(r.difference)})
                </li>
              )),
          )}
        </ul>
      )}
    </Callout>
  )
}

export default function TrialBalancePage() {
  usePageTitle('Trial balance')
  const { me } = useAuth()
  const { scope } = useScope()
  const navigate = useNavigate()
  const periodState = usePeriod()
  const { period } = periodState
  const sp = scopeParams(scope)
  const allowed = mayReadBooks(me?.role)
  const tb = useQuery({ queryKey: ['accounts', 'tb', period, sp], queryFn: () => fetchTrialBalance(period, sp), enabled: allowed })
  const checks = useQuery({ queryKey: ['accounts', 'checks'], queryFn: fetchChecks, enabled: allowed && scope.mode === 'portfolio' })
  const [q, setQ] = React.useState('')
  const [open, setOpen] = React.useState<Set<string>>(new Set())
  const [all, setAll] = React.useState(false)

  const tree = React.useMemo(() => (tb.data ? buildTree(tb.data.groups, tb.data.rows, q) : []), [tb.data, q])
  if (!allowed) return <BooksClosed />
  if (tb.isError) return <PageError message="The trial balance could not be loaded." onRetry={() => tb.refetch()} back={{ to: '/finance/money', label: 'Money' }} />

  const toggle = (id: string) =>
    setOpen((s) => {
      const n = new Set(s)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })
  const d = tb.data
  const keep = new URLSearchParams(window.location.search).toString()
  const onLedger = (r: TrialRow) => navigate(`/accounts/ledgers/${r.ledger_id}${keep ? `?${keep}` : ''}`)
  const t = d?.totals
  const headOffice = d?.rows.find((r) => r.code === 'head_office')
  const max = Math.max(0, ...tree.map((n) => Math.abs(n.closing)))
  const natures = [...new Set(tree.map((n) => n.group.nature))]

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 pb-8 sm:px-2">
      <DprHeader
        back={{ to: '/finance/money', label: 'Money' }}
        crumb="Accounts"
        title="Trial balance"
        chip={
          t && (
            <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium', t.balanced ? 'bg-success-soft text-success' : 'bg-destructive/10 text-destructive')}>
              {t.balanced ? <BadgeCheck className="size-3.5" /> : <CircleAlert className="size-3.5" />} {t.balanced ? 'Balanced' : 'Does not balance'}
            </span>
          )
        }
        date={d ? `${d.financial_year} · ${d.scope}` : undefined}
        action={d && <ExcelButton path="/accounts/trial-balance/export" params={{ ...period, ...sp }} name={`trial-balance-${period.date_from}-to-${period.date_to}`} />}
      />
      <BooksTabs current="/accounts/trial-balance" />
      <PeriodBar state={periodState} />
      {tb.isLoading || !d || !t ? (
        <Skeleton className="h-96 rounded-xl" />
      ) : (
        <>
          <StatStrip
            phoneCols={2}
            stats={[
              { label: 'Debits in the period', value: rupees(t.debit), icon: Scale },
              { label: 'Credits in the period', value: rupees(t.credit), icon: Scale },
              {
                label: t.balanced ? 'Balanced' : 'Does not balance',
                value: t.balanced ? `${rupees(t.closing_debit)} each side` : rupees(Number(t.closing_debit) - Number(t.closing_credit)),
                tone: t.balanced ? 'good' : 'bad',
                icon: t.balanced ? BadgeCheck : CircleAlert,
                hint: 'Closing debits = closing credits',
              },
              { label: 'Ledgers with entries', value: String(d.rows.filter((r) => r.ledger_id).length), icon: ListTree },
            ]}
          />
          {scope.mode === 'portfolio' && checks.data && <ChecksCallout checks={checks.data} />}
          {headOffice && (
            <Callout tone="info" icon={ListTree}>
              <span className="font-medium">Head office and other projects: {drCr(headOffice.closing)}.</span>{' '}
              <span className="text-muted-foreground">
                What moved between {d.scope.replace(/^(project|site) /, '')} and the rest of the company (a transfer to its petty cash, a bill paid from the office bank), so its books balance on their own.
              </span>
            </Callout>
          )}
          <DprSection icon={ListTree} title="Ledgers by group" meta={d.rows.length || undefined}>
            {d.rows.length === 0 ? (
              <p className="rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground">
                Nothing in the books for this period{scope.mode !== 'portfolio' ? ` on ${d.scope}` : ''}. Expenses, payments, transfers, RA bills and money from clients appear here as soon as they are recorded.
              </p>
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <div className="relative w-full sm:w-72">
                    <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
                    <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a ledger" className="h-9 pl-8" aria-label="Find a ledger" />
                  </div>
                  <Button size="sm" variant="ghost" onClick={() => setAll((a) => !a)}>
                    {all ? 'Collapse all' : 'Expand all'}
                  </Button>
                  <span className="ml-auto flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground" aria-label="Kinds of group">
                    {natures.map((n) => (
                      <span key={n} className="inline-flex items-center gap-1.5">
                        <span className={cn('size-2 rounded-full', NATURE_DOT[n])} /> {NATURE_LABEL[n]}
                      </span>
                    ))}
                  </span>
                </div>
                <div className="overflow-x-auto rounded-lg border">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b bg-muted/40 text-xs text-muted-foreground">
                        <th className="px-3 py-2 text-left font-medium">Group / ledger</th>
                        <th className="hidden px-3 py-2 text-right font-medium md:table-cell">Opening</th>
                        <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">Debit</th>
                        <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">Credit</th>
                        <th className="px-3 py-2 text-right font-medium">Closing</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y">
                      {tree.map((n) => (
                        <GroupRows key={n.group.id} node={n} depth={0} open={open} toggle={toggle} onLedger={onLedger} forceOpen={all || !!q.trim()} max={max} />
                      ))}
                    </tbody>
                    <tfoot>
                      <tr className="border-t-2 font-semibold">
                        <td className="px-3 py-2">Total</td>
                        <td className="hidden px-3 py-2 text-right tabular-nums md:table-cell">
                          {rupees(t.opening_debit)} Dr / {rupees(t.opening_credit)} Cr
                        </td>
                        <td className="hidden px-3 py-2 text-right tabular-nums sm:table-cell">{rupees(t.debit)}</td>
                        <td className="hidden px-3 py-2 text-right tabular-nums sm:table-cell">{rupees(t.credit)}</td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {rupees(t.closing_debit)} Dr / {rupees(t.closing_credit)} Cr
                        </td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
                <p className="text-xs text-muted-foreground">
                  Groups follow Tally's ({Object.values(NATURE_LABEL).join(', ').toLowerCase()}). Income and expense ledgers start each year (April) at nil. Tap a ledger for every entry in it, or{' '}
                  <Link to="/accounts/chart" className="underline">
                    arrange the chart
                  </Link>
                  .
                </p>
              </>
            )}
          </DprSection>
        </>
      )}
    </div>
  )
}
