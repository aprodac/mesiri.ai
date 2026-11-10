import * as React from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Boxes, Building2, Plus, Receipt, TrendingDown, Truck, Wrench } from 'lucide-react'
import { BooksClosed, BooksTabs, ExcelButton } from '@/components/accounts/books'
import { Callout, DprHeader, DprSection, PageError, Segmented, StatStrip } from '@/components/dpr-page'
import { Button } from '@/components/ui/button'
import { Combobox } from '@/components/ui/combobox'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast-notification'
import { useAuth } from '@/lib/AuthContext'
import {
  deleteAsset,
  disposeAsset,
  fetchAssetBills,
  fetchAssets,
  formatDay,
  mayReadBooks,
  mayReopen,
  rupees,
  saveAsset,
  setAssetMethod,
  type AssetClass,
  type AssetInput,
  type AssetRegister,
  type FixedAsset,
} from '@/lib/accounts'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import { fetchProjects } from '@/lib/projects'
import { cn } from '@/lib/utils'

// ACC-16 (D-ACC9): machines, shuttering, vehicles, computers, furniture and buildings the company owns: cost, value
// now, depreciation year by year (WDV at Income-tax rates by default, or SLM), sold or scrapped. An asset bought in
// Mesiri's time comes from its bill (the bill's cost moves from its category to the asset); one owned before comes in
// at its value then. The books follow on their own. Backend: /accounts/assets.

const today = () => new Date().toLocaleDateString('en-CA') // the local day (YYYY-MM-DD), not UTC's

export default function AssetsPage() {
  usePageTitle('Fixed assets')
  const { me } = useAuth()
  const allowed = mayReadBooks(me?.role)
  const toast = useToast()
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const q = useQuery({ queryKey: ['accounts', 'assets'], queryFn: fetchAssets, enabled: allowed })
  const [editing, setEditing] = React.useState<FixedAsset | 'new' | null>(null)
  const [selling, setSelling] = React.useState<FixedAsset | null>(null)
  const [open, setOpen] = React.useState<string | null>(params.get('open'))
  const method = useMutation({
    mutationFn: setAssetMethod,
    onSuccess: () => {
      toast.success('Saved', 'New assets use this method; each asset keeps its own.')
      qc.invalidateQueries({ queryKey: ['accounts', 'assets'] })
    },
    onError: (err: unknown) => toast.error('Not changed', apiErrorMessage(err)),
  })
  if (!allowed) return <BooksClosed />
  if (q.isError) return <PageError message="The register could not be loaded." onRetry={() => q.refetch()} back={{ to: '/accounts', label: 'Accounts' }} />
  const d = q.data
  const live = d?.assets.filter((a) => a.status === 'in_use') ?? []
  const sold = d?.assets.filter((a) => a.status === 'sold') ?? []
  const toggle = (id: string) => {
    setOpen((o) => (o === id ? null : id))
    if (params.get('open')) setParams((p) => { const n = new URLSearchParams(p); n.delete('open'); return n }, { replace: true })
  }
  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader
        back={{ to: '/accounts/balance-sheet', label: 'Balance sheet' }}
        crumb="Accounts"
        title="Fixed assets"
        date={d ? `Year ${d.financial_year}` : undefined}
        action={
          <div className="flex flex-wrap gap-1.5">
            {d && d.assets.length > 0 && <ExcelButton path="/accounts/assets/export" params={{}} name={`fixed-assets-${d.today}`} />}
            <Button size="sm" className="gap-1.5" onClick={() => setEditing('new')}><Plus className="size-4" /> Add asset</Button>
          </div>
        }
      />
      <BooksTabs current="/accounts/assets" />
      {!d ? (
        <Skeleton className="h-96 rounded-xl" />
      ) : (
        <>
          <StatStrip
            phoneCols={2}
            stats={[
              { label: 'In use', value: String(d.totals.count), icon: Boxes },
              { label: 'Cost', value: rupees(d.totals.cost), icon: Receipt },
              { label: 'Value now', value: rupees(d.totals.value), icon: Building2, tone: 'info' },
              { label: `Depreciation ${d.financial_year}`, value: rupees(d.totals.this_year), icon: TrendingDown, hint: 'posted on 31 March' },
            ]}
          />
          <div className="flex flex-wrap items-center gap-3">
            <Segmented<'wdv' | 'slm'> label="Method for new assets" value={d.method} options={[{ value: 'wdv', label: 'WDV (Income-tax)' }, { value: 'slm', label: 'SLM (Companies Act)' }]}
              onChange={(m) => (mayReopen(me?.role) ? method.mutate(m) : toast.error('Not changed', 'Only the owner or an admin can change it.'))} />
            <span className="text-xs text-muted-foreground">Default rates and lives are the usual ones; check them with your CA.</span>
          </div>
          {d.assets.length === 0 && (
            <Callout tone="info" icon={Truck}>
              Add the machines, shuttering, vehicles and computers the company owns. A purchase already in Expenses is picked from its bill; one owned before Mesiri is added at its value then. Each year's depreciation is then posted on its own on 31 March.
            </Callout>
          )}
          {d.classes.length > 0 && (
            <DprSection icon={Boxes} title="By class" meta={d.classes.length}>
              <ul className="grid gap-2 sm:grid-cols-3">
                {d.classes.map((c) => (
                  <li key={c.asset_class} className="rounded-lg border px-3 py-2 text-sm">
                    <span className="block font-medium">{c.label}</span>
                    <span className="block text-xs text-muted-foreground tabular-nums">{c.count} · cost {rupees(c.cost)} · now {rupees(c.value)}</span>
                  </li>
                ))}
              </ul>
            </DprSection>
          )}
          {[['In use', live] as const, ['Sold or scrapped', sold] as const].map(([title, rows]) => rows.length > 0 && (
            <DprSection key={title} icon={Wrench} title={title} meta={rows.length}>
              <ul className="divide-y rounded-lg border text-sm">
                {rows.map((a) => (
                  <li key={a.id} className="px-3 py-2.5">
                    <button type="button" className="flex w-full flex-col gap-1 text-left sm:flex-row sm:items-center sm:gap-4" onClick={() => toggle(a.id)}>
                      <span className="min-w-0 flex-1">
                        <span className="block font-medium">{a.name}</span>
                        <span className="block text-xs text-muted-foreground">
                          {[a.class_label, `bought ${formatDay(a.acquired_on)}`, a.expense_number ? `bill ${a.expense_number}${a.supplier ? ` from ${a.supplier}` : ''}` : 'owned before the books',
                            a.method === 'wdv' ? `WDV ${Number(a.rate)}%` : `SLM ${Number(a.useful_life_years)} years`, a.project,
                            a.disposed_on ? `sold ${formatDay(a.disposed_on)} for ${rupees(a.disposal_value)}` : null].filter(Boolean).join(' · ')}
                        </span>
                      </span>
                      <span className="text-right tabular-nums">
                        <span className="block font-semibold">{a.status === 'sold' ? 'Sold' : rupees(a.value)}</span>
                        <span className="block text-xs text-muted-foreground">cost {rupees(a.cost)}</span>
                      </span>
                    </button>
                    {open === a.id && <AssetDetail asset={a} onEdit={() => setEditing(a)} onSell={() => setSelling(a)} />}
                  </li>
                ))}
              </ul>
            </DprSection>
          ))}
        </>
      )}
      {editing && d && <AssetEditor asset={editing === 'new' ? null : editing} register={d} onClose={() => setEditing(null)} />}
      <SellDialog asset={selling} onClose={() => setSelling(null)} />
    </div>
  )
}

function AssetDetail({ asset, onEdit, onSell }: { asset: FixedAsset; onEdit: () => void; onSell: () => void }) {
  const toast = useToast()
  const qc = useQueryClient()
  const remove = useMutation({
    mutationFn: () => deleteAsset(asset.id),
    onSuccess: () => { toast.success('Taken out of the register'); qc.invalidateQueries({ queryKey: ['accounts'] }) },
    onError: (err: unknown) => toast.error('Not removed', apiErrorMessage(err)),
  })
  const unsell = useMutation({
    mutationFn: () => disposeAsset(asset.id, null, null),
    onSuccess: () => { toast.success('Back in use'); qc.invalidateQueries({ queryKey: ['accounts'] }) },
    onError: (err: unknown) => toast.error('Not changed', apiErrorMessage(err)),
  })
  return (
    <div className="mt-2 flex flex-col gap-2 rounded-lg bg-muted/40 p-3">
      <table className="w-full text-xs tabular-nums">
        <thead className="text-muted-foreground">
          <tr><th className="text-left font-normal">Year</th><th className="text-right font-normal">Opening</th><th className="text-right font-normal">Depreciation</th><th className="text-right font-normal">Closing</th><th className="text-right font-normal" /></tr>
        </thead>
        <tbody>
          {asset.years.map((y) => (
            <tr key={y.financial_year}>
              <td>{y.financial_year}</td>
              <td className="text-right">{rupees(y.opening)}</td>
              <td className="text-right">{rupees(y.depreciation)}</td>
              <td className="text-right">{rupees(y.closing)}</td>
              <td className={cn('text-right', y.posted ? 'text-success' : 'text-muted-foreground')}>{y.posted ? 'posted' : `on ${formatDay(y.post_on)}`}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="flex flex-wrap gap-1.5">
        <Button size="sm" variant="outline" onClick={onEdit}>Change</Button>
        {asset.status === 'in_use' ? (
          <Button size="sm" variant="outline" onClick={onSell}>Sold or scrapped</Button>
        ) : (
          <Button size="sm" variant="outline" disabled={unsell.isPending} onClick={() => unsell.mutate()}>Take the sale back</Button>
        )}
        <Button size="sm" variant="ghost" className="text-muted-foreground" disabled={remove.isPending} onClick={() => remove.mutate()}>Remove from the register</Button>
      </div>
    </div>
  )
}

function AssetEditor({ asset, register, onClose }: { asset: FixedAsset | null; register: AssetRegister; onClose: () => void }) {
  const toast = useToast()
  const qc = useQueryClient()
  const bills = useQuery({ queryKey: ['accounts', 'asset-bills'], queryFn: fetchAssetBills })
  const projects = useQuery({ queryKey: ['scope-projects'], queryFn: fetchProjects, staleTime: 60_000 })
  const [from, setFrom] = React.useState<'bill' | 'before'>(asset ? (asset.expense_id ? 'bill' : 'before') : 'bill')
  const [f, setF] = React.useState<AssetInput>(() => asset ? {
    name: asset.name, asset_class: asset.asset_class, cost: String(Number(asset.cost)), acquired_on: asset.acquired_on,
    put_to_use_on: asset.put_to_use_on, method: asset.method, rate: asset.rate ? String(Number(asset.rate)) : null,
    useful_life_years: asset.useful_life_years ? String(Number(asset.useful_life_years)) : null,
    salvage_value: String(Number(asset.salvage_value)), opening_depreciation: String(Number(asset.opening_depreciation)),
    books_from: asset.books_from, expense_id: asset.expense_id, project_id: asset.project_id, site_id: asset.site_id, notes: asset.notes,
  } : { name: '', asset_class: 'plant', cost: '', acquired_on: today(), method: register.method, salvage_value: '0', opening_depreciation: '0' })
  const set = (patch: Partial<AssetInput>) => setF((x) => ({ ...x, ...patch }))
  const defaults = register.class_defaults.find((c) => c.asset_class === f.asset_class)
  const pickBill = (id: string) => {
    const b = bills.data?.bills.find((x) => x.id === id)
    if (!b) return
    set({ expense_id: b.id, cost: String(Number(b.cost)), acquired_on: b.occurred_date, name: f.name || b.description || b.category || 'Asset', project_id: b.project_id, site_id: b.site_id })
  }
  const billOptions = [
    ...(asset?.expense_id ? [{ value: asset.expense_id, label: `${asset.expense_number ?? 'Bill'} · ${rupees(asset.cost)}` }] : []),
    ...(bills.data?.bills ?? []).map((b) => ({ value: b.id, label: `${b.expense_number ?? 'Bill'} · ${formatDay(b.occurred_date)} · ${b.supplier ?? b.category ?? ''} · ${rupees(b.amount)}${b.description ? ` · ${b.description}` : ''}` })),
  ]
  const ready = f.name.trim().length >= 2 && Number(f.cost) > 0 && !!f.acquired_on && (from === 'before' || !!f.expense_id)
  const save = useMutation({
    mutationFn: () => saveAsset({
      ...f,
      expense_id: from === 'bill' ? f.expense_id : null,
      books_from: from === 'before' ? (f.books_from || f.acquired_on) : null,
      opening_depreciation: from === 'before' ? f.opening_depreciation || '0' : '0',
      rate: f.method === 'wdv' ? f.rate || null : null,
      useful_life_years: f.method === 'slm' ? f.useful_life_years || null : null,
      project_id: f.project_id || null,
    }, asset?.id),
    onSuccess: () => {
      toast.success(asset ? 'Asset changed' : 'Asset added', 'The books follow on their own.')
      qc.invalidateQueries({ queryKey: ['accounts'] })
      onClose()
    },
    onError: (err: unknown) => toast.error('Not saved', apiErrorMessage(err)),
  })
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{asset ? asset.name : 'Add an asset'}</DialogTitle>
          <DialogDescription>What it is, what it cost and how it is written down. The depreciation of each year is posted on 31 March.</DialogDescription>
        </DialogHeader>
        <Segmented<'bill' | 'before'> label="Bought" value={from} options={[{ value: 'bill', label: 'From a bill in Expenses' }, { value: 'before', label: 'Owned before Mesiri' }]} onChange={setFrom} />
        {from === 'bill' && (
          <div className="flex flex-col gap-1.5">
            <Label>The bill</Label>
            <Combobox options={billOptions} value={f.expense_id ?? ''} onValueChange={pickBill} placeholder={bills.isLoading ? 'Loading bills…' : 'Pick the purchase bill'} searchPlaceholder="Type a bill number or supplier" emptyText="No confirmed bill of ₹10,000 or more that is not already an asset." />
            <p className="text-xs text-muted-foreground">Its cost moves from the bill's category to the asset; the bill, its supplier and its payment stay as they are.</p>
          </div>
        )}
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5 sm:col-span-2">
            <Label htmlFor="a-name">Name</Label>
            <Input id="a-name" value={f.name} onChange={(e) => set({ name: e.target.value })} placeholder="e.g. JCB 3DX, KL-07-AB-1234" maxLength={160} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>Class</Label>
            <Combobox options={register.class_defaults.map((c) => ({ value: c.asset_class, label: c.label }))} value={f.asset_class} onValueChange={(v) => set({ asset_class: v as AssetClass, rate: null, useful_life_years: null })} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="a-cost">Cost (before GST you claim)</Label>
            <Input id="a-cost" inputMode="decimal" value={f.cost} onChange={(e) => set({ cost: e.target.value.replace(/[^0-9.]/g, '') })} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="a-bought">Bought on</Label>
            <Input id="a-bought" type="date" value={f.acquired_on} onChange={(e) => set({ acquired_on: e.target.value })} className="dark:[color-scheme:dark]" />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="a-use">Put to use on (if later)</Label>
            <Input id="a-use" type="date" value={f.put_to_use_on ?? ''} onChange={(e) => set({ put_to_use_on: e.target.value || null })} className="dark:[color-scheme:dark]" />
          </div>
          {from === 'before' && (
            <>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="a-from">In these books from</Label>
                <Input id="a-from" type="date" value={f.books_from ?? f.acquired_on} onChange={(e) => set({ books_from: e.target.value })} className="dark:[color-scheme:dark]" />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="a-dep">Written off before that year</Label>
                <Input id="a-dep" inputMode="decimal" value={f.opening_depreciation} onChange={(e) => set({ opening_depreciation: e.target.value.replace(/[^0-9.]/g, '') })} />
              </div>
            </>
          )}
          <div className="flex flex-col gap-1.5">
            <Label>Method</Label>
            <Segmented<'wdv' | 'slm'> label="Method" value={(f.method ?? register.method) as 'wdv' | 'slm'} options={[{ value: 'wdv', label: 'WDV' }, { value: 'slm', label: 'SLM' }]} onChange={(m) => set({ method: m })} />
          </div>
          {(f.method ?? register.method) === 'wdv' ? (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="a-rate">Rate % a year</Label>
              <Input id="a-rate" inputMode="decimal" value={f.rate ?? ''} placeholder={String(defaults?.rate ?? '')} onChange={(e) => set({ rate: e.target.value.replace(/[^0-9.]/g, '') || null })} />
            </div>
          ) : (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="a-life">Useful life (years)</Label>
              <Input id="a-life" inputMode="decimal" value={f.useful_life_years ?? ''} placeholder={String(defaults?.life ?? '')} onChange={(e) => set({ useful_life_years: e.target.value.replace(/[^0-9.]/g, '') || null })} />
            </div>
          )}
          <div className="flex flex-col gap-1.5 sm:col-span-2">
            <Label>Project (where it works, for its cost)</Label>
            <Combobox options={[{ value: '', label: 'Head office' }, ...(projects.data ?? []).map((p) => ({ value: p.id, label: p.name }))]} value={f.project_id ?? ''} onValueChange={(v) => set({ project_id: v || null })} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => save.mutate()} disabled={!ready || save.isPending}>{save.isPending ? 'Saving…' : asset ? 'Save' : 'Add asset'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function SellDialog({ asset, onClose }: { asset: FixedAsset | null; onClose: () => void }) {
  const toast = useToast()
  const qc = useQueryClient()
  const [day, setDay] = React.useState(today())
  const [value, setValue] = React.useState('0')
  const act = useMutation({
    mutationFn: () => disposeAsset(asset!.id, day, value || '0'),
    onSuccess: () => { toast.success('Marked sold', 'Its book value is out of the books; what it fetched is to receive.'); qc.invalidateQueries({ queryKey: ['accounts'] }); onClose() },
    onError: (err: unknown) => toast.error('Not saved', apiErrorMessage(err)),
  })
  return (
    <Dialog open={!!asset} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{asset?.name}: sold or scrapped</DialogTitle>
          <DialogDescription>Worth {rupees(asset?.value)} in the books. The difference with what it fetched is a loss or gain; record the money itself in Finance › Money when it comes.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="s-day">On</Label>
            <Input id="s-day" type="date" value={day} onChange={(e) => setDay(e.target.value)} className="dark:[color-scheme:dark]" />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="s-value">Sold for (0: scrapped)</Label>
            <Input id="s-value" inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value.replace(/[^0-9.]/g, ''))} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => act.mutate()} disabled={!day || act.isPending}>{act.isPending ? 'Saving…' : 'Save'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
