import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download, IndianRupee, Snail, TriangleAlert, Wallet } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ModuleTitle } from '@/components/page/page-kit'
import { useScope } from '@/lib/ScopeContext'
import { usePageTitle } from '@/lib/page-title'
import { exportCsv } from '@/lib/export'
import { rupees } from '@/lib/orders'
import { fetchStockValue, type ValueRow } from '@/lib/stock-count'
import { cn } from '@/lib/utils'

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
        <Button variant="outline" className="gap-2" disabled={!v?.rows.length} onClick={exportRows}><Download className="size-4" /> <span className="hidden sm:inline">Excel</span></Button>
      </header>
      {isError && <p className="text-sm text-destructive">Stock value did not load. It is for the roles that see spending.</p>}

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 sm:gap-3">
        <Tile icon={IndianRupee} tone="bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100" value={isLoading ? '–' : rupees(v?.total)} label={`Stock worth, ${v?.items ?? 0} items`} />
        <button type="button" onClick={() => setSlowOnly((s) => !s)} className={cn('rounded-xl text-left', slowOnly && 'ring-2 ring-orange-500')}>
          <Tile icon={Snail} tone="bg-orange-100 text-orange-900 dark:bg-orange-950 dark:text-orange-100" value={isLoading ? '–' : rupees(v?.slow_moving_value)} label={`${v?.slow_moving ?? 0} not used in 30 days`} />
        </button>
        {!!v?.unpriced && <Tile icon={TriangleAlert} tone="bg-muted text-foreground/80" value={String(v.unpriced)} label="Items with no rate yet (not in the total)" />}
      </div>

      {!!v?.by_category.length && (
        <section className="flex flex-col gap-2 rounded-xl border p-3 sm:p-4">
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

      <section className="overflow-hidden rounded-xl border">
        <h2 className="border-b bg-muted/40 px-3 py-2 text-sm font-semibold">{slowOnly ? 'Not used in 30 days' : 'Every item, most valuable first'} <span className="font-normal text-muted-foreground">{rows.length}</span></h2>
        {!isLoading && rows.length === 0 && <p className="p-6 text-center text-sm text-muted-foreground">Nothing on hand here. Stock value comes from deliveries with a rate.</p>}
        <ul className="divide-y">
          {rows.map((r, i) => <Row key={`${r.site_id}:${r.material_id}`} r={r} rank={!slowOnly && i < 10 ? i + 1 : null} />)}
        </ul>
      </section>
      {v?.as_of && <p className="text-xs text-muted-foreground">As on {v.as_of}: on hand x the average rate of every delivery with a rate (GST you claim back left out).</p>}
    </div>
  )
}

function Tile({ icon: Icon, tone, value, label }: { icon: typeof Wallet; tone: string; value: string; label: string }) {
  return (
    <div className="flex h-full items-center gap-3 rounded-xl border bg-card p-3 sm:p-3.5">
      <span className={cn('inline-flex size-9 shrink-0 items-center justify-center rounded-lg sm:size-11', tone)}><Icon className="size-4 sm:size-5" /></span>
      <span className="flex min-w-0 flex-col">
        <span className="truncate text-xl leading-none font-semibold tabular-nums sm:text-2xl">{value}</span>
        <span className="text-xs leading-tight text-muted-foreground sm:text-sm">{label}</span>
      </span>
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
