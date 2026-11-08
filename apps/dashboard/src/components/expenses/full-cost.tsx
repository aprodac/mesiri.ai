import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Boxes, HardHat, Info, Receipt } from 'lucide-react'
import { compact, fetchCosts, type ExpenseFilters } from '@/lib/expenses'
import { cn } from '@/lib/utils'

// CC-01: what the period really cost -- the expenses on this page, plus materials delivered with a price (a delivery
// that came with a bill is already an expense), plus labour at the wage on each attendance line. A part opens its
// page; a bar per site shows where it went. Shown above the expense tiles.

const PARTS = [
  { key: 'expenses', label: 'Expenses', icon: Receipt, bar: 'bg-indigo-500', to: null },
  { key: 'materials', label: 'Materials delivered', icon: Boxes, bar: 'bg-emerald-500', to: '/materials?view=movements&dir=in' },
  { key: 'labour', label: 'Labour', icon: HardHat, bar: 'bg-amber-500', to: '/labour' },
] as const

export function FullCost({ filters }: { filters: ExpenseFilters }) {
  const { data, isLoading, isError } = useQuery({ queryKey: ['finance', 'costs', filters], queryFn: () => fetchCosts(filters), retry: false })
  if (isError) return null
  const total = Number(data?.total ?? 0)
  const amount = (k: (typeof PARTS)[number]['key']) => Number(data?.[k].amount ?? 0)
  const notes = [
    data && data.materials.unpriced > 0 ? `${data.materials.unpriced} ${data.materials.unpriced === 1 ? 'delivery has' : 'deliveries have'} no price` : null,
    data && Number(data.labour.man_days) > Number(data.labour.priced_man_days)
      ? `${Number(data.labour.man_days) - Number(data.labour.priced_man_days)} of ${data.labour.man_days} man-days have no wage`
      : null,
  ].filter(Boolean)
  return (
    <section aria-label="Full cost" className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div>
          <p className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Full cost in this period</p>
          <p className="text-3xl font-semibold tabular-nums">{isLoading ? '–' : compact(total)}</p>
        </div>
        <div className="flex flex-wrap gap-x-5 gap-y-2">
          {PARTS.map((p) => {
            const body = (
              <span className="flex items-center gap-2">
                <span className={cn('size-2.5 rounded-full', p.bar)} />
                <span className="flex flex-col leading-tight">
                  <span className="text-sm font-semibold tabular-nums">{isLoading ? '–' : compact(amount(p.key))}</span>
                  <span className="text-xs text-muted-foreground">
                    {p.label}
                    {data && p.key === 'labour' && Number(data.labour.man_days) > 0 ? ` · ${data.labour.man_days} man-days` : ''}
                    {data && p.key === 'materials' && data.materials.deliveries > 0 ? ` · ${data.materials.deliveries}` : ''}
                  </span>
                </span>
              </span>
            )
            return p.to ? (
              <Link key={p.key} to={p.to} className="rounded-lg px-1 transition hover:bg-muted/50">
                {body}
              </Link>
            ) : (
              <span key={p.key} className="px-1">
                {body}
              </span>
            )
          })}
        </div>
      </div>
      <div className="flex h-2.5 overflow-hidden rounded-full bg-muted" aria-hidden="true">
        {PARTS.map((p) => (
          <span key={p.key} className={p.bar} style={{ width: `${total > 0 ? (amount(p.key) / total) * 100 : 0}%` }} />
        ))}
      </div>
      {data && data.by_site.length > 1 && (
        <ul className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
          {data.by_site.slice(0, 6).map((s) => {
            const t = Number(s.total)
            return (
              <li key={`${s.project_id}:${s.site_id}`} className="flex items-center gap-2 text-sm">
                <span className="w-32 shrink-0 truncate font-medium sm:w-40">{s.site_name ?? `${s.project_name} (no site)`}</span>
                <span className="flex h-2 flex-1 overflow-hidden rounded-full bg-muted">
                  {(['expenses', 'materials', 'labour'] as const).map((k, i) => (
                    <span key={k} className={PARTS[i].bar} style={{ width: `${total > 0 ? (Number(s[k]) / total) * 100 : 0}%` }} />
                  ))}
                </span>
                <span className="w-16 shrink-0 text-right font-semibold tabular-nums">{compact(t)}</span>
              </li>
            )
          })}
        </ul>
      )}
      {notes.length > 0 && (
        <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
          <Info className="mt-0.5 size-3.5 shrink-0" />
          {notes.join(' · ')}: not in the total. A delivery priced on site and also typed as an expense counts twice until it is put on that bill: the
          supplier's page › Not billed (Finance › Suppliers).
        </p>
      )}
    </section>
  )
}
