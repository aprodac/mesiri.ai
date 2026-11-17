import * as React from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ClipboardCheck, Handshake, HandCoins, Lock, Plus, Search, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Callout } from '@/components/dpr-page'
import { FilterSelect } from '@/components/filter-select'
import { VendorTile } from '@/components/orders/order-detail'
import { WorkOrderDialog } from '@/components/subcontracts/dialogs'
import { Progress3 } from '@/components/subcontracts/parts'
import { ValueStrip } from '@/components/subcontracts/value-strip'
import { useAuth } from '@/lib/AuthContext'
import { useScope } from '@/lib/ScopeContext'
import { useReadOnly } from '@/lib/trial'
import { useUrlState } from '@/lib/url-state'
import { usePageTitle } from '@/lib/page-title'
import { rupees } from '@/lib/expenses'
import { exportCsv } from '@/lib/export'
import { cn } from '@/lib/utils'
import { WO_LOOK, fetchWorkOrders, mayGiveWork, n, woUrl, type WorkOrder } from '@/lib/subcontracts'
import { ActionIcon, type KpiItem, KpiStrip, ModuleTitle } from '@/components/page/page-kit'

// NXT-05 (8 Nov 2026): Subcontract › Work orders. Every work given out: who, where, how much is done, billed and
// payable; tiles that filter (open, bills to check, over the agreed / measured, retention held), status tabs, search,
// subcontractor filter, export. A row opens the work order.

type Tab = 'open' | 'draft' | 'done' | 'all'
type Tile = '' | 'check' | 'over'

const TABS: { value: Tab; label: string; test: (w: WorkOrder) => boolean }[] = [
  { value: 'open', label: 'Open', test: (w) => w.status === 'issued' },
  { value: 'draft', label: 'Drafts', test: (w) => w.status === 'draft' },
  { value: 'done', label: 'Work done', test: (w) => w.status === 'completed' || w.status === 'closed' },
  { value: 'all', label: 'All', test: () => true },
]

export default function WorkOrdersPage() {
  usePageTitle('Work orders')
  const navigate = useNavigate()
  const readOnly = useReadOnly()
  const { me } = useAuth()
  const { scope } = useScope()
  const office = mayGiveWork(me?.role) && !readOnly
  const projectId = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : undefined
  const [tab, setTab] = useUrlState<Tab>('tab', 'open')
  const [tile, setTile] = useUrlState<Tile>('show', '')
  const [vendor, setVendor] = useUrlState<string>('vendor', 'all')
  const [q, setQ] = useUrlState<string>('q', '')
  const [creating, setCreating] = React.useState(false)

  const list = useQuery({ queryKey: ['subcontracts', 'list', projectId ?? ''], queryFn: () => fetchWorkOrders({ project_id: projectId }) })
  const all = list.data?.work_orders ?? []
  const money = !!list.data?.with_money
  const needle = q.trim().toLowerCase()
  const shown = all
    .filter(TABS.find((t) => t.value === tab)!.test)
    .filter((w) => vendor === 'all' || w.vendor_id === vendor)
    .filter((w) => tile === '' || (tile === 'check' ? w.totals.to_check > 0 : w.flags > 0))
    .filter((w) => !needle || [w.ref, w.title, w.vendor_name, w.site_name, w.project_name, ...w.lines.map((l) => l.description)].join(' ').toLowerCase().includes(needle))
  const vendors = [...new Map(all.map((w) => [w.vendor_id, w.vendor_name])).entries()].sort((a, b) => a[1].localeCompare(b[1]))
  const s = list.data?.summary
  // UX-15: page kit figures. Bills to check amber, lines over measured red; the first three filter the list.
  const tiles = (([
    { key: 'open', label: 'Open', value: s?.open ?? '—', icon: Handshake, hint: `${s?.drafts ?? 0} drafts`, pressed: tab === 'open' && tile === '', onClick: () => { setTab('open'); setTile('') } },
    { key: 'check', label: 'Bills to check', value: s?.to_check || '—', icon: ClipboardCheck, tone: s?.to_check ? 'attention' : 'default', pressed: tile === 'check', onClick: () => { setTab('all'); setTile(tile === 'check' ? '' : 'check') } },
    { key: 'over', label: 'Lines over measured', value: s?.flagged_lines || '—', icon: AlertTriangle, tone: s?.flagged_lines ? 'bad' : 'default', pressed: tile === 'over', onClick: () => { setTab('all'); setTile(tile === 'over' ? '' : 'over') } },
    ...(money ? [
      { key: 'money', label: 'Payable now', value: rupees(n(s?.payable_now)), icon: HandCoins, hint: `${rupees(n(s?.advance_left))} advance out` },
      { key: 'ret', label: 'Retention held', value: rupees(n(s?.retention_held)), icon: Lock },
    ] : []),
  ] as KpiItem[]).map((k) => ({ ...k, loading: list.isLoading })))

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <header className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <ModuleTitle icon={Handshake} title="Work orders" />
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" className="gap-2" data-guide="wo.export" disabled={!shown.length} onClick={() => exportCsv('work-orders.csv',
            ['Work order', 'Status', 'Subcontractor', 'Project', 'Site', 'Work', 'Done %', ...(money ? ['Value', 'Measured', 'Billed', 'Paid', 'Retention held', 'Advance left', 'Payable now'] : [])],
            shown.map((w) => [w.ref, WO_LOOK[w.status].label, w.vendor_name, w.project_name, w.site_name ?? '', w.title ?? w.lines.map((l) => l.description).join('; '), Number(w.totals.progress_pct),
              ...(money ? [n(w.totals.value), n(w.totals.measured_value), n(w.totals.billed), n(w.totals.paid), n(w.totals.retention_held), n(w.totals.advance_left), n(w.totals.payable_now)] : [])]))}>
            <ActionIcon kind="export-excel" className="size-4" /> <span className="hidden sm:inline">Export</span>
          </Button>
          {office && <Button className="gap-1.5 font-semibold" data-guide="wo.add" onClick={() => setCreating(true)}><Plus className="size-4" /> <span className="hidden sm:inline">New work order</span><span className="sm:hidden">New</span></Button>}
        </div>
      </header>

      {money && <ValueStrip projectId={projectId} />}

      <KpiStrip guide="wo.tiles" stats={tiles} />

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div role="tablist" aria-label="Status" className="flex gap-0.5 rounded-xl bg-muted p-1" data-guide="wo.tabs">
          {TABS.map((t) => (
            <button key={t.value} role="tab" type="button" aria-selected={tab === t.value} onClick={() => setTab(t.value)}
              className={cn('inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-sm', tab === t.value ? 'bg-background font-semibold shadow-sm' : 'text-foreground/75 hover:text-foreground')}>
              {t.label}<span className="text-xs text-muted-foreground tabular-nums">{all.filter(t.test).length}</span>
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2" data-guide="wo.filters">
          <div className="relative">
            <Search className="pointer-events-none absolute top-2 left-2.5 size-4 text-muted-foreground" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="WO, work, site" aria-label="Search work orders" className="h-8 w-[180px] pl-8" />
          </div>
          <FilterSelect label="Subcontractor" value={vendor} onChange={setVendor} className="w-[190px]" options={[{ value: 'all', label: 'Every subcontractor' }, ...vendors.map(([id, name]) => ({ value: id, label: name }))]} />
        </div>
      </div>

      {list.isError ? (
        <Callout tone="draft" icon={TriangleAlert} action={<Button variant="outline" size="sm" className="bg-background" onClick={() => list.refetch()}>Try again</Button>}>The work orders could not be loaded.</Callout>
      ) : list.isLoading ? (
        <div className="flex flex-col gap-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24 rounded-xl" />)}</div>
      ) : shown.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center" data-guide="wo.empty">
          <Handshake className="size-6 text-muted-foreground" />
          <p className="text-sm font-medium">{all.length ? 'No work order matches' : 'No work orders yet'}</p>
          <p className="max-w-md text-sm text-muted-foreground">{all.length ? 'Try another tab or clear the filters.' : 'Concreting, plastering, wiring: who does it, at what rate.'}</p>
          {office && !all.length && <Button size="sm" className="mt-1 gap-1.5" onClick={() => setCreating(true)}><Plus className="size-4" /> New work order</Button>}
        </div>
      ) : (
        <ul className="grid gap-2" data-guide="wo.list">
          {shown.map((w) => (
            <li key={w.id}>
              <button type="button" onClick={() => navigate(woUrl(w.id))} className="flex w-full flex-col gap-2 rounded-xl border bg-card p-3 text-left transition hover:bg-muted/30 sm:flex-row sm:items-center sm:gap-4">
                <span className="flex min-w-0 flex-1 items-center gap-3">
                  <VendorTile id={w.vendor_id} name={w.vendor_name} />
                  <span className="min-w-0">
                    <span className="flex flex-wrap items-center gap-1.5">
                      <span className="font-semibold tabular-nums">{w.ref}</span>
                      <span className="truncate font-medium">{w.vendor_name}</span>
                      <span className={cn('rounded px-1.5 py-0.5 text-[11px] font-medium', WO_LOOK[w.status].chip)}>{WO_LOOK[w.status].label}</span>
                      {w.totals.to_check > 0 && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] font-medium text-amber-900 dark:bg-amber-950 dark:text-amber-100">{w.totals.to_check} to check</span>}
                      {w.flags > 0 && <span className="rounded bg-red-100 px-1.5 py-0.5 text-[11px] font-medium text-red-800 dark:bg-red-950 dark:text-red-200">⚠ {w.flags}</span>}
                    </span>
                    <span className="block truncate text-xs text-muted-foreground">{[w.title || w.lines.map((l) => l.description).join(', '), [w.project_name, w.site_name].filter(Boolean).join(' › ')].filter(Boolean).join(' · ')}</span>
                  </span>
                </span>
                <span className="flex w-full shrink-0 flex-col gap-1 sm:w-64">
                  <Progress3 done={Number(w.totals.progress_pct)} billed={w.totals.billed_pct ? Number(w.totals.billed_pct) : undefined} />
                  <span className="flex justify-between text-xs text-muted-foreground tabular-nums">
                    <span>{w.totals.progress_pct}% done{w.totals.billed_pct ? ` · ${w.totals.billed_pct}% billed` : ''}</span>
                    {money && <span className="font-medium text-foreground">{rupees(n(w.totals.value))}</span>}
                  </span>
                </span>
                {money && n(w.totals.payable_now) > 0 && <span className="shrink-0 text-right text-xs"><span className="block font-semibold text-foreground tabular-nums">{rupees(n(w.totals.payable_now))}</span><span className="text-muted-foreground">payable now</span></span>}
              </button>
            </li>
          ))}
        </ul>
      )}
      <WorkOrderDialog open={creating} onOpenChange={setCreating} preset={{ project_id: projectId, site_id: scope.mode === 'site' ? scope.siteId : undefined }} onSaved={(wo) => navigate(woUrl(wo.id))} />
    </div>
  )
}
