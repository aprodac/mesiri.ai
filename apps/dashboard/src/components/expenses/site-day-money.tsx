import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { IndianRupee } from 'lucide-react'
import { useAuth } from '@/lib/AuthContext'
import { MONEY_ROLES } from '@/lib/module-map'
import { PAID_VIA, compact, fetchCosts, fetchExpenses, paidWords, rupees } from '@/lib/expenses'
import { cn } from '@/lib/utils'

// CC-01 / PRC-18 on the site's day: what the day cost there -- expenses, materials delivered, labour -- and the
// day's expenses, each opening its panel on Finance > Expenses. For the roles that see spending.

export function SiteDayMoney({ siteId, date }: { siteId: string; date: string }) {
  const { me } = useAuth()
  const allowed = (MONEY_ROLES as readonly string[]).includes((me?.role || '').toUpperCase())
  const filters = { site_id: siteId, date_from: date, date_to: date }
  const costs = useQuery({ queryKey: ['finance', 'costs', filters], queryFn: () => fetchCosts(filters), enabled: allowed, retry: false })
  const expenses = useQuery({ queryKey: ['finance', 'expenses', filters], queryFn: () => fetchExpenses(filters), enabled: allowed, retry: false })
  if (!allowed || costs.isError) return null
  const c = costs.data
  const rows = (expenses.data ?? []).filter((e) => !e.reversed)
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <IndianRupee className="size-4 text-muted-foreground" /> Money spent
        </h3>
        <span className="text-lg font-semibold tabular-nums">{c ? compact(Number(c.total)) : '–'}</span>
      </div>
      {c && (
        <dl className="grid grid-cols-3 gap-2 text-xs">
          {([
            ['Expenses', c.expenses.amount, null],
            ['Materials', c.materials.amount, '/materials?view=movements&dir=in'],
            ['Labour', c.labour.amount, '/labour'],
          ] as const).map(([label, value, to]) => (
            <div key={label} className="rounded-lg bg-muted/60 px-2 py-1.5">
              <dt className="text-muted-foreground">{to ? <Link to={to} className="hover:underline">{label}</Link> : label}</dt>
              <dd className="font-semibold tabular-nums">{compact(Number(value))}</dd>
            </div>
          ))}
        </dl>
      )}
      {rows.length > 0 ? (
        <ul className="flex flex-col divide-y rounded-lg border">
          {rows.map((e) => (
            <li key={e.id}>
              <Link to={`/finance/expenses/${e.id}`} className="flex items-center gap-2 px-3 py-2 text-sm transition hover:bg-muted/40">
                <span className={cn('size-2 shrink-0 rounded-full', PAID_VIA[e.paid_via].dot)} title={paidWords(e)} />
                <span className="min-w-0 flex-1 truncate">{e.vendor || e.category}{e.description ? <span className="text-muted-foreground"> · {e.description}</span> : null}</span>
                <span className="font-semibold tabular-nums">{rupees(e.amount)}</span>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-muted-foreground">No expense recorded for this day.</p>
      )}
    </section>
  )
}
