import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Snail, TriangleAlert, Wallet } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { KpiStrip, ModuleTitle } from '@/components/page/page-kit'
import { useScope } from '@/lib/ScopeContext'
import { usePageTitle } from '@/lib/page-title'
import { exportCsv } from '@/lib/export'
import { rupees } from '@/lib/orders'
import { fetchStockValue, type ValueRow } from '@/lib/stock-count'
import { ActionIcon } from '@/components/page/action-button'

// PRC-49: Materials › Stock value (web only, money roles). What the stock on hand is worth: quantity x the weighted
// average rate of its deliveries (D-P2-4, GST per D-CC8): the total, a bar per category, the top 10 items, and what
// has not been used in 30 days. Read only; Excel (CSV) export of every row.

const n = (v: string) => Number(v).toLocaleString('en-IN', { maximumFractionDigits: 3 })

export default function StockValuePage() {
  usePageTitle('Stock value')
  const { scope } = useScope()
  const projectId = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : null
  const siteId = scope.mode === 'site' ? scope.siteId : null
  const [slowOnly, setSlowOnly] = React.useState(false)
  const { data: v, isLoading, isError } = useQuery({ queryKey: ['materials', 'stock-value', projectId, siteId], queryFn: () => fetchStockValue({ project_id: projectId, site_id: siteId }) })
  const max = Math.max(1, ...(v?.by_category ?? []).map((c) => Number(c.value)))
  const rows = (v?.rows ?? []).filter((r) => !slowOnly || r.slow_moving)
  const exportRows = () =>
    exportCsv(`stock-value-${v?.as_of ?? 'today'}.csv`, ['Site', 'Category', 'Item', 'On hand', 'Unit', 'Average rate', 'Value', 'Used in 30 days', 'Slow-moving'],
      (v?.rows ?? []).map((r) => [r.site_name, r.category ?? r.main_category, r.material, Number(r.on_hand), r.unit, r.rate ? Number(r.rate) : '', r.value ? Number(r.value) : '', Number(r.used_30d), r.slow_moving ? 'yes' : '']))

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <header className="flex items-center justify-between gap-3">
        <ModuleTitle icon={Wallet} title="Stock value" />
        <Button variant="outline" className="gap-2" data-guide="value.export" disabled={!v?.rows.length} onClick={exportRows}><ActionIcon kind="export-excel" className="size-4" /> <span className="hidden sm:inline">Excel</span></Button>
      </header>
      {isError && <p className="text-sm text-destructive">Stock value did not load.</p>}

      {/* UX-15: page kit figures; the slow-moving figure filters the list. */}
      <KpiStrip
        guide="value.tiles"
        stats={[
          { label: 'Stock worth', value: rupees(v?.total), kind: 'stock', loading: isLoading, hint: `${v?.items ?? 0} items` },
          {
            label: 'Not used in 30 days', value: rupees(v?.slow_moving_value), icon: Snail, loading: isLoading, guide: 'value.slow',
            tone: Number(v?.slow_moving_value) > 0 ? 'attention' : 'default', share: Number(v?.total) > 0 ? Number(v?.slow_moving_value) / Number(v?.total) : undefined,
            hint: `${v?.slow_moving ?? 0} items`, pressed: slowOnly, onClick: () => setSlowOnly((x) => !x),
          },
          ...(v?.unpriced ? [{ label: 'No rate yet', value: v.unpriced, icon: TriangleAlert, tone: 'attention' as const, hint: 'not in the total' }] : []),
        ]}
      />

      {!!v?.by_category.length && (
        <section className="flex flex-col gap-2 rounded-xl border p-3 sm:p-4" data-guide="value.categories">
          <h2 className="text-sm font-semibold">By category</h2>
          {v.by_category.map((c) => (
            <div key={c.category} className="grid grid-cols-[8rem_1fr_auto] items-center gap-2 text-sm sm:grid-cols-[12rem_1fr_auto]">
              <span className="truncate">{c.category}</span>
              <span className="h-2.5 overflow-hidden rounded-full bg-muted"><span className="block h-full rounded-full bg-emerald-500" style={{ width: `${(Number(c.value) / max) * 100}%` }} /></span>
              <span className="tabular-nums">{rupees(c.value)}</span>
            </div>
          ))}
        </section>
      )}

      <section className="overflow-hidden rounded-xl border" data-guide={isLoading ? undefined : rows.length ? 'value.list' : 'value.empty'}>
        <h2 className="border-b bg-muted/40 px-3 py-2 text-sm font-semibold">{slowOnly ? 'Not used in 30 days' : 'Every item, most valuable first'} <span className="font-normal text-muted-foreground">{rows.length}</span></h2>
        {!isLoading && rows.length === 0 && <p className="p-6 text-center text-sm text-muted-foreground">Nothing on hand here. Stock value comes from deliveries with a rate.</p>}
        <ul className="divide-y">
          {rows.map((r, i) => <Row key={`${r.site_id}:${r.material_id}`} r={r} rank={!slowOnly && i < 10 ? i + 1 : null} />)}
        </ul>
      </section>
      {v?.as_of && <p className="text-xs text-muted-foreground">As on {v.as_of} · on hand × average delivery rate</p>}
    </div>
  )
}

function Row({ r, rank }: { r: ValueRow; rank: number | null }) {
  return (
    <li className="flex items-center gap-3 px-3 py-2.5">
      <span className="w-6 shrink-0 text-xs text-muted-foreground tabular-nums">{rank ?? ''}</span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-semibold">{r.material}</span>
        <span className="block truncate text-xs text-muted-foreground">
          {r.site_name} · {n(r.on_hand)} {r.unit}{r.rate ? ` at ${rupees(r.rate)}` : ' · no rate yet'}
        </span>
      </span>
      {r.slow_moving && <span className="shrink-0 rounded-md bg-orange-100 px-1.5 py-0.5 text-[11px] font-semibold text-orange-900 dark:bg-orange-950 dark:text-orange-100">Not used 30 d</span>}
      <span className="w-24 shrink-0 text-right text-sm font-semibold tabular-nums">{r.value ? rupees(r.value) : '—'}</span>
    </li>
  )
}
