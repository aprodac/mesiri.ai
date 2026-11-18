import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeftRight, Layers, MapPin, Snail, TriangleAlert, Wallet } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { EmptyState, KpiStrip, ModuleTitle, Pill, SearchBox, Segmented } from '@/components/page/page-kit'
import { CategoryTile } from '@/components/requests/parts'
import { RecordTransferDialog, type TransferPrefill } from '@/components/materials/record-transfer-dialog'
import { useScope } from '@/lib/ScopeContext'
import { usePageTitle } from '@/lib/page-title'
import { useUrlState } from '@/lib/url-state'
import { useReadOnly } from '@/lib/trial'
import { exportCsv } from '@/lib/export'
import { swatch } from '@/lib/requests'
import { compact } from '@/lib/expenses'
import { fetchStockValue, type ValueRow } from '@/lib/stock-count'
import { ActionIcon } from '@/components/page/action-button'

// PRC-49: Materials › Stock value (web only, money roles). What the stock on hand is worth: quantity x the weighted
// average rate of its deliveries (D-P2-4, GST per D-CC8). Read only; Excel (CSV) export of every row.
// UX-69 (18 Nov 2026): one row a material (not one a site), its sites as a split bar the width of its value; a by-site
// and a by-category view; what has not been used in 30 days, and "Move" to the site that uses it (the transfer form
// filled in); whole rupees; the date in words.

const n = (v: string | number) => Number(v).toLocaleString('en-IN', { maximumFractionDigits: 3 })
const inr = (v: number) => `₹${Math.round(v).toLocaleString('en-IN')}`

interface Material { key: string; material: string; unit: string; category: string; main: string; value: number; onHand: number; rows: ValueRow[]; slow: boolean }

function byMaterial(rows: ValueRow[]): Material[] {
  const m = new Map<string, Material>()
  for (const r of rows) {
    const x = m.get(r.material_id) ?? { key: r.material_id, material: r.material, unit: r.unit, category: r.category ?? r.main_category, main: r.main_category, value: 0, onHand: 0, rows: [], slow: false }
    x.value += Number(r.value ?? 0)
    x.onHand += Number(r.on_hand)
    x.rows.push(r)
    x.slow = x.slow || r.slow_moving
    m.set(r.material_id, x)
  }
  return [...m.values()].map((x) => ({ ...x, rows: x.rows.sort((a, b) => Number(b.value ?? 0) - Number(a.value ?? 0)) })).sort((a, b) => b.value - a.value)
}

/** Where slow stock could go: another site with the same material that has used it in the last 30 days. */
function moveTarget(slow: ValueRow, rows: ValueRow[]): ValueRow | undefined {
  return rows.filter((r) => r !== slow && r.site_id && Number(r.used_30d) > 0).sort((a, b) => Number(b.used_30d) - Number(a.used_30d))[0]
}

type Split = 'material' | 'site' | 'category'

export default function StockValuePage() {
  usePageTitle('Stock value')
  const { scope } = useScope()
  const readOnly = useReadOnly()
  const projectId = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : null
  const siteId = scope.mode === 'site' ? scope.siteId : null
  const [slowParam, setSlowParam] = useUrlState<string>('slow', '')
  const slowOnly = slowParam === '1'
  const [split, setSplit] = useUrlState<Split>('by', 'material')
  const [q, setQ] = useUrlState<string>('q', '')
  const [move, setMove] = React.useState<TransferPrefill | null>(null)
  const { data: v, isLoading, isError } = useQuery({ queryKey: ['materials', 'stock-value', projectId, siteId], queryFn: () => fetchStockValue({ project_id: projectId, site_id: siteId }) })
  const all = React.useMemo(() => v?.rows ?? [], [v])
  const materials = React.useMemo(() => byMaterial(all), [all])
  const needle = q.trim().toLowerCase()
  const shown = materials.filter((x) => (!slowOnly || x.slow) && (!needle || `${x.material} ${x.category}`.toLowerCase().includes(needle)))
  const total = Number(v?.total ?? 0)
  const sites = React.useMemo(() => {
    const m = new Map<string, { id: string; name: string; value: number; slow: number }>()
    for (const r of all) {
      const id = r.site_id ?? '—'
      const x = m.get(id) ?? { id, name: r.site_name, value: 0, slow: 0 }
      x.value += Number(r.value ?? 0)
      if (r.slow_moving) x.slow += Number(r.value ?? 0)
      m.set(id, x)
    }
    return [...m.values()].sort((a, b) => b.value - a.value)
  }, [all])
  const exportRows = () =>
    exportCsv(`stock-value-${v?.as_of ?? 'today'}.csv`, ['Site', 'Category', 'Item', 'On hand', 'Unit', 'Average rate', 'Value', 'Used in 30 days', 'Slow-moving'],
      all.map((r) => [r.site_name, r.category ?? r.main_category, r.material, Number(r.on_hand), r.unit, r.rate ? Number(r.rate) : '', r.value ? Number(r.value) : '', Number(r.used_30d), r.slow_moving ? 'yes' : '']))

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <ModuleTitle icon={Wallet} title="Stock value" chip={v?.as_of ? <span className="text-xs text-muted-foreground">{new Date(`${v.as_of}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}</span> : undefined} />
        <Button variant="outline" className="gap-2" data-guide="value.export" disabled={!all.length} onClick={exportRows}><ActionIcon kind="export-excel" className="size-4" /> <span className="hidden sm:inline">Excel</span></Button>
      </header>
      {isError && <p className="text-sm text-destructive">Stock value did not load.</p>}

      <KpiStrip
        guide="value.tiles"
        stats={[
          { label: 'Stock worth', value: total ? compact(total) : '—', kind: 'stock', loading: isLoading, hint: `${materials.length} materials · ${sites.length} sites` },
          {
            label: 'Not used in 30 days', value: Number(v?.slow_moving_value) ? compact(Number(v?.slow_moving_value)) : '—', icon: Snail, loading: isLoading, guide: 'value.slow',
            tone: Number(v?.slow_moving_value) > 0 ? 'attention' : 'default', share: total > 0 ? Number(v?.slow_moving_value) / total : undefined,
            hint: `${v?.slow_moving ?? 0} items`, pressed: slowOnly, onClick: () => setSlowParam(slowOnly ? '' : '1'),
          },
          { label: 'Biggest site', value: sites[0] ? compact(sites[0].value) : '—', icon: MapPin, loading: isLoading, hint: sites[0]?.name, share: total > 0 && sites[0] ? sites[0].value / total : undefined },
          ...(v?.unpriced ? [{ label: 'No rate yet', value: v.unpriced, icon: TriangleAlert, tone: 'attention' as const, hint: 'not in the total' }] : []),
        ]}
      />

      <div className="flex flex-wrap items-center justify-between gap-2">
        <Segmented label="Split by" guide="value.categories" value={split} onChange={setSplit}
          options={[{ value: 'material', label: 'Materials', count: materials.length }, { value: 'site', label: 'Sites', count: sites.length }, { value: 'category', label: 'Categories', count: v?.by_category.length ?? 0 }]} />
        {split === 'material' && <SearchBox value={q} onChange={setQ} placeholder="Search materials" size="sm" className="w-full sm:w-56" />}
      </div>

      {!isLoading && all.length === 0 ? (
        <div data-guide="value.empty"><EmptyState icon={Wallet} title="Nothing on hand" className="bg-card" /></div>
      ) : split === 'site' ? (
        <ShareList guide="value.list" rows={sites.map((x) => ({ key: x.id, name: x.name, value: x.value, colour: swatch(x.id), note: x.slow > 0 ? <Pill tone="attention" size="xs" icon={Snail}>{compact(x.slow)} unused</Pill> : null }))} total={total} icon={MapPin} />
      ) : split === 'category' ? (
        <ShareList guide="value.list" rows={(v?.by_category ?? []).map((c) => ({ key: c.category, name: c.category, value: Number(c.value), tile: c.category }))} total={total} icon={Layers} />
      ) : (
        <ul className="divide-y overflow-hidden rounded-xl border bg-card shadow-xs" data-guide={isLoading ? undefined : 'value.list'}>
          {shown.map((x, i) => (
            <li key={x.key} className="flex flex-col gap-2 px-3 py-3 sm:px-4">
              <div className="flex items-center gap-3">
                <span className="w-5 shrink-0 text-xs text-muted-foreground tabular-nums">{!slowOnly && !needle && i < 10 ? i + 1 : ''}</span>
                <CategoryTile mainCategory={x.main} size="sm" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-semibold">{x.material}</span>
                  <span className="block truncate text-xs text-muted-foreground">{n(x.onHand)} {x.unit} · {x.rows.length === 1 ? x.rows[0].site_name : `${x.rows.length} sites`}</span>
                </span>
                {x.slow && <Pill tone="attention" size="xs" icon={Snail}>Not used 30 d</Pill>}
                <span className="w-24 shrink-0 text-right font-semibold tabular-nums">{x.value ? inr(x.value) : '—'}</span>
              </div>
              {x.rows.length > 1 && (
                <span className="ml-8 flex h-2.5 overflow-hidden rounded-full bg-muted" role="img" aria-label={x.rows.map((r) => `${r.site_name} ${inr(Number(r.value ?? 0))}`).join(', ')}>
                  {x.rows.map((r) => <span key={r.site_id ?? r.site_name} className="h-full" style={{ width: `${(Number(r.value ?? 0) / Math.max(1, x.value)) * 100}%`, backgroundColor: swatch(r.site_id ?? r.site_name) }} title={`${r.site_name} ${inr(Number(r.value ?? 0))}`} />)}
                </span>
              )}
              {x.rows.length > 1 && (
                <span className="ml-8 flex flex-wrap gap-x-3 gap-y-1 text-xs">
                  {x.rows.map((r) => {
                    const to = r.slow_moving && !readOnly ? moveTarget(r, x.rows) : undefined
                    return (
                      <span key={r.site_id ?? r.site_name} className="inline-flex items-center gap-1.5">
                        <span className="size-2 rounded-full" style={{ backgroundColor: swatch(r.site_id ?? r.site_name) }} />
                        <span className={r.slow_moving ? 'text-draft' : 'text-muted-foreground'}>{r.site_name}</span>
                        <span className="font-medium tabular-nums">{inr(Number(r.value ?? 0))}</span>
                        {to && r.site_id && to.site_id && (
                          <button type="button" className="inline-flex items-center gap-1 rounded-md border bg-background px-1.5 py-0.5 font-semibold hover:bg-muted" title={`${n(r.on_hand)} ${r.unit} unused here; ${to.site_name} used ${n(to.used_30d)} in 30 days`}
                            onClick={() => setMove({ from_project_id: r.project_id, from_site_id: r.site_id!, to_project_id: to.project_id, to_site_id: to.site_id!, material_id: r.material_id })}>
                            <ArrowLeftRight className="size-3" />Move to {to.site_name}
                          </button>
                        )}
                      </span>
                    )
                  })}
                </span>
              )}
            </li>
          ))}
          {!isLoading && shown.length === 0 && <li className="p-6 text-center text-sm text-muted-foreground">No material matches</li>}
        </ul>
      )}
      <RecordTransferDialog open={!!move} onOpenChange={(o) => !o && setMove(null)} scope={scope} prefill={move} />
    </div>
  )
}

/** A share of the whole per row: a bar the width of its value against the biggest, its share of the total. */
function ShareList({ rows, total, icon: Icon, guide }: { rows: { key: string; name: string; value: number; colour?: string; tile?: string; note?: React.ReactNode }[]; total: number; icon: typeof MapPin; guide: string }) {
  const top = Math.max(1, ...rows.map((r) => r.value))
  return (
    <ul className="divide-y overflow-hidden rounded-xl border bg-card shadow-xs" data-guide={guide}>
      {rows.map((r) => (
        <li key={r.key} className="grid grid-cols-[minmax(0,10rem)_minmax(0,1fr)_auto] items-center gap-3 px-3 py-3 text-sm sm:grid-cols-[minmax(0,14rem)_minmax(0,1fr)_auto] sm:px-4">
          <span className="flex min-w-0 items-center gap-2">
            {r.tile ? <CategoryTile mainCategory={r.tile} size="sm" /> : <Icon className="size-4 shrink-0 text-muted-foreground" />}
            <span className="truncate font-medium">{r.name}</span>
          </span>
          <span className="flex min-w-0 items-center gap-2">
            <span className="block h-2.5 flex-1 overflow-hidden rounded-full bg-muted"><span className="block h-full rounded-full bg-info" style={{ width: `${(r.value / top) * 100}%`, backgroundColor: r.colour }} /></span>
            <span className="w-10 shrink-0 text-right text-xs text-muted-foreground tabular-nums">{total ? Math.round((r.value / total) * 100) : 0}%</span>
            {r.note}
          </span>
          <span className="w-24 text-right font-semibold tabular-nums">{inr(r.value)}</span>
        </li>
      ))}
    </ul>
  )
}
